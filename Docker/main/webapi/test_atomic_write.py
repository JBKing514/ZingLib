#!/usr/bin/env python3
"""A failed write must not destroy the file it was replacing.

The report's P0 list has one line that is easy to nod at and hard to honour:
"verify that a corrupt sidecar, a full disk, an unavailable permission or an
interrupted process cannot destroy an existing backup". This test attacks the
three files ZingLib rewrites in place -- the sidecar JSON, the folder's
ComicInfo.xml, and the archive's ComicInfo member -- by making the rename fail
half-way and asserting the *previous* bytes are still there, byte for byte.

No database, no server, so it runs both in the image and in a local venv:

    python -m webapi.test_atomic_write
"""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/app")

from webapi.services import atomic_io, gallery_metadata_backup, local_lib_service  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  |  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def tmp_files(directory: Path) -> list[str]:
    """Leftover temp files this helper creates (`.name.XXXX.tmp`)."""
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_plain_write() -> None:
    print("\n--- a normal write replaces the file ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        target = d / "note.json"
        target.write_bytes(b"old")
        atomic_io.atomic_write_bytes(target, b"new")
        check(target.read_bytes() == b"new", "the new bytes land")
        check(not tmp_files(d), "no temp file is left behind", str(tmp_files(d)))


def test_rename_failure_keeps_the_old_file() -> None:
    print("\n--- a failed rename leaves the old file untouched ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        target = d / "note.json"
        target.write_bytes(b"old-and-valid")
        raised = False
        try:
            with patch.object(atomic_io.os, "replace", side_effect=OSError(28, "No space left")):
                atomic_io.atomic_write_bytes(target, b"new")
        except OSError:
            raised = True
        check(raised, "the failure is reported to the caller")
        check(target.read_bytes() == b"old-and-valid", "the original bytes survive")
        check(not tmp_files(d), "the partial temp file is cleaned up", str(tmp_files(d)))


def test_fsync_failure_keeps_the_old_file() -> None:
    print("\n--- a failed fsync leaves the old file untouched ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        target = d / "note.json"
        target.write_bytes(b"old-and-valid")
        raised = False
        try:
            with patch.object(atomic_io.os, "fsync", side_effect=OSError(5, "I/O error")):
                atomic_io.atomic_write_bytes(target, b"new")
        except OSError:
            raised = True
        check(raised, "the failure is reported to the caller")
        check(target.read_bytes() == b"old-and-valid", "the original bytes survive")
        check(not tmp_files(d), "no temp file is left behind", str(tmp_files(d)))


def test_comicinfo_folder() -> None:
    print("\n--- ComicInfo.xml in a gallery folder ---")
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "lib"
        gallery = root / "Gallery"
        gallery.mkdir(parents=True)
        target = gallery / "ComicInfo.xml"
        target.write_text('<?xml version="1.0"?><ComicInfo><Title>Old</Title></ComicInfo>', encoding="utf-8")
        original = target.read_bytes()
        with patch.object(local_lib_service, "LOCAL_LIB_DIR", root):
            ok = local_lib_service.write_comicinfo("Gallery", "New title", ["category:Action"])
            check(ok is True, "the write reports success")
            check(b"New title" in target.read_bytes(), "the new title is on disk")

            # Now make the replacement fail and prove the old file is intact.
            target.write_bytes(original)
            with patch.object(atomic_io.os, "replace", side_effect=OSError(28, "No space left")):
                ok = local_lib_service.write_comicinfo("Gallery", "Never lands", [])
            check(ok is False, "a failed write reports False instead of raising")
            check(target.read_bytes() == original, "the previous ComicInfo.xml is intact")
            check(not tmp_files(gallery), "no temp file is left in the gallery", str(tmp_files(gallery)))


def test_comicinfo_archive() -> None:
    print("\n--- ComicInfo.xml inside a .cbz ---")
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "lib"
        root.mkdir(parents=True)
        book = root / "Book.cbz"
        with zipfile.ZipFile(book, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("001.png", b"\x89PNG-not-really")
            zf.writestr("ComicInfo.xml", '<?xml version="1.0"?><ComicInfo><Title>Old</Title></ComicInfo>')
        original = book.read_bytes()
        with patch.object(local_lib_service, "LOCAL_LIB_DIR", root):
            ok = local_lib_service.write_comicinfo("Book.cbz", "New title", ["category:Action"])
            check(ok is True, "the archive write reports success")
            with zipfile.ZipFile(book, "r") as zf:
                inner = zf.read("ComicInfo.xml").decode("utf-8")
            check("New title" in inner, "the member was rewritten")
            check("001.png" in zipfile.ZipFile(book, "r").namelist(), "the pages survive the rebuild")

            book.write_bytes(original)
            with patch.object(atomic_io.os, "replace", side_effect=OSError(28, "No space left")):
                ok = local_lib_service.write_comicinfo("Book.cbz", "Never lands", [])
            check(ok is False, "a failed archive write reports False")
            check(book.read_bytes() == original, "the previous archive is intact")
            check(not tmp_files(root), "no temp archive is left beside the gallery", str(tmp_files(root)))


def test_sidecar() -> None:
    print("\n--- the per-gallery sidecar ---")
    with tempfile.TemporaryDirectory() as raw:
        meta = Path(raw) / "meta"
        meta.mkdir(parents=True)
        target = meta / "abc_zinglib_metadata.json"
        target.write_text('{"schema":"zinglib.gallery_metadata.v1","kept":true}', encoding="utf-8")
        original = target.read_bytes()
        with patch.object(atomic_io.os, "replace", side_effect=OSError(28, "No space left")):
            try:
                atomic_io.atomic_write_text(target, '{"schema":"zinglib.gallery_metadata.v1","kept":false}')
            except OSError:
                pass
        check(target.read_bytes() == original, "a failed sidecar write keeps the previous backup")
        check(not tmp_files(meta), "no temp sidecar is left behind", str(tmp_files(meta)))


def main() -> int:
    print("=" * 78)
    print("P0: atomic file replacement")
    print("=" * 78)
    test_plain_write()
    test_rename_failure_keeps_the_old_file()
    test_fsync_failure_keeps_the_old_file()
    test_comicinfo_folder()
    test_comicinfo_archive()
    test_sidecar()

    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)}/{CHECKS}")
        for name in FAILS:
            print("  - " + name)
        return 1
    print(f"ALL {CHECKS} CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
