export const DEFAULT_CATEGORY_COLOR = "#475569";

// `key` is the identity: it is what gets stored, compared against ComicInfo
// genres and written to the database, so it must never change. Built-in rows
// carry a literal English `label` and are intentionally NOT translated: these
// categories mirror the app's ten-category ComicInfo vocabulary (Doujinshi,
// Manga, Image Set, ...) and stay verbatim in every UI language. Custom rows keep the
// user-entered label as-is.
export const BUILTIN_LOCAL_CATEGORY_DEFS = [
  { key: "doujinshi", label: "Doujinshi", color: "#ff5252", pinned: true, builtin: true, order: 0 },
  { key: "manga", label: "Manga", color: "#fdb813", pinned: true, builtin: true, order: 1 },
  { key: "image set", label: "Image Set", color: "#4f54d1", pinned: true, builtin: true, order: 2 },
  { key: "game cg", label: "Game CG", color: "#00c700", pinned: true, builtin: true, order: 3 },
  { key: "artist cg", label: "Artist CG", color: "#d7e600", pinned: true, builtin: true, order: 4 },
  { key: "cosplay", label: "Cosplay", color: "#8756e6", pinned: true, builtin: true, order: 5 },
  { key: "non-h", label: "Non-H", color: "#66bcd3", pinned: true, builtin: true, order: 6 },
  { key: "asian porn", label: "Asian Porn", color: "#de7de5", pinned: true, builtin: true, order: 7 },
  { key: "western", label: "Western", color: "#18e61f", pinned: true, builtin: true, order: 8 },
  { key: "misc", label: "Misc", color: "#473f3f", pinned: true, builtin: true, order: 9 },
];

/**
 * Resolve the label to render for a category definition.
 *
 * Built-in categories render their literal English label verbatim. Only custom
 * rows may carry a `labelKey`, which is resolved through the translator when one
 * is available. Falls back to the literal label (and then the key).
 */
export function getCategoryLabel(def, t) {
  if (!def) return "";
  if (def.builtin === true) return String(def.label || def.key || "");
  const labelKey = String(def.labelKey || "").trim();
  if (labelKey && typeof t === "function") {
    const text = t(labelKey);
    if (text && text !== labelKey) return String(text);
  }
  return String(def.label || def.key || "");
}

export const BUILTIN_LOCAL_CATEGORY_MAP = Object.fromEntries(BUILTIN_LOCAL_CATEGORY_DEFS.map((it) => [it.key, it]));
export const DEFAULT_PINNED_CATEGORY_KEYS = BUILTIN_LOCAL_CATEGORY_DEFS.slice(0, 10).map((it) => it.key);

export function normalizeCategoryKey(raw) {
  return String(raw || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export function normalizeCategoryColor(raw, fallback = DEFAULT_CATEGORY_COLOR) {
  const text = String(raw || "").trim();
  return /^#([0-9a-fA-F]{6})$/.test(text) ? text.toLowerCase() : String(fallback || DEFAULT_CATEGORY_COLOR).toLowerCase();
}

function toDisplayLabel(raw, fallbackKey) {
  const text = String(raw || "").trim().replace(/\s+/g, " ");
  if (text) return text;
  const key = String(fallbackKey || "").trim();
  if (!key) return "";
  return key.split(" ").map((part) => part ? part[0].toUpperCase() + part.slice(1) : "").join(" ");
}

export function parseCustomCategoryConfig(raw) {
  let parsed = [];
  try {
    const value = typeof raw === "string" ? JSON.parse(raw || "[]") : raw;
    parsed = Array.isArray(value) ? value : [];
  } catch {
    parsed = [];
  }
  const out = [];
  const seen = new Set();
  for (const row of parsed) {
    const key = normalizeCategoryKey(row?.key || row?.name || row?.label || "");
    if (!key || seen.has(key) || BUILTIN_LOCAL_CATEGORY_MAP[key]) continue;
    seen.add(key);
    out.push({
      key,
      label: toDisplayLabel(row?.label || row?.name || "", key),
      color: normalizeCategoryColor(row?.color),
      pinned: row?.pinned !== false,
      order: Number.isFinite(Number(row?.order)) ? Number(row.order) : out.length,
      builtin: false,
    });
  }
  return out.sort((a, b) => {
    const ao = Number(a?.order || 0);
    const bo = Number(b?.order || 0);
    if (ao !== bo) return ao - bo;
    return String(a?.label || a?.key || "").localeCompare(String(b?.label || b?.key || ""));
  });
}

export function stringifyCustomCategoryConfig(rows = []) {
  return JSON.stringify(parseCustomCategoryConfig(rows));
}

export function parsePinnedCategoryKeys(raw, customRows = [], maxPinned = 10) {
  let parsed = [];
  try {
    const value = typeof raw === "string" ? JSON.parse(raw || "[]") : raw;
    parsed = Array.isArray(value) ? value : [];
  } catch {
    parsed = [];
  }
  const knownKeys = new Set([
    ...BUILTIN_LOCAL_CATEGORY_DEFS.map((it) => it.key),
    ...parseCustomCategoryConfig(customRows).map((it) => it.key),
  ]);
  const out = [];
  const seen = new Set();
  for (const row of parsed) {
    const key = normalizeCategoryKey(row);
    if (!key || seen.has(key) || !knownKeys.has(key)) continue;
    seen.add(key);
    out.push(key);
    if (out.length >= maxPinned) break;
  }
  if (out.length) return out;
  return DEFAULT_PINNED_CATEGORY_KEYS.slice(0, maxPinned);
}

export function stringifyPinnedCategoryKeys(raw, customRows = [], maxPinned = 10) {
  return JSON.stringify(parsePinnedCategoryKeys(raw, customRows, maxPinned));
}

export function buildEffectiveCategoryDefs(customRows = [], pinnedKeysRaw = []) {
  const custom = parseCustomCategoryConfig(customRows);
  const pinnedSet = new Set(parsePinnedCategoryKeys(pinnedKeysRaw, custom));
  return [
    ...BUILTIN_LOCAL_CATEGORY_DEFS.map((it, index) => ({ ...it, pinned: pinnedSet.has(it.key), order: index })),
    ...custom.map((it, index) => ({ ...it, pinned: pinnedSet.has(it.key), order: BUILTIN_LOCAL_CATEGORY_DEFS.length + index })),
  ];
}

export function getPinnedCategoryDefs(customRows = [], pinnedKeysRaw = [], maxPinned = 10) {
  const pinnedSet = new Set(parsePinnedCategoryKeys(pinnedKeysRaw, customRows, maxPinned));
  return buildEffectiveCategoryDefs(customRows, pinnedKeysRaw).filter((it) => pinnedSet.has(it.key));
}

export function findCategoryDef(rawCategory, customRows = [], pinnedKeysRaw = []) {
  const key = normalizeCategoryKey(rawCategory);
  if (!key) return null;
  return buildEffectiveCategoryDefs(customRows, pinnedKeysRaw).find((it) => it.key === key) || null;
}

export function getCategoryDisplayLabel(rawCategory, customRows = [], pinnedKeysRaw = []) {
  const def = findCategoryDef(rawCategory, customRows, pinnedKeysRaw);
  if (def?.label) return def.label;
  return normalizeCategoryKey(rawCategory);
}

export function getCategoryColor(rawCategory, customRows = [], pinnedKeysRaw = [], fallback = DEFAULT_CATEGORY_COLOR) {
  const def = findCategoryDef(rawCategory, customRows, pinnedKeysRaw);
  if (def?.color) return normalizeCategoryColor(def.color, fallback);
  return normalizeCategoryColor(fallback);
}
