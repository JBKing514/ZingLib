import {
  buildEffectiveCategoryDefs,
  getCategoryColor,
  getCategoryDisplayLabel,
  getPinnedCategoryDefs,
  normalizeCategoryKey,
  parseCustomCategoryConfig,
  parsePinnedCategoryKeys,
  stringifyPinnedCategoryKeys,
  stringifyCustomCategoryConfig,
} from "./src/utils/categoryPresets.js";

function assertTrue(condition, message) {
  if (!condition) throw new Error(message);
}

function main() {
  console.log("========================================================================");
  console.log("Phase 6.3 custom category frontend regression");
  console.log("========================================================================");

  const customDefs = parseCustomCategoryConfig([
    { label: "Light Novel", color: "#22c55e", pinned: true },
    { label: "Art Book", color: "#2563eb", pinned: false },
  ]);

  console.log("[1] custom categories are normalized and preserved");
  assertTrue(customDefs.length === 2, "expected two custom category presets");
  assertTrue(customDefs[0].key === "light novel", "light novel key normalization failed");

  console.log("[2] effective categories include builtin + custom");
  const pinnedKeys = parsePinnedCategoryKeys(["manga", "light novel"], customDefs);
  const allDefs = buildEffectiveCategoryDefs(customDefs, pinnedKeys);
  assertTrue(allDefs.some((row) => row.key === "light novel"), "custom category missing from effective definitions");

  console.log("[3] pinned category list respects explicit key selection");
  const pinnedDefs = getPinnedCategoryDefs(customDefs, pinnedKeys);
  assertTrue(pinnedDefs.some((row) => row.key === "light novel"), "pinned custom category missing");
  assertTrue(pinnedDefs.some((row) => row.key === "manga"), "pinned builtin category missing");
  assertTrue(!pinnedDefs.some((row) => row.key === "art book"), "unpinned custom category should not appear in pinned list");

  console.log("[4] display label and color helpers");
  assertTrue(getCategoryDisplayLabel("light novel", customDefs) === "Light Novel", "custom category display label mismatch");
  assertTrue(getCategoryColor("light novel", customDefs) === "#22c55e", "custom category color mismatch");

  console.log("[5] config stringify round-trip");
  const roundTrip = parseCustomCategoryConfig(stringifyCustomCategoryConfig(customDefs));
  assertTrue(roundTrip.length === 2, "round-trip category config lost rows");
  const pinnedRoundTrip = parsePinnedCategoryKeys(stringifyPinnedCategoryKeys(pinnedKeys, customDefs), customDefs);
  assertTrue(pinnedRoundTrip.includes("light novel"), "pinned key round-trip lost custom key");
  assertTrue(normalizeCategoryKey("  LIGHT   NOVEL ") === "light novel", "category key normalization mismatch");

  console.log("[OK] Phase 6.3 custom category frontend regression passed");
}

try {
  main();
} catch (error) {
  console.error("[FAIL]", error?.message || error);
  process.exitCode = 1;
}
