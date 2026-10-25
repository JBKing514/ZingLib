#!/usr/bin/env python3
import json
import logging
import os
import traceback
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.constants import APP_CONFIG_FILE, STATIC_DIR
from .core.middleware import auth_guard
from .routers import auth, local_lib, media, reader, search, settings, system, tasks, xp
from .services.config_service import apply_runtime_timezone, ensure_dirs

app = FastAPI(title="ZingLib Web API", version="1.0.0")

logger = logging.getLogger("zinglib.http")
REQUEST_ID_HEADER = "X-Request-Id"


def _truthy(raw: object) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _expose_error_details() -> bool:
    """Whether an HTTP response may carry a traceback and the raw exception text.

    Off unless asked for. A deployment is expected to keep it off: the response
    gets a short request id and the log gets the traceback, so "what the user saw"
    and "what actually happened" stay correlatable without shipping internals.

    This reads the environment and the saved JSON config, never the database: it
    runs inside the error path, where a failing or hanging DB round-trip would
    take the error handler down with it.
    """
    env = os.getenv("DATA_UI_EXPOSE_TRACEBACK")
    if env is not None:
        return _truthy(env)
    try:
        payload = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return False
    values = payload.get("values") if isinstance(payload, dict) else None
    return _truthy((values or {}).get("DATA_UI_EXPOSE_TRACEBACK"))


def _request_id(request: Request | None) -> str:
    rid = str(getattr(getattr(request, "state", None), "request_id", "") or "")
    return rid or uuid.uuid4().hex[:12]


def _has_real_traceback(tb: str) -> bool:
    return bool(tb) and "Traceback" in tb and tb.strip().splitlines()[-1] != "NoneType: None"


def _split_env_csv(name: str, default: str = "") -> list[str]:
    raw = str(os.getenv(name, default) or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        s = str(part or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0") or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "on"}


async def _attach_request_id(request: Request, call_next):
    """Give every request an id and echo it back.

    Registered *last* (see the bottom of this module) so it is the outermost
    layer: a 401/403 that `auth_guard` returns before the route runs still
    carries the header and the log line, which is exactly the case an operator
    needs to correlate.
    """
    rid = str(request.headers.get(REQUEST_ID_HEADER) or "").strip() or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = rid
    return response


@app.exception_handler(HTTPException)
async def _http_exception_with_traceback(request: Request, exc: HTTPException) -> JSONResponse:
    tb = traceback.format_exc()
    rid = _request_id(request)
    detail = exc.detail
    status = int(exc.status_code)
    payload: dict[str, object] = {"detail": detail}

    suppress_traceback = isinstance(detail, dict) and bool(detail.get("suppress_traceback"))
    if not suppress_traceback and tb and ("Errno 36" in tb or "file name too long" in tb.lower()):
        suppress_traceback = True
    if _expose_error_details() and not suppress_traceback:
        if isinstance(detail, dict) and detail.get("traceback"):
            payload["traceback"] = str(detail.get("traceback") or "")
        elif _has_real_traceback(tb):
            payload["traceback"] = tb
    payload["request_id"] = rid

    # 4xx are the client's fault and happen on purpose (validation, 403, 404):
    # one line each, no stack. 5xx are ours, so the stack goes to the log.
    path = str(getattr(request, "url", "") or "")
    if status >= 500:
        logger.error("status=%s request_id=%s path=%s detail=%s\n%s", status, rid, path, detail, tb)
    else:
        logger.warning("status=%s request_id=%s path=%s detail=%s", status, rid, path, detail)
    return JSONResponse(status_code=status, content=payload, headers={REQUEST_ID_HEADER: rid})


@app.exception_handler(Exception)
async def _unhandled_exception_with_traceback(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    rid = _request_id(request)
    path = str(getattr(request, "url", "") or "")
    logger.error("unhandled request_id=%s path=%s exc=%s\n%s", rid, path, exc, tb)

    too_long = (isinstance(exc, OSError) and getattr(exc, "errno", None) == 36) or \
               (isinstance(exc, (OSError, ValueError)) and "too long" in str(exc).lower())
    if too_long:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "request_id": rid},
            headers={REQUEST_ID_HEADER: rid},
        )
    content: dict[str, object] = {
        # The message itself can quote a DSN, a path or a provider payload, so it
        # stays in the log next to the same id unless the debug switch is on.
        "detail": f"internal error (ref {rid})",
        "request_id": rid,
    }
    if _expose_error_details():
        content["detail"] = f"internal error: {exc}"
        content["traceback"] = tb
    return JSONResponse(status_code=500, content=content, headers={REQUEST_ID_HEADER: rid})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_split_env_csv("DATA_UI_CORS_ALLOW_ORIGINS", ""),
    allow_methods=_split_env_csv("DATA_UI_CORS_ALLOW_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS"),
    allow_headers=_split_env_csv("DATA_UI_CORS_ALLOW_HEADERS", "Accept,Authorization,Content-Type,X-CSRF-Token"),
    allow_credentials=_env_bool("DATA_UI_CORS_ALLOW_CREDENTIALS", False),
)
app.middleware("http")(auth_guard)
# Outer-most on purpose (Starlette applies the last registered middleware first):
# the id has to exist before `auth_guard` can reject a request, otherwise the
# 401/403 path -- the one worth correlating -- would be the only one without it.
app.middleware("http")(_attach_request_id)

app.include_router(auth.router)
app.include_router(search.router)
app.include_router(media.router)
app.include_router(reader.router)
app.include_router(settings.router)
app.include_router(tasks.router)
app.include_router(local_lib.router)
app.include_router(xp.router)
app.include_router(system.router)

if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

ensure_dirs()
apply_runtime_timezone()
