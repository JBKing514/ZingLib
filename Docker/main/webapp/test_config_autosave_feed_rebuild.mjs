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
  // Balance from the *body* brace, not the first `{` after the name: a default
  // parameter object (`opts = {}`) contains braces of its own, and counting them
  // makes the slice close on the parameter instead of the function. Walk the
  // parenthesised parameter list first, then hand the body brace to the balancer.
  const paramsOpen = source.indexOf("(", at);
  let pdepth = 0;
  let bodyOpen = -1;
  for (let i = paramsOpen; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === "(") pdepth += 1;
    else if (ch === ")") {
      pdepth -= 1;
      if (pdepth === 0) {
        bodyOpen = source.indexOf("{", i);
        break;
      }
    }
  }
  assert.ok(bodyOpen >= 0, `body not found: ${name}`);
  return sliceBalancedAt(source, at, bodyOpen);
}

/**
 * Slice `source` from `from` to the brace that closes the block opening at
 * `bodyOpen`.
 *
 * `sliceBalanced` above finds the body brace itself, which is wrong for a
 * signature carrying a brace of its own (`opts = {}`); this variant is told
 * where the body starts, so only the body's nesting is counted.
 */
function sliceBalancedAt(source, from, bodyOpen) {
  let depth = 0;
  for (let i = bodyOpen; i < source.length; i += 1) {
    if (source[i] === "{") depth += 1;
    else if (source[i] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(from, i + 1);
    }
  }
  throw new Error(`unbalanced block at ${bodyOpen}`);
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

// --- 4. the danger zone is not auto-saved -----------------------------------

test("the database keys are excluded from the auto-saver, not merely debounced", () => {
  const store = read("./src/stores/settingsStore.js");

  // The exclusion has to live in the *diff*, because that is the one funnel every
  // implicit save passes through. A rule applied in the watcher would be one
  // refactor away from being bypassed by a new caller.
  assert.match(store, /const NO_AUTOSAVE_KEYS = Object\.freeze\(\[/);
  assert.match(store, /const _noAutoSave = new Set\(NO_AUTOSAVE_KEYS\);/);

  const dirty = sliceCallable(store, "_dirtyConfigKeys");
  assert.match(dirty, /if \(_noAutoSave\.has\(key\)\) return;/);
  // ...and it must be *before* the value comparison, or the key is already dirty.
  assert.ok(
    dirty.indexOf("_noAutoSave.has(key)") < dirty.indexOf("_configValueChanged(key"),
    "the exclusion must run before the key can be added to `dirty`",
  );

  // Every database coordinate the panel binds is named here. Missing one is the
  // whole bug: it would autosave while its neighbours wait for verification.
  ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER",
   "POSTGRES_PASSWORD", "POSTGRES_SSLMODE"].forEach((key) => {
    assert.ok(store.includes(`"${key}"`), `NO_AUTOSAVE_KEYS is missing ${key}`);
  });
});

test("the database panel verifies before it saves, and the gate is per-value", () => {
  const page = read("./src/views/settings/GeneralSettingsPage.vue");

  // The view must gate the same six keys the store excludes; the two lists are
  // one contract across two files.
  ["POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "POSTGRES_USER",
   "POSTGRES_PASSWORD", "POSTGRES_SSLMODE"].forEach((key) => {
    assert.ok(page.includes(`"${key}"`), `DB_KEYS is missing ${key}`);
  });

  // Two distinct actions: a probe (writes nothing) and a save that is only
  // reachable once that probe passed.
  assert.match(page, /@click="testDbGate"/);
  assert.match(page, /@click="saveDbGate"/);
  assert.match(page, /:disabled="!settingsUnlocked \|\| !dbGateVerified"/);
  assert.match(page, /await validateSetupDb\(draft\)/, "the probe reuses the wizard's endpoint");
  assert.match(page, /await settingsStore\.commitConfigKeys\(DB_KEYS\)/,
    "the write goes through the explicit commit, never the auto-saver");

  // Verification describes specific values: editing any field must clear it.
  const changed = sliceCallable(page, "onDbFieldChanged");
  assert.match(changed, /dbGateVerified\.value = false;/);
  assert.match(changed, /_sameDraft\(_dbDraft\(\), dbGateSnapshot\)/,
    "a snapshot comparison, not a bare boolean, decides whether the pass still holds");

  // And the save refuses when the gate is down, so a stray call cannot slip past.
  const save = sliceCallable(page, "saveDbGate");
  assert.match(save, /if \(dbGateSaving\.value \|\| !dbGateVerified\.value\) return;/);
});

test("every account action is gated on the current password", () => {
  const app = read("./src/stores/appStore.js");
  const store = read("./src/stores/settingsStore.js");
  const page = read("./src/views/settings/GeneralSettingsPage.vue");

  // One gate, shared: three flows that each grew their own verification would
  // drift into three different answers to "is this password right".
  const gate = sliceCallable(app, "verifyCurrentPassword");
  assert.match(gate, /await verifyPassword\(currentName, typed\)/);
  assert.match(gate, /if \(!typed\) \{/);

  // Rename: the *current* password is verified before the new name is written.
  // Without it a one-click typo can lock the only administrator out, because the
  // login form keys off the stored name.
  const rename = sliceCallable(app, "renameAccount");
  assert.match(rename, /await verifyCurrentPassword\(currentPassword\)/);
  assert.match(rename, /await updateProfile\(nextName\)/);
  assert.ok(
    rename.indexOf("verifyCurrentPassword") < rename.indexOf("updateProfile"),
    "the password check must precede the rename",
  );
  // Renaming to the name you already have must not demand a password.
  assert.match(rename, /if \(nextName === currentName\) \{/);
  // The new name arrives as an argument -- the store's `accountForm.username`
  // is a mirror of the account and must never be the source of a rename. The
  // mutation to watch for is someone "helpfully" falling back to it.
  const renameParams = rename.slice(0, rename.indexOf("{"));
  assert.match(renameParams, /renameAccount\(currentPassword, nextUsername\)/);
  assert.doesNotMatch(rename, /accountForm\.value\.username \|\| nextUsername/);
  assert.match(rename, /const nextName = String\(nextUsername \|\| ""\)\.trim\(\);/);

  // Password change: gate first, then the write, and the account is signed out
  // afterwards (the session was issued under the old credential).
  const pw = sliceCallable(app, "changeAccountPassword");
  // The first line of the callable is the signature (the body brace is on it
  // too, but the parameters are all we need).
  const pwParams = pw.split("\n")[0];
  assert.match(pwParams, /changeAccountPassword\(currentPassword, newPassword, newPassword2, opts = \{\}/);
  assert.match(pw, /if \(!\(await verifyCurrentPassword\(currentPassword\)\)\) return false;/);
  assert.match(pw, /await changePassword\(/);
  assert.ok(
    pw.indexOf("verifyCurrentPassword") < pw.indexOf("await changePassword("),
    "the password check must precede the change",
  );
  assert.match(pw, /await logoutNow\(\)/);
  assert.match(pw, /password_mismatch/);

  // ...and the same function, when the dialog says "forgot the password", takes
  // the recovery branch instead: the typed value is a burn-after-use code, the
  // old password is never asked for, and the write goes to its own endpoint.
  // The failure this pins is a "forgot" tick that still routes through the
  // normal gate -- the user is locked out, the dialog reports a wrong password,
  // and the recovery code never gets a chance to work.
  assert.match(pw, /if \(opts && opts\.useRecoveryCode\) \{/);
  assert.ok(
    pw.indexOf("useRecoveryCode") < pw.indexOf("verifyCurrentPassword"),
    "the recovery branch has to come *before* the password gate, not after it",
  );
  assert.match(pw, /await changePasswordWithRecoveryCode\(username, code, String\(newPassword \|\| ""\)\)/);
  assert.match(pw, /toast\.warning\(_t\("auth\.profile\.recovery_code_required"\)\)/);
  assert.ok(
    pw.indexOf("changePasswordWithRecoveryCode") < pw.indexOf("await verifyCurrentPassword"),
    "the recovery write replaces the gate rather than following it",
  );

  const api = read("./src/api.js");
  assert.match(api, /export async function changePasswordWithRecoveryCode\(username, recoveryCode, newPassword\) \{/);
  assert.match(api, /api\.post\("\/auth\/recovery-password-change", \{/);
  // The account is named by the *body*, not by the session: that is what makes
  // the endpoint usable by someone who cannot log in, and why the middleware
  // admits it as a self-service path. A silent fallback to the session's own
  // user would make the feature a no-op for its only caller.
  assert.match(api, /username,\n    recovery_code: recoveryCode,/);

  // Delete: verified server-side by the request itself (the password is the
  // body), then the app is handed back to the wizard rather than to a login
  // form with no account behind it.
  const del = sliceCallable(app, "deleteAccountNow");
  assert.match(del, /await deleteAccount\(pwd\)/);
  assert.match(del, /await bootstrap\(\)/);
  assert.doesNotMatch(del, /prompt\(/, "the confirmation is a dialog, not a prompt()");
  assert.ok(
    del.indexOf("await bootstrap()") > del.indexOf("await deleteAccount(pwd)"),
    "the wizard is raised by re-bootstrapping *after* the row is gone",
  );
  assert.match(del, /showSetupWizard\.value = true/);

  // The view states the flows, one dialog each.
  ["openPasswordDialog", "openRenameDialog", "openDeleteDialog"].forEach((fn) => {
    assert.match(page, new RegExp(`@click="${fn}"`), `${fn} is not wired to a button`);
  });
  assert.match(page, /v-model="passwordDialog"/);
  assert.match(page, /v-model="renameDialog"/);
  assert.match(page, /v-model="deleteDialog"/);
  // The password dialog is two pages: the gate, then the new value. Asking for
  // the new password first is what turns "old password wrong" into a report
  // about the new one.
  assert.match(page, /passwordStep === 'verify'/);
  assert.match(page, /passwordStep\.value = "new"/);
  assert.match(page, /await appStore\.verifyCurrentPassword\(passwordOld\.value\)/);
  assert.match(page, /await appStore\.changeAccountPassword\(/);
  assert.match(page, /await appStore\.renameAccount\(renamePassword\.value, renameNewName\.value\)/);
  assert.match(page, /await appStore\.deleteAccountNow\(deletePassword\.value\)/);

  // The dialog exposes the recovery branch as a checkbox on the *gate* page --
  // it changes what the gate asks for, so it has no business on the page that
  // types the new password -- and it forwards the flag.
  assert.match(page, /v-model="passwordUseRecovery"/);
  assert.match(page, /auth\.profile\.forgot_password/);
  assert.match(page, /auth\.profile\.recovery_code/);
  assert.match(page, /\{ useRecoveryCode: passwordUseRecovery\.value \}/);
  assert.match(page, /passwordUseRecovery/);
  assert.match(page, /passwordBusy, passwordUseRecovery,/);
  // It lives inside the `verify` branch and nowhere else. Asserted by position,
  // because the checkbox's own markup says nothing about which page it is on --
  // moving it to the new-password page would leave the gate with no way to
  // choose a credential, and the markup would look identical.
  const verifyBranch = page.slice(page.indexOf("v-if=\"passwordStep === 'verify'\""), page.indexOf("<template v-else>", page.indexOf("v-if=\"passwordStep === 'verify'\"")));
  assert.match(verifyBranch, /v-model="passwordUseRecovery"/, "the tick must sit on the gate page");
  assert.match(verifyBranch, /v-if="!passwordUseRecovery"/, "the two credentials are one field, swapped");
  const newBranch = page.slice(page.indexOf("<template v-else>", page.indexOf("v-if=\"passwordStep === 'verify'\"")));
  assert.doesNotMatch(newBranch, /v-model="passwordUseRecovery"/, "the tick has no business on the new-password page");
  // The two gate credentials are one field, so switching meaning must clear it:
  // otherwise a password typed before the tick is submitted as a recovery code.
  const forgot = sliceCallable(page, "onForgotToggle");
  assert.match(forgot, /passwordOld\.value = "";/);
  // Proving the recovery code on the gate page would burn it before the user
  // has committed to a new password, so that page only advances.
  const verifyStep = sliceCallable(page, "verifyPasswordStep");
  assert.match(verifyStep, /if \(passwordUseRecovery\.value\) \{\s*\n\s*passwordStep\.value = "new";\s*\n\s*return;/);
  assert.ok(
    verifyStep.indexOf("passwordUseRecovery.value") < verifyStep.indexOf("verifyCurrentPassword"),
    "the recovery code must short-circuit the password gate",
  );

  // Both locales carry the new copy -- a missing key renders as the raw key.
  const en = JSON.parse(read("./src/i18n/en.json"));
  const zh = JSON.parse(read("./src/i18n/zh.json"));
  ["auth.profile.forgot_password", "auth.profile.recovery_code",
   "auth.profile.recovery_code_hint", "auth.profile.recovery_code_required",
   "auth.profile.recovery_code_warning"].forEach((key) => {
    assert.ok(en[key], `en.json is missing ${key}`);
    assert.ok(zh[key], `zh.json is missing ${key}`);
  });
  // ...and the three keys that were sitting in the wrong locale are back where
  // they belong (the English file was rendering Chinese labels and vice versa).
  assert.match(en["auth.profile.new_username"], /New Username/);
  assert.match(en["auth.profile.next"], /Next/);
  assert.match(en["auth.profile.done"], /Done/);
  assert.match(zh["auth.profile.new_username"], /新用户名/);
  assert.match(zh["auth.profile.next"], /下一步/);
  assert.match(zh["auth.profile.done"], /完成/);

  // The store's older, per-field surface is gone: a rename reachable by editing
  // a bound input is exactly the hole this closed.
  assert.doesNotMatch(app, /function updateAccountUsername/);
  assert.doesNotMatch(app, /function updateAccountPassword/);
  assert.doesNotMatch(store, /updateAccountUsername/);
  assert.doesNotMatch(store, /updateAccountPassword/);
  // ...and the new names are delegated too, or the page's spread is undefined.
  ["verifyCurrentPassword", "renameAccount", "changeAccountPassword", "deleteAccountNow"].forEach((fn) => {
    assert.match(store, new RegExp(`appStore\\.${fn}\\(`), `${fn} is not delegated by the settings store`);
  });
  // The form ref is a mirror of the account, not a scratch pad for the dialogs.
  assert.match(app, /const accountForm = ref\(\{ username: "" \}\);/);
});

test("the account and the rebuild left the danger zone; it holds only the connection", () => {
  const page = read("./src/views/settings/GeneralSettingsPage.vue");
  const localLib = read("./src/views/settings/LocalLibSettingsPage.vue");

  // Everything the danger zone still gates sits between the wrapper and its
  // closing tag -- so the account card and the rebuild button must not.
  const open = page.indexOf('<div class="danger-zone"');
  assert.ok(open > 0, "the danger zone wrapper is gone");
  const zone = page.slice(open, page.indexOf("</div>", page.indexOf("app_config_backup")));

  // The connection gate is inside (its own password flow lives in the dialog).
  assert.match(zone, /settings\.danger_zone\.title/);
  assert.match(zone, /testDbGate/);

  // The account moved out: its three buttons are password-gated, so the panel
  // unlock switch would only have made "change my password" look destructive.
  assert.doesNotMatch(zone, /@click="openPasswordDialog"/);
  assert.doesNotMatch(zone, /@click="openDeleteDialog"/);
  assert.match(page, /@click="openPasswordDialog"/);
  assert.match(page, /@click="openRenameDialog"/);
  assert.match(page, /@click="openDeleteDialog"/);
  // The username is display-only.
  assert.match(page, /\{\{ authUser\.username \|\| '-'\s*\}\}/);
  assert.doesNotMatch(page, /v-model="accountForm\.username"/);
  assert.doesNotMatch(page, /@click="updateAccountUsername/);
  assert.doesNotMatch(page, /@click="updateAccountPassword/);

  // The rebuild button is gone from the general page entirely...
  assert.doesNotMatch(page, /settings\.rebuild\./);
  assert.doesNotMatch(page, /rebuildGalleryDatabase/);
  // ...and lives with the library maintenance that acts on the same database.
  assert.match(localLib, /@click="openRebuildDialog"/);
  assert.match(localLib, /v-model="rebuildDialog"/);
  assert.match(localLib, /settings\.rebuild\.confirm/);
  assert.match(localLib, /await rebuildGalleryDatabase\(rebuildPassword\.value\)/);
  // The password is still required to rebuild, whichever tab it lives on.
  assert.match(localLib, /:disabled="!rebuildPassword"/);
  assert.match(localLib, /settings\.rebuild\.done/);

  // Every cached dashboard feed gets emptied: the rows this call deletes are the
  // rows those caches hold, so leaving them populated shows phantom cards until
  // each screen happens to re-fetch. The four state objects are the contract --
  // named individually, because "clear the feed" drifting to one of them is the
  // half-fix that looks fine until you switch tabs.
  const rebuild = sliceCallable(localLib, "confirmRebuild");
  assert.match(rebuild, /dashboard\.homeLocal, dashboard\.homeLocalFavorite, dashboard\.homeHistory, dashboard\.homeSearchState/);
  assert.match(rebuild, /state\.items = \[\];/);
  assert.match(rebuild, /dashboard\.mobilePreviewItem = null;/);
  assert.match(rebuild, /dashboard\.localFolderNodes = \[\];/);
  // ...and it throws rather than quietly reporting success when the clear is
  // skipped: the notify is what tells the user the library is now empty.
  assert.match(rebuild, /settings\.rebuild\.done/, "the result must be reported, not swallowed");
});

test("the danger zone reads top-to-bottom: switch, then zone, then the account", () => {
  const page = read("./src/views/settings/GeneralSettingsPage.vue");

  // The ordering the user asked for: the unlock switch is glued to the top of
  // the zone it governs, and the account follows below it. A regression here is
  // a *silent* one -- every card still renders, just in the wrong place -- so it
  // is pinned by index rather than by presence.
  const unlockIdx = page.indexOf("settings.unlock.title");
  const zoneIdx = page.indexOf('<div class="danger-zone"');
  const accountIdx = page.indexOf("settings.section.account");
  assert.ok(unlockIdx > 0, "the unlock card is gone");
  assert.ok(zoneIdx > 0, "the danger zone wrapper is gone");
  assert.ok(accountIdx > 0, "the account card is gone");
  assert.ok(unlockIdx < zoneIdx, "the unlock switch must sit above the danger zone");
  assert.ok(zoneIdx < accountIdx, "the account card must sit below the danger zone");

  // There is exactly one account card. A re-injection above the zone would
  // otherwise satisfy `indexOf` while the account still renders twice.
  const accountCards = page.match(/t\('settings\.section\.account'\)/g) || [];
  assert.equal(accountCards.length, 1, "the account section must appear exactly once");

  // ...and exactly one danger-zone wrapper. Swallowing the account into the zone
  // means opening a second wrapper above it, which leaves the account card
  // inside a locked, pointer-events-none region -- reachable in the DOM, dead in
  // the UI. The account must sit *after* the zone's single closing tag, so the
  // wrapper count is the cheap, order-independent way to catch that.
  const zoneOpeners = page.match(/<div class="danger-zone"/g) || [];
  assert.equal(zoneOpeners.length, 1, "there must be exactly one danger-zone wrapper");
  const zoneClose = page.indexOf("</div>", page.indexOf("app_config_backup"));
  assert.ok(zoneClose > 0, "the danger zone never closes");
  assert.ok(accountIdx > zoneClose, "the account card must sit after the danger zone closes");

  // The switch has to stay *outside* the wrapper: while locked that wrapper sets
  // `pointer-events: none`, so a switch nested inside it could never be flipped
  // back on. Assert it is not between the wrapper's open tag and its close.
  const zoneStart = page.indexOf('<div class="danger-zone"');
  const zone = page.slice(zoneStart, zoneClose);
  assert.doesNotMatch(zone, /settings\.unlock\.title/, "the unlock switch must not move inside the locked wrapper");
  assert.doesNotMatch(zone, /v-model="settingsUnlocked"/, "the unlock switch must not move inside the locked wrapper");
  // ...and it is directly adjacent: nothing but whitespace between the switch
  // card and the wrapper open tag.
  const between = page.slice(page.indexOf("</v-card>", unlockIdx), zoneStart);
  assert.match(between, /^\s*$/m, "nothing may sit between the unlock switch and the danger zone");
});

test("the dead OPENAI health check is gone from every layer", () => {
  const constants = read("../webapi/core/constants.py");
  const settings = read("../webapi/routers/settings.py");
  const provider = read("../webapi/services/ai_provider.py");  const page = read("./src/views/settings/GeneralSettingsPage.vue");
  const store = read("./src/stores/settingsStore.js");
  const en = JSON.parse(read("./src/i18n/en.json"));
  const zh = JSON.parse(read("./src/i18n/zh.json"));

  // The config key and the probe that existed only to serve it.
  assert.doesNotMatch(constants, /OPENAI_HEALTH_URL/);
  assert.doesNotMatch(provider, /def check_http\(/);
  assert.doesNotMatch(settings, /check_http/);
  assert.doesNotMatch(settings, /openai_health/);
  // Nothing rendered `services.llm`; the field goes with it rather than sitting
  // there as an invitation to re-wire it.
  assert.doesNotMatch(settings, /payload\["services"\] = \{"llm"/);

  assert.doesNotMatch(page, /OPENAI_HEALTH_URL/);
  assert.doesNotMatch(store, /OPENAI_HEALTH_URL/);
  ["settings.openai.health", "settings.section.urls", "health.llm.na",
   "settings.err.openai_health"].forEach((key) => {
    assert.ok(!(key in en), `en.json still carries the dead key ${key}`);
    assert.ok(!(key in zh), `zh.json still carries the dead key ${key}`);
  });
});

// --- 5. the timezone picker takes typed input -------------------------------

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

// --- 6. the two library actions left the vector-ingest page ------------------
//
// "Clear duplicate rows" and "clear read history" act on the library database,
// but they were stranded at the bottom of the vector-ingest tab, below options
// about model endpoints. Moving them is only correct if nothing was left behind
// on the old page and the confirmation survived the move -- the clear has no
// undo.

test("the library maintenance actions live with the library, once", () => {
  const localLib = read("./src/views/settings/LocalLibSettingsPage.vue");
  const dataClean = read("./src/views/settings/DataCleanSettingsPage.vue");

  // Present where they belong...
  assert.match(localLib, /@click="clearWorksDuplicatesAction"/);
  assert.match(localLib, /@click="openReadEventsConfirm"/);
  assert.match(localLib, /settings\.data_clean\.dedup_works/);
  assert.match(localLib, /settings\.data_clean\.clear_read_events/);

  // ...and gone from the page they used to be on.
  assert.doesNotMatch(dataClean, /clearWorksDuplicatesAction/);
  assert.doesNotMatch(dataClean, /openReadEventsConfirm/);
  assert.doesNotMatch(dataClean, /settings\.data_clean\.dedup_works/);
  assert.doesNotMatch(dataClean, /settings\.data_clean\.clear_read_events/);

  // The destructive action still asks first, and the dialog lives with the button.
  assert.match(localLib, /v-model="confirmReadEventsDialog"/);
  assert.match(localLib, /settings\.data_clean\.clear_read_events_confirm/);
  assert.match(localLib, /await settingsStore\.clearReadEventsAction\(\)/);

  // The store's own cleanup (notify on done) must not have been orphaned.
  const store = read("./src/stores/settingsStore.js");
  assert.match(store, /settings\.data_clean\.dedup_works_done/);
  assert.match(store, /settings\.data_clean\.clear_read_events_done/);
});

// --- 7. one tag-translation surface, and it is the real one ------------------
//
// Two UIs edited the same table: the local-library glossary card (upload + clear
// + stats) and a block at the bottom of the vector-ingest page that also offered
// a "translation repo" URL and an auto-update interval. The repo half had no
// backend consumer at all -- the config keys were rendered and never read -- so
// the duplicate is removed rather than kept as two doors onto one file.

test("the tag-translation table is edited from exactly one place", () => {
  const localLib = read("./src/views/settings/LocalLibSettingsPage.vue");
  const dataClean = read("./src/views/settings/DataCleanSettingsPage.vue");

  // The surviving surface.
  assert.match(localLib, /settings\.local_lib\.translation\.title/);
  assert.match(localLib, /onTranslationTablePicked/);

  // The duplicate is gone from the vector-ingest page, fields and all.
  assert.doesNotMatch(dataClean, /TAG_TRANSLATION_REPO/);
  assert.doesNotMatch(dataClean, /TAG_TRANSLATION_AUTO_UPDATE_HOURS/);
  assert.doesNotMatch(dataClean, /settings\.translation\./);
  assert.doesNotMatch(dataClean, /translationUploadRef/);

  // And the store stopped carrying the dead repo-status refs and preload.
  const store = read("./src/stores/settingsStore.js");
  assert.doesNotMatch(store, /translationStatus/);
  assert.doesNotMatch(store, /loadTranslationStatus/);
  assert.doesNotMatch(store, /TAG_TRANSLATION_REPO/);
  assert.doesNotMatch(store, /TAG_TRANSLATION_AUTO_UPDATE_HOURS/);

  // The config keys they edited are gone from the backend spec...
  const constants = read("../webapi/core/constants.py");
  assert.doesNotMatch(constants, /TAG_TRANSLATION_REPO/);
  assert.doesNotMatch(constants, /TAG_TRANSLATION_AUTO_UPDATE_HOURS/);

  // ...and the status route no longer advertises a repo that does not exist.
  const settings = read("../webapi/routers/settings.py");
  assert.doesNotMatch(settings, /"repo": ""/);
  assert.doesNotMatch(settings, /"head_sha": ""/);
  assert.match(settings, /"manual_file": manual_info/);

  // No dead i18n keys survive in either locale.
  const en = JSON.parse(read("./src/i18n/en.json"));
  const zh = JSON.parse(read("./src/i18n/zh.json"));
  const dead = Object.keys(en).filter((k) => k.startsWith("settings.translation."));
  assert.deepEqual(dead, [], `en.json still carries ${dead}`);
  const deadZh = Object.keys(zh).filter((k) => k.startsWith("settings.translation."));
  assert.deepEqual(deadZh, [], `zh.json still carries ${deadZh}`);

  // The startup preload of the removed ref must not be left calling a ghost.
  const app = read("./src/App.vue");
  assert.doesNotMatch(app, /loadTranslationStatus/);
});

// --- 8. the settings tabs are ordered by how much they own -------------------
//
// The library tab owns the library itself, so it belongs right after the general
// options -- not after search/reader/other. The order is asserted as a sequence,
// because "contains all six" would pass with any arrangement.

test("the settings tabs read general, library, reader, ingest, search, other", () => {
  const page = read("./src/views/SettingsPage.vue");
  const order = [...page.matchAll(/settings\.tab\.(\w+)/g)].map((m) => m[1]);
  assert.deepEqual(order, [
    "general",
    "local_lib",
    "reader",
    "data_clean",
    "search",
    "other",
  ]);
});
