// Round 39: the local library is the home page and its feeds moved into the
// sidebar rail. Three rail entries share `key: "dashboard"`, so the only thing
// that can tell them apart is the sub-tab -- and it has to survive the trip
// through the URL, or clicking "Favorites" while on "History" would no-op.
//
// The store is evaluated in a fresh VM realm, so its objects carry foreign
// prototypes; compare JSON instead of using deepStrictEqual, which compares
// prototypes and would fail for reasons that have nothing to do with the code.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { computed, ref } from "vue";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const json = value => JSON.stringify(value);

function makeLayoutStore() {
  const source = read("./src/stores/layoutStore.js");
  const body = source
    .split("\n")
    .filter(line => !line.trimStart().startsWith("import "))
    .join("\n")
    .replace("export const useLayoutStore", "const useLayoutStore")
    .replace(/const brandLogo = [^\n]*\n/, 'const brandLogo = "/ico/logo.png";\n');
  const factory = runInNewContext(`(() => { ${body}\nreturn useLayoutStore; })()`, {
    ref,
    computed,
    // A real Pinia store unwraps its refs on access; the stub has to do the same
    // or `ui.navItems` would hand back a ref instead of the array.
    defineStore: (_id, setup) => () => {
      const raw = setup();
      return new Proxy(raw, {
        get(target, key) { const v = target[key]; return v && v.__v_isRef ? v.value : v; },
      });
    },
    getInitialLang: () => "zh",
    setLang: v => v,
    t: (_lang, key) => key,
    useSettingsStore: () => ({ config: {} }),
    useAppStore: () => ({ isRecoveryMode: false }),
  });
  return factory();
}

test("the rail exposes library, favorites and history with their own icons", () => {
  const ui = makeLayoutStore();
  const home = ui.navItems.filter(x => x.homeTab);
  assert.equal(json(home.map(x => x.homeTab)), json(["local_gallery", "local_favorite", "local_history"]));
  assert.equal(json(home.map(x => x.icon)), json(["mdi-bookshelf", "mdi-star", "mdi-history"]));
  assert.equal(json(home.map(x => x.title)), json(["nav.section.local", "nav.section.favorite", "nav.section.history"]));
  assert.ok(home.every(x => x.key === "dashboard"), "every feed lives on /dashboard");
});

test("the rest of the rail stays a single flat group", () => {
  const ui = makeLayoutStore();
  assert.equal(
    json(ui.navItems.filter(x => !x.homeTab).map(x => x.key)),
    json(["tools", "xp", "settings"]),
  );
});

test("pathForTab carries the sub-tab in the query, so the switch survives", () => {
  const ui = makeLayoutStore();
  ui.setHomeTab("local_history");
  assert.equal(json(ui.pathForTab("dashboard")), json({ path: "/dashboard", query: { local_tab: "local_history" } }));
  ui.setHomeTab("local_favorite");
  assert.equal(json(ui.pathForTab("dashboard")), json({ path: "/dashboard", query: { local_tab: "local_favorite" } }));
  ui.setHomeTab("");
  assert.equal(json(ui.pathForTab("dashboard")), json({ path: "/dashboard", query: { local_tab: "local_gallery" } }));
});

test("navigation follows the sub-tab and the top bar names the active feed", () => {
  const ui = makeLayoutStore();
  const pushed = [];
  ui.init({ navigate: target => pushed.push(target) });

  ui.setHomeTab("local_favorite");
  ui.goTab("dashboard");
  assert.equal(json(pushed.at(-1)), json({ path: "/dashboard", query: { local_tab: "local_favorite" } }));
  assert.equal(ui.tab, "dashboard");
  assert.equal(ui.currentTitleKey, "nav.section.favorite");

  ui.setHomeTab("local_history");
  assert.equal(ui.currentTitleKey, "nav.section.history");
  ui.setHomeTab("local_gallery");
  assert.equal(ui.currentTitleKey, "nav.section.local");

  ui.goTab("tools");
  assert.equal(ui.currentTitleKey, "tab.tools");
});

test("legacy /control and /audit still resolve to the tools tab", () => {
  const ui = makeLayoutStore();
  assert.equal(ui.routeToTab("/control"), "tools");
  assert.equal(ui.routeToTab("/audit"), "tools");
  assert.equal(ui.routeToTab("/dashboard"), "dashboard");
  assert.equal(ui.pathForTab("tools"), "/tools");
});

test("the sidebar renders the rail feeds and the dashboard keeps only its view toggle", () => {
  const sidebar = read("./src/layouts/AppSidebar.vue");
  assert.match(sidebar, /v-for="item in homeNavItems"/);
  assert.match(sidebar, /:active="tab === 'dashboard' && homeTab === item\.homeTab"/);
  assert.match(sidebar, /@click="emit\('go-home', item\.homeTab\)"/);
  assert.match(sidebar, /homeTab: \{ type: String, default: "local_gallery" \}/);

  const dash = read("./src/views/DashboardScopePage.vue");
  assert.doesNotMatch(dash, /<v-tab value="local_/);
  assert.match(dash, /home-view-toggle/);
});

test("App.vue compares the whole location and mirrors the page's sub-tab back", () => {
  const app = read("./src/App.vue");
  assert.match(app, /function sameLocation\(target\)/);
  assert.match(app, /layoutStore\.HOME_TAB_QUERY_KEY/);
  assert.match(app, /!sameLocation\(target\)/);
  assert.match(app, /watch\(\s*\(\) => dashboardStore\.homeTab,\s*\(next\) => layoutStore\.setHomeTab\(next\),\s*\)/);
});
