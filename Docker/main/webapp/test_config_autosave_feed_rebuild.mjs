// Round 42: four behaviours that "it built" cannot prove.
//
//   1. Switching infinite <-> paged used to empty the feed for good, because the
//      watcher that cleared the rows never fetched anything back and the tab the
//      user was standing on (settings) does not own the dashboard. The rebuild is
//      therefore asserted to sit *inside* that watcher, after the clearing.
//   2. The pull-to-page arrow must not spin any more; the down-nudge stays.
//   3. Every settings surface writes through the store's auto-saver: no save
//      button may survive, and the saver must diff, debounce and single-flight.
//   4. The timezone picker is a filterable autocomplete, so a city can be typed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

/** Slice a brace-balanced block that starts at the first `marker`. */
function sliceBalanced(source, marker) {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, `marker not found: ${marker}`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced: ${marker}`);
}

/** The body of a top-level `function name(` or a bare (async) `name(...) {`. */
function sliceCallable(source, name) {
  const decl = new RegExp(`(?:async\\s+)?function ${name}\\(`).exec(source);
  const at = decl ? decl.index : new RegExp(`^\\s*(?:async\\s+)?${name}\\(`, "m").exec(source)?.index;
  assert.ok(at >= 0, `callable not found: ${name}`);
  return sliceBalanced(source.slice(at), decl ? `function ${name}(` : `${name}(`);
}

// --- 1. a mode switch rebuilds the feed, on its own --------------------------

test("the watcher that empties the feed also fetches one back", () => {
  const store = read("./src/stores/dashboardStore.js");
  const watcher = sliceBalanced(store, "watch(feedPaged, () => {");

  // Both row sets are dropped, exactly as before.
  assert.match(watcher, /clearHomeObserver\(\)/);
  assert.match(watcher, /items: \[\], cursor: "", hasMore: true/);
  assert.match(watcher, /feedPages\.value = \{\};/);
  assert.match(watcher, /feedHighPages\.value = \{\};/);

  // ...and now something puts a feed back, which is the whole fix.
  const clearAt = watcher.indexOf("feedHighPages.value = {};");
  const rebuildAt = watcher.search(/loadHomeFeed\(true\)/);
  assert.ok(rebuildAt > clearAt, "the rebuild has to happen after the clearing, not instead of it");
  assert.match(watcher, /setFeedPage\(1\);/, "a rebuilt feed starts on page one");
  assert.match(watcher, /if \(!worthRebuilding \|\| isUploadTab\(\)\) return;/, "the upload tab has nothing to rebuild");
  assert.match(watcher, /const worthRebuilding = feedModeSeen \|\| feedPaged\.value;/);
  // The one firing that must be skipped is the *default* being confirmed while
  // the config loads -- the dashboard's own mount already fetches that feed.
  assert.match(store, /let feedModeSeen = false;\s*watch\(feedPaged,/);
});

test("coming back to the dashboard rebinds the feed and honours a pending rebuild", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  const activated = dash.slice(dash.indexOf("activated() {"), dash.indexOf("deactivated() {"));

  assert.match(activated, /if \(this\._feedPendingTop\)/, "a rebuilt feed cannot restore an old offset onto new rows");
  assert.match(activated, /this\._scrollFeedToTop\(\)/);
  assert.match(activated, /this\._feedPendingTop = false;/, "the flag is one-shot");
  assert.match(activated, /this\._restoreFeedScroll\(this\.homeTab\);/, "otherwise scroll memory still wins");
  assert.match(activated, /bindHomeInfiniteScroll/, "paged needs a fetch, infinite needs the append observer");
  assert.ok(
    activated.indexOf("$nextTick") < activated.indexOf("bindHomeInfiniteScroll"),
    "the observer is bound after the DOM settles, not against a stale list",
  );

  // The flag is set from the mode watcher, and only while the dashboard is away
  // (yanking the settings page the user is standing on to the top would be wrong).
  const watcher = sliceBalanced(dash, "feedPaged() {");
  assert.match(watcher, /String\(this\.\$route\?\.name \|\| ""\) === "dashboard"[\s\S]{0,120}this\._scrollFeedToTop\(\);/);
  assert.match(watcher, /else \{[\s\S]{0,220}this\._feedPendingTop = true;/, "away from the dashboard the jump is deferred");
  assert.match(watcher, /clearFeedScroll\(\);/, "the old offsets are dead either way");
  assert.match(dash, /_feedPendingTop: false,/, "declared on the component");
});

// --- 2. the arrow no longer spins -------------------------------------------

test("pulling to the next page nudges the arrow instead of spinning it", () => {
  const pull = read("./src/components/dashboard/FeedPullToPage.vue");
  assert.doesNotMatch(pull, /feed-pull-spin/, "the spin keyframes and their use are gone");
  assert.match(pull, /@keyframes feed-pull-nudge/, "the arrival bob is the intended motion and stays");
  assert.match(pull, /\.feed-pull\.is-busy \.feed-pull-arrow \{\s*animation: none;/);
  assert.match(pull, /\{ 'is-armed': armed, 'is-busy': busy \}/, "the busy class is still what the rule hangs off");
});

// --- 3. one auto-saver, no save buttons -------------------------------------

test("no settings surface keeps a save button", () => {
  const settingsPage = read("./src/views/SettingsPage.vue");
  assert.doesNotMatch(settingsPage, /saveConfig\(/, "the page must not be able to save by hand");
  assert.doesNotMatch(settingsPage, /settings\.save\b/, "and the old 'Save Settings' label is not back");
  assert.match(settingsPage, /settings-autosave/, "in its place: a status row");
  assert.match(settingsPage, /settingsStore\.configSaveState/, "driven by the store, not a local flag");

  const quick = read("./src/components/reader/ReaderQuickSettings.vue");
  assert.doesNotMatch(quick, /saveNow/, "the reader panel's save button and handler are removed");
  assert.doesNotMatch(quick, /settings\.save\b/);
  assert.match(quick, /settings\.autosave\.inline/);
});

test("the auto-saver diffs, debounces and is single-flight", () => {
  const store = read("./src/stores/settingsStore.js");

  assert.match(store, /watch\(config, \(\) => \{ scheduleConfigAutoSave\(\); \}, \{ deep: true \}\);/);

  const flush = sliceCallable(store, "flushConfig");
  // Overlapping writes would land out of order, so a second call while one is in
  // flight only raises a flag; the in-flight one runs again afterwards.
  assert.match(flush, /if \(_autoSaveInFlight\) \{\s*_autoSaveAgain = true;\s*return _autoSaveInFlight;/);
  assert.match(flush, /if \(!dirty\.length\) \{/);
  assert.match(flush, /_markConfigSaved\(dirty, desired\);/);
  assert.match(flush, /if \(_autoSaveAgain\) \{\s*_autoSaveAgain = false;\s*flushConfig\(\)/);
  assert.match(flush, /const res = await updateConfig\(payload\);/, "only the changed keys go out");

  // "Changed" is asked per schema type: the wire keeps every value as text, so a
  // number 20 vs "20" or false vs "0" must not read as an edit.
  const changed = sliceCallable(store, "_configValueChanged");
  assert.match(changed, /const type = String\(schema\.value\?\.\[key\]\?\.type \|\| ""\);/);
  assert.match(changed, /if \(type === "bool"\) return parseBool\(a, false\) !== parseBool\(b, false\);/);
  assert.match(changed, /return String\(a \?\? ""\) !== String\(b \?\? ""\);/);

  // The baseline is taken at the end of the load, *after* the client-side
  // fallbacks are filled in -- otherwise opening the app would push all of them.
  const load = sliceCallable(store, "loadConfigData");
  assert.match(load, /_savedConfig = \{ \.\.\._desiredConfigValues\(\) \};/);
  assert.match(store, /const AUTO_SAVE_DEBOUNCE_MS = \d+;/);
  assert.match(store, /flushConfig,\s*configSaveState,\s*configSaveError,/);

  // `saveConfig` survives as a flush escape hatch for the flows that must land
  // before they continue; it must not re-read the config any more.
  const save = sliceCallable(store, "saveConfig");
  assert.match(save, /return flushConfig\(\);/);
  assert.doesNotMatch(save, /loadConfigData/);
});

test("the autosave copy exists in both languages", () => {
  const en = JSON.parse(read("./src/i18n/en.json"));
  const zh = JSON.parse(read("./src/i18n/zh.json"));
  const keys = [
    "settings.autosave.idle",
    "settings.autosave.pending",
    "settings.autosave.saving",
    "settings.autosave.saved",
    "settings.autosave.failed",
    "settings.autosave.inline",
    "settings.ui.timezone_hint",
  ];
  keys.forEach((key) => {
    assert.ok(en[key], `en.json is missing ${key}`);
    assert.ok(zh[key], `zh.json is missing ${key}`);
  });
  assert.match(en["settings.autosave.failed"], /\{reason\}/, "the failure has to say why");
  assert.match(zh["settings.autosave.failed"], /\{reason\}/);
});

// --- 4. the timezone picker takes typed input -------------------------------

test("the container timezone can be typed, not only scrolled", () => {
  const general = read("./src/views/settings/GeneralSettingsPage.vue");
  assert.match(general, /<v-autocomplete[\s\S]{0,400}v-model="config\.DATA_UI_TIMEZONE"/);
  assert.doesNotMatch(general, /v-select[^>]*v-model="config\.DATA_UI_TIMEZONE"/);
  assert.match(general, /:placeholder="t\('settings\.ui\.timezone_hint'\)"/);

  const wizard = read("./src/components/SetupWizard.vue");
  assert.match(wizard, /<v-autocomplete[\s\S]{0,400}v-model="setupForm\.DATA_UI_TIMEZONE"/);
  assert.doesNotMatch(wizard, /v-select[^>]*v-model="setupForm\.DATA_UI_TIMEZONE"/);

  // Autocomplete is only useful because the list is the full IANA set.
  const store = read("./src/stores/settingsStore.js");
  assert.match(store, /Intl\.supportedValuesOf\("timeZone"\)/);
});
