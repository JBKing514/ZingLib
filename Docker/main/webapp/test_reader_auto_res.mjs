import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cappedDpr, readerResParam, screenResolution } from "./src/utils/readerRes.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("the DPR cap keeps 3x screens at a 2x ceiling", () => {
  assert.equal(cappedDpr(3), 2);
  assert.equal(cappedDpr(1.5), 1.5);
  assert.equal(cappedDpr(0), 1);
  assert.equal(cappedDpr(Number.NaN), 1);
});

test("screenResolution reads physical pixels from the screen object", () => {
  assert.deepEqual(screenResolution({ screen: { width: 1920, height: 1080 }, devicePixelRatio: 1 }), { width: 1920, height: 1080 });
  // A 3x phone asks for the same ceiling as a 2x one: the reader never draws
  // more than 2x CSS pixels, so shipping more only spends bytes.
  assert.deepEqual(screenResolution({ screen: { width: 390, height: 844 }, devicePixelRatio: 3 }), { width: 780, height: 1688 });
  // No window / no screen / degenerate sizes degrade to null, never to a guess.
  assert.equal(screenResolution(null), null);
  assert.equal(screenResolution({ devicePixelRatio: 2 }), null);
  assert.equal(screenResolution({ screen: { width: 0, height: 0 }, devicePixelRatio: 2 }), null);
});

test("the res hint rides along only in auto mode", () => {
  assert.equal(readerResParam("auto", { width: 2560, height: 1440 }), "2560x1440");
  assert.equal(readerResParam("AUTO", { width: 1920, height: 1080 }), "1920x1080");
  // Manual tiers keep byte-stable URLs: no hint is ever attached to them.
  assert.equal(readerResParam("high", { width: 2560, height: 1440 }), "");
  assert.equal(readerResParam("original", { width: 2560, height: 1440 }), "");
  assert.equal(readerResParam("", { width: 2560, height: 1440 }), "");
  // No usable screen (SSR, sandbox) or a degenerate one degrades to no hint,
  // which the server treats as a pass-through -- never as a surprise tier.
  assert.equal(readerResParam("auto", null), "");
  assert.equal(readerResParam("auto", { width: 12, height: 10 }), "");
});

test("the reader URL carries the res hint in auto mode and nothing otherwise", () => {
  const page = read("./src/views/ReaderPage.vue");
  assert.match(page, /import \{ readerResParam \} from "\.\.\/utils\/readerRes";/);
  assert.match(page, /const mode = encodeURIComponent\(String\(readerImageQualityMode\.value \|\| "auto"\)/);
  assert.match(page, /const res = readerResParam\(readerImageQualityMode\.value\);/);
  assert.match(page, /const resQuery = res \? `&res=\$\{encodeURIComponent\(res\)\}` : "";/);
  // Both URL shapes (session and direct) append the hint after the mode.
  assert.match(page, /page\/\$\{Number\(page \|\| 1\)\}\?mode=\$\{mode\}\$\{resQuery\}/);
  assert.match(page, /page\/\$\{page\}\?mode=\$\{mode\}\$\{resQuery\}/);
});

test("auto is the default tier and validates against the known set", () => {
  const store = read("./src/stores/settingsStore.js");
  assert.match(store, /if \(!config\.value\.READER_IMAGE_QUALITY_MODE\) config\.value\.READER_IMAGE_QUALITY_MODE = "auto";/);
  assert.match(store, /\["auto", "low", "mid", "high", "original"\]\.includes\(mode\) \? mode : "auto"/);
});

test("paged reading keeps the ordinary image rendering path", () => {
  const page = read("./src/views/ReaderPage.vue");
  assert.match(page, /:src="pageRenderUrl\(spreadLeftPage\)"/);
  assert.match(page, /:src="pageRenderUrl\(spreadRightPage\)"/);
  // The keyed transition is what makes a page turn an out-in animation again.
  assert.match(page, /<transition :name="pageTransitionName" mode="out-in">/);
  assert.match(page, /:key="`p-\$\{currentPage\}-\$\{spreadDouble \? 'd' : 's'\}`"/);
});

test("the server-side contract: auto is a mode, downsampling only above the hint", () => {
  const router = read("../webapi/routers/reader.py");
  // `auto` must stay a mode instead of collapsing to a fixed tier: the reader
  // chose it to keep pages that fit the screen intact.
  assert.match(router, /return text if text in \{"thumb", "low", "mid", "high", "original", "auto"\} else "high"/);
  assert.match(router, /def _reader_auto_res_bytes\(data: bytes, ctype: str, res: tuple\[int, int\] \| None\)/);
  // Only shrink: a page that fits keeps its original bytes, on both exits.
  assert.match(router, /if img\.width <= res\[0\] and img\.height <= res\[1\]:\s*\n\s*return data, ctype/);
  assert.match(router, /if res is None:\s*\n\s*return data, ctype/);
  // Contain-fit: the smaller scale wins, so a portrait page fits by height.
  assert.match(router, /scale = min\(res\[0\] \/ img\.width, res\[1\] \/ img\.height\)/);
  assert.match(router, /resample=resampling\.LANCZOS/);
  // Both page endpoints accept the hint.
  assert.match(router, /async def reader_session_page\(session_id: str, index: int, mode: str = Query\(default=""\), res: str = Query\(default=""\)\)/);
  assert.match(router, /async def reader_page\(arcid: str, index: int, mode: str = Query\(default=""\), res: str = Query\(default=""\)\)/);
  // The low tier is back to its 360px HEAD value.
  assert.match(router, /"low": \(360, 60\),/);
  // Producing parameters are part of the cache key: the dev container once
  // kept serving 480px `low` derivatives after the tier was reverted to 360,
  // because the old files still matched the bare source hash.
  assert.match(router, /cache_path = cache_dir \/ f"\{cache_key\}_\{max_edge\}_\{quality\}\.webp"/);
  assert.match(router, /cache_path = cache_dir \/ f"\{cache_key\}_\{res\[0\]\}x\{res\[1\]\}_q\{_AUTO_RES_WEBP_QUALITY\}\.webp"/);
});
