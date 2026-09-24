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
import { resolveSidebarSwipe, SIDEBAR_SWIPE_EDGE, SIDEBAR_SWIPE_TRAVEL } from "./src/composables/useSidebarSwipe.js";

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
  dx: 90,
  dy: 6,
  ...extra,
});

test("a pull from the edge opens the drawer", () => {
  // Literals, not `SIDEBAR_SWIPE_EDGE`: an expectation imported from the module
  // under test moves with the constant, so retuning the zone (or deleting the
  // constant) would keep this green. The gesture is defined in pixels of screen
  // edge, and that is what the user can actually feel.
  assert.equal(resolveSidebarSwipe(pull({ startX: 24 })), "open");
  // Exactly on the edge of the zone still counts; a pixel past it does not.
  assert.equal(resolveSidebarSwipe(pull({ startX: 25 })), "");
  assert.equal(resolveSidebarSwipe(pull({ startX: 120 })), "");
  assert.ok(SIDEBAR_SWIPE_EDGE <= 32, `the edge zone stays reachable (${SIDEBAR_SWIPE_EDGE}px)`);
  assert.ok(SIDEBAR_SWIPE_TRAVEL >= 40, `the travel threshold still rejects jitter (${SIDEBAR_SWIPE_TRAVEL}px)`);
});

test("a pull out of the rail asks for the full sidebar, not nothing", () => {
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, railOn: true })), "open");
  // Already open at full width: there is nothing to pull out.
  assert.equal(resolveSidebarSwipe(pull({ drawerOpen: true, railOn: false })), "");
});

test("a pull that starts on a gallery belongs to the gallery", () => {
  // The long-press row picker scrubs a card's row horizontally; the shell must
  // not steal that drag.
  assert.equal(resolveSidebarSwipe(pull({ onCard: true })), "");
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
  assert.match(dash, /@click="cancelHomeFilters">{{ t\('home\.filter\.cancel'\) }}/);
  assert.match(dash, /cancelHomeFilters\(\) \{[\s\S]*?this\.homeFilters = draft;[\s\S]*?this\.homeFiltersOpen = false;/);
  assert.match(explore, /@click="filtersOpen = false">{{ t\('home\.filter\.cancel'\) }}/);

  for (const locale of ["zh", "en"]) {
    const dict = JSON.parse(read(`./src/i18n/${locale}.json`));
    assert.equal(typeof dict["home.filter.cancel"], "string", `${locale} carries the cancel label`);
    assert.ok(String(dict["home.filter.cancel"]).trim().length > 0);
    assert.ok(dict["home.filter.apply"], `${locale} still has the apply label`);
  }
});
