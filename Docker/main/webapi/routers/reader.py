import asyncio
import io
import json
import logging
import mimetypes
import secrets
import time
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query, Response
from PIL import Image, UnidentifiedImageError

from ..core.schemas import ReaderReadEventRequest
from ..core.config_values import as_bool as _as_bool
import zipfile
from ..services.config_service import resolve_config
from ..services.db_service import db_dsn, query_rows
from ..services.local_lib_service import first_local_gallery_image, get_work_source_local_dir, list_local_gallery_pages, _safe_join_local_dir
from ..services.rec_service_local import similar_items_for_gallery

router = APIRouter(tags=["reader"])
logger = logging.getLogger(__name__)

_reader_manifest_lock = asyncio.Lock()
_reader_manifest_cache: dict[str, dict[str, Any]] = {}
_reader_session_lock = asyncio.Lock()
_reader_sessions: dict[str, dict[str, Any]] = {}
_reader_session_ttl_s = 1800.0
_reader_session_max_cache_pages = 48


def invalidate_reader_caches(arcid: str = "") -> None:
    """Drop cached reader state for one gallery, or all of it when arcid is "".

    Call this whenever a gallery's files or row change. Both caches are keyed by
    arcid, and a local arcid is a hash of the gallery's *path* -- so a gallery
    deleted and then re-uploaded under the same folder name reuses the same key.
    Left alone, the manifest cache keeps answering with the previous gallery's
    page list, and every page request then 404s ("local reader page missing")
    because those page names do not exist in the new gallery.

    Deliberately synchronous: the callers are sync endpoints running in a
    threadpool, so they must not await the event loop's locks. The mutations are
    plain dict operations, which are atomic under the GIL.
    """
    key = str(arcid or "").strip()
    if not key:
        _reader_manifest_cache.clear()
        doomed = list(_reader_sessions.keys())
    else:
        _reader_manifest_cache.pop(key, None)
        doomed = [
            sid for sid, session in _reader_sessions.items()
            if isinstance(session, dict) and str(session.get("arcid") or "") == key
        ]
    for sid in doomed:
        session = _reader_sessions.pop(sid, None)
        if not isinstance(session, dict):
            continue
        task = session.get("task")
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()


def _normalize_reader_quality_mode(raw: Any, cfg: dict[str, Any] | None = None) -> str:
    text = str(raw or "").strip().lower()
    if not text and isinstance(cfg, dict):
        text = str(cfg.get("READER_IMAGE_QUALITY_MODE") or "high").strip().lower()
    return text if text in {"low", "mid", "high", "original"} else "high"


def _reader_quality_spec(mode: str) -> tuple[int, int] | None:
    return {
        "low": (360, 60),
        "mid": (720, 75),
        "high": (1080, 85),
        "original": None,
    }.get(str(mode or "high"), (1080, 85))


def _reader_transform_image_bytes(data: bytes, ctype: str, mode: str) -> tuple[bytes, str]:
    safe_mode = _normalize_reader_quality_mode(mode)
    spec = _reader_quality_spec(safe_mode)
    if spec is None:
        return data, ctype
    if not isinstance(data, (bytes, bytearray)) or not data:
        return data, ctype
    max_edge, quality = spec
    try:
        with Image.open(io.BytesIO(data)) as img:
            frame = img.convert("RGB")
            resampling = getattr(Image, "Resampling", Image)
            frame.thumbnail((max_edge, max_edge), resample=resampling.LANCZOS)
            bio = io.BytesIO()
            frame.save(bio, format="WEBP", quality=quality, method=6)
            return bio.getvalue(), "image/webp"
    except (UnidentifiedImageError, OSError):
        return data, ctype


def _safe_json_dump(obj: Any) -> str:
    if isinstance(obj, dict):
        return json.dumps(obj, ensure_ascii=False)
    return "{}"


def _process_read_event_sync(req_obj: dict[str, Any]) -> None:
    try:
        safe_arcid = str(req_obj.get("arcid") or "").strip()
        if not safe_arcid:
            return
        read_time = int(req_obj.get("read_time") or int(time.time()))
        source_file = str(req_obj.get("source_file") or "reader-ui").strip() or "reader-ui"
        ingested_at = str(req_obj.get("ingested_at") or "").strip() or None
        raw = req_obj.get("raw") if isinstance(req_obj.get("raw"), dict) else {}
        dsn = str(db_dsn() or "").strip()
        if not dsn:
            logger.warning("reader read-event ignored: POSTGRES_DSN missing")
            return

        sql = (
            "INSERT INTO read_events (arcid, read_time, source_file, ingested_at, raw) "
            "VALUES (%s, %s, %s, COALESCE(%s::timestamptz, now()), %s::jsonb) "
            "ON CONFLICT (arcid, read_time) DO NOTHING"
        )
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (safe_arcid, read_time, source_file, ingested_at, _safe_json_dump(raw)))
            conn.commit()

        # Keep this gallery's sidecar history current. A read is the only event
        # that changes `read_events`, so it is also the only cheap moment to
        # refresh the backup -- but it must never *create* the sidecar (that
        # belongs to the embedding run, the first moment there is anything
        # expensive to protect), hence `only_if_exists`.
        try:
            from ..services.gallery_metadata_backup import write_sidecar

            write_sidecar(safe_arcid, only_if_exists=True)
        except Exception:
            logger.exception("reader sidecar refresh failed")
    except Exception:
        logger.exception("reader read-event background task failed")


async def _load_reader_manifest(arcid: str, *, force: bool = False) -> list[str]:
    key = str(arcid or "").strip()
    if not key:
        return []
    if not force:
        async with _reader_manifest_lock:
            cached = _reader_manifest_cache.get(key)
            if cached and isinstance(cached.get("pages"), list) and cached.get("pages"):
                return list(cached.get("pages") or [])

    source_kind, local_dir = get_work_source_local_dir(key)
    local_pages = list_local_gallery_pages(local_dir) if local_dir else []
    if local_pages:
        async with _reader_manifest_lock:
            _reader_manifest_cache[key] = {"pages": list(local_pages), "mode": "local", "local_dir": local_dir}
        return local_pages
    if source_kind == "local":
        async with _reader_manifest_lock:
            _reader_manifest_cache[key] = {"pages": [], "mode": "local", "local_dir": local_dir}
        return []

    async with _reader_manifest_lock:
        _reader_manifest_cache[key] = {"pages": [], "mode": "local", "local_dir": local_dir}
    return []


def _reader_ahead(v: Any, default: int = 10) -> int:
    try:
        n = int(v)
    except Exception:
        n = int(default)
    return max(1, min(20, n))


def _reader_page(v: Any, total: int) -> int:
    try:
        n = int(v)
    except Exception:
        n = 1
    return max(1, min(max(1, int(total)), n))


async def _fetch_reader_page_bytes(arcid: str, page_path: str) -> tuple[bytes, str]:
    safe_arcid = str(arcid or "").strip()
    p = str(page_path or "").strip()
    if not safe_arcid or not p:
        raise HTTPException(status_code=404, detail="reader page path missing")

    source_kind, local_dir = get_work_source_local_dir(safe_arcid)
    if local_dir:
        try:
            base = _safe_join_local_dir(local_dir)
        except Exception:
            base = None
        if base is not None and base.exists():
            if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
                try:
                    with zipfile.ZipFile(base, "r") as zf:
                        data = zf.read(p)
                        ctype = str(mimetypes.guess_type(p)[0] or "image/jpeg")
                        return data, ctype
                except Exception as e:
                    raise HTTPException(status_code=404, detail=f"read zip page failed: {e}")
            elif base.is_dir():
                cand = (base / p).resolve()
                try:
                    cand.relative_to(base)
                except Exception:
                    cand = None
                if cand is not None and cand.exists() and cand.is_file():
                    ctype = str(mimetypes.guess_type(str(cand))[0] or "image/jpeg")
                    return cand.read_bytes(), ctype
    if source_kind == "local":
        raise HTTPException(status_code=404, detail="local reader page missing")

    raise HTTPException(status_code=404, detail="reader page missing from local library")


def _reader_session_targets(session: dict[str, Any]) -> list[int]:
    total = max(1, int(session.get("page_count") or 1))
    cursor = _reader_page(session.get("cursor") or 1, total)
    ahead = _reader_ahead(session.get("ahead") or 10)
    targets: list[int] = []
    for idx in range(cursor, min(total, cursor + ahead) + 1):
        targets.append(int(idx))
    back = cursor - 1
    if back >= 1:
        targets.insert(0, int(back))
    return targets


def _reader_trim_cache(session: dict[str, Any]) -> None:
    cache = session.get("cache")
    if not isinstance(cache, dict):
        session["cache"] = {}
        return
    total = max(1, int(session.get("page_count") or 1))
    cursor = _reader_page(session.get("cursor") or 1, total)
    ahead = _reader_ahead(session.get("ahead") or 10)
    keep_min = max(1, cursor - 2)
    keep_max = min(total, cursor + ahead + 2)
    drop_keys = [k for k in cache.keys() if int(k) < keep_min or int(k) > keep_max]
    for k in drop_keys:
        cache.pop(int(k), None)
    if len(cache) <= _reader_session_max_cache_pages:
        return
    rows = sorted(cache.items(), key=lambda kv: float((kv[1] or {}).get("last_access") or 0.0))
    to_drop = len(cache) - _reader_session_max_cache_pages
    for k, _ in rows[: max(0, to_drop)]:
        cache.pop(int(k), None)


def _reader_session_view(session: dict[str, Any]) -> dict[str, Any]:
    cache_obj = session.get("cache")
    cache: dict[int, dict[str, Any]] = cache_obj if isinstance(cache_obj, dict) else {}
    fetching_obj = session.get("fetching")
    fetching: set[int] = fetching_obj if isinstance(fetching_obj, set) else set()
    target_pages = sorted({int(p) for p in _reader_session_targets(session) if int(p) >= 1})
    cached_pages = sorted(int(k) for k in cache.keys())
    cached_target_pages = sorted(p for p in target_pages if p in cache)
    pending_target_pages = sorted(p for p in target_pages if p not in cache)
    target_count = len(target_pages)
    preload_percent = int(round((len(cached_target_pages) / target_count) * 100.0)) if target_count > 0 else 100
    return {
        "session_id": str(session.get("session_id") or ""),
        "arcid": str(session.get("arcid") or ""),
        "title": str(session.get("title") or ""),
        "page_count": int(session.get("page_count") or 0),
        "cursor": int(session.get("cursor") or 1),
        "ahead": int(session.get("ahead") or 10),
        "cached_pages": cached_pages,
        "cached_count": len(cache),
        "fetching_pages": sorted(int(x) for x in fetching),
        "fetching_count": len(fetching),
        "preload_target_pages": target_pages,
        "preload_target_count": target_count,
        "preload_cached_pages": cached_target_pages,
        "preload_cached_count": len(cached_target_pages),
        "preload_pending_pages": pending_target_pages,
        "preload_pending_count": len(pending_target_pages),
        "preload_percent": max(0, min(100, preload_percent)),
        "status": str(session.get("status") or "idle"),
        "error": str(session.get("error") or ""),
        "created_at": float(session.get("created_at") or 0.0),
        "last_touch": float(session.get("last_touch") or 0.0),
    }


async def _prune_reader_sessions_locked(now_ts: float) -> None:
    stale: list[str] = []
    for sid, s in _reader_sessions.items():
        last_touch = float(s.get("last_touch") or 0.0)
        if now_ts - last_touch > _reader_session_ttl_s:
            stale.append(sid)
    for sid in stale:
        session = _reader_sessions.pop(sid, None)
        task = session.get("task") if isinstance(session, dict) else None
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()


async def _reader_session_worker(session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    while True:
        page_idx = 0
        page_path = ""
        arcid = ""
        await asyncio.sleep(0)
        async with _reader_session_lock:
            now_ts = time.monotonic()
            await _prune_reader_sessions_locked(now_ts)
            session = _reader_sessions.get(sid)
            if not isinstance(session, dict):
                return
            session["status"] = "running"
            session["last_touch"] = now_ts
            cache_obj = session.get("cache")
            cache: dict[int, dict[str, Any]] = cache_obj if isinstance(cache_obj, dict) else {}
            session["cache"] = cache
            fetching_obj = session.get("fetching")
            fetching: set[int] = fetching_obj if isinstance(fetching_obj, set) else set()
            session["fetching"] = fetching
            targets = _reader_session_targets(session)
            for p in targets:
                if p in cache or p in fetching:
                    continue
                pages_obj = session.get("pages")
                pages: list[str] = pages_obj if isinstance(pages_obj, list) else []
                if p < 1 or p > len(pages):
                    continue
                page_idx = int(p)
                page_path = str(pages[p - 1] or "").strip()
                arcid = str(session.get("arcid") or "").strip()
                fetching.add(page_idx)
                break
        if page_idx <= 0:
            await asyncio.sleep(0.22)
            continue

        ok = False
        err_txt = ""
        data: bytes | None = None
        ctype = "image/jpeg"
        try:
            data, ctype = await _fetch_reader_page_bytes(arcid, page_path)
            ok = True
        except Exception as e:
            err_txt = str(e)

        async with _reader_session_lock:
            session = _reader_sessions.get(sid)
            if not isinstance(session, dict):
                continue
            fetching_obj = session.get("fetching")
            fetching: set[int] = fetching_obj if isinstance(fetching_obj, set) else set()
            fetching.discard(page_idx)
            session["fetching"] = fetching
            if ok and data is not None:
                cache_obj = session.get("cache")
                cache: dict[int, dict[str, Any]] = cache_obj if isinstance(cache_obj, dict) else {}
                cache[int(page_idx)] = {
                    "data": data,
                    "ctype": str(ctype or "image/jpeg"),
                    "created_at": time.monotonic(),
                    "last_access": time.monotonic(),
                }
                session["cache"] = cache
                session["error"] = ""
                _reader_trim_cache(session)
            else:
                session["error"] = err_txt


@router.get("/api/reader/{arcid}/manifest")
async def reader_manifest(arcid: str) -> dict[str, Any]:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    pages = await _load_reader_manifest(safe_arcid)
    row = query_rows("SELECT title, raw->>'bookmark' AS bookmark FROM works WHERE arcid = %s LIMIT 1", (safe_arcid,))
    title = str((row[0] if row else {}).get("title") or "")
    bookmark_raw = str((row[0] if row else {}).get("bookmark") or "").strip()
    try:
        bookmark = max(1, int(bookmark_raw)) if bookmark_raw else 1
    except Exception:
        bookmark = 1
    return {"arcid": safe_arcid, "title": title, "page_count": len(pages), "bookmark": int(bookmark)}


@router.get("/api/reader/{arcid}/similar")
def reader_similar_galleries(
    arcid: str,
    limit: int = Query(default=6, ge=1, le=12),
) -> dict[str, Any]:
    """Candidates for the end-of-gallery "guess you like" strip.

    Scored from this gallery's own cover vector + tags, normalised against each
    other -- see `rec_service_local.similar_items_for_gallery` for why the page
    vectors and the XP profile are deliberately not part of it.
    """
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    cfg, _ = resolve_config()
    if not _as_bool(cfg.get("READER_REC_ENABLED"), True):
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "reader_similar", "disabled": True}}
    return similar_items_for_gallery(safe_arcid, limit=int(limit), cfg=cfg)


@router.post("/api/reader/{arcid}/session")
async def reader_session_start(
    arcid: str,
    page: int = Query(default=1, ge=1),
    ahead: int = Query(default=10, ge=1, le=20),
) -> dict[str, Any]:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    pages = await _load_reader_manifest(safe_arcid)
    if not pages:
        raise HTTPException(status_code=404, detail="manifest pages empty")
    row = query_rows("SELECT title FROM works WHERE arcid = %s LIMIT 1", (safe_arcid,))
    title = str((row[0] if row else {}).get("title") or "")

    sid = secrets.token_urlsafe(12)
    now_ts = time.monotonic()
    total = len(pages)
    session = {
        "session_id": sid,
        "arcid": safe_arcid,
        "title": title,
        "pages": list(pages),
        "page_count": int(total),
        "cursor": _reader_page(page, total),
        "ahead": _reader_ahead(ahead),
        "cache": {},
        "fetching": set(),
        "status": "running",
        "error": "",
        "created_at": now_ts,
        "last_touch": now_ts,
        "task": None,
    }
    async with _reader_session_lock:
        await _prune_reader_sessions_locked(now_ts)
        _reader_sessions[sid] = session
        task = asyncio.create_task(_reader_session_worker(sid))
        session["task"] = task
    return {"ok": True, **_reader_session_view(session)}


@router.post("/api/reader/session/{session_id}/cursor")
async def reader_session_cursor(
    session_id: str,
    page: int = Query(default=1, ge=1),
    ahead: int = Query(default=10, ge=1, le=20),
) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    async with _reader_session_lock:
        now_ts = time.monotonic()
        await _prune_reader_sessions_locked(now_ts)
        session = _reader_sessions.get(sid)
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="reader session not found")
        total = max(1, int(session.get("page_count") or 1))
        session["cursor"] = _reader_page(page, total)
        session["ahead"] = _reader_ahead(ahead)
        session["last_touch"] = now_ts
        _reader_trim_cache(session)
        view = _reader_session_view(session)
    return {"ok": True, **view}


@router.get("/api/reader/session/{session_id}/status")
async def reader_session_status(session_id: str) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    async with _reader_session_lock:
        now_ts = time.monotonic()
        await _prune_reader_sessions_locked(now_ts)
        session = _reader_sessions.get(sid)
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="reader session not found")
        session["last_touch"] = now_ts
        view = _reader_session_view(session)
    return {"ok": True, **view}


@router.delete("/api/reader/session/{session_id}")
async def reader_session_close(session_id: str) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    async with _reader_session_lock:
        session = _reader_sessions.pop(sid, None)
    task = session.get("task") if isinstance(session, dict) else None
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()
    return {"ok": True, "closed": bool(session)}


@router.get("/api/reader/session/{session_id}/page/{index}")
async def reader_session_page(session_id: str, index: int, mode: str = Query(default="")) -> Response:
    sid = str(session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required")
    idx = int(index)
    if idx < 1:
        raise HTTPException(status_code=400, detail="index must be >= 1")

    arcid = ""
    page_path = ""
    cached_data: bytes | None = None
    cached_ctype = "image/jpeg"
    async with _reader_session_lock:
        now_ts = time.monotonic()
        await _prune_reader_sessions_locked(now_ts)
        session = _reader_sessions.get(sid)
        if not isinstance(session, dict):
            raise HTTPException(status_code=404, detail="reader session not found")
        total = max(1, int(session.get("page_count") or 1))
        if idx > total:
            raise HTTPException(status_code=404, detail="page out of range")
        session["cursor"] = _reader_page(idx, total)
        session["last_touch"] = now_ts
        cache_obj = session.get("cache")
        cache: dict[int, dict[str, Any]] = cache_obj if isinstance(cache_obj, dict) else {}
        row = cache.get(idx)
        if isinstance(row, dict) and isinstance(row.get("data"), (bytes, bytearray)):
            row["last_access"] = time.monotonic()
            cached_data = bytes(row.get("data") or b"")
            cached_ctype = str(row.get("ctype") or "image/jpeg")
        pages_obj = session.get("pages")
        pages: list[str] = pages_obj if isinstance(pages_obj, list) else []
        page_path = str(pages[idx - 1] or "").strip() if idx - 1 < len(pages) else ""
        arcid = str(session.get("arcid") or "").strip()

    if cached_data is not None and cached_data:
        cfg, _ = resolve_config()
        transformed, media_type = await asyncio.to_thread(_reader_transform_image_bytes, cached_data, cached_ctype, _normalize_reader_quality_mode(mode, cfg))
        return Response(content=transformed, media_type=media_type, headers={"X-Reader-Session-Cache": "HIT"})

    data, ctype = await _fetch_reader_page_bytes(arcid, page_path)
    async with _reader_session_lock:
        session = _reader_sessions.get(sid)
        if isinstance(session, dict):
            cache_obj = session.get("cache")
            cache: dict[int, dict[str, Any]] = cache_obj if isinstance(cache_obj, dict) else {}
            cache[idx] = {
                "data": data,
                "ctype": str(ctype or "image/jpeg"),
                "created_at": time.monotonic(),
                "last_access": time.monotonic(),
            }
            session["cache"] = cache
            session["error"] = ""
            _reader_trim_cache(session)
    cfg, _ = resolve_config()
    transformed, media_type = await asyncio.to_thread(_reader_transform_image_bytes, data, ctype, _normalize_reader_quality_mode(mode, cfg))
    return Response(content=transformed, media_type=media_type, headers={"X-Reader-Session-Cache": "MISS"})


@router.get("/api/reader/{arcid}/page/{index}")
async def reader_page(arcid: str, index: int, mode: str = Query(default="")) -> Response:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    if int(index) < 1:
        raise HTTPException(status_code=400, detail="index must be >= 1")
    pages = await _load_reader_manifest(safe_arcid)
    if int(index) > len(pages):
        raise HTTPException(status_code=404, detail="page out of range")

    page_path = str(pages[int(index) - 1] or "").strip()
    if not page_path:
        raise HTTPException(status_code=404, detail="page path missing")
    data, ctype = await _fetch_reader_page_bytes(safe_arcid, page_path)
    cfg, _ = resolve_config()
    transformed, media_type = await asyncio.to_thread(_reader_transform_image_bytes, data, ctype, _normalize_reader_quality_mode(mode, cfg))
    return Response(content=transformed, media_type=media_type)


@router.post("/api/reader/read-event")
async def reader_read_event(req: ReaderReadEventRequest) -> dict[str, Any]:
    safe_arcid = str(req.arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    try:
        payload = {
            "arcid": safe_arcid,
            "read_time": int(req.read_time or int(time.time())),
            "source_file": str(req.source_file or "reader-ui"),
            "ingested_at": str(req.ingested_at or ""),
            "raw": req.raw if isinstance(req.raw, dict) else {},
        }
        asyncio.create_task(asyncio.to_thread(_process_read_event_sync, payload))
        return {"ok": True, "queued": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"queue read_event failed: {e}")


@router.post("/api/reader/bookmark/set")
async def reader_bookmark_set(
    arcid: str = Query(default=""),
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    safe_arcid = str(arcid or "").strip()
    safe_page = max(1, int(page or 1))

    if safe_arcid:
        rows = query_rows(
            "UPDATE works "
            "SET raw = jsonb_set(COALESCE(raw, '{}'::jsonb), '{bookmark}', %s::jsonb), "
            "last_seen_at = now() "
            "WHERE arcid = %s "
            "RETURNING arcid",
            (json.dumps(str(safe_page), ensure_ascii=False), safe_arcid),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="work not found")
        return {"ok": True, "scope": "works", "arcid": safe_arcid, "bookmark": safe_page}

    raise HTTPException(status_code=400, detail="arcid required")
