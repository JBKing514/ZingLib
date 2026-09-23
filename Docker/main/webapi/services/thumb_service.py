"""Shared thumbnail rendering used by both the work and staging routers.

The thumbnail pipeline was originally private to ``routers/media.py``. The
staged-upload review list needs exactly the same resize/encode/cache behaviour
for files that have no ``works`` row yet, and importing one router from another
would invert the intended layering (routers depend on services, not on each
other). The helpers therefore live here and both routers import them.

Nothing in this module touches the network.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from PIL import Image

from ..core.constants import THUMB_GALLARY_DIR

# Preset name -> longest edge in pixels. "mid" is the default everywhere.
_PRESET_ALIASES: dict[str, str] = {
    "low": "300",
    "mid": "600",
    "high": "900",
    "ultra": "1200",
    "300": "300",
    "600": "600",
    "900": "900",
    "1200": "1200",
}


def normalize_thumb_preset(raw: str | int | None, cfg: dict[str, Any] | None = None) -> str:
    """Resolve a preset name/number to a concrete pixel width."""
    text = str(raw or "").strip().lower()
    if not text and isinstance(cfg, dict):
        text = str(cfg.get("LOCAL_THUMB_PRESET") or "mid").strip().lower()
    return _PRESET_ALIASES.get(text, "600")


def thumb_quality_for_preset(preset: str) -> int:
    return {
        "300": 64,
        "600": 76,
        "900": 84,
        "1200": 90,
    }.get(str(preset or "600"), 76)


def thumb_size_for_preset(preset: str) -> tuple[int, int]:
    width = int(str(preset or "600") or 600)
    return width, int(round(width * 1.5))


def work_thumb_cache_file(arcid: str, preset: str) -> Path:
    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", str(arcid or "").strip())
    if not safe:
        safe = "work"
    safe_preset = normalize_thumb_preset(preset)
    return THUMB_GALLARY_DIR / f"{safe}_cover_{safe_preset}.webp"


def build_thumb_cache(src: Path | bytes, cache_file: Path, preset: str) -> bytes:
    """Render ``src`` to a cached WebP cover and return the encoded bytes."""
    THUMB_GALLARY_DIR.mkdir(parents=True, exist_ok=True)
    resampling = getattr(Image, "Resampling", Image)
    safe_preset = normalize_thumb_preset(preset)
    target_size = thumb_size_for_preset(safe_preset)
    quality = thumb_quality_for_preset(safe_preset)
    fp = io.BytesIO(src) if isinstance(src, bytes) else src
    with Image.open(fp) as img:
        frame = img.convert("RGB")
        frame.thumbnail(target_size, resample=resampling.LANCZOS)
        bio = io.BytesIO()
        frame.save(bio, format="WEBP", quality=quality, method=6)
        data = bio.getvalue()
    tmp = cache_file.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(cache_file)
    return data
