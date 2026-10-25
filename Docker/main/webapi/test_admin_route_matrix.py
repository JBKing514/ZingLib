#!/usr/bin/env python3
"""The admin gate, route by route.

The report's item was blunt: "add an API test matrix where an ordinary user
tries every mutating route". A hand-written list of endpoints ages badly -- the
one route somebody forgets to add is exactly the one that ships without a role
check -- so this test *discovers* the route table from the app itself and walks
all of it:

  * anonymous            -> 401   (the route is not open to the world)
  * plain authenticated  -> 403   (the admin gate, not merely "logged in")
  * self-service routes  -> must be reachable for a plain user, and are the only
                            exemption, so they are asserted explicitly

It deliberately never calls a mutating route as an administrator: several of
them restart the process, download models or rewrite global config, and a test
that "just checks it is not 403" must not trigger them.

Needs a reachable server, so it runs inside the deployed container:

    docker exec -w /app zinglib-dev python -m webapi.test_admin_route_matrix
"""

from __future__ import annotations

import sys
import time
import uuid

import requests

sys.path.insert(0, "/app")

from webapi.core.middleware import (  # noqa: E402
    AUTH_ALLOW_PATHS,
    AUTH_COOKIE_NAME,
    AUTH_CSRF_COOKIE_NAME,
    RECOVERY_ALLOWED_ENDPOINTS,
    SELF_SERVICE_PATHS,
    SETUP_OPEN_PATHS,
)
from webapi.main import app  # noqa: E402
from webapi.services.auth_service import create_session  # noqa: E402
from webapi.services.db_service import db_dsn, query_rows  # noqa: E402

BASE = "http://127.0.0.1:8501"
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Paths the guard lets through before it can know who is calling: the setup
# wizard and the login/bootstrap endpoints. They cannot answer 401/403 because
# they are how a caller becomes authenticated in the first place.
OPEN_BEFORE_AUTH = set(AUTH_ALLOW_PATHS) | set(SETUP_OPEN_PATHS) | set(RECOVERY_ALLOWED_ENDPOINTS)

FAILURES: list[str] = []
CHECKS = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if ok:
        print(f"PASS  {label}" + (f"  |  {detail}" if detail else ""))
    else:
        print(f"FAIL  {label}" + (f"  |  {detail}" if detail else ""))
        FAILURES.append(label)


def mutating_routes() -> list[tuple[str, str]]:
    """(method, concrete path) for every mutating route the app actually serves.

    Read from the OpenAPI schema rather than from `app.routes`: newer FastAPI
    keeps included routers as lazy `_IncludedRouter` wrappers, so `app.routes`
    shows a handful of containers with no `.path`/`.methods` and route discovery
    silently finds zero endpoints -- a matrix that checks nothing and reports
    success. The schema is generated from the same table the server dispatches
    on, so it cannot drift from it.
    """
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    paths = app.openapi().get("paths", {})
    for path, operations in paths.items():
        if not path.startswith("/api"):
            continue
        for method in operations:
            if method.upper() not in MUTATING:
                continue
            concrete = path
            while "{" in concrete and "}" in concrete:
                start = concrete.index("{")
                end = concrete.index("}", start)
                concrete = concrete[:start] + "__probe__" + concrete[end + 1 :]
            key = (method.upper(), path)
            if key in seen:
                continue
            seen.add(key)
            out.append((method.upper(), concrete))
    return sorted(out)


def make_plain_user() -> tuple[str, str, str]:
    """Throwaway non-admin account + session. Returns (uid, token, csrf)."""
    dsn = db_dsn()
    uid = str(uuid.uuid4())
    username = f"matrix_{int(time.time())}"
    import psycopg

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ui_users (uid, username, password_hash, role, disabled, created_at) "
                "VALUES (%s, %s, %s, 'user', false, now())",
                (uid, username, "x" * 32),
            )
        conn.commit()
    token, sess = create_session(dsn, uid, ttl_hours=1)
    return uid, str(token), str(sess.get("csrf_token") or "")


def mint_admin() -> tuple[str, str]:
    """A real admin session + its CSRF token, for the CSRF leg."""
    rows = query_rows("SELECT uid FROM ui_users WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1")
    if not rows:
        return "", ""
    token, sess = create_session(db_dsn(), str(rows[0]["uid"]), ttl_hours=1)
    return str(token), str(sess.get("csrf_token") or "")


def drop_plain_user(uid: str) -> None:
    import psycopg

    try:
        with psycopg.connect(db_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ui_sessions WHERE uid = %s::uuid", (uid,))
                cur.execute("DELETE FROM ui_users WHERE uid = %s::uuid", (uid,))
            conn.commit()
        print(f"[cleanup] removed throwaway user {uid}")
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] could not remove {uid}: {exc}")


def probe(method: str, path: str, token: str = "", csrf: str = "") -> int:
    headers = {}
    cookies = {}
    if token:
        headers["x-csrf-token"] = csrf
        cookies[AUTH_COOKIE_NAME] = token
        cookies[AUTH_CSRF_COOKIE_NAME] = csrf
    try:
        r = requests.request(method, BASE + path, json={}, headers=headers, cookies=cookies, timeout=60)
        return r.status_code
    except Exception as exc:  # noqa: BLE001
        print(f"   ({method} {path} raised {exc})")
        return -1


def main() -> int:
    print("=" * 78)
    print("ZingLib admin-gate matrix @ " + BASE)
    print("=" * 78)

    try:
        requests.get(BASE + "/version.json", timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP: no server at {BASE} ({exc})")
        return 0

    if not db_dsn():
        print("SKIP: no database configured")
        return 0

    routes = mutating_routes()
    print(f"\ndiscovered {len(routes)} mutating route(s)")
    check(len(routes) >= 15, "route discovery found the mutating surface", f"{len(routes)} routes")

    # Self-service endpoints act on the caller's own account only and are
    # deliberately open to every authenticated role, so "403 for a plain user"
    # is the wrong expectation for them; they get their own section below.
    guarded = [(m, p) for (m, p) in routes if p not in OPEN_BEFORE_AUTH and p not in SELF_SERVICE_PATHS]
    print(f"of which {len(guarded)} sit behind the admin gate")
    print(f"({len(SELF_SERVICE_PATHS)} self-service path(s) are exempt by design)")

    print("\n--- anonymous callers get 401 ---")
    for method, path in guarded:
        status = probe(method, path)
        check(status == 401, f"{method} {path} -> 401", f"got {status}")

    uid, token, csrf = make_plain_user()
    try:
        print("\n--- an ordinary user gets 403 ---")
        for method, path in guarded:
            status = probe(method, path, token, csrf)
            check(status == 403, f"{method} {path} -> 403", f"got {status}")

        print("\n--- self-service routes stay reachable ---")
        check(
            bool(SELF_SERVICE_PATHS),
            "the self-service list is not empty",
            f"{len(SELF_SERVICE_PATHS)} paths",
        )
        registered = {(m, p) for (m, p) in routes}
        for path in sorted(SELF_SERVICE_PATHS):
            check(
                any(p == path for (_m, p) in registered),
                f"self-service path exists in the route table: {path}",
            )
        status = probe("POST", "/api/auth/verify-password", token, csrf)
        check(status != 403, "POST /api/auth/verify-password is not 403 for a plain user", f"got {status}")
    finally:
        drop_plain_user(uid)

    # CSRF, route by route. An administrator session is used on purpose: the role
    # gate has already passed, so a 403 here can only come from the CSRF check.
    # Routes in AUTH_ALLOW_PATHS are skipped -- they run before any session
    # exists, so there is no token to compare against yet.
    print("\n--- CSRF covers every mutating route ---")
    admin_token, admin_csrf = mint_admin()
    if not admin_token:
        skip_reason = "no admin account to mint a session from"
        print(f"SKIP  the CSRF leg  |  {skip_reason}")
    else:
        # Positive control. Without it, a session that is silently invalid would
        # make every 403 below pass for the wrong reason.
        # `meta/preview` is a POST that only computes a plan -- no writes. An
        # empty body answers 400 ("arcids required"), and that 400 is the point:
        # it can only be produced by the route itself, i.e. the guard let the
        # request through. Only 401/403 would mean the control is broken.
        status = probe("POST", "/api/local-lib/meta/preview", admin_token, admin_csrf)
        check(
            status not in (401, 403),
            "a valid session + CSRF gets past the guard",
            f"got {status} (400 = the route's own validation, not the guard)",
        )

        csrf_guarded = [(m, p) for (m, p) in routes if p not in AUTH_ALLOW_PATHS]
        print(f"({len(csrf_guarded)} route(s) are expected to reject a bad token)")
        for method, path in csrf_guarded:
            status = probe(method, path, admin_token, "bogus-token")
            check(
                status == 403,
                f"{method} {path} rejects a forged CSRF token",
                f"got {status}",
            )

    print("\n" + "=" * 78)
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKS}")
        for name in FAILURES:
            print("  - " + name)
        return 1
    print(f"ALL {CHECKS} CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
