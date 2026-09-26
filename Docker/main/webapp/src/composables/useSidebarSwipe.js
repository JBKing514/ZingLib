import { onBeforeUnmount, onMounted } from "vue";

/**
 * One gesture for the whole shell: pull the sidebar out from the screen edge,
 * push it away to put it back.
 *
 * It lives here rather than inside the dashboard because the toolbox, the XP map
 * and the settings pages are the same shell -- the reader (which hides the app
 * chrome) is the only place that opts out. The dashboard's own library/favorites/
 * history swipes are gone: that switch belongs to the rail, so a horizontal drag
 * on a feed has nothing left to mean but the sidebar.
 */

// Keep the opening gesture clear of Android's own edge-back zone. A third of
// the viewport is broad enough to start deliberately from page content.
export const SIDEBAR_SWIPE_EDGE_RATIO = 1 / 3;
export const SIDEBAR_SWIPE_EDGE_FALLBACK = 160;
export function sidebarSwipeEdge(viewportWidth) {
  const width = Number(viewportWidth);
  return Number.isFinite(width) && width > 0
    ? width * SIDEBAR_SWIPE_EDGE_RATIO
    : SIDEBAR_SWIPE_EDGE_FALLBACK;
}
// A quarter of a phone's width: past the jitter of a scroll, short of a drag.
export const SIDEBAR_SWIPE_TRAVEL = 56;
// The drag has to be this much more horizontal than vertical to count.
export const SIDEBAR_SWIPE_BIAS = 1.2;

/**
 * The page zoom factor the app renders at (`#app { zoom: var(--zgl-page-zoom) }`).
 *
 * CSS `zoom` shrinks the *layout* viewport while `window.innerWidth` keeps
 * reporting the unzoomed width, and a `clientX` read from a pointer inside the
 * zoomed subtree is reported in that zoomed space. Both halves of the gesture
 * decision are therefore in different units at any zoom but 100%:
 *
 *   * the edge zone is `innerWidth * 1/3` -- unzoomed CSS px;
 *   * `dx` / `startX` are visual px, which are `1 / zoom` times as many CSS px.
 *
 * At 90% a third of the screen was no longer a third, and the 56px travel
 * threshold silently became 50px, which is how "the swipe stops working when I
 * zoom out" reads. Normalising the pointer numbers back into CSS px puts both
 * sides in the same unit again.
 */
export const SIDEBAR_SWIPE_ZOOM_VAR = "--zgl-page-zoom";

/** Read the current zoom factor from the document, defaulting to 1. */
export function readPageZoom(doc = (typeof document !== "undefined" ? document : null)) {
  if (!doc || typeof doc.defaultView?.getComputedStyle !== "function") return 1;
  const raw = doc.defaultView.getComputedStyle(doc.documentElement).getPropertyValue(SIDEBAR_SWIPE_ZOOM_VAR);
  const n = Number(String(raw).trim());
  // A missing / malformed value means "no zoom" rather than "zoom to zero" --
  // dividing by it would otherwise make every drag infinite.
  return Number.isFinite(n) && n > 0 ? n : 1;
}

/** Convert a zoomed pointer coordinate back into the layout's CSS pixels. */
export function unzoomPointer(value, zoom) {
  const n = Number(value);
  const z = Number(zoom);
  if (!Number.isFinite(n)) return 0;
  return Number.isFinite(z) && z > 0 ? n / z : n;
}

// A horizontal drag that starts on a gallery belongs to that gallery (the
// long-press row picker scrubs through its row), never to the shell.
const CARD_SELECTOR = ".home-card, .preview-card, .tag-explore-item-card";

// Panels that own their own pointers. A dialog or a full-screen overlay is not
// "the page", so a swipe inside one must not move the drawer underneath it.
const BLOCKED_SELECTOR = [
  ".v-overlay-container",
  ".tag-explore-host",
  ".longpress-picker-host",
  ".longpress-picker-backdrop",
  ".mobile-preview-fullscreen",
  "input",
  "textarea",
  "select",
  '[contenteditable="true"]',
].join(", ");

/**
 * The whole decision, with no DOM in it, so the rules above can be tested
 * directly. Returns "", "open" or "close".
 *
 * `startX` / `dx` must already be in the document's CSS pixels (see
 * `unzoomPointer`); `viewportWidth` is `window.innerWidth`, which is already in
 * that unit.
 *
 * `longPressActive` means "a gallery long-press owns the pointer right now".
 * It covers both the arming window (finger down, 430ms timer running) and the
 * open picker, because in both states the same horizontal drag is the gallery's
 * scrub control rather than the shell's drawer pull. Keying it only to "picker
 * open" was not enough: the drag that *opens* the picker is tracked from
 * `pointerdown`, so at a zoom level that widens the edge zone the shell would
 * fire "open" out from under the user's finger and the two gestures fought.
 */
export function resolveSidebarSwipe(input = {}) {
  if (!input.enabled || input.blocked) return "";
  // The dashboard's long-press picker owns the pointer for as long as it is on
  // screen: it is scrubbed by the same horizontal drag the shell would read as
  // "pull the sidebar out". Its backdrop only covers the page *after* the picker
  // opens, so the drag that opened it -- and every drag on it -- would otherwise
  // be stolen mid-gesture. One flag, checked before any distance rule.
  if (input.longPressActive) return "";
  const dx = Number(input.dx || 0);
  const dy = Number(input.dy || 0);
  if (!Number.isFinite(dx) || !Number.isFinite(dy)) return "";
  if (Math.abs(dx) < SIDEBAR_SWIPE_TRAVEL) return "";
  if (Math.abs(dx) < Math.abs(dy) * SIDEBAR_SWIPE_BIAS) return "";

  if (dx > 0) {
    // Rightward: pull it out. Already open at full width means there is nothing
    // to pull out, and the gesture must not start on a card or mid-page.
    if (input.drawerOpen && !input.railOn) return "";
    if (Number(input.startX || 0) > sidebarSwipeEdge(input.viewportWidth)) return "";
    return "open";
  }

  // Leftward: push it away. With the drawer showing, this is a drag off the
  // drawer itself -- or from anywhere, when the drawer is an overlay whose scrim
  // already covers the page.
  if (!input.drawerOpen) return "";
  if (!input.overlay && Number(input.startX || 0) > Number(input.drawerRight || 0) + 12) return "";
  return "close";
}

function closestOf(target, selector) {
  return !!target && typeof target.closest === "function" && !!target.closest(selector);
}

/**
 * Wire the gesture to the window. `drawer` and `rail` are refs onto the layout
 * store; `enabled` says whether the shell is even mounted (the reader and the
 * recovery screen render no sidebar, so the gesture has nothing to move);
 * `longPressActive` is a ref that a page raises while one of its own
 * long-press pickers owns the pointer.
 */
export function useSidebarSwipe({ drawer, rail, enabled, longPressActive }) {
  let tracking = false;
  let pointerId = -1;
  let startX = 0;
  let startY = 0;
  let startEl = null;
  // The zoom in force when the gesture began. Read once, at pointerdown: the
  // whole drag has to be measured in one unit, and re-reading mid-gesture could
  // rescale the thresholds under the user's finger.
  let gestureZoom = 1;

  function sidebarEl() {
    return typeof document !== "undefined" ? document.querySelector(".app-sidebar-drawer") : null;
  }

  function canTrack() {
    return enabled ? !!enabled.value : true;
  }

  function onPointerDown(event) {
    tracking = false;
    if (!canTrack()) return;
    if (longPressActive && longPressActive.value) return;
    if (event?.isPrimary === false || !["touch", "pen"].includes(String(event?.pointerType || ""))) return;
    const target = event?.target || null;
    if (closestOf(target, BLOCKED_SELECTOR)) return;
    const downZoom = readPageZoom();
    const downX = unzoomPointer(event?.clientX, downZoom);
    // A touch that lands on a gallery card belongs to that card from the first
    // event. The card is already arming its 430ms long-press and the drag that
    // follows is the picker's scrub. Letting the shell keep the same pointer in
    // the edge zone creates a race: it can open the drawer before the picker has
    // had time to publish its active flag, especially under CSS zoom.
    const onCard = closestOf(target, CARD_SELECTOR);
    if (onCard) return;
    pointerId = Number(event?.pointerId ?? -1);
    gestureZoom = downZoom;
    startX = downX;
    startY = unzoomPointer(event?.clientY, downZoom);
    startEl = target;
    tracking = true;
  }

  function onPointerMove(event) {
    if (!tracking || Number(event?.pointerId ?? -1) !== pointerId) return;
    if (!canTrack()) return;

    const root = sidebarEl();
    const rect = root && typeof root.getBoundingClientRect === "function" ? root.getBoundingClientRect() : null;
    // The scrim is what makes the drawer an overlay: Vuetify renders it only for
    // a temporary drawer, i.e. one that dims and covers the page underneath.
    const overlay = !!root && !!root.querySelector(".v-navigation-drawer__scrim");

    const action = resolveSidebarSwipe({
      enabled: true,
      blocked: false,
      longPressActive: !!(longPressActive && longPressActive.value),
      dx: unzoomPointer(event?.clientX, gestureZoom) - startX,
      dy: unzoomPointer(event?.clientY, gestureZoom) - startY,
      startX,
      viewportWidth: Number(window.innerWidth || 0),
      drawerOpen: drawer ? !!drawer.value : false,
      railOn: rail ? !!rail.value : false,
      overlay,
      drawerRight: rect ? Number(rect.right || 0) : 0,
      onCard: closestOf(startEl, CARD_SELECTOR),
    });

    if (action === "open") {
      tracking = false;
      if (drawer) drawer.value = true;
      // A deliberate pull means the full sidebar, not the compact rail.
      if (rail && rail.value) rail.value = false;
      return;
    }
    if (action === "close" && drawer) {
      tracking = false;
      drawer.value = false;
    }
  }

  function onPointerEnd(event) {
    if (Number(event?.pointerId ?? -1) !== pointerId) return;
    tracking = false;
    pointerId = -1;
  }

  onMounted(() => {
    window.addEventListener("pointerdown", onPointerDown, { passive: true });
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerup", onPointerEnd, { passive: true });
    window.addEventListener("pointercancel", onPointerEnd, { passive: true });
  });

  onBeforeUnmount(() => {
    window.removeEventListener("pointerdown", onPointerDown);
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerEnd);
    window.removeEventListener("pointercancel", onPointerEnd);
  });
}
