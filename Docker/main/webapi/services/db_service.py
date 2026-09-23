import threading
import time
from typing import Any
from urllib.parse import quote_plus, urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..core.config_values import normalize_value as _normalize_value

_cfg_lock = threading.Lock()
_cfg_cache: dict[str, Any] = {"ts": 0.0, "dsn": ""}
_CFG_TTL_S: float = 5.0


def _cached_dsn() -> str:
    now = time.monotonic()
    with _cfg_lock:
        if now - _cfg_cache["ts"] < _CFG_TTL_S and _cfg_cache["dsn"]:
            return str(_cfg_cache["dsn"])
    from .config_service import resolve_config

    cfg, _ = resolve_config()
    dsn = str(cfg.get("POSTGRES_DSN", "")).strip()
    with _cfg_lock:
        _cfg_cache["ts"] = time.monotonic()
        _cfg_cache["dsn"] = dsn
    return dsn


_pool_lock = threading.Lock()
_pool: ConnectionPool | None = None
_pool_dsn: str = ""  # 用于安全地记录当前池的 DSN，替代危险的 _pool.conninfo


def _get_pool() -> ConnectionPool | None:
    global _pool, _pool_dsn
    dsn = _cached_dsn()
    if not dsn:
        return None

    with _pool_lock:
        if _pool is not None:
            if _pool_dsn == dsn:
                return _pool
            # 如果 DSN 变了，优雅关闭旧池
            try:
                _pool.close()
            except Exception:
                pass
            _pool = None

        try:
            # 初始化新池，设置 autocommit=True 简化普通用户的事务管理负担
            _pool = ConnectionPool(
                conninfo=dsn,
                min_size=1,
                max_size=8,
                open=True,
                kwargs={"autocommit": True, "row_factory": dict_row}
            )
            _pool_dsn = dsn
        except Exception:
            _pool = None
            _pool_dsn = ""

    return _pool


def _parse_dsn_components(dsn: str) -> dict[str, str]:
    # (保留你原来的解析逻辑，无需改动)
    out: dict[str, str] = {}
    s = str(dsn or "").strip()
    if not s:
        return out
    try:
        u = urlparse(s)
    except Exception:
        return out
    out["POSTGRES_HOST"] = (u.hostname or "").strip()
    out["POSTGRES_PORT"] = str(u.port or 5432)
    out["POSTGRES_DB"] = (u.path or "").lstrip("/").strip()
    out["POSTGRES_USER"] = (u.username or "").strip()
    out["POSTGRES_PASSWORD"] = (u.password or "").strip()
    q = (u.query or "").strip()
    if "sslmode=" in q:
        for item in q.split("&"):
            if item.startswith("sslmode="):
                out["POSTGRES_SSLMODE"] = item.split("=", 1)[1].strip()
                break
    return out


def _build_dsn(values: dict[str, str]) -> str:
    # (保留你原来的构建逻辑，无需改动)
    manual = str(values.get("POSTGRES_DSN", "")).strip()
    host = str(values.get("POSTGRES_HOST", "")).strip()
    db = str(values.get("POSTGRES_DB", "")).strip()
    user = str(values.get("POSTGRES_USER", "")).strip()
    pwd = str(values.get("POSTGRES_PASSWORD", "")).strip()
    if not host or not db or not user:
        return manual
    port = _normalize_value("POSTGRES_PORT", values.get("POSTGRES_PORT", "5432"))
    sslmode = str(values.get("POSTGRES_SSLMODE", "prefer")).strip() or "prefer"
    return (
        f"postgresql://{quote_plus(user)}:{quote_plus(pwd)}@{host}:{port}/{quote_plus(db)}"
        f"?sslmode={quote_plus(sslmode)}"
    )


def db_dsn() -> str:
    return _cached_dsn()


def query_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    pool = _get_pool()

    # === 核心改造：优雅的池管理与安全的 fetchall 判断 ===
    if pool is not None:
        # with 语句会自动管理 getconn 和 putconn，哪怕发生异常也会安全回收！
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                # 极其关键：必须判断 description，否则 INSERT/CREATE 会报错！
                if cur.description:
                    return [dict(r) for r in cur.fetchall()]
                return []

    # === 极限备用逻辑（只有在连接池彻底崩溃无法创建时才会走到这里） ===
    dsn = _cached_dsn()
    if not dsn:
        return []
    with psycopg.connect(dsn, row_factory=dict_row, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return [dict(r) for r in cur.fetchall()]
            return []


_table_exists_cache: dict[str, tuple[bool, float]] = {}
_table_exists_lock = threading.Lock()


def check_table_exists(table_name: str) -> bool:
    now = time.monotonic()
    with _table_exists_lock:
        if table_name in _table_exists_cache:
            exists, expiry = _table_exists_cache[table_name]
            if now < expiry:
                return exists
    try:
        rows = query_rows(
            "SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = %s)",
            (table_name,)
        )
        exists = bool(rows and rows[0].get("exists"))
    except Exception:
        exists = False

    with _table_exists_lock:
        _table_exists_cache[table_name] = (exists, now + 10.0)
    return exists
