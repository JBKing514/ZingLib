#!/usr/bin/env python3
"""
Regression test for phase 6.3 custom category support.

- custom category values should survive metadata batch updates
- category tags and raw/comicinfo mirrors should stay aligned
- metadata list should expose the custom category
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import local_lib_meta_batch_update, local_lib_meta_list
    from webapi.services.db_service import query_rows
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import local_lib_meta_batch_update, local_lib_meta_list
    from webapi.services.db_service import query_rows


PREFIX = "test_phase63_"


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
        (arcid, title, tags, json.dumps(raw, ensure_ascii=False), "", 1710002000),
    )


def main() -> int:
    print("=" * 72)
    print("Phase 6.3 custom category regression")
    print("=" * 72)
    cleanup()
    try:
        arcid = f"{PREFIX}custom_category"
        print("[1] Creating local work fixture")
        insert_work(arcid, "Category Fixture", ["artist:test", "category:manga"], {"eh_raw": {"category": "manga"}})

        print("[2] Applying custom category through metadata batch update")
        result = local_lib_meta_batch_update(
            {
                "arcids": [arcid],
                "set_category": "light novel",
                "clear_category": False,
                "add_user_tags": [],
                "remove_user_tags": [],
                "clear_user_title": False,
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert_true(int(result.get("done") or 0) == 1, "custom category batch update did not affect the fixture")

        print("[3] Verifying DB mirrors")
        rows = query_rows(
            "SELECT tags, raw->'eh_raw'->>'category' AS category, raw->'comicinfo'->>'genre' AS genre "
            "FROM works WHERE arcid = %s LIMIT 1",
            (arcid,),
        )
        assert_true(bool(rows), "fixture row missing after update")
        row = rows[0]
        tags = [str(x or "").strip().lower() for x in (row.get("tags") or []) if str(x or "").strip()]
        assert_true("category:light novel" in tags, "custom category tag missing from tags array")
        assert_true(str(row.get("category") or "").strip().lower() == "light novel", "eh_raw category not synced")
        assert_true(str(row.get("genre") or "").strip().lower() == "light novel", "comicinfo genre not synced")

        print("[4] Verifying metadata list payload")
        payload = local_lib_meta_list(limit=10, offset=0, q=arcid)
        items = payload.get("items") or []
        assert_true(len(items) == 1, "metadata list did not return the fixture")
        assert_true(str(items[0].get("category") or "") == "light novel", "metadata list category did not expose custom category")

        print("[OK] Phase 6.3 custom category regression passed")
        return 0
    finally:
        print("[cleanup] removing phase 6.3 fixtures")
        cleanup()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
