#!/usr/bin/env python3
import os
import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .core.constants import STATIC_DIR
from .core.middleware import auth_guard
from .routers import auth, local_lib, media, reader, search, settings, system, tasks, xp
from .services.config_service import apply_runtime_timezone, ensure_dirs

app = FastAPI(title="ZingLib Web API", version="1.0.0")


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


@app.exception_handler(HTTPException)
async def _http_exception_with_traceback(_request: Request, exc: HTTPException) -> JSONResponse:
    tb = traceback.format_exc()
    detail = exc.detail
    payload: dict[str, object] = {"detail": detail}
    suppress_traceback = isinstance(detail, dict) and bool(detail.get("suppress_traceback"))
    if not suppress_traceback and tb and ("Errno 36" in tb or "file name too long" in tb.lower()):
        suppress_traceback = True
    if isinstance(detail, dict) and detail.get("traceback"):
        payload["traceback"] = str(detail.get("traceback") or "")
    if (not suppress_traceback) and tb and "Traceback" in tb and tb.strip().splitlines()[-1] != "NoneType: None":
        if not payload.get("traceback"):
            payload["traceback"] = tb
    return JSONResponse(status_code=int(exc.status_code), content=payload)


@app.exception_handler(Exception)
async def _unhandled_exception_with_traceback(_request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    if (isinstance(exc, OSError) and (getattr(exc, "errno", None) == 36 or "too long" in str(exc).lower())) or \
       (isinstance(exc, ValueError) and "too long" in str(exc).lower()):
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc),
                "traceback": f"{exc.__class__.__name__}: {exc} (traceback suppressed)",
            },
        )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"internal error: {exc}",
            "traceback": tb,
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_split_env_csv("DATA_UI_CORS_ALLOW_ORIGINS", ""),
    allow_methods=_split_env_csv("DATA_UI_CORS_ALLOW_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS"),
    allow_headers=_split_env_csv("DATA_UI_CORS_ALLOW_HEADERS", "Accept,Authorization,Content-Type,X-CSRF-Token"),
    allow_credentials=_env_bool("DATA_UI_CORS_ALLOW_CREDENTIALS", False),
)
app.middleware("http")(auth_guard)

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
