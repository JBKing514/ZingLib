import os
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from .config_values import as_bool as _as_bool
from ..services.auth_service import (
    auth_pepper,
    bootstrap_status as auth_bootstrap_status,
    get_session_user as auth_get_session_user,
    verify_recovery_csrf,
    verify_csrf,
)
from ..services.db_service import db_dsn
from ..services.config_service import resolve_config

AUTH_COOKIE_NAME = "zgl_session"
AUTH_CSRF_COOKIE_NAME = "zgl_csrf"
AUTH_ALLOW_PATHS = {
    "/api/auth/bootstrap",
    "/api/auth/register-admin",
    "/api/auth/login",
}
SETUP_OPEN_PATHS = {
    "/api/config",
    "/api/config/schema",
    "/api/setup/status",
    "/api/setup/validate-db",
}
RECOVERY_ALLOWED_ENDPOINTS = {
    "/api/config",
    "/api/config/schema",
    "/api/auth/password",
    "/api/auth/logout",
}


def _auth_ttl_hours(cfg: dict[str, Any] | None = None) -> int:
    src = cfg or {}
    try:
        return max(1, min(720, int(str(src.get("AUTH_SESSION_TTL_HOURS") or "72"))))
    except Exception:
        return 72


def _auth_cookie_secure(cfg: dict[str, Any] | None = None) -> bool:
    src = cfg or {}
    return _as_bool(src.get("AUTH_COOKIE_SECURE"), False)


def _auth_cookie_samesite() -> str:
    raw = str(os.getenv("DATA_UI_AUTH_COOKIE_SAMESITE", "strict") or "").strip().lower()
    if raw in {"strict", "lax", "none"}:
        return raw
    return "strict"


def _auth_set_cookie(resp: Response, token: str, cfg: dict[str, Any], csrf_token: str = "") -> None:
    samesite = _auth_cookie_samesite()
    resp.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=_auth_cookie_secure(cfg),
        samesite=samesite,
        max_age=_auth_ttl_hours(cfg) * 3600,
        path="/",
    )
    if csrf_token:
        resp.set_cookie(
            key=AUTH_CSRF_COOKIE_NAME,
            value=str(csrf_token),
            httponly=False,
            secure=_auth_cookie_secure(cfg),
            samesite=samesite,
            max_age=_auth_ttl_hours(cfg) * 3600,
            path="/",
        )


def _auth_clear_cookie(resp: Response, cfg: dict[str, Any]) -> None:
    samesite = _auth_cookie_samesite()
    resp.delete_cookie(key=AUTH_COOKIE_NAME, path="/", samesite=samesite, secure=_auth_cookie_secure(cfg))
    resp.delete_cookie(key=AUTH_CSRF_COOKIE_NAME, path="/", samesite=samesite, secure=_auth_cookie_secure(cfg))


async def auth_guard(request: Request, call_next):
    p = str(request.url.path or "")
    method = str(request.method or "GET").upper()
    if p.startswith("/api") and p not in AUTH_ALLOW_PATHS:
        token = str(request.cookies.get(AUTH_COOKIE_NAME) or "").strip()
        if token and token.startswith("RECV::"):
            user = auth_get_session_user("", token)
            if not user:
                return JSONResponse(status_code=401, content={"detail": "invalid session"})
            user_role = str(user.get("role") or "")
            if user_role == "recovery":
                if p not in RECOVERY_ALLOWED_ENDPOINTS:
                    return JSONResponse(status_code=403, content={"detail": "recovery mode: limited access"})
                if method in {"POST", "PUT", "PATCH", "DELETE"}:
                    csrf_cookie = str(request.cookies.get(AUTH_CSRF_COOKIE_NAME) or "")
                    csrf_header = str(request.headers.get("x-csrf-token") or "")
                    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                        return JSONResponse(status_code=403, content={"detail": "csrf verification failed"})
                    if not verify_recovery_csrf(token, csrf_header, pepper=auth_pepper()):
                        return JSONResponse(status_code=403, content={"detail": "csrf verification failed"})
                request.state.auth_user = user
                return await call_next(request)
        dsn = db_dsn()
        if not dsn:
            if p in SETUP_OPEN_PATHS:
                return await call_next(request)
            return JSONResponse(status_code=503, content={"detail": "database is not configured"})
        try:
            st = auth_bootstrap_status(dsn)
        except Exception:
            if p in SETUP_OPEN_PATHS:
                return await call_next(request)
            return JSONResponse(status_code=503, content={"detail": "auth service unavailable"})
        if bool(st.get("configured")):
            if not token:
                return JSONResponse(status_code=401, content={"detail": "authentication required"})

            cfg, _ = resolve_config()
            ttl_hours = _auth_ttl_hours(cfg)
            user = auth_get_session_user(dsn, token, ttl_hours=ttl_hours)
            if not user:
                return JSONResponse(status_code=401, content={"detail": "invalid session"})
            user_role = str(user.get("role") or "")
            if user_role == "recovery":
                if p not in RECOVERY_ALLOWED_ENDPOINTS:
                    return JSONResponse(status_code=403, content={"detail": "recovery mode: limited access"})

            csrf_cookie = str(request.cookies.get(AUTH_CSRF_COOKIE_NAME) or "")
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                csrf_header = str(request.headers.get("x-csrf-token") or "")
                if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                    return JSONResponse(status_code=403, content={"detail": "csrf verification failed"})
                if not verify_csrf(dsn, token, csrf_header):
                    return JSONResponse(status_code=403, content={"detail": "csrf verification failed"})

            request.state.auth_user = user
            if user.get("extended"):
                request.state.auth_extend_cookies = (token, csrf_cookie, cfg)

    response = await call_next(request)

    extend_cookies = getattr(request.state, "auth_extend_cookies", None)
    if extend_cookies:
        t_val, c_val, cfg_val = extend_cookies
        _auth_set_cookie(response, t_val, cfg_val, csrf_token=c_val)

    return response
