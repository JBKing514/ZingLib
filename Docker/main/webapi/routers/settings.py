import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, Request
from fastapi.responses import FileResponse

from ..core.config_values import as_bool as _as_bool
from ..core.config_values import normalize_value as _normalize_value
from ..core.constants import APP_CONFIG_FILE, CONFIG_SPECS, RUNTIME_DIR, TRANSLATION_DIR
from ..core.runtime_state import model_dl_lock, model_dl_state
from ..core.schemas import ConfigUpdateRequest, ProviderModelsRequest, SetupValidateDbRequest
from ..services.ai_provider import _provider_models
from ..services.auth_service import bootstrap_status as auth_bootstrap_status
from ..services.auth_service import set_initialized
from ..services.config_service import (
    _runtime_timezone_name,
    _runtime_tzinfo,
    _save_db_config,
    _save_json_config,
    apply_runtime_timezone,
    default_credentials_in_use,
    ensure_dirs,
    now_iso,
    resolve_config,
)
from ..services.db_service import _build_dsn, db_dsn, query_rows
from ..services.local_embedding_service import disable_local_embedding_worker, enable_local_embedding_worker
from ..services.local_lib_service import (
    _load_translation_maps,
    translation_table_info,
    validate_translation_table,
)
from ..services.schedule_service import sync_scheduler
from ..services.setup_service import init_core_schema, validate_db_connection
from ..services.vision_service import (
    _clear_runtime_pydeps,
    _clear_siglip_runtime,
    _download_siglip_worker,
    _model_status,
    _set_dl_state,
)

router = APIRouter(tags=["settings"])


def _db_health_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    db_ok = True
    db_error = ""
    total_works = 0

    try:
        # Probe database connection
        query_rows("SELECT 1")
    except Exception as e:
        db_ok = False
        db_error = f"Database connection failed: {e}"
        return {
            "database": {
                "ok": False,
                "error": db_error,
                "works": 0,
                "timezone": _runtime_timezone_name(),
            }
        }

    from ..services.db_service import check_table_exists

    try:
        if check_table_exists("works"):
            works = query_rows("SELECT count(*) AS n FROM works")
            total_works = int((works[0] or {}).get("n") or 0) if works else 0
    except Exception:
        pass

    return {
        "database": {
            "ok": db_ok,
            "error": db_error,
            "works": total_works,
            "timezone": _runtime_timezone_name(),
        }
    }


@router.get("/api/config/schema")
def get_config_schema() -> dict[str, Any]:
    return {"schema": CONFIG_SPECS}


@router.get("/api/setup/status")
def setup_status() -> dict[str, Any]:
    dsn = db_dsn()
    if not dsn:
        return {
            "ok": True,
            "db_ready": False,
            "configured": False,
            "initialized": False,
            "user_configured": False,
        }
    try:
        st = auth_bootstrap_status(dsn)
    except Exception as e:
        return {
            "ok": True,
            "db_ready": False,
            "configured": False,
            "initialized": False,
            "user_configured": False,
            "db_error": str(e),
        }
    return {
        "ok": True,
        "db_ready": True,
        "configured": bool(st.get("configured")),
        "initialized": bool(st.get("initialized")),
        "user_configured": bool(st.get("user_configured")),
    }


@router.post("/api/setup/validate-db")
def setup_validate_db(req: SetupValidateDbRequest) -> dict[str, Any]:
    ok, msg, _dsn = validate_db_connection(req.host, int(req.port or 5432), req.db, req.user, req.password, req.sslmode)
    if not ok:
        return {"ok": False, "message": msg}
    return {"ok": True, "message": "ok"}


@router.post("/api/setup/complete")
def setup_complete() -> dict[str, Any]:
    from ..services.auth_service import generate_recovery_codes, hash_recovery_codes
    from ..services.config_service import _save_json_config, resolve_config

    dsn = db_dsn()
    if not dsn:
        raise HTTPException(status_code=503, detail="database is not configured")

    schema_ok, schema_msg = init_core_schema(dsn)
    if not schema_ok:
        raise HTTPException(status_code=500, detail=f"schema init failed: {schema_msg}")

    set_initialized(dsn, True)

    codes = generate_recovery_codes(10)
    hashed = hash_recovery_codes(codes)
    cfg, _ = resolve_config()
    to_save = dict(cfg)
    to_save["DATA_UI_RECOVERY_CODES"] = ",".join(hashed)
    _save_json_config(to_save)

    return {"ok": True, "recovery_codes": codes}


@router.get("/api/health")
def health() -> dict[str, Any]:
    cfg, _ = resolve_config()
    payload = _db_health_payload(cfg)

    # `services.llm` used to report a probe against OPENAI_HEALTH_URL. Nothing
    # ever rendered it -- the only consumer, ControlPage, reads
    # `health.database` alone -- so it was a network call on every poll whose
    # result went nowhere, and it contradicted the project's "no outbound calls"
    # rule. The field is gone rather than left as a dead key: an empty payload
    # slot is an invitation to re-wire it by accident.
    payload["services"] = {}
    return payload


@router.get("/api/health/db")
def health_db() -> dict[str, Any]:
    cfg, _ = resolve_config()
    return _db_health_payload(cfg)


@router.post("/api/provider/models")
def provider_models(req: ProviderModelsRequest) -> dict[str, Any]:
    cfg, _ = resolve_config()
    api_key = str(req.api_key or "").strip()
    base = str(req.base_url or "").strip()
    if not api_key:
        llm_base = str(cfg.get("LLM_API_BASE", "")).strip().rstrip("/")
        ingest_base = str(cfg.get("INGEST_API_BASE", "")).strip().rstrip("/")
        norm_base = base.rstrip("/")
        if norm_base == llm_base:
            api_key = str(cfg.get("LLM_API_KEY", "")).strip()
        elif norm_base == ingest_base:
            api_key = str(cfg.get("INGEST_API_KEY", "")).strip()
    models, err = _provider_models(base, api_key)
    return {"ok": bool(models), "models": models, "error": err}


@router.get("/api/config")
def get_config() -> dict[str, Any]:
    cfg, meta = resolve_config()
    values: dict[str, Any] = {}
    secret_state: dict[str, bool] = {}
    for key, spec in CONFIG_SPECS.items():
        if spec.get("secret", False):
            values[key] = ""
            secret_state[key] = bool(str(cfg.get(key, "")).strip())
        else:
            values[key] = cfg.get(key, _normalize_value(key, spec.get("default", "")))
    # The "you are still on the example credentials" banner is only honest when
    # the values really are the shipped ones, so the decision is made here from
    # the resolved config rather than assumed in the UI.
    meta = {**meta, "security_defaults": default_credentials_in_use(cfg)}
    return {"values": values, "secret_state": secret_state, "meta": meta}


def _db_write_pending(ok_db: bool, had_saved_config: bool) -> bool:
    return (not ok_db) and (not had_saved_config)


@router.put("/api/config")
def update_config(req: ConfigUpdateRequest, request: Request) -> dict[str, Any]:
    cfg, _ = resolve_config()
    had_saved_config = APP_CONFIG_FILE.exists()
    new_cfg = dict(cfg)
    for key, spec in CONFIG_SPECS.items():
        if key not in req.values:
            continue
        v = req.values[key]
        if spec.get("secret", False) and not str(v or "").strip():
            continue
        new_cfg[key] = _normalize_value(key, v)
    new_cfg["SIGLIP_DEVICE"] = "cpu"
    new_cfg["POSTGRES_DSN"] = _build_dsn(new_cfg)
    _save_json_config(new_cfg)
    ok_db, db_err = _save_db_config(new_cfg.get("POSTGRES_DSN", ""), new_cfg)
    # `saved_db: false` only means "something is broken" when there was already a
    # database to write to. On the setup screen there is nothing yet -- the JSON
    # copy is the whole truth until the wizard has a working DSN -- and reporting
    # a failure there put "save failed" on the very first screen a new user sees,
    # for typing into a form that cannot be saved yet.
    #
    # What it must *not* swallow is an installation that was configured and whose
    # database is now unreachable. The resolved DSN cannot distinguish those
    # states because defaults are enough for `_build_dsn` to synthesize a non-empty
    # URL on a fresh install. The durable JSON copy can: capture whether it existed
    # before this request writes it, then surface failures on every later save.
    db_pending = _db_write_pending(ok_db, had_saved_config)
    try:
        siglip_worker_enabled = _as_bool(new_cfg.get("SIGLIP_WORKER_ENABLED"), True)
        if siglip_worker_enabled:
            enable_local_embedding_worker()
        else:
            disable_local_embedding_worker()

    except Exception:
        pass
    apply_runtime_timezone()
    sync_scheduler()
    return {
        "ok": True,
        "saved_json": True,
        "saved_db": None if db_pending else bool(ok_db),
        "db_pending": bool(db_pending),
        "db_error": "" if db_pending else db_err,
    }


@router.get("/api/config/app-config/download")
def download_app_config_json() -> FileResponse:
    ensure_dirs()
    if not APP_CONFIG_FILE.exists():
        cfg, _ = resolve_config()
        _save_json_config(cfg)
    return FileResponse(
        path=str(APP_CONFIG_FILE),
        filename="app_config.json",
        media_type="application/json",
    )


@router.post("/api/config/app-config/restore")
async def restore_app_config_json(file: UploadFile = File(...)) -> dict[str, Any]:
    ensure_dirs()
    name = str(file.filename or "app_config.json").strip().lower()
    if not name.endswith(".json"):
        raise HTTPException(status_code=400, detail="only .json file is allowed")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="empty file")
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="invalid app_config payload")
    if "values" in obj and not isinstance(obj.get("values"), dict):
        raise HTTPException(status_code=400, detail="invalid app_config payload: values must be object")

    APP_CONFIG_FILE.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    apply_runtime_timezone()
    sync_scheduler()
    return {
        "ok": True,
        "path": str(APP_CONFIG_FILE),
        "bytes": len(body),
        "updated_at": datetime.fromtimestamp(APP_CONFIG_FILE.stat().st_mtime, tz=_runtime_tzinfo()).isoformat(timespec="seconds"),
        "note": "Restored runtime app_config.json only. Database config is unchanged.",
    }


@router.get("/api/translation/status")
def translation_status() -> dict[str, Any]:
    ensure_dirs()
    info = translation_table_info()
    manual = Path(str(info.get("path") or ""))
    updated_at = "-"
    if info.get("updated_at"):
        updated_at = datetime.fromtimestamp(int(info["updated_at"]), tz=_runtime_tzinfo()).isoformat(timespec="seconds")
    manual_info = {
        "path": str(manual),
        "dir": str(info.get("dir") or ""),
        "file_name": str(info.get("file_name") or ""),
        "exists": bool(info.get("exists")),
        "size": int(info.get("size") or 0),
        "updated_at": updated_at,
        "namespaces": int(info.get("namespaces") or 0),
        "tag_namespaces": int(info.get("tag_namespaces") or 0),
        "tags": int(info.get("tags") or 0),
    }
    # There is no remote repository behind this: the table is maintained either
    # by uploading a JSON glossary or by editing the file in place. The old
    # `repo` / `head_sha` / `fetched_at` keys were hardcoded empties that no
    # consumer ever read, so they are gone rather than kept as decor.
    return {
        "manual_file": manual_info,
    }


@router.post("/api/translation/upload")
async def translation_upload(file: UploadFile = File(...)) -> dict[str, Any]:
    ensure_dirs()
    name = str(file.filename or "").lower()
    if not (name.endswith(".json") or name.endswith(".jsonl") or name.endswith(".txt")):
        raise HTTPException(status_code=400, detail="only json/jsonl/txt allowed")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    text = data.decode("utf-8", errors="replace")
    ok, reason, stats = validate_translation_table(text)
    if not ok:
        # Reject before writing so a bad upload cannot clobber a working table.
        raise HTTPException(status_code=400, detail=f"invalid translation table: {reason}")
    out = TRANSLATION_DIR / "manual_tags.json"
    out.write_bytes(data)
    # Refresh the in-process cache immediately instead of waiting for the next
    # signature check, so the new table applies to the very next scan.
    _load_translation_maps(force=True)
    return {
        "ok": True,
        "path": str(out),
        "bytes": len(data),
        "namespaces": stats.get("namespaces", 0),
        "tags": stats.get("tags", 0),
        "updated_at": datetime.fromtimestamp(out.stat().st_mtime, tz=_runtime_tzinfo()).isoformat(timespec="seconds"),
    }


@router.delete("/api/translation/table")
def translation_table_clear() -> dict[str, Any]:
    ensure_dirs()
    out = TRANSLATION_DIR / "manual_tags.json"
    removed = False
    if out.exists():
        try:
            out.unlink()
            removed = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to remove translation table: {e}")
    _load_translation_maps(force=True)
    return {"ok": True, "removed": removed, "path": str(out)}


@router.get("/api/models/status")
def models_status_api() -> dict[str, Any]:
    return {"model": _model_status(), "download": list(model_dl_state.values())[-1] if model_dl_state else None}


@router.post("/api/models/siglip/download")
def model_siglip_download(model_id: str = Query(default="google/siglip-so400m-patch14-384")) -> dict[str, Any]:
    with model_dl_lock:
        for st in model_dl_state.values():
            if str(st.get("status")) == "running":
                return {"ok": True, "task_id": st.get("task_id"), "already_running": True}
    task_id = f"siglip-{int(time.time())}"
    state = {
        "task_id": task_id,
        "model_id": str(model_id or "google/siglip-so400m-patch14-384").strip(),
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "error": "",
        "logs": [],
        "started_at": now_iso(),
    }
    _set_dl_state(task_id, state)
    th = threading.Thread(target=_download_siglip_worker, args=(task_id, state["model_id"]), daemon=True)
    th.start()
    return {"ok": True, "task_id": task_id, "status": state}


@router.get("/api/models/siglip/download/{task_id}")
def model_siglip_download_status(task_id: str) -> dict[str, Any]:
    with model_dl_lock:
        st = model_dl_state.get(str(task_id))
    if not st:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True, "status": st, "model": _model_status()}


@router.delete("/api/models/siglip")
def model_siglip_clear() -> dict[str, Any]:
    return _clear_siglip_runtime()


@router.delete("/api/models/runtime-deps")
def model_runtime_deps_clear() -> dict[str, Any]:
    return _clear_runtime_pydeps()
