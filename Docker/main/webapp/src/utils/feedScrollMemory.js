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
