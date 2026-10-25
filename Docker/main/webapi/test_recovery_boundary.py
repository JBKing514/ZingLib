#!/usr/bin/env python3
"""The recovery session is the most privileged-looking, least privileged session.

Recovery mode exists for one situation: the database is unreachable, so the
operator cannot log in, and the only way back is to repair the connection from
the settings screen. That session can therefore reach exactly four endpoints and
nothing else -- it is deliberately *narrower* than a normal user, not wider.

The report asked for the boundary to be tested explicitly. This does it without
a database, a server or a configured pepper, by driving `auth_guard` directly
with a stub request and a stubbed session lookup: the guard's decision is the
thing under test, not psycopg.

The CSRF half needs `DATA_UI_AUTH_PEPPER` to produce a *valid* token, so the
positive case reports SKIP when none is configured rather than pretending.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import patch

sys.path.insert(0, "/app")

from fastapi.responses import JSONResponse  # noqa: E402

from webapi.core import middleware  # noqa: E402
from webapi.core.middleware import (  # noqa: E402
    AUTH_CSRF_COOKIE_NAME,
    AUTH_COOKIE_NAME,
    RECOVERY_ALLOWED_ENDPOINTS,
)

FAILS: list[str] = []
CHECKS = 0
SKIPS: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  |  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def skip(label: str, why: str) -> None:
    SKIPS.append(label)
    print(f"SKIP  {label}  |  {why}")


def _request(path: str, method: str = "GET", csrf: str = "", with_csrf_header: bool = True):
    cookies = {AUTH_COOKIE_NAME: "RECV::1900000000::deadbeef"}
    headers: dict[str, str] = {}
    if csrf:
        cookies[AUTH_CSRF_COOKIE_NAME] = csrf
        if with_csrf_header:
            headers["x-csrf-token"] = csrf
    return types.SimpleNamespace(
        url=types.SimpleNamespace(path=path),
        method=method,
        cookies=cookies,
        headers=headers,
        state=types.SimpleNamespace(),
    )


async def _guard(req):
    async def call_next(_request):
        return JSONResponse({"ok": True}, status_code=200)

    return await middleware.auth_guard(req, call_next)


def _status(response) -> int:
    return int(getattr(response, "status_code", 0) or 0)


def _detail(response) -> str:
    try:
        payload = json.loads(bytes(response.body))
    except Exception:
        return ""
    return str(payload.get("detail") or "")


def _as_recovery(_dsn="", _token="", **_kw):
    return {"sid": "recovery_session", "uid": "recovery_uid", "username": "emergency_admin", "role": "recovery"}


# Every one of these is a normal user's route. A recovery session must not reach
# any of them; `/api/auth/account` is in SELF_SERVICE_PATHS, which makes it the
# most interesting case -- recovery is narrower than an ordinary login.
FORBIDDEN = [
    ("GET", "/api/local-lib/meta/list"),
    ("POST", "/api/local-lib/scan"),
    ("POST", "/api/system/restart"),
    ("DELETE", "/api/auth/account"),
    ("PUT", "/api/auth/profile"),
    ("POST", "/api/home/favorite/toggle"),
]


def main() -> int:
    print("=" * 78)
    print("P0: recovery session boundary")
    print("=" * 78)

    with patch.object(middleware, "auth_get_session_user", _as_recovery):
        print("\n--- everything outside the four allowed endpoints is refused ---")
        for method, path in FORBIDDEN:
            response = asyncio.run(_guard(_request(path, method)))
            check(
                _status(response) == 403 and "recovery mode" in _detail(response),
                f"{method} {path} -> 403 recovery mode",
                f"{_status(response)} {_detail(response)}",
            )

        print("\n--- the allowed endpoints still work ---")
        for path in sorted(RECOVERY_ALLOWED_ENDPOINTS):
            response = asyncio.run(_guard(_request(path, "GET")))
            check(_status(response) == 200, f"GET {path} -> passes the guard", str(_status(response)))

        print("\n--- a mutating allowed endpoint still needs CSRF ---")
        response = asyncio.run(_guard(_request("/api/auth/logout", "POST")))
        check(
            _status(response) == 403 and "csrf" in _detail(response),
            "no CSRF token -> 403 csrf verification failed",
            f"{_status(response)} {_detail(response)}",
        )
        response = asyncio.run(_guard(_request("/api/auth/logout", "POST", csrf="not-the-real-token")))
        check(
            _status(response) == 403 and "csrf" in _detail(response),
            "a forged CSRF token -> 403",
            f"{_status(response)} {_detail(response)}",
        )
        response = asyncio.run(_guard(_request("/api/auth/logout", "POST", csrf="whatever", with_csrf_header=False)))
        check(
            _status(response) == 403 and "csrf" in _detail(response),
            "a cookie with no matching header -> 403",
            f"{_status(response)} {_detail(response)}",
        )

        # A *valid* recovery CSRF is an HMAC over the token with the pepper. With
        # no pepper configured the token cannot be produced at all -- which also
        # means recovery login is unusable -- so this half is skipped honestly.
        pepper = ""
        try:
            pepper = str(middleware.auth_pepper() or "")
        except Exception:
            pepper = ""
        if pepper:
            from webapi.services.auth_service import issue_recovery_csrf

            token = "RECV::1900000000::deadbeef"
            csrf = issue_recovery_csrf(token, pepper=pepper)
            response = asyncio.run(_guard(_request("/api/auth/logout", "POST", csrf=csrf)))
            check(
                _status(response) == 200,
                "a valid recovery CSRF passes",
                f"{_status(response)} {_detail(response)}",
            )
        else:
            skip("a valid recovery CSRF passes", "DATA_UI_AUTH_PEPPER is not configured")

    print("\n" + "=" * 78)
    print(f"{CHECKS} checks, {len(SKIPS)} skipped")
    if FAILS:
        print(f"FAILED {len(FAILS)}/{CHECKS}")
        for name in FAILS:
            print("  - " + name)
        return 1
    print("ALL CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
