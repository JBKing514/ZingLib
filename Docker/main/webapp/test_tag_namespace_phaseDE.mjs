import {
  extractNamespaceSeed,
  getNamespaceColor,
  getNamespaceDisplayLabel,
  isManagedNamespace,
  normalizeUserTagInput,
  parseCustomNamespaceConfig,
  stripUserTagMarker,
  tagSuggestLabels,
} from "./src/utils/tagNamespaces.js";

function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function main() {
  console.log("========================================================================");
  console.log("Phase DE tag namespace frontend regression");
  console.log("========================================================================");

  const customDefs = parseCustomNamespaceConfig([
    { key: "studio", color: "#22c55e" },
    { key: "author_note", color: "#2563eb" },
  ]);

  console.log("[1] a hand-picked tag keeps its namespace, with no marker in front");
  assertTrue(
    normalizeUserTagInput("studio:line art", { fallbackNs: "other" }) === "studio:line art",
    "custom namespace should be preserved without a `user:` marker",
  );

  console.log("[2] builtin alias still normalizes");
  assertTrue(
    normalizeUserTagInput("男性:test", { fallbackNs: "other" }) === "male:test",
    "builtin alias should still normalize to male",
  );

  console.log("[2b] a bare label takes the namespace the picker chose");
  assertTrue(
    normalizeUserTagInput("巨乳", { fallbackNs: "female" }) === "female:巨乳",
    "the caller's namespace must be applied, and it must not be `user:`",
  );
  assertTrue(
    normalizeUserTagInput("女性:巨乳", { fallbackNs: "other" }) === "female:巨乳",
    "an alias prefix collapses to the builtin key",
  );

  console.log("[2c] legacy input is accepted, but never re-emitted");
  assertTrue(
    normalizeUserTagInput("user:studio:line art", { fallbackNs: "other" }) === "studio:line art",
    "a pre-marker value must fold to the marker-less shape",
  );
  assertTrue(
    !normalizeUserTagInput("studio:line art", { fallbackNs: "other" }).startsWith("user:"),
    "nothing the normalizer returns may start with `user:`",
  );

  console.log("[2d] the retired marker is stripped on display, native tags untouched");
  assertTrue(stripUserTagMarker("user:female:x") === "female:x", "legacy marker should be stripped");
  assertTrue(stripUserTagMarker("female:x") === "female:x", "a clean tag must pass through untouched");
  assertTrue(
    stripUserTagMarker("source_tag") === "source_tag",
    "a native namespace-less tag must not gain one just by being shown",
  );

  console.log("[3] custom namespace display label and color");
  assertTrue(getNamespaceDisplayLabel("studio", null, customDefs) === "studio", "custom namespace label should use raw key");
  assertTrue(getNamespaceColor("studio", customDefs) === "#22c55e", "custom namespace color should come from config");

  console.log("[4] fallback color for unmanaged namespace");
  assertTrue(getNamespaceColor("unknown_ns", []) === "#6b7280", "unmanaged namespace should fall back to gray");

  console.log("[5] namespace seed extraction and managed detection");
  assertTrue(extractNamespaceSeed("author_note:todo") === "author_note", "namespace seed extraction failed");
  assertTrue(isManagedNamespace("author_note", customDefs) === true, "custom namespace should be treated as managed");
  assertTrue(isManagedNamespace("brand_new", customDefs) === false, "unknown namespace should not be treated as managed");

  console.log("[6] suggestions keep cross-namespace hits (the empty-list regression)");
  assertTrue(
    JSON.stringify(tagSuggestLabels(["女性:巨乳", "男性:筋肉"], "other")) === JSON.stringify(["female:巨乳", "male:筋肉"]),
    "with `other` picked, a hit from another namespace must survive as `ns:value`, not be dropped",
  );
  assertTrue(
    JSON.stringify(tagSuggestLabels(["女性:巨乳", "男性:筋肉"], "female")) === JSON.stringify(["巨乳", "male:筋肉"]),
    "same-namespace hits show the bare value; foreign ones keep their prefix",
  );
  assertTrue(
    JSON.stringify(tagSuggestLabels(["user:female:x", "source_tag"], "other")) === JSON.stringify(["female:x", "source_tag"]),
    "legacy `user:` markers are stripped and prefix-less tags pass through",
  );
  assertTrue(
    JSON.stringify(tagSuggestLabels(["女性:巨乳", "female:巨乳"], "other")) === JSON.stringify(["female:巨乳"]),
    "an alias and its builtin key are the same namespace, so duplicates collapse",
  );

  console.log("[7] a cross-namespace suggestion commits under its own namespace");
  assertTrue(
    normalizeUserTagInput("male:筋肉", { fallbackNs: "other" }) === "male:筋肉",
    "the commit path must not re-prefix a label that already carries a namespace",
  );
  assertTrue(
    normalizeUserTagInput("巨乳", { fallbackNs: "other" }) === "other:巨乳",
    "a bare value still takes the picked namespace as fallback",
  );

  console.log("[OK] Phase DE tag namespace frontend regression passed");
}

try {
  main();
} catch (error) {
  console.error("[FAIL]", error?.message || error);
  process.exitCode = 1;
}
