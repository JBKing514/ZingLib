from __future__ import annotations

from typing import Any

import psycopg

from .auth_service import build_dsn
from .schema_guard import ensure_schema


def validate_db_connection(host: str, port: int, db: str, user: str, password: str, sslmode: str = "prefer") -> tuple[bool, str, str]:
    dsn = build_dsn(host=host, port=port, db=db, user=user, password=password, sslmode=sslmode)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ping")
                row = cur.fetchone()
                if row is None:
                    return False, "db ping failed", dsn
        return True, "ok", dsn
    except Exception as e:
        return False, str(e), dsn


def init_core_schema(dsn: str, schema_path: str = "") -> tuple[bool, str]:
    """Bring the database up to the schema this image expects.

    `schema_path` is still accepted so existing callers do not break, but it is
    ignored: the schema is a numbered set under textIngest/migrations/, applied
    in order. Honouring a single file here is what allowed a database to be left
    part-migrated, which is the failure this round removes.
    """
    s = str(dsn or "").strip()
    if not s:
        return False, "missing dsn"
    ok, msg = ensure_schema(s, force=True)
    if not ok:
        return False, msg
    return True, "schema initialized"
