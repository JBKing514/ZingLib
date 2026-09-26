import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { parse } from "@vue/compiler-sfc";
import { computed, ref } from "vue";
import { createPinia, defineStore, setActivePinia } from "pinia";
import * as namespaces from "./src/utils/tagNamespaces.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const { descriptor } = parse(read("./src/views/DashboardScopePage.vue"));
function quickDialog(api = async () => ({ items: [] })) {
  const saved = [];
  const source = descriptor.script.content;
  const component = runInNewContext(`(${source.slice(source.indexOf('export default') + 14).trim().replace(/;$/, '')})`, {
    // Every component the page registers has to be stubbed here: an undefined
    // identifier in `components: {...}` throws before a single test runs.
    ...namespaces, PreviewCard: {}, TagExploreOverlay: {}, FeedPager: {}, FeedPullToPage: {},
    // The progress capsule joined `components` in round 62.
    CardProgressBadge: {},
    useSettingsStore: () => ({ customNamespaceDefs: [{ key: "my-space", color: "#123456" }] }),
    getHomeTagSuggest: api,
    batchUpdateLocalMeta: async payload => saved.push(payload),
    useToastStore: () => ({ open: message => { throw Error(message); } }),
  });
  const ctx = { ...component.data(), t: key => key, config: {}, resetHomeFeed: async () => {} };
  for (const [key, fn] of Object.entries(component.methods)) ctx[key] = fn.bind(ctx);
  return { ctx, saved };
}

test("quick namespace picker receives an array with builtins and custom entries", () => {
  assert.match(descriptor.template.content, /:items="quickTagNamespaceOptions\(\)"/);
  const { ctx } = quickDialog();
  const options = ctx.quickTagNamespaceOptions();
  assert.ok(Array.isArray(options));
  assert.ok(options.some(o => o.value === "male"));
  assert.ok(options.some(o => o.value === "my-space"));
});

test("quick add accepts chosen namespace, aliases and pending text on confirm", async () => {
  const { ctx, saved } = quickDialog();
  ctx.openQuickTagDialog({ source: "works", arcid: "demo" });
  ctx.quickTagNs = "my-space";
  ctx.quickTagSearch = "example";
  ctx.commitQuickTag();
  ctx.quickTagSearch = "男性:sample";
  await ctx.applyQuickTagDialog();
  assert.deepEqual(Array.from(saved[0].add_user_tags), ["my-space:example", "male:sample"]);
  assert.equal(saved[0].arcids[0], "demo");
});

test("cleared input, switched namespace and closed dialog reject late suggestions", async () => {
  const pending = [];
  const { ctx } = quickDialog(() => new Promise(resolve => pending.push(resolve)));
  ctx.openQuickTagDialog({ source: "works", arcid: "demo" });
  const first = ctx.onQuickTagSearch("old");
  await ctx.onQuickTagSearch("");
  pending.shift()({ items: ["other:old"] });
  await first;
  assert.equal(ctx.quickTagSuggest.length, 0);
  const second = ctx.onQuickTagSearch("stale");
  ctx.onQuickTagNamespaceChange("male");
  pending.shift()({ items: ["other:stale"] });
  await second;
  assert.equal(ctx.quickTagSuggest.length, 0);
  const third = ctx.onQuickTagSearch("late");
  ctx.closeQuickTagDialog();
  pending.shift()({ items: ["male:late"] });
  await third;
  assert.equal(ctx.quickTagSuggest.length, 0);
});

test("tools contains tasks, old routes redirect and duplicate state table is gone", () => {
  const router = read("./src/router/index.js");
  for (const path of ["control", "audit"]) assert.match(router, new RegExp(`path: "${path}"[^\\n]+redirect:.*tab: "tasks"`));
  const control = read("./src/views/ControlPage.vue");
  assert.match(control, /<AuditPage/);
  assert.doesNotMatch(control, /metric-card|v-for="task in tasks"/);
  assert.match(read("./src/views/ToolsPage.vue"), /<ControlPage v-if="active === 'tasks'"/);
});

test("leaving the tasks tab during startup does not resurrect polling", async () => {
  setActivePinia(createPinia());
  let release;
  let streams = 0;
  let timers = 0;
  const source = read("./src/stores/controlStore.js");
  const storeFactory = runInNewContext(source.slice(source.indexOf("export const")).replace("export const", "const") + "\nuseControlStore", {
    computed, ref, defineStore,
    getHealth: () => new Promise(resolve => { release = resolve; }),
    getSchedule: async () => ({ schedule: {} }),
    getTasks: async () => ({ tasks: [] }),
    EventSource: class { constructor() { streams += 1; } close() {} },
    setInterval: () => { timers += 1; return 1; }, clearInterval: () => {},
  });
  const store = storeFactory();
  const started = store.startControlPolling();
  store.stopControlPolling();
  release({ database: {} });
  await started;
  assert.equal(streams, 0);
  assert.equal(timers, 0);
});
