#!/usr/bin/env python3
"""
Regression test for dashboard title sync.

Verifies that:
1. local_lib_meta_batch_update() persists a user title into works.raw.user_meta.title
2. /api/home/local equivalent logic returns the user title in XP mode
3. title sorting also prefers the user title over the official title
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import local_lib_meta_batch_update
    from webapi.routers.system import home_local
    from webapi.services.db_service import query_rows
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import local_lib_meta_batch_update
    from webapi.routers.system import home_local
    from webapi.services.db_service import query_rows


TEST_ARCID = "test_dashboard_title_regression"
OFFICIAL_TITLE = "Official Dashboard Title"
USER_TITLE = "User Override Title"


def _zero_vector(dim: int = 1152) -> str:
    return "[" + ",".join(["0"] * dim) + "]"


def cleanup() -> None:
    query_rows("DELETE FROM read_events WHERE arcid = %s", (TEST_ARCID,))
    query_rows("DELETE FROM works WHERE arcid = %s", (TEST_ARCID,))


def setup_test_work() -> None:
    payload = {
        "eh_raw": {
            "title": OFFICIAL_TITLE,
            "title_jpn": "",
            "category": "manga",
        }
    }
    query_rows(
        "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added, visual_embedding, cover_embedding_status) "
        "VALUES (%s, %s, %s::text[], %s::jsonb, %s, %s, %s, %s::vector, %s) "
        "ON CONFLICT (arcid) DO UPDATE SET "
        "title = EXCLUDED.title, "
        "tags = EXCLUDED.tags, "
        "raw = EXCLUDED.raw, "
        "local_dir = EXCLUDED.local_dir, "
        "source = EXCLUDED.source, "
        "date_added = EXCLUDED.date_added, "
        "visual_embedding = EXCLUDED.visual_embedding, "
        "cover_embedding_status = EXCLUDED.cover_embedding_status, "
        "last_seen_at = now()",
        (
            TEST_ARCID,
            OFFICIAL_TITLE,
            ["artist:test", "tag:regression", "category:manga"],
            json.dumps(payload, ensure_ascii=False),
            "",
            "local",
            1710000000,
            _zero_vector(),
            "complete",
        ),
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def find_item_paged(
    request: Any,
    *,
    sort_by: str,
    sort_order: str,
    page_size: int = 50,
    max_pages: int = 20,
) -> dict:
    """Walk home_local pages until the test arcid shows up.

    A freshly inserted work has no read history, so on the ``xp`` axis it sorts
    to the very end of a populated library. Asserting on the first page would
    make this test depend on the size of the surrounding database, so page
    through the cursor instead (which also exercises pagination for real).
    """
    cursor = ""
    for _ in range(max_pages):
        payload = home_local(
            request,
            cursor=cursor,
            limit=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
            include_categories="",
            include_tags="",
            min_rating=0.0,
        )
        for item in list(payload.get("items") or []):
            if str(item.get("arcid") or "") == TEST_ARCID:
                return item
        cursor = str(payload.get("next_cursor") or "")
        if not cursor:
            break
    raise AssertionError(f"item not found in feed: {TEST_ARCID} (sort_by={sort_by})")


def main() -> int:
    print("=" * 72)
    print("Dashboard title regression test")
    print("=" * 72)
    cleanup()
    try:
        print("[1] Creating test work row")
        setup_test_work()

        print("[2] Applying user title through local_lib_meta_batch_update")
        result = local_lib_meta_batch_update(
            {
                "arcids": [TEST_ARCID],
                "set_user_title": USER_TITLE,
                "clear_user_title": False,
                "add_user_tags": [],
                "remove_user_tags": [],
            }
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        assert_true(int(result.get("done") or 0) == 1, "batch update did not report success")

        print("[3] Verifying DB raw.user_meta.title")
        rows = query_rows("SELECT title, raw FROM works WHERE arcid = %s", (TEST_ARCID,))
        assert_true(bool(rows), "test work missing after update")
        raw = rows[0].get("raw") or {}
        user_title = ""
        if isinstance(raw, dict):
            user_meta = raw.get("user_meta") if isinstance(raw.get("user_meta"), dict) else {}
            user_title = str(user_meta.get("title") or "").strip()
        assert_true(user_title == USER_TITLE, f"expected DB user title {USER_TITLE!r}, got {user_title!r}")

        fake_request = SimpleNamespace(state=SimpleNamespace(auth_user={"uid": "regression-user"}))

        print("[4] Verifying home_local XP feed")
        xp_item = find_item_paged(fake_request, sort_by="xp", sort_order="desc")
        print(json.dumps(xp_item, ensure_ascii=False, indent=2))
        assert_true(str(xp_item.get("title") or "") == USER_TITLE, "XP feed did not expose user title")
        assert_true(str(xp_item.get("user_title") or "") == USER_TITLE, "XP feed lost user_title field")

        print("[5] Verifying home_local title sort")
        title_item = find_item_paged(fake_request, sort_by="title", sort_order="asc")
        print(json.dumps(title_item, ensure_ascii=False, indent=2))
        assert_true(str(title_item.get("title") or "") == USER_TITLE, "title-sorted feed did not expose user title")
        assert_true(str(title_item.get("official_title") or "") == OFFICIAL_TITLE, "official title fallback changed unexpectedly")

        print("[OK] Dashboard title regression passed")
        return 0
    finally:
        print("[cleanup] removing test rows")
        cleanup()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
