"""Versioned, re-entrant database migrations.

The migration state is stored in PostgreSQL rather than the container
filesystem. The runner:

* runs on **every** container start (nothing is remembered outside the DB);
* reads the applied set from the `schema_version` table, so only pending
  migrations are executed;
* applies each migration and its bookkeeping row in **one transaction**;
* takes an advisory lock, so two containers cannot migrate concurrently;
* refuses to start when the database is *ahead* of the image (rollback guard);
* writes a logical snapshot of the application tables before migrating.

Rules for migration files (see `migrations/README.md`):

* filename must be `NNNN_lower_snake.sql`;
* files are immutable once they have been applied anywhere -- the recorded
  checksum is compared on every start and a mismatch is reported as drift;
* `CREATE INDEX CONCURRENTLY` (and anything else that cannot run inside a
  transaction) is not supported here.

Run as a CLI:

    python db_migrations.py --dsn postgresql://... --migrations-dir .../migrations
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Distinct from auth_service's key: the two must never deadlock each other.
ADVISORY_LOCK_KEY = 874205932

MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
BASELINE_FILENAME = "0001_baseline.sql"

DEFAULT_MIGRATIONS_DIR = "/app/textIngest/migrations"
DEFAULT_LOG = "/app/runtime/logs/db_init.log"
DEFAULT_BACKUP_DIR = "/app/runtime/backups"
DEFAULT_APP_VERSION_FILE = "/app/webapi/static/version.json"

SCHEMA_VERSION_TABLE = "schema_version"
VERSION_TABLE_DDL = (
    f"CREATE TABLE IF NOT EXISTS {SCHEMA_VERSION_TABLE} ("
    "version     integer PRIMARY KEY,"
    "name        text NOT NULL,"
    "checksum    text NOT NULL DEFAULT '',"
    "app_version text NOT NULL DEFAULT '',"
    "applied_at  timestamptz NOT NULL DEFAULT now())"
)

# Application tables snapshotted before any migration runs. Order matters only
# for readability; a snapshot is a plain per-table COPY, not a FK-ordered dump.
BACKUP_TABLES = (
    "works",
    "read_events",
    "app_config",
    "ui_users",
    "ui_sessions",
    "ui_meta",
    "user_interactions",
    "user_profiles",
)


class MigrationError(RuntimeError):
    """Raised for problems that must stop the run (bad filenames, no dir...)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(sql: str) -> str:
    """Line-ending-insensitive text, so a CRLF checkout does not read as drift."""
    return sql.replace("\r\n", "\n").replace("\r", "\n")


def checksum_of(sql: str) -> str:
    return hashlib.sha256(_normalize(sql).encode("utf-8")).hexdigest()


def make_logger(log_path: str = ""):
    """Return (log(msg), lines) -- lines keeps the transcript for JSON output."""

    lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{_now()}] {msg}"
        lines.append(line)
        print(line)
        if not log_path:
            return
        try:
            p = Path(log_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            # Never let logging take the process down: the DB work matters more.
            pass

    return log, lines


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


@dataclass
class MigrationOutcome:
    ok: bool = True
    message: str = ""
    current: int = 0
    target: int = 0
    applied: list[int] = field(default_factory=list)
    pending: list[int] = field(default_factory=list)
    drift: list[int] = field(default_factory=list)
    gaps: list[int] = field(default_factory=list)
    downgrade_blocked: bool = False
    backup_dir: str = ""
    app_version: str = ""
    changes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "message": self.message,
            "current": self.current,
            "target": self.target,
            "applied": self.applied,
            "pending": self.pending,
            "drift": self.drift,
            "gaps": self.gaps,
            "downgrade_blocked": self.downgrade_blocked,
            "backup_dir": self.backup_dir,
            "app_version": self.app_version,
        }


def discover_migrations(migrations_dir: str | os.PathLike) -> list[Migration]:
    d = Path(migrations_dir)
    if not d.is_dir():
        raise MigrationError(f"migrations dir not found: {d}")

    items: list[Migration] = []
    seen: dict[int, str] = {}
    for p in sorted(d.glob("*.sql")):
        m = MIGRATION_RE.match(p.name)
        if not m:
            raise MigrationError(
                f"bad migration filename {p.name!r}: expected NNNN_lower_snake.sql"
            )
        version = int(m.group(1))
        if version < 1:
            raise MigrationError(f"migration version must be >= 1: {p.name}")
        if version in seen:
            raise MigrationError(
                f"duplicate migration version {version}: {seen[version]} and {p.name}"
            )
        sql = _normalize(p.read_text(encoding="utf-8"))
        items.append(Migration(version, m.group(2), p, sql, checksum_of(sql)))
        seen[version] = p.name

    if not items:
        raise MigrationError(f"no migrations found in {d}")
    items.sort(key=lambda x: x.version)
    return items


def find_gaps(migrations: list[Migration]) -> list[int]:
    """Numbers missing between 1 and max. A gap is a deploy mistake, not fatal."""
    versions = {m.version for m in migrations}
    return [v for v in range(1, max(versions) + 1) if v not in versions]


def read_app_version(explicit: str = "", version_file: str = "") -> str:
    if str(explicit or "").strip():
        return str(explicit).strip()
    env = os.environ.get("APP_VERSION", "").strip()
    if env:
        return env
    candidates = [str(version_file or "").strip(), DEFAULT_APP_VERSION_FILE]
    for cand in candidates:
        if not cand:
            continue
        try:
            data = json.loads(Path(cand).read_text(encoding="utf-8"))
        except Exception:
            continue
        v = str(data.get("version", "")).strip()
        if v:
            return v
    return ""


def _connect(dsn: str, connect_timeout: int = 15):
    import psycopg

    return psycopg.connect(dsn, connect_timeout=connect_timeout, autocommit=True)


def _read_applied(conn) -> dict[int, str]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT version, checksum FROM {SCHEMA_VERSION_TABLE}")
        return {int(v): str(c or "") for v, c in cur.fetchall()}


def _table_exists(conn, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
        row = cur.fetchone()
    return bool(row and row[0])


def snapshot_tables(conn, backup_dir: str, app_version: str, current: int, target: int,
                    keep: int = 3, tables=BACKUP_TABLES, log=print) -> str:
    """Logical snapshot of the application tables, as gzipped CSV per table.

    Deliberately dependency-free: the app image ships libpq but not the
    postgresql-client tools, and a pg15 client cannot dump a pg17 server, so a
    Python COPY is the only route that works without dragging in PGDG.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(backup_dir) / f"pre_{current}_to_{target}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    manifest = {
        "created_at": _now(),
        "app_version": app_version,
        "from_schema_version": current,
        "to_schema_version": target,
        "tables": {},
        "missing_tables": [],
    }
    for name in tables:
        if not _table_exists(conn, name):
            manifest["missing_tables"].append(name)
            continue
        dest = out / f"{name}.csv.gz"
        rows = 0
        # Binary write: COPY yields raw blocks that can split a multi-byte
        # character, so decoding per block would be wrong.
        with gzip.open(dest, "wb") as fh:
            with conn.cursor() as cur:
                with cur.copy(
                    f"COPY (SELECT * FROM {name}) TO STDOUT WITH (FORMAT csv, HEADER)"
                ) as cp:
                    for block in cp:
                        fh.write(bytes(block))
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {name}")
            rows = int(cur.fetchone()[0])
        manifest["tables"][name] = {"rows": rows, "bytes": dest.stat().st_size}

    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if keep > 0:
        snaps = sorted(
            (p for p in Path(backup_dir).glob("pre_*") if p.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in snaps[keep:]:
            try:
                for child in old.iterdir():
                    child.unlink()
                old.rmdir()
                log(f"INFO backup pruned: {old.name}")
            except Exception as e:  # pragma: no cover - best effort housekeeping
                log(f"WARN backup prune failed for {old.name}: {e}")

    total = sum(v["bytes"] for v in manifest["tables"].values())
    log(
        f"INFO backup written: {out} "
        f"tables={len(manifest['tables'])} bytes={total} missing={len(manifest['missing_tables'])}"
    )
    return str(out)


def apply_pending(
    dsn: str,
    *,
    migrations_dir: str = DEFAULT_MIGRATIONS_DIR,
    log_path: str = "",
    connect_timeout: int = 15,
    backup_dir: str = "",
    backup_keep: int = 3,
    require_backup: bool = False,
    allow_downgrade: bool = False,
    app_version: str = "",
    app_version_file: str = "",
    dry_run: bool = False,
    statement_timeout: str = "5min",
) -> tuple[MigrationOutcome, list[str]]:
    log, lines = make_logger(log_path)
    out = MigrationOutcome()

    dsn = str(dsn or "").strip()
    if not dsn:
        out.ok = False
        out.message = "missing dsn"
        log("WARN db-init skipped: POSTGRES_DSN is empty")
        return out, lines

    try:
        migrations = discover_migrations(migrations_dir)
    except MigrationError as e:
        out.ok = False
        out.message = str(e)
        log(f"ERROR db-init failed: {e}")
        return out, lines

    out.target = max(m.version for m in migrations)
    out.gaps = find_gaps(migrations)
    if out.gaps:
        log(f"WARN migration numbering has gaps: {out.gaps}")

    out.app_version = read_app_version(app_version, app_version_file)

    conn = None
    try:
        conn = _connect(dsn, connect_timeout)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = '{statement_timeout}'")
            cur.execute("SET lock_timeout = '30s'")
            cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        try:
            with conn.cursor() as cur:
                cur.execute(VERSION_TABLE_DDL)

            applied = _read_applied(conn)
            out.current = max(applied) if applied else 0

            # Rollback guard: the database knows migrations this image does not.
            if applied and max(applied) > out.target:
                if not allow_downgrade:
                    out.ok = False
                    out.downgrade_blocked = True
                    out.message = (
                        f"database schema v{max(applied)} is newer than this image's "
                        f"v{out.target}; refusing to run. Set DB_INIT_ALLOW_DOWNGRADE=1 "
                        f"(or ALLOW_DOWNGRADE=1) only if you know the older code is compatible."
                    )
                    log(f"ERROR db-init blocked: {out.message}")
                    return out, lines
                log(
                    f"WARN database schema v{max(applied)} is newer than this image's "
                    f"v{out.target}; continuing because allow-downgrade is set"
                )

            out.drift = sorted(
                m.version
                for m in migrations
                if m.version in applied and applied[m.version] and applied[m.version] != m.checksum
            )
            if out.drift:
                log(
                    "WARN migration files changed after being applied (checksum drift): "
                    f"{out.drift} -- an applied migration must stay immutable"
                )

            pending = [m for m in migrations if m.version not in applied]
            out.pending = [m.version for m in pending]

            if not pending:
                out.message = f"already at v{out.current}"
                log(f"INFO db-init ok: already at schema v{out.current} (target v{out.target})")
                return out, lines

            if dry_run:
                out.message = f"dry-run: would apply {out.pending}"
                log(f"INFO db-init dry-run: would apply {out.pending} (v{out.current} -> v{out.target})")
                return out, lines

            if backup_dir:
                try:
                    out.backup_dir = snapshot_tables(
                        conn, backup_dir, out.app_version, out.current, out.target,
                        keep=backup_keep, log=log,
                    )
                except Exception as e:
                    out.backup_dir = ""
                    if require_backup:
                        out.ok = False
                        out.message = f"backup failed and backup is required: {type(e).__name__}: {e}"
                        log(f"ERROR {out.message}")
                        return out, lines
                    log(f"WARN backup failed, continuing: {type(e).__name__}: {e}")

            for m in pending:
                # One transaction per migration: the schema change and its
                # bookkeeping row commit together, or not at all.
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(m.sql)
                        cur.execute(
                            f"INSERT INTO {SCHEMA_VERSION_TABLE}"
                            "(version, name, checksum, app_version) VALUES (%s, %s, %s, %s)",
                            (m.version, m.name, m.checksum, out.app_version),
                        )
                out.applied.append(m.version)
                out.changes.append({"version": m.version, "name": m.name})
                log(f"INFO migration applied: {m.version:04d}_{m.name}")

            out.current = out.target
            out.message = f"applied {out.applied}"
            log(
                f"INFO db-init ok: {len(out.applied)} migration(s) applied, "
                f"schema now v{out.current} (app_version={out.app_version or 'unknown'})"
            )
            return out, lines
        finally:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
            except Exception:  # pragma: no cover - connection may already be gone
                pass
    except Exception as e:
        out.ok = False
        out.message = f"{type(e).__name__}: {e}"
        log(f"ERROR db-init failed: dsn={_sanitize(dsn)} err={out.message}")
        return out, lines
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover
                pass


def _sanitize(dsn: str) -> str:
    return re.sub(r":([^:@/]+)@", r":***@", str(dsn or ""))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply pending ZingLib database migrations.")
    p.add_argument("--dsn", default=os.environ.get("POSTGRES_DSN", ""))
    p.add_argument("--migrations-dir", default=DEFAULT_MIGRATIONS_DIR)
    p.add_argument("--log", default="")
    p.add_argument("--connect-timeout", type=int, default=15)
    p.add_argument("--backup-dir", default="")
    p.add_argument("--backup-keep", type=int, default=3)
    p.add_argument("--require-backup", action="store_true")
    p.add_argument("--no-backup", action="store_true")
    p.add_argument("--allow-downgrade", action="store_true")
    p.add_argument("--app-version", default="")
    p.add_argument("--app-version-file", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backup_dir = "" if args.no_backup else args.backup_dir
    outcome, _ = apply_pending(
        args.dsn,
        migrations_dir=args.migrations_dir,
        log_path=args.log,
        connect_timeout=args.connect_timeout,
        backup_dir=backup_dir,
        backup_keep=args.backup_keep,
        require_backup=args.require_backup,
        allow_downgrade=args.allow_downgrade,
        app_version=args.app_version,
        app_version_file=args.app_version_file,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(outcome.to_dict(), ensure_ascii=False))
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    sys.exit(main())
