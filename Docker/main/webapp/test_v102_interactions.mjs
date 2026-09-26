import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { WHEEL_DRAG_THRESHOLD_PX, pageForWheelDrag } from "./src/utils/readerWheelDrag.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("reader wheel tracks total pointer travel until release", () => {
  const base = { startPage: 20, startX: 200, startY: 300, totalPages: 100, position: "bottom", rtl: false };
  assert.equal(pageForWheelDrag({ ...base, currentX: 182, currentY: 300 }), 21);
  assert.equal(pageForWheelDrag({ ...base, currentX: 110, currentY: 300 }), 25);
  assert.equal(pageForWheelDrag({ ...base, currentX: 20, currentY: 300 }), 30);
  assert.equal(pageForWheelDrag({ ...base, currentX: 380, currentY: 300 }), 10);
  assert.equal(pageForWheelDrag({ ...base, position: "left", currentX: 200, currentY: 210 }), 25);
});

test("reader wheel captures one pointer and uses absolute drag state", () => {
  const wheel = read("./src/components/reader/ReaderNavWheel.vue");
  assert.match(wheel, /@pointerdown="onWheelPointerDown"/);
  assert.match(wheel, /setPointerCapture/);
  assert.match(wheel, /pageForWheelDrag\(\{/);
  assert.doesNotMatch(wheel, /touchAnchor|onWheelTouchMove/);
  assert.match(wheel, /touch-action: none/);
});

test("a wheel tap is not captured, so a mouse click still reaches the thumbnail", () => {
  const wheel = read("./src/components/reader/ReaderNavWheel.vue");
  const drag = read("./src/utils/readerWheelDrag.js");

  // Capturing on `pointerdown` retargets the following `pointerup`, and the
  // browser derives the `click` target from that -- the thumbnail's own handler
  // then never fires and a mouse click on the strip does nothing. Capture has to
  // wait for real travel.
  const down = wheel.slice(
    wheel.indexOf("function onWheelPointerDown"),
    wheel.indexOf("function onWheelPointerMove"),
  );
  assert.ok(down.length > 0, "pointerdown handler must exist");
  assert.doesNotMatch(
    down,
    /setPointerCapture/,
    "pointerdown must not capture: it would swallow the click",
  );

  // And the move handler must gate the capture behind the drag threshold.
  const move = wheel.slice(
    wheel.indexOf("function onWheelPointerMove"),
    wheel.indexOf("function onWheelPointerEnd"),
  );
  assert.match(move, /WHEEL_DRAG_THRESHOLD_PX/);
  assert.match(move, /if \(travel < WHEEL_DRAG_THRESHOLD_PX\) return;/);
  assert.match(move, /setPointerCapture/);
  assert.ok(
    move.indexOf("WHEEL_DRAG_THRESHOLD_PX") < move.indexOf("setPointerCapture"),
    "the threshold must be checked before capturing",
  );

  // The threshold constant has to be a small, non-zero distance.
  const declared = Number(/WHEEL_DRAG_THRESHOLD_PX\s*=\s*(\d+)/.exec(drag)?.[1] || 0);
  assert.ok(declared > 0 && declared <= 12, `threshold must be a small tap tolerance, got ${declared}`);

  // A tap must not also be dragged: the click handler has to exist and consume
  // the post-drag click.
  assert.match(wheel, /@click="onThumbClick\(entry, \$event\)"/);
  assert.match(wheel, /if \(draggedThisGesture\)/);
});

test("page zoom scales the application surface instead of the root font", () => {
  const css = read("./src/styles/app.css");
  assert.match(css, /#app \{[\s\S]*?zoom: var\(--zgl-page-zoom\)/);
  assert.match(css, /#app \{[\s\S]*?width: 100%/);
  assert.doesNotMatch(css, /width: calc\([^\n]*zgl-page-zoom/);
  assert.doesNotMatch(css, /font-size: calc\(16px \* var\(--zgl-page-zoom\)\)/);
});

test("dashboard view buttons remain complete independent capsules", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.doesNotMatch(dash, /<v-btn-toggle[\s\S]*?\bdivided\b[\s\S]*?<\/v-btn-toggle>/);
  assert.match(dash, /\.home-view-toggle :deep\(\.v-btn\)[\s\S]*?border-radius: 999px !important/);
  assert.match(dash, /\.home-view-toggle \{[\s\S]*?overflow: visible/);
});

test("mobile PreviewCard follows the scaled preview pane instead of raw viewport units", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /\.mobile-preview-fullscreen \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0/);
  assert.match(dash, /\.mobile-preview-body :deep\(\.preview-card\) \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0/);
  assert.doesNotMatch(dash, /\.mobile-preview-body :deep\(\.preview-card\) \{[\s\S]*?width: 100vw/);
});

test("sidebar exposes the real GitHub issues feedback link", () => {
  const sidebar = read("./src/layouts/AppSidebar.vue");
  assert.match(sidebar, /href="https:\/\/github\.com\/JBKing514\/ZingLib\/issues"/);
  assert.match(sidebar, /rel="noopener noreferrer"/);
  for (const locale of ["zh", "en"]) {
    const dict = JSON.parse(read(`./src/i18n/${locale}.json`));
    assert.ok(String(dict["nav.feedback"] || "").trim(), `${locale} carries the feedback label`);
  }
});

test("the app shell reserves horizontal touch travel for the sidebar", () => {
  const css = read("./src/styles/app.css");
  assert.match(css, /\.v-main \{[\s\S]*?touch-action: pan-y/);
});

// --- the tablet side pane -------------------------------------------------

test("a left-docked preview pane pushes the feed aside like the right one does", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const shell = dash.slice(dash.indexOf("dashboardPageShellClass() {"), dash.indexOf("longPressPickerStyle() {"));

  // Both sides have to be declared, because the CSS keys itself off these names.
  assert.match(shell, /"tablet-preview-open-right":/, "the right side is still declared");
  assert.match(shell, /"tablet-preview-open-left":/, "and so is the left");

  // The shell gives up the pane width on whichever side the drawer docked.
  // Before this, only the right side padded: the left drawer floated *over* the
  // first column of cards while the right one moved them out of the way.
  assert.match(dash, /\.dashboard-page-shell\.tablet-preview-open-right \{\s*\n\s*padding-right: var\(--tablet-preview-pane-width\);/);
  assert.match(dash, /\.dashboard-page-shell\.tablet-preview-open-left \{\s*\n\s*padding-left: var\(--tablet-preview-pane-width\);/);

  // The left drawer is docked against the rail, not the window edge, so it must
  // not also claim the rail's width as its own left offset twice over.
  assert.match(dash, /\.mobile-preview-fullscreen\.tablet-preview-drawer\.drawer-left \{[\s\S]*?left: var\(--app-sidebar-rail-width\);/);
  assert.match(dash, /\.mobile-preview-fullscreen\.tablet-preview-drawer\.drawer-left \{[\s\S]*?right: auto;/);

  // The two sides are mutually exclusive: a side cannot pad both ways.
  assert.match(shell, /"tablet-preview-open-right": this\.isTabletDrawerPreview && this\.showMobilePreview && this\.previewDrawerSide !== "left"/);
  assert.match(shell, /"tablet-preview-open-left": this\.isTabletDrawerPreview && this\.showMobilePreview && this\.previewDrawerSide === "left"/);
});

test("closing the preview pane never resurrects the previous gallery's card", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const close = dash.slice(dash.indexOf("closeMobilePreview() {"), dash.indexOf("openHomeItem(item) {"));

  // The pane is torn down from local state first, then the URL is corrected. The
  // other order (`router.back()` and hope) let the route watcher re-resolve a
  // `pv` that was still present, sliding the previous gallery's card back in.
  const clearAt = close.indexOf("this.mobilePreviewItem = null;");
  const routeAt = close.indexOf("this.$router.replace(");
  assert.ok(clearAt > -1 && routeAt > -1, "both steps must exist");
  assert.ok(clearAt < routeAt, "clear the pane before touching the route");

  // `back` assumes every open pushed a history entry; a reload or a deep link
  // breaks that, and back then lands on a route that still carries a `pv`.
  assert.doesNotMatch(close, /\$router\.back\(\)/, "going back is the bug, not the fix");
  assert.doesNotMatch(close, /setTimeout\(/, "a fixed delay both races the watcher and keeps the pane up");

  // A slower earlier close must not cancel a later one's cleanup.
  assert.match(close, /_previewCloseSeq/, "closes are sequenced");
});

// --- metadata edits have to reach the open pane ---------------------------

test("a hydrated row is folded into the open preview instead of calling a ghost", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const store = read("./src/stores/dashboardStore.js");

  // `onPreviewHydrated` used to open with `this.applyHydratedEhItem(item)` -- a
  // method that exists nowhere in the tree. The call threw on every hydration, so
  // the merge right after it never ran and an edited card kept its old tags. The
  // dead call is the bug; assert it is gone, not merely unused.
  assert.doesNotMatch(dash, /applyHydratedEhItem/, "the phantom EH-era call must not come back");

  const handler = dash.slice(dash.indexOf("onPreviewHydrated(item) {"), dash.indexOf("applyReaderOriginRestore() {"));
  assert.match(handler, /this\.patchHomeItem\(item\)/, "the rows are patched by identity");
  assert.match(handler, /_mergeHydratedItem\(this\.mobilePreviewItem, item\)/, "and the open pane is refreshed");
  assert.match(handler, /_mergeHydratedItem\(this\.tempMobileItem, item\)/, "including the snapshot that shadows the feed");
  assert.match(handler, /_mergeHydratedItem\(this\.desktopHoverPreviewItem, item\)/, "and the desktop hover pane");

  // The store owns the patch, and it must be in the public surface the page's
  // `setup()` returns -- otherwise the call is another silent undefined.
  assert.match(store, /function patchHomeItem\(item\) \{/);
  assert.match(store, /^\s*patchHomeItem,$/m, "patchHomeItem must be exported from the store");

  // `Array.prototype.map` mutates nothing; a patch that assigned into the old
  // array would leave the reactive rows untouched.
  assert.match(store, /items: \(stateRef\.value\?\.items \|\| \[\]\)\.map\(/, "patch by rebuilding the rows");
});

test("a quick-tag edit re-points the open pane at the new row", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const apply = dash.slice(dash.indexOf("async applyQuickTagDialog() {"), dash.indexOf("onPreviewApplyTagFilter(payload) {"));

  // The dialog holds `quickTagItem` -- a snapshot from before the edit -- and the
  // pane holds `tempMobileItem`, which shadows the feed. Both must be refreshed
  // once the write lands, or the card keeps showing what the user just changed.
  assert.match(apply, /await this\.resetHomeFeed\(\)/, "the write is followed by a feed reload");
  assert.match(apply, /this\.refreshOpenPreviewFromFeed\(\)/, "and the open pane is re-resolved");

  const refresh = dash.slice(dash.indexOf("refreshOpenPreviewFromFeed() {"), dash.indexOf("async onPreviewApplyTagFilter(payload) {"));
  assert.match(refresh, /findPreviewItemByKey\(pv\)/, "it looks the row up by identity");
  assert.match(refresh, /this\.tempMobileItem = hit;/, "the shadowing snapshot is replaced, not left stale");
  assert.match(refresh, /return;/, "with no open pane it is a no-op");
});
