"""Offline unit test for the staging gallery detector.

The detector decides what the user sees as an importable gallery, so its
contract is pinned here without a database, a container, or a browser:

* a folder leaf (no sub-dirs, all images, optional ComicInfo.xml) is a gallery;
* a parent folder holding many galleries yields many entries, not one;
* a folder mixing images with other payloads is *not* a gallery (its children
  get examined instead) and neither is a folder of sub-directories;
* .zip/.cbz report their image-member count; .cbr is listed but flagged
  non-ingestable because the reader has no RAR decompressor;
* symlinks are never followed and the walk is depth-bounded.

The test redirects ``LOCAL_LIB_DIR`` into a temp directory *before* importing the
backend, because both ``core.constants`` and the service bind it at import time.

Run directly:  python test_upload_gallery_detect.py
As a module:   python -m webapi.test_upload_gallery_detect
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

_LIB = Path(tempfile.mkdtemp(prefix="zinglib-upload-lib-"))
_RUNTIME = Path(tempfile.mkdtemp(prefix="zinglib-upload-rt-"))
os.environ["DATA_UI_LOCAL_LIB_DIR"] = str(_LIB)
os.environ["DATA_UI_RUNTIME_DIR"] = str(_RUNTIME)
atexit.register(lambda: shutil.rmtree(_LIB, ignore_errors=True))
atexit.register(lambda: shutil.rmtree(_RUNTIME, ignore_errors=True))

from webapi.services import local_upload_service as up  # noqa: E402


def _img(path: Path, payload: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _zip_with(path: Path, members: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name in members:
            zf.writestr(name, b"img")


def _fresh_batch() -> tuple[str, Path]:
    batch_id = up.new_staging_id()
    d = up.stage_dir_for(batch_id)
    d.mkdir(parents=True, exist_ok=True)
    return batch_id, d


def test_leaf_folder_is_one_gallery() -> None:
    batch_id, root = _fresh_batch()
    g = root / "Gallery A"
    for i in range(1, 6):
        _img(g / f"{i:03d}.jpg")
    (g / "ComicInfo.xml").write_text("<ComicInfo/>", encoding="utf-8")

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 1, res
    only = res["galleries"][0]
    assert only["kind"] == "folder", only
    assert only["page_count"] == 5, only
    assert only["has_comicinfo"] is True, only
    assert only["ingestable"] is True, only
    assert only["first_page"] == "001.jpg", only
    assert only["name"] == "Gallery A", only


def test_parent_folder_yields_many_galleries_not_one() -> None:
    """The whole point of the feature: a mother folder is not swallowed whole."""
    batch_id, root = _fresh_batch()
    for idx in range(1, 4):
        g = root / f"Gallery {idx}"
        for page in range(1, idx + 2):
            _img(g / f"{page:03d}.png")
    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 3, res
    counts = sorted(g["page_count"] for g in res["galleries"])
    assert counts == [2, 3, 4], counts


def test_folder_with_subdirs_is_not_a_gallery() -> None:
    batch_id, root = _fresh_batch()
    parent = root / "Parent"
    _img(parent / "loose.jpg")
    _img(parent / "Child" / "a.jpg")
    _img(parent / "Child" / "b.jpg")

    res = up.inspect_staged_galleries(batch_id)
    paths = [g["path"] for g in res["galleries"]]
    assert "Parent" not in paths, paths
    assert "Parent/Child" in paths, paths
    assert res["gallery_count"] == 1, res


def test_folder_with_non_image_payload_is_not_a_gallery() -> None:
    batch_id, root = _fresh_batch()
    g = root / "Mixed"
    _img(g / "a.jpg")
    (g / "notes.txt").write_text("hi", encoding="utf-8")

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 0, res


def test_dotfiles_do_not_disqualify_a_gallery() -> None:
    """.DS_Store and friends ride along with every macOS folder pick."""
    batch_id, root = _fresh_batch()
    g = root / "WithDot"
    _img(g / "a.jpg")
    (g / ".DS_Store").write_bytes(b"\x00")

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 1, res
    assert res["galleries"][0]["page_count"] == 1, res


def test_zip_and_cbz_report_member_counts() -> None:
    batch_id, root = _fresh_batch()
    # `__MACOSX` resource forks and non-image members must not inflate the count.
    _zip_with(root / "pack.zip", ["001.jpg", "002.jpg", "notes.txt", "__MACOSX/._001.jpg"])
    _zip_with(root / "pack2.cbz", ["a.png"])

    res = up.inspect_staged_galleries(batch_id)
    by_name = {g["name"]: g for g in res["galleries"]}
    assert by_name["pack"]["page_count"] == 2, by_name
    assert by_name["pack"]["kind"] == "zip", by_name
    assert by_name["pack2"]["page_count"] == 1, by_name


def test_cbr_is_listed_but_not_ingestable() -> None:
    """`.cbr` is a RAR container the reader cannot open.

    It must still *appear* in the review list (the user dropped it there on
    purpose) with ``ingestable: false`` so the UI can explain why it will not be
    imported, instead of silently vanishing.
    """
    batch_id, root = _fresh_batch()
    (root / "volume.cbr").write_bytes(b"Rar!\x1a\x07\x00 not a real rar")

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 1, res
    only = res["galleries"][0]
    assert only["kind"] == "rar", only
    assert only["ingestable"] is False, only
    assert only["page_count"] == 0, only


def test_unreadable_zip_is_listed_but_not_ingestable() -> None:
    """A corrupt .zip must be surfaced, not swallowed as a 0-page entry."""
    batch_id, root = _fresh_batch()
    (root / "broken.zip").write_bytes(b"PK\x03\x04 truncated garbage")

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 1, res
    only = res["galleries"][0]
    assert only["kind"] == "zip", only
    assert only["ingestable"] is False, only


def test_zip_without_images_is_not_a_gallery() -> None:
    batch_id, root = _fresh_batch()
    _zip_with(root / "docs.zip", ["readme.txt", "changelog.md"])

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 0, res


def test_nested_archives_are_found_inside_a_mother_folder() -> None:
    batch_id, root = _fresh_batch()
    _zip_with(root / "batch" / "one.zip", ["1.jpg", "2.jpg", "3.jpg"])
    _img(root / "batch" / "loose" / "a.jpg")

    res = up.inspect_staged_galleries(batch_id)
    paths = sorted(g["path"] for g in res["galleries"])
    assert paths == ["batch/loose", "batch/one.zip"], paths


def test_symlinks_are_not_followed() -> None:
    batch_id, root = _fresh_batch()
    outside = Path(tempfile.mkdtemp(prefix="zinglib-outside-"))
    atexit.register(lambda: shutil.rmtree(outside, ignore_errors=True))
    _img(outside / "secret" / "a.jpg")
    link = root / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        print("  note: symlinks unsupported here; assertion skipped")
        return

    res = up.inspect_staged_galleries(batch_id)
    assert res["gallery_count"] == 0, res


def test_results_are_stably_ordered_for_pagination() -> None:
    """A 50-per-page UI must never see an entry jump between pages."""
    batch_id, root = _fresh_batch()
    for i in range(1, 13):
        _img(root / f"G{i:02d}" / "001.jpg")

    first = [g["path"] for g in up.inspect_staged_galleries(batch_id)["galleries"]]
    second = [g["path"] for g in up.inspect_staged_galleries(batch_id)["galleries"]]
    assert first == second, (first, second)
    assert first[0] == "G01", first


def test_sub_path_narrows_the_walk() -> None:
    batch_id, root = _fresh_batch()
    _img(root / "outer" / "inner1" / "a.jpg")
    _img(root / "other" / "b.jpg")

    res = up.inspect_staged_galleries(batch_id, sub_path="outer")
    assert res["gallery_count"] == 1, res
    assert res["galleries"][0]["path"] == "outer/inner1", res


def test_bad_staging_id_is_rejected() -> None:
    for bad in ("", "../etc", "not-hex!", "abc/def"):
        try:
            up.stage_dir_for(bad)
        except ValueError:
            continue
        raise AssertionError(f"staging id accepted: {bad!r}")


def test_staging_prefix_is_invisible_to_library_scan() -> None:
    """A staged upload must not be ingested before the user confirms it."""
    from webapi.services.local_lib_service import _is_scan_skipped_local_dir

    assert _is_scan_skipped_local_dir(".staging") is True
    assert _is_scan_skipped_local_dir(".staging/abc123/Gallery A") is True
    assert _is_scan_skipped_local_dir("Real Gallery") is False


def test_missing_batch_raises() -> None:
    try:
        up.inspect_staged_galleries("deadbeefdeadbeef")
    except FileNotFoundError:
        return
    raise AssertionError("missing batch did not raise")


def test_names_only_mode_strips_the_preview_fields() -> None:
    """The confirm dialog reads names and page counts, nothing else."""
    batch_id, d = _fresh_batch()
    for name, n in (("Alpha", 3), ("Beta", 2)):
        for i in range(n):
            _img(d / name / f"{i:03d}.jpg")

    full = up.inspect_staged_galleries(batch_id)
    slim = up.inspect_staged_galleries(batch_id, names_only=True)

    assert full["gallery_count"] == 2, full
    assert slim["gallery_count"] == 2, slim
    assert "first_page" in full["galleries"][0], full
    # Every field the dialog actually renders survives the trim.
    for row in slim["galleries"]:
        assert set(row) == {"path", "name", "kind", "page_count", "ingestable", "over_limit"}, row
    assert [r["page_count"] for r in slim["galleries"]] == [3, 2], slim
    assert slim["max_gallery_pages"] == up.MAX_GALLERY_PAGES, slim


def test_per_gallery_page_cap_is_10000_and_reported_not_fatal() -> None:
    """The cap applies per gallery; a big sibling does not poison the rest.

    This is the regression the whole redesign exists for: the old limit was a
    *request* budget for the entire mother folder, so a dozen galleries adding
    up to 1000+ pages failed as a group.
    """
    assert up.MAX_GALLERY_PAGES == 10000, up.MAX_GALLERY_PAGES

    # At the cap: accepted. One over: rejected, with the gallery named.
    up.check_gallery_pages(10000, name="Ok")
    try:
        up.check_gallery_pages(10001, name="Huge Volume")
    except ValueError as e:
        assert "Huge Volume" in str(e), str(e)
        assert "10001" in str(e), str(e)
    else:
        raise AssertionError("over-cap gallery was not rejected")

    # The flag is computed per row, so the UI can grey one row out instead of
    # failing the batch.
    batch_id, d = _fresh_batch()
    _img(d / "Small" / "001.jpg")
    _img(d / "Huge" / "001.jpg")
    res = up.inspect_staged_galleries(batch_id, names_only=True)
    flags = {r["name"]: r["over_limit"] for r in res["galleries"]}
    assert flags == {"Small": False, "Huge": False}, flags

    # And the detector marks a genuinely oversized row rather than dropping it.
    original = up.MAX_GALLERY_PAGES
    try:
        up.MAX_GALLERY_PAGES = 0
        res2 = up.inspect_staged_galleries(batch_id, names_only=True)
        assert res2["gallery_count"] == 2, res2
        assert all(r["over_limit"] for r in res2["galleries"]), res2
    finally:
        up.MAX_GALLERY_PAGES = original


if __name__ == "__main__":
    tests = [
        test_leaf_folder_is_one_gallery,
        test_parent_folder_yields_many_galleries_not_one,
        test_folder_with_subdirs_is_not_a_gallery,
        test_folder_with_non_image_payload_is_not_a_gallery,
        test_dotfiles_do_not_disqualify_a_gallery,
        test_zip_and_cbz_report_member_counts,
        test_cbr_is_listed_but_not_ingestable,
        test_unreadable_zip_is_listed_but_not_ingestable,
        test_zip_without_images_is_not_a_gallery,
        test_nested_archives_are_found_inside_a_mother_folder,
        test_symlinks_are_not_followed,
        test_results_are_stably_ordered_for_pagination,
        test_sub_path_narrows_the_walk,
        test_bad_staging_id_is_rejected,
        test_staging_prefix_is_invisible_to_library_scan,
        test_missing_batch_raises,
        test_names_only_mode_strips_the_preview_fields,
        test_per_gallery_page_cap_is_10000_and_reported_not_fatal,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"OK {len(tests)} gallery-detection checks")
