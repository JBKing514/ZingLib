"""Gallery detection for the local-library upload flow.

The upload feature used to swallow whatever the browser handed it: one POST with
every file of a parent folder, a hard 1000-file ceiling, and no idea which of
those files belonged together. Bulk-importing a folder tree that way is both
fragile (one oversized folder fails the whole request) and opaque (the user
cannot see what the container decided to ingest).

This module replaces that with a two-phase flow:

1. **Stage** -- the browser uploads the picked/dropped files into a staging
   directory under the local library. Nothing is ingested yet.
2. **Inspect** -- :func:`inspect_staged_galleries` walks the staged tree and
   identifies the gallery units inside it, so the UI can show an editable list
   (name, detected page count, first-page thumbnail) *before* anything is
   committed.

Detection rules (mirroring what ``scan_local_lib`` will later ingest):

* **folder gallery** -- a directory with *no sub-directories*, whose files are
  *all* images, plus an optional ``ComicInfo.xml``. A directory holding a mix of
  images and other files, or one that itself contains sub-directories, is not a
  leaf gallery: its children are examined instead, so a parent folder holding
  many independent galleries yields many entries rather than one.
* **archive gallery** -- a ``.zip`` / ``.cbz`` (and ``.cbr``, counted for the
  listing although the ingest pipeline treats it as an opaque blob), provided
  the archive actually contains image members.

Every entry reports the page count it detected, which is what the per-gallery
progress bar counts against ("0/50P").

The module is deliberately read-only and offline: it stats/inspects already
staged files and never touches the network or the database.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Any

from ..core.constants import LOCAL_LIB_DIR
from .local_lib_service import (
    IMAGE_EXTS,
    _is_allowed_image,
    _natural_sort_key,
    _safe_join_local_dir,
)

# Archive extensions the *listing* recognises. `.zip`/`.cbz` are what the ingest
# pipeline can actually page through; `.cbr` is a RAR container that the reader
# has no decompressor for, so it is surfaced as a candidate with an explicit
# ``ingestable: false`` flag instead of being silently dropped -- the user gets
# to see that something was found and why it will not be read.
ARCHIVE_EXTS: dict[str, str] = {
    ".zip": "zip",
    ".cbz": "zip",
    ".cbr": "rar",
}
INGESTABLE_ARCHIVE_EXTS = {".zip", ".cbz"}

COMICINFO_NAMES = {"comicinfo.xml"}

# The staging area lives next to the galleries it will become, so a staged file
# never has to be copied across filesystems when the import commits. It is
# registered in ``SCAN_SKIP_PREFIXES`` (see ``local_lib_service``) so the library
# scanner ignores it: a staged-but-unreviewed upload must never be ingested.
STAGING_DIR_NAME = ".staging"

# Guard rails for the inspection walk. A parent folder holding thousands of
# galleries is a legitimate import; an adversarial or accidental symlink loop is
# not, so the walk is depth-bounded and explicitly does not follow links.
MAX_WALK_DEPTH = 12

# Upper bound on the page count of a *single* gallery, not of an upload.
#
# The old flow bounded a whole request (1000 files for an entire mother folder),
# so a dozen galleries sharing that budget failed as soon as their pages added
# up. Since one gallery is now staged, reviewed and committed on its own, the
# budget applies per gallery and can afford to be generous: 10000 pages covers
# any realistic doujinshi/manga collection volume while still refusing an
# obviously bogus count. Overflow is reported per gallery, so one oversized
# volume never blocks its siblings.
MAX_GALLERY_PAGES = 10000


def check_gallery_pages(page_count: int, *, name: str = "") -> None:
    """Raise ``ValueError`` when one gallery exceeds the per-gallery page cap.

    Called on the commit path so the limit is enforced by the server rather
    than trusted from the client, and phrased with the gallery name so the user
    knows which volume to split or drop.
    """
    try:
        n = int(page_count or 0)
    except Exception:
        n = 0
    if n > MAX_GALLERY_PAGES:
        label = f" [{name}]" if name else ""
        raise ValueError(
            f"gallery{label} has {n} pages, over the {MAX_GALLERY_PAGES}-page per-gallery limit"
        )


def staging_root() -> Path:
    """Directory every upload is staged under (``local_lib/.staging``)."""
    return _safe_join_local_dir(STAGING_DIR_NAME)


def new_staging_id() -> str:
    """A fresh, collision-free staging batch id."""
    import uuid

    return uuid.uuid4().hex


def stage_dir_for(batch_id: str) -> Path:
    """Absolute staging directory for ``batch_id``, validated against the root.

    Raises ``ValueError`` for anything that is not a plain hex token, which
    keeps a caller-supplied id from escaping the staging root.
    """
    safe = str(batch_id or "").strip()
    if not safe or not all(ch in "0123456789abcdef" for ch in safe.lower()):
        raise ValueError("invalid staging id")
    batch = staging_root() / safe
    root = staging_root().resolve()
    resolved = batch.resolve()
    if os.path.commonpath([str(root), str(resolved)]) != str(root):
        raise ValueError("invalid staging id")
    return batch


def _archive_image_members(path: Path) -> tuple[list[str], bool]:
    """``(image_members, readable)`` for a zip/cbz.

    ``readable`` is False when the container could not be opened at all. A
    ``.cbr`` is a RAR file and there is no stdlib reader for it, so it always
    comes back unreadable -- the caller reports it as a found-but-unusable
    gallery rather than quietly dropping a file the user explicitly dropped in.
    """
    suffix = path.suffix.lower()
    if suffix not in INGESTABLE_ARCHIVE_EXTS:
        return [], False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names: list[str] = []
            for name in zf.namelist():
                if name.endswith("/") or "__MACOSX" in name:
                    continue
                if Path(name).suffix.lower() in IMAGE_EXTS:
                    names.append(name)
            names.sort(key=_natural_sort_key)
            return names, True
    except Exception:
        return [], False


def _archive_has_comicinfo(path: Path) -> bool:
    if path.suffix.lower() not in INGESTABLE_ARCHIVE_EXTS:
        return False
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return any(Path(n).name.lower() in COMICINFO_NAMES for n in zf.namelist())
    except Exception:
        return False


def _archive_entry(f: Path) -> dict[str, Any] | None:
    """Build a gallery entry for an archive file, or None to skip it.

    Skipped only when we could read the container and it held neither images nor
    ComicInfo -- an unreadable container is always surfaced, flagged
    ``ingestable: false``, so the user can see it and act on it.
    """
    suffix = f.suffix.lower()
    members, readable = _archive_image_members(f)
    has_ci = _archive_has_comicinfo(f)
    if readable and not members and not has_ci:
        # A readable archive with no images and no ComicInfo is somebody's
        # document bundle that the folder dialog happened to sweep up.
        return None
    ingestable = suffix in INGESTABLE_ARCHIVE_EXTS and bool(members)
    return _gallery_entry(
        rel_path="",  # filled in by the caller, which knows the walk root
        name=f.stem or f.name,
        kind="zip" if suffix in INGESTABLE_ARCHIVE_EXTS else "rar",
        page_count=len(members),
        has_comicinfo=has_ci,
        ingestable=ingestable,
        first_page="",
    )


def _leaf_folder_verdict(entry: Path) -> tuple[bool, int, bool]:
    """Classify a directory as a leaf gallery.

    Returns ``(is_gallery, image_count, has_comicinfo)``. A directory qualifies
    only when it holds no sub-directories and every one of its files is either an
    image or a ``ComicInfo.xml`` -- exactly the shape ``scan_local_lib`` turns
    into one work.
    """
    try:
        children = list(entry.iterdir())
    except OSError:
        return False, 0, False

    images = 0
    has_comicinfo = False
    for child in children:
        try:
            if child.is_dir():
                # Any sub-directory disqualifies the leaf: the parent is a
                # container for galleries, not a gallery itself.
                return False, 0, False
        except OSError:
            return False, 0, False
        name = child.name.lower()
        if name in COMICINFO_NAMES:
            has_comicinfo = True
            continue
        if _is_allowed_image(child):
            images += 1
            continue
        # A stray non-image file (a .txt readme, a .DS_Store, an .nfo) means
        # this is not a clean image folder. Treat it as "not a gallery" so the
        # caller keeps descending and the user sees the real galleries inside.
        if name.startswith("."):
            continue
        return False, 0, False

    if images <= 0:
        return False, 0, False
    return True, images, has_comicinfo


def _gallery_entry(
    *,
    rel_path: str,
    name: str,
    kind: str,
    page_count: int,
    has_comicinfo: bool,
    ingestable: bool,
    first_page: str,
) -> dict[str, Any]:
    pages = int(page_count)
    return {
        "path": rel_path,
        "name": name,
        "kind": kind,
        "page_count": pages,
        "has_comicinfo": bool(has_comicinfo),
        "ingestable": bool(ingestable),
        "first_page": first_page,
        # Surfaced so the confirm dialog can grey out a volume that is too big
        # instead of letting the commit fail after the user already said yes.
        "over_limit": pages > MAX_GALLERY_PAGES,
    }


def _first_page_rel(entry: Path, is_dir: bool) -> str:
    """Relative path of the first page, used to render the preview thumbnail."""
    if not is_dir:
        return ""
    try:
        candidates = [p for p in entry.iterdir() if p.is_file() and _is_allowed_image(p)]
    except OSError:
        return ""
    if not candidates:
        return ""
    candidates.sort(key=lambda p: _natural_sort_key(p.name))
    return candidates[0].name


def inspect_staged_galleries(
    batch_id: str, *, sub_path: str = "", names_only: bool = False
) -> dict[str, Any]:
    """Walk a staged upload and report the galleries it contains.

    ``sub_path`` narrows the walk to one subtree (used when a staged upload
    contains a parent folder and the UI wants just its children). The result is
    a flat, naturally-sorted list; ordering is stable so a UI that paginates 50
    at a time never sees an entry move between pages.

    ``names_only`` drops ``first_page`` and blanks ``has_comicinfo`` -- the
    confirm dialog only lists gallery names and page counts, so there is no
    reason to pay for per-file enumeration just to fill a field nobody reads.

    This never mutates anything on disk.
    """
    batch = stage_dir_for(batch_id)
    if not batch.exists() or not batch.is_dir():
        raise FileNotFoundError(f"staging batch not found: {batch_id}")

    walk_root = batch
    prefix = ""
    safe_sub = str(sub_path or "").replace("\\", "/").strip().strip("/")
    if safe_sub:
        for part in safe_sub.split("/"):
            if part in {"", ".", ".."}:
                raise ValueError("invalid sub path")
        walk_root = (batch / safe_sub).resolve()
        root_resolved = batch.resolve()
        if os.path.commonpath([str(root_resolved), str(walk_root)]) != str(root_resolved):
            raise ValueError("invalid sub path")
        if not walk_root.exists():
            raise FileNotFoundError(f"staged sub path not found: {safe_sub}")
        prefix = safe_sub

    galleries: list[dict[str, Any]] = []
    scanned_dirs = 0

    def _rel(p: Path) -> str:
        rel = p.relative_to(batch).as_posix()
        return rel

    def _walk(current: Path, depth: int) -> None:
        nonlocal scanned_dirs
        if depth > MAX_WALK_DEPTH:
            return
        try:
            children = sorted(current.iterdir(), key=lambda p: _natural_sort_key(p.name))
        except OSError:
            return

        files: list[Path] = []
        dirs: list[Path] = []
        for child in children:
            try:
                if child.is_symlink():
                    # Never follow links: a staged tree comes from the user's
                    # disk, and a link could point anywhere.
                    continue
                if child.is_dir():
                    dirs.append(child)
                elif child.is_file():
                    files.append(child)
            except OSError:
                continue

        # Leaf folder: qualify it directly.
        verdict_ok, image_count, has_ci = _leaf_folder_verdict(current)
        if verdict_ok:
            scanned_dirs += 1
            galleries.append(
                _gallery_entry(
                    rel_path=_rel(current),
                    name=current.name,
                    kind="folder",
                    page_count=image_count,
                    has_comicinfo=has_ci,
                    ingestable=True,
                    first_page=_first_page_rel(current, True),
                )
            )
            return

        for f in files:
            suffix = f.suffix.lower()
            if suffix not in ARCHIVE_EXTS:
                continue
            entry = _archive_entry(f)
            if entry is None:
                continue
            entry["path"] = _rel(f)
            galleries.append(entry)

        for d in dirs:
            _walk(d, depth + 1)

    _walk(walk_root, 0)

    galleries.sort(key=lambda g: _natural_sort_key(str(g.get("path") or "")))
    if names_only:
        slim: list[dict[str, Any]] = []
        for g in galleries:
            slim.append(
                {
                    "path": g.get("path") or "",
                    "name": g.get("name") or "",
                    "kind": g.get("kind") or "folder",
                    "page_count": int(g.get("page_count") or 0),
                    "ingestable": bool(g.get("ingestable")),
                    "over_limit": bool(g.get("over_limit")),
                }
            )
        galleries = slim
    return {
        "ok": True,
        "batch_id": str(batch_id or ""),
        "sub_path": prefix,
        "root": str(batch),
        "gallery_count": len(galleries),
        "leaf_dirs_scanned": int(scanned_dirs),
        "max_gallery_pages": MAX_GALLERY_PAGES,
        "galleries": galleries,
    }


def inspect_local_dir(local_dir: str) -> dict[str, Any]:
    """Inspect an already-ingested local library directory with the same rules.

    Used by the settings-side tooling so "what would be detected as a gallery"
    can be answered for a library that was not uploaded through the staging
    flow. Read-only.
    """
    base = _safe_join_local_dir(local_dir)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"local dir not found: {local_dir}")
    rel_base = str(local_dir or "").replace("\\", "/").strip().strip("/")
    galleries: list[dict[str, Any]] = []

    for current, dirs, files in os.walk(base):
        cur = Path(current)
        # Prune dotted directories (thumb caches, staging leftovers).
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        verdict_ok, image_count, has_ci = _leaf_folder_verdict(cur)
        if verdict_ok:
            rel = cur.relative_to(base).as_posix()
            rel_path = rel if rel != "." else ""
            full = f"{rel_base}/{rel_path}".strip("/") if rel_base else rel_path
            galleries.append(
                _gallery_entry(
                    rel_path=full,
                    name=cur.name,
                    kind="folder",
                    page_count=image_count,
                    has_comicinfo=has_ci,
                    ingestable=True,
                    first_page=_first_page_rel(cur, True),
                )
            )
            dirs[:] = []
            continue
        for name in files:
            f = cur / name
            suffix = f.suffix.lower()
            if suffix not in ARCHIVE_EXTS:
                continue
            entry = _archive_entry(f)
            if entry is None:
                continue
            rel = f.relative_to(base).as_posix()
            entry["path"] = f"{rel_base}/{rel}".strip("/") if rel_base else rel
            galleries.append(entry)

    galleries.sort(key=lambda g: _natural_sort_key(str(g.get("path") or "")))
    return {
        "ok": True,
        "root": str(base),
        "gallery_count": len(galleries),
        "galleries": galleries,
    }
