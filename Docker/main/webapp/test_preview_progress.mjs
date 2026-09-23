import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { computed, ref, reactive } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { usePreviewProgressStore } from "./src/stores/previewProgressStore.js";

const reader = readFileSync(new URL("./src/views/ReaderPage.vue", import.meta.url), "utf8");

test("reader identity survives the router switching to the preview route", () => {
  const route = reactive({ params: { arcid: "gallery-a" } });
  const declaration = reader.match(/^const arcid = .*;$/m)?.[0];
  assert.ok(declaration);
  const arcid = runInNewContext(`${declaration}\narcid`, { ref, computed, route });
  route.params = {};
  assert.equal(arcid.value, "gallery-a");
});

test("reader exit updates mounted and remounted previews, not dashboard rows", () => {
  setActivePinia(createPinia());
  const store = usePreviewProgressStore();
  const item = Object.freeze({ arcid: "gallery-a", raw: Object.freeze({ bookmark: 3 }) });
  const other = Object.freeze({ arcid: "gallery-b", raw: Object.freeze({ bookmark: 6 }) });
  const feed = Object.freeze([other, item]);
  const mounted = computed(() => store.resumePage(item));
  assert.equal(mounted.value, 3);
  store.publish({ arcid: "gallery-a", page: 12 });
  assert.equal(mounted.value, 12);
  assert.equal(store.resumePage({ ...item }), 12);
  assert.equal(store.resumePage(other), 6);
  assert.deepEqual(feed.map(row => row.raw.bookmark), [6, 3]);
  store.publish({ arcid: "gallery-a", page: 2 });
  assert.equal(mounted.value, 2, "rereading an earlier page is not monotonic");
});

test("invalid exits are ignored; full reload returns to server bookmarks", () => {
  setActivePinia(createPinia());
  const store = usePreviewProgressStore();
  const item = { arcid: "a", raw: { bookmark: 8 } };
  for (const page of [undefined, NaN, Infinity, -1, 0]) store.publish({ arcid: "a", page });
  store.publish({ arcid: "", page: 4 });
  assert.equal(store.resumePage(item), 8);
  store.publish({ arcid: "a", page: 10.9 });
  assert.equal(store.resumePage(item), 10);
  setActivePinia(createPinia());
  assert.equal(usePreviewProgressStore().resumePage(item), 8);
  assert.equal(usePreviewProgressStore().resumePage(null), 1);
});

/** A stub component instance for running the reader's real onBeforeUnmount. */
function makeTeardown(body) {
  const calls = [];
  const context = {
    onBeforeUnmount: fn => fn(),
    manifestReady: { value: true },
    arcid: { value: "leaving-gallery" },
    currentPage: { value: 23 },
    // The reader publishes `progressPage` (currentPage clamped to the last real
    // page), not `currentPage`: on the round-40 end screen the latter is N+1,
    // which would offer "resume at" a page that cannot open.
    progressPage: { value: 23 },
    route: { name: "dashboard", params: {}, query: {} },
    readDwellQualified: true, readTurnCount: 1,
    previewProgressStore: { publish: value => calls.push(["preview", value.arcid, value.page]) },
    syncBookmarkDebounced: (page, immediate) => calls.push(["bookmark", page, immediate]),
    // An unresolved network request must not delay the preview update.
    recordReadEvent: () => new Promise(() => {}),
    closeLocalReaderSession: () => Promise.resolve(),
    localPrefetchSeen: new Set(),
    ...body,
  };
  for (const name of ["clearLongPressTimer", "clearBookmarkSyncTimer", "clearReadQualifyTimer",
    "clearPagedProgressTimer", "resetWheelThumbPreload", "clearLocalReaderStatusPolling", "disposeContinuousScroll"]) {
    context[name] = () => {};
  }
  const start = reader.lastIndexOf("onBeforeUnmount(() => {");
  runInNewContext(reader.slice(start, reader.indexOf("</script>", start)), context);
  return calls;
}

for (const ready of [true, false]) {
  test(`actual reader teardown publishes only valid sessions (ready=${ready})`, () => {
    const calls = makeTeardown({ manifestReady: { value: ready } });
    assert.deepEqual(calls, ready ? [["preview", "leaving-gallery", 23], ["bookmark", 23, true]] : []);
  });
}

test("a reader parked on the end screen publishes the last real page", () => {
  // currentPage is one past the last page there, so only progressPage is valid.
  const calls = makeTeardown({ currentPage: { value: 41 }, progressPage: { value: 40 } });
  assert.deepEqual(calls.filter(c => c[0] === "preview"), [["preview", "leaving-gallery", 40]]);
});

test("dashboard navigation does not reset the leaving reader to page one", () => {
  const start = reader.indexOf("watch(() => route.query.page,");
  const end = reader.indexOf("watch(() => currentPage.value", start);
  runInNewContext(reader.slice(start, end), {
    watch: (_source, callback) => callback(),
    route: { name: "dashboard", query: {} },
    pageFromRoute: () => { throw new Error("must not read destination query"); },
  });
});
