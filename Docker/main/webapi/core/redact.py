"""Mask credentials before text reaches a log file or an error response.

The report's P0 list ends with "check whether sensitive information can appear in
logs or in exception responses". It can, in three ways, and all three are ordinary
code rather than carelessness:

* a DSN carries its password in the URL userinfo, and psycopg quotes the whole
  connection string back in several of its errors;
* a task log records a child process's stderr, which may echo the environment;
* a route turns an exception into ``detail=str(exc)``, so whatever the driver
  said becomes the body the browser shows.

Redaction happens at the two boundaries rather than at each of the call sites: the
error handler masks the outgoing detail, and the log writers mask the text they
persist. Anything that reaches disk or the client through those doors is covered,
including code that has not been written yet.
"""

from __future__ import annotations

import re
from typing import Any

REPLACEMENT = "***"

# scheme://user:password@host  -- keep the scheme and the user, drop the password.
_DSN_USERINFO = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)(?P<user>[^:/@\s]+):(?P<pw>[^@/\s]*)@"
)

# password=..., api_key: "...", POSTGRES_PASSWORD=... -- the shapes a connection
# string and a .env dump both use. The key may carry a prefix (`OPENAI_API_KEY`,
# `client_secret`), which is why it is matched as "a word ending in a secret
# word" rather than the bare word: a plain `\bapi_key\b` misses both, because the
# character before `API_KEY` is an underscore, not a boundary.
# Deliberately limited to key names that are secrets -- redacting every `key=`
# would eat legitimate log content.
_KEY_VALUE = re.compile(
    r"(?i)\b(?P<key>[A-Za-z0-9_]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|pepper|csrf))"
    r"(?P<sep>\s*[=:]\s*)"
    r"(?P<val>\"[^\"]*\"|'[^']*'|[^\s,;&\"'\]\)]+)"
)

# Authorization: Bearer <token>
_BEARER = re.compile(r"(?i)\b(?P<head>bearer\s+)(?P<tok>[A-Za-z0-9._\-]{8,})")


def redact_text(value: Any) -> str:
    """Return `value` as text with credential-shaped substrings masked."""
    text = "" if value is None else str(value)
    if not text:
        return ""
    text = _DSN_USERINFO.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:{REPLACEMENT}@", text)
    text = _KEY_VALUE.sub(lambda m: f"{m.group('key')}{m.group('sep')}{REPLACEMENT}", text)
    text = _BEARER.sub(lambda m: f"{m.group('head')}{REPLACEMENT}", text)
    return text


def redact_value(value: Any) -> Any:
    """Walk a JSON-ish structure and redact every string inside it.

    Used on `HTTPException.detail`, which is sometimes a plain string and
    sometimes a dict (`{"code": ..., "message": ...}`); both shapes end up in the
    response body.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    return value
