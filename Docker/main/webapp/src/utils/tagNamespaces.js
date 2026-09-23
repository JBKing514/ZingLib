const NS_ALIAS = {
  female: "female",
  "\u5973\u6027": "female",
  male: "male",
  "\u7537\u6027": "male",
  mixed: "mixed",
  language: "language",
  "\u8bed\u8a00": "language",
  parody: "parody",
  "\u539f\u4f5c": "parody",
  character: "character",
  "\u89d2\u8272": "character",
  artist: "artist",
  "\u4f5c\u8005": "artist",
  "\u827a\u672f\u5bb6": "artist",
  group: "group",
  "\u56e2\u961f": "group",
  reclass: "reclass",
  category: "reclass",
  "\u5206\u7c7b": "reclass",
  user: "user",
  uploader: "uploader",
  "\u4e0a\u4f20\u8005": "uploader",
  source: "source",
  "\u6765\u6e90": "source",
  date: "date",
  posted: "date",
  timestamp: "date",
  date_added: "date",
  dateadded: "date",
  other: "other",
  "\u5176\u4ed6": "other",
  misc: "misc",
  "\u6742\u9879": "misc",
};

export const DEFAULT_NAMESPACE_COLOR = "#6b7280";
export const BUILTIN_NAMESPACE_DEFS = [
  { key: "female", labelKey: "home.tag_ns.female", color: "#d946ef" },
  { key: "male", labelKey: "home.tag_ns.male", color: "#3b82f6" },
  { key: "mixed", labelKey: "home.tag_ns.mixed", color: "#8b5cf6" },
  { key: "language", labelKey: "home.tag_ns.language", color: "#0ea5e9" },
  { key: "parody", labelKey: "home.tag_ns.parody", color: "#fb7185" },
  { key: "character", labelKey: "home.tag_ns.character", color: "#6366f1" },
  { key: "artist", labelKey: "home.tag_ns.artist", color: "#10b981" },
  { key: "group", labelKey: "home.tag_ns.group", color: "#8b5cf6" },
  { key: "reclass", labelKey: "home.tag_ns.reclass", color: "#f59e0b" },
  { key: "other", labelKey: "home.tag_ns.other", color: "#6b7280" },
  { key: "cosplayer", labelKey: "home.tag_ns.cosplayer", color: "#14b8a6" },
  { key: "rest", labelKey: "home.tag_ns.rest", color: "#64748b" },
];
export const BUILTIN_NAMESPACE_MAP = Object.fromEntries(BUILTIN_NAMESPACE_DEFS.map((it) => [it.key, it]));

export function normalizeNamespaceKey(raw, options = {}) {
  const fallbackNs = String(options.fallbackNs || "other").trim();
  const fallbackToOther = Boolean(options.fallbackToOther);
  const text = String(raw || "").trim().replace(/\s+/g, " ");
  if (!text) {
    return fallbackToOther ? normalizeNamespaceKey(fallbackNs, { fallbackToOther: false }) : "";
  }
  const lower = text.toLowerCase();
  return NS_ALIAS[text] || NS_ALIAS[lower] || lower;
}

export function normalizeUserTagInput(raw, options = {}) {
  const fallbackNs = normalizeNamespaceKey(options.fallbackNs || "other", { fallbackToOther: true }) || "other";
  const s0 = String(raw || "").trim();
  if (!s0) return "";
  const s = s0.replace(/\uFF1A/g, ":");
  if (s.toLowerCase().startsWith("user:")) {
    const parts = s.split(":", 3);
    if (parts.length < 3) return "";
    const ns = normalizeNamespaceKey(parts[1], { fallbackNs, fallbackToOther: true }) || fallbackNs;
    const tag = String(parts.slice(2).join(":") || "").trim().replace(/\s+/g, " ");
    return tag ? `${ns}:${tag}` : "";
  }
  const i = s.indexOf(":");
  if (i > 0) {
    const nsRaw = s.slice(0, i).trim();
    const tagRaw = s.slice(i + 1).trim();
    const ns = normalizeNamespaceKey(nsRaw, { fallbackNs, fallbackToOther: true }) || fallbackNs;
    const tag = tagRaw.replace(/\s+/g, " ");
    return tag ? `${ns}:${tag}` : "";
  }
  return `${fallbackNs}:${s.replace(/\s+/g, " ")}`;
}

/**
 * Drop a retired `user:` marker: `user:female:x` -> `female:x`.
 *
 * Tags picked by hand used to be marked so the UI could tell them from native
 * ones. There is nothing to tell them apart from any more, so the marker is no
 * longer written -- but rows saved before that still carry it, and this is what
 * keeps it from ever reaching the screen.
 */
export function stripUserTagMarker(raw) {
  const s = String(raw || "").trim();
  if (!s.toLowerCase().startsWith("user:")) return s;
  const parts = s.split(":", 3);
  if (parts.length < 3) return s;
  const ns = normalizeNamespaceKey(parts[1], { fallbackNs: "other", fallbackToOther: true }) || "other";
  const tag = String(parts[2] || "").trim().replace(/\s+/g, " ");
  return tag ? `${ns}:${tag}` : s;
}

export function uniqueUserTags(tags = [], options = {}) {
  const out = [];
  const seen = new Set();
  for (const raw of tags || []) {
    const next = normalizeUserTagInput(raw, options);
    if (!next) continue;
    const key = next.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(next);
  }
  return out;
}

/**
 * Turn raw suggestion strings into what a namespace-first composer shows.
 *
 * The suggester answers with stored tags (`female:巨乳`) while the user types
 * only the value part (`巨乳`) -- the backend substring-matches the whole tag,
 * so hits come back under whatever namespace they live in. A hit inside the
 * picked namespace shows as the bare value (the composer re-adds the prefix on
 * commit); a hit from ANOTHER namespace keeps its full `ns:value` label so it
 * still commits under its own namespace. Dropping those hits used to make the
 * suggestion list permanently empty whenever the picked namespace was `other`.
 */
export function tagSuggestLabels(items = [], nsKey = "other") {
  const want = normalizeNamespaceKey(nsKey, { fallbackToOther: true }) || "other";
  const out = [];
  const seen = new Set();
  for (const raw of items || []) {
    const s = stripUserTagMarker(String(raw || "").trim());
    if (!s) continue;
    const i = s.indexOf(":");
    let label = s;
    if (i > 0) {
      const ns = normalizeNamespaceKey(s.slice(0, i), { fallbackToOther: false });
      const val = s.slice(i + 1).trim();
      if (!ns || ns === want) label = val;
      else if (val) label = `${ns}:${val}`; // normalized, so aliases dedupe
      else continue;
    }
    if (!label) continue;
    const key = label.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(label);
  }
  return out;
}

export function normalizeNamespaceColor(raw, fallback = DEFAULT_NAMESPACE_COLOR) {
  const text = String(raw || "").trim();
  return /^#([0-9a-fA-F]{6})$/.test(text) ? text.toLowerCase() : String(fallback || DEFAULT_NAMESPACE_COLOR).toLowerCase();
}

export function parseCustomNamespaceConfig(raw) {
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
    const key = normalizeNamespaceKey(row?.key || row?.name || "", { fallbackToOther: false });
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      key,
      color: normalizeNamespaceColor(row?.color),
    });
  }
  return out;
}

export function stringifyCustomNamespaceConfig(rows = []) {
  return JSON.stringify(parseCustomNamespaceConfig(rows));
}

export function findCustomNamespaceDef(nsKey, customDefs = []) {
  const key = normalizeNamespaceKey(nsKey, { fallbackToOther: false });
  if (!key) return null;
  return parseCustomNamespaceConfig(customDefs).find((it) => it.key === key) || null;
}

export function getNamespaceColor(nsKey, customDefs = [], fallback = DEFAULT_NAMESPACE_COLOR) {
  const key = normalizeNamespaceKey(nsKey, { fallbackToOther: false });
  if (!key) return normalizeNamespaceColor(fallback);
  const custom = findCustomNamespaceDef(key, customDefs);
  if (custom?.color) return normalizeNamespaceColor(custom.color, fallback);
  const builtin = BUILTIN_NAMESPACE_MAP[key];
  if (builtin?.color) return normalizeNamespaceColor(builtin.color, fallback);
  return normalizeNamespaceColor(fallback);
}

export function isBuiltinNamespace(nsKey) {
  const key = normalizeNamespaceKey(nsKey, { fallbackToOther: false });
  return !!(key && BUILTIN_NAMESPACE_MAP[key]);
}

export function isManagedNamespace(nsKey, customDefs = []) {
  return isBuiltinNamespace(nsKey) || !!findCustomNamespaceDef(nsKey, customDefs);
}

export function extractNamespaceSeed(raw) {
  const text = String(raw || "").trim().replace(/\uFF1A/g, ":");
  if (!text) return "";
  const body = text.toLowerCase().startsWith("user:") ? text.slice(5) : text;
  const idx = body.indexOf(":");
  const head = (idx >= 0 ? body.slice(0, idx) : body).trim();
  return normalizeNamespaceKey(head, { fallbackToOther: false });
}

export function getNamespaceDisplayLabel(nsKey, t, customDefs = []) {
  const key = normalizeNamespaceKey(nsKey, { fallbackToOther: false });
  if (!key) return "";
  const custom = findCustomNamespaceDef(key, customDefs);
  if (custom) return custom.key;
  const builtin = BUILTIN_NAMESPACE_MAP[key];
  if (!builtin) return key;
  if (typeof t !== "function") return builtin.key;
  const translated = String(t(builtin.labelKey) || "").trim();
  return translated && translated !== builtin.labelKey ? translated : builtin.key;
}
