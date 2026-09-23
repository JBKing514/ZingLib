import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));
const read = (path) => readFileSync(join(root, path), "utf8");

const api = read("src/api.js");
const routes = read("src/router/index.js");
const dashboard = read("src/views/DashboardScopePage.vue");
const previewCard = read("src/components/dashboard/PreviewCard.vue");
const mainLayout = read("src/layouts/MainLayout.vue");

for (const endpoint of [
  "/manifest/upload",
  "/manifest/status",
  "/home/recommend/touch",
  "/home/recommend/impressions",
  "/home/recommend/dislike",
  "/downloads/eh",
  "/downloads/ext",
]) {
  assert.equal(api.includes(endpoint), false, `obsolete API remains: ${endpoint}`);
}

for (const routeName of ["settings-eh", "downloads", "eh-dashboard"]) {
  assert.equal(routes.includes(routeName), false, `obsolete route remains: ${routeName}`);
}

assert.equal(dashboard.includes("settings-eh"), false);
assert.equal(dashboard.includes("eh_works"), false);
assert.equal(dashboard.includes("isEhScope"), false);
assert.equal(previewCard.includes("recDebugEnabled"), false);
assert.equal(mainLayout.includes("external_source_enabled"), false);
assert.match(dashboard, /openLongPressPicker/);
assert.match(dashboard, /<PreviewCard/);

console.log("OK frontend local-only contract");
