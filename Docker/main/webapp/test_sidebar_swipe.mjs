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
