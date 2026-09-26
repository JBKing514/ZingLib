// Round 59b: editing a gallery's metadata from the preview card must refresh
// *that card*, not the dashboard.
//
// `applyQuickTagDialog` used to call `resetHomeFeed()`, which does refresh the
// card -- by throwing away and re-fetching every other row, dropping the scroll
// position and flickering the grid, for a change that touched one gallery.
// The replacement folds the batch-update *deltas* into the row already on
// screen, so this file pins the merge.
//
// The row's derived fields matter here: the backend builds `tags` as
// `base_tags + extras + user_tags` and `title` as `user_title || official_title`
// (see `search_service._item_from_work`), so a merge that only stored a
// `user_tags` array would leave the card unchanged.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { mergeMetaEditIntoItem } from "./src/utils/metaEditMerge.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

const row = (extra = {}) => ({
  arcid: "local-abc123",
  source: "works",
  title: "官方标题",
  official_title: "官方标题",
  user_title: "",
  tags: ["female:眼镜", "language:chinese", "category:doujinshi"],
  category: "doujinshi",
  ...extra,
});

test("an added tag lands on the row in its namespaced form", () => {
  const out = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123",
    ok: true,
    added_user_tags: ["female:丝袜"],
    removed_user_tags: [],
    namespace: "female",
  });
  assert.deepEqual(out.tags, ["female:眼镜", "language:chinese", "category:doujinshi", "female:丝袜"]);
  // The card is the one on screen, and the merge must not mutate it in place:
  // `patchHomeItem` needs a new object to see the change.
  assert.notEqual(out, row(), "a new row, not a mutation");
});

test("a bare value is canonicalised with the dialog's namespace", () => {
  const out = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123",
    ok: true,
    added_user_tags: ["丝袜"],
    removed_user_tags: [],
    namespace: "female",
  });
  assert.ok(out.tags.includes("female:丝袜"), `expected female:丝袜 in ${JSON.stringify(out.tags)}`);
  assert.ok(!out.tags.includes("丝袜"), "not stored bare");
});

test("re-adding a tag does not duplicate it, in either spelling", () => {
  const exact = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123", ok: true, added_user_tags: ["female:眼镜"], removed_user_tags: [], namespace: "female",
  });
  assert.equal(exact.tags.filter(t => t === "female:眼镜").length, 1, "no duplicate");
  assert.equal(exact.tags.length, 3, "and nothing was appended");

  // A pre-namespace row may hold the bare value; the canonical form replaces it
  // rather than sitting next to it.
  const bare = mergeMetaEditIntoItem(row({ tags: ["眼镜", "language:chinese"] }), {
    arcid: "local-abc123", ok: true, added_user_tags: ["female:眼镜"], removed_user_tags: [], namespace: "female",
  });
  assert.deepEqual(bare.tags, ["language:chinese", "female:眼镜"], "the bare spelling is replaced");
});

test("a removal drops both the namespaced and the bare spelling", () => {
  const out = mergeMetaEditIntoItem(row({ tags: ["female:眼镜", "眼镜", "language:chinese"] }), {
    arcid: "local-abc123", ok: true, added_user_tags: [], removed_user_tags: ["female:眼镜"], namespace: "female",
  });
  assert.deepEqual(out.tags, ["language:chinese"], "no spelling survives");
});

test("a tag that is both added and removed ends up present", () => {
  // The server applies the add after the remove, so the merge has to agree --
  // otherwise the card and a later refresh would disagree about the same edit.
  const out = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123", ok: true,
    added_user_tags: ["female:眼镜"], removed_user_tags: ["female:眼镜"], namespace: "female",
  });
  assert.ok(out.tags.includes("female:眼镜"), "present");
  assert.equal(out.tags.filter(t => t === "female:眼镜").length, 1, "and exactly once");
});

test("the display title follows user_title and falls back when it is cleared", () => {
  const set = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123", ok: true, added_user_tags: [], removed_user_tags: [],
    namespace: "other", user_title: "我的标题",
  });
  assert.equal(set.user_title, "我的标题");
  assert.equal(set.title, "我的标题", "the user's title wins");

  const cleared = mergeMetaEditIntoItem(set, {
    arcid: "local-abc123", ok: true, added_user_tags: [], removed_user_tags: [],
    namespace: "other", user_title: "",
  });
  assert.equal(cleared.title, "官方标题", "clearing falls back to the official title");
  // The official title is the server's view of the file and is never touched.
  assert.equal(cleared.official_title, "官方标题");
});

test("the category pill is re-derived from the rewritten tag set", () => {
  // Replacing the category tag moves the pill.
  const swapped = mergeMetaEditIntoItem(row({ tags: ["language:chinese", "category:manga"], category: "manga" }), {
    arcid: "local-abc123", ok: true, added_user_tags: ["category:doujinshi"], removed_user_tags: ["category:manga"], namespace: "category",
  });
  assert.equal(swapped.category, "doujinshi", "the pill follows the tag");

  // Dropping it leaves whatever the row already resolved to. The backend falls
  // back to `raw.eh_raw.category` when no `category:` tag is present
  // (`_category_from_tags(tags, _raw_category(row))`), so an empty string would
  // be a *pessimistic* guess: the pill may legitimately stay. The merge must not
  // invent an empty category the server would not return.
  const dropped = mergeMetaEditIntoItem(row(), {
    arcid: "local-abc123", ok: true, added_user_tags: [], removed_user_tags: ["category:doujinshi"], namespace: "other",
  });
  assert.ok(!dropped.tags.some(t => t.startsWith("category:")), "the tag is gone");
  assert.equal(dropped.category, "doujinshi", "but the row keeps the category it had resolved to");
});

test("an edit that names another row, or failed, changes nothing", () => {
  const original = row();
  assert.equal(mergeMetaEditIntoItem(original, {
    arcid: "local-other", ok: true, added_user_tags: ["female:x"], removed_user_tags: [], namespace: "female",
  }), original, "a different arcid is left alone");
  assert.equal(mergeMetaEditIntoItem(original, {
    arcid: "local-abc123", ok: false, added_user_tags: ["female:x"], removed_user_tags: [], namespace: "female",
  }), original, "a failed row is not partially applied");
  assert.equal(mergeMetaEditIntoItem(null, { arcid: "local-abc123", ok: true }), null, "and a missing row is safe");
  assert.equal(mergeMetaEditIntoItem(original, null), original, "as is a missing edit");
});

// --- the wiring: the dashboard must not rebuild the feed -------------------

test("the quick-add dialog patches the card instead of rebuilding the feed", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const start = dash.indexOf("async applyQuickTagDialog() {");
  assert.ok(start > 0, "the method is still there");
  const body = dash.slice(start, dash.indexOf("quickTagTargetItem(arcid) {", start));

  assert.match(body, /mergeMetaEditIntoItem\(/, "the deltas are folded in");
  assert.match(body, /this\.patchHomeItem\(merged\);/, "and pushed into the feed states through the store");
  assert.match(body, /res\?\.rows/, "using the deltas the endpoint returned");
  // The regression: a whole-feed rebuild must no longer be the normal path.
  const eagerReset = /await this\.resetHomeFeed\(\);\s*this\.refreshOpenPreviewFromFeed\(\);/.exec(body);
  assert.ok(
    !eagerReset || body.indexOf("} else {") < eagerReset.index,
    "resetHomeFeed is only reached on the fallback branch, never on the happy path",
  );
  assert.match(body, /const ns = normalizeNamespaceKey/, "the namespace is still normalised for the merge");
});

test("the touched card is re-pointed, and the fallback still exists", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /refreshOpenPreviewFromArcids\(arcid\) \{/, "a single-card refresh helper");
  assert.match(dash, /quickTagTargetItem\(arcid\) \{/, "and a lookup that finds the on-screen row");
  // The fallback matters: if the row cannot be found or the server refused the
  // edit, showing a stale card is worse than paying for a rebuild.
  assert.match(dash, /await this\.resetHomeFeed\(\);/, "the rebuild is still reachable as a fallback");
});
