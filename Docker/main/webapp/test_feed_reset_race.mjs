import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { test } from "node:test";

const source = readFileSync(new URL("./src/stores/dashboardStore.js", import.meta.url), "utf8");
function declaration(name) {
  const start = source.indexOf(`  async function ${name}(`);
  const end = source.indexOf("\n  }", start) + 4;
  assert.ok(start >= 0 && end > start);
  return source.slice(start, end);
}

test("reset during append reloads page one and ignores the stale append", async () => {
  const state = { items: ["first"], cursor: "24", loading: false, hasMore: true };
  const pending = [];
  let sequence = 0;
  const context = {
    activeHomeState: { value: state }, feedPaged: { value: false },
    FEED_INFINITE_LIMIT: 24,
    currentFeedTabKey: () => "local_gallery",
    _nextFeedRequestId: () => ++sequence,
    _isFeedRequestCurrent: (_, id) => sequence === id,
    isUploadTab: () => false, isLocalGalleryTab: () => true, isLocalFolderMode: () => false,
    _requestHomeFeed: params => new Promise(resolve => pending.push({ params, resolve })),
    markFeedFetched() {},
    _applyHomeFeedPayload(res, { replace }) {
      state.items = replace ? res.items : [...state.items, ...res.items];
      state.cursor = res.next_cursor;
      state.hasMore = res.has_more;
    },
  };
  runInNewContext(`${declaration("loadHomeFeed")}\n${declaration("resetHomeFeed")}`, context);
  const append = context.loadHomeFeed(false);
  assert.equal(pending[0].params.cursor, "24");
  const reset = context.resetHomeFeed();
  assert.equal(pending.length, 2, "reset must not be dropped by the append's loading flag");
  assert.equal(pending[1].params.cursor, "");
  pending[0].resolve({ items: ["later"], next_cursor: "48", has_more: true });
  await append;
  assert.equal(state.items.length, 0);
  assert.equal(state.loading, true, "obsolete append must not clear the reset's loading flag");
  pending[1].resolve({ items: ["first"], next_cursor: "24", has_more: true });
  await reset;
  assert.deepEqual(state.items, ["first"]);
  assert.equal(state.loading, false);
});
