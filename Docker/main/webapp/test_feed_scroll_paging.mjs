// Round 41: two feed-presentation behaviours that a source-shape check cannot
// actually prove, so the real code is sliced out and exercised.
//
//   1. Scroll memory. The feed rows survive a tab switch (KeepAlive) and a trip
//      to the toolbox (they live in the store), but the *window offset* does
//      not: every page shares one scroller and the shorter destination clamps
//      it to zero. The page has to write the offset on the way out and read it
//      on the way back in.
//   2. Paged mode's bottom affordance. "Pull once more at the bottom" must not
//      fire on the flick that merely *arrived* at the bottom -- otherwise the
//      page bar is unusable, which is the whole complaint.
import assert from "node:assert/strict";
import { after, test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

import { clearFeedScroll, forgetFeedScroll, readFeedScroll, writeFeedScroll } from "./src/utils/feedScrollMemory.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const json = value => JSON.stringify(value);
const REAL_NOW = Date.now;
after(() => { Date.now = REAL_NOW; });

/** Slice a brace-balanced body, skipping any destructuring in the parameters. */
function sliceBody(source, start, name) {
  let parens = 0;
  let open = -1;
  for (let i = start; i < source.length; i += 1) {
    const c = source[i];
    if (c === "(") parens += 1;
    else if (c === ")") parens -= 1;
    else if (c === "{" && parens === 0) { open = i; break; }
  }
  if (open < 0) throw new Error(`no body: ${name}`);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced: ${name}`);
}

/** Slice a `function name(` declaration, or a bare (possibly async) `name(...) {` method. */
function extractCallable(source, name) {
  const decl = new RegExp(`(?:async\\s+)?function ${name}\\(`).exec(source);
  if (decl) return sliceBody(source, decl.index, name);
  // The `async` prefix has to survive the slice: dropping it would leave a bare
  // `await` in the extracted body and the vm would refuse to compile it.
  const method = new RegExp(`^\\s*(?:async\\s+)?${name}\\(`, "m").exec(source);
  if (!method) throw new Error(`not found: ${name}`);
  return sliceBody(source, method.index, name);
}

/**
 * Load methods out of DashboardScopePage.vue with an `env` object that stands in
 * for the globals they reach for (window, document, the scroll-memory module).
 * The methods are real; only the browser is fake.
 */
function loadPageMethods(names) {
  const src = read("./src/views/DashboardScopePage.vue");
  const env = {
    window: undefined,
    document: undefined,
    readFeedScroll,
    writeFeedScroll,
    clearFeedScroll,
  };
  const globals = { Number, Math, JSON, String, Object, Array };
  for (const key of Object.keys(env)) {
    Object.defineProperty(globals, key, { get: () => env[key], configurable: true });
  }
  const methods = runInNewContext(
    `(() => ({ ${names.map(n => extractCallable(src, n)).join(",\n")} }))()`,
    globals,
  );
  return { methods, env };
}

/**
 * A fake dashboard instance wiring the page's own scroll helpers together, so
 * the tests assert the collaboration rather than a single method in isolation.
 */
function makePage() {
  const { methods, env } = loadPageMethods([
    "_feedScrollKeyFor",
    "_currentScrollY",
    "_scrollPinnedToDocumentEnd",
    "_saveFeedScroll",
    "_restoreFeedScroll",
    "_scrollFeedToTop",
    "_applyPagerMove",
    "onFeedScroll",
  ]);
  const state = { y: 0, scrolls: [], timers: [], written: [] };
  const ctx = {
    homeTab: "local_gallery",
    isLocalFolderMode: () => false,
    localFolderPath: "",
    $route: { name: "dashboard" },
    _feedRestoreUntil: 0,
    _feedRestoreTarget: 0,
    $nextTick: cb => cb(),
    // The window's own scroll position is the source of truth for both readers.
    _currentScrollY: () => state.y,
    _scrollPinnedToDocumentEnd: methods._scrollPinnedToDocumentEnd,
    _feedScrollKeyFor: methods._feedScrollKeyFor,
    _saveFeedScroll: methods._saveFeedScroll,
    _restoreFeedScroll: methods._restoreFeedScroll,
    _scrollFeedToTop: methods._scrollFeedToTop,
    _applyPagerMove: methods._applyPagerMove,
    onFeedScroll: methods.onFeedScroll,
  };
  env.window = {
    scrollY: 0,
    innerHeight: 800,
    scrollTo: (opts) => { state.y = Number(opts?.top || 0); state.scrolls.push(state.y); },
    requestAnimationFrame: cb => cb(),
    setTimeout: (cb) => { state.timers.push(cb); return 0; },
  };
  env.document = { documentElement: { scrollTop: 0, scrollHeight: 5000 }, body: { scrollTop: 0, scrollHeight: 5000 } };
  // Let the harness record what the module would have stored.
  env.writeFeedScroll = (key, y) => { state.written.push([key, y]); return writeFeedScroll(key, y); };
  return { ctx, state, methods, env };
}

// --- 1. the scroll memory itself ------------------------------------------

test("the scroll memory is module-scoped, so a remount cannot forget", () => {
  clearFeedScroll();
  writeFeedScroll("local_gallery", 1234.6);
  // A component that unmounts and mounts again never touches the module: the
  // offset has to still be there, because that is exactly the case it exists for.
  assert.equal(readFeedScroll("local_gallery"), 1235, "offsets are rounded");

  writeFeedScroll("local_gallery", -5);
  assert.equal(readFeedScroll("local_gallery"), 0, "a negative offset is clamped, never stored");

  forgetFeedScroll("local_gallery");
  assert.equal(readFeedScroll("local_gallery"), 0);
  assert.equal(readFeedScroll("never-written"), 0, "an unknown feed reads as the top of the page");
  assert.equal(writeFeedScroll("", 500), 0, "a blank key is not a slot");
  clearFeedScroll();
});

test("each feed gets its own offset, and folder mode is its own feed", () => {
  const { ctx, methods } = makePage();
  const at = (over) => methods._feedScrollKeyFor.call({ ...ctx, ...over });

  const keys = [
    at({ homeTab: "local_gallery" }),
    at({ homeTab: "local_gallery", isLocalFolderMode: () => true, localFolderPath: "/a/b/" }),
    at({ homeTab: "local_gallery", isLocalFolderMode: () => true, localFolderPath: "a/b/c" }),
    at({ homeTab: "local_history" }),
    at({ homeTab: "local_favorite" }),
  ];
  assert.equal(new Set(keys).size, keys.length, `feeds must not share a slot: ${json(keys)}`);
  assert.equal(at({ homeTab: "local_gallery" }), "local_gallery");
  assert.notEqual(keys[1], keys[2], "two folders are two feeds");
  assert.equal(keys[2], "local_gallery|folder:a/b/c", "the key must not depend on the slashes typed");
  assert.equal(at({ homeTab: "" }), "", "no tab means no slot to write into");
  clearFeedScroll();
});

test("the page restores a feed's offset on the way back in", () => {
  const { ctx, state, methods } = makePage();
  clearFeedScroll();
  writeFeedScroll("local_history", 900);
  ctx.homeTab = "local_history";

  methods._restoreFeedScroll.call(ctx, "local_history");
  assert.equal(state.y, 900, "coming back has to land where the user left");
  assert.equal(json(state.scrolls), json([900]));
  clearFeedScroll();
});

test("a feed that mounts short gets one retry; a user scroll is never overridden", () => {
  const { ctx, state, methods } = makePage();
  clearFeedScroll();
  writeFeedScroll("local_gallery", 2000);

  const attempt = ({ pinned, landed, expire = false }) => {
    state.y = 0;
    state.scrolls.length = 0;
    state.timers.length = 0;
    ctx._scrollPinnedToDocumentEnd = () => pinned;
    ctx._feedRestoreUntil = 0;
    methods._restoreFeedScroll.call(ctx, "local_gallery");
    // Then the browser settles: either it clamped (the feed is still growing) or
    // the user scrolled somewhere of their own accord.
    state.y = landed;
    if (expire) ctx._feedRestoreUntil = 0;
    state.timers.forEach(cb => cb());
    return json(state.scrolls);
  };

  assert.equal(attempt({ pinned: true, landed: 620 }), json([2000, 2000]), "a clamp is worth one retry");
  assert.equal(attempt({ pinned: false, landed: 300 }), json([2000]), "a short document that is NOT pinned means the user moved");
  assert.equal(attempt({ pinned: true, landed: 620, expire: true }), json([2000]), "an expired window is not retried");
  assert.equal(attempt({ pinned: true, landed: 2000 }), json([2000]), "and a landing that worked needs no retry");

  // A feed with nothing remembered is left alone entirely.
  clearFeedScroll();
  state.y = 0;
  state.scrolls.length = 0;
  state.timers.length = 0;
  methods._restoreFeedScroll.call(ctx, "local_gallery");
  state.timers.forEach(cb => cb());
  assert.equal(json(state.scrolls), json([]), "a first visit stays at the top");
  clearFeedScroll();
});

test("the page writes the offset out on deactivate and on a tab switch", () => {
  const src = read("./src/views/DashboardScopePage.vue");
  // Slice each hook out by its neighbours instead of regexing loose text: the
  // same call also appears in mounted(), so a bare `src.includes` assertion stays
  // green even when activated() is gutted -- and KeepAlive never re-fires mounted.
  const between = (from, to) =>
    src.slice(src.indexOf(from), src.indexOf(to));
  const activated = between("activated() {", "deactivated() {");
  const deactivated = between("deactivated() {", "beforeUnmount() {");
  const beforeUnmount = between("beforeUnmount() {", "watch: {");
  const homeTabWatch = between("homeTab(next, prev) {", "feedPaged() {");

  assert.ok(src.includes("activated() {"), "KeepAlive fires activated, not mounted, on the way back");
  assert.match(activated, /this\._restoreFeedScroll\(this\.homeTab\);/, "activate restores");
  assert.match(deactivated, /this\._saveFeedScroll\(\);/, "deactivate is the last-chance write");
  assert.match(beforeUnmount, /this\._saveFeedScroll\(\);/, "and an uncached unmount still saves");
  assert.match(homeTabWatch, /this\._saveFeedScroll\(prev\);/, "the tab being left is written first");
  assert.match(homeTabWatch, /this\._restoreFeedScroll\(next\);/, "and the tab being entered is restored");
  assert.match(src, /window\.addEventListener\("scroll", this\.onFeedScroll, \{ passive: true \}\);/, "a scroll has to be recorded as it happens");
  assert.match(src, /window\.removeEventListener\("scroll", this\.onFeedScroll\);/, "and unbound with the rest");
  assert.doesNotMatch(src, /_tabScrollTopMap/, "the old per-instance map is gone; two stores would fight");
  assert.doesNotMatch(src, /_tabPendingRestore/, "the pending-restore flag is dead once every tab restores itself");
});

test("a scroll on another page is never filed as the library's offset", () => {
  const { ctx, state, methods } = makePage();
  clearFeedScroll();

  ctx.$route = { name: "tools" };
  state.y = 700;
  methods.onFeedScroll.call(ctx);
  assert.equal(json(state.written), json([]), "the toolbox scrolls the same window");

  ctx.$route = { name: "dashboard" };
  methods.onFeedScroll.call(ctx);
  assert.deepEqual(state.written, [["local_gallery", 700]]);

  // ...and nothing is written while a restore is still settling, or the clamped
  // value would overwrite the offset we are trying to put back.
  state.written.length = 0;
  ctx._feedRestoreUntil = Date.now() + 5000;
  methods.onFeedScroll.call(ctx);
  assert.equal(json(state.written), json([]));
  clearFeedScroll();
});

// --- 2. the paging arithmetic ---------------------------------------------

/** The mode names and the two normalisers, straight out of the real store. */
function makeFeedConfig() {
  const src = read("./src/stores/dashboardStore.js");
  const block = src.slice(src.indexOf("export const FEED_MODE_INFINITE"), src.indexOf("export const useDashboardStore"));
  return runInNewContext(
    `(() => { ${block.replace(/export /g, "")}
      return { FEED_MODE_INFINITE, FEED_MODE_PAGED, FEED_PAGE_SIZES, FEED_DEFAULT_PAGE_SIZE, FEED_INFINITE_LIMIT, normalizeFeedMode, normalizeFeedPageSize }; })()`,
    { Number, String, Math },
  );
}

test("infinite and paged cannot both be on: they are one value, not two switches", () => {
  const cfg = makeFeedConfig();
  const store = read("./src/stores/dashboardStore.js");
  const consts = read("../webapi/core/constants.py");

  assert.equal(cfg.FEED_MODE_INFINITE, "infinite");
  assert.equal(cfg.FEED_MODE_PAGED, "paged");
  assert.match(consts, /"LOCAL_LIB_FEED_MODE": \{"type": "text", "default": "infinite"\}/);
  assert.equal((consts.match(/LOCAL_LIB_FEED_MODE/g) || []).length, 1, "declared exactly once, so 'both on' is unrepresentable");
  assert.equal((consts.match(/LOCAL_LIB_PULL_TO_PAGE/g) || []).length, 1);
  assert.doesNotMatch(store, /LOCAL_LIB_INFINITE_SCROLL|LOCAL_LIB_PAGED_ENABLED/);
  assert.match(store, /const feedPaged = computed\(\(\) => feedMode\.value === FEED_MODE_PAGED\);/);
  // The pull gesture is meaningless outside paged mode, and must report so --
  // otherwise a stale "true" leaves the bottom affordance armed in infinite mode.
  assert.match(store, /const feedPullToPage = computed\(\(\) => feedPaged\.value && settingsStore\.config\?\.LOCAL_LIB_PULL_TO_PAGE === true\);/);
});

test("a stored value the feed cannot use degrades to a usable one", () => {
  const cfg = makeFeedConfig();
  assert.equal(cfg.normalizeFeedMode(undefined), "infinite");
  assert.equal(cfg.normalizeFeedMode("PAGED"), "paged", "the config comes back as a loose string");
  assert.equal(cfg.normalizeFeedMode("nonsense"), "infinite");
  assert.equal(cfg.normalizeFeedMode(""), "infinite");

  // The wire value of an int is a string; a hand-edited config could hold
  // anything at all. Every answer has to be a size the endpoint accepts.
  assert.equal(cfg.normalizeFeedPageSize("20"), 20);
  assert.equal(cfg.normalizeFeedPageSize(undefined), cfg.FEED_DEFAULT_PAGE_SIZE);
  assert.equal(cfg.normalizeFeedPageSize(0), cfg.FEED_DEFAULT_PAGE_SIZE);
  assert.equal(cfg.normalizeFeedPageSize(-10), cfg.FEED_DEFAULT_PAGE_SIZE);
  assert.equal(cfg.normalizeFeedPageSize("999"), 100, "snapped to the largest offered size");
  assert.equal(cfg.normalizeFeedPageSize(12), 10);
  assert.ok(cfg.FEED_PAGE_SIZES.every(n => Number.isInteger(n)));
  assert.equal(cfg.FEED_INFINITE_LIMIT, 24, "the append path must keep the batch size it always had");
});

test("the page sizes the settings offer all fit under the endpoint cap", () => {
  const cfg = makeFeedConfig();
  const router = read("../webapi/routers/system.py");
  const consts = read("../webapi/core/constants.py");
  const cap = Number(/MAX_HOME_FEED_LIMIT\s*=\s*(\d+)/.exec(consts)[1]);

  assert.ok(cap >= Math.max(...cfg.FEED_PAGE_SIZES), `a ${Math.max(...cfg.FEED_PAGE_SIZES)}-row page would otherwise be a 422`);
  assert.equal((router.match(/le=MAX_HOME_FEED_LIMIT/g) || []).length, 3, "history, local and favorite");
  assert.doesNotMatch(router, /le=80/);
  assert.match(router, /offset = max\(0, int\(str\(cursor\)\)\)/, "the feeds page by offset, which is what makes the page arithmetic possible");
  // Folder mode has its own endpoint; it must accept the same page sizes.
  const folder = read("../webapi/routers/local_lib.py");
  const folderCap = Number(/safe_limit = max\(1, min\((\d+), int\(limit or 24\)\)\)/.exec(folder)[1]);
  assert.ok(folderCap >= cap, "a 100-row page in folder mode must not be truncated below the others");
});

test("paged mode replaces the feed instead of appending, and never binds the observer", () => {
  const src = read("./src/stores/dashboardStore.js");
  const bind = extractCallable(src, "bindHomeInfiniteScroll");
  const pagedAt = bind.indexOf("if (feedPaged.value) {");
  const observerAt = bind.indexOf("new IntersectionObserver");
  assert.ok(pagedAt >= 0 && pagedAt < observerAt, "paged mode has to return before the observer is created");
  assert.match(bind.slice(pagedAt, observerAt), /loadHomePage\(feedPage\.value\)/, "but mounting still has to fetch the page on screen");

  const load = extractCallable(src, "loadHomeFeed");
  assert.match(load, /if \(feedPaged\.value\) \{\s*return loadHomePage\(reset \? 1 : feedPage\.value\);/, "every existing trigger funnels through one entry point");

  // `replace` is the only difference between the two modes.
  const apply = extractCallable(src, "_applyHomeFeedPayload");
  assert.match(apply, /state\.items = replace \? rows : mergeUniqueItems\(state\.items \|\| \[\], rows\);/);

  const loadPage = extractCallable(src, "loadHomePage");
  assert.match(loadPage, /cursor: String\(\(target - 1\) \* size\)/, "pages are offset arithmetic over the same endpoint");
  assert.match(loadPage, /_applyHomeFeedPayload\(res, \{ replace: true \}\)/);
  assert.match(loadPage, /if \(!\(state\.items \|\| \[\]\)\.length && target > 1\) landed = target - 1;/, "an overshooting jump steps back instead of parking on a blank page");
  assert.match(loadPage, /if \(landed !== target\) return loadHomePage\(landed\);/);
  assert.match(loadPage, /setFeedPage\(target\);/, "the page counter only moves once a page actually landed");

  // Switching mode invalidates both row sets.
  assert.match(src, /watch\(feedPaged, \(\) => \{[\s\S]{0,400}items: \[\], cursor: "", hasMore: true/);
});

test("the jump box is bounded by the pages actually reached", () => {
  const src = read("./src/stores/dashboardStore.js");
  assert.match(
    src,
    /const high = Math\.max\(Number\(feedHighPages\.value\?\.\[key\] \|\| 0\), feedPage\.value\);\s*return high \+ \(feedCanNext\.value \? 1 : 0\);/,
    "the feeds report has_more but no total, so nothing may invent a page count",
  );
  assert.match(src, /const feedCanNext = computed\(\(\) => !!activeHomeState\.value\?\.hasMore\);/);
  assert.match(src, /const feedCanPrev = computed\(\(\) => feedPage\.value > 1\);/);
  assert.match(src, /if \(next > high\) feedHighPages\.value = \{ \.\.\.\(feedHighPages\.value \|\| \{\}\), \[key\]: next \};/, "the high-water mark only ever grows");
});

test("a page change drops the user at the top of the new page", async () => {
  const { ctx, state, methods } = makePage();
  state.y = 2400;

  await methods._applyPagerMove.call(ctx, async () => { ctx.feedPage = 4; });
  assert.equal(json(state.scrolls), json([0]), "moving to a page starts at its top");

  // A load that failed, or a page that turned out to be the one already shown,
  // must not teleport the user for nothing.
  state.scrolls.length = 0;
  await methods._applyPagerMove.call(ctx, async () => { /* the page did not change */ });
  assert.equal(json(state.scrolls), json([]), "no page change, no jump");
  // And the *page component* is what funnels every pager entry point through it.
  const dash = read("./src/views/DashboardScopePage.vue");
  for (const call of ["this.prevFeedPage()", "this.nextFeedPage()", "this.goToFeedPage(page)"]) {
    assert.ok(dash.includes(`return this._applyPagerMove(() => ${call}`), `${call} must go through _applyPagerMove`);
  }
});

// --- 3. pull-to-page must not fire on arrival -------------------------------

/** The real arming logic from FeedPullToPage.vue, on a controllable clock. */
function makePullToPage() {
  const src = read("./src/components/dashboard/FeedPullToPage.vue");
  const num = (name) => Number(new RegExp(`const ${name} = (\\d+);`).exec(src)[1]);
  const factory = runInNewContext(`(() => {
    const ARM_DELAY_MS = ${num("ARM_DELAY_MS")};
    const COOLDOWN_MS = ${num("COOLDOWN_MS")};
    const WHEEL_STEP = ${num("WHEEL_STEP")};
    const TOUCH_STEP = ${num("TOUCH_STEP")};
    let armed = { value: false };
    let armedAt = 0;
    let lastAdvanceAt = 0;
    let touchStartY = 0;
    let touchActive = false;
    let bottom = true;
    const props = { busy: false };
    const emitted = [];
    const emit = (name) => emitted.push(name);
    function atBottom() { return bottom; }
    ${extractCallable(src, "canAdvance")}
    ${extractCallable(src, "advance")}
    ${extractCallable(src, "onWheel")}
    ${extractCallable(src, "onTouchMove")}
    return {
      canAdvance, advance, onWheel, onTouchMove, emitted, props,
      armNow: t => { armed.value = true; armedAt = t; },
      setBottom: v => { bottom = v; },
      startTouch: y => { touchStartY = y; touchActive = true; },
      ARM_DELAY_MS, COOLDOWN_MS, WHEEL_STEP, TOUCH_STEP,
    };
  })()`, { Number, Date });
  return factory;
}

test("arriving at the bottom does not turn the page", () => {
  const p = makePullToPage();
  const t0 = 1_000_000;

  // The flick that brought the user here: the affordance has just armed.
  p.armNow(t0);
  Date.now = () => t0 + 50;
  p.onWheel({ deltaY: 120 });
  assert.equal(json(p.emitted), json([]), "the scroll that arrived must not page");

  // Dwelling at the bottom and pulling again -- that is the gesture.
  Date.now = () => t0 + p.ARM_DELAY_MS + 1;
  p.onWheel({ deltaY: 120 });
  assert.equal(json(p.emitted), json(["advance"]));

  // One inertial scroll cannot burn through pages.
  Date.now = () => t0 + p.ARM_DELAY_MS + 100;
  p.armNow(Date.now());
  p.onWheel({ deltaY: 220 });
  assert.equal(json(p.emitted), json(["advance"]), "the cooldown swallows a second page in the same flick");

  // ...and never while the next page is already loading.
  Date.now = () => t0 + p.ARM_DELAY_MS + p.COOLDOWN_MS + 200;
  p.props.busy = true;
  p.armNow(Date.now());
  p.onWheel({ deltaY: 220 });
  assert.equal(json(p.emitted), json(["advance"]));

  // An upward nudge is not a pull either.
  Date.now = () => t0 + p.ARM_DELAY_MS + 2 * p.COOLDOWN_MS + 300;
  p.props.busy = false;
  p.armNow(Date.now());
  p.onWheel({ deltaY: -300 });
  assert.equal(json(p.emitted), json(["advance"]), "scrolling back up must not page");
});

test("the gesture only counts at the bottom, and a twitch is not a pull", () => {
  const p = makePullToPage();
  const t0 = 2_000_000;
  const later = t0 + p.ARM_DELAY_MS + p.COOLDOWN_MS + 10;

  // Armed and past the delay and the cooldown, so the only thing left to fail is
  // the position: mid-list pulls are just scrolling.
  p.setBottom(false);
  p.armNow(t0);
  Date.now = () => later;
  p.onWheel({ deltaY: 220 });
  assert.equal(json(p.emitted), json([]), "mid-list pulls are just scrolling");

  p.setBottom(true);
  p.armNow(t0);
  Date.now = () => t0 + p.ARM_DELAY_MS + p.COOLDOWN_MS + 50;
  p.startTouch(600);
  p.onTouchMove({ touches: [{ clientY: 600 - p.TOUCH_STEP + 1 }] });
  assert.equal(json(p.emitted), json([]), "a twitch is not a pull");
  p.onTouchMove({ touches: [{ clientY: 600 - p.TOUCH_STEP - 1 }] });
  assert.equal(json(p.emitted), json(["advance"]), "a finger travelling up past the threshold is");
});

test("an explicit tap ignores the arm delay, because a click is unambiguous", () => {
  const p = makePullToPage();
  const t0 = 3_000_000;
  p.armNow(t0);
  Date.now = () => t0 + 5;
  p.advance();
  assert.equal(json(p.emitted), json(["advance"]), "keyboard and mouse users reach for the button");

  // But a tap mid-list still does nothing.
  const q = makePullToPage();
  q.setBottom(false);
  q.armNow(t0);
  Date.now = () => t0 + 5;
  q.advance();
  assert.equal(json(q.emitted), json([]));
});

test("the paged feed's bottom affordances cannot cancel each other out", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /<div v-if="!feedPaged" class="d-flex justify-center py-2">/, "infinite keeps load-more");
  assert.match(dash, /<FeedPager\s+v-else/, "paged swaps it for the page bar");
  assert.match(dash, /v-if="feedPaged && feedPullToPage && feedCanNext"/, "the pull gesture is extra, not instead");
  assert.match(dash, /:max-page="feedMaxJump"/);
  assert.match(dash, /@prev="onPagerPrev"[\s\S]{0,200}@next="onPagerNext"[\s\S]{0,200}@jump="onPagerJump"/);

  const pull = read("./src/components/dashboard/FeedPullToPage.vue");
  assert.match(pull, /if \(!armed\.value\) return false;/, "unarmed means no advance");
  assert.match(pull, /if \(Date\.now\(\) - armedAt < ARM_DELAY_MS\) return false;/, "the delay is what separates arrival from intent");
  assert.match(pull, /window\.removeEventListener\("wheel", onWheel\);/, "the window listeners are released on unmount");

  const pager = read("./src/components/dashboard/FeedPager.vue");
  assert.match(pager, /flex: 0 0 92px;\s*width: 92px;/, "an outlined field in a flex row collapses to zero width otherwise");
});

test("the settings page offers the mode as one choice and greys the rest", () => {
  const page = read("./src/views/settings/LocalLibSettingsPage.vue");
  assert.match(page, /settings\.local_lib\.display_mode\.title/);
  assert.match(page, /mandatory/, "a segmented picker, so 'both' cannot be selected");
  assert.match(page, /value="infinite"/);
  assert.match(page, /value="paged"/);
  assert.match(page, /:disabled="!feedPagedMode \|\| savingDisplayMode"/, "page size is greyed out when it does not apply");
  assert.match(page, /data-feed-mode-gated/, "and the whole gated block is visually dimmed");
  assert.match(page, /data-feed-pull\s+:disabled="!feedPagedMode \|\| savingDisplayMode"/, "the pull switch too");
  // The values must come from the module the dashboard reads, not a local copy.
  assert.match(page, /from "\.\.\/\.\.\/stores\/dashboardStore"/);
  assert.match(page, /FEED_PAGE_SIZES\.map/);
  assert.match(page, /await settingsStore\.loadConfigData\(\);/, "the dashboard reads the store, so a bare PUT would not reach the feed");
  assert.match(page, /save_not_persisted/, "and the write is read back rather than trusted");
});
