#!/usr/bin/env python3
"""Credentials must not survive into a log file or an error body.

Pure string work, no database and no server, so it runs in the image and in a
local venv alike:

    python -m webapi.test_redaction
"""

from __future__ import annotations

import sys

sys.path.insert(0, "/app")

from webapi.core.redact import redact_text, redact_value  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  |  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def masked(text: str, needle: str = "hunter2") -> bool:
    return needle not in redact_text(text)


def main() -> int:
    print("=" * 78)
    print("P0: secret redaction")
    print("=" * 78)

    print("\n--- DSN userinfo ---")
    out = redact_text("postgresql://postgres:hunter2@db:5432/lrr_library?sslmode=disable")
    check("hunter2" not in out, "the password is gone", out)
    check("postgresql://postgres:***@db:5432/lrr_library?sslmode=disable" == out, "the rest is intact", out)
    out = redact_text("postgresql://postgres:@db:5432/x")
    check("postgresql://postgres:***@db:5432/x" == out, "an empty password is masked too", out)
    out = redact_text("redis://user:p%40ss@cache:6379/0")
    check("p%40ss" not in out, "a percent-encoded password is masked", out)

    print("\n--- the driver's own wording ---")
    msg = (
        "connection failed: host=db user=postgres password=hunter2 dbname=lrr_library\n"
        "OperationalError: could not connect to postgresql://postgres:hunter2@db:5432/x"
    )
    out = redact_text(msg)
    check("hunter2" not in out, "no password survives a multi-line driver error")
    check("host=db user=postgres" in out, "the non-secret context is kept", out.splitlines()[0])

    print("\n--- key=value and key: value ---")
    for raw in (
        "POSTGRES_PASSWORD=hunter2",
        "password: hunter2",
        'password: "hunter2"',
        "client_secret=hunter2",
        "OPENAI_API_KEY=sk-hunter2",
        "api-key=hunter2",
        "auth_token=hunter2",
        "DATA_UI_AUTH_PEPPER=hunter2",
        "csrf=hunter2",
        "db_pwd=hunter2",
    ):
        check(masked(raw), f"{raw.split('=')[0].split(':')[0]} is masked", redact_text(raw))

    print("\n--- bearer tokens ---")
    out = redact_text("Authorization: Bearer abcdef123456ghijkl")
    check("abcdef123456ghijkl" not in out, "the token is masked", out)

    print("\n--- things that are NOT secrets stay readable ---")
    for raw in (
        "postgresql://postgres:***@db/x",  # already masked, must stay stable
        "sslmode=disable",
        "user=postgres",
        "task=local_lib_scan status=failed reason=manual",
        "scan root not found: /app/runtime/local_lib/Gallery",
        "标签重放完成，共 120 个画廊",  # Chinese log text is untouched
    ):
        out = redact_text(raw)
        check(out == raw, f"unchanged: {raw[:42]}", out if out != raw else "")

    print("\n--- structures ---")
    value = {"message": "boom postgresql://postgres:hunter2@db/x", "items": ["token=hunter2", 42]}
    out = redact_value(value)
    check("hunter2" not in str(out), "dicts and lists are walked", str(out))
    check(out["items"][1] == 42, "non-strings pass through untouched")
    check(redact_value(None) is None and redact_text(None) == "", "None is safe")

    print("\n--- idempotent ---")
    once = redact_text("postgresql://postgres:hunter2@db/x password=hunter2")
    twice = redact_text(once)
    check(once == twice, "redacting twice changes nothing", twice)

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
