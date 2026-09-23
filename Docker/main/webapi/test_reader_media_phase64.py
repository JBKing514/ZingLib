#!/usr/bin/env python3
"""
Regression test for phase 6.4 reader/media helpers.

- thumbnail preset normalization and cache naming
- reader compression modes
- reader session preload progress payload
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from webapi.routers.media import _normalize_thumb_preset, _work_thumb_cache_file
    from webapi.routers.reader import _normalize_reader_quality_mode, _reader_session_view, _reader_transform_image_bytes
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.media import _normalize_thumb_preset, _work_thumb_cache_file
    from webapi.routers.reader import _normalize_reader_quality_mode, _reader_session_view, _reader_transform_image_bytes


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_fixture_bytes(size: tuple[int, int] = (2000, 1500)) -> bytes:
    img = Image.new("RGB", size, (80, 140, 220))
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=95)
    return bio.getvalue()


def main() -> int:
    print("=" * 72)
    print("Phase 6.4 reader/media regression")
    print("=" * 72)

    print("[1] Thumbnail presets normalize to stable cache variants")
    assert_true(_normalize_thumb_preset("low") == "300", "low thumbnail preset should map to 300")
    assert_true(_normalize_thumb_preset("ultra") == "1200", "ultra thumbnail preset should map to 1200")
    cache_path = _work_thumb_cache_file("phase64-demo", "high")
    assert_true(cache_path.name.endswith("_cover_900.webp"), "thumbnail cache file should encode the preset")

    print("[2] Reader compression modes return bounded webp output")
    raw_bytes = build_fixture_bytes()
    low_bytes, low_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "low")
    original_bytes, original_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "original")
    assert_true(low_type == "image/webp", "low-quality reader output should be webp")
    assert_true(original_type == "image/jpeg", "original reader mode should preserve original mime type")
    assert_true(len(low_bytes) < len(raw_bytes), "low-quality reader output should be smaller than original")
    assert_true(original_bytes == raw_bytes, "original reader mode should keep source bytes unchanged")
    assert_true(_normalize_reader_quality_mode("weird") == "high", "unknown reader quality should fall back to high")

    print("[3] Reader session status exposes preload progress")
    session = {
        "session_id": "phase64",
        "arcid": "phase64-arcid",
        "title": "Phase 6.4",
        "page_count": 20,
        "cursor": 5,
        "ahead": 4,
        "cache": {
            4: {"data": b"a", "ctype": "image/jpeg", "last_access": 1.0},
            5: {"data": b"b", "ctype": "image/jpeg", "last_access": 1.0},
            6: {"data": b"c", "ctype": "image/jpeg", "last_access": 1.0},
        },
        "fetching": {7},
        "status": "running",
        "error": "",
        "created_at": 1.0,
        "last_touch": 2.0,
    }
    view = _reader_session_view(session)
    assert_true(int(view.get("preload_target_count") or 0) >= 5, "preload target set should include cursor window")
    assert_true(int(view.get("preload_cached_count") or 0) == 3, "cached target count mismatch")
    assert_true(int(view.get("fetching_count") or 0) == 1, "fetching count mismatch")
    assert_true(0 < int(view.get("preload_percent") or 0) < 100, "preload percent should be between 0 and 100")

    print("[OK] Phase 6.4 reader/media regression passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        raise
