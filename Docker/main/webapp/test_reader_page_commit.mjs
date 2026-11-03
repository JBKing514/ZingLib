import assert from "node:assert/strict";
import { test } from "node:test";
import { createPageCommitQueue } from "./src/utils/pageCommitQueue.js";

/** A loader whose every call is resolved by hand, so a test can decide the order. */
function manualLoader() {
  const calls = [];
  const load = (url) => new Promise((resolve) => {
    calls.push({ url, resolve });
  });
  return { load, calls };
}

const flush = () => new Promise((r) => setImmediate(r));

test("a page reaches the screen only after its bytes have decoded", async () => {
  const { load, calls } = manualLoader();
  const committed = [];
  const q = createPageCommitQueue({ load, onCommit: (k) => committed.push(k) });

  q.request("s:2", ["/page/2"]);
  await flush();
  assert.deepEqual(committed, [], "nothing on screen while the page is still loading");

  calls[0].resolve(true);
  await flush();
  assert.deepEqual(committed, ["s:2"]);
});

test("a burst of turns commits only the last target", async () => {
  const { load, calls } = manualLoader();
  const committed = [];
  const q = createPageCommitQueue({ load, onCommit: (k) => committed.push(k) });

  q.request("s:2", ["/page/2"]);
  q.request("s:3", ["/page/3"]);
  q.request("s:4", ["/page/4"]);
  await flush();

  // The middle turn finishing first must not paint over the newer target.
  calls[1].resolve(true);
  await flush();
  assert.deepEqual(committed, [], "a superseded turn commits nothing");

  calls[0].resolve(true);
  await flush();
  assert.deepEqual(committed, [], "a stale turn commits nothing either");

  calls[2].resolve(true);
  await flush();
  assert.deepEqual(committed, ["s:4"]);
});

test("a spread commits as a pair, never half of one", async () => {
  const { load, calls } = manualLoader();
  const committed = [];
  const q = createPageCommitQueue({ load, onCommit: (k) => committed.push(k) });

  q.request("d:7", ["/page/7", "/page/8"]);
  await flush();
  assert.equal(calls.length, 2);

  calls[0].resolve(true);
  await flush();
  assert.deepEqual(committed, [], "the left half alone is not a spread");

  calls[1].resolve(true);
  await flush();
  assert.deepEqual(committed, ["d:7"]);
});

test("a broken page still commits so the error state can be shown", async () => {
  const { load, calls } = manualLoader();
  const committed = [];
  const q = createPageCommitQueue({ load, onCommit: (k, info) => committed.push([k, info.ready]) });

  q.request("s:9", ["/page/9"]);
  await flush();
  calls[0].resolve(false);
  await flush();
  assert.deepEqual(committed, [["s:9", false]], "staying on the previous page forever is worse");
});

test("a stalled request does not hold the reader hostage", async () => {
  const { load } = manualLoader();
  const committed = [];
  const timers = [];
  const q = createPageCommitQueue({
    load,
    onCommit: (k, info) => committed.push([k, info.ready]),
    timeoutMs: 50,
    schedule: (fn) => {
      timers.push(fn);
      return timers.length;
    },
    cancel: () => {},
  });

  q.request("s:11", ["/page/11"]);
  await flush();
  assert.deepEqual(committed, []);

  timers[0]();
  assert.deepEqual(committed, [["s:11", false]], "timed out, still show something");
});

test("asking for the page already on screen does not reload it", async () => {
  const { load, calls } = manualLoader();
  const committed = [];
  const q = createPageCommitQueue({ load, onCommit: (k) => committed.push(k) });

  q.request("s:2", ["/page/2"]);
  await flush();
  calls[0].resolve(true);
  await flush();

  await q.request("s:2", ["/page/2"]);
  assert.equal(calls.length, 1, "no second request for the same page");
  assert.deepEqual(committed, ["s:2"]);
});
