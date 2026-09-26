/**
 * Fold a metadata edit back into a single feed row.
 *
 * Why this exists: editing a gallery's metadata from the preview pane's quick-add
 * dialog must refresh *that card*, not the dashboard. The obvious shortcut --
 * re-running the home feed (`resetHomeFeed()`) -- does refresh the card, but it
 * also re-fetches and re-renders every row the user is looking at, drops the
 * scroll position, and makes the whole grid flicker for a change that touched
 * one gallery.
 *
 * The batch-update endpoint answers with the deltas it applied rather than the
 * row (`{arcid, ok, added_user_tags, removed_user_tags, user_title, category}`),
 * so the merge is done here against the row already on screen.
 *
 * The row's own fields are derived server-side in `_item_from_work`:
 *
 *   tags        = base_tags + extras + user_tags
 *   title       = user_title || official_title
 *   category    = the `category:<x>` tag
 *
 * so a merge has to touch the same derived fields, not just store a `user_tags`
 * array the row does not carry.
 */

/** A tag's identity for comparison: trimmed and case-folded. */
function tagKey(value) {
  return String(value ?? "").trim().toLowerCase();
}

/**
 * Every spelling a single tag could have been stored under.
 *
 * The dialog sends the namespaced form (`female:眼镜`) while a row built before
 * the namespace change may still hold the bare value (`眼镜`), and an edit may
 * arrive in either shape. Matching only the exact string would leave the old
 * spelling behind, and the card would appear to gain a tag it already had.
 */
function tagVariants(value) {
  const s = String(value ?? "").trim();
  if (!s) return [];
  const out = new Set([tagKey(s)]);
  if (s.includes(":")) {
    const bare = s.slice(s.indexOf(":") + 1);
    if (bare) out.add(tagKey(bare));
  }
  return [...out];
}

/** Canonicalise an incoming add to the stored `namespace:value` shape. */
function canonicalTag(value, namespace) {
  const s = String(value ?? "").trim();
  if (!s || s.includes(":")) return s;
  const ns = String(namespace ?? "").trim();
  return ns ? `${ns}:${s}` : s;
}

/**
 * Apply a batch-update result to one feed row.
 *
 * Returns a **new** row, or the original untouched when the edit did not name
 * this row / failed, so callers can hand the result straight to
 * `patchHomeItem`. `official_title` is never touched: it is the server's view of
 * the file's own title, which this edit cannot change.
 */
export function mergeMetaEditIntoItem(item, edit) {
  if (!item || typeof item !== "object") return item;
  if (!edit || typeof edit !== "object" || edit.ok === false) return item;

  const arcid = String(item?.arcid || "").trim();
  const editArcid = String(edit?.arcid || "").trim();
  if (!arcid || !editArcid || arcid !== editArcid) return item;

  const rawAdds = Array.isArray(edit.added_user_tags) ? edit.added_user_tags : [];
  const rawRemoves = Array.isArray(edit.removed_user_tags) ? edit.removed_user_tags : [];
  const namespace = String(edit.namespace || "").trim();

  // Identity sets: what the edit wants gone, and every spelling of what it wants
  // present. A tag that is both added and removed resolves to "present", which
  // matches the server, where the add is applied after the remove.
  const goneSet = new Set(rawRemoves.flatMap((t) => tagVariants(t)));
  const addVariantKeys = new Set(rawAdds.flatMap((t) => tagVariants(t)));

  const current = Array.isArray(item.tags) ? item.tags : [];
  // One pass: drop what was removed, and drop any surviving spelling of a tag
  // that is being added, so the canonical form replaces it instead of sitting
  // next to it.
  const body = current.filter((t) => {
    const k = tagKey(t);
    if (!k) return false;
    if (goneSet.has(k)) return false;
    if (addVariantKeys.has(k)) return false;
    return true;
  });

  const addedCanonical = rawAdds.map((t) => canonicalTag(t, namespace)).filter(Boolean);
  const seen = new Set(body.map((t) => tagKey(t)));
  const nextTags = [...body];
  for (const t of addedCanonical) {
    const k = tagKey(t);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    nextTags.push(t);
  }

  const next = { ...item, tags: nextTags };

  // `user_title` is the only title the edit can move; the display title follows
  // it and falls back to the official title when it is cleared.
  if (Object.prototype.hasOwnProperty.call(edit, "user_title")) {
    const nextUserTitle = String(edit.user_title ?? "").trim();
    next.user_title = nextUserTitle;
    next.title = nextUserTitle || String(item.official_title || "").trim();
  }

  // The category pill is read off the `category:<x>` tag. When a rewrite leaves
  // no such tag the row keeps the category it already resolved to, because the
  // backend falls back to `raw.eh_raw.category` (`_category_from_tags(tags,
  // _raw_category(row))`) -- clearing the field here would show a blank pill the
  // next feed load would fill back in.
  const catTag = nextTags.find((t) => tagKey(t).startsWith("category:"));
  if (catTag) {
    next.category = tagKey(catTag).slice("category:".length);
  } else if (Object.prototype.hasOwnProperty.call(edit, "category") && String(edit.category || "").trim()) {
    next.category = String(edit.category).trim().toLowerCase();
  }

  return next;
}
