/**
 * Where each library feed was last scrolled to.
 *
 * The dashboard's feeds live under `<KeepAlive>` and their rows survive a trip to
 * the toolbox or the settings page -- but the *scroll offset* does not, because
 * the whole app shares one window scroller: the shorter page the user navigates
 * to clamps the offset, and coming back leaves them at the top.
 *
 * Module scope, not component data, for two reasons: the value has to outlive the
 * component (a remount must not forget it), and a plain module is directly
 * testable without mounting anything.
 */

const positions = new Map();

function normalizeKey(key) {
  return String(key ?? "").trim();
}

export function readFeedScroll(key) {
  const k = normalizeKey(key);
  if (!k) return 0;
  const y = Number(positions.get(k) || 0);
  return Number.isFinite(y) && y > 0 ? y : 0;
}

export function writeFeedScroll(key, y) {
  const k = normalizeKey(key);
  if (!k) return 0;
  const top = Math.max(0, Math.round(Number(y) || 0));
  // Forgetting is the caller's job (see forgetFeedScroll): a feed that scrolls
  // back to the top legitimately stores 0.
  positions.set(k, top);
  return top;
}

export function forgetFeedScroll(key) {
  const k = normalizeKey(key);
  if (!k) return;
  positions.delete(k);
}

export function clearFeedScroll() {
  positions.clear();
}

/**
 * Does the offset remembered for a feed still describe what is on screen?
 *
 * Three outcomes, and the caller must not collapse them into a boolean:
 *
 *   "same"     -- the rows match the ones the offset was measured on; restore it.
 *   "stale"    -- the rows are a *different* set (a search, a filter, a folder);
 *                 the offset points into content that is gone. Forget it.
 *   "pending"  -- nothing is rendered yet, because the first load is still in
 *                 flight. The offset is still good; forgetting it here would
 *                 lose the position on every slow load, which is the exact case
 *                 scroll memory exists for.
 *
 * Compare row identities, not the length: "twelve rows" is not the same twelve,
 * and an equal-count replacement is the common case.
 */
export const FEED_SCROLL_SAME = "same";
export const FEED_SCROLL_STALE = "stale";
export const FEED_SCROLL_PENDING = "pending";

export function classifyFeedScrollRestore(savedIds, liveIds) {
  const a = Array.isArray(savedIds) ? savedIds : [];
  const b = Array.isArray(liveIds) ? liveIds : [];
  // Nothing remembered: there is no claim to check, and nothing to forget.
  if (!a.length) return FEED_SCROLL_PENDING;
  // Something remembered, nothing rendered yet -- the list has not arrived.
  if (!b.length) return FEED_SCROLL_PENDING;
  if (a.length !== b.length) return FEED_SCROLL_STALE;
  for (let i = 0; i < a.length; i += 1) {
    if (String(a[i] ?? "") !== String(b[i] ?? "")) return FEED_SCROLL_STALE;
  }
  return FEED_SCROLL_SAME;
}

/** Convenience for callers that only need "may I use this offset?". */
export function shouldRestoreFeedScroll(savedIds, liveIds) {
  return classifyFeedScrollRestore(savedIds, liveIds) !== FEED_SCROLL_STALE;
}
