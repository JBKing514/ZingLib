"""Isolated title-language and folder-count regressions; no real DB writes."""
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

_runtime = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_UI_RUNTIME_DIR", _runtime.name)
os.environ.setdefault("DATA_UI_LOCAL_LIB_DIR", str(Path(_runtime.name) / "library"))

from webapi.services import local_lib_service as lib
from webapi.routers import local_lib


class TitleLanguageTests(unittest.TestCase):
    def test_ratio_boundary_and_translation_suffix(self):
        for title in ["A very long English title Chinese edition 中文翻译", "abc中文日文漢字", "123 !", "", "한국어"]:
            with self.subTest(title=title):
                self.assertFalse(lib._has_cjk(title))
        for title in ["abc中文日文漢字名", "日本語の作品名 [2026] vol", "ｶﾀｶﾅの物語", "中文作品（第123卷）", "𠀀𠀁𠀂"]:
            with self.subTest(title=title):
                self.assertTrue(lib._has_cjk(title))
        self.assertFalse(lib._has_cjk("ＡＢＣＤ中文翻译"))

    def test_comicinfo_chooses_real_cjk_candidate_without_changing_title(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            english = "A long romanized gallery title 中文翻译"
            native = "日本語の正式な作品名"
            tree = ET.Element("ComicInfo")
            ET.SubElement(tree, "Title").text = english
            ET.SubElement(tree, "AlternateSeries").text = native
            ET.ElementTree(tree).write(folder / "ComicInfo.xml", encoding="utf-8")
            with patch.object(lib, "_safe_join_local_dir", return_value=folder):
                meta, _ = lib._comicinfo_meta("test", use_translated_tags=False)
            self.assertEqual(meta["title"], english)
            self.assertEqual(meta["title_jpn"], native)
            self.assertEqual(meta["raw"]["title_jpn_field"], "AlternateSeries")
            self.assertEqual(lib._pick_jpn_title_field([("Title", english)]), ("", ""))


class FolderCountTests(unittest.TestCase):
    def test_counts_are_not_page_length_and_paths_are_literal(self):
        with tempfile.TemporaryDirectory() as root:
            calls = []
            def query(sql, params):
                calls.append((sql, params))
                if "AS library_gallery_count" in sql:
                    return [{"folder_gallery_count": 243, "library_gallery_count": 1025}]
                if "OFFSET %s" in sql:
                    return [{"arcid": str(i), "title": str(i)} for i in range(121)]
                return []
            with patch.object(local_lib, "_safe_join_local_dir", return_value=Path(root)), patch.object(local_lib, "query_rows", side_effect=query), patch.object(local_lib, "resolve_config", return_value=({}, {})):
                result = local_lib._folder_list_payload("books_100%", limit=120, lite=True)
                self.assertEqual(len(result["galleries"]), 120)
                self.assertEqual(result["folder_gallery_count"], 243)
                self.assertEqual(result["library_gallery_count"], 1025)
                self.assertEqual(result["next_cursor"], "120")
                self.assertTrue(all("books\\_100\\%/%" in params for _, params in calls))
                calls.clear()
                local_lib._folder_list_payload("books_100%", cursor="120", limit=120, lite=True)
                self.assertFalse(any("AS library_gallery_count" in sql for sql, _ in calls))


if __name__ == "__main__":
    unittest.main()
