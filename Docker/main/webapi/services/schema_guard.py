"""Single entry point for "make sure the database matches this image".

All callers use `ensure_schema`, which runs the numbered migrations in
`textIngest/migrations/` through the same engine the container start uses.
The lazily-triggered path still exists because the setup wizard can store a DSN
at runtime, long after the container started -- but it now self-heals by
applying the same files, not by maintaining a parallel copy of the schema.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading
from pathlib import Path
from typing import Any

_ENGINE_LOCK = threading.Lock()
_ENGINE: Any = None

_READY_LOCK = threading.Lock()
_READY_DSN: str = ""

_ROOT = Path(__file__).resolve().parents[2]

_ENGINE_CANDIDATES = (
    Path("/app/textIngest/db_migrations.py"),
    _ROOT / "textIngest" / "db_migrations.py",
)

_MIGRATIONS_DIR_CANDIDATES = (
    Path("/app/textIngest/migrations"),
    _ROOT / "textIngest" / "migrations",
)


def _as_bool(value: str, default: bool = False) -> bool:
    v = str(value or "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "y", "on")


def _first_existing(candidates: tuple[Path, ...]) -> Path | None:
    for p in candidates:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def _load_engine() -> Any:
    """Import textIngest/db_migrations.py by path.

    It is deliberately not a package: textIngest is shipped as a directory of
    scripts and is also invoked directly from shell, so a path import keeps the
    engine usable from both sides without inventing a package layout.
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        path = _first_existing(_ENGINE_CANDIDATES)
        if path is None:
            raise RuntimeError(
                "db_migrations.py not found; looked in: "
                + ", ".join(str(p) for p in _ENGINE_CANDIDATES)
            )
        spec = importlib.util.spec_from_file_location("_zinglib_db_migrations", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load migration engine from {path}")
        module = importlib.util.module_from_spec(spec)
        # Register before executing: dataclasses (used by the engine) resolves
        # cls.__module__ through sys.modules, and a path import that never
        # registers itself blows up with AttributeError on __dict__ instead.
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(spec.name, None)
            raise
        _ENGINE = module
        return _ENGINE


def ensure_schema(dsn: str, *, force: bool = False) -> tuple[bool, str]:
    """Apply pending migrations for `dsn`. Cached per DSN for the process.

    Returns (ok, message). Never raises for an ordinary database problem: the
    callers are request handlers and a failed migration must surface as a
    message, not a traceback in the middle of someone's session.
    """
    global _READY_DSN

    s = str(dsn or "").strip()
    if not s:
        return False, "missing dsn"

    if not force and _READY_DSN == s:
        return True, "ok"

    try:
        engine = _load_engine()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    migrations_dir = _first_existing(_MIGRATIONS_DIR_CANDIDATES)
    if migrations_dir is None:
        return False, "migrations dir not found"

    backup_dir = ""
    if _as_bool(os.environ.get("DB_INIT_BACKUP", "1"), default=True):
        backup_dir = os.environ.get("DB_INIT_BACKUP_DIR", "").strip() or "/app/runtime/backups"

    try:
        outcome, _lines = engine.apply_pending(
            s,
            migrations_dir=str(migrations_dir),
            log_path=os.environ.get("DB_INIT_LOG", "").strip(),
            connect_timeout=int(os.environ.get("DB_INIT_CONNECT_TIMEOUT", "15") or 15),
            backup_dir=backup_dir,
            backup_keep=int(os.environ.get("DB_INIT_BACKUP_KEEP", "3") or 3),
            require_backup=False,
            allow_downgrade=_as_bool(os.environ.get("DB_INIT_ALLOW_DOWNGRADE", "0")),
            app_version_file=os.environ.get("DB_INIT_APP_VERSION_FILE", "").strip(),
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if not outcome.ok:
        return False, str(outcome.message or "migration failed")

    with _READY_LOCK:
        _READY_DSN = s
    return True, str(outcome.message or "ok")


def schema_status(dsn: str) -> dict[str, Any]:
    """Plan-only view of the schema, for diagnostics. Never mutates anything."""
    s = str(dsn or "").strip()
    if not s:
        return {"ok": False, "message": "missing dsn"}
    try:
        engine = _load_engine()
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}
    migrations_dir = _first_existing(_MIGRATIONS_DIR_CANDIDATES)
    if migrations_dir is None:
        return {"ok": False, "message": "migrations dir not found"}
    try:
        outcome, _lines = engine.apply_pending(
            s,
            migrations_dir=str(migrations_dir),
            connect_timeout=5,
            dry_run=True,
        )
        return outcome.to_dict()
    except Exception as e:
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}


def reset_cache() -> None:
    """Forget the per-process memo. Used by tests."""
    global _READY_DSN
    with _READY_LOCK:
        _READY_DSN = ""
