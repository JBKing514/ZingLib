import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { createFeedCoverWindow, FEED_THUMB_PLACEHOLDER } from "./src/utils/feedCoverWindow.js";
import { markRaw, reactive, effect } from "vue";

test("cover visibility belongs to image children, not the full dashboard render", () => {
  const page = readFileSync(new URL("./src/views/DashboardScopePage.vue", import.meta.url), "utf8");
  const image = readFileSync(new URL("./src/components/FeedCoverImage.vue", import.meta.url), "utf8");
  assert.equal((page.match(/<FeedCoverImage\b/g) || []).length, 2);
  assert.doesNotMatch(page, /feedDeferredKeys\.has\(/);
  assert.match(image, /deferredKeys\.has\(coverKey\)/);
  const keys = reactive(new Set());
  let first = 0;
  let second = 0;
  const a = effect(() => { keys.has("a"); first++; });
  const b = effect(() => { keys.has("b"); second++; });
  keys.add("a");
  assert.equal(first, 2);
  assert.equal(second, 1);
  a.effect.stop();
  b.effect.stop();
});

test("raw feed rows update cover sources through independent reactive visibility", () => {
  let receive;
  const deferred = reactive(new Set());
  const item = markRaw({ thumb_url: "/thumb/a" });
  let rendered;
  let renders = 0;
  const runner = effect(() => { rendered = deferred.has("a") ? FEED_THUMB_PLACEHOLDER : item.thumb_url; renders++; });
  const window = createFeedCoverWindow({
    createObserver(callback) { receive = callback; return { observe() {}, unobserve() {}, disconnect() {} }; },
    onDeferredChange(key, value) { if (value) deferred.add(key); else deferred.delete(key); },
  });
  const node = { nodeType: 1, isConnected: true };
  window.register("a", node, item);
  window.pause();
  assert.equal(rendered, FEED_THUMB_PLACEHOLDER);
  window.resume();
  receive([{ target: node, isIntersecting: true }]);
  assert.equal(rendered, "/thumb/a");
  assert.equal(renders, 3);
  window.dispose();
  runner.effect.stop();
});

function harness() {
  let time = 0;
  let sequence = 0;
  let receive;
  let observeCalls = 0;
  const timers = new Map();
  const observed = new Set();
  const window = createFeedCoverWindow({
    createObserver(callback) {
      receive = callback;
      return {
        observe(node) { observed.add(node); observeCalls++; },
        unobserve: node => observed.delete(node),
        disconnect: () => observed.clear(),
      };
    },
    now: () => time,
    setTimer(callback, delay) {
      const id = ++sequence;
      timers.set(id, { callback, at: time + delay });
      return id;
    },
    clearTimer: id => timers.delete(id),
  });
  return {
    window, observed, timers,
    get observeCalls() { return observeCalls; },
    add(key) {
      const node = { nodeType: 1, isConnected: true, getBoundingClientRect() { throw Error("unexpected layout read"); } };
      const item = { thumb_url: `/thumb/${key}` };
      window.register(key, node, item);
      return { key, node, item };
    },
    emit(node, isIntersecting) { receive([{ target: node, isIntersecting }]); },
    advance(ms) {
      const end = time + ms;
      for (;;) {
        const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
        if (!next || next[1].at > end) break;
        time = next[1].at;
        timers.delete(next[0]);
        next[1].callback();
      }
      time = end;
    },
  };
}

test("distant covers release after the grace period without synchronous layout reads", () => {
  const h = harness();
  const { node, item } = h.add("a");
  h.emit(node, false);
  h.advance(399);
  assert.equal(Boolean(item._thumbDeferred), false);
  h.advance(1);
  assert.equal(item._thumbDeferred, true);
  h.emit(node, true);
  assert.equal(item._thumbDeferred, false);
});

test("returning to the preload margin cancels a stale release even before the card is visible", () => {
  const h = harness();
  const { node, item } = h.add("a");
  h.emit(node, false);
  h.advance(200);
  h.emit(node, true);
  h.advance(1000);
  assert.equal(Boolean(item._thumbDeferred), false);
  assert.equal(h.timers.size, 0);
});

test("a thousand releases share one timer and preserve individual deadlines", () => {
  const h = harness();
  const rows = Array.from({ length: 1000 }, (_, i) => h.add(String(i)));
  rows.forEach(({ node }) => h.emit(node, false));
  assert.equal(h.timers.size, 1);
  h.advance(200);
  const later = h.add("later");
  h.emit(later.node, false);
  h.advance(200);
  assert.ok(rows.every(({ item }) => item._thumbDeferred));
  assert.equal(Boolean(later.item._thumbDeferred), false);
  assert.equal(h.timers.size, 1);
  h.advance(200);
  assert.equal(later.item._thumbDeferred, true);
  assert.equal(h.timers.size, 0);
});

test("null refs unobserve removed cards and cancel their queued releases", () => {
  const h = harness();
  const { node, item } = h.add("a");
  h.emit(node, false);
  h.window.register("a", null, item);
  assert.equal(h.observed.size, 0);
  assert.equal(h.timers.size, 0);
  h.emit(node, false);
  h.advance(1000);
  assert.equal(Boolean(item._thumbDeferred), false);
});

test("rebinding a row snapshot preserves deferred state without observing the same node twice", () => {
  const h = harness();
  const { node, item } = h.add("a");
  h.emit(node, false);
  h.advance(400);
  const replacement = { thumb_url: "/thumb/new-a" };
  h.window.register("a", node, replacement);
  assert.equal(replacement._thumbDeferred, true);
  assert.equal(h.observeCalls, 1);
  h.emit(node, true);
  assert.equal(replacement._thumbDeferred, false);
  assert.equal(item._thumbDeferred, true, "late updates must not mutate the old row snapshot");
});

test("replacing a node prevents old observer entries from affecting the new card", () => {
  const h = harness();
  const old = h.add("a");
  h.emit(old.node, false);
  const next = h.add("a");
  h.emit(old.node, false);
  h.advance(1000);
  assert.equal(Boolean(next.item._thumbDeferred), false);
  assert.deepEqual([...h.observed], [next.node]);
});

test("KeepAlive pause releases covers and resume restores only near cards", () => {
  const h = harness();
  const first = h.add("a");
  h.emit(first.node, false);
  h.window.pause();
  assert.equal(h.observed.size, 0);
  assert.equal(h.timers.size, 0);
  assert.equal(first.item._thumbDeferred, true);
  h.emit(first.node, true);
  assert.equal(first.item._thumbDeferred, true, "callbacks queued before pause are ignored");
  const second = h.add("b");
  assert.equal(second.item._thumbDeferred, true);
  h.window.resume();
  assert.equal(h.observed.size, 2);
  h.emit(first.node, true);
  assert.equal(first.item._thumbDeferred, false);
  assert.equal(second.item._thumbDeferred, true);
});

test("disposal clears observers and timers and cannot be revived by late callbacks", () => {
  const h = harness();
  const { node, item } = h.add("a");
  h.emit(node, false);
  h.window.dispose();
  h.window.resume();
  h.emit(node, true);
  h.advance(1000);
  assert.equal(item._thumbDeferred, true);
  assert.equal(h.observed.size, 0);
  assert.equal(h.timers.size, 0);
});

test("an unavailable IntersectionObserver leaves real thumbnails usable", () => {
  const window = createFeedCoverWindow({ createObserver: null });
  const item = { thumb_url: "/thumb/a", _thumbDeferred: true };
  window.register("a", { nodeType: 1, isConnected: true }, item);
  assert.equal(item._thumbDeferred, false);
  window.pause();
  window.resume();
  window.dispose();
});

test("ordinary cover loads do not write reactive retry state, while retry successes still reset it", () => {
  const source = readFileSync(new URL("./src/views/DashboardScopePage.vue", import.meta.url), "utf8");
  const body = source.match(/onFeedImageLoaded\(item, event\) \{([\s\S]*?)\n    \},/)[1];
  const load = runInNewContext(`(function(item, event) {${body}})`, { FEED_THUMB_PLACEHOLDER });
  const reset = [];
  const receiver = { onImageLoaded: item => reset.push(item) };
  const ordinary = Object.freeze({ thumb_url: "/thumb/a" });
  load.call(receiver, ordinary, { target: { getAttribute: () => "/thumb/a" } });
  assert.equal(reset.length, 0, "successful first loads should not invalidate the whole gallery feed");
  const retrying = { _is_retrying: true, _retries: 3 };
  load.call(receiver, retrying, { target: { getAttribute: () => FEED_THUMB_PLACEHOLDER } });
  assert.equal(reset.length, 0, "placeholder success must not clear a real image's retry state");
  load.call(receiver, retrying, { target: { getAttribute: () => "/thumb/a" } });
  assert.deepEqual(reset, [retrying]);
});
