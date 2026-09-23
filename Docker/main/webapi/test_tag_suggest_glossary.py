"""Tag suggestions must survive an empty library.

The metadata editor's suggestion box is filled by `GET /api/home/filter/tag-suggest`.
Its candidate pool used to be a single `unnest(works.tags)`, so a user who had
not tagged anything yet saw an empty box no matter what the uploaded translation
table (`manual_tags.json`) knew. These tests pin the widened pool: the table is
searched too, and library hits keep their slots.

No database is involved on purpose. The `works.tags` side is stubbed, which is
what lets a test *be* the fresh-install case deterministically instead of hoping
a live library happens to be empty; the module can therefore never skip. The
live container path (real table, real library) is exercised separately by
`assets/probe_tag_suggest.py`.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from webapi.routers import search
from webapi.services import local_lib_service as lib

TABLE_NAME = "manual_tags.json"


def _payload(namespaces, display_names=None):
    """Build an EhTagTranslation `db.text.json` shaped payload.

    `namespaces` maps a namespace key to ``{raw tag: translated name}``; the
    `rows` entry (namespace display names, used by `_translate_tag`) is filled
    from `display_names` so the fixture stays short.
    """
    data = [{"namespace": "rows", "data": dict(display_names or {})}]
    for ns, entries in namespaces.items():
        data.append({"namespace": ns, "data": {k: {"name": v} for k, v in entries.items()}})
    return {"data": data}


class _TableFixture(unittest.TestCase):
    """Runs against a private temp table, never the user's upload.

    Redirecting `DATA_UI_RUNTIME_DIR` would NOT be enough: `constants.py` reads
    it once at import time, so whichever module of the suite imports webapi
    first decides the value, and these tests delete the table in `setUp`. The
    module attribute is patched instead, which is what `_translation_file_path`
    actually reads, and the assertion below makes a mis-patch fail loudly rather
    than deleting a real 4 MB glossary.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        table_dir = Path(tmp.name)
        for patcher in (
            patch.object(lib, "TRANSLATION_DIR", table_dir),
            # ensure_dirs() would otherwise mkdir the real runtime tree.
            patch.object(lib, "ensure_dirs", lambda: None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual(Path(lib.TRANSLATION_DIR).resolve(), table_dir.resolve())
        self.table_path = table_dir / TABLE_NAME
        self.assertFalse(self.table_path.exists())

    def install(self, payload) -> None:
        self.table_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def remove_table(self) -> None:
        self.table_path.unlink(missing_ok=True)


class GlossarySuggestionRules(_TableFixture):
    """`translation_tag_suggestions` on its own."""

    def test_an_entry_is_offered_by_its_translated_name(self):
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        self.assertEqual(lib.translation_tag_suggestions("萝莉"), ["female:萝莉"])

    def test_an_entry_is_offered_by_its_raw_tag_too(self):
        """An English typist must find it: the table is a translation map."""
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        self.assertEqual(lib.translation_tag_suggestions("lolicon"), ["female:萝莉"])

    def test_the_emitted_tag_keeps_the_english_namespace_key(self):
        """`_translate_tag` leaves the namespace untranslated, and works.tags agrees.

        The live database stores `female:眼镜`, never `女性:眼镜`; a suggestion
        that used the display name would commit a tag nothing else can match.
        """
        self.install(
            _payload(
                {"female": {"glasses": "眼镜"}},
                display_names={"female": {"name": "女性"}},
            )
        )
        tags = lib.translation_tag_suggestions("眼镜")
        self.assertEqual(tags, ["female:眼镜"])
        self.assertNotIn("女性:眼镜", tags)

    def test_a_value_match_outranks_a_raw_substring_match(self):
        """Ranking mirrors the library query: what the user typed wins."""
        self.install(
            _payload(
                {
                    "female": {"lolicon": "萝莉"},
                    "other": {"big lolicon works": "某萝莉合集"},
                }
            )
        )
        tags = lib.translation_tag_suggestions("萝莉")
        self.assertEqual(tags[0], "female:萝莉", tags)

    def test_an_exact_hit_outranks_a_prefix_hit(self):
        self.install(
            _payload(
                {
                    "female": {"glasses": "眼镜"},
                    "other": {"glasses stand": "眼镜架"},
                }
            )
        )
        tags = lib.translation_tag_suggestions("眼镜")
        self.assertEqual(tags[0], "female:眼镜", tags)
        self.assertIn("other:眼镜架", tags)

    def test_a_namespace_match_is_prefix_only(self):
        """`male` must not answer with the whole `female` namespace."""
        self.install(
            _payload(
                {
                    "male": {"muscular": "肌肉"},
                    "female": {"curvy": "曲线"},
                }
            )
        )
        tags = lib.translation_tag_suggestions("male")
        self.assertIn("male:肌肉", tags)
        self.assertEqual([t for t in tags if t.startswith("female:")], [], tags)

    def test_two_raw_tags_sharing_a_name_collapse_into_one(self):
        self.install(_payload({"female": {"glasses": "眼镜", "eyewear": "眼镜"}}))
        self.assertEqual(lib.translation_tag_suggestions("眼镜"), ["female:眼镜"])

    def test_a_missing_table_yields_an_empty_list(self):
        """A user who never uploaded a table still sees an empty box, not a 500."""
        self.remove_table()
        self.assertEqual(lib.translation_tag_suggestions("萝莉"), [])
        self.assertFalse(lib.translation_table_info()["exists"])

    def test_a_corrupt_table_yields_an_empty_list(self):
        self.table_path.write_text("{not json at all", encoding="utf-8")
        self.assertEqual(lib.translation_tag_suggestions("萝莉"), [])

    def test_a_blank_keyword_yields_an_empty_list(self):
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        self.assertEqual(lib.translation_tag_suggestions("   "), [])
        self.assertEqual(lib.translation_tag_suggestions(""), [])

    def test_the_limit_is_respected(self):
        self.install(_payload({"artist": {f"circle {i}": f"社团{i}" for i in range(30)}}))
        self.assertEqual(len(lib.translation_tag_suggestions("社团", limit=5)), 5)

    def test_replacing_the_table_changes_the_suggestions(self):
        """The index is cached by file signature, so a new upload must take over.

        Both directions are asserted: the old entry stops being suggested and the
        new one starts, which is what distinguishes a real reload from a stale
        index that merely happens to overlap.
        """
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        self.assertEqual(lib.translation_tag_suggestions("萝莉"), ["female:萝莉"])
        self.assertEqual(lib.translation_tag_suggestions("幼稚型"), [])
        self.install(_payload({"female": {"infantilism": "幼稚型"}}))
        self.assertEqual(lib.translation_tag_suggestions("萝莉"), [])
        self.assertEqual(lib.translation_tag_suggestions("幼稚型"), ["female:幼稚型"])


class TagSuggestEndpoint(_TableFixture):
    """The merge contract of `GET /api/home/filter/tag-suggest`."""

    def setUp(self):
        super().setUp()
        app = FastAPI()
        app.include_router(search.router)
        self.client = TestClient(app)

    def suggest(self, q, *, library=(), fuzzy=(), limit=20, ui_lang="zh"):
        """Call the endpoint with the library side stubbed to `library`."""
        with patch.object(search, "resolve_config", return_value=({}, None)), \
                patch.object(search, "query_rows", return_value=[dict(r) for r in library]), \
                patch.object(search, "_fuzzy_tags", return_value=list(fuzzy)):
            res = self.client.get(
                "/api/home/filter/tag-suggest",
                params={"q": q, "limit": limit, "ui_lang": ui_lang},
            )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_a_fresh_install_still_gets_suggestions(self):
        """The reported bug: no tags in the library, so the box was always empty."""
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        body = self.suggest("萝莉", library=[])
        self.assertEqual(body["items"], ["female:萝莉"])

    def test_a_library_hit_outranks_a_glossary_hit(self):
        """A tag the library actually uses is the better suggestion."""
        self.install(_payload({"female": {"glasses": "眼镜"}}))
        body = self.suggest("眼镜", library=[{"tag": "other:眼镜娘"}])
        self.assertEqual(body["items"][0], "other:眼镜娘", body["items"])
        self.assertIn("female:眼镜", body["items"])

    def test_the_glossary_never_duplicates_a_library_hit(self):
        self.install(_payload({"female": {"glasses": "眼镜"}}))
        body = self.suggest("眼镜", library=[{"tag": "female:眼镜"}])
        self.assertEqual(body["items"].count("female:眼镜"), 1, body["items"])

    def test_library_hits_that_fill_the_limit_leave_no_room(self):
        self.install(_payload({"female": {"glasses": "眼镜"}}))
        body = self.suggest("眼镜", library=[{"tag": "other:眼镜娘"}], limit=1)
        self.assertEqual(body["items"], ["other:眼镜娘"])

    def test_the_glossary_fills_only_the_remainder(self):
        self.install(_payload({"artist": {f"circle {i}": f"社团{i}" for i in range(30)}}))
        body = self.suggest("社团", library=[{"tag": "group:社团甲"}], limit=4)
        self.assertEqual(body["items"][0], "group:社团甲", body["items"])
        self.assertEqual(len(body["items"]), 4)
        self.assertEqual(len(set(body["items"])), 4)

    def test_no_table_and_no_library_is_an_empty_list_not_an_error(self):
        self.remove_table()
        body = self.suggest("萝莉", library=[])
        self.assertEqual(body, {"items": []})

    def test_the_payload_shape_is_unchanged(self):
        self.install(_payload({"female": {"lolicon": "萝莉"}}))
        body = self.suggest("萝莉", library=[])
        self.assertEqual(sorted(body.keys()), ["items"])


if __name__ == "__main__":
    unittest.main()
