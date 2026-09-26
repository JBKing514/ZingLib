// Reader input shortcuts: keyboard and mouse wheel.
//
// Every mapping decision lives here as a pure function so it can be tested
// without a DOM, and `bindReaderShortcuts` is the only thing that touches the
// window. The reader passes its own `next`/`prev` callbacks in; this module
// never imports the reader.

/** Parse "a,d" / "A D" / "" into a lower-cased, de-duplicated key list. */
export function parseTurnKeys(raw) {
  return String(raw || "")
    .split(/[\s,，、;；|/]+/)
    .map((k) => k.trim().toLowerCase())
    .filter(Boolean);
}

/**
 * Which way a key turns the page.
 *
 * Returns "next" | "prev" | "" (not a turn key). Deliberately avoids "did the
 * user press an arrow key" special-casing: only the configured bindings turn
 * pages, so an unconfigured key does nothing rather than guessing.
 */
export function resolveKeyAction(event, { nextKeys = [], prevKeys = [] } = {}) {
  const key = String(event?.key || "").toLowerCase();
  if (!key) return "";
  // Never hijack a modified keystroke: Ctrl/Cmd/Alt combos belong to the
  // browser and the OS (reload, close tab, zoom), and stealing them breaks the
  // user's expectations far worse than a missing page turn.
  if (event?.ctrlKey || event?.metaKey || event?.altKey) return "";
  if (nextKeys.includes(key)) return "next";
  if (prevKeys.includes(key)) return "prev";
  return "";
}

/**
 * Which way a wheel event turns the page.
 *
 * `natural` is the user-facing "natural scrolling" switch. It is a plain
 * inversion with no platform sniffing: the browser already reports the same
 * `deltaY` sign for the same physical gesture on every OS once its own natural
 * scrolling preference is applied, so turning that back into a page direction
 * only needs one bit the user controls.
 */
export function resolveWheelAction(deltaY, { natural = false } = {}) {
  const d = Number(deltaY || 0);
  if (!Number.isFinite(d) || d === 0) return "";
  const forward = d > 0;
  const turn = natural ? !forward : forward;
  return turn ? "next" : "prev";
}

/** True when another wheel notch may turn a page. */
export function canTurnFromWheel(lastTurnAt, now, minInterval = 150) {
  const previous = Number(lastTurnAt);
  const current = Number(now);
  const delay = Math.max(0, Number(minInterval) || 0);
  if (!Number.isFinite(current)) return false;
  if (!Number.isFinite(previous)) return true;
  return current - previous >= delay;
}

/**
 * Bind the reader's window-level inputs and return a disposer.
 *
 * Kept as one function so the reader has exactly one thing to call on mount and
 * one to call on unmount -- a leaked listener here would page a gallery after
 * the user left it.
 */
export function bindReaderShortcuts({
  onNext,
  onPrev,
  nextKeys = [],
  prevKeys = [],
  wheelEnabled = true,
  wheelNatural = false,
  isEditableTarget = defaultIsEditableTarget,
  wheelMinInterval = 150,
  now = () => Date.now(),
} = {}) {
  if (typeof window === "undefined") return () => {};
  let lastWheelTurnAt = Number.NEGATIVE_INFINITY;

  const onKeyDown = (event) => {
    // Typing in a field must never turn a page.
    if (isEditableTarget(event?.target)) return;
    const action = resolveKeyAction(event, { nextKeys, prevKeys });
    if (!action) return;
    event.preventDefault?.();
    if (action === "next") onNext?.();
    else onPrev?.();
  };

  const onWheel = (event) => {
    if (!wheelEnabled) return;
    if (isEditableTarget(event?.target)) return;
    const action = resolveWheelAction(event?.deltaY, { natural: wheelNatural });
    if (!action) return;
    event.preventDefault?.();
    const at = Number(now());
    if (!canTurnFromWheel(lastWheelTurnAt, at, wheelMinInterval)) return;
    lastWheelTurnAt = at;
    if (action === "next") onNext?.();
    else onPrev?.();
  };

  window.addEventListener("keydown", onKeyDown);
  // `passive: false` because paging calls preventDefault; a passive listener
  // would let the page scroll *and* turn, which is the bug this avoids.
  window.addEventListener("wheel", onWheel, { passive: false });

  return () => {
    window.removeEventListener("keydown", onKeyDown);
    window.removeEventListener("wheel", onWheel, { passive: false });
  };
}

/** True for inputs a keystroke belongs to. */
export function defaultIsEditableTarget(target) {
  const el = target;
  if (!el || typeof el !== "object") return false;
  const tag = String(el.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable === true) return true;
  return false;
}
