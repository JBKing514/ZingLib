// Round 40: the favorite star must move on the tap, not one round trip later.
//
// Two separate things were wrong before this round:
//   1. `dashboardStore.toggleFavorite` awaited the POST *before* touching any
//      local state, so the icon stayed stale for the whole request.
//   2. Even once the store patches the feed rows, the desktop hover preview and
//      the mobile full-screen card are holding *snapshot* objects that the store
//      cannot reach -- so the star there never moved at all.
//
// The store function is sliced out and evaluated on its own (rather than
// stubbing the whole 1000-line store) so the ordering and the rollback are
// actually exercised, not merely grepped for.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

/** Slice a brace-balanced body starting at `start`, keeping the `async` prefix. */
function sliceBody(source, start, name) {
  const open = source.indexOf("{", start);
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

/** Slice a function declaration, or a `name(...) {` method with no `function`. */
function extractCallable(source, name) {
  const decl = source.indexOf(`async function ${name}(`) >= 0
    ? source.indexOf(`async function ${name}(`)
    : source.indexOf(`function ${name}(`);
  if (decl >= 0) return sliceBody(source, decl, name);
  const hit = new RegExp(`^\\s*${name}\\(`, "m").exec(source);
  if (!hit) throw new Error(`not found: ${name}`);
  return sliceBody(source, hit.index + hit[0].length - name.length - 1, name);
}

/** Build a callable `toggleFavorite` from the real source, with recording stubs. */
function makeToggleFavorite({ fail = false } = {}) {
  const fn = extractCallable(read("./src/stores/dashboardStore.js"), "toggleFavorite");
  const calls = [];
  const notify = [];
  const factory = runInNewContext(`(() => { ${fn}\nreturn toggleFavorite; })()`, {
    isFavorited: item => (item.tags || []).includes("favorited"),
    applyFavoritedToStates: (item, on) => calls.push(["patch", item.arcid, on]),
    postHomeFavoriteToggle: async () => {
      calls.push(["post"]);
      if (fail) throw Object.assign(new Error("nope"), { response: { data: { detail: "boom" } } });
      return { ok: true };
    },
    _notify: (msg, kind) => notify.push([msg, kind]),
    _t: key => key,
    String,
  });
  return { toggleFavorite: factory, calls, notify };
}

/** Run the page's snapshot patcher against a fake component instance. */
function makeSnapshotPatcher() {
  const fn = extractCallable(read("./src/views/DashboardScopePage.vue"), "_patchPreviewFavoriteSnapshot");
  const object = runInNewContext(`(() => ({ ${fn} }))()`, { String });
  return ({ arcid, on }) => {
    const ctx = {
      desktopHoverPreviewItem: { arcid: "local:abc", tags: ["female:x", "favorited"] },
      tempMobileItem: { arcid: "local:other", tags: ["male:y"] },
    };
    object._patchPreviewFavoriteSnapshot.call(ctx, arcid, on);
    return ctx;
  };
}

test("toggleFavorite flips the star before it talks to the server", async () => {
  const { toggleFavorite, calls, notify } = makeToggleFavorite();
  const ok = await toggleFavorite({ arcid: "local:abc", source: "works", tags: [] });

  assert.equal(ok, true);
  // The whole point: local flip first, network second.
  assert.deepEqual(calls, [["patch", "local:abc", true], ["post"]]);
  assert.deepEqual(notify, [["home.favorite.added", "success"]]);
});

test("a failed write rolls the star back and reports it", async () => {
  const { toggleFavorite, calls, notify } = makeToggleFavorite({ fail: true });
  const ok = await toggleFavorite({ arcid: "local:abc", source: "works", tags: ["favorited"] });

  assert.equal(ok, false, "callers need the failure so they can undo their own snapshot");
  assert.deepEqual(calls, [["patch", "local:abc", false], ["post"], ["patch", "local:abc", true]]);
  assert.equal(notify.length, 1);
  assert.equal(notify[0][1], "warning");
});

test("only works rows are favoritable", async () => {
  const { toggleFavorite, calls } = makeToggleFavorite();
  assert.equal(await toggleFavorite({ arcid: "x", source: "folder", tags: [] }), false);
  assert.equal(await toggleFavorite({ arcid: "", source: "works", tags: [] }), false);
  assert.deepEqual(calls, []);
});

test("the page patches the preview snapshots the store cannot reach", () => {
  const patch = makeSnapshotPatcher();
  // Arrays built inside the VM carry foreign prototypes, so compare JSON.
  const json = value => JSON.stringify(value);

  // Matching row: the star comes off, nothing else is touched.
  const off = patch({ arcid: "local:abc", on: false });
  assert.equal(json(off.desktopHoverPreviewItem.tags), json(["female:x"]));
  assert.equal(json(off.tempMobileItem.tags), json(["male:y"]), "other rows stay untouched");

  // ...and goes back on, at the end, without duplicating an existing marker.
  const on = patch({ arcid: "local:abc", on: true });
  assert.equal(json(on.desktopHoverPreviewItem.tags), json(["female:x", "favorited"]));
  const again = patch({ arcid: "local:abc", on: true });
  assert.equal(json(again.desktopHoverPreviewItem.tags), json(["female:x", "favorited"]));

  // An unrelated arcid is a no-op.
  const other = patch({ arcid: "local:zzz", on: true });
  assert.equal(json(other.desktopHoverPreviewItem.tags), json(["female:x", "favorited"]));
});

test("the page flips its snapshot optimistically and undoes it on failure", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.match(page, /requestFavoriteToggle\(item\) \{/);
  assert.match(page, /this\._patchPreviewFavoriteSnapshot\(key, next\);/);
  assert.match(page, /if \(ok === false\) this\._patchPreviewFavoriteSnapshot\(key, !next\);/);

  const body = page.slice(page.indexOf("requestFavoriteToggle(item) {"));
  const patchAt = body.indexOf("this._patchPreviewFavoriteSnapshot(key, next);");
  const postAt = body.indexOf("this.toggleFavorite(item)");
  assert.ok(patchAt > 0 && postAt > patchAt, "the snapshot patch must precede the POST");
});

test("the reader's long-press preview is optimistic too", () => {
  const src = read("./src/components/reader/ReaderLongPressSearch.vue");
  const body = src.slice(src.indexOf("async function toggleFavorite(item) {"));
  const patchAt = body.indexOf("applyFavoriteTags(item, next);");
  const postAt = body.indexOf("await postHomeFavoriteToggle(");
  assert.ok(patchAt > 0 && postAt > patchAt, "flip before the request");
  assert.match(body, /applyFavoriteTags\(item, !next\)/);
});
