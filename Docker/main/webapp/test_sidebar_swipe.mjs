// Round 54: the sidebar is opened and closed by one gesture, owned by the shell.
//
// The dashboard used to spend a horizontal drag on its own library/favorites/
// history switch. That switch lives in the rail now, so the axis was re-purposed:
// pull the drawer out from the screen edge, push it away to put it back -- on the
// feed, in the toolbox, on the XP map and in the settings alike.
//
// Two things have to hold, and they fail in different ways:
//   1. the decision itself (edge zone, travel, direction, who owns the pointer),
//      which is why it is a pure function with no DOM in it;
//   2. the wiring -- one owner, and no leftover tab swipe in the page that used
//      to have one.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import {
  resolveSidebarSwipe,
  sidebarSwipeEdge,
  SIDEBAR_SWIPE_EDGE_RATIO,
  SIDEBAR_SWIPE_TRAVEL,
  readPageZoom,
  unzoomPointer,
} from "./src/composables/useSidebarSwipe.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

// A plain rightward pull from the screen edge, with everything else neutral.
const pull = (extra = {}) => ({
  enabled: true,
  blocked: false,
  drawerOpen: false,
  railOn: false,
  overlay: false,
  drawerRight: 280,
  onCard: false,
  startX: 4,
  viewportWidth: 360,
  dx: 90,
  dy: 6,
  ...extra,
});

test("a pull from the first third of the viewport opens the drawer", () => {
  assert.equal(resolveSidebarSwipe(pull({ startX: 120 })), "open");
  // Exactly on the edge of the zone still counts; a pixel past it does not.
  assert.equal(resolveSidebarSwipe(pull({ startX: 121 })), "");
  assert.equal(sidebarSwipeEdge(360), 120);
  assert.equal(sidebarSwipeEdge(900), 300);
  assert.equal(SIDEBAR_SWIPE_EDGE_RATIO, 1 / 3);
  assert.ok(SIDEBAR_SWIPE_TRAVEL >= 40, `the travel threshold still rejects jitter (${SIDEBAR_SWIPE_TRAVEL}px)`);
});

test("a pull out of the rail asks for the full sidebar, not nothing", () => {
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, railOn: true })), "open");
  // Already open at full width: there is nothing to pull out.
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, railOn: false })), "");
});

test("the edge gesture also works where a dashboard card reaches the edge", () => {
  assert.equal(resolveSidebarSwipe(pull({ onCard: true })), "open");
  assert.equal(resolveSidebarSwipe(pull({ onCard: true, startX: 121 })), "");
});

test("a leftward drag pushes the drawer away when it is showing", () => {
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, dx: -90 })), "close");
  // Nothing to push when it is hidden.
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: false, dx: -90 })), "");
});

test("a push-style drawer is only pushed away from the drawer itself", () => {
  // No scrim: the page next to the drawer keeps its own leftward drags.
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, dx: -90, startX: 200 })), "close");
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, dx: -90, startX: 900 })), "");
  // With a scrim (a temporary drawer) the page underneath is not reachable, so
  // the whole screen belongs to the gesture.
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, dx: -90, startX: 900, overlay: true })), "close");
});

test("a scroll, a tap and a disabled shell are all left alone", () => {
  assert.equal(resolveSidebarSwipe(pull({ dy: 200 })), "", "vertical scroll");
  // Literals again: 40px is a jitter, 56px is a drag, and neither number may
  // follow the constant it is meant to pin.
  assert.equal(resolveSidebarSwipe(pull({ dx: 40 })), "", "too short");
  assert.equal(resolveSidebarSwipe(pull({ dx: 56 })), "open", "just long enough");
  assert.equal(resolveSidebarSwipe(pull({ dx: -90, drawerOpen: true, dy: 200 })), "", "vertical push");
  assert.equal(resolveSidebarSwipe(pull({ enabled: false })), "", "reader / recovery mode");
  assert.equal(resolveSidebarSwipe(pull({ blocked: true })), "", "inside an overlay");
  assert.equal(resolveSidebarSwipe({}), "", "no input at all");
});

test("the shell owns the gesture, and the dashboard owns none of it", () => {
  const layout = read("./src/layouts/MainLayout.vue");
  assert.match(layout, /useSidebarSwipe\(\{/);
  assert.match(layout, /drawer: toRef\(ui, "drawer"\)/);
  assert.match(layout, /const sidebarSwipeEnabled = computed\(\(\) => !appStore\.isRecoveryMode && !hideReaderChrome\.value\)/);

  const dash = read("./src/views/DashboardScopePage.vue");
  assert.doesNotMatch(dash, /v-touch/, "the tab swipe is gone, not just unbound");
  assert.doesNotMatch(dash, /swipeLeft|swipeRight|onItemsSwipe|_swipeTabsInScope|_swipeSuppressUntil|home-items-swipe-zone/);
  assert.doesNotMatch(dash, /useSidebarSwipe/, "one owner: the shell");

  const swipe = read("./src/composables/useSidebarSwipe.js");
  assert.match(swipe, /window\.addEventListener\("pointermove", onPointerMove/);
  assert.match(swipe, /if \(action === "open"\) \{[\s\S]*?tracking = false;[\s\S]*?drawer\.value = true;/);
});

test("the shell yields while a page-owned long-press picker holds the pointer", () => {
  // The dashboard's long-press row picker is scrubbed by the same horizontal drag
  // the shell reads as "pull the drawer out", and its backdrop only covers the
  // page *after* it opens -- so the shell has to be told, not guess.
  assert.equal(resolveSidebarSwipe(pull({ longPressActive: true })), "", "pull suppressed");
  assert.equal(resolveSidebarSwipe(pull({ longPressActive: true, drawerOpen: true, dx: -90 })), "", "push suppressed");
  assert.equal(resolveSidebarSwipe(pull({ longPressActive: false })), "open", "and released again");
  assert.equal(resolveSidebarSwipe(pull({ longPressActive: true, startX: 900 })), "", "no edge, still suppressed");

  const swipe = read("./src/composables/useSidebarSwipe.js");
  assert.match(swipe, /if \(input\.longPressActive\) return "";/);
  assert.match(swipe, /export function useSidebarSwipe\(\{ drawer, rail, enabled, longPressActive \}\)/);
  assert.match(swipe, /longPressActive: !!\(longPressActive && longPressActive\.value\)/);
  assert.match(swipe, /if \(longPressActive && longPressActive\.value\) return;/);

  // One flag, raised where the picker is opened and cleared where it closes.
  const store = read("./src/stores/dashboardStore.js");
  assert.match(store, /const longPressPickerActive = ref\(false\)/);
  assert.match(store, /\n    longPressPickerActive,/);
  const layout = read("./src/layouts/MainLayout.vue");
  assert.match(layout, /longPressActive: toRef\(dashboardStore, "longPressPickerActive"\)/);
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /longPressPickerOpen\(open\) \{[\s\S]*?this\.longPressPickerActive = !!open;/);
  // <KeepAlive> keeps the view mounted, so a route change has to lower the flag.
  assert.match(dash, /deactivated\(\) \{[\s\S]*?this\.closeLongPressPicker\(true\);[\s\S]*?\n  \},\n  beforeUnmount/);
});

test("one tap on a sidebar item both navigates and closes the drawer", () => {
  const sidebar = read("./src/layouts/AppSidebar.vue");
  // A bare `emit("go-home", ...)` left the closing to the model round-trip; on a
  // phone the overlay drawer turns `inert` for a frame while it transitions, so
  // that first tap only ever hovered. Collapsing it explicitly is half the fix.
  assert.doesNotMatch(sidebar, /@click="emit\('go-home', item\.homeTab\)"/);
  assert.doesNotMatch(sidebar, /@click="emit\('go-tab', item\.key\)"/);
  assert.match(sidebar, /@click="onNavClick\('go-home', item\.homeTab\)"/);
  assert.match(sidebar, /@click="onNavClick\('go-tab', item\.key\)"/);
  assert.match(sidebar, /function onNavClick\(event, value\) \{[\s\S]*?emit\(event, value\);[\s\S]*?if \(mobile\.value\) emit\("update:modelValue", false\);[\s\S]*?\n\}/);
  // The other half: an explicit mode, so `isTemporary` cannot flip underneath the
  // user when the breakpoint resolves after the first paint.
  assert.match(sidebar, /:temporary="mobile"/);
});

test("a blank tap in the tablet pane puts the preview away", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /class="dashboard-page-shell" :class="dashboardPageShellClass" @click="onPageShellClick"/);
  assert.match(dash, /onPageShellClick\(event\) \{[\s\S]*?if \(!this\.isTabletDrawerPreview\) return;[\s\S]*?if \(!this\.showMobilePreview\) return;/);
  assert.match(dash, /el\.closest\(SHELL_CLICK_KEEPS_PREVIEW\)/);
  assert.match(dash, /this\.closeMobilePreview\(\);/);
  // The galleries and the controls have to survive the handler, or tapping a
  // gallery would dismiss the pane instead of showing the gallery.
  for (const keep of ['".home-card"', '".v-btn"', '".v-field"', '".longpress-picker-host"', '".mobile-preview-fullscreen"']) {
    assert.ok(dash.includes(keep), `SHELL_CLICK_KEEPS_PREVIEW keeps ${keep}`);
  }
});

test("a rebuilt preview card starts at the top of the new gallery", () => {
  const card = read("./src/components/dashboard/PreviewCard.vue");
  assert.match(card, /ref="cardEl"/);
  assert.match(card, /function resetCardScroll\(\) \{[\s\S]*?el\.scrollTop = 0;/);
  assert.match(card, /() => `\$\{props\.item\?\.source \|\| ""\}:\$\{props\.item\?\.arcid \|\| ""\}`,[\s\S]*?cancelThumbLoad\(\);[\s\S]*?armThumbLoad\(\);[\s\S]*?resetCardScroll\(\);/);
});

test("both filter panels can be dismissed, not only by tapping the scrim", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const explore = read("./src/components/dashboard/TagExploreOverlay.vue");
  const store = read("./src/stores/dashboardStore.js");
  // Esc and a scrim tap write the dialog's open flag to false without calling any
  // handler (`v-dialog` is not persistent), so the rollback has to hang off the
  // close edge of that flag -- and Apply has to drop the snapshot first, which is
  // the only thing that distinguishes "keep my edit" from "put it back".
  assert.match(dash, /@click="cancelHomeFilters">{{ t\('home\.filter\.cancel'\) }}/);
  assert.doesNotMatch(dash, /_homeFiltersDraft/, "the rollback is on the store's close edge, not in the view");
  assert.match(store, /homeFiltersDraft = ref\(null\)/);
  assert.match(store, /JSON\.parse\(JSON\.stringify\(homeFilters\.value/);
  assert.match(store, /watch\(homeFiltersOpen, \(open\) => \{[\s\S]*?homeFilters\.value = homeFiltersDraft\.value;/);
  assert.match(store, /async function applyHomeFilters\(\) \{[\s\S]*?homeFiltersDraft\.value = null;/);
  assert.match(explore, /@click="cancelFilters">{{ t\('home\.filter\.cancel'\) }}/);
  assert.match(explore, /filtersDraft = ref\(null\)/);
  assert.match(explore, /watch\(filtersOpen, \(openNow\) => \{[\s\S]*?filters\.value = filtersDraft\.value;/);
  assert.match(explore, /function applyFilters\(\) \{[\s\S]*?filtersDraft\.value = null;/);

  for (const locale of ["zh", "en"]) {
    const dict = JSON.parse(read(`./src/i18n/${locale}.json`));
    assert.equal(typeof dict["home.filter.cancel"], "string", `${locale} carries the cancel label`);
    assert.ok(String(dict["home.filter.cancel"]).trim().length > 0);
    assert.ok(dict["home.filter.apply"], `${locale} still has the apply label`);
  }
});

// --- page zoom must not desynchronise the gesture -------------------------
//
// `#app { zoom: var(--zgl-page-zoom) }` shrinks the *layout* viewport, but
// `window.innerWidth` keeps reporting the unzoomed width and a `clientX` read
// inside the zoomed subtree is reported in zoomed space. At any zoom != 100% the
// edge zone (innerWidth/3, unzoomed) and the pointer that has to fall inside it
// (zoomed) were therefore measured in two different units: at 80% the zone the
// user could actually reach was a fifth of the screen wider than intended, and
// the travel threshold was off by the same factor.

test("the edge zone and the pointer are measured in the same units under zoom", () => {
  // At 100% nothing changes.
  assert.equal(unzoomPointer(120, 1), 120);
  assert.equal(unzoomPointer(120, undefined), 120, "a missing zoom is treated as 100%");
  assert.equal(unzoomPointer(120, 0), 120, "and so is a nonsense one, rather than dividing by zero");

  // In the zoomed subtree the browser reports 80px for a point that is 100 CSS
  // px from the edge; dividing by the zoom puts it back on the layout grid.
  assert.equal(unzoomPointer(80, 0.8), 100);
  assert.equal(unzoomPointer(160, 1.6), 100);

  // The collaboration, which is what actually broke: a pull that starts 100 CSS
  // px from the edge is inside the 360px zone at *any* zoom, because both sides
  // are normalised before they meet.
  const atZoom = (zoom, startCss) => resolveSidebarSwipe(pull({
    startX: unzoomPointer(startCss * zoom, zoom),
    dx: unzoomPointer(90 * zoom, zoom),
  }));
  assert.equal(atZoom(1, 100), "open");
  assert.equal(atZoom(0.8, 100), "open", "80% zoom must not move the edge zone");
  assert.equal(atZoom(1.6, 100), "open", "nor 160%");
  assert.equal(atZoom(0.8, 200), "", "and a start well past the zone still does not open");
});

test("the composable reads the live zoom, not a value captured once", () => {
  assert.equal(readPageZoom(), 1, "no document in the test: the neutral value");
  // A string CSS value, an empty declaration and a stray custom property all
  // have to resolve to a usable number -- `Number("")` is 0, which would make
  // every unzoom a division by zero.
  assert.equal(unzoomPointer(50, readPageZoom()), 50);

  const src = read("./src/composables/useSidebarSwipe.js");
  assert.match(src, /SIDEBAR_SWIPE_ZOOM_VAR = "--zgl-page-zoom"/, "the var read is the one the layout actually sets");
  assert.match(src, /getComputedStyle\(doc\.documentElement\)/, "read it from the document element");
  // The zoom has to be sampled per gesture: the user can change it between two
  // swipes, and a module-level constant would keep using the old one.
  assert.match(src, /const downZoom = readPageZoom\(\);/, "sampled when the gesture starts");
  assert.match(src, /gestureZoom = downZoom;/, "and carried for the whole drag");
  assert.match(src, /unzoomPointer\(event\?\.clientX, gestureZoom\) - startX/, "and applied to the travel");
});

// --- the long-press picker and the drawer must not fight -------------------
//
// A touch on a gallery arms a 430ms timer that opens the row picker; the picker
// is then scrubbed by the same horizontal drag the shell reads as "pull the
// sidebar out". The two were indistinguishable, so at a zoom that widened the
// edge zone the shell opened the drawer out from under the finger (130%), and at
// a zoom that narrowed it the browser's own long-press started a text selection
// and answered with `touchcancel`, which the card read as "released" -- closing
// the picker the instant it appeared (90%).

test("a press that starts on a gallery card is never the drawer's", () => {
  // The veto lives in `onPointerDown`, which decides whether to track at all --
  // a pure resolver cannot see it, so the wiring is pinned by source instead.
  const src = read("./src/composables/useSidebarSwipe.js");
  assert.match(src, /const onCard = closestOf\(target, CARD_SELECTOR\);/,
    "the card test is evaluated at pointerdown");
  assert.match(src, /if \(onCard\) return;/,
    "the shell must not track a card press, even inside its edge zone");
});

test("the long-press arming window owns the gesture and browser cancellation cannot flash it closed", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.match(page, /onCardTouchStart[\s\S]*?this\.closeLongPressPicker\(\);[\s\S]*?this\.longPressPickerActive = true;/,
    "ownership is published before the 430ms timer fires");
  assert.match(page, /onCardTouchCancel\(\) \{[\s\S]*?if \(this\.longPressPickerOpen\) \{[\s\S]*?return;[\s\S]*?\}/,
    "a browser cancellation after opening leaves the picker visible");
  assert.doesNotMatch(page, /body\.style\.touchAction = "none"/,
    "opening the picker must not change touch-action in the middle of a gesture");
  assert.match(page, /class="longpress-picker-backdrop"[\s\S]*?@click="closeLongPressPicker\(true\)"/,
    "a preserved picker still has an explicit dismissal path");
});

test("a long-press in progress owns the pointer, whether or not the picker is up", () => {
  // The flag has to cover the *arming* window too: the drag that opens the picker
  // is tracked from pointerdown, so gating only on "picker open" let the shell
  // fire 'open' mid-hold.
  assert.equal(resolveSidebarSwipe(pull({ longPressActive: true })), "",
    "while a gallery long-press owns the pointer the shell stays out");
  const src = read("./src/composables/useSidebarSwipe.js");
  assert.match(src, /if \(input\.longPressActive\) return "";/,
    "checked before any distance rule");

  // And the dashboard must raise it from the moment the press starts, not when
  // the picker opens.
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /cardPressingKey: ""/, "state for the pressed card");
  assert.match(dash, /this\.cardPressingKey = this\.previewItemKey\(item\);/,
    "raised on touchstart, before the 430ms timer");
  assert.match(dash, /this\.cardPressingKey = "";/,
    "and cleared when the press ends");
});

test("the pressed card declares that the browser does not own the touch", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  // `.card-pressing` has to be bound in the template...
  assert.match(dash, /'card-pressing': cardPressingKey === previewItemKey\(item\)/,
    "the class is bound to the pressed card");
  // ...and it has to actually take the gesture away from the browser. `pan-y`
  // (inherited from .v-main) reserves the horizontal axis, which is the axis the
  // picker scrubs on; `none` during the press is what stops the selection.
  assert.match(dash, /\.home-card\.card-pressing \{\s*touch-action: none;\s*\}/,
    "the pressing card opts out of browser panning entirely");
  assert.match(dash, /\.home-card\.card-pressing,[\s\S]{0,120}user-select: none !important;/,
    "and nothing inside it may be selected");
  // The callout is what a sustained press over text raises on mobile.
  assert.match(dash, /-webkit-touch-callout: none !important;/, "the long-press callout is suppressed");
  // The picker's own scrub axis needs the same protection.
  const host = dash.slice(dash.indexOf(".longpress-picker-host {"), dash.indexOf(".longpress-picker-card {"));
  assert.match(host, /touch-action: none;/, "the picker host does not let the browser claim the drag");
});

test("a cancel cannot close a picker that is already open", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const start = dash.indexOf("onCardTouchCancel() {");
  const body = dash.slice(start, dash.indexOf("async onManualLoadMoreClick()", start));
  // A `touchcancel` never means "the user chose something", so this path only
  // dismisses before opening. Once visible, keeping it alive is safer than
  // treating a browser/system cancellation as a completed selection.
  assert.match(body, /if \(this\.longPressPickerOpen\)/, "an open picker is recognised");
  assert.match(body, /return;/, "and the cancel is swallowed");
  assert.doesNotMatch(body, /openHomeItem/, "a cancel must never navigate");
});
