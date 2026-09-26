// feat-16 "auto resolution": the reader's auto quality tier asks the server to
// Lanczos-downsample pages that are LARGER than the screen into a contain-fit
// of it. Pages that already fit are served as their original bytes, so auto can
// only save bandwidth and decode cost, never cost quality. The screen hint
// travels as `res=<W>x<H>` on the page URLs; manual tiers (low/mid/high/
// original) never send it, which keeps their URLs byte-stable and cache-friendly.

export const RES_DPR_CAP = 2;

export function cappedDpr(value) {
  const dpr = Number(value || 1);
  return Math.max(1, Math.min(RES_DPR_CAP, Number.isFinite(dpr) ? dpr : 1));
}

// The screen in physical pixels, DPR capped at 2: a 3x phone asks for the same
// ceiling as a 2x one, because the reader draws into a canvas of at most 2x
// CSS pixels and shipping more only spends bytes. Returns null when there is
// no usable screen (SSR, a test sandbox) -- callers degrade to no hint.
export function screenResolution(win = typeof window !== "undefined" ? window : null) {
  if (!win || !win.screen) return null;
  const dpr = cappedDpr(win.devicePixelRatio);
  const width = Math.round(Number(win.screen.width || 0) * dpr);
  const height = Math.round(Number(win.screen.height || 0) * dpr);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 100 || height < 100) return null;
  return { width, height };
}

// The `res` query value for the reader page endpoints: "WxH" in auto mode with
// a known screen, "" everywhere else. The server mirrors these bounds, so a
// hint that passes here is one it will honour.
export function readerResParam(mode, resolution = screenResolution()) {
  if (String(mode || "").trim().toLowerCase() !== "auto") return "";
  if (!resolution) return "";
  const width = Math.round(Number(resolution.width || 0));
  const height = Math.round(Number(resolution.height || 0));
  if (!Number.isFinite(width) || !Number.isFinite(height) || width < 100 || height < 100) return "";
  return `${width}x${height}`;
}
