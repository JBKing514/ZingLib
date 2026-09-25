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
 */
export function resolveSidebarSwipe(input = {}) {
  if (!input.enabled || input.blocked) return "";
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
 * recovery screen render no sidebar, so the gesture has nothing to move).
 */
export function useSidebarSwipe({ drawer, rail, enabled }) {
  let tracking = false;
  let pointerId = -1;
  let startX = 0;
  let startY = 0;
  let startEl = null;

  function sidebarEl() {
    return typeof document !== "undefined" ? document.querySelector(".app-sidebar-drawer") : null;
  }

  function canTrack() {
    return enabled ? !!enabled.value : true;
  }

  function onPointerDown(event) {
    tracking = false;
    if (!canTrack()) return;
    if (event?.isPrimary === false || !["touch", "pen"].includes(String(event?.pointerType || ""))) return;
    const target = event?.target || null;
    if (closestOf(target, BLOCKED_SELECTOR)) return;
    pointerId = Number(event?.pointerId ?? -1);
    startX = Number(event?.clientX || 0);
    startY = Number(event?.clientY || 0);
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
      dx: Number(event?.clientX || 0) - startX,
      dy: Number(event?.clientY || 0) - startY,
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
