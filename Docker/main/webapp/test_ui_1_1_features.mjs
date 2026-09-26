import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("dashboard keeps automatic refresh but removes the manual refresh control", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.doesNotMatch(page, /@click="onRefreshClick"/);
  assert.doesNotMatch(page, /function onRefreshClick|onRefreshClick\(\)/);
  assert.match(page, /isFeedStale\(this\.homeTab, 5 \* 60 \* 1000\)/);
});

test("mobile shares the compact icon-only sort and filter controls", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.match(page, /flex-wrap ga-2 home-search-row/);
  assert.match(page, /v-if="isMobile" class="mobile-action-row"/);
  assert.match(page, /icon="mdi-sort"/);
  assert.match(page, /icon="mdi-filter-variant"/);
  assert.equal((page.match(/class="mobile-action-btn"/g) || []).length, 2);
  assert.doesNotMatch(page, /prepend-icon="mdi-filter-variant"/);
  assert.match(page, /\.mobile-action-row \{[\s\S]*?margin-left: auto;/);
});

test("list rating leaves breathing room above progress metadata", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.match(page, /class="d-flex align-center ga-1 list-rating-row"/);
  assert.match(page, /\.list-rating-row \{[\s\S]*?margin-bottom: 4px;[\s\S]*?translateY\(-2px\)/);
});

test("compact progress sits above the title overlay", () => {
  const css = read("./src/styles/app.css");
  assert.match(css, /\.home-card\.compact \.progress-badge-anchor \{[\s\S]*?bottom: 38px;/);
});
