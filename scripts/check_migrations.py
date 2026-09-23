#!/usr/bin/env python3
"""Verify that the database has one versioned schema source and startup path."""
from __future__ import annotations
import hashlib
import re
import sys
from pathlib import Path

MIGRATIONS_REL = Path("Docker/main/textIngest/migrations")
BASELINE_SHA256 = "1b142aba7c6f07a3f7c72423ec69baf2ca61ffaf24319fd2141cbf2c4ed1fb52"
NAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
failures = []
checks = 0

def check(name, ok, detail=""):
    global checks
    checks += 1
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail and not ok else ""))
    if not ok:
        failures.append(name)

def read(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""

def digest(path):
    text = read(path).replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def main():
    root = Path(__file__).resolve().parents[1]
    mig = root / MIGRATIONS_REL
    names = sorted(p.name for p in mig.glob("*.sql"))
    check("single initial migration", names == ["0001_baseline.sql"], str(names))
    check("migration filenames valid", all(NAME_RE.match(n) for n in names))
    baseline = mig / "0001_baseline.sql"
    check("baseline checksum pinned", digest(baseline) == BASELINE_SHA256, digest(baseline))
    sql = read(baseline)
    for table in ("works", "read_events", "app_config", "ui_users", "ui_sessions", "ui_meta", "user_interactions", "user_profiles"):
        check(f"baseline creates {table}", f"CREATE TABLE IF NOT EXISTS {table}" in sql)
    check("baseline contains csrf_hash", "csrf_hash" in sql)
    check("removed Agent tables absent", "chat_history" not in sql and "semantic_memory" not in sql)
    text_ingest = root / "Docker/main/textIngest"
    check("schema tombstone absent", not (text_ingest / "schema.sql").exists())
    check("legacy bootstrap absent", not (text_ingest / "init_schema_once.sh").exists())
    engine = read(text_ingest / "db_migrations.py")
    check("engine owns schema_version", "SCHEMA_VERSION_TABLE" in engine)
    check("engine uses advisory lock", "pg_advisory_lock" in engine)
    check("engine is transactional", "conn.transaction()" in engine)
    check("engine supports dry run", "--dry-run" in engine)
    runner = read(text_ingest / "run_migrations.sh")
    check("runner fails hard by default", "DB_INIT_FAIL_HARD=${DB_INIT_FAIL_HARD:-1}" in runner)
    check("runner wires backup directory", "--backup-dir" in runner)
    entry = read(root / "Docker/main/entrypoint.sh")
    dockerfile = read(root / "Docker/main/Dockerfile")
    check("entrypoint runs migrations", "run_migrations.sh" in entry)
    check("Dockerfile installs runner", "/app/textIngest/run_migrations.sh" in dockerfile)
    check("Dockerfile has no legacy bootstrap", "init_schema_once.sh" not in dockerfile)
    auth = read(root / "Docker/main/webapi/services/auth_service.py")
    config = read(root / "Docker/main/webapi/services/config_service.py")
    setup = read(root / "Docker/main/webapi/services/setup_service.py")
    check("services delegate to schema guard", all("schema_guard" in value for value in (auth, config, setup)))
    print(f"\nTOTAL {checks - len(failures)}/{checks} passed")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
