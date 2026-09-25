"""Per-gallery sidecar backup of the data that is expensive to recompute.

Two things in ZingLib cost real compute and cannot be recovered from the library
files themselves:

* the SigLIP vectors (a CPU forward pass over the cover plus a sample of inner
  pages -- ``visual_embedding`` / ``page_visual_embedding``), and
* the reading history (``read_events``).

Everything else can be rebuilt by re-scanning the folders. That is exactly why a
user who moves their library would otherwise also have to carry a dump of
Postgres: the DB is the only place the vectors and the history live.

So every time we finish computing a gallery's vectors -- and every time the user
edits its metadata -- we drop a small JSON sidecar next to the library::

    <LOCAL_LIB_DIR>/.zinglib_meta/<arcid>_zinglib_metadata.json

The sidecar is *write-only* during normal operation. Nothing reads it back except
the explicit, user-triggered restore in :func:`restore_sidecars`. ``.zinglib_meta``
is therefore part of ``SCAN_SKIP_PREFIXES`` -- the scanner and the file manager
must never mistake these files for library content.

What goes in it:

* the visual vectors -- always present, because SigLIP runs on CPU and a
  ``complete`` gallery therefore always has them;
* the text/description vector -- only when the operator configured an LLM. Most
  users never do, and a gallery with no text vector is simply a pure image
  search, which is fine;
* this gallery's read events;
* the ZingLib-only metadata the files cannot carry: the hand-picked title and
  tag ledger, the reading bookmark, the category and the ComicInfo snapshot.

Nothing here is allowed to raise into a caller. A convenience for library
migration must never be able to fail a scan, a metadata edit or an embedding run,
so every public entry point is best-effort and swallows its own errors.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.constants import LOCAL_LIB_DIR
from .db_service import query_rows

# Bumped whenever the payload shape changes. A restore refuses a sidecar whose
# schema it does not know, rather than guessing at the layout.
SIDECAR_SCHEMA = "zinglib.metadata.v1"
SIDECAR_SUFFIX = "_zinglib_metadata.json"
# Dot-prefixed so it is skipped by the scanner and by the upload detector even
# without a SCAN_SKIP_PREFIXES entry; the explicit entry is what keeps the file
# manager's folder listing clean.
META_DIR_NAME = ".zinglib_meta"

SIGLIP_DIM = 1152
TEXT_DIM = 1024
# A gallery read a thousand times is not a gallery whose history we need in
# full; the cap only bounds the file size.
MAX_HISTORY_ROWS = 1000

# --- the cover fingerprint --------------------------------------------------
# An arcid is a hash of the gallery's *path*, so moving the folder invalidates
# every id we hold -- and moving it also breaks the relative-path match. What
# does not change when a folder moves is its content, so the sidecar carries a
# small fingerprint of page 1 (the cover) as a third way to find its gallery.
#
# The header is enough: the first 8 KiB identifies a real image and costs one
# short read per gallery. Hashing the whole cover would mean reading a few
# hundred KB per gallery every time a sidecar is written -- the embedding run and
# the metadata writeback both do this for the entire library.
COVER_HASH_READ_BYTES = 8192
# Which bytes of a large cover to sample, on top of the header. A JPEG's first
# 8 KiB is mostly its header, and two covers edited from the same template could
# share one; the tail keeps the fingerprint honest without a full read.
COVER_HASH_TAIL_BYTES = 4096


def _hash_reader(reader: Any) -> str:
    """Hash an opened binary stream's fingerprint (header + head/tail sample)."""
    try:
        head = reader.read(COVER_HASH_READ_BYTES) or b""
    except Exception:
        return ""
    if not head:
        return ""
    payload = bytearray(head)
    # `seek` needs a real position, so read the tail as "everything after the
    # header" -- for a small cover this is empty, which is fine and keeps the
    # fingerprint a pure function of the file.
    try:
        reader.seek(0, os.SEEK_END)
        size = int(reader.tell() or 0)
        start = max(0, size - COVER_HASH_TAIL_BYTES)
        if start > len(head):
            reader.seek(start, os.SEEK_SET)
            payload.extend(reader.read(COVER_HASH_TAIL_BYTES) or b"")
    except Exception:
        pass
    return hashlib.sha1(bytes(payload)).hexdigest()


def gallery_cover_hash(local_dir: str, *, meta: dict[str, Any] | None = None) -> str:
    """Fingerprint page 1 of a gallery. Never raises. ``""`` when unavailable.

    ``meta`` is the optional sidecar directory override. It exists for the same
    reason ``sidecar_path`` takes one: the test suite redirects the sidecar
    directory to a temp dir, and library lookups have to honour that instead of
    reaching into the user's real ``.zinglib_meta``.
    """
    rel = normalize_rel_path(local_dir)
    if not rel:
        return ""
    try:
        base = LOCAL_LIB_DIR / rel
    except Exception:
        return ""
    try:
        if not base.exists():
            return ""
    except OSError:
        return ""
    try:
        if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
            import zipfile

            with zipfile.ZipFile(base, "r") as zf:
                names = [n for n in zf.namelist() if n.endswith("/") is False and "__MACOSX" not in n]
                # The manifest the reader uses is naturally sorted, matching how
                # page 1 is chosen everywhere else.
                candidates = [
                    n for n in names
                    if Path(n).suffix.lower().lstrip(".") in _COVER_IMAGE_EXTS
                ]
                if not candidates:
                    return ""
                chosen = sorted(candidates, key=_cover_natural_key)[0]
                with zf.open(chosen) as handle:
                    return _hash_reader(handle)
        if base.is_dir():
            files: list[Path] = []
            for p in base.rglob("*"):
                try:
                    if p.is_file() and p.suffix.lower().lstrip(".") in _COVER_IMAGE_EXTS:
                        files.append(p)
                except OSError:
                    continue
            if not files:
                return ""
            files.sort(key=lambda x: _cover_natural_key(x.relative_to(base).as_posix()))
            with files[0].open("rb") as handle:
                return _hash_reader(handle)
    except Exception:
        return ""
    return ""


# Kept local so this module does not import the scanner's constants just for a
# suffix test; they are the same set the library accepts as pages.
_COVER_IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "webp", "gif", "bmp", "avif"})


def _cover_natural_key(name: str) -> tuple:
    """Sort key for page order. Splits digits so page 10 follows page 9."""
    import re as _re

    parts = _re.split(r"(\d+)", str(name or "").lower())
    return tuple(int(p) if p.isdigit() else p for p in parts)

# --- the restore report -----------------------------------------------------
# The report is read by a human in a support thread as often as by a machine, so
# every line answers the same four questions and nobody has to cross-reference a
# counter to work out what happened to a particular gallery: did it come back,
# why or why not, which gallery (the folder the user recognises), and which id.
REPORT_SCHEMA = "zinglib.restore_log.v1"
RESTORE_STATUSES = (
    "restored",   # a backup was applied to a live gallery
    "preview",    # dry run: the very line a real run would write
    "no_backup",  # live gallery with no backup -> still needs recomputing
    "orphan",     # backup whose gallery is not in this library any more
    "duplicate",  # an older backup for a gallery a newer one already covered
    "failed",     # matched, but writing it back raised
    "unreadable",  # backup file could not be parsed
)
# `ok` is "this line is not an error", not "something was written": a gallery
# that legitimately has no backup is information, not a failure.
NEGATIVE_STATUSES = ("failed", "unreadable")
RESTORE_REASONS = {
    "restored": "restored from backup",
    "restored_noop": "already up to date (nothing to write)",
    "preview": "would be restored (dry run)",
    "preview_noop": "already up to date (nothing to write)",
    "no_backup": "no backup file for this gallery: it must be recomputed",
    "orphan": "backup does not belong to any gallery in this library",
    "duplicate": "superseded by a newer backup for the same gallery",
    "unreadable": "backup file could not be read, or has an unknown schema",
    "failed": "restore failed",
}

# --- paths ------------------------------------------------------------------


def meta_dir(*, create: bool = False) -> Path:
    target = LOCAL_LIB_DIR / META_DIR_NAME
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def sidecar_filename(arcid: str) -> str:
    return f"{str(arcid or '').strip()}{SIDECAR_SUFFIX}"


def sidecar_path(arcid: str, *, meta: dict[str, Any] | None = None) -> Path:
    """Absolute path of one gallery's sidecar.

    ``meta`` is an optional override dict carrying ``meta_dir`` -- the test
    suite's way of redirecting the directory without patching the module
    attribute (which every live reference would then bypass).
    """
    return _resolve_meta_dir(meta) / sidecar_filename(arcid)


def _resolve_meta_dir(meta: dict[str, Any] | None) -> Path:
    if isinstance(meta, dict) and isinstance(meta.get("meta_dir"), Path):
        return meta["meta_dir"]
    return meta_dir()


def normalize_rel_path(local_dir: str) -> str:
    """Fold the several spellings a `local_dir` arrives in into one key.

    The DB stores a posix relative path, the sidecar is read back from disk and a
    user may have moved the library between filesystems -- so the match between a
    sidecar and a live gallery is done on this normalized form, never on the raw
    string.
    """
    return str(local_dir or "").replace("\\", "/").strip().strip("/")


def gallery_name(local_dir: str) -> str:
    """What a user calls the gallery: the last segment of the relative path."""
    rel = normalize_rel_path(local_dir)
    return rel.rsplit("/", 1)[-1] if rel else ""


def report_row(
    kind: str,
    *,
    status: str,
    reason: str = "",
    arcid: str = "",
    local_dir: str = "",
    file: str = "",
    ok: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One self-describing line of the restore report.

    A row is rejected if it does not carry a known status, so an added branch
    can never quietly ship a line the reader cannot interpret.
    """
    if status not in RESTORE_STATUSES:
        raise ValueError(f"unknown restore status: {status}")
    rel = normalize_rel_path(local_dir)
    ident = str(arcid or "").strip()
    row: dict[str, Any] = {
        "type": str(kind or status),
        "status": status,
        "ok": (status not in NEGATIVE_STATUSES) if ok is None else bool(ok),
        "reason": str(reason or RESTORE_REASONS.get(status, "") or "").strip(),
        "gallery": gallery_name(rel) or ident,
        "arcid": ident,
        "local_dir": rel,
    }
    if file:
        row["file"] = str(file)
    row.update(extra)
    return row


def vector_literal(vec: list[float]) -> str:
    """Render a python list as the pgvector text literal (``[0.1,0.2]``)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# --- decode helpers ---------------------------------------------------------


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x or "").strip() for x in value if str(x or "").strip()]


def _floats(value: Any) -> list[float]:
    """Coerce a JSON array (or a pgvector text column) into a float list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except Exception:
            return []
    return out


# --- write ------------------------------------------------------------------

# A full-library writeback or embedding run calls `build_payload` once per
# gallery, and each of those would otherwise re-read the first bytes of a cover
# that has not changed. Keyed on the file signature (size + mtime), so an edited
# gallery is re-fingerprinted and a moved one is not.
_cover_hash_cache: dict[str, tuple[tuple[int, int], str]] = {}
_COVER_HASH_CACHE_MAX = 4096


def _cover_signature(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
        return int(st.st_size), int(st.st_mtime_ns)
    except Exception:
        return 0, 0


def _cover_hash_cached(local_dir: str) -> str:
    """`gallery_cover_hash` with a signature-keyed memo. Never raises."""
    rel = normalize_rel_path(local_dir)
    if not rel:
        return ""
    try:
        base = LOCAL_LIB_DIR / rel
        signature = _cover_signature(base)
    except Exception:
        return ""
    hit = _cover_hash_cache.get(rel)
    if isinstance(hit, tuple) and len(hit) == 2 and hit[0] == signature:
        return str(hit[1] or "")
    value = gallery_cover_hash(local_dir)
    if len(_cover_hash_cache) >= _COVER_HASH_CACHE_MAX:
        _cover_hash_cache.clear()
    _cover_hash_cache[rel] = (signature, value)
    return value


def invalidate_cover_hash_cache(local_dir: str = "") -> None:
    """Drop the memo for one gallery, or all of it when ``local_dir`` is "".

    Every path that rewrites the files in a gallery has to call this, for the
    same reason the reader caches do: the memo is keyed on the *path*, so a
    gallery whose pages were replaced in place keeps answering with the
    fingerprint of the pages that are no longer there.
    """
    rel = normalize_rel_path(local_dir)
    if not rel:
        _cover_hash_cache.clear()
        return
    _cover_hash_cache.pop(rel, None)


def _cover_hash_for_match(rel: str) -> str:
    """Adapter for the match index: it hands over a relative path, not a dir.

    A library-wide restore fingerprints every gallery once, so this rides the
    same signature-keyed memo the write path uses -- a second restore in the same
    process re-hashes nothing that has not changed.
    """
    return _cover_hash_cached(rel)


def _read_events_for(arcid: str, limit: int = MAX_HISTORY_ROWS) -> list[dict[str, Any]]:
    rows = query_rows(
        "SELECT read_time, source_file, ingested_at, raw FROM read_events "
        "WHERE arcid = %s ORDER BY read_time DESC LIMIT %s",
        (arcid, int(max(1, limit))),
    )
    out: list[dict[str, Any]] = []
    for row in rows or []:
        out.append(
            {
                "read_time": int(row.get("read_time") or 0),
                "source_file": str(row.get("source_file") or "").strip(),
                "ingested_at": _iso(row.get("ingested_at")),
                "raw": _as_dict(row.get("raw")),
            }
        )
    return out


def build_payload(
    row: dict[str, Any],
    *,
    model_id: str = "",
    cover_hash: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the sidecar body from one ``works`` row.

    ``cover_hash`` lets a caller that already fingerprints the cover (the
    restore's own directory scan) avoid doing it twice; when omitted it is
    computed from ``local_dir``, memoised on the file signature.
    """
    arcid = str(row.get("arcid") or "").strip()
    raw = _as_dict(row.get("raw"))
    user_meta = _as_dict(raw.get("user_meta"))
    cover = _floats(row.get("cover_vec"))
    page = _floats(row.get("page_vec"))
    text_vec = _floats(row.get("text_vec"))

    siglip: dict[str, Any] = {"dim": SIGLIP_DIM, "cover": cover, "page": page}
    model = str(model_id or "").strip()
    if model:
        siglip["model"] = model

    local_dir = normalize_rel_path(str(row.get("local_dir") or ""))
    if cover_hash is None:
        cover_hash = _cover_hash_cached(local_dir)

    payload: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "arcid": arcid,
        # Stored so a restore can follow the gallery even if the DB row (and
        # therefore the arcid, which is a hash of the path) was rebuilt.
        "local_dir": local_dir,
        "written_at": datetime.now(timezone.utc).isoformat(),
        "siglip": siglip,
        "meta": {
            "title": str(user_meta.get("title") or "").strip(),
            "tags": _as_str_list(user_meta.get("tags")),
            "bookmark": raw.get("bookmark"),
            "category": str(_as_dict(raw.get("eh_raw")).get("category") or "").strip(),
            "comicinfo": _as_dict(raw.get("comicinfo")),
        },
    }
    # Only written when page 1 could actually be fingerprinted. A sidecar whose
    # `cover_hash` is "" is not broken -- it just has one fallback fewer, and
    # storing an empty string would make every unfingerprintable gallery match
    # every other one.
    if cover_hash:
        payload["cover_hash"] = str(cover_hash)
    # Only present when an LLM was configured. Absent is a legitimate state: it
    # means "this gallery is searched by image only", not "backup broken".
    if text_vec:
        payload["text"] = {"dim": TEXT_DIM, "vector": text_vec}
    payload["history"] = _read_events_for(arcid)
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    meta_dir(create=True)
    tmp = path.with_name(f"{path.name}.tmp")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def write_sidecar(
    arcid: str,
    *,
    model_id: str = "",
    only_if_exists: bool = False,
    meta: dict[str, Any] | None = None,
) -> bool:
    """Write (or refresh) one gallery's sidecar. Never raises.

    ``only_if_exists`` is what the read-event hook uses: a read must be able to
    keep an existing sidecar's history current, but must never *create* one --
    creation belongs to the embedding run, which is the first moment there is
    something expensive worth protecting.

    ``meta`` overrides the sidecar directory (see :func:`meta_dir`); the test
    suite points it at a temp dir so a round trip cannot touch a real library.
    """
    safe = str(arcid or "").strip()
    if not safe:
        return False
    try:
        if only_if_exists and not sidecar_path(safe, meta=meta).exists():
            return False
        rows = query_rows(
            "SELECT arcid, local_dir, raw, "
            "visual_embedding::text AS cover_vec, "
            "page_visual_embedding::text AS page_vec, "
            "desc_embedding::text AS text_vec "
            "FROM works WHERE arcid = %s LIMIT 1",
            (safe,),
        )
        if not rows:
            return False
        payload = build_payload(rows[0], model_id=model_id, meta=meta)
        # A sidecar means "here is the compute I spent on this gallery". Without
        # a visual vector there is nothing expensive to protect yet -- and
        # writing one anyway would make the restore report claim a gallery is
        # backed up when it still has to be recomputed.
        if not payload["siglip"]["cover"]:
            return False
        _atomic_write(sidecar_path(safe, meta=meta), payload)
        return True
    except Exception:
        return False


# --- restore ----------------------------------------------------------------


def _merge_raw(current: Any, meta: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fold a sidecar's metadata block into ``raw`` key by key.

    Never replaces ``raw`` wholesale -- an earlier iteration of this idea did
    that and silently erased unrelated keys (``raw.bookmark`` among them). Only
    keys that are *missing* on the live row are filled, so a restore can never
    clobber metadata the user has edited since the backup was taken.
    """
    out = _as_dict(current)
    changed = False

    user_meta = _as_dict(out.get("user_meta"))
    if str(meta.get("title") or "").strip() and not str(user_meta.get("title") or "").strip():
        user_meta["title"] = str(meta.get("title") or "").strip()
        changed = True
    ledger = _as_str_list(user_meta.get("tags"))
    for tag in _as_str_list(meta.get("tags")):
        if tag not in ledger:
            ledger.append(tag)
            changed = True
    if ledger:
        user_meta["tags"] = ledger
    if user_meta:
        out["user_meta"] = user_meta

    if not out.get("bookmark") and meta.get("bookmark"):
        out["bookmark"] = meta["bookmark"]
        changed = True
    if not _as_dict(out.get("comicinfo")) and _as_dict(meta.get("comicinfo")):
        out["comicinfo"] = meta["comicinfo"]
        changed = True
    category = str(meta.get("category") or "").strip()
    eh_raw = _as_dict(out.get("eh_raw"))
    if category and not str(eh_raw.get("category") or "").strip():
        eh_raw["category"] = category
        out["eh_raw"] = eh_raw
        changed = True
    return out, changed


def _history_count(arcid: str) -> int:
    rows = query_rows("SELECT count(*)::bigint AS n FROM read_events WHERE arcid = %s", (arcid,))
    return int((rows[0] or {}).get("n") or 0) if rows else 0


def _restore_one(arcid: str, payload: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """Restore one matched gallery. Returns the per-gallery counters."""
    rows = query_rows(
        "SELECT visual_embedding IS NULL AS cover_missing, "
        "page_visual_embedding IS NULL AS page_missing, "
        "desc_embedding IS NULL AS text_missing, raw "
        "FROM works WHERE arcid = %s LIMIT 1",
        (arcid,),
    )
    if not rows:
        return {"ok": False, "reason": "work not found"}
    row = rows[0]

    siglip = _as_dict(payload.get("siglip"))
    cover = _floats(siglip.get("cover"))
    page = _floats(siglip.get("page"))
    text_vec = _floats(_as_dict(payload.get("text")).get("vector"))

    # Fill only what is missing: a live vector is newer than the backup by
    # definition, so overwriting it would trade real compute for stale compute.
    set_cover = cover if (row.get("cover_missing") and cover) else []
    set_page = page if (row.get("page_missing") and page) else []
    set_text = text_vec if (row.get("text_missing") and text_vec) else []

    merged_raw, raw_changed = _merge_raw(row.get("raw"), _as_dict(payload.get("meta")))

    events: list[dict[str, Any]] = [
        e for e in (payload.get("history") or []) if isinstance(e, dict)
    ]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "visual": 1 if (set_cover or set_page) else 0,
            "text": 1 if set_text else 0,
            "history": len(events),
            "meta": 1 if raw_changed else 0,
        }

    sets: list[str] = []
    params: list[Any] = []
    if set_cover:
        sets.append("visual_embedding = %s::vector")
        params.append(vector_literal(set_cover))
    if set_page:
        sets.append("page_visual_embedding = %s::vector")
        params.append(vector_literal(set_page))
    if set_text:
        sets.append("desc_embedding = %s::vector")
        params.append(vector_literal(set_text))
    if raw_changed:
        sets.append("raw = %s::jsonb")
        params.append(json.dumps(merged_raw, ensure_ascii=False))

    cover_present = bool(set_cover) or not bool(row.get("cover_missing"))
    page_present = bool(set_page) or not bool(row.get("page_missing"))
    if cover_present and page_present:
        sets.append("cover_embedding_status = 'complete'")

    if sets:
        params.append(arcid)
        query_rows(f"UPDATE works SET {', '.join(sets)} WHERE arcid = %s", tuple(params))

    # The insert is idempotent by construction (UNIQUE(arcid, read_time)), which
    # is what makes it safe to restore the same sidecar twice.
    before = _history_count(arcid)
    for event in events:
        try:
            read_time = int(event.get("read_time") or 0)
        except Exception:
            continue
        if read_time <= 0:
            continue
        query_rows(
            "INSERT INTO read_events (arcid, read_time, source_file, raw) "
            "VALUES (%s, %s, %s, %s::jsonb) "
            "ON CONFLICT (arcid, read_time) DO NOTHING",
            (
                arcid,
                read_time,
                str(event.get("source_file") or "zinglib-restore"),
                json.dumps(_as_dict(event.get("raw")), ensure_ascii=False),
            ),
        )
    added = max(0, _history_count(arcid) - before)

    return {
        "ok": True,
        "visual": 1 if (set_cover or set_page) else 0,
        "text": 1 if set_text else 0,
        "history": int(added),
        "meta": 1 if raw_changed else 0,
    }


def _read_sidecar(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("schema") or "") != SIDECAR_SCHEMA:
        return None
    return data


# --- matching a sidecar to a live gallery -----------------------------------
#
# An arcid is a hash of the gallery's *path*, so the moment a user renames or
# moves a folder every id we hold is stale -- and a move breaks the relative path
# as well. Four tiers, strongest first, because each is a progressively weaker
# claim about identity and a weaker tier must never override a stronger one:
#
#   1. relative path   -- exact. What the DB and the sidecar both record.
#   2. arcid           -- exact, and survives a *rename of a parent* (the arcid
#                         is stale, but a row rebuilt from the same path gets the
#                         same hash back).
#   3. cover fingerprint -- the folder moved. Content is the only surviving
#                         identity; page 1 is what we fingerprint.
#   4. unique folder name -- the last resort. Only when exactly one live gallery
#                         carries that name, so it can never pick arbitrarily.
#
# Tiers 1 and 2 are "the sidecar names something we can point at". Tiers 3 and 4
# are inferences, and they are the ones that have to be conservative.
MATCH_BY_PATH = "path"
MATCH_BY_ARCDID = "arcid"
MATCH_BY_COVER_HASH = "cover_hash"
MATCH_BY_NAME = "gallery_name"
MATCH_TIERS = (MATCH_BY_PATH, MATCH_BY_ARCDID, MATCH_BY_COVER_HASH, MATCH_BY_NAME)


def build_match_index(
    live: list[dict[str, Any]],
    *,
    cover_hash_of: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Index the live library for :func:`resolve_sidecar_match`.

    ``cover_hash_of`` is injected rather than called directly so a caller can
    supply a pre-computed map (the restore fingerprints the whole library once)
    and so the pure lookup logic stays testable without touching a filesystem.
    """
    by_rel: dict[str, str] = {}
    by_arcid: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    rel_of: dict[str, str] = {}
    for row in live or []:
        arcid = str(row.get("arcid") or "").strip()
        if not arcid:
            continue
        rel = normalize_rel_path(str(row.get("local_dir") or ""))
        by_arcid[arcid] = rel
        rel_of[arcid] = rel
        if rel:
            by_rel[rel] = arcid
        name = gallery_name(rel)
        if name:
            by_name.setdefault(name, []).append(arcid)

    by_hash: dict[str, str] = {}
    if callable(cover_hash_of):
        for arcid, rel in rel_of.items():
            if not rel:
                continue
            digest = str(cover_hash_of(rel) or "").strip()
            if not digest:
                continue
            # Two galleries can hold byte-identical covers (a repack, a duplicate
            # download). An ambiguous fingerprint identifies neither, so it is
            # dropped rather than resolved to whichever came first.
            if digest in by_hash:
                by_hash[digest] = ""
            else:
                by_hash[digest] = arcid
    return {
        "by_rel": by_rel,
        "by_arcid": by_arcid,
        "by_name": by_name,
        "by_hash": by_hash,
        "rel_of": rel_of,
    }


def resolve_sidecar_match(
    index: dict[str, Any],
    *,
    sidecar_rel: str,
    sidecar_arcid: str,
    sidecar_cover_hash: str = "",
) -> tuple[str, str]:
    """Return ``(arcid, tier)`` for one sidecar. ``("", "")`` when unmatched."""
    rel = normalize_rel_path(sidecar_rel)
    arcid = str(sidecar_arcid or "").strip()
    digest = str(sidecar_cover_hash or "").strip()

    target = str((index.get("by_rel") or {}).get(rel) or "")
    if target:
        return target, MATCH_BY_PATH

    if arcid and arcid in (index.get("by_arcid") or {}):
        return arcid, MATCH_BY_ARCDID

    if digest:
        target = str((index.get("by_hash") or {}).get(digest) or "")
        if target:
            return target, MATCH_BY_COVER_HASH

    # Last resort, and the only tier that is allowed to guess: a name match is
    # accepted solely when the name is unique in the live library. Two folders
    # called "Chapter 1" must not let one gallery's vectors land on the other.
    name = gallery_name(rel)
    if name:
        candidates = (index.get("by_name") or {}).get(name) or []
        if len(candidates) == 1:
            return str(candidates[0]), MATCH_BY_NAME
    return "", ""


def restore_sidecars(
    *,
    dry_run: bool = False,
    on_restored: Callable[[str], None] | None = None,
    detail_sink: Callable[[str, dict[str, Any]], None] | None = None,
    include_details: bool = True,
    meta: dict[str, Any] | None = None,
    cover_hash_of: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Replay every sidecar back into the database.

    Deliberately manual: this only ever runs because a user pressed a button, so
    it can afford to be thorough about *reporting* rather than clever. What a
    caller needs to show is the honest denominator -- every gallery in the live
    library, of which some were matched and restored and some carry no sidecar at
    all. The latter are the ones that will have to be recomputed.

    ``meta`` and ``cover_hash_of`` exist for the test suite: the first redirects
    the sidecar directory, the second replaces the cover fingerprint so a round
    trip can be exercised without real image files.
    """
    report: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "report_schema": REPORT_SCHEMA,
        "meta_dir": str(_resolve_meta_dir(meta)),
        "sidecars": 0,
        "matched": 0,
        "restored": 0,
        "visual_restored": 0,
        "text_restored": 0,
        "history_rows": 0,
        "meta_restored": 0,
        "total_galleries": 0,
        "no_sidecar_count": 0,
        "orphan_count": 0,
        "unreadable_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
        # How many galleries were found by something weaker than an exact id.
        # A move that lands on the wrong gallery would otherwise be invisible:
        # the counters would look exactly like a clean run.
        "matched_by_tier": {tier: 0 for tier in MATCH_TIERS},
    }
    if include_details:
        # Only present when asked for. A compact response must not carry an empty
        # list next to a non-zero count: `failed: []` reads like "nothing failed".
        report.update(
            {
                "no_sidecar": [],
                "orphan_sidecars": [],
                "unreadable": [],
                "duplicate_sidecars": [],
                "failed": [],
            }
        )

    try:
        live = query_rows(
            "SELECT arcid, local_dir FROM works "
            "WHERE source = 'local' AND COALESCE(local_dir, '') <> ''"
        )
    except Exception as exc:  # noqa: BLE001 - the message is shown to the user
        report["ok"] = False
        report["error"] = f"database unavailable: {exc}"
        return report

    fingerprint = cover_hash_of if callable(cover_hash_of) else _cover_hash_for_match
    index = build_match_index(live or [], cover_hash_of=fingerprint)
    by_arcid: dict[str, str] = index["by_arcid"]
    report["total_galleries"] = len(by_arcid)

    files: list[Path] = []
    dirp = _resolve_meta_dir(meta)
    if dirp.is_dir():
        try:
            files = sorted(
                dirp.glob(f"*{SIDECAR_SUFFIX}"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["error"] = f"cannot list sidecars: {exc}"
            return report
    report["sidecars"] = len(files)

    # Two bookkeeping sets, and the distinction matters: `covered` is every live
    # gallery a sidecar points at (used for the "missing metadata" denominator),
    # while `restored_arcids` is only what a real run actually wrote.
    covered: set[str] = set()
    restored_arcids: set[str] = set()

    if detail_sink is not None:
        # A header, so a file found months later explains itself.
        detail_sink(
            "restore_report",
            report_row(
                "restore_report",
                status="preview" if dry_run else "restored",
                reason=(
                    "dry run: nothing was written"
                    if dry_run
                    else "one line per gallery follows"
                ),
                ok=True,
                schema=REPORT_SCHEMA,
                started_at=datetime.now(timezone.utc).isoformat(),
                dry_run=bool(dry_run),
                library_galleries=report["total_galleries"],
                sidecar_files=report["sidecars"],
            ),
        )

    for path in files:
        payload = _read_sidecar(path)
        if payload is None:
            item = report_row(
                "unreadable", status="unreadable", file=path.name
            )
            if include_details:
                report["unreadable"].append(item)
            report["unreadable_count"] += 1
            if detail_sink is not None:
                detail_sink("unreadable", item)
            continue

        sidecar_arcid = str(payload.get("arcid") or "").strip()
        sidecar_rel = normalize_rel_path(str(payload.get("local_dir") or ""))
        sidecar_cover_hash = str(payload.get("cover_hash") or "").strip()

        # Four tiers, strongest first: relative path, then the exact arcid, then
        # the cover fingerprint, then a unique folder name. See
        # `resolve_sidecar_match` for why the order is what it is.
        target, tier = resolve_sidecar_match(
            index,
            sidecar_rel=sidecar_rel,
            sidecar_arcid=sidecar_arcid,
            sidecar_cover_hash=sidecar_cover_hash,
        )
        if not target:
            item = report_row(
                "orphan_sidecar",
                status="orphan",
                arcid=sidecar_arcid,
                local_dir=sidecar_rel,
                file=path.name,
                reason=(
                    RESTORE_REASONS["orphan"]
                    if not (sidecar_rel or sidecar_arcid)
                    else
                    "backup matches no gallery by path, arcid, cover hash or unique name"
                ),
            )
            if include_details:
                report["orphan_sidecars"].append(item)
            report["orphan_count"] += 1
            if detail_sink is not None:
                detail_sink("orphan_sidecar", item)
            continue

        # A moved gallery can temporarily have both its old-path sidecar and a
        # freshly written one. Files are newest-first, so use one backup per
        # live gallery and report the older copies instead of inflating matched.
        if target in covered:
            item = report_row(
                "duplicate_sidecar",
                status="duplicate",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
                match=tier,
            )
            if include_details:
                report["duplicate_sidecars"].append(item)
            report["duplicate_count"] += 1
            if detail_sink is not None:
                detail_sink("duplicate_sidecar", item)
            continue

        report["matched"] += 1
        report["matched_by_tier"][tier] = int(report["matched_by_tier"].get(tier) or 0) + 1
        covered.add(target)
        try:
            outcome = _restore_one(target, payload, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad gallery must not stop the rest
            item = report_row(
                "failed",
                status="failed",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
                reason=str(exc),
            )
            if include_details:
                report["failed"].append(item)
            report["failed_count"] += 1
            if detail_sink is not None:
                detail_sink("failed", item)
            continue
        if not outcome.get("ok"):
            item = report_row(
                "failed",
                status="failed",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
                reason=str(outcome.get("reason") or RESTORE_REASONS["failed"]),
            )
            if include_details:
                report["failed"].append(item)
            report["failed_count"] += 1
            if detail_sink is not None:
                detail_sink("failed", item)
            continue

        report["visual_restored"] += int(outcome.get("visual") or 0)
        report["text_restored"] += int(outcome.get("text") or 0)
        report["history_rows"] += int(outcome.get("history") or 0)
        report["meta_restored"] += int(outcome.get("meta") or 0)
        if not dry_run:
            report["restored"] += 1
            restored_arcids.add(target)
            if on_restored is not None:
                try:
                    on_restored(target)
                except Exception:
                    pass
        if detail_sink is not None:
            wrote = int(outcome.get("visual") or 0) + int(outcome.get("text") or 0)
            wrote += int(outcome.get("history") or 0) + int(outcome.get("meta") or 0)
            # `match` and `sidecar_dir` say *how* this backup was found. A restore
            # that fell back to the cover fingerprint or a folder name is a
            # different event from an exact-id restore and must be auditable as
            # one -- the counters alone would look identical.
            detail_sink(
                "matched",
                report_row(
                    "matched",
                    status="preview" if dry_run else "restored",
                    reason=RESTORE_REASONS[
                        ("preview_noop" if dry_run else "restored_noop")
                        if not wrote
                        else ("preview" if dry_run else "restored")
                    ],
                    arcid=target,
                    local_dir=by_arcid.get(target, ""),
                    file=path.name,
                    match=tier,
                    sidecar_dir=sidecar_rel,
                    **outcome,
                ),
            )

    missing = [
        report_row(
            "no_sidecar",
            status="no_backup",
            arcid=arcid,
            local_dir=rel,
        )
        for arcid, rel in by_arcid.items()
        if arcid not in covered
    ]
    report["no_sidecar_count"] = len(missing)
    if include_details:
        report["no_sidecar"] = missing
        report["restored_arcids"] = sorted(restored_arcids)
    if detail_sink is not None:
        for item in missing:
            detail_sink("no_sidecar", item)

    # The one-line answer for a human who reads nothing else, plus a flag so a
    # caller never has to infer "did anything go wrong" from arithmetic.
    report["had_failures"] = report["failed_count"] > 0
    report["summary"] = (
        f"{report['restored']} restored, {report['matched']} matched, "
        f"{report['no_sidecar_count']} without backup, "
        f"{report['orphan_count']} orphan, {report['duplicate_count']} duplicate, "
        f"{report['failed_count']} failed, {report['unreadable_count']} unreadable"
    )
    if detail_sink is not None:
        detail_sink("summary", {"type": "summary", **report})
    return report
