/**
 * Dual-screen (Surface Duo) geometry and the decision whether to use it.
 *
 * Measured on a Duo 2 / Android 12 / Chrome 156, 2026-11-03:
 *
 *   served over http://<lan-ip>   (the normal deployment)
 *     navigator.userAgentData     undefined      -> no model, no client hints
 *     navigator.devicePosture     undefined
 *     screen / innerWidth         2754x1892 @ dpr 2.5, one continuous display
 *
 *   served over https:// or localhost (a secure context)
 *     userAgentData.getHighEntropyValues(['model']) -> "Surface Duo 2"
 *     devicePosture.type                            -> "continuous"
 *
 *   window.getWindowSegments()    absent in both
 *   env(viewport-segment-*)       0px in both
 *
 * Two consequences drive this module:
 *
 * 1. The hinge cannot be measured -- the OS presents one continuous surface and
 *    even a screenshot shows no seam -- so its width is a constant. 27 CSS px is
 *    the calibrated value: 33 looked right at a glance but left a few px of
 *    clearance on both sides, and 2754 - 2*1344 = 66 device px = 26.4 CSS px.
 * 2. Auto-detection can only use the model, and the model only exists in a
 *    secure context. The PWA itself requires HTTPS, so that is the normal case;
 *    a LAN deployment served over plain HTTP is the fallback one, and there the
 *    switch is the only way in -- so it is offered to any touch device with a
 *    wide viewport instead of being hidden. Posture plus a wide viewport was
 *    tried as an auto trigger first and is not enough: a tablet, a desktop
 *    window or a foldable at 90 degrees all match it. So auto turns on ONLY for
 *    a Surface Duo, and everything else is left to the explicit toggle.
 */

import { computed, reactive, readonly } from "vue";

/** Calibrated on a Duo 2: 33 left a few px of clearance on both sides. */
export const DEFAULT_HINGE_CSS = 27;

const STORAGE_KEY = "zinglib.duoMode";
const DEBUG_KEY = "zinglib.duoDebug";
const DUO_MODEL = /surface\s*duo/i;


/**
 * Two panels at ~537 CSS px each plus the hinge is ~1100; anything narrower is
 * a single screen and splitting it would eat a third of the viewport.
 *
 * It was dropped once during a rewrite and the reference below survived, which
 * `vite build` cannot catch: an undefined identifier is a runtime ReferenceError,
 * and because this runs in the shell's setup the whole app rendered blank after
 * login while the login page (outside the shell) still worked.
 */
const MIN_DUAL_WIDTH = 900;

const state = reactive({
  /** The layout is on. */
  active: false,
  /** The user can see the toggle: a Duo was recognised, or they forced it on. */
  available: false,
  /** "auto" | "on" | "off" -- the stored preference. */
  mode: "auto",
  /** Why the result is what it is; shown by the calibration marker. */
  reason: "",
  /** "Surface Duo 2" when the browser exposed it, else "". */
  model: "",
  posture: "",
  secure: true,
  /** Debug mode: force the layout on and show the geometry readout. */
  debug: false,
  gap: DEFAULT_HINGE_CSS,
  leftWidth: 0,
  rightWidth: 0,
  viewport: 0,
  /** False when the numbers came from the constant instead of an API. */
  measured: false,
});

let started = false;
let modelLookup = null;

function readMode() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw === "on" || raw === "off" ? raw : "auto";
  } catch (_e) {
    return "auto";
  }
}

function writeMode(mode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch (_e) {
    /* private mode / disabled storage: the preference simply does not persist */
  }
}

function readDebug() {
  try {
    return localStorage.getItem(DEBUG_KEY) === "1";
  } catch (_e) {
    return false;
  }
}

/**
 * Turn the debug overlay on, and make the address say so.
 *
 * The readout is driven by `?duo=1`, which is also what forces the layout on, so
 * the switch writes that parameter into the address rather than inventing a
 * second path through the code. `replaceState` keeps it out of the history.
 */
export function setDualScreenDebug(on) {
  state.debug = Boolean(on);
  try {
    if (state.debug) localStorage.setItem(DEBUG_KEY, "1");
    else localStorage.removeItem(DEBUG_KEY);
  } catch (_e) {
    /* storage refused; the flag still applies for this page */
  }
  if (typeof window !== "undefined" && window.history && window.history.replaceState) {
    try {
      const url = new URL(window.location.href);
      if (state.debug) url.searchParams.set("duo", "1");
      else url.searchParams.delete("duo");
      window.history.replaceState(null, "", url.toString());
    } catch (_e) {
      /* a malformed address is not worth breaking the toggle over */
    }
  }
  apply();
}

export function setDualScreenMode(mode) {
  state.mode = mode === "on" || mode === "off" ? mode : "auto";
  writeMode(state.mode);
  apply();
}

function readSegments() {
  if (typeof window === "undefined" || typeof window.getWindowSegments !== "function") return [];
  try {
    const rects = window.getWindowSegments();
    return rects ? Array.prototype.slice.call(rects) : [];
  } catch (_e) {
    return [];
  }
}

function queryFlag(name) {
  if (typeof window === "undefined") return false;
  try {
    return new URLSearchParams(window.location.search).get(name) === "1";
  } catch (_e) {
    return false;
  }
}

function hingeOverride() {
  if (typeof window === "undefined") return null;
  try {
    const raw = new URLSearchParams(window.location.search).get("duo_hinge");
    // `Number(null)` is 0, which would read as "no hinge" and collapse the
    // split; an absent parameter has to be distinguishable from an explicit 0.
    if (raw === null || raw.trim() === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) && value >= 0 && value <= 120 ? value : null;
  } catch (_e) {
    return null;
  }
}

/** Cached: the high-entropy lookup is async and only needs to happen once. */
function detectModel() {
  if (modelLookup) return modelLookup;
  modelLookup = (async () => {
    const data = navigator.userAgentData;
    if (!data || typeof data.getHighEntropyValues !== "function") return "";
    try {
      const values = await data.getHighEntropyValues(["model"]);
      return String(values.model || "");
    } catch (_e) {
      return "";
    }
  })();
  return modelLookup;
}

function apply() {
  if (typeof window === "undefined") return;

  const segments = readSegments();
  const viewport = window.innerWidth || 0;
  const posture = navigator.devicePosture ? String(navigator.devicePosture.type || "") : "";
  const secure = window.isSecureContext !== false;
  const touch = Number(navigator.maxTouchPoints || 0) > 0;
  const forced = queryFlag("duo") || state.debug;
  const override = hingeOverride();

  const isDuo = DUO_MODEL.test(state.model);

  // A folded device is a laptop or a phone -- not two panels side by side.
  const folded = posture === "folded";

  let active = false;
  let reason = "";
  // A window narrower than two panels cannot be split, whatever the preference
  // says: the "on" switch is a decision about how to use a dual screen, not a
  // licence to squeeze the layout into one. Seen on the device when the browser
  // dropped out of spanning -- the header collapsed into a strip.
  const tooNarrow = viewport > 0 && viewport < MIN_DUAL_WIDTH;

  if (forced) {
    active = true;
    reason = "dev-query";
  } else if (tooNarrow) {
    reason = "too-narrow";
  } else if (state.mode === "off") {
    reason = "user-off";
  } else if (state.mode === "on") {
    active = !folded;
    reason = folded ? "user-on-but-folded" : "user-on";
  } else if (isDuo) {
    active = !folded;
    reason = folded ? "duo-but-folded" : "duo-model";
  } else if (!state.model) {
    reason = secure ? "no-model" : "insecure-context";
  } else {
    reason = "not-a-duo";
  }

  let gap = override === null ? DEFAULT_HINGE_CSS : override;
  let leftWidth = 0;
  let rightWidth = 0;
  let measured = false;

  if (segments.length >= 2) {
    // If a future Chrome restores segment enumeration, that wins outright and
    // the constant stops being used without touching the layout.
    gap = Math.max(0, Math.round(segments[1].left - segments[0].right));
    leftWidth = Math.round(segments[0].width);
    rightWidth = Math.round(segments[1].width);
    measured = true;
  } else if (active) {
    const content = Math.max(0, viewport - gap);
    leftWidth = Math.floor(content / 2);
    rightWidth = viewport - leftWidth - gap;
  }

  Object.assign(state, {
    active,
    // Graceful degradation: auto-detection needs a secure context (the PWA
    // itself requires HTTPS, but a LAN deployment over plain HTTP is exactly the
    // case where the model is unavailable). There, offer the switch to anything
    // that could plausibly be two panels -- touch plus a wide viewport -- rather
    // than hiding the only way in. Desktop mice and phones stay clean.
    available:
      forced
      || state.mode === "on"
      || state.mode === "off"
      || isDuo
      || (touch && viewport >= 900),
    reason,
    posture,
    secure,
    gap,
    leftWidth,
    rightWidth,
    viewport,
    measured,
  });

  const root = document.documentElement;
  root.classList.toggle("duo-active", active);
  root.classList.toggle("duo-spanned", measured);
  if (active) {
    root.style.setProperty("--duo-hinge", `${gap}px`);
    root.style.setProperty("--duo-left-width", `${leftWidth}px`);
    root.style.setProperty("--duo-right-width", `${rightWidth}px`);
  } else {
    root.style.removeProperty("--duo-hinge");
    root.style.removeProperty("--duo-left-width");
    root.style.removeProperty("--duo-right-width");
  }
}

export function useDualScreen() {
  if (!started && typeof window !== "undefined") {
    started = true;
    state.mode = readMode();
    state.debug = readDebug();
    apply();

    window.addEventListener("resize", apply);
    window.addEventListener("orientationchange", apply);
    if (navigator.devicePosture && typeof navigator.devicePosture.addEventListener === "function") {
      navigator.devicePosture.addEventListener("change", apply);
    }

    // The model arrives asynchronously; re-run once it does so a device that is
    // genuinely a Duo does not need a reload to be recognised.
    detectModel().then((model) => {
      state.model = model;
      apply();
    });
    setTimeout(apply, 1200);
  }

  return {
    state: readonly(state),
    isActive: computed(() => state.active),
    isAvailable: computed(() => state.available),
    hingeGap: computed(() => state.gap),
    leftWidth: computed(() => state.leftWidth),
    rightWidth: computed(() => state.rightWidth),
    isMeasured: computed(() => state.measured),
    setMode: setDualScreenMode,
    setDebug: setDualScreenDebug,
    refresh: apply,
  };
}
