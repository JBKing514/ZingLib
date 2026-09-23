"""Round 44: the per-gallery sidecar backup and its manual restore.

Two layers, deliberately separated:

* the payload/merge rules are pure, so they always run and never depend on a
  database;
* the write -> wipe -> restore round trip needs Postgres, so it SKIPs (never
  fails, never fakes a pass) when no database is reachable. The offline guard
  proves the shape; only the container run proves the SQL.

The round trip uses its own sidecar directory, so running it against a live
library cannot read or rewrite any other gallery's backup.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Redirect the library root only -- deliberately NOT DATA_UI_RUNTIME_DIR.
# config_service keeps the secret-encryption key inside the runtime dir and
# resolves config with a `db > json > env` precedence, so a private runtime dir
# makes the stored POSTGRES_PASSWORD undecryptable: the empty database value
# then shadows the correct environment one and the suite SKIPs instead of
# proving the SQL.  Nothing here needs a private runtime dir anyway -- the
# sidecar directory is derived from the library root and is patched below.
_runtime = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_UI_LOCAL_LIB_DIR", str(Path(_runtime.name) / "library"))

from webapi.services import gallery_metadata_backup as gmb
from webapi.services import local_lib_service as lib
from webapi.services.db_service import db_dsn


def _connectable_dsn() -> str:
    """The first DSN that really connects; '' when none does.

    ``db_dsn()`` is the production path, but it is only as good as the config
    it resolves, so the environment DSN is kept as a second candidate.  A suite
    that skipped because it asked the wrong question would be a fake green.
    """
    candidates: list[str] = []
    try:
        candidates.append(str(db_dsn() or "").strip())
    except Exception:  # noqa: BLE001
        pass
    candidates.append(str(os.environ.get("POSTGRES_DSN") or "").strip())
    import psycopg

    for candidate in candidates:
        if not candidate:
            continue
        try:
            with psycopg.connect(candidate) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            return candidate
        except Exception:  # noqa: BLE001
            continue
    return ""


COVER = [0.001 * (i % 97) for i in range(gmb.SIGLIP_DIM)]
PAGE = [0.002 * (i % 89) for i in range(gmb.SIGLIP_DIM)]
TEXT = [0.003 * (i % 83) for i in range(gmb.TEXT_DIM)]

SIDECAR_SQL_KEYS = ("schema", "arcid", "local_dir", "siglip", "meta", "history")


class PayloadRuleTests(unittest.TestCase):
    """Pure rules: these are what the offline guard also pins."""

    def test_sidecar_dir_is_invisible_to_the_scanner(self):
        self.assertIn(".zinglib_meta", lib.SCAN_SKIP_PREFIXES)
        self.assertTrue(lib._is_scan_skipped_local_dir(".zinglib_meta"))
        self.assertTrue(
            lib._is_scan_skipped_local_dir(".zinglib_meta/local-abc_zinglib_metadata.json")
        )
        # A gallery that merely has "zinglib" in its name must stay visible.
        self.assertFalse(lib._is_scan_skipped_local_dir("zinglib favourites"))

    def test_sidecar_name_follows_the_arcid(self):
        self.assertEqual(
            gmb.sidecar_filename("local-abc"), "local-abc_zinglib_metadata.json"
        )
        self.assertTrue(gmb.sidecar_filename("local-abc").endswith(gmb.SIDECAR_SUFFIX))

    def test_relative_path_normalisation_is_the_match_key(self):
        self.assertEqual(gmb.normalize_rel_path("a\\b/ c/"), "a/b/ c")
        self.assertEqual(gmb.normalize_rel_path("/a/b/"), "a/b")
        self.assertEqual(gmb.normalize_rel_path(None), "")

    def test_vector_literal_is_pgvector_text(self):
        self.assertEqual(gmb.vector_literal([1.0, 0.5]), "[1.0,0.5]")
        # It has to be accepted by `_floats` again, which is how a sidecar read
        # back from disk is turned into a literal on the restore path.
        self.assertEqual(gmb._floats(gmb.vector_literal([0.25, -2.0])), [0.25, -2.0])

    def test_payload_carries_every_contract_key(self):
        row = {
            "arcid": "local-abc",
            "local_dir": r"Folder\Gallery",
            "raw": {
                "user_meta": {"title": "Picked", "tags": ["artist:x"]},
                "bookmark": 12,
                "eh_raw": {"category": "doujinshi"},
                "comicinfo": {"Genre": "Action"},
            },
            "cover_vec": gmb.vector_literal(COVER),
            "page_vec": gmb.vector_literal(PAGE),
            "text_vec": gmb.vector_literal(TEXT),
        }
        with patch.object(gmb, "_read_events_for", return_value=[]):
            payload = gmb.build_payload(row, model_id="siglip-test")
        for key in SIDECAR_SQL_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["local_dir"], "Folder/Gallery")
        self.assertEqual(payload["siglip"]["model"], "siglip-test")
        self.assertEqual(len(payload["siglip"]["cover"]), gmb.SIGLIP_DIM)
        self.assertEqual(len(payload["siglip"]["page"]), gmb.SIGLIP_DIM)
        self.assertEqual(len(payload["text"]["vector"]), gmb.TEXT_DIM)
        self.assertEqual(payload["meta"]["bookmark"], 12)
        self.assertEqual(payload["meta"]["tags"], ["artist:x"])
        self.assertEqual(payload["meta"]["category"], "doujinshi")
        self.assertEqual(payload["meta"]["comicinfo"], {"Genre": "Action"})
        # JSON has to survive the round trip byte-for-byte through the file.
        self.assertEqual(json.loads(json.dumps(payload))["arcid"], "local-abc")

    def test_text_vector_is_optional_not_broken(self):
        row = {
            "arcid": "local-abc",
            "local_dir": "g",
            "raw": {},
            "cover_vec": gmb.vector_literal(COVER),
            "page_vec": gmb.vector_literal(PAGE),
            "text_vec": "",
        }
        with patch.object(gmb, "_read_events_for", return_value=[]):
            payload = gmb.build_payload(row)
        self.assertNotIn("text", payload, "a pure image library must not look broken")
        self.assertEqual(payload["siglip"]["cover"], COVER)

    def test_raw_merge_is_key_wise_and_never_clobbers(self):
        current = {"bookmark": 7, "unrelated": {"keep": 1}, "user_meta": {"title": "Newer"}}
        merged, changed = gmb._merge_raw(
            current,
            {"title": "Older", "tags": ["artist:x"], "bookmark": 99, "comicinfo": {"G": "A"}},
        )
        self.assertEqual(merged["bookmark"], 7, "a live bookmark is newer than the backup")
        self.assertEqual(merged["user_meta"]["title"], "Newer")
        self.assertEqual(merged["unrelated"], {"keep": 1}, "raw must never be replaced wholesale")
        self.assertEqual(merged["user_meta"]["tags"], ["artist:x"])
        self.assertEqual(merged["comicinfo"], {"G": "A"})
        self.assertTrue(changed)

    def test_merge_raw_restores_category_and_empty_comicinfo(self):
        merged, changed = gmb._merge_raw(
            {"comicinfo": {}, "eh_raw": {}},
            {"category": "manga", "comicinfo": {"Genre": "Manga"}},
        )
        self.assertTrue(changed)
        self.assertEqual(merged["eh_raw"]["category"], "manga")
        self.assertEqual(merged["comicinfo"], {"Genre": "Manga"})

    def test_report_row_refuses_an_unknown_status(self):
        with self.assertRaises(ValueError):
            gmb.report_row("whatever", status="nonsense")

    def test_gallery_name_is_what_the_user_recognises(self):
        self.assertEqual(gmb.gallery_name("Uploads/Box/My Gallery"), "My Gallery")
        self.assertEqual(gmb.gallery_name("Uploads\\Box\\My Gallery"), "My Gallery")
        self.assertEqual(gmb.gallery_name("My Gallery"), "My Gallery")
        self.assertEqual(gmb.gallery_name(""), "")

    def test_compact_report_streams_self_describing_rows(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(gmb, "LOCAL_LIB_DIR", Path(tmp)):
                with patch.object(
                    gmb,
                    "query_rows",
                    return_value=[{"arcid": "local-missing", "local_dir": "missing/gallery"}],
                ):
                    report = gmb.restore_sidecars(
                        dry_run=True,
                        include_details=False,
                        detail_sink=lambda kind, item: seen.append(item),
                    )

        # A compact response carries counters only. An empty list sitting next to
        # a non-zero count reads like "nothing failed", so the list must be gone.
        self.assertNotIn("no_sidecar", report)
        self.assertNotIn("failed", report)
        self.assertNotIn("orphan_sidecars", report)
        self.assertEqual(report["no_sidecar_count"], 1)

        kinds = [row["type"] for row in seen]
        self.assertEqual(kinds[0], "restore_report", "the log must explain itself")
        self.assertEqual(kinds[-1], "summary")
        self.assertIn("no_sidecar", kinds)

        # Every per-gallery line answers the four questions -- a reader never has
        # to join this file against the counters to learn what happened to a
        # gallery. The trailing summary is not a per-gallery line, so it gets its
        # own shape below instead of being folded into this loop.
        per_gallery = [row for row in seen if row["type"] != "summary"]
        self.assertEqual(len(per_gallery) + 1, len(seen))
        for row in per_gallery:
            for key in ("status", "ok", "reason", "arcid", "gallery", "local_dir"):
                self.assertIn(key, row)
            self.assertIn(row["status"], gmb.RESTORE_STATUSES)
            self.assertTrue(str(row["reason"]).strip(), f"empty reason: {row}")

        detail = [r for r in seen if r["type"] == "no_sidecar"][0]
        self.assertEqual(detail["status"], "no_backup")
        self.assertTrue(detail["ok"], "no backup is information, not a failure")
        self.assertEqual(detail["arcid"], "local-missing")
        self.assertEqual(detail["local_dir"], "missing/gallery")
        self.assertEqual(detail["gallery"], "gallery")

        header = seen[0]
        self.assertEqual(header["status"], "preview")
        self.assertEqual(header["schema"], gmb.REPORT_SCHEMA)
        self.assertEqual(header["library_galleries"], 1)

        summary = seen[-1]
        self.assertNotIn("status", summary, "the summary is counters, not a gallery line")
        self.assertFalse(summary["had_failures"])
        self.assertEqual(summary["no_sidecar_count"], 1)
        self.assertIn("1 without backup", summary["summary"])
        self.assertTrue(summary["dry_run"])

    def test_raw_merge_fills_only_what_is_missing(self):
        merged, changed = gmb._merge_raw(
            {}, {"title": "T", "tags": ["a:1", "a:1"], "bookmark": 3}
        )
        self.assertEqual(merged["user_meta"]["title"], "T")
        self.assertEqual(merged["user_meta"]["tags"], ["a:1"], "the ledger must not gain duplicates")
        self.assertEqual(merged["bookmark"], 3)
        self.assertTrue(changed)

    def test_raw_merge_reports_no_change_for_an_empty_meta_block(self):
        merged, changed = gmb._merge_raw({"bookmark": 1}, {})
        self.assertFalse(changed)
        self.assertEqual(merged, {"bookmark": 1})

    def test_unknown_schema_is_refused_instead_of_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / gmb.sidecar_filename("local-abc")
            good.write_text(json.dumps({"schema": gmb.SIDECAR_SCHEMA}), encoding="utf-8")
            self.assertIsNotNone(gmb._read_sidecar(good))
            good.write_text(json.dumps({"schema": "zinglib.metadata.v99"}), encoding="utf-8")
            self.assertIsNone(gmb._read_sidecar(good), "a future layout must not be misinterpreted")
            good.write_text("{not json", encoding="utf-8")
            self.assertIsNone(gmb._read_sidecar(good))


class RoundTripTests(unittest.TestCase):
    """Needs Postgres. Skips -- never fails -- when there is none."""

    arcid = "local-r44-roundtrip"
    bare_arcid = "local-r44-nosidecar"
    orphan_arcid = "local-r44-orphan"
    rel = "r44-selftest/gallery-with-backup"
    bare_rel = "r44-selftest/gallery-without-backup"

    @classmethod
    def setUpClass(cls):
        cls.dsn = _connectable_dsn()
        if not cls.dsn:
            raise unittest.SkipTest(
                "no reachable Postgres: neither the resolved config DSN nor "
                "POSTGRES_DSN connected"
            )

    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.dsn = type(self).dsn
        self.meta = Path(tempfile.mkdtemp(prefix="zinglib-meta-"))
        self._patch = patch.object(gmb, "meta_dir", lambda create=False: self.meta)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self._cleanup()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                # read_events cascades from works, so this is the whole cleanup.
                cur.execute(
                    "DELETE FROM works WHERE arcid = ANY(%s::text[])",
                    ([self.arcid, self.bare_arcid, self.orphan_arcid],),
                )
            conn.commit()

    def _seed(self):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                for arcid, rel, title in (
                    (self.arcid, self.rel, "With backup"),
                    (self.bare_arcid, self.bare_rel, "Without backup"),
                ):
                    cur.execute(
                        "INSERT INTO works (arcid, title, tags, raw, local_dir, source, last_seen_at) "
                        "VALUES (%s, %s, ARRAY[]::text[], '{}'::jsonb, %s, 'local', now()) "
                        "ON CONFLICT (arcid) DO UPDATE SET local_dir = EXCLUDED.local_dir, "
                        "source = 'local'",
                        (arcid, title, rel),
                    )
                cur.execute(
                    "UPDATE works SET visual_embedding = %s::vector, "
                    "page_visual_embedding = %s::vector, desc_embedding = %s::vector, "
                    "cover_embedding_status = 'complete', "
                    "raw = %s::jsonb WHERE arcid = %s",
                    (
                        gmb.vector_literal(COVER),
                        gmb.vector_literal(PAGE),
                        gmb.vector_literal(TEXT),
                        json.dumps(
                            {
                                "user_meta": {"title": "Picked title", "tags": ["artist:someone"]},
                                "bookmark": 9,
                                "eh_raw": {"category": "doujinshi"},
                                "comicinfo": {"Genre": "Action"},
                            }
                        ),
                        self.arcid,
                    ),
                )
                cur.execute(
                    "INSERT INTO read_events (arcid, read_time, source_file) "
                    "VALUES (%s, 1700000001, 'selftest'), (%s, 1700000002, 'selftest')",
                    (self.arcid, self.arcid),
                )
            conn.commit()

    def _wipe(self):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE works SET visual_embedding = NULL, page_visual_embedding = NULL, "
                    "desc_embedding = NULL, cover_embedding_status = 'pending', "
                    "raw = '{}'::jsonb WHERE arcid = %s",
                    (self.arcid,),
                )
                cur.execute("DELETE FROM read_events WHERE arcid = %s", (self.arcid,))
            conn.commit()

    def _row(self, arcid):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT (visual_embedding IS NOT NULL) AS has_cover, "
                    "(page_visual_embedding IS NOT NULL) AS has_page, "
                    "(desc_embedding IS NOT NULL) AS has_text, "
                    "cover_embedding_status, raw "
                    "FROM works WHERE arcid = %s",
                    (arcid,),
                )
                r = cur.fetchone()
        keys = ("has_cover", "has_page", "has_text", "cover_embedding_status", "raw")
        return dict(zip(keys, r)) if r else None

    def _history(self, arcid):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM read_events WHERE arcid = %s", (arcid,))
                return int(cur.fetchone()[0])

    def test_write_wipe_restore_round_trip(self):
        self._seed()

        self.assertTrue(gmb.write_sidecar(self.arcid, model_id="selftest-siglip"))
        path = self.meta / gmb.sidecar_filename(self.arcid)
        self.assertTrue(path.is_file(), "the embedding run must leave a sidecar behind")
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        for key in SIDECAR_SQL_KEYS:
            self.assertIn(key, on_disk)
        self.assertEqual(len(on_disk["siglip"]["cover"]), gmb.SIGLIP_DIM)
        self.assertEqual(len(on_disk["text"]["vector"]), gmb.TEXT_DIM)
        self.assertEqual(len(on_disk["history"]), 2)
        # The gallery with no vectors at all must still get a sidecar: "no text
        # vector" is a configuration, "no visual vector" would be a bug.
        self.assertFalse(gmb.write_sidecar(self.bare_arcid))

        self._wipe()
        self.assertFalse(self._row(self.arcid)["has_cover"])

        preview = gmb.restore_sidecars(dry_run=True)
        self.assertEqual(preview["restored"], 0, "a dry run must not write")
        self.assertFalse(self._row(self.arcid)["has_cover"])
        self.assertEqual(preview["matched"], 1)
        self.assertIn(self.bare_arcid, [r["arcid"] for r in preview["no_sidecar"]])

        report = gmb.restore_sidecars()
        self.assertTrue(report["ok"])
        self.assertEqual(report["restored"], 1)
        self.assertEqual(report["visual_restored"], 1)
        self.assertEqual(report["text_restored"], 1, "the optional LLM vector was backed up")
        self.assertEqual(report["history_rows"], 2)

        row = self._row(self.arcid)
        self.assertTrue(row["has_cover"])
        self.assertTrue(row["has_page"])
        self.assertTrue(row["has_text"])
        self.assertEqual(row["cover_embedding_status"], "complete")
        self.assertEqual(self._history(self.arcid), 2)

        raw = row["raw"]
        self.assertEqual(raw["user_meta"]["title"], "Picked title")
        self.assertEqual(raw["user_meta"]["tags"], ["artist:someone"])
        self.assertEqual(int(raw["bookmark"]), 9)
        self.assertEqual(raw["comicinfo"], {"Genre": "Action"})
        self.assertEqual(raw["eh_raw"]["category"], "doujinshi")

        # Every live gallery is accounted for: restored, or reported as carrying
        # no ZingLib metadata. That is the denominator the popup shows.
        self.assertGreaterEqual(report["total_galleries"], 2)
        self.assertIn(self.bare_arcid, [r["arcid"] for r in report["no_sidecar"]])
        self.assertNotIn(self.arcid, [r["arcid"] for r in report["no_sidecar"]])

        # Restoring twice must be idempotent: the history insert is keyed on
        # (arcid, read_time) and the vectors are never overwritten.
        again = gmb.restore_sidecars()
        self.assertEqual(again["history_rows"], 0)
        self.assertEqual(self._history(self.arcid), 2)

    def test_report_rows_name_the_gallery_and_the_outcome(self):
        self._seed()
        self.assertTrue(gmb.write_sidecar(self.arcid, model_id="selftest-siglip"))
        self._wipe()
        rows = []
        report = gmb.restore_sidecars(detail_sink=lambda kind, item: rows.append(item))
        self.assertEqual(report["restored"], 1)

        # The line a reader lands on first: "this gallery came back, from what".
        matched = [r for r in rows if r["type"] == "matched"][0]
        self.assertEqual(matched["status"], "restored")
        self.assertTrue(matched["ok"])
        self.assertEqual(matched["arcid"], self.arcid)
        self.assertEqual(matched["gallery"], "gallery-with-backup")
        self.assertEqual(matched["reason"], gmb.RESTORE_REASONS["restored"])
        self.assertGreater(int(matched["visual"]), 0)

        # And the one that will never come back has to say so in words, not just
        # shave the denominator by one.
        # 🔴 Pick the row by arcid, never by position: `no_sidecar` covers every
        # live gallery without a backup, and on the dev host that list starts
        # with the user's real library. `[0]` passed against an empty local DB
        # and failed in the container with a real gallery's name.
        gap = [r for r in rows if r["type"] == "no_sidecar" and r["arcid"] == self.bare_arcid]
        self.assertEqual(len(gap), 1, "the fixture gallery must appear exactly once")
        gap = gap[0]
        self.assertEqual(gap["status"], "no_backup")
        self.assertEqual(gap["gallery"], "gallery-without-backup")
        self.assertEqual(gap["arcid"], self.bare_arcid)
        self.assertTrue(gap["reason"])

    def test_two_backups_for_one_gallery_report_a_duplicate(self):
        self._seed()
        self.assertTrue(gmb.write_sidecar(self.arcid, model_id="selftest-siglip"))
        older = self.meta / gmb.sidecar_filename(self.arcid)
        payload = json.loads(older.read_text(encoding="utf-8"))
        # A moved library leaves the old backup behind: same relative layout,
        # stale arcid, so its own filename. Both match, only one may be applied.
        payload["arcid"] = "local-r44-stale-copy"
        newer = self.meta / gmb.sidecar_filename("local-r44-stale-copy")
        newer.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_700_000_100, 1_700_000_100))

        self._wipe()
        report = gmb.restore_sidecars()

        # The denominator must stay honest: one gallery, one match.
        self.assertEqual(report["matched"], 1, "two backups must not inflate matched")
        self.assertEqual(report["restored"], 1)
        self.assertEqual(report["duplicate_count"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["duplicate_sidecars"][0]["file"], older.name)
        self.assertEqual(report["duplicate_sidecars"][0]["status"], "duplicate")
        self.assertEqual(report["duplicate_sidecars"][0]["arcid"], self.arcid)
        self.assertEqual(report["duplicate_sidecars"][0]["gallery"], "gallery-with-backup")

    def test_sidecar_whose_gallery_is_gone_is_reported_not_restored(self):
        self._seed()
        stray = self.meta / gmb.sidecar_filename(self.orphan_arcid)
        stray.write_text(
            json.dumps(
                {
                    "schema": gmb.SIDECAR_SCHEMA,
                    "arcid": self.orphan_arcid,
                    "local_dir": "r44-selftest/gallery-that-moved-away",
                    "siglip": {"dim": gmb.SIGLIP_DIM, "cover": COVER, "page": PAGE},
                    "meta": {},
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        report = gmb.restore_sidecars()
        self.assertEqual(report["orphan_count"], 1)
        self.assertEqual(report["orphan_sidecars"][0]["arcid"], self.orphan_arcid)
        self.assertEqual(report["restored"], 0)

    def test_arcid_fallback_uses_arcid_not_local_dir(self):
        self._seed()
        fallback = self.meta / gmb.sidecar_filename(self.arcid)
        fallback.write_text(
            json.dumps(
                {
                    "schema": gmb.SIDECAR_SCHEMA,
                    "arcid": self.arcid,
                    "local_dir": "",
                    "siglip": {"cover": COVER, "page": PAGE},
                    "meta": {},
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        self._wipe()
        report = gmb.restore_sidecars()
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["failed_count"], 0)
        self.assertTrue(self._row(self.arcid)["has_cover"])

    def test_restore_follows_the_path_when_the_arcid_went_stale(self):
        self._seed()
        # Same relative layout, different arcid -- exactly what happens when the
        # library is moved and the rows are rebuilt from the new paths.
        stale = self.meta / gmb.sidecar_filename("local-r44-stalehash")
        stale.write_text(
            json.dumps(
                {
                    "schema": gmb.SIDECAR_SCHEMA,
                    "arcid": "local-r44-stalehash",
                    "local_dir": self.rel,
                    "siglip": {"dim": gmb.SIGLIP_DIM, "cover": COVER, "page": PAGE},
                    "text": {"dim": gmb.TEXT_DIM, "vector": TEXT},
                    "meta": {"title": "From the backup"},
                    "history": [],
                }
            ),
            encoding="utf-8",
        )
        self._wipe()
        report = gmb.restore_sidecars()
        self.assertEqual(report["restored"], 1)
        self.assertTrue(self._row(self.arcid)["has_cover"])
        self.assertEqual(self._row(self.arcid)["raw"]["user_meta"]["title"], "From the backup")


if __name__ == "__main__":
    unittest.main()
