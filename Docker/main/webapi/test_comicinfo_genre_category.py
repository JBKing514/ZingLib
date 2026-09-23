#!/usr/bin/env python3
"""
Regression test for ComicInfo Genre <-> category mapping and title selection.

Covers three behaviours that regressed at some point:

* ``category:<genre>`` must be emitted from ``<Genre>`` in **every** tag mode,
  not only when the ``<Tags>`` field happens to be empty. The dashboard category
  pill and the category filter both read that prefix from ``works.tags``.
* ``raw.eh_raw.category`` must still be usable as a category when the tag is
  missing from an already ingested row (no re-apply needed).
* The Japanese/kanji title must be taken from whichever of
  Title / Series / AlternateSeries actually contains kanji or kana, because
  ``AlternateSeries`` is frequently a romanized name.
"""

from __future__ import annotations

import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.core.constants import LOCAL_LIB_DIR
    from webapi.services.local_lib_service import (
        _comicinfo_meta,
        _pick_tags_from_mode,
        _pick_title_from_mode,
        write_comicinfo,
    )
    from webapi.services.search_service import _item_from_work
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.core.constants import LOCAL_LIB_DIR
    from webapi.services.local_lib_service import (
        _comicinfo_meta,
        _pick_tags_from_mode,
        _pick_title_from_mode,
        write_comicinfo,
    )
    from webapi.services.search_service import _item_from_work


TEST_DIR_NAME = "unit_test_genre_category"

JPN_TITLE = "[あくた～ (木家マユ)] TSしたら肉便器 何回転生してもずっと"
ROMAN_TITLE = "[Akuta (Kiya Mayu)] TS Shitara Nikubenki Nankai Tensei Shitemo Zutto"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_comicinfo_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>Genre Mapping Test</Title>
  <Genre>Action, Adventure</Genre>
  <Tags>artist:test, tag:demo</Tags>
</ComicInfo>
"""


def build_title_xml(title: str, series: str = "", alt_series: str = "", tags: str = "artist:test") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<ComicInfo>\n"
        f"  <Title>{title}</Title>\n"
        f"  <Series>{series}</Series>\n"
        f"  <AlternateSeries>{alt_series}</AlternateSeries>\n"
        f"  <Tags>{tags}</Tags>\n"
        "</ComicInfo>\n"
    )


def main() -> int:
    base = Path(LOCAL_LIB_DIR) / TEST_DIR_NAME
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    try:
        comicinfo_path = base / "ComicInfo.xml"
        comicinfo_path.write_text(build_comicinfo_xml(), encoding="utf-8")

        print("[1] Parsing ComicInfo Genre")
        meta, target_name = _comicinfo_meta(TEST_DIR_NAME, use_translated_tags=False)
        assert_true(target_name.lower() == "comicinfo.xml", f"unexpected ComicInfo target: {target_name!r}")
        eh_raw = meta.get("raw", {}).get("eh_raw") if isinstance(meta.get("raw"), dict) else {}
        category = str((eh_raw or {}).get("category") or "").strip().lower()
        assert_true(category == "action", f"expected category 'action', got {category!r}")

        print("[2] Building tags from parsed metadata (every tag mode keeps the category)")
        # The fixture has a NON-empty <Tags> field on purpose: this is the shape
        # that used to swallow the category extra in the default "translated"
        # mode.
        tags = _pick_tags_from_mode(meta, "raw")
        print(f"    raw mode: {tags}")
        assert_true("category:action" in [str(x).lower() for x in tags], "category tag not emitted from Genre in raw mode")
        for mode in ("translated", "translated_plus_raw"):
            mode_tags = [str(x).lower() for x in _pick_tags_from_mode(meta, mode)]
            print(f"    {mode} mode: {mode_tags}")
            assert_true(
                "category:action" in mode_tags,
                f"category tag dropped in {mode!r} mode although <Tags> is non-empty",
            )

        print("[3] Verifying dashboard item category extraction")
        item = _item_from_work(
            {
                "arcid": "genre-mapping-test",
                "title": "Genre Mapping Test",
                "tags": tags,
                "raw": meta.get("raw") or {},
                "local_dir": TEST_DIR_NAME,
                "source": "local",
            }
        )
        assert_true(str(item.get("category") or "") == "action", f"expected item.category 'action', got {item.get('category')!r}")

        print("[4] Verifying category fallback from raw.eh_raw for legacy rows")
        legacy = _item_from_work(
            {
                "arcid": "genre-mapping-legacy",
                "title": "Genre Mapping Test",
                "tags": ["artist:test", "group:demo"],
                "raw": {"eh_raw": {"category": "doujinshi"}},
                "local_dir": TEST_DIR_NAME,
                "source": "local",
            }
        )
        assert_true(
            str(legacy.get("category") or "") == "doujinshi",
            f"expected legacy fallback category 'doujinshi', got {legacy.get('category')!r}",
        )
        # An explicit category: tag still wins over the raw mirror.
        both = _item_from_work(
            {
                "arcid": "genre-mapping-both",
                "title": "Genre Mapping Test",
                "tags": ["category:manga"],
                "raw": {"eh_raw": {"category": "doujinshi"}},
                "local_dir": TEST_DIR_NAME,
                "source": "local",
            }
        )
        assert_true(str(both.get("category") or "") == "manga", f"expected tag category 'manga', got {both.get('category')!r}")

        print("[5] Japanese title is read from the field that actually holds kanji")
        comicinfo_path.write_text(build_title_xml(JPN_TITLE, JPN_TITLE, ROMAN_TITLE), encoding="utf-8")
        meta_jpn, _ = _comicinfo_meta(TEST_DIR_NAME, use_translated_tags=False)
        assert_true(meta_jpn.get("title") == JPN_TITLE, f"unexpected meta title: {meta_jpn.get('title')!r}")
        assert_true(
            meta_jpn.get("title_jpn") == JPN_TITLE,
            f"AlternateSeries (romanized) was used as the Japanese title: {meta_jpn.get('title_jpn')!r}",
        )
        assert_true(
            str((meta_jpn.get("raw") or {}).get("title_jpn_field") or "") == "Title",
            f"unexpected jpn title field: {(meta_jpn.get('raw') or {}).get('title_jpn_field')!r}",
        )
        assert_true(
            _pick_title_from_mode(meta_jpn, "fallback", "title_jpn") == JPN_TITLE,
            "title_jpn display mode did not surface the kanji title",
        )

        print("[6] Japanese title falls back to AlternateSeries when that is the kanji field")
        comicinfo_path.write_text(build_title_xml(ROMAN_TITLE, "", JPN_TITLE), encoding="utf-8")
        meta_alt, _ = _comicinfo_meta(TEST_DIR_NAME, use_translated_tags=False)
        assert_true(meta_alt.get("title_jpn") == JPN_TITLE, f"kanji AlternateSeries not detected: {meta_alt.get('title_jpn')!r}")
        assert_true(
            str((meta_alt.get("raw") or {}).get("title_jpn_field") or "") == "AlternateSeries",
            f"unexpected jpn title field: {(meta_alt.get('raw') or {}).get('title_jpn_field')!r}",
        )

        print("[7] With no kanji anywhere the Japanese slot stays empty and Title is used")
        comicinfo_path.write_text(build_title_xml(ROMAN_TITLE, ROMAN_TITLE, ROMAN_TITLE), encoding="utf-8")
        meta_latin, _ = _comicinfo_meta(TEST_DIR_NAME, use_translated_tags=False)
        assert_true(meta_latin.get("title_jpn") == "", f"expected empty jpn title, got {meta_latin.get('title_jpn')!r}")
        assert_true(
            str((meta_latin.get("raw") or {}).get("title_jpn_field") or "") == "",
            f"expected empty jpn title field, got {(meta_latin.get('raw') or {}).get('title_jpn_field')!r}",
        )
        assert_true(
            _pick_title_from_mode(meta_latin, "fallback", "title_jpn") == ROMAN_TITLE,
            "kanji-less ComicInfo should fall back to Title",
        )

        print("[8] Verifying ComicInfo write-back to Genre")
        comicinfo_path.write_text(build_comicinfo_xml(), encoding="utf-8")
        ok = write_comicinfo(TEST_DIR_NAME, "Genre Mapping Test", ["artist:test", "category:action"])
        assert_true(ok, "write_comicinfo returned false")
        root = ET.fromstring(comicinfo_path.read_text(encoding="utf-8"))
        genre_text = str(root.findtext("Genre") or "").strip().lower()
        assert_true(genre_text == "action", f"expected Genre write-back 'action', got {genre_text!r}")

        print("[OK] ComicInfo Genre/category + jpn title regression passed")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
