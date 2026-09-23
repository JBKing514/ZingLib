import asyncio
import os
from typing import Any
from fastapi import APIRouter, HTTPException, Query, Response
from PIL import UnidentifiedImageError

from ..services.config_service import resolve_config
from ..services.local_lib_service import first_local_gallery_image, get_work_source_local_dir
from ..services.thumb_service import (
    build_thumb_cache as _build_work_thumb_cache,
    normalize_thumb_preset as _normalize_thumb_preset,
    work_thumb_cache_file as _work_thumb_cache_file,
)

router = APIRouter(tags=["media"])


def _count_open_fds() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except Exception:
        return -1


@router.get("/api/thumb/work/{arcid}")
async def thumb_work(arcid: str, preset: str = Query(default="")) -> Response:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    cfg, _ = resolve_config()
    safe_preset = _normalize_thumb_preset(preset, cfg)

    cache_file = _work_thumb_cache_file(safe_arcid, safe_preset)
    if cache_file.exists() and cache_file.is_file():
        try:
            cached = await asyncio.to_thread(cache_file.read_bytes)
            if cached:
                return Response(content=cached, media_type="image/webp", headers={"X-Thumb-Cache": "HIT", "X-Thumb-Preset": safe_preset})
        except Exception:
            pass

    source_kind, local_dir = get_work_source_local_dir(safe_arcid)
    if local_dir:
        local_thumb = first_local_gallery_image(local_dir)
        if local_thumb is not None and local_thumb.exists() and local_thumb.is_file():
            try:
                if local_thumb.suffix.lower() in {".zip", ".cbz"}:
                    import zipfile
                    from ..services.local_lib_service import list_local_gallery_pages
                    pages = list_local_gallery_pages(local_dir)
                    if not pages:
                        raise HTTPException(status_code=404, detail="no images found in zip")
                    with zipfile.ZipFile(local_thumb, "r") as zf:
                        img_bytes = zf.read(pages[0])
                    data = await asyncio.to_thread(_build_work_thumb_cache, img_bytes, cache_file, safe_preset)
                else:
                    data = await asyncio.to_thread(_build_work_thumb_cache, local_thumb, cache_file, safe_preset)
            except UnidentifiedImageError:
                raise HTTPException(status_code=422, detail="unsupported local image")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"build local thumbnail failed: {e}")
            return Response(content=data, media_type="image/webp", headers={"X-Thumb-Cache": "MISS", "X-Thumb-Preset": safe_preset})
    if source_kind == "local":
        raise HTTPException(status_code=404, detail="local thumbnail missing")
    raise HTTPException(status_code=404, detail="work thumbnail missing")


@router.get("/api/thumb/runtime-stats")
def thumb_runtime_stats() -> dict[str, Any]:
    return {
        "ok": True,
        "thumb_client": {
            "active": False,
            "age_s": 0.0,
            "rotate_s": 0.0,
            "rotations": 0,
            "errors": 0,
            "pool_resets": 0,
        },
        "limits": {"open_fds": _count_open_fds()},
    }
