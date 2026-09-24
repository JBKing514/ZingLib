import os
import sys
import uuid
import time
from datetime import datetime, timezone
import psycopg

# TestClient is a test-only extra: starlette needs httpx (or httpx2) for it, and
# neither ships in the runtime image, which must stay free of unused HTTP clients.
# Import it lazily so the parts of this file that do not need an ASGI transport
# still run in a bare container.
try:
    from fastapi.testclient import TestClient
except Exception as _testclient_exc:  # pragma: no cover - depends on environment
    TestClient = None  # type: ignore[assignment]
    _TESTCLIENT_ERROR: Exception | None = _testclient_exc
else:
    _TESTCLIENT_ERROR = None

# Adjust path to import webapi modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webapi.main import app
from webapi.services.local_lib_service import _safe_join_local_dir
from webapi.services.db_service import db_dsn
from webapi.services.auth_service import _invalidate_bootstrap_cache, create_session, get_session_user
from webapi.core.middleware import AUTH_COOKIE_NAME, AUTH_CSRF_COOKIE_NAME


def skip_without_testclient(stage: str) -> bool:
    """True when a stage must be skipped because TestClient cannot be imported."""
    if TestClient is not None:
        return False
    print(f"SKIP {stage}: fastapi.testclient is unavailable ({_TESTCLIENT_ERROR})")
    print("     install the test extra: pip install -r Docker/main/requirements-dev.txt")
    return True


def test_path_length_error_suppression():
    print("--- Test 1: Path Length Error Suppression ---")
    long_path = "a" * 500
    try:
        _safe_join_local_dir(long_path)
        assert False, "Should have raised ValueError for too long file name"
    except ValueError as e:
        print(f"Success: Correctly raised ValueError: {e}")
        assert "too long" in str(e).lower()

    if skip_without_testclient("test 1 -- /api/local-lib/folder/mkdir probe"):
        return

    client = TestClient(app)
    # The route sits behind the auth middleware, so an anonymous request is
    # answered with 401 before the validation this test is about ever runs. That
    # is the state of any install that already has an admin; CI has none (a fresh
    # runtime dir), so the unauthenticated request reached the guard there and the
    # assertion only ever failed in a real container. Mint a session so the request
    # is answered by the path-length check on both.
    dsn = db_dsn()
    uid = str(uuid.uuid4())
    headers: dict[str, str] = {}
    try:
        if dsn:
            with psycopg.connect(dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO ui_users (uid, username, password_hash, role, disabled, created_at) "
                        "VALUES (%s::uuid, %s, 'hash', 'admin', false, now())",
                        (uid, f"testuser_mkdir_{int(time.time())}"),
                    )
                conn.commit()
            _invalidate_bootstrap_cache()
            token, sess = create_session(dsn, uid, ttl_hours=2)
            client.cookies.set(AUTH_COOKIE_NAME, token)
            client.cookies.set(AUTH_CSRF_COOKIE_NAME, str(sess.get("csrf_token") or ""))
            headers["x-csrf-token"] = str(sess.get("csrf_token") or "")
        response = client.post(
            "/api/local-lib/folder/mkdir",
            json={"parent_path": "", "name": long_path},
            headers=headers,
        )
        print(f"mkdir response status: {response.status_code}, body: {response.text}")
        assert response.status_code == 400, (
            f"expected the path-length guard to answer 400, got {response.status_code}: {response.text[:200]}"
        )
        payload = response.json()
        assert "too long" in str(payload.get("detail") or "").lower()
        assert "traceback" not in payload
    finally:
        if dsn:
            _drop_test_user(uid)


def _drop_test_user(uid: str) -> None:
    """Remove the throwaway user + session rows this test creates."""
    try:
        with psycopg.connect(db_dsn()) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ui_sessions WHERE uid = %s::uuid", (uid,))
                cur.execute("DELETE FROM ui_users WHERE uid = %s::uuid", (uid,))
            conn.commit()
        _invalidate_bootstrap_cache()
        print(f"[cleanup] removed test user {uid}")
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] could not remove test user {uid}: {exc}")


def test_sliding_session_renewal():
    print("--- Test 2: Sliding Session Renewal ---")
    dsn = db_dsn()
    if not dsn:
        print("Skip: Database not configured")
        return

    # Throwaway account: the flow under test needs a real ui_users row. It must
    # not outlive the run -- this fixture used to leave one admin user behind
    # per execution, which then showed up in the operator's user list.
    uid = str(uuid.uuid4())
    username = f"testuser_{int(time.time())}"
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ui_users (uid, username, password_hash, role, disabled, created_at) "
                    "VALUES (%s::uuid, %s, 'hash', 'admin', false, now())",
                    (uid, username),
                )
            conn.commit()
        _invalidate_bootstrap_cache()
        _sliding_session_renewal_body(dsn, uid)
    finally:
        _drop_test_user(uid)


def _sliding_session_renewal_body(dsn: str, uid: str) -> None:
    # Create session with TTL of 2 hours
    token, sess = create_session(dsn, uid, ttl_hours=2)
    sid = sess["sid"]
    csrf_token = sess["csrf_token"]
    print(f"Created session sid: {sid}, token: {token}")

    # Verify initial get_session_user does NOT extend (since remaining TTL is ~100%)
    user_info = get_session_user(dsn, token, ttl_hours=2)
    assert user_info is not None
    assert user_info["extended"] is False, "Should not extend when TTL is fresh"

    # Manually backdate expires_at in the database to 30 minutes in the future (remaining TTL < 50%)
    now = datetime.now(timezone.utc)
    short_expiry = now.timestamp() + 1800 # 30 mins
    short_expiry_dt = datetime.fromtimestamp(short_expiry, tz=timezone.utc)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ui_sessions SET expires_at=%s WHERE sid=%s::uuid",
                (short_expiry_dt, sid),
            )
        conn.commit()

    # Verify get_session_user now triggers extension
    user_info2 = get_session_user(dsn, token, ttl_hours=2)
    assert user_info2 is not None
    assert user_info2["extended"] is True, "Should extend session"

    # Verify expires_at in DB has been updated to ~2 hours in the future
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT expires_at FROM ui_sessions WHERE sid=%s::uuid", (sid,))
            db_exp = cur.fetchone()[0]
    time_diff = (db_exp - now).total_seconds()
    print(f"Extended expires_at is in {time_diff} seconds")
    assert 7000 < time_diff < 7300, "Expiration time should be extended to ~2 hours (7200 seconds)"

    if skip_without_testclient("test 2 -- Set-Cookie refresh probe"):
        return

    # Test via TestClient to verify cookies are set on response
    # Let's mock a GET request with cookies and see if response has updated Set-Cookie headers
    client = TestClient(app)
    # Reset expires_at to short duration
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE ui_sessions SET expires_at=%s WHERE sid=%s::uuid", (short_expiry_dt, sid))
        conn.commit()

    client.cookies.set(AUTH_COOKIE_NAME, token)
    client.cookies.set(AUTH_CSRF_COOKIE_NAME, csrf_token)
    # Request an authenticated page (e.g. get health db status)
    response = client.get("/api/health/db")
    print(f"API request response: {response.status_code}")
    print(f"Headers: {response.headers}")
    cookies = response.headers.get("set-cookie", "")
    print(f"Set-Cookie headers: {cookies}")
    assert AUTH_COOKIE_NAME in cookies, f"Should set new {AUTH_COOKIE_NAME} cookie"
    assert AUTH_CSRF_COOKIE_NAME in cookies, f"Should set new {AUTH_CSRF_COOKIE_NAME} cookie"
    print("Success: Cookies refreshed correctly in response")


def test_migration_timeout():
    """Obsolete: the manifest/migration router was removed in the local-only rewrite.

    The long-running-SQL timeout behaviour it covered no longer has a caller, and
    ``test_local_only_contract.test_legacy_migration_and_remote_health_are_absent``
    now asserts the migration endpoints stay gone. Kept as a marker so the removal
    is deliberate rather than an accident.
    """
    print("--- Test 3: Migration Timeout (skipped, subject removed) ---")


if __name__ == "__main__":
    test_path_length_error_suppression()
    test_sliding_session_renewal()
    test_migration_timeout()
    print("ALL TESTS PASSED SUCCESSFULLY!")
