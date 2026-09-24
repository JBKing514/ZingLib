import os
import sys
import threading
from typing import Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from ..core.constants import MAX_HOME_FEED_LIMIT, STATIC_DIR
from ..core.runtime_state import scheduler
from ..services.auth_service import ensure_auth_schema
from ..services.config_service import apply_runtime_timezone, ensure_dirs, resolve_config
from ..services.db_service import db_dsn, query_rows
from ..services.local_embedding_service import (
    disable_local_embedding_worker,
    enable_local_embedding_worker,
    get_local_embedding_worker_status,
    stop_local_embedding_worker,
    stop_local_embedding_worker_until_restart,
)

from ..services.rec_service_local import get_local_recommendation_items_cached
from ..services.schedule_service import sync_scheduler
from ..services.search_service import _item_from_work
from ..services.vision_service import warmup_siglip_model, _embed_image_siglip

router = APIRouter(tags=["system"])


def _warmup_siglip_model_in_background(model_id: str) -> None:
    try:
        warmup_siglip_model(model_id, strict=False, silent_skip=True)
    except Exception as e:
        print(f"[startup] siglip warmup skipped: {e}", flush=True)


def _ensure_auth_schema_in_background(dsn: str) -> None:
    try:
        ensure_auth_schema(dsn)
    except Exception as e:
        print(f"[startup] auth schema init skipped: {e}", flush=True)


def _sync_scheduler_in_background() -> None:
    try:
        sync_scheduler()
    except Exception as e:
        print(f"[startup] scheduler sync skipped: {e}", flush=True)


def _parse_csv_param(raw: str) -> list[str]:
    return [str(x).strip().lower() for x in str(raw or "").split(",") if str(x).strip()]


def _apply_item_filters(items: list[dict[str, Any]], cats: list[str], tags: list[str]) -> list[dict[str, Any]]:
    if not cats and not tags:
        return items
    out: list[dict[str, Any]] = []
    for it in items or []:
        if cats:
            c = str(it.get("category") or "").strip().lower()
            if c not in cats:
                continue
        if tags:
            bag = [
                *(str(x).strip().lower() for x in (it.get("tags") or [])),
                *(str(x).strip().lower() for x in (it.get("tags_translated") or [])),
            ]
            joined = " ".join([x for x in bag if x])
            ok = True
            for t in tags:
                if t not in joined:
                    ok = False
                    break
            if not ok:
                continue
        out.append(it)
    return out


def _norm_rating(v: Any) -> float | None:
    try:
        n = float(v)
    except Exception:
        return None
    if n < 0:
        n = 0.0
    if n > 5:
        n = 5.0
    return round(n, 2)


def _filter_by_min_rating(items: list[dict[str, Any]], min_rating: float) -> list[dict[str, Any]]:
    need = max(0.0, min(5.0, float(min_rating or 0.0)))
    if need <= 0:
        return items
    out: list[dict[str, Any]] = []
    for it in items or []:
        rating = _norm_rating(((it.get("meta") or {}).get("rating")))
        if rating is None:
            continue
        if rating >= need:
            out.append(it)
    return out


class ImageEmbedPayload(BaseModel):
    image: str


class HomeFavoriteTogglePayload(BaseModel):
    source: str = ""
    arcid: str = ""
    favorited: bool | None = None


class HomeRatingSetPayload(BaseModel):
    source: str = ""
    arcid: str = ""
    rating: float | None = None

@router.post("/api/internal/embed/image", response_class=JSONResponse)
def embed_image_internal(payload: ImageEmbedPayload) -> JSONResponse:
    image_b64 = payload.image
    if not image_b64:
        return JSONResponse({"error": "missing image field"}, status_code=400)
    try:
        import base64
        image_bytes = base64.b64decode(image_b64)
    except Exception as e:
        return JSONResponse({"error": f"invalid base64: {e}"}, status_code=400)
    try:
        cfg, _ = resolve_config()
        model_id = str(cfg.get("SIGLIP_MODEL") or "google/siglip-so400m-patch14-384").strip()
        vec = _embed_image_siglip(image_bytes, model_id)
    except Exception as e:
        return JSONResponse({"error": f"embedding failed: {e}"}, status_code=500)
    if not vec:
        return JSONResponse({"error": "embedding empty"}, status_code=500)
    return JSONResponse({"embedding": vec})


@router.on_event("startup")
def _on_startup() -> None:
    print("[startup] system hook begin", flush=True)
    ensure_dirs()
    print("[startup] dirs ready", flush=True)
    apply_runtime_timezone()
    print("[startup] timezone applied", flush=True)
    try:
        dsn = db_dsn()
        print(f"[startup] db dsn {'present' if dsn else 'missing'}", flush=True)
        if dsn:
            threading.Thread(
                target=_ensure_auth_schema_in_background,
                args=(dsn,),
                daemon=True,
                name="auth-schema-startup",
            ).start()
    except Exception as e:
        print(f"[startup] auth schema dispatch skipped: {e}", flush=True)
    if not scheduler.running:
        scheduler.start()
    print("[startup] scheduler started", flush=True)
    threading.Thread(
        target=_sync_scheduler_in_background,
        daemon=True,
        name="scheduler-sync-startup",
    ).start()
    print("[startup] scheduler sync dispatched", flush=True)
    print("[startup] siglip startup warmup skipped", flush=True)
    try:
        cfg, _ = resolve_config()
        siglip_worker_enabled = str(cfg.get("SIGLIP_WORKER_ENABLED", "True")).strip().lower() in {"1", "true", "yes", "y", "on"}
        if siglip_worker_enabled:
            enable_local_embedding_worker()
        else:
            disable_local_embedding_worker()

    except Exception as e:
        print(f"[startup] worker toggle skipped: {e}", flush=True)
    print("[startup] system hook complete", flush=True)


@router.on_event("shutdown")
def _on_shutdown() -> None:
    stop_local_embedding_worker()
    if scheduler.running:
        scheduler.shutdown(wait=False)


@router.get("/api/visual-task/status")
def visual_task_status() -> dict[str, Any]:
    return {"ok": True, "status": get_local_embedding_worker_status()}


def request_process_restart(delay_s: float = 2.5) -> None:
    """Restart by exiting: the container's restart policy brings it back.

    This is the only way to reload everything -- model, workers, per-process
    caches -- from inside the container, and it is what un-suspends the visual
    task after a metadata restore (`stop_local_embedding_worker_until_restart`
    is deliberately in-memory). The delay leaves room for the HTTP response and
    the client-side message to go out before the socket closes.

    Deployments must set a restart policy. `Docker/quick_deploy_docker-compose.yml`
    carries `restart: unless-stopped`, and the manual `docker run` in STARTUP.md
    does too; without one this exit would simply stop the container.
    """

    def _exit() -> None:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(0)

    threading.Timer(max(0.5, float(delay_s)), _exit).start()


@router.post("/api/system/restart")
def restart_app() -> dict[str, Any]:
    """Exit so the container restarts. Admin-only, like every mutating route."""
    request_process_restart()
    return {"ok": True, "restart_scheduled": True, "delay_s": 2.5}


@router.post("/api/visual-task/stop")
def stop_visual_task() -> dict[str, Any]:
    stop_local_embedding_worker_until_restart()
    return {
        "ok": True,
        "message": "visual task stopped; restart container to restore automatic visual embedding",
    }


@router.post("/api/visual-task/enable")
def enable_visual_task() -> dict[str, Any]:
    enable_local_embedding_worker()
    return {"ok": True, "message": "visual task worker enabled"}


@router.post("/api/visual-task/disable")
def disable_visual_task() -> dict[str, Any]:
    disable_local_embedding_worker()
    return {"ok": True, "message": "visual task worker disabled"}


@router.get("/api/home/history")
def home_history(
    cursor: str = Query(default=""),
    limit: int = Query(default=24, ge=1, le=MAX_HOME_FEED_LIMIT),
    include_categories: str = Query(default=""),
    include_tags: str = Query(default=""),
    min_rating: float = Query(default=0.0),
) -> dict[str, Any]:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(str(cursor)))
        except Exception:
            offset = 0

    cats = _parse_csv_param(include_categories)
    tags = _parse_csv_param(include_tags)
    if "__none__" in cats:
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "history"}}
    cat_tag_vals = [f"category:{c}" for c in cats if c and c != "__none__"]

    works_conds: list[str] = ["COALESCE(w.source, 'lrr') = 'local'"]
    works_params: list[Any] = []
    if cat_tag_vals:
        works_conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) t(tag) WHERE lower(t.tag) = ANY(%s))")
        works_params.append(cat_tag_vals)
    for t in tags:
        works_conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) tt(tag) WHERE lower(tt.tag) LIKE %s)")
        works_params.append(f"%{t}%")

    sql = (
        "WITH local_latest AS ("
        "  SELECT arcid, max(read_time) AS read_time FROM read_events GROUP BY arcid"
        ") "
        "SELECT w.arcid, w.title, w.tags, w.eh_posted, w.date_added, w.lastreadtime, "
        "w.local_dir, w.source, w.raw, w.raw->>'rating' AS rating, "
        "w.raw->>'bookmark' AS bookmark, l.read_time "
        "FROM local_latest l "
        "JOIN works w ON w.arcid = l.arcid AND COALESCE(w.source, 'lrr') <> 'missing' "
        f"WHERE {' AND '.join(works_conds)} "
        "ORDER BY l.read_time DESC, w.arcid ASC OFFSET %s LIMIT %s"
    )
    rows = query_rows(sql, tuple([*works_params, int(offset), int(limit) + 1]))
    has_more = len(rows) > int(limit)
    cfg, _ = resolve_config()
    items = [_item_from_work(r, cfg) for r in rows[: int(limit)]]
    items = _filter_by_min_rating(items, min_rating)
    next_cursor = str(offset + int(limit)) if has_more else ""
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
        "meta": {"mode": "history"},
    }


@router.get("/api/home/local")
def home_local(
    request: Request,
    cursor: str = Query(default=""),
    limit: int = Query(default=24, ge=1, le=MAX_HOME_FEED_LIMIT),
    sort_by: str = Query(default="xp"),
    sort_order: str = Query(default="desc"),
    include_categories: str = Query(default=""),
    include_tags: str = Query(default=""),
    min_rating: float = Query(default=0.0),
) -> dict[str, Any]:
    safe_sort_by = str(sort_by or "xp").strip().lower()
    if safe_sort_by not in {"xp", "date_added", "eh_posted", "title"}:
        safe_sort_by = "xp"
    safe_sort_order = str(sort_order or "desc").strip().lower()
    if safe_sort_order not in {"asc", "desc"}:
        safe_sort_order = "desc"
    offset = 0
    if cursor:
        try:
            offset = max(0, int(str(cursor)))
        except Exception:
            offset = 0

    cfg, _ = resolve_config()
    cats = _parse_csv_param(include_categories)
    tags = _parse_csv_param(include_tags)
    if "__none__" in cats:
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "local", "sort_by": safe_sort_by, "sort_order": safe_sort_order}}

    rows: list[dict[str, Any]] = []
    use_xp = (safe_sort_by == "xp")
    fallback_active = False

    if use_xp:
        auth_user = getattr(request.state, "auth_user", {}) or {}
        user_id = str(auth_user.get("uid") or "default_user")
        ranked = get_local_recommendation_items_cached(cfg, user_id=user_id, sort_order=safe_sort_order)
        all_items = _apply_item_filters(list(ranked.get("items") or []), cats, tags)
        all_items = _filter_by_min_rating(all_items, min_rating)
        if all_items:
            end = offset + int(limit)
            items = all_items[offset:end]
            work_arcids = [str(it.get("arcid") or "").strip() for it in items if str(it.get("source") or "") == "works" and str(it.get("arcid") or "").strip()]
            if work_arcids:
                b_rows = query_rows(
                    "SELECT arcid, raw->>'bookmark' AS bookmark FROM works WHERE arcid = ANY(%s::text[])",
                    (work_arcids,),
                )
                b_map: dict[str, int] = {}
                for r in b_rows:
                    k = str(r.get("arcid") or "").strip()
                    if not k:
                        continue
                    try:
                        b_map[k] = max(0, int(r.get("bookmark") or 0))
                    except Exception:
                        b_map[k] = 0
                if b_map:
                    patched: list[dict[str, Any]] = []
                    for it in items:
                        if str(it.get("source") or "") != "works":
                            patched.append(it)
                            continue
                        arcid = str(it.get("arcid") or "").strip()
                        b = int(b_map.get(arcid, 0))
                        raw = dict(it.get("raw") or {})
                        raw["bookmark"] = b
                        patched.append({**it, "raw": raw})
                    items = patched
            next_cursor = str(end) if end < len(all_items) else ""
            return {
                "items": items,
                "next_cursor": next_cursor,
                "has_more": bool(next_cursor),
                "meta": {
                    **(ranked.get("meta") or {}),
                    "mode": "local",
                    "sort_by": safe_sort_by,
                    "sort_order": safe_sort_order,
                },
            }
        else:
            fallback_active = True

    # Fallback or explicit DB sorting (title, date_added, eh_posted)
    query_sort_by = "title" if fallback_active or safe_sort_by == "title" else safe_sort_by
    if query_sort_by == "title":
        order_clause = (
            "lower(COALESCE("
            "NULLIF(btrim(COALESCE(w.raw->'user_meta'->>'title', '')), ''), "
            "NULLIF(btrim(COALESCE(w.title, '')), ''), "
            "''"
            f")) {'ASC' if safe_sort_order == 'asc' else 'DESC'}, "
            f"w.arcid {'ASC' if safe_sort_order == 'asc' else 'DESC'}"
        )
    else:
        safe_col = "date_added" if query_sort_by == "date_added" else "eh_posted"
        order_clause = f"COALESCE(w.{safe_col}, 0) {'ASC' if safe_sort_order == 'asc' else 'DESC'}, w.arcid {'ASC' if safe_sort_order == 'asc' else 'DESC'}"

    conds: list[str] = ["COALESCE(w.source, 'lrr') <> 'missing'"]
    params: list[Any] = []
    cat_tag_vals = [f"category:{c}" for c in cats if c and c != "__none__"]
    if cat_tag_vals:
        conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) t(tag) WHERE lower(t.tag) = ANY(%s))")
        params.append(cat_tag_vals)
    for t in tags:
        conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) tt(tag) WHERE lower(tt.tag) LIKE %s)")
        params.append(f"%{t}%")
    where = f"WHERE {' AND '.join(conds)}"
    sql = (
        "SELECT w.arcid, w.title, w.tags, w.eh_posted, w.date_added, w.lastreadtime, w.local_dir, w.source, w.raw, w.raw->>'rating' AS rating, w.raw->>'bookmark' AS bookmark "
        "FROM works w "
        f"{where} "
        f"ORDER BY {order_clause} "
        "OFFSET %s LIMIT %s"
    )
    params.extend([int(offset), int(limit)])
    rows = query_rows(sql, tuple(params))
    items = [_item_from_work(r, cfg) for r in rows]
    items = _filter_by_min_rating(items, min_rating)
    next_cursor = str(offset + int(limit)) if len(rows) >= int(limit) else ""
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
        "meta": {
            "mode": "local",
            "sort_by": safe_sort_by,
            "sort_order": safe_sort_order,
            "fallback": fallback_active,
        },
    }


@router.get("/api/home/favorite")
def home_favorite(
    cursor: str = Query(default=""),
    limit: int = Query(default=24, ge=1, le=MAX_HOME_FEED_LIMIT),
    include_categories: str = Query(default=""),
    include_tags: str = Query(default=""),
    min_rating: float = Query(default=0.0),
) -> dict[str, Any]:
    offset = 0
    if cursor:
        try:
            offset = max(0, int(str(cursor)))
        except Exception:
            offset = 0

    cfg, _ = resolve_config()
    cats = _parse_csv_param(include_categories)
    tags = _parse_csv_param(include_tags)
    if "__none__" in cats:
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "favorite"}}

    cat_tag_vals = [f"category:{c}" for c in cats if c and c != "__none__"]

    works_conds = [
        "COALESCE(w.source, 'lrr') <> 'missing'",
        "EXISTS (SELECT 1 FROM unnest(w.tags) fav(tag) WHERE lower(fav.tag) = 'favorited')",
    ]
    works_params: list[Any] = []
    if cat_tag_vals:
        works_conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) t(tag) WHERE lower(t.tag) = ANY(%s))")
        works_params.append(cat_tag_vals)
    for t in tags:
        works_conds.append("EXISTS (SELECT 1 FROM unnest(w.tags) tt(tag) WHERE lower(tt.tag) LIKE %s)")
        works_params.append(f"%{t}%")

    sql = (
        "SELECT w.arcid, w.title, w.tags, w.eh_posted, w.date_added, w.lastreadtime, "
        "w.local_dir, w.source, w.raw, w.raw->>'rating' AS rating, "
        "w.raw->>'bookmark' AS bookmark "
        "FROM works w "
        f"WHERE {' AND '.join(works_conds)} "
        "ORDER BY COALESCE(w.lastreadtime, w.date_added, w.eh_posted, 0) DESC, w.arcid ASC "
        "OFFSET %s LIMIT %s"
    )
    rows = query_rows(sql, tuple([*works_params, int(offset), int(limit) + 1]))
    has_more = len(rows) > int(limit)
    items = [_item_from_work(r, cfg) for r in rows[: int(limit)]]
    items = _filter_by_min_rating(items, min_rating)

    next_cursor = str(offset + int(limit)) if has_more else ""
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
        "meta": {"mode": "favorite"},
    }


@router.post("/api/home/favorite/toggle")
def home_favorite_toggle(payload: HomeFavoriteTogglePayload) -> dict[str, Any]:
    source = str(payload.source or "").strip().lower()
    set_on = payload.favorited
    cfg, _ = resolve_config()

    if source == "works":
        arcid = str(payload.arcid or "").strip()
        if not arcid:
            raise HTTPException(status_code=400, detail="invalid arcid")
        if set_on is None:
            probe = query_rows(
                "SELECT EXISTS (SELECT 1 FROM works w, unnest(w.tags) t(tag) WHERE w.arcid = %s AND lower(t.tag) = 'favorited') AS on",
                (arcid,),
            )
            is_on = bool((probe[0] or {}).get("on")) if probe else False
            set_on = not is_on
        rows = query_rows(
            "UPDATE works w "
            "SET tags = CASE "
            "WHEN %s THEN CASE "
            "WHEN EXISTS (SELECT 1 FROM unnest(w.tags) t(tag) WHERE lower(t.tag) = 'favorited') THEN w.tags "
            "ELSE array_append(w.tags, 'favorited') END "
            "ELSE COALESCE(ARRAY(SELECT t FROM unnest(w.tags) t WHERE lower(t) <> 'favorited'), ARRAY[]::text[]) "
            "END "
            "WHERE w.arcid = %s "
            "RETURNING w.arcid, w.title, w.tags, w.eh_posted, w.date_added, w.lastreadtime, w.local_dir, w.source, w.raw, w.raw->>'rating' AS rating, w.raw->>'bookmark' AS bookmark",
            (bool(set_on), arcid),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="work not found")
        item = _item_from_work(rows[0], cfg)
        return {"ok": True, "favorited": bool(set_on), "item": item}

    raise HTTPException(status_code=400, detail="invalid source")


@router.post("/api/home/rating/set")
def home_rating_set(payload: HomeRatingSetPayload) -> dict[str, Any]:
    source = str(payload.source or "").strip().lower()
    rating = _norm_rating(payload.rating)
    rating_str = "" if rating is None else (f"{rating:.2f}".rstrip("0").rstrip("."))
    cfg, _ = resolve_config()

    if source == "works":
        arcid = str(payload.arcid or "").strip()
        if not arcid:
            raise HTTPException(status_code=400, detail="invalid arcid")
        rows = query_rows(
            "UPDATE works w "
            "SET raw = COALESCE(w.raw, '{}'::jsonb) || jsonb_build_object('rating', %s::text), "
            "last_seen_at = now() "
            "WHERE w.arcid = %s "
            "RETURNING w.arcid, w.title, w.tags, w.eh_posted, w.date_added, w.lastreadtime, w.local_dir, w.source, w.raw, w.raw->>'rating' AS rating, w.raw->>'bookmark' AS bookmark",
            (rating_str, arcid),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="work not found")
        return {"ok": True, "item": _item_from_work(rows[0], cfg)}

    raise HTTPException(status_code=400, detail="invalid source")


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    raise HTTPException(status_code=404, detail="frontend not built")


@router.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest() -> FileResponse:
    p = STATIC_DIR / "manifest.webmanifest"
    if p.exists():
        return FileResponse(str(p), media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="manifest not found")


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    p = STATIC_DIR / "sw.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="service worker not found")


@router.get("/workbox-{name}.js", include_in_schema=False)
def workbox_bundle(name: str) -> FileResponse:
    safe = str(name or "").strip()
    if not safe:
        raise HTTPException(status_code=404, detail="not found")
    p = STATIC_DIR / f"workbox-{safe}.js"
    if p.exists():
        return FileResponse(str(p), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="not found")


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    p = STATIC_DIR / "favicon.ico"
    if p.exists():
        return FileResponse(str(p))
    raise HTTPException(status_code=404, detail="favicon not found")


@router.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str) -> FileResponse:
    p = str(path or "").strip()
    if not p:
        return index()
    if p.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    candidate = STATIC_DIR / p
    if candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate))
    idx = STATIC_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    raise HTTPException(status_code=404, detail="frontend not built")
