"""Isolated title-language and folder-count regressions; no real DB writes."""
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

_runtime = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_UI_RUNTIME_DIR", _runtime.name)
os.environ.setdefault("DATA_UI_LOCAL_LIB_DIR", str(Path(_runtime.name) / "library"))

# Before the `webapi` imports: the container and CI run this as
# `python -m webapi.test_metadata_tools_regression` from `Docker/main`, where the
# package is already importable, but the offline runner may invoke it as a plain
# script -- and then only its own directory (`webapi/`) lands on `sys.path`, so
# `import webapi` fails. `parent.parent` is `Docker/main` in a checkout and `/app`
# in the image, which is exactly the import root either way.
sys.path.insert(0, str(Path(__file__).parent.parent))

from webapi.services import gallery_metadata_backup as backup
from webapi.services import local_lib_service as lib
from webapi.routers import local_lib
from webapi.routers.settings import _db_write_pending


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


class WritebackEligibilityTests(unittest.TestCase):
    """The metadata writeback has to ask the same questions, and apply the same rules.

    Two real defects are pinned here, both of the same shape -- the route working
    from a different answer than the one the rest of the app uses.

    1. It selected `works.title`, while the title a user sees is
       `raw.user_meta.title || works.title`. For any gallery the user had renamed,
       the writeback therefore stamped the stale *official* title back onto disk over
       the newer one -- undoing the very metadata the route exists to preserve.
    2. Its `dry_run` counted every row with a `local_dir` as writable, without asking
       either question the write path asks (does the path exist? is there a visual
       vector, without which `write_sidecar` refuses to back anything up?). The
       preview promised writes and reported zero skips; the confirmed run then failed.

    The route is driven for real (only its row source and the two writers are
    faked), so the assertions cover the branch logic rather than a mock's opinion.
    """

    def setUp(self):
        self.exists_dir = "wb_exists"
        self.dir_path = lib._safe_join_local_dir(self.exists_dir)
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def _drive(self, rows, *, dry_run, sidecar_ok=None, payload=None):
        written = []
        sidecars = []
        sql_seen = []

        def fake_query(sql, params):
            sql_seen.append(sql)
            return list(rows)

        def fake_comicinfo(local_dir, title, tags):
            written.append({"local_dir": local_dir, "title": title, "tags": list(tags)})
            return True

        def fake_sidecar(arcid):
            # Mirrors the real rule: `write_sidecar` refuses a gallery that has no
            # visual vector, because a sidecar is "the compute I spent on this".
            sidecars.append(arcid)
            return bool((sidecar_ok or {}).get(arcid, False))

        with (
            patch.object(local_lib, "tag_reapply_running", return_value=False),
            patch.object(local_lib, "query_rows", side_effect=fake_query),
            patch.object(lib, "write_comicinfo", side_effect=fake_comicinfo),
            patch.object(backup, "write_sidecar", side_effect=fake_sidecar),
        ):
            request = {"dry_run": dry_run}
            request.update(payload or {})
            result = local_lib.writeback_local_metadata(request)
        return result, written, sidecars, sql_seen

    def test_comicinfo_receives_the_display_title(self):
        rows = [
            {
                "arcid": "wb-renamed",
                "title": "Official Stale Title",
                "tags": ["artist:x"],
                "local_dir": self.exists_dir,
                "raw": {"user_meta": {"title": "My Renamed Title"}},
                "has_cover": True,
            }
        ]
        result, written, _sidecars, sql_seen = self._drive(
            rows, dry_run=False, sidecar_ok={"wb-renamed": True}
        )
        self.assertIn("raw", sql_seen[0], "the writeback must read raw to see user_meta")
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["title"], "My Renamed Title")
        self.assertEqual(written[0]["tags"], ["artist:x"])
        self.assertEqual(result["comicinfo_written"], 1)
        self.assertEqual(result["failed"], 0)
        # The fake row carries every column whatever the SQL asks for, so the
        # projection has to be asserted separately -- otherwise dropping `raw` (or
        # `has_cover`) from the SELECT would leave this suite green while production
        # lost the fix again.
        self.assertIn("has_cover", sql_seen[0], "the eligibility flag must come from the query")

    def test_official_title_is_the_fallback_when_the_user_did_not_rename(self):
        rows = [
            {
                "arcid": "wb-official",
                "title": "Official Title",
                "tags": [],
                "local_dir": self.exists_dir,
                "raw": {},
                "has_cover": True,
            }
        ]
        _result, written, _sidecars, _sql = self._drive(
            rows, dry_run=False, sidecar_ok={"wb-official": True}
        )
        self.assertEqual([w["title"] for w in written], ["Official Title"])

    def test_dry_run_counts_exactly_what_the_write_run_would_fail_on(self):
        rows = [
            {
                # Writable path, but nothing expensive to protect: ComicInfo must
                # still be written even though the sidecar is unavailable.
                "arcid": "wb-no-cover",
                "title": "No Cover",
                "tags": [],
                "local_dir": self.exists_dir,
                "raw": {},
                "has_cover": False,
            },
            {
                # Has a vector, but the directory is gone: sidecar backup remains
                # possible because it lives under the library metadata directory.
                "arcid": "wb-missing-path",
                "title": "Missing Path",
                "tags": [],
                "local_dir": "wb_does_not_exist",
                "raw": {},
                "has_cover": True,
            },
        ]

        preview, preview_written, _preview_sidecars, _sql = self._drive(rows, dry_run=True)
        self.assertEqual(preview["skipped"], 0, "each row has one independently writable output")
        self.assertEqual(preview["comicinfo_written"], 0)
        self.assertEqual(preview_written, [], "a dry run writes nothing")
        by_arcid = {d["arcid"]: d for d in preview["details"]}
        self.assertTrue(by_arcid["wb-no-cover"]["comicinfo"])
        self.assertFalse(by_arcid["wb-no-cover"]["sidecar"])
        self.assertEqual(by_arcid["wb-no-cover"]["sidecar_reason"], "no visual embedding")
        self.assertFalse(by_arcid["wb-missing-path"]["comicinfo"])
        self.assertEqual(by_arcid["wb-missing-path"]["comicinfo_reason"], "path not found")
        self.assertTrue(by_arcid["wb-missing-path"]["sidecar"])

        applied, applied_written, _sidecars, _sql = self._drive(
            rows, dry_run=False, sidecar_ok={"wb-missing-path": True}
        )
        self.assertEqual([w["title"] for w in applied_written], ["No Cover"])
        self.assertEqual(applied["comicinfo_written"], 1)
        self.assertEqual(applied["sidecar_written"], 1)
        self.assertEqual(applied["skipped"], preview["skipped"])
        self.assertEqual(applied["failed"], 0)


class ConfigSaveStateTests(unittest.TestCase):
    def test_only_the_first_unsaved_config_treats_a_db_failure_as_pending(self):
        self.assertTrue(_db_write_pending(False, False))
        self.assertFalse(_db_write_pending(False, True))
        self.assertFalse(_db_write_pending(True, False))
        self.assertFalse(_db_write_pending(True, True))


if __name__ == "__main__":
    unittest.main()
