"""Regaining control with a burn-after-use recovery code.

The account panel's change-password dialog offers a "forgot the password" tick.
When it is on, the gate field carries a recovery code instead of the current
password, and `POST /api/auth/recovery-password-change` rewrites the password
without ever seeing the old one.

Three properties make that safe, and each is a way the feature fails badly:

1. The code is *burned* -- a code that keeps working is a permanent skeleton key
   sitting in the config once the user believes they used it up.
2. A wrong code does not consume a good one, and does not touch the password.
3. The endpoint is reachable while the caller cannot remember their password,
   which is why it is a self-service route rather than an admin-only one -- but
   it still writes only the named account's hash.

No database is involved: the burn is exercised against the real
`check_recovery_login` reading a private temp config file (`_load_json_config`
/ `_save_json_config` are patched to it), and the write is captured by stubbing
`force_change_password_by_username`. The live container path is exercised by
`assets/probe_recovery_password_change.py`.
"""
import hashlib
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from webapi.core import middleware
from webapi.routers import auth as auth_router
from webapi.services import auth_service
from webapi.services import config_service


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class _RecoveryConfigFixture(unittest.TestCase):
    """A private in-memory replacement for the shipped JSON config."""

    def setUp(self):
        self.values = {"DATA_UI_RECOVERY_CODES": ",".join([_code_hash("burnt-once"), _code_hash("still-good")])}
        self.saves = 0

        def _load():
            return dict(self.values)

        def _save(vals):
            self.saves += 1
            self.values = dict(vals)

        for patcher in (
            patch.object(config_service, "_load_json_config", _load),
            patch.object(config_service, "_save_json_config", _save),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def stored(self) -> list[str]:
        raw = str(self.values.get("DATA_UI_RECOVERY_CODES", ""))
        return [h for h in raw.split(",") if h]


class BurnAfterUseTests(_RecoveryConfigFixture):
    def test_a_code_works_exactly_once(self):
        self.assertTrue(auth_service.check_recovery_login("burnt-once"))
        # The hash is gone from the stored set...
        self.assertNotIn(_code_hash("burnt-once"), self.stored())
        self.assertEqual(self.saves, 1, "the burn has to be persisted, not just returned")
        # ...so the same code is dead on the second attempt.
        self.assertFalse(auth_service.check_recovery_login("burnt-once"))

    def test_a_wrong_code_does_not_consume_a_good_one(self):
        self.assertFalse(auth_service.check_recovery_login("not-a-code"))
        self.assertEqual(self.saves, 0, "a miss must not rewrite the config")
        self.assertEqual(len(self.stored()), 2, "a miss must not spend a code")
        # ...and the good ones are still good.
        self.assertTrue(auth_service.check_recovery_login("still-good"))

    def test_burning_the_last_code_leaves_an_empty_set(self):
        self.assertTrue(auth_service.check_recovery_login("burnt-once"))
        self.assertTrue(auth_service.check_recovery_login("still-good"))
        self.assertEqual(self.stored(), [])
        self.assertFalse(auth_service.check_recovery_login("still-good"))

    def test_no_codes_configured_is_a_plain_miss(self):
        self.values["DATA_UI_RECOVERY_CODES"] = ""
        self.assertFalse(auth_service.check_recovery_login("anything"))
        self.assertFalse(auth_service.check_recovery_login(""))


class EndpointTests(_RecoveryConfigFixture):
    def setUp(self):
        super().setUp()
        self.calls = []

        def _force(dsn, username, new_password, pepper=""):
            self.calls.append({"dsn": dsn, "username": username, "new_password": new_password})

        app = FastAPI()
        app.include_router(auth_router.router)
        self.client = TestClient(app)
        for patcher in (
            patch.object(auth_router, "db_dsn", lambda: "postgres://fake/db"),
            patch.object(auth_router, "force_change_password_by_username", _force),
            patch.object(auth_router, "auth_pepper", lambda: "pepper"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, **body):
        return self.client.post("/api/auth/recovery-password-change", json=body)

    def test_a_valid_code_forces_the_password_and_names_the_account(self):
        r = self.post(username="admin", recovery_code="burnt-once", new_password="new-secret-1")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get("ok"))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["username"], "admin")
        self.assertEqual(self.calls[0]["new_password"], "new-secret-1")
        # ...and the code is spent.
        self.assertFalse(auth_service.check_recovery_login("burnt-once"))

    def test_an_invalid_code_changes_nothing(self):
        r = self.post(username="admin", recovery_code="nope", new_password="new-secret-1")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.calls, [], "a rejected code must not reach the write")

    def test_the_code_is_spent_even_though_the_old_password_was_never_sent(self):
        # The request model has no old-password field at all: the absence is the
        # feature, so assert it rather than trusting the signature.
        from webapi.core.schemas import AuthRecoveryPasswordChangeRequest
        self.assertNotIn("old_password", AuthRecoveryPasswordChangeRequest.model_fields)

    def test_missing_fields_are_rejected_before_anything_is_burned(self):
        for body in (
            {"username": "", "recovery_code": "burnt-once", "new_password": "x"},
            {"username": "admin", "recovery_code": "", "new_password": "x"},
        ):
            r = self.post(**body)
            self.assertEqual(r.status_code, 400, body)
        # The good code survived both malformed attempts.
        self.assertTrue(auth_service.check_recovery_login("burnt-once"))

    def test_a_failing_write_still_consumes_the_code(self):
        # The burn happens first on purpose: a code that stays usable because the
        # subsequent write happened to fail is the worse failure of the two.
        def _boom(*_a, **_k):
            raise ValueError("user not found")

        with patch.object(auth_router, "force_change_password_by_username", _boom):
            r = self.post(username="ghost", recovery_code="burnt-once", new_password="x")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(auth_service.check_recovery_login("burnt-once"))


class MiddlewareTests(unittest.TestCase):
    """The route must be reachable by a role that is not an administrator."""

    def test_it_is_a_self_service_path(self):
        # Without this the admin-only rule on every mutating route would answer
        # 403 before the handler ran -- and the user who needs the feature is
        # precisely the one who cannot log in as themselves.
        self.assertIn("/api/auth/recovery-password-change", middleware.SELF_SERVICE_PATHS)

    def test_it_is_not_an_unauthenticated_endpoint(self):
        # The opposite over-correction: adding it to AUTH_ALLOW_PATHS would let
        # anyone POST a code with no session at all.
        self.assertNotIn("/api/auth/recovery-password-change", middleware.AUTH_ALLOW_PATHS)

    def test_recovery_role_cannot_reach_it(self):
        # Recovery mode is pinned to a four-endpoint whitelist outside the
        # self-service set; the recovery *session* has no account behind it, so
        # there is nothing for it to reset and it must stay excluded.
        self.assertNotIn("/api/auth/recovery-password-change", middleware.RECOVERY_ALLOWED_ENDPOINTS)
        self.assertNotIn("/api/auth/recovery-password-change", middleware.SETUP_OPEN_PATHS)


if __name__ == "__main__":
    unittest.main()
