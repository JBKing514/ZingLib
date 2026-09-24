import base64
import json
import os
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..core.config_values import normalize_value as _normalize_value
from ..core.constants import (
    APP_CONFIG_FILE,
    APP_CONFIG_KEY_FILE,
    DEFAULT_POSTGRES_PASSWORD,
    LOCAL_LIB_DIR,
    CONFIG_SCOPE,
    CONFIG_SPECS,
    RUNTIME_DIR,
    TASK_LOG_DIR,
    GALLERY_CACHE_DIR,
    THUMB_GALLARY_DIR,
    TRANSLATION_DIR,
)
from .db_service import _build_dsn, _parse_dsn_components
from .schema_guard import ensure_schema


def _valid_timezone(name: str) -> str:
    candidate = str(name or "").strip() or "UTC"
    try:
        ZoneInfo(candidate)
        return candidate
    except ZoneInfoNotFoundError:
        return "UTC"


def _runtime_timezone_name() -> str:
    cfg, _ = resolve_config()
    return _valid_timezone(cfg.get("DATA_UI_TIMEZONE", "UTC"))


def _runtime_tzinfo() -> ZoneInfo:
    return ZoneInfo(_runtime_timezone_name())


def now_iso() -> str:
    return datetime.now(_runtime_tzinfo()).isoformat(timespec="seconds")


def apply_runtime_timezone() -> None:
    tz_name = _runtime_timezone_name()
    os.environ["TZ"] = tz_name
    tzset_fn = getattr(time, "tzset", None)
    if callable(tzset_fn):
        try:
            tzset_fn()
        except Exception:
            pass


def ensure_dirs() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    THUMB_GALLARY_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_LIB_DIR.mkdir(parents=True, exist_ok=True)


def _legacy_env_fernet() -> Fernet | None:
    key_env = os.getenv("DATA_UI_CONFIG_CRYPT_KEY", "").strip()
    if not key_env or (len(key_env) == 44 and key_env.endswith("=")):
        return None
    try:
        key = base64.urlsafe_b64encode(key_env.encode("utf-8")[:32].ljust(32, b"0"))
        return Fernet(key)
    except Exception:
        return None


def get_config_cipher() -> Fernet:
    ensure_dirs()
    key_env = os.getenv("DATA_UI_CONFIG_CRYPT_KEY", "").strip()
    if key_env:
        if len(key_env) == 44 and key_env.endswith("="):
            key = key_env.encode("ascii")
        else:
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"AutoEhHunter.ConfigCipher.Salt.v1",
                info=b"AutoEhHunter.ConfigCipher.Fernet.v1",
            )
            key = base64.urlsafe_b64encode(hkdf.derive(key_env.encode("utf-8")))
        return Fernet(key)

    if APP_CONFIG_KEY_FILE.exists():
        return Fernet(APP_CONFIG_KEY_FILE.read_bytes().strip())

    key = Fernet.generate_key()
    APP_CONFIG_KEY_FILE.write_bytes(key + b"\n")
    return Fernet(key)


def _encrypt_secret(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    token = get_config_cipher().encrypt(v.encode("utf-8")).decode("utf-8")
    return f"enc:v1:{token}"


def _decrypt_secret(value: str) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    if not s.startswith("enc:v1:"):
        return s
    token = s[len("enc:v1:") :]
    try:
        return get_config_cipher().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception):
        legacy = _legacy_env_fernet()
        if legacy is not None:
            try:
                return legacy.decrypt(token.encode("utf-8")).decode("utf-8")
            except Exception:
                return ""
        return ""


def _load_json_config() -> dict[str, str]:
    ensure_dirs()
    if not APP_CONFIG_FILE.exists():
        return {}
    try:
        obj = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    vals = obj.get("values", obj) if isinstance(obj, dict) else {}
    if not isinstance(vals, dict):
        return {}
    out: dict[str, str] = {}
    for key, spec in CONFIG_SPECS.items():
        if key not in vals:
            continue
        raw = vals.get(key)
        out[key] = _decrypt_secret(str(raw or "")) if spec.get("secret", False) else _normalize_value(key, raw)
    return out


def _save_json_config(values: dict[str, str]) -> None:
    ensure_dirs()
    payload: dict[str, Any] = {"version": 1, "updated_at": now_iso(), "values": {}}
    for key, spec in CONFIG_SPECS.items():
        raw = str(values.get(key, _normalize_value(key, spec.get("default", ""))))
        payload["values"][key] = _encrypt_secret(raw) if spec.get("secret", False) else _normalize_value(key, raw)
    APP_CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_db_config(dsn: str) -> tuple[dict[str, str], str]:
    s = str(dsn or "").strip()
    if not s:
        return ({}, "missing dsn")
    sql = "SELECT key, value, is_secret FROM app_config WHERE scope = %s"
    try:
        out: dict[str, str] = {}
        with psycopg.connect(s, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5s'")
                cur.execute(sql, (CONFIG_SCOPE,))
                for key, value, is_secret in cur.fetchall():
                    if key not in CONFIG_SPECS:
                        continue
                    out[key] = _decrypt_secret(str(value or "")) if is_secret else _normalize_value(str(key), value)
        return (out, "")
    except Exception as e:
        return ({}, str(e))


def _save_db_config(dsn: str, values: dict[str, str]) -> tuple[bool, str]:
    s = str(dsn or "").strip()
    if not s:
        return (False, "missing dsn")
    # app_config is defined by textIngest/migrations/0001_baseline.sql. Ask for
    # the schema to be current rather than creating the table here: an inline
    # CREATE TABLE was a second DDL source that could drift from the migration
    # files without anything noticing. Cached per DSN, so this is not a round
    # trip on every save.
    schema_ok, schema_msg = ensure_schema(s)
    if not schema_ok:
        return (False, f"schema not ready: {schema_msg}")
    upsert_sql = (
        "INSERT INTO app_config(scope, key, value, value_type, is_secret, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, now()) "
        "ON CONFLICT (scope, key) DO UPDATE SET value = EXCLUDED.value, "
        "value_type = EXCLUDED.value_type, is_secret = EXCLUDED.is_secret, updated_at = now()"
    )
    try:
        with psycopg.connect(s) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout = '5s'")
                for key, spec in CONFIG_SPECS.items():
                    plain = str(values.get(key, _normalize_value(key, spec.get("default", ""))))
                    stored = _encrypt_secret(plain) if spec.get("secret", False) else _normalize_value(key, plain)
                    cur.execute(
                        upsert_sql,
                        (CONFIG_SCOPE, key, stored, str(spec.get("type", "text")), bool(spec.get("secret", False))),
                    )
            conn.commit()
        return (True, "")
    except Exception as e:
        return (False, str(e))


def default_credentials_in_use(cfg: dict[str, Any]) -> dict[str, Any]:
    """Which shipped default credentials are still in effect.

    The database credentials are the only defaults this project ships: the admin
    account is created by the user during setup, so there is no constant to compare
    an admin password against. That is why the settings banner can be *shown*
    truthfully only for the database side, while the admin password appears in its
    wording as advice.

    An empty stored password counts as "not changed" too -- a blank field is how a
    database configured without a password looks, and that is not safer.
    """
    user = str(cfg.get("POSTGRES_USER", "") or "").strip()
    password = str(cfg.get("POSTGRES_PASSWORD", "") or "").strip()
    user_default = user == str(CONFIG_SPECS["POSTGRES_USER"].get("default", "")).strip()
    password_default = password in {"", DEFAULT_POSTGRES_PASSWORD}
    fields: list[str] = []
    if user_default:
        fields.append("POSTGRES_USER")
    if password_default:
        fields.append("POSTGRES_PASSWORD")
    return {
        "in_use": bool(fields),
        "fields": fields,
        "db_user_default": user_default,
        "db_password_default": password_default,
    }


def resolve_config() -> tuple[dict[str, str], dict[str, Any]]:
    merged: dict[str, str] = {k: _normalize_value(k, spec.get("default", "")) for k, spec in CONFIG_SPECS.items()}
    env_vals: dict[str, str] = {}
    for key in CONFIG_SPECS:
        v = os.getenv(key)
        if v is not None:
            env_vals[key] = _normalize_value(key, v)
    if env_vals.get("POSTGRES_DSN"):
        env_vals.update(_parse_dsn_components(env_vals["POSTGRES_DSN"]))

    json_vals = _load_json_config()
    if json_vals.get("POSTGRES_DSN"):
        json_vals.update(_parse_dsn_components(json_vals["POSTGRES_DSN"]))

    merged.update(env_vals)
    merged.update(json_vals)
    merged["POSTGRES_DSN"] = _build_dsn(merged)

    db_vals, db_error = _load_db_config(merged.get("POSTGRES_DSN", ""))
    if db_vals.get("POSTGRES_DSN"):
        db_vals.update(_parse_dsn_components(db_vals["POSTGRES_DSN"]))
    merged.update(db_vals)
    merged["POSTGRES_DSN"] = _build_dsn(merged)

    ingest_base = str(merged.get("INGEST_API_BASE", "")).strip().rstrip("/")
    llm_base = str(merged.get("LLM_API_BASE", "")).strip().rstrip("/")
    if llm_base and not llm_base.endswith("/v1"):
        llm_base = f"{llm_base}/v1"
    if ingest_base and not ingest_base.endswith("/v1"):
        ingest_base = f"{ingest_base}/v1"
    merged["LLM_API_BASE"] = llm_base
    merged["EMB_API_BASE"] = llm_base
    merged["INGEST_API_BASE"] = ingest_base
    merged["VL_BASE"] = ingest_base
    merged["EMB_BASE"] = ingest_base
    merged["VL_MODEL_ID"] = str(merged.get("INGEST_VL_MODEL_CUSTOM") or merged.get("INGEST_VL_MODEL") or "").strip()
    merged["EMB_MODEL_ID"] = str(merged.get("INGEST_EMB_MODEL_CUSTOM") or merged.get("INGEST_EMB_MODEL") or "").strip()
    merged["LLM_MODEL"] = str(merged.get("LLM_MODEL_CUSTOM") or merged.get("LLM_MODEL") or "").strip()
    merged["EMB_MODEL"] = str(merged.get("EMB_MODEL_CUSTOM") or merged.get("EMB_MODEL") or "").strip()
    if str(merged.get("INGEST_API_KEY", "")).strip():
        merged["OPENAI_API_KEY"] = str(merged.get("INGEST_API_KEY", "")).strip()
    db_connected = bool(merged.get("POSTGRES_DSN", "")) and not db_error
    if db_connected and db_vals:
        active_source = "db"
    elif json_vals:
        active_source = "json"
    elif env_vals:
        active_source = "env"
    else:
        active_source = "none"
    meta = {
        "db_connected": db_connected,
        "db_error": db_error,
        "sources": "db > json > env",
        "active_source": active_source,
    }
    return merged, meta


def build_runtime_env() -> dict[str, str]:
    cfg, _ = resolve_config()
    env = dict(os.environ)
    for key in CONFIG_SPECS:
        val = str(cfg.get(key, ""))
        if val:
            env[key] = val
    env["POSTGRES_DSN"] = cfg.get("POSTGRES_DSN", "")
    return env
