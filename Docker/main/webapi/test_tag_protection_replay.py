#!/usr/bin/env python3
"""
Regression: a hand-picked tag must survive the two paths that rebuild
`works.tags` from the ComicInfo source.

`enrich_local_work_metadata` (重新获取元数据) and `tag_reapply_service`
(标签重放) both recompute `works.tags` as `source tags || PROTECTED_TAGS_SQL`.
That used to be the job of the `user:` prefix the editor wrote, which is now
retired: the editor mirrors hand-picked tags into `raw.user_meta.tags` and the
fragment has to read them from there.

This has to be guarded because a miss is completely silent -- the refetch or
the re-apply reports success and the tag is simply gone.

Four cases:
  1. ledger present             -> ledger tags survive a rebuild
  2. no ledger, pre-marker row  -> legacy `user:` tags survive
  3. ledger present but not an array -> no crash, contributes nothing
  4. both spellings at once     -> union, deduped, source tags kept
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.services.db_service import query_rows
    from webapi.services.local_lib_service import PROTECTED_TAGS_SQL
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.services.db_service import query_rows
    from webapi.services.local_lib_service import PROTECTED_TAGS_SQL


ARCID = "test_tag_protection_replay"

# The exact shape both rebuild paths use: the freshly picked ComicInfo tags,
# then everything the protected fragment adds back.
_REBUILD_SQL = (
    "UPDATE works AS w SET tags = ("
    "  SELECT ARRAY("
    "    SELECT t FROM unnest("
    "      COALESCE(%s::text[], ARRAY[]::text[]) "
    "      || " + PROTECTED_TAGS_SQL + " "
    "    ) AS t "
    "    WHERE COALESCE(btrim(t), '') <> '' "
    "    GROUP BY t "
    "    ORDER BY lower(t)"
    "  )"
    ") WHERE arcid = %s"
)


def cleanup() -> None:
    query_rows("DELETE FROM read_events WHERE arcid = %s", (ARCID,))
    query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def seed(tags: list[str], raw: dict) -> None:
    query_rows(
        "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added) "
        "VALUES (%s, %s, %s::text[], %s::jsonb, %s, 'local', %s)",
        (ARCID, "Tag Protection Fixture", tags, json.dumps(raw, ensure_ascii=False), "", 1710005000),
    )


def rebuild(source_tags: list[str]) -> list[str]:
    """Run the rebuild both services perform, keeping only the tag column work."""
    query_rows(_REBUILD_SQL, (source_tags, ARCID))
    row = query_rows("SELECT tags FROM works WHERE arcid = %s LIMIT 1", (ARCID,))
    return [str(x or "").strip() for x in ((row[0] or {}).get("tags") or []) if str(x or "").strip()]


def main() -> int:
    print("=" * 72)
    print("Hand-picked tag protection across metadata rebuilds")
    print("=" * 72)
    cleanup()
    try:
        print("[1] A ledger tag survives a rebuild that does not know about it")
        seed(["category:manga"], {"user_meta": {"tags": ["female:\u5de8\u4e73", "other:\u624b\u7ed8"]}})
        tags = rebuild(["male:solo"])
        print(tags)
        assert_true("female:\u5de8\u4e73" in tags, "ledger tag was dropped by the rebuild")
        assert_true("other:\u624b\u7ed8" in tags, "second ledger tag was dropped by the rebuild")
        assert_true("male:solo" in tags, "the freshly picked source tag must still be there")
        assert_true("category:manga" not in tags, "a stale tag must be replaced by the rebuild")

        print("[2] A pre-marker row keeps its `user:` tags with no ledger at all")
        query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))
        seed(["category:manga", "user:male:legacy-kept"], {})
        tags = rebuild(["male:solo"])
        print(tags)
        assert_true("user:male:legacy-kept" in tags, "an old row lost its hand-picked tag to the rebuild")
        assert_true("male:solo" in tags, "the freshly picked source tag must still be there")

        print("[3] A malformed ledger contributes nothing instead of raising")
        query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))
        seed(["category:manga"], {"user_meta": {"tags": "not-an-array"}})
        tags = rebuild(["male:solo"])
        print(tags)
        assert_true(tags == ["male:solo"], f"unexpected tags for a malformed ledger: {tags}")

        print("[4] Both spellings are unioned and deduped")
        query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))
        seed(
            ["category:manga", "user:male:legacy-kept"],
            {"user_meta": {"tags": ["female:\u5de8\u4e73", "male:legacy-kept"]}},
        )
        tags = rebuild(["male:solo", "female:\u5de8\u4e73"])
        print(tags)
        assert_true("female:\u5de8\u4e73" in tags, "ledger tag missing after a mixed rebuild")
        assert_true("user:male:legacy-kept" in tags, "legacy tag missing after a mixed rebuild")
        assert_true("male:legacy-kept" in tags, "ledger spelling of the legacy tag missing")
        assert_true("male:solo" in tags, "source tag missing after a mixed rebuild")
        assert_true(
            len(tags) == len({t.lower() for t in tags}),
            f"rebuild produced case-duplicate tags: {tags}",
        )

        print("[5] Both rebuild paths still carry the protected fragment")
        from webapi.services import local_lib_service, tag_reapply_service

        assert_true(
            PROTECTED_TAGS_SQL in tag_reapply_service._UPDATE_SQL,
            "tag_reapply_service no longer re-adds hand-picked tags",
        )
        enrich_src = Path(local_lib_service.__file__).read_text(encoding="utf-8")
        assert_true(
            "PROTECTED_TAGS_SQL" in enrich_src
            and enrich_src.count('+ PROTECTED_TAGS_SQL + "') >= 1,
            "enrich_local_work_metadata no longer re-adds hand-picked tags",
        )
        assert_true(
            "user:%%" in PROTECTED_TAGS_SQL,
            "the legacy `user:` branch must stay until every pre-marker row is rewritten",
        )

        print("[OK] hand-picked tag protection regression passed")
        return 0
    finally:
        print("[cleanup] removing fixture row")
        cleanup()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
