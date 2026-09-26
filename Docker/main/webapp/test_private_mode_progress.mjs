// Private (incognito) reading mode and the reading-progress capsule.
//
// Both touch things that quietly lose data if wrong: private mode must actually
// stop the writes, and the capsule must not claim a percentage it cannot know.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { usePreviewProgressStore } from "./src/stores/previewProgressStore.js";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const dash = read("./src/views/DashboardScopePage.vue");
const reader = read("./src/views/ReaderPage.vue");
const store = read("./src/stores/dashboardStore.js");
const app = read("./src/App.vue");
const css = read("./src/styles/app.css");

function freshStore() {
  setActivePinia(createPinia());
  return usePreviewProgressStore();
}

// --- private mode ---------------------------------------------------------

test("private mode publishes a persistent notice with a way out", () => {
  // The mode is a posture the user cannot see on any other screen, so it has to
  // announce itself -- and the announcement has to be dismissible from the
  // notification centre, not only from the switch that set it.
  assert.match(store, /function setPrivateMode\(on\)/);
  assert.match(store, /layout\.pushNotice\(/);
  assert.match(store, /actionLabel:/, "the notice carries a button");
  assert.match(store, /onAction: \(\) => setPrivateMode\(false\)/, "and the button turns the mode off");
  assert.match(store, /layout\.dismissNoticeType\(/, "leaving the mode retracts the notice");
});

test("both reader write paths consult private mode before persisting", () => {
  // History...
  const rec = reader.indexOf("async function recordReadEvent(");
  const recBody = reader.slice(rec, reader.indexOf("\n}\n", rec));
  assert.match(recBody, /isPrivateMode\(\)\) return;/, "history is dropped in private mode");
  // ...and bookmarks.
  const bm = reader.indexOf("function syncBookmarkDebounced(");
  const bmBody = reader.slice(bm, reader.indexOf("\n}\n", bm));
  assert.match(bmBody, /isPrivateMode\(\)\) return;/, "bookmarks are dropped in private mode");
  assert.match(bmBody, /postReaderBookmarkSet/, "the guard is on the request, not on scheduling");
});

test("the history guard fires before the throttle is consumed", () => {
  // If the private-mode return sat *after* `lastReadEventAt` was updated, a
  // suppressed write would still burn the coalescing window and the next
  // legitimate event would be swallowed. Order is the contract.
  const rec = reader.indexOf("async function recordReadEvent(");
  const body = reader.slice(rec, reader.indexOf("\n}\n", rec));
  const guardAt = body.indexOf("isPrivateMode()");
  const throttleAt = body.indexOf("lastReadEventAt = nowMs");
  assert.ok(guardAt > 0, "the guard exists");
  assert.ok(throttleAt > 0, "the throttle write exists");
  assert.ok(guardAt < throttleAt, "the guard runs first");
});

test("private mode changes application chrome without filtering gallery media", () => {
  assert.match(css, /#app\.zgl-private-mode \.v-application\s*\{[^}]*--v-theme-primary:/);
  assert.doesNotMatch(css, /#app\.zgl-private-mode\s*\{[^}]*filter:/,
    "a root filter would recolour every cover image");
  assert.match(app, /classList\.toggle\("zgl-private-mode"/);
  assert.match(app, /\{\s*immediate:\s*true\s*\}/, "the class is applied on mount, not only on change");
});

test("private mode gives the app bar and sidebar an explicit private palette", () => {
  assert.match(css, /#app\.zgl-private-mode \.app-header,[\s\S]{0,120}\.app-sidebar-drawer/);
});

// --- progress capsule -----------------------------------------------------

test("the capsule states a percentage only when it has a denominator", () => {
  const s = freshStore();
  // No manifest yet: unknown, not zero. A card that reads "0%" for a gallery
  // the user has never opened would be asserting something it cannot know.
  assert.equal(s.progressPercent({ arcid: "a" }), null);
  s.publish({ arcid: "a", page: 3, total: 10 });
  assert.equal(s.progressPercent({ arcid: "a" }), 30);
  assert.equal(s.progressPercent({ arcid: "b" }), null, "a different gallery is still unknown");
});

test("persisted bookmarks become visible once the manifest total is known", () => {
  const s = freshStore();
  const item = { arcid: "saved", raw: { bookmark: 7 } };
  assert.equal(s.progressPercent(item), null, "a bookmark alone has no honest percentage");
  s.publish({ arcid: "saved", total: 20 });
  assert.equal(s.progressPercent(item), 35);
});

test("a row may carry its own page count without a session publish", () => {
  const s = freshStore();
  assert.equal(s.progressPercent({ arcid: "inline", raw: { bookmark: 3 }, page_count: 12 }), 25);
});

test("a finished gallery reads 100, not (total - 1) / total", () => {
  const s = freshStore();
  s.publish({ arcid: "done", page: 20, total: 20 });
  assert.equal(s.progressPercent({ arcid: "done" }), 100);
});

test("progress survives a page update that omits the total", () => {
  // The reader publishes `total` only once the manifest is loaded; later page
  // turns must not erase the denominator it already learned.
  const s = freshStore();
  s.publish({ arcid: "x", page: 1, total: 8 });
  s.publish({ arcid: "x", page: 6 });
  assert.equal(s.progressPercent({ arcid: "x" }), 75);
});

test("a resumed reading is not mistaken for an unread one", () => {
  const s = freshStore();
  s.publish({ arcid: "y", page: 4, total: 10 });
  assert.equal(s.resumePage({ arcid: "y" }), 4, "the resume affordance still works");
});

test("folders never get a progress capsule", () => {
  // A folder is a container, not something with pages: there is no honest
  // percentage to show, so the helper refuses rather than defaulting to 0.
  const helper = store.slice(store.indexOf("function itemProgressPercent("));
  const body = helper.slice(0, helper.indexOf("\n  }\n"));
  assert.match(body, /!== "works"/, "only readable galleries qualify");
});

test("the capsule is rendered in all three card shapes", () => {
  const badges = dash.match(/<CardProgressBadge/g) || [];
  assert.ok(badges.length >= 2, `expected the grid card and the list row to carry it, saw ${badges.length}`);
  assert.match(dash, /class="progress-badge-anchor"/, "the cover overlay placement");
  assert.match(dash, /class="progress-badge-inline"/, "the list metadata placement");
});

test("the cover capsule mirrors the category capsule instead of stacking on it", () => {
  // Category is bottom-right; progress must be bottom-left at the same inset,
  // or the two overlap on every gallery that has both.
  const anchor = css.slice(css.indexOf(".progress-badge-anchor"));
  const block = anchor.slice(0, anchor.indexOf("}"));
  assert.match(block, /left:\s*6px/);
  assert.match(block, /bottom:\s*6px/);
  assert.doesNotMatch(block, /right:\s*6px/);
});

test("a completed gallery receives the darker progress treatment", () => {
  const badge = read("./src/components/dashboard/CardProgressBadge.vue");
  assert.match(badge, /'is-complete': isComplete/);
  assert.match(badge, /return Number\(this\.percent\) >= 100;/);
  const complete = css.slice(css.indexOf(".progress-badge.is-complete"));
  assert.match(complete, /#7c2d12/, "the 100% state ends in a deeper burnt orange");
});
