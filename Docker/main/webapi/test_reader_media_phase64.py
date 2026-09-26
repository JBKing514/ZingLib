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
    from webapi.routers.reader import (
        _normalize_reader_quality_mode,
        _parse_reader_res,
        _reader_session_view,
        _reader_transform_image_bytes,
    )
except ImportError:
    sys.path.insert(0, "/app")
    from webapi.routers.media import _normalize_thumb_preset, _work_thumb_cache_file
    from webapi.routers.reader import (
        _normalize_reader_quality_mode,
        _parse_reader_res,
        _reader_session_view,
        _reader_transform_image_bytes,
    )


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_fixture_bytes(size: tuple[int, int] = (2000, 1500)) -> bytes:
    img = Image.new("RGB", size, (80, 140, 220))
    bio = io.BytesIO()
    img.save(bio, format="JPEG", quality=95)
    return bio.getvalue()


def build_animated_gif_bytes(size: tuple[int, int] = (1000, 800)) -> bytes:
    frames = [Image.new("RGB", size, (200, 40, 40)), Image.new("RGB", size, (40, 40, 200))]
    bio = io.BytesIO()
    frames[0].save(bio, format="GIF", save_all=True, append_images=frames[1:], duration=200, loop=0)
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
    with Image.open(io.BytesIO(low_bytes)) as low_image:
        assert_true(max(low_image.size) == 360, "low reader tier should be a 360px Lanczos derivative")
    assert_true(original_bytes == raw_bytes, "original reader mode should keep source bytes unchanged")
    assert_true(_normalize_reader_quality_mode("weird") == "high", "unknown reader quality should fall back to high")

    print("[2b] Auto resolution: downsample only above the screen hint")
    # `auto` must stay a mode: the client pairs it with a `res` hint, and the
    # server downsamples only pages larger than that hint.
    assert_true(_normalize_reader_quality_mode("auto") == "auto", "auto must stay a mode, not collapse to a fixed tier")
    assert_true(_parse_reader_res("1920x1080") == (1920, 1080), "a well-formed hint should parse")
    assert_true(_parse_reader_res("") is None, "no hint should parse to None")
    assert_true(_parse_reader_res("bogus") is None, "a malformed hint should parse to None")
    assert_true(_parse_reader_res("50x40") is None, "a sub-screen hint should be rejected as None")
    assert_true(_parse_reader_res("99999x99999") is None, "an absurd hint should be rejected as None")
    # The 2000x1500 fixture with no hint: byte-for-byte pass-through.
    auto_bytes, auto_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "auto")
    assert_true(auto_bytes == raw_bytes and auto_type == "image/jpeg", "auto without a hint must pass through unchanged")
    # Hint 1000x600: the page exceeds it, so it is Lanczos-downsampled to a
    # contain-fit (scale 0.4 -> 800x600; a fill would have been 1000x750).
    auto_hint_bytes, auto_hint_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "auto", "1000x600")
    assert_true(auto_hint_type == "image/webp", "auto with an exceeded hint should be a webp derivative")
    with Image.open(io.BytesIO(auto_hint_bytes)) as auto_image:
        assert_true(tuple(auto_image.size) == (800, 600), "auto should contain-fit the page into the screen hint (800x600)")
    assert_true(len(auto_hint_bytes) < len(raw_bytes), "auto derivative should be smaller than the source")
    # Hint the page already fits (4000x3000): original bytes, animation and all.
    auto_fit_bytes, auto_fit_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "auto", "4000x3000")
    assert_true(auto_fit_bytes == raw_bytes and auto_fit_type == "image/jpeg", "auto with a hint the page fits must keep the original bytes")
    # A malformed hint degrades to no hint, never to a surprise tier.
    auto_bogus_bytes, auto_bogus_type = _reader_transform_image_bytes(raw_bytes, "image/jpeg", "auto", "not-a-hint")
    assert_true(auto_bogus_bytes == raw_bytes and auto_bogus_type == "image/jpeg", "auto with a malformed hint must pass through unchanged")
    # An oversized animation is served as-is: resizing it would mean re-encoding
    # every frame, which this path does not attempt -- flattening it to the
    # first frame would destroy content, so it stays untouched even oversized.
    anim_bytes = build_animated_gif_bytes()
    anim_out, anim_type = _reader_transform_image_bytes(anim_bytes, "image/gif", "auto", "500x500")
    assert_true(anim_out == anim_bytes and anim_type == "image/gif", "an oversized animation must pass through untouched")

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
