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


class MatchTierTests(unittest.TestCase):
    """The four-tier sidecar -> gallery match, as pure data.

    A move changes both the arcid (a hash of the path) and the relative path, so
    the two exact tiers stop working and only content or a name can identify the
    gallery. Every tier here is ordered by how strong its claim is, and the
    weaker ones must never be allowed to win over a stronger one.
    """

    LIVE = [
        {"arcid": "local-a", "local_dir": "Uploads/Box/Alpha"},
        {"arcid": "local-b", "local_dir": "Inbox/Beta"},
    ]
    HASHES = {
        "Uploads/Box/Alpha": "h-alpha",
        "Inbox/Beta": "h-beta",
    }

    def _index(self, live=None, hashes=None):
        return gmb.build_match_index(
            live if live is not None else self.LIVE,
            cover_hash_of=lambda rel: (hashes if hashes is not None else self.HASHES).get(rel, ""),
        )

    def test_tier_one_wins_on_the_relative_path(self):
        target, tier = gmb.resolve_sidecar_match(
            self._index(),
            sidecar_rel="Uploads/Box/Alpha",
            sidecar_arcid="local-stale-and-wrong",
            sidecar_cover_hash="h-beta",
        )
        self.assertEqual((target, tier), ("local-a", gmb.MATCH_BY_PATH))

    def test_tier_two_wins_when_only_the_arcid_survives(self):
        # The parent was renamed, so `local_dir` moved -- but the row was rebuilt
        # from the same path and got its old hash back.
        target, tier = gmb.resolve_sidecar_match(
            self._index(),
            sidecar_rel="Old/Parent/Alpha",
            sidecar_arcid="local-a",
            sidecar_cover_hash="",
        )
        self.assertEqual((target, tier), ("local-a", gmb.MATCH_BY_ARCDID))

    def test_tier_three_follows_the_cover_when_the_folder_moved(self):
        target, tier = gmb.resolve_sidecar_match(
            self._index(),
            sidecar_rel="Uploads/Box/Alpha",
            sidecar_arcid="local-stale",
            sidecar_cover_hash="h-alpha",
        )
        # The path still exists in this fixture, so tier 1 answers -- move it.
        self.assertEqual(tier, gmb.MATCH_BY_PATH)

        moved = [
            {"arcid": "local-a", "local_dir": "Moved/Elsewhere/Alpha"},
            {"arcid": "local-b", "local_dir": "Inbox/Beta"},
        ]
        hashes = {"Moved/Elsewhere/Alpha": "h-alpha", "Inbox/Beta": "h-beta"}
        target, tier = gmb.resolve_sidecar_match(
            self._index(moved, hashes),
            sidecar_rel="Uploads/Box/Alpha",
            sidecar_arcid="local-stale",
            sidecar_cover_hash="h-alpha",
        )
        self.assertEqual((target, tier), ("local-a", gmb.MATCH_BY_COVER_HASH))

    def test_tier_four_needs_a_unique_folder_name(self):
        moved = [
            {"arcid": "local-a", "local_dir": "Moved/Alpha"},
            {"arcid": "local-b", "local_dir": "Inbox/Beta"},
        ]
        target, tier = gmb.resolve_sidecar_match(
            self._index(moved, {}),
            sidecar_rel="Uploads/Box/Alpha",
            sidecar_arcid="local-stale",
            sidecar_cover_hash="",
        )
        self.assertEqual((target, tier), ("local-a", gmb.MATCH_BY_NAME))

    def test_an_ambiguous_folder_name_refuses_to_guess(self):
        ambiguous = [
            {"arcid": "local-a", "local_dir": "A/Shared"},
            {"arcid": "local-c", "local_dir": "B/Shared"},
        ]
        target, tier = gmb.resolve_sidecar_match(
            self._index(ambiguous, {}),
            sidecar_rel="Z/Shared",
            sidecar_arcid="local-stale",
            sidecar_cover_hash="",
        )
        self.assertEqual((target, tier), ("", ""), "two candidates is not a match")

    def test_an_ambiguous_cover_fingerprint_refuses_to_guess(self):
        # Two galleries holding byte-identical covers identify neither.
        twins = [
            {"arcid": "local-a", "local_dir": "A/Twin"},
            {"arcid": "local-c", "local_dir": "B/Twin"},
        ]
        target, tier = gmb.resolve_sidecar_match(
            self._index(twins, {"A/Twin": "same", "B/Twin": "same"}),
            sidecar_rel="Z/Gone",
            sidecar_arcid="local-stale",
            sidecar_cover_hash="same",
        )
        self.assertEqual((target, tier), ("", ""), "an ambiguous fingerprint is not a match")

    def test_an_empty_fingerprint_never_matches_everything(self):
        # A gallery whose page 1 could not be read stores no hash at all. If ""
        # were indexed, every unfingerprintable gallery would match every other.
        live = [{"arcid": "local-a", "local_dir": "A/Nohash"}]
        index = self._index(live, {"A/Nohash": ""})
        # The name tier must still work; the hash tier must not have a "" entry.
        self.assertNotIn("", index["by_hash"])
        target, tier = gmb.resolve_sidecar_match(
            index,
            sidecar_rel="Z/Gone",
            sidecar_arcid="",
            sidecar_cover_hash="",
        )
        self.assertEqual((target, tier), ("", ""))

    def test_a_stronger_tier_is_never_overridden_by_a_weaker_one(self):
        # The path points at one gallery and the fingerprint at another: the path
        # is the sidecar's own statement about where it lives and must win.
        target, tier = gmb.resolve_sidecar_match(
            self._index(),
            sidecar_rel="Uploads/Box/Alpha",
            sidecar_arcid="local-b",
            sidecar_cover_hash="h-beta",
        )
        self.assertEqual((target, tier), ("local-a", gmb.MATCH_BY_PATH))

    def test_build_match_index_reports_what_each_tier_resolved(self):
        index = self._index()
        self.assertEqual(index["by_rel"]["Inbox/Beta"], "local-b")
        self.assertEqual(index["by_arcid"]["local-a"], "Uploads/Box/Alpha")
        self.assertEqual(index["by_name"]["Alpha"], ["local-a"])
        self.assertEqual(index["by_hash"]["h-beta"], "local-b")

    def test_cover_hash_is_a_pure_function_of_the_first_page(self):
        # Only the head and tail matter; the middle must not shift the digest.
        import io

        def digest(payload: bytes) -> str:
            return gmb._hash_reader(io.BytesIO(payload))

        head = b"\xff\xd8\xff\xe0" + b"a" * 100
        self.assertEqual(digest(head), digest(head))
        self.assertNotEqual(digest(head), digest(b"\xff\xd8\xff\xe0" + b"b" * 100))
        self.assertEqual(digest(b""), "", "an empty file has no fingerprint")

    def test_cover_hash_of_a_directory_uses_the_first_page_in_natural_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gallery = root / "lib" / "R44 Cover Order"
            gallery.mkdir(parents=True)
            # page 10 must not sort before page 2, or the "cover" would be an
            # arbitrary inner page and the fingerprint would drift with the sort.
            (gallery / "2.jpg").write_bytes(b"PAGE-TWO" * 40)
            (gallery / "10.jpg").write_bytes(b"PAGE-TEN" * 40)
            (gallery / "1.jpg").write_bytes(b"PAGE-ONE" * 40)
            (gallery / "notes.txt").write_bytes(b"not an image")
            with patch.object(gmb, "LOCAL_LIB_DIR", root / "lib"):
                digest = gmb.gallery_cover_hash("R44 Cover Order")
                expected = gmb._hash_reader(__import__("io").BytesIO((gallery / "1.jpg").read_bytes()))
            self.assertTrue(digest)
            self.assertEqual(digest, expected)


class RoundTripTests(unittest.TestCase):
    """Needs Postgres. Skips -- never fails -- when there is none."""

    arcid = "local-r44-roundtrip"
    bare_arcid = "local-r44-nosidecar"
    orphan_arcid = "local-r44-orphan"
    # A gallery whose folder is moved: a fresh row under a new path gets a new
    # arcid, while the sidecar still names the old one.
    moved_arcid = "local-r44-moved"
    moved_rel = "r44-selftest/after-the-move"
    twin_a_arcid = "local-r44-twin-a"
    twin_b_arcid = "local-r44-twin-b"
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
        # Both the module attribute and the sidecar lookup have to point at the
        # temp dir: `restore_sidecars` resolves the directory once and threads it
        # through, so a patched module attribute alone would be bypassed.
        self._patch = patch.object(gmb, "meta_dir", lambda create=False: self.meta)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self._cleanup()
        self.addCleanup(self._cleanup)

    def _all_arcids(self):
        return [
            self.arcid,
            self.bare_arcid,
            self.orphan_arcid,
            self.moved_arcid,
            self.twin_a_arcid,
            self.twin_b_arcid,
        ]

    def _cleanup(self):
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                # read_events cascades from works, so this is the whole cleanup.
                cur.execute(
                    "DELETE FROM works WHERE arcid = ANY(%s::text[])",
                    (self._all_arcids(),),
                )
            conn.commit()

    def _restore(self, **kwargs):
        """Restore with a synthetic fingerprint map.

        The fixture galleries have no files on disk, so the cover tier is driven
        by an injected map instead of real images. `cover_hash_of` is the seam
        the production code already threads through for exactly this reason.
        """
        kwargs.setdefault("cover_hash_of", lambda _rel: "")
        return gmb.restore_sidecars(meta={"meta_dir": self.meta}, **kwargs)

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

        preview = self._restore(dry_run=True)
        self.assertEqual(preview["restored"], 0, "a dry run must not write")
        self.assertFalse(self._row(self.arcid)["has_cover"])
        self.assertEqual(preview["matched"], 1)
        self.assertIn(self.bare_arcid, [r["arcid"] for r in preview["no_sidecar"]])

        report = self._restore()
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
        again = self._restore()
        self.assertEqual(again["history_rows"], 0)
        self.assertEqual(self._history(self.arcid), 2)

    def test_report_rows_name_the_gallery_and_the_outcome(self):
        self._seed()
        self.assertTrue(gmb.write_sidecar(self.arcid, model_id="selftest-siglip"))
        self._wipe()
        rows = []
        report = self._restore(detail_sink=lambda kind, item: rows.append(item))
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
        report = self._restore()

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
        report = self._restore()
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
        report = self._restore()
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
        report = self._restore()
        self.assertEqual(report["restored"], 1)
        self.assertTrue(self._row(self.arcid)["has_cover"])
        self.assertEqual(self._row(self.arcid)["raw"]["user_meta"]["title"], "From the backup")

    # --- the move fallbacks -------------------------------------------------
    #
    # A move is the case the two exact tiers cannot survive: the path changed, so
    # the arcid (a hash of it) changed with it, and `local_dir` no longer points
    # anywhere the sidecar recognises. These tests cover the two inferences.

    def _seed_row(self, arcid: str, rel: str, title: str) -> None:
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO works (arcid, title, tags, raw, local_dir, source, last_seen_at) "
                    "VALUES (%s, %s, ARRAY[]::text[], '{}'::jsonb, %s, 'local', now()) "
                    "ON CONFLICT (arcid) DO UPDATE SET local_dir = EXCLUDED.local_dir, "
                    "source = 'local'",
                    (arcid, title, rel),
                )
            conn.commit()

    def _wipe_many(self, arcids) -> None:
        with self.psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE works SET visual_embedding = NULL, page_visual_embedding = NULL, "
                    "desc_embedding = NULL, cover_embedding_status = 'pending', "
                    "raw = '{}'::jsonb WHERE arcid = ANY(%s::text[])",
                    (list(arcids),),
                )
            conn.commit()

    def _write_sidecar_file(self, arcid: str, local_dir: str, **extra) -> None:
        body = {
            "schema": gmb.SIDECAR_SCHEMA,
            "arcid": arcid,
            "local_dir": local_dir,
            "siglip": {"dim": gmb.SIGLIP_DIM, "cover": COVER, "page": PAGE},
            "text": {"dim": gmb.TEXT_DIM, "vector": TEXT},
            "meta": {"title": "Survived the move"},
            "history": [],
        }
        body.update(extra)
        (self.meta / gmb.sidecar_filename(arcid)).write_text(
            json.dumps(body), encoding="utf-8"
        )

    def test_restore_follows_the_cover_hash_when_the_folder_moved(self):
        # The user moved the gallery, then re-scanned: the live row has the new
        # path and a new arcid. Only page 1 is still the same file.
        self._seed_row(self.moved_arcid, self.moved_rel, "Moved gallery")
        self._write_sidecar_file(
            "local-r44-old-path",
            "r44-selftest/before-the-move",
            cover_hash="shared-cover-fingerprint",
        )
        self._wipe_many([self.moved_arcid])

        def fingerprint(rel):
            return "shared-cover-fingerprint" if rel == self.moved_rel else ""

        report = self._restore(cover_hash_of=fingerprint)

        matched = [r for r in report["no_sidecar"] if r["arcid"] == self.moved_arcid]
        self.assertEqual(matched, [], "the cover tier must have found this gallery")
        self.assertEqual(report["matched_by_tier"][gmb.MATCH_BY_COVER_HASH], 1)
        self.assertEqual(report["matched_by_tier"][gmb.MATCH_BY_PATH], 0)
        row = self._row(self.moved_arcid)
        self.assertTrue(row["has_cover"], "the vectors came back across the move")
        self.assertEqual(row["raw"]["user_meta"]["title"], "Survived the move")

    def test_restore_falls_back_to_a_unique_folder_name(self):
        # No fingerprint available (an older sidecar, or an unreadable cover):
        # the folder name is the only thing left, and it is unique here. The
        # sidecar's own path must differ, or tier 1 would answer first and this
        # would not be exercising the fallback at all.
        self._seed_row(self.moved_arcid, "r44-selftest/box-b/moved-gallery-unique", "Moved gallery")
        self._write_sidecar_file("local-r44-old-path", "r44-selftest/box-a/moved-gallery-unique")
        self._wipe_many([self.moved_arcid])

        report = self._restore()
        self.assertEqual(report["matched_by_tier"][gmb.MATCH_BY_NAME], 1)
        self.assertEqual(report["matched_by_tier"][gmb.MATCH_BY_PATH], 0)
        self.assertTrue(self._row(self.moved_arcid)["has_cover"])

    def test_a_duplicated_folder_name_is_left_as_an_orphan(self):
        # Two galleries share a name. Guessing would put one gallery's vectors on
        # the other, so the sidecar must be reported, not applied.
        self._seed_row(self.twin_a_arcid, "r44-selftest/twin-alpha/shared-name", "Twin A")
        self._seed_row(self.twin_b_arcid, "r44-selftest/twin-beta/shared-name", "Twin B")
        self._write_sidecar_file("local-r44-old-path", "r44-selftest/gone/shared-name")
        self._wipe_many([self.twin_a_arcid, self.twin_b_arcid])

        report = self._restore()
        self.assertGreaterEqual(report["orphan_count"], 1)
        orphan = [r for r in report["orphan_sidecars"] if r["arcid"] == "local-r44-old-path"]
        self.assertEqual(len(orphan), 1)
        self.assertEqual(orphan[0]["status"], "orphan")
        self.assertIn("unique name", orphan[0]["reason"])
        self.assertFalse(self._row(self.twin_a_arcid)["has_cover"])
        self.assertFalse(self._row(self.twin_b_arcid)["has_cover"])

    def test_a_written_sidecar_omits_an_unfingerprintable_cover(self):
        # This fixture gallery has no files on disk, so page 1 cannot be read and
        # the hash is "" -- which must be *omitted*, not stored. An empty string
        # in the index would make every unfingerprintable gallery match every
        # other one, which is worse than having no fallback at all.
        self._seed()
        self.assertTrue(
            gmb.write_sidecar(
                self.arcid, model_id="selftest-siglip", meta={"meta_dir": self.meta}
            )
        )
        on_disk = json.loads(
            (self.meta / gmb.sidecar_filename(self.arcid)).read_text(encoding="utf-8")
        )
        self.assertEqual(gmb.gallery_cover_hash(self.rel), "")
        self.assertNotIn("cover_hash", on_disk)

    def test_a_written_sidecar_records_a_readable_cover(self):
        # And the positive half: when page 1 *is* readable, the fingerprint is
        # written. Without this the fallback would ship silently disabled.
        with tempfile.TemporaryDirectory() as tmp:
            lib = Path(tmp) / "lib"
            gallery = lib / self.rel
            gallery.mkdir(parents=True)
            (gallery / "1.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"cover" * 200)
            (gallery / "2.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"page2" * 200)
            with patch.object(gmb, "LOCAL_LIB_DIR", lib):
                digest = gmb.gallery_cover_hash(self.rel)
                self.assertTrue(digest, "a readable page 1 must produce a fingerprint")
                row = {
                    "arcid": self.arcid,
                    "local_dir": self.rel,
                    "raw": {},
                    "cover_vec": gmb.vector_literal(COVER),
                    "page_vec": gmb.vector_literal(PAGE),
                    "text_vec": "",
                }
                with patch.object(gmb, "_read_events_for", return_value=[]):
                    payload = gmb.build_payload(row)
            self.assertEqual(payload.get("cover_hash"), digest)

    def test_write_sidecar_targets_the_overridden_directory(self):
        # The `meta` override exists so a round trip cannot touch a real library;
        # if it were ignored the file would land next to the user's galleries.
        self._seed()
        self.assertTrue(gmb.write_sidecar(self.arcid, meta={"meta_dir": self.meta}))
        self.assertTrue((self.meta / gmb.sidecar_filename(self.arcid)).is_file())
        self.assertEqual(
            gmb.sidecar_path(self.arcid, meta={"meta_dir": self.meta}),
            self.meta / gmb.sidecar_filename(self.arcid),
        )


if __name__ == "__main__":
    unittest.main()
