#!/usr/bin/env python3
"""Regression test: metadata-editor title sync reaches the local-library read path.

Scenario
--------
1. Insert a synthetic ``source='local'`` work that carries an official title.
2. Apply a user title through ``local_lib_meta_batch_update`` -- the endpoint the
   Metadata Editor calls.
3. Read it back through ``local_lib_meta_list`` -- the endpoint the Local Library
   page uses -- and assert ``user_title`` plus the derived ``display_title``.

History
-------
This file previously imported ``services.local_lib_service.batch_update_local_meta``.
That function no longer exists: the batch-meta logic moved into
``webapi.routers.local_lib.local_lib_meta_batch_update`` and
``services/local_lib_service.py`` kept only filesystem helpers. The old import
root (``services.*``) also broke package-relative imports, so the module could
not even be collected. It now drives the live router surface and covers a
different read path than ``test_dashboard_title_regression`` (which covers the
dashboard / XP feed).

Run as:  python -m webapi.test_title_sync_fix
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import (
        local_lib_meta_batch_update,
        local_lib_meta_list,
    )
    from webapi.services.db_service import query_rows
except ImportError:  # pragma: no cover - fallback for script-mode execution
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import (
        local_lib_meta_batch_update,
        local_lib_meta_list,
    )
    from webapi.services.db_service import query_rows


TEST_ARCID = "test_title_sync_fix"
TEST_LOCAL_DIR = "test_title_sync/fixture"
OFFICIAL_TITLE = "Official Title Sync Fixture"
USER_TITLE = "User Title Override"


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
        "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added, "
        "visual_embedding, cover_embedding_status) "
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
            ["artist:test", "tag:titlesync", "category:manga"],
            json.dumps(payload, ensure_ascii=False),
            TEST_LOCAL_DIR,
            "local",
            1710000000,
            _zero_vector(),
            "complete",
        ),
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def find_row(rows: list[dict]) -> dict:
    for row in rows or []:
        if str(row.get("arcid") or "") == TEST_ARCID:
            return row
    raise AssertionError(f"{TEST_ARCID} missing from /api/local-lib/meta/list payload")


def main() -> int:
    print("=" * 72)
    print("Metadata editor / local library title sync regression test")
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
        assert_true(int(result.get("done") or 0) == 1, "batch update did not report success")
        assert_true(int(result.get("failed") or 0) == 0, "batch update reported failures")

        print("[3] Verifying the raw.user_meta.title persisted")
        rows = query_rows("SELECT title, raw FROM works WHERE arcid = %s", (TEST_ARCID,))
        assert_true(bool(rows), "test work missing after update")
        raw = rows[0].get("raw") or {}
        stored = ""
        if isinstance(raw, dict):
            user_meta = raw.get("user_meta") if isinstance(raw.get("user_meta"), dict) else {}
            stored = str(user_meta.get("title") or "").strip()
        assert_true(stored == USER_TITLE, f"expected stored user title {USER_TITLE!r}, got {stored!r}")

        print("[4] Verifying /api/local-lib/meta/list exposes user + display title")
        listing = local_lib_meta_list(limit=200, offset=0, q=TEST_ARCID)
        assert_true(bool(listing.get("ok")), "meta list did not report ok")
        row = find_row(list(listing.get("items") or []))
        print(json.dumps(row, ensure_ascii=False, indent=2))
        assert_true(
            str(row.get("user_title") or "") == USER_TITLE,
            "meta list lost the user title",
        )
        assert_true(
            str(row.get("display_title") or "") == USER_TITLE,
            "meta list display_title did not prefer the user title",
        )
        assert_true(
            str(row.get("title") or "") == OFFICIAL_TITLE,
            "meta list stopped exposing the official title",
        )
        assert_true(
            str(row.get("local_dir") or "") == TEST_LOCAL_DIR,
            "meta list lost local_dir",
        )

        print("[5] Verifying clearing the user title falls back to the official one")
        cleared = local_lib_meta_batch_update(
            {
                "arcids": [TEST_ARCID],
                "set_user_title": None,
                "clear_user_title": True,
                "add_user_tags": [],
                "remove_user_tags": [],
            }
        )
        assert_true(int(cleared.get("done") or 0) == 1, "clear did not report success")
        listing2 = local_lib_meta_list(limit=200, offset=0, q=TEST_ARCID)
        row2 = find_row(list(listing2.get("items") or []))
        assert_true(
            str(row2.get("user_title") or "") == "",
            "user title was not cleared",
        )
        assert_true(
            str(row2.get("display_title") or "") == OFFICIAL_TITLE,
            "display_title did not fall back to the official title after clearing",
        )

        print("[OK] Title sync regression passed")
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
