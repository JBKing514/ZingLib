#!/usr/bin/env python3
"""
Regression test for phase 6.2:
- bulk category edits
- metadata gap filtering
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import local_lib_meta_batch_update, local_lib_meta_list
    from webapi.services.db_service import query_rows
    from webapi.services.local_lib_service import local_metadata_gaps
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import local_lib_meta_batch_update, local_lib_meta_list
    from webapi.services.db_service import query_rows
    from webapi.services.local_lib_service import local_metadata_gaps


PREFIX = "test_phase62_"


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def cleanup() -> None:
    query_rows("DELETE FROM read_events WHERE arcid LIKE %s", (f"{PREFIX}%",))
    query_rows("DELETE FROM works WHERE arcid LIKE %s", (f"{PREFIX}%",))


def insert_work(arcid: str, title: str, tags: list[str], raw: dict) -> None:
    query_rows(
        "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added) "
        "VALUES (%s, %s, %s::text[], %s::jsonb, %s, 'local', %s) "
        "ON CONFLICT (arcid) DO UPDATE SET "
        "title = EXCLUDED.title, tags = EXCLUDED.tags, raw = EXCLUDED.raw, "
        "local_dir = EXCLUDED.local_dir, source = EXCLUDED.source, date_added = EXCLUDED.date_added, last_seen_at = now()",
        (arcid, title, tags, json.dumps(raw, ensure_ascii=False), "", 1710001000),
    )


def arcids_of(payload: dict) -> set[str]:
    return {str(x.get("arcid") or "").strip() for x in (payload.get("items") or [])}


def main() -> int:
    print("=" * 72)
    print("Phase 6.2 metadata editor regression")
    print("=" * 72)
    cleanup()
    try:
        print("[1] Creating gap fixtures")
        insert_work(f"{PREFIX}no_title", "", [], {})
        insert_work(f"{PREFIX}no_category", "Has Title", ["artist:test"], {})
        insert_work(f"{PREFIX}no_tags", "Has Category Only", ["category:manga"], {"eh_raw": {"category": "manga"}})
        insert_work(f"{PREFIX}complete", "Complete", ["category:manga", "artist:test"], {"eh_raw": {"category": "manga"}})

        print("[2] Verifying gap filters")
        all_items = arcids_of(local_metadata_gaps(limit=50, offset=0, gap_type="all", q=PREFIX))
        title_items = arcids_of(local_metadata_gaps(limit=50, offset=0, gap_type="title", q=PREFIX))
        category_items = arcids_of(local_metadata_gaps(limit=50, offset=0, gap_type="category", q=PREFIX))
        tags_items = arcids_of(local_metadata_gaps(limit=50, offset=0, gap_type="tags", q=PREFIX))

        assert_true(f"{PREFIX}no_title" in all_items, "all gaps missing no_title fixture")
        assert_true(f"{PREFIX}no_category" in all_items, "all gaps missing no_category fixture")
        assert_true(f"{PREFIX}no_tags" in all_items, "all gaps missing no_tags fixture")
        assert_true(f"{PREFIX}complete" not in all_items, "all gaps should not include complete fixture")

        assert_true(title_items == {f"{PREFIX}no_title"}, f"unexpected no_title set: {title_items}")
        assert_true(category_items == {f"{PREFIX}no_title", f"{PREFIX}no_category"}, f"unexpected no_category set: {category_items}")
        assert_true(tags_items == {f"{PREFIX}no_title", f"{PREFIX}no_tags"}, f"unexpected no_tags set: {tags_items}")

        print("[3] Verifying bulk category edit")
        bulk_res = local_lib_meta_batch_update(
            {
                "arcids": [f"{PREFIX}no_category", f"{PREFIX}no_tags"],
                "set_category": "western",
                "clear_category": False,
                "add_user_tags": [],
                "remove_user_tags": [],
                "clear_user_title": False,
            }
        )
        print(json.dumps(bulk_res, ensure_ascii=False, indent=2))
        assert_true(int(bulk_res.get("done") or 0) == 2, "bulk category edit did not update both fixtures")

        rows = query_rows(
            "SELECT arcid, tags, raw->'eh_raw'->>'category' AS category FROM works WHERE arcid = ANY(%s::text[]) ORDER BY arcid ASC",
            ([f"{PREFIX}no_category", f"{PREFIX}no_tags"],),
        )
        for row in rows:
            tags = [str(x or "").strip().lower() for x in (row.get("tags") or []) if str(x or "").strip()]
            assert_true("category:western" in tags, f"western category tag missing for {row.get('arcid')}")
            assert_true(str(row.get("category") or "").strip().lower() == "western", f"raw category not synced for {row.get('arcid')}")

        print("[4] Verifying metadata editor list exposes category")
        list_payload = local_lib_meta_list(limit=20, offset=0, q=PREFIX)
        list_map = {str(x.get("arcid") or ""): x for x in (list_payload.get("items") or [])}
        assert_true(str((list_map.get(f"{PREFIX}no_category") or {}).get("category") or "") == "western", "meta list category not updated")
        assert_true(str((list_map.get(f"{PREFIX}no_tags") or {}).get("category") or "") == "western", "meta list category missing for category-only work")

        print("[OK] Phase 6.2 regression passed")
        return 0
    finally:
        print("[cleanup] removing phase 6.2 fixtures")
        cleanup()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
