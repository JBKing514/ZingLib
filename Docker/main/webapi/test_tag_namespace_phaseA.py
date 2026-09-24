#!/usr/bin/env python3
"""
Regression test for phase A of local tag namespaces:
- known aliases still normalize to builtin namespaces
- unknown namespaces are preserved instead of collapsing to other
- hand-picked tags are stored marker-less (`ns:tag`) and mirrored into the
  raw.user_meta.tags ledger that survives a metadata enrich / tag re-apply
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.local_lib import local_lib_meta_batch_update
    from webapi.services.db_service import query_rows
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.local_lib import local_lib_meta_batch_update
    from webapi.services.db_service import query_rows


ARCID = "test_tag_namespace_phase_a"


def cleanup() -> None:
    query_rows("DELETE FROM read_events WHERE arcid = %s", (ARCID,))
    query_rows("DELETE FROM works WHERE arcid = %s", (ARCID,))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_row() -> tuple[list[str], dict]:
    row = query_rows("SELECT tags, raw FROM works WHERE arcid = %s LIMIT 1", (ARCID,))
    data = (row[0] or {}) if row else {}
    tags = [str(x or "").strip() for x in (data.get("tags") or []) if str(x or "").strip()]
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    return tags, raw


def ledger_of(raw: dict) -> list[str]:
    user_meta = raw.get("user_meta") if isinstance(raw.get("user_meta"), dict) else {}
    return [str(x or "").strip() for x in (user_meta.get("tags") or []) if str(x or "").strip()]


def main() -> int:
    print("=" * 72)
    print("Phase A tag namespace regression")
    print("=" * 72)
    cleanup()
    try:
        print("[1] Creating fixture row")
        query_rows(
            "INSERT INTO works (arcid, title, tags, raw, local_dir, source, date_added) "
            "VALUES (%s, %s, %s::text[], %s::jsonb, %s, 'local', %s)",
            (
                ARCID,
                "Namespace Fixture",
                ["category:manga"],
                json.dumps({}, ensure_ascii=False),
                "",
                1710003000,
            ),
        )

        print("[2] Writing builtin alias + custom namespace tags")
        res = local_lib_meta_batch_update(
            {
                "arcids": [ARCID],
                "add_user_tags": ["\u7537\u6027:test-built-in", "studio:color-script"],
                "remove_user_tags": [],
                "clear_user_title": False,
            }
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        assert_true(int(res.get("done") or 0) == 1, "batch update did not complete")

        print("[3] Verifying stored tags are marker-less")
        tags, raw = read_row()
        lowered = [t.lower() for t in tags]
        assert_true("male:test-built-in" in lowered, "known alias did not normalize to male")
        assert_true("studio:color-script" in lowered, "custom namespace collapsed unexpectedly")
        assert_true("other:color-script" not in lowered, "custom namespace should not fall back to other")
        assert_true(
            not [t for t in lowered if t.startswith("user:")],
            "no tag may still carry the retired `user:` marker",
        )

        print("[4] Verifying the hidden ledger mirrors the hand-picked tags")
        ledger = [t.lower() for t in ledger_of(raw)]
        assert_true("male:test-built-in" in ledger, "builtin tag missing from the user_meta ledger")
        assert_true("studio:color-script" in ledger, "custom tag missing from the user_meta ledger")
        assert_true(
            "category:manga" not in ledger,
            "the ledger must only hold hand-picked tags, not ComicInfo-derived ones",
        )

        print("[5] Verifying custom namespace removal still works")
        res2 = local_lib_meta_batch_update(
            {
                "arcids": [ARCID],
                "add_user_tags": [],
                "remove_user_tags": ["studio:color-script"],
                "clear_user_title": False,
            }
        )
        print(json.dumps(res2, ensure_ascii=False, indent=2))
        tags2, raw2 = read_row()
        lowered2 = [t.lower() for t in tags2]
        assert_true("studio:color-script" not in lowered2, "custom namespace tag removal failed")
        assert_true("male:test-built-in" in lowered2, "removal took an unrelated tag with it")
        ledger2 = [t.lower() for t in ledger_of(raw2)]
        assert_true("studio:color-script" not in ledger2, "removed tag left behind in the ledger")

        print("[6] Verifying a legacy `user:` removal request still lands")
        query_rows(
            "UPDATE works SET tags = %s::text[] WHERE arcid = %s",
            (["category:manga", "user:male:test-built-in"], ARCID),
        )
        res3 = local_lib_meta_batch_update(
            {
                "arcids": [ARCID],
                "add_user_tags": [],
                "remove_user_tags": ["male:test-built-in"],
                "clear_user_title": False,
            }
        )
        print(json.dumps(res3, ensure_ascii=False, indent=2))
        tags3, _raw3 = read_row()
        assert_true(
            not [t for t in (x.lower() for x in tags3) if t.startswith("user:")],
            "a pre-marker row must be cleanable by its marker-less name",
        )

        print("[OK] Phase A tag namespace regression passed")
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
