#!/usr/bin/env python3
"""Error-response hygiene and cookie security, without a database.

These two rules are easy to regress by "just adding the traceback back in while
debugging", so they are pinned by behaviour rather than by grepping source:

  * an error response carries a request id and no stack by default;
  * the debug switch (env or saved config) is what re-enables the stack;
  * an unhandled error never echoes the raw exception text by default, because
    that text can quote a DSN, a filesystem path or a provider payload;
  * the session cookie is `Secure` automatically once the request arrived over
    TLS, and an explicit switch still forces it on over plain HTTP.

No DB and no httpx, so it runs both inside the image and in a local venv:

    python -m webapi.test_p0_error_and_cookie
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, "/app")

from fastapi import HTTPException  # noqa: E402

import webapi.main as main  # noqa: E402
from webapi.core.middleware import _auth_cookie_secure  # noqa: E402

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


class _Url:
    def __init__(self, scheme: str) -> None:
        self.scheme = scheme

    def __str__(self) -> str:
        return f"{self.scheme}://test/api/probe"


def _request(scheme: str = "http") -> types.SimpleNamespace:
    req = types.SimpleNamespace()
    req.state = types.SimpleNamespace()
    req.url = _Url(scheme)
    return req


def _body(response) -> dict:
    return json.loads(bytes(response.body))


def _as_dict(resp) -> dict:
    return _body(resp)


def main_test() -> int:
    print("=" * 78)
    print("P0: error hygiene + cookie security")
    print("=" * 78)

    tmpdir = Path(tempfile.mkdtemp(prefix="zgl-p0-"))
    real_config = main.APP_CONFIG_FILE
    saved_env = os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)
    try:
        cfg = tmpdir / "app_config.json"
        main.APP_CONFIG_FILE = cfg

        print("\n--- the switch is closed by default ---")
        check(main._expose_error_details() is False, "no env and no saved config -> off")

        cfg.write_text(json.dumps({"values": {"DATA_UI_EXPOSE_TRACEBACK": "1"}}), encoding="utf-8")
        check(main._expose_error_details() is True, "saved config '1' -> on")

        cfg.write_text(json.dumps({"values": {"DATA_UI_EXPOSE_TRACEBACK": "0"}}), encoding="utf-8")
        check(main._expose_error_details() is False, "saved config '0' -> off")

        os.environ["DATA_UI_EXPOSE_TRACEBACK"] = "1"
        check(main._expose_error_details() is True, "env '1' wins over the saved '0'")
        os.environ["DATA_UI_EXPOSE_TRACEBACK"] = "0"
        check(main._expose_error_details() is False, "env '0' wins too")
        os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)

        print("\n--- a 500 hides the stack but hands back an id ---")
        cfg.unlink(missing_ok=True)
        try:
            raise RuntimeError("dsn=postgresql://user:hunter2@db/x")
        except RuntimeError:
            exc = HTTPException(status_code=500, detail="boom")
        resp = asyncio.run(main._http_exception_with_traceback(_request(), exc))
        payload = _as_dict(resp)
        check(payload.get("traceback") is None, "no traceback in the body")
        check(bool(payload.get("request_id")), "the body carries a request id", str(payload.get("request_id")))
        check(
            resp.headers.get(main.REQUEST_ID_HEADER) == payload.get("request_id"),
            "the header and the body agree on the id",
        )

        print("\n--- with the switch on, the stack comes back ---")
        os.environ["DATA_UI_EXPOSE_TRACEBACK"] = "1"
        # The handler reads `traceback.format_exc()`, which only has a stack
        # while the exception is being handled -- FastAPI calls handlers from
        # inside its own `except`, so the probe has to do the same. Calling it
        # after the block yields "NoneType: None" and tests nothing.
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            exc = HTTPException(status_code=500, detail="boom")
            payload = _as_dict(asyncio.run(main._http_exception_with_traceback(_request(), exc)))
        check("Traceback" in str(payload.get("traceback") or ""), "traceback is present when asked for")
        os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)

        print("\n--- unexpected validation errors stay quiet even with the switch on ---")
        os.environ["DATA_UI_EXPOSE_TRACEBACK"] = "1"
        try:
            raise ValueError("no recognizable images")
        except ValueError:
            exc = HTTPException(
                status_code=422,
                detail={"code": "no_recognizable_images", "message": "nope", "suppress_traceback": True},
            )
        payload = _as_dict(asyncio.run(main._http_exception_with_traceback(_request(), exc)))
        check(payload.get("traceback") is None, "suppress_traceback still wins over the switch")
        os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)

        print("\n--- an unhandled error never echoes the raw text by default ---")
        secret = "postgresql://postgres:postgres@db/secret"
        try:
            raise RuntimeError(f"connect failed for {secret}")
        except RuntimeError as exc:
            resp = asyncio.run(main._unhandled_exception_with_traceback(_request(), exc))
        payload = _as_dict(resp)
        check(secret not in json.dumps(payload), "the DSN does not leak into the response")
        check("traceback" not in payload, "no traceback in the body")
        check(bool(payload.get("request_id")), "an id is still returned")

        os.environ["DATA_UI_EXPOSE_TRACEBACK"] = "1"
        try:
            raise RuntimeError(f"connect failed for {secret}")
        except RuntimeError as exc:
            payload = _as_dict(asyncio.run(main._unhandled_exception_with_traceback(_request(), exc)))
        text = json.dumps(payload)
        # The debug switch restores the *message*, not the credentials: a traceback
        # is for reading, and a password in a traceback is how a debugging aid
        # becomes a leak. The redactor runs on both paths.
        check("connect failed for" in text, "with the switch on, the message is returned", str(payload.get("detail")))
        check(":postgres@" not in text, "but the password is still masked", str(payload.get("detail")))
        os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)

        print("\n--- the cookie follows the scheme ---")
        check(_auth_cookie_secure({}, _request("https")) is True, "https request -> Secure")
        check(_auth_cookie_secure({}, _request("http")) is False, "plain http request -> not Secure")
        check(
            _auth_cookie_secure({"AUTH_COOKIE_SECURE": "1"}, _request("http")) is True,
            "the explicit switch still forces Secure over http",
        )
        check(_auth_cookie_secure({}, None) is False, "no request object -> not Secure")
    finally:
        main.APP_CONFIG_FILE = real_config
        if saved_env is None:
            os.environ.pop("DATA_UI_EXPOSE_TRACEBACK", None)
        else:
            os.environ["DATA_UI_EXPOSE_TRACEBACK"] = saved_env

    print("\n" + "=" * 78)
    if FAILURES:
        print(f"FAILED {len(FAILURES)}/{CHECKS}")
        for name in FAILURES:
            print("  - " + name)
        return 1
    print(f"ALL {CHECKS} CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_test())
