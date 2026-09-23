#!/usr/bin/env python3
"""
Regression test for phase BC of local tag namespaces:
- namespace suggest endpoint returns builtin namespaces
- namespace suggest endpoint returns namespaces discovered from local works
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import local_lib_tag_namespace_suggest
    from webapi.services.db_service import query_rows
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import local_lib_tag_namespace_suggest
    from webapi.services.db_service import query_rows


ARCID = "test_tag_namespace_phase_bc"


def cleanup() -> None:
    query_rows("DELETE FROM read_events WHERE arcid = %s", (ARCID,))
    query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    print("=" * 72)
    print("Phase BC namespace suggestion regression")
    print("=" * 72)
    cleanup()
    try:
        print("[1] Creating fixture row with custom namespace tags")
        # `user:` rows are pre-marker leftovers, `circle:` is the shape written
        # today. Both must be counted, or the picker would stop offering a
        # namespace that clearly has works behind it.
        query_rows(
            "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added) "
            "VALUES (%s, %s, %s::text[], %s::jsonb, %s, 'local', %s)",
            (
                ARCID,
                "Namespace Suggest Fixture",
                ["category:manga", "user:studio:alpha", "circle:beta"],
                json.dumps({}, ensure_ascii=False),
                "",
                1710004000,
            ),
        )

        print("[2] Checking builtin suggestions")
        builtin = local_lib_tag_namespace_suggest(q="male", limit=10)
        builtin_keys = [str(x.get("key") or "") for x in (builtin.get("items") or [])]
        print(builtin_keys)
        assert_true("male" in builtin_keys, "builtin namespace 'male' missing from suggestions")

        print("[3] Checking custom namespace suggestions from DB")
        custom = local_lib_tag_namespace_suggest(q="studio", limit=10)
        custom_items = list(custom.get("items") or [])
        print(json.dumps(custom_items, ensure_ascii=False, indent=2))
        studio = next((x for x in custom_items if str(x.get("key") or "") == "studio"), None)
        assert_true(studio is not None, "custom namespace 'studio' missing from suggestions")
        assert_true(int(studio.get("count") or 0) >= 1, "custom namespace usage count was not reported")
        assert_true(bool(studio.get("builtin")) is False, "custom namespace should not be marked builtin")

        print("[4] Checking a marker-less namespace is discovered too")
        clean = local_lib_tag_namespace_suggest(q="circle", limit=10)
        clean_items = list(clean.get("items") or [])
        print(json.dumps(clean_items, ensure_ascii=False, indent=2))
        circle = next((x for x in clean_items if str(x.get("key") or "") == "circle"), None)
        assert_true(circle is not None, "a marker-less namespace must still be suggested")
        assert_true(int(circle.get("count") or 0) >= 1, "marker-less namespace usage count was not reported")
        assert_true(bool(circle.get("builtin")) is False, "a custom namespace should not be marked builtin")

        print("[OK] Phase BC namespace suggestion regression passed")
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
