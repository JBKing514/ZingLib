// v1.0.3: the nav wheel must not be able to starve the page it is navigating to.
//
// Three separate faults stacked into the same symptom ("jump far and the page
// takes forever"):
//   1. the thumbnails were built from `pageImageUrl`, i.e. a full read-quality
//      transform per thumbnail;
//   2. `wheelPages` re-rendered on every slider tick, so a flick through 30 pages
//      created ~30 <img> requests for pages the user never stopped on;
//   3. on the server all of those ran through the reader session's page cache,
//      which both moved the session cursor and evicted the full-size neighbours
//      the session had already preloaded.
//
// Each layer is pinned separately, because a fix to one of them alone still
// leaves the others.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("the wheel asks for its own cheap mode, not the reader's quality", () => {
  const page = read("./src/views/ReaderPage.vue");
  // The original bug, verbatim: the thumbnail url *was* the page url.
  assert.doesNotMatch(page, /function pageThumbUrl\(page\) \{\s*return pageImageUrl\(page\);/);
  assert.match(page, /const WHEEL_THUMB_MODE = "thumb";/);
  assert.match(page, /function wheelThumbUrl\(page\) \{[\s\S]*?mode=\$\{WHEEL_THUMB_MODE\}/);
  // Both the session route and the no-session fallback have to carry it, or the
  // wheel silently goes back to full-size images on one of the two paths.
  assert.equal((page.match(/\?mode=\$\{WHEEL_THUMB_MODE\}/g) || []).length, 2);
  assert.match(page, /function pageThumbUrl\(page\) \{\s*return wheelThumbUrl\(page\);/);
  // `thumb` must not be one of the reading modes -- the reader's own ladder is
  // unchanged, so switching quality still affects the page and nothing else.
  assert.match(page, /READER_IMAGE_QUALITY_MODE/);
});

test("a drag settles normally but recenters before it outruns the strip", () => {
  const page = read("./src/views/ReaderPage.vue");
  // The slider cursor and the strip cursor are two things now.
  assert.match(page, /const wheelStripPage = ref\(1\);/);
  assert.match(page, /const WHEEL_STRIP_SETTLE_MS = 150;/);
  assert.match(page, /function onWheelPreviewPage\(page\) \{[\s\S]*?wheelCursorPage\.value = clamped;[\s\S]*?armWheelStripSettle\(\);/);
  assert.match(page, /const recenterGap = Math\.max\(1, Number\(wheelRange\.value \|\| 4\) - 1\);/);
  assert.match(page, /Math\.abs\(clamped - Number\(wheelStripPage\.value \|\| 1\)\) >= recenterGap/);
  assert.match(page, /wheelStripPage\.value = clamped;/);
  assert.match(page, /wheelStripPage\.value = wheelCursorPage\.value;/);
  // And the strip is built from the settled cursor, not the live one.
  assert.match(page, /const center = Math\.max\(1, Math\.min\([\s\S]{0,160}?Number\(wheelStripPage\.value/);
  // The timer has to die with the view.
  assert.match(page, /clearWheelStripSettle\(\);/);
  assert.match(page, /function clearWheelStripSettle\(\) \{[\s\S]*?window\.clearTimeout\(wheelStripSettleTimer\);/);
});

test("global wheel paging stands down while the thumbnail wheel is visible", () => {
  const page = read("./src/views/ReaderPage.vue");
  assert.match(page, /wheelEnabled: wheelPagingEnabled\.value && !showUi\.value/);
  assert.match(page, /\[shortcutKeys, wheelPagingEnabled, wheelNatural, showUi\]/);
});

test("unloaded wheel thumbnails keep their own placeholder and optional haptics", () => {
  const page = read("./src/views/ReaderPage.vue");
  const wheel = read("./src/components/reader/ReaderNavWheel.vue");
  assert.doesNotMatch(page, /:fast-scrolling=/);
  assert.match(wheel, /class="wheel-thumb-placeholder"/);
  assert.doesNotMatch(wheel, /wheel-track\.is-seeking/);
  assert.match(wheel, /typeof navigator\.vibrate === "function"/);
  assert.match(wheel, /navigator\.vibrate\(8\)/);
  assert.match(wheel, /function emitPreviewPage\(page\)/);
});

test("thumb preloading is bounded to the strip on screen", () => {
  const page = read("./src/views/ReaderPage.vue");
  // It used to walk page 1..last_page -- one read-quality request per page of the
  // book, queued ahead of the page the reader was waiting for.
  assert.doesNotMatch(page, /for \(let p = 1; p <= max; p \+= 1\)/);
  assert.match(page, /const start = Math\.max\(1, center - range\);\s*const end = Math\.min\(max, center \+ range\);\s*for \(let p = start; p <= end; p \+= 1\)/);
  // Moving the strip re-runs it, which is also what drops the old strip's loads.
  assert.match(page, /watch\(wheelStripPage, \(\) => \{[\s\S]*?preloadWheelStripThumbs\(\);/);
  assert.match(page, /function resetWheelThumbPreload\(\) \{[\s\S]*?img\.src = "";/);
});

test("a thumb request is read-only on the server", () => {
  const reader = read("../webapi/routers/reader.py");
  // Its own cache, so building thumbnails cannot evict the reader's pages.
  assert.match(reader, /_reader_wheel_thumb_cache: dict\[tuple\[str, int, str\], tuple\[bytes, str\]\] = \{\}/);
  assert.match(reader, /_reader_wheel_thumb_max = 256/);
  assert.match(reader, /async def _reader_wheel_thumb_bytes\(arcid: str, page_path: str, page_no: int\)/);
  // The mode itself has to exist, and stay out of the reading ladder. `auto`
  // joined the set with feat-16 (auto resolution) but is handled before the
  // ladder: it never reaches this spec table.
  assert.match(reader, /"thumb": \(200, 55\),/);
  assert.match(reader, /return text if text in \{"thumb", "low", "mid", "high", "original", "auto"\} else "high"/);
  // A thumb moves neither the cursor nor the session cache.
  assert.match(reader, /is_thumb = safe_mode == "thumb"/);
  assert.match(reader, /if not is_thumb:\s*session\["cursor"\] = _reader_page\(idx, total\)/);
  assert.match(reader, /if is_thumb:\s*#[^\n]*\n\s*#[^\n]*\n\s*thumb, thumb_type = await _reader_wheel_thumb_bytes/);
  // A re-uploaded gallery reuses its path-derived arcid, so the wheel cache has
  // to be dropped with the session caches.
  assert.match(reader, /_reader_wheel_thumb_cache\.clear\(\)/);
});

test("the wheel strip is the only consumer of the thumb mode", () => {
  const page = read("./src/views/ReaderPage.vue");
  // `pageRenderUrl` / `continuousRenderUrl` are the正文 and must keep the reader's
  // chosen quality -- a regression here would silently make the page blurry.
  assert.match(page, /function pageRenderUrl\(page\) \{\s*return withNonce\(pageImageUrl\(page\)/);
  assert.match(page, /function continuousRenderUrl\(page\) \{\s*return withNonce\(pageImageUrl\(page\)/);
  assert.match(page, /const mode = encodeURIComponent\(String\(readerImageQualityMode\.value \|\| "auto"\)/);
});
