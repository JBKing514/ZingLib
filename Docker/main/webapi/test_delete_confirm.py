#!/usr/bin/env python3
"""Deleting a gallery needs consent in the request body, not just in the dialog.

`POST /api/local-lib/delete` can remove the gallery's files from disk. Both UI
entry points show a confirmation dialog, but the endpoint itself accepted any
POST with an arcid -- so a stray request, a replay, or a future caller that
skipped the dialog could delete a user's files. The rebuild route already
required `confirm: true`; this brings the other destructive route in line.

The check runs before the row lookup, which is what makes this test DB-free: a
request without the flag is refused without touching the database.

    python -m webapi.test_delete_confirm
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from fastapi import HTTPException  # noqa: E402

from webapi.routers.local_lib import delete_local_gallery  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  |  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def refusal(payload) -> tuple[int, str]:
    """Run the route and report how it refused (it must never succeed here)."""
    try:
        delete_local_gallery(payload)
    except HTTPException as exc:
        return int(exc.status_code), str(exc.detail)
    return 0, "NO REFUSAL"


def main() -> int:
    print("=" * 78)
    print("P0: gallery delete requires an explicit confirmation")
    print("=" * 78)

    cases = [
        ({}, "an empty body"),
        ({"arcid": "local-abc"}, "an arcid but no confirmation"),
        ({"arcid": "local-abc", "delete_files": True}, "delete_files without confirmation"),
        ({"arcid": "local-abc", "confirm": False}, "confirmation set to false"),
        # Consent has to be the boolean. `"true"` and `1` are the shapes a sloppy
        # caller produces, and neither is an intentional "yes".
        ({"arcid": "local-abc", "confirm": "true"}, 'confirmation as the string "true"'),
        ({"arcid": "local-abc", "confirm": 1}, "confirmation as the number 1"),
        (None, "no payload at all"),
    ]
    for payload, label in cases:
        status, detail = refusal(payload)
        check(status == 400 and "confirmation" in detail, f"refused: {label}", f"{status} {detail}")

    print("\n--- confirmation is only the first gate ---")
    status, detail = refusal({"confirm": True})
    check(status == 400 and "arcid" in detail, "a confirmed call still needs an arcid", f"{status} {detail}")

    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)}/{CHECKS}")
        for name in FAILS:
            print("  - " + name)
        return 1
    print(f"ALL {CHECKS} CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
