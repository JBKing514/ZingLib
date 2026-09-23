<template>
  <v-card class="pa-4" variant="flat">
    <div class="d-flex align-center justify-space-between flex-wrap ga-2 mb-3">
      <div class="text-subtitle-1 font-weight-medium">{{ t("tools.metadata_editor.title") }}</div>
      <v-btn size="small" variant="tonal" prepend-icon="mdi-refresh" :loading="loading" @click="reloadRows">{{ t("common.refresh") }}</v-btn>
    </div>

    <div class="d-flex ga-2 flex-wrap mb-3">
      <v-text-field
        v-model="keyword"
        density="compact"
        variant="outlined"
        clearable
        hide-details
        :label="t('tools.metadata_editor.search')"
        style="max-width: 360px"
        @keyup.enter="reloadRows"
      />
      <v-select
        v-model="gapFilter"
        :items="gapFilterOptions"
        density="compact"
        variant="outlined"
        hide-details
        :label="t('tools.metadata_editor.gap_filter')"
        style="max-width: 220px"
        @update:model-value="reloadRows"
      />
      <v-btn size="small" variant="tonal" prepend-icon="mdi-magnify" @click="reloadRows">{{ t("common.search") }}</v-btn>
      <v-btn size="small" variant="text" @click="selectAllCurrent">{{ t("tools.metadata_editor.select_all") }}</v-btn>
      <v-btn size="small" variant="text" @click="clearSelection">{{ t("tools.metadata_editor.clear_selection") }}</v-btn>
      <div class="text-caption text-medium-emphasis align-self-center">{{ t("tools.metadata_editor.selected_count", { n: selectedArcids.length }) }}</div>
    </div>

    <v-alert v-if="errorText" type="warning" variant="tonal" density="compact" class="mb-3">{{ errorText }}</v-alert>

    <v-card class="pa-3 mb-3" variant="tonal" color="blue-lighten-5">
      <div class="text-subtitle-2 mb-2">{{ t("tools.metadata_editor.bulk_title") }}</div>
      <div class="d-flex ga-2 flex-wrap mb-2 align-center">
        <v-switch
          v-model="bulkMode"
          true-value="remove"
          false-value="add"
          color="error"
          hide-details
          inset
          :label="bulkMode === 'remove' ? t('tools.metadata_editor.mode_remove') : t('tools.metadata_editor.mode_add')"
          class="mode-switch"
        />
        <v-select
          v-model="bulkNamespace"
          :items="namespaceOptions"
          density="compact"
          variant="outlined"
          hide-details
          :label="t('tools.metadata_editor.namespace')"
          class="bulk-ns-select"
          @update:model-value="onBulkNamespaceChange"
        />
        <v-combobox
          v-model="bulkTags"
          v-model:search="bulkTagSearch"
          :items="bulkSuggest"
          chips
          clearable
          multiple
          closable-chips
          density="compact"
          variant="outlined"
          :label="bulkMode === 'remove' ? t('tools.metadata_editor.remove_tags') : t('tools.metadata_editor.add_tags')"
          style="min-width: 320px; flex: 1"
          @update:search="onSearchBulkTags"
        />
      </div>
      <div class="d-flex ga-2 flex-wrap mb-2">
        <v-text-field
          v-model="setUserTitle"
          density="compact"
          variant="outlined"
          clearable
          :label="t('tools.metadata_editor.set_user_title')"
          style="min-width: 340px; flex: 1"
        />
        <v-switch v-model="clearUserTitle" color="warning" hide-details inset :label="t('tools.metadata_editor.clear_user_title')" />
      </div>
      <div class="d-flex ga-2 flex-wrap mb-2 align-center">
        <v-select
          v-model="setCategory"
          :items="categoryOptions"
          density="compact"
          variant="outlined"
          clearable
          :label="t('tools.metadata_editor.set_category')"
          style="min-width: 260px; max-width: 320px"
        />
        <v-switch v-model="clearCategory" color="warning" hide-details inset :label="t('tools.metadata_editor.clear_category')" />
      </div>
      <div class="d-flex ga-2 flex-wrap">
        <v-btn color="secondary" variant="tonal" :disabled="!selectedArcids.length" :loading="previewing" @click="previewUpdate">{{ t("tools.metadata_editor.preview") }}</v-btn>
        <v-btn :color="bulkMode === 'remove' ? 'error' : 'primary'" :disabled="!selectedArcids.length" :loading="applying" @click="applyUpdate">{{ t("tools.metadata_editor.apply") }}</v-btn>
      </div>
      <v-alert v-if="previewText" class="mt-2" density="compact" type="info" variant="tonal">{{ previewText }}</v-alert>
    </v-card>

    <v-data-table
      :headers="headers"
      :items="rows"
      :loading="loading"
      item-value="arcid"
      hover
      density="comfortable"
      class="meta-table"
    >
      <template #item.select="{ item }">
        <v-checkbox-btn :model-value="selectedSet.has(item.arcid)" @update:model-value="toggleSelected(item.arcid)" />
      </template>

      <template #item.cover="{ item }">
        <img :src="coverThumbUrl(item)" alt="cover" class="meta-cover" loading="lazy" />
      </template>

      <template #item.titles="{ item }">
        <div class="title-cell">
          <div class="text-caption text-medium-emphasis text-truncate" :title="item.title || ''">{{ item.title || item.arcid }}</div>
          <div
            v-if="!item._editingTitle"
            class="font-weight-bold text-primary text-truncate cursor-pointer"
            :title="item.user_title || ''"
            @dblclick="startInlineTitle(item)"
          >
            {{ item.user_title || t("tools.metadata_editor.inline_title_hint") }}
          </div>
          <v-text-field
            v-else
            v-model="item._tempUserTitle"
            density="compact"
            variant="underlined"
            hide-details
            autofocus
            @blur="saveInlineTitle(item)"
            @keyup.enter="saveInlineTitle(item)"
          />
        </div>
      </template>

      <template #item.category="{ item }">
        <v-select
          :model-value="item.category || ''"
          :items="categoryOptions"
          density="compact"
          variant="underlined"
          hide-details
          :disabled="Boolean(item._savingCategory)"
          @update:model-value="(v) => saveInlineCategory(item, v)"
        />
      </template>

      <template #item.tags="{ item }">
        <div v-if="!item._editingTags" class="cursor-pointer meta-tag-cell" @dblclick="startInlineTags(item)">
          <div
            v-for="group in rowTagGroups(item.tags)"
            :key="`${item.arcid}-${group.key}`"
            class="tag-namespace-row"
            :class="{ 'tag-namespace-row-no-pill': !group.label }"
          >
            <span v-if="group.label" class="tag-namespace-pill" :style="group.pillStyle">{{ group.label }}</span>
            <div class="tag-chip-list">
              <v-chip v-for="row in group.items" :key="`${item.arcid}-${group.key}-${row.tag}`" size="small" variant="outlined" class="meta-tag-chip">{{ row.label }}</v-chip>
            </div>
          </div>
          <span v-if="!(item.tags || []).length" class="text-caption text-medium-emphasis">{{ t("tools.metadata_editor.inline_tags_hint") }}</span>
        </div>
        <div v-else class="tag-composer">
          <div class="d-flex ga-2 flex-wrap align-center mb-1">
            <v-select
              v-model="inlineTagNs"
              :items="namespaceOptions"
              density="compact"
              variant="outlined"
              hide-details
              :label="t('tools.metadata_editor.tag_namespace')"
              class="inline-ns-select"
              @update:model-value="onInlineNamespaceChange"
            />
            <v-text-field
              v-model="inlineTagSearch"
              density="compact"
              variant="outlined"
              hide-details
              clearable
              :label="t('tools.metadata_editor.tag_input')"
              class="inline-tag-input"
              @keydown.enter.prevent="commitInlineTag"
              @update:model-value="onSearchInlineTags"
            />
            <v-btn size="small" variant="tonal" :disabled="!String(inlineTagSearch || '').trim()" @click="commitInlineTag">{{ t("tools.metadata_editor.tag_add") }}</v-btn>
          </div>
          <div v-if="inlineSuggestVisible" class="d-flex flex-wrap ga-1 mb-1">
            <v-chip
              v-for="label in inlineSuggest"
              :key="`${item.arcid}-sug-${label}`"
              size="x-small"
              variant="text"
              class="tag-suggest-chip"
              @mousedown.prevent
              @click.stop="pickInlineSuggestion(label)"
            >{{ label }}</v-chip>
          </div>
          <div v-else-if="String(inlineTagSearch || '').trim()" class="text-caption text-medium-emphasis mb-1">
            {{ t("tools.metadata_editor.tag_no_candidate") }}
          </div>
          <div class="d-flex flex-wrap ga-1 mb-1">
            <v-chip
              v-for="tag in item._tempTags || []"
              :key="`${item.arcid}-tmp-${tag}`"
              size="small"
              variant="tonal"
              closable
              @click:close="removeInlineTag(item, tag)"
            >{{ displayTag(tag) }}</v-chip>
          </div>
          <div class="d-flex align-center ga-2">
            <v-btn size="x-small" variant="text" @click="cancelInlineTags(item)">{{ t("common.cancel") }}</v-btn>
            <v-btn size="x-small" color="primary" variant="tonal" @click="saveInlineTags(item)">{{ t("common.save") }}</v-btn>
            <v-btn size="x-small" variant="text" prepend-icon="mdi-cog-outline" @click="goNamespaceSettings">{{ t("tools.metadata_editor.namespace_manage") }}</v-btn>
          </div>
        </div>
      </template>
    </v-data-table>

    <div class="d-flex justify-center mt-3">
      <v-btn v-if="hasMore" size="small" variant="tonal" :loading="loadingMore" @click="loadMore">{{ t("tools.metadata_editor.load_more") }}</v-btn>
    </div>
  </v-card>
</template>

<script setup>
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import {
  batchUpdateLocalMeta,
  getHomeTagSuggest,
  getLocalMetadataGaps,
  getLocalMetaList,
  previewLocalMetaBatchUpdate,
} from "../../api";
import { useDashboardStore } from "../../stores/dashboardStore";
import { useLayoutStore } from "../../stores/layoutStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { getCategoryLabel } from "../../utils/categoryPresets";
import {
  BUILTIN_NAMESPACE_DEFS,
  getNamespaceColor,
  getNamespaceDisplayLabel,
  normalizeNamespaceKey,
  normalizeUserTagInput as normalizeUserTagInputCore,
  stripUserTagMarker,
  tagSuggestLabels,
} from "../../utils/tagNamespaces";

const dashboardStore = useDashboardStore();
const layoutStore = useLayoutStore();
const settingsStore = useSettingsStore();
const router = useRouter();

// The tag column now lists every tag a work carries -- hand-picked ones are no
// longer a separate pool from the ComicInfo-sourced ones, so there is nothing
// left to filter on and the column is simply "Tags".
const headers = computed(() => [
  { title: "", key: "select", sortable: false, width: 48 },
  { title: "", key: "cover", sortable: false, width: 56 },
  { title: t("tools.metadata_editor.col_arcid"), key: "arcid", width: 220 },
  { title: t("tools.metadata_editor.col_title"), key: "titles", sortable: false, width: 340 },
  { title: t("tools.metadata_editor.col_category"), key: "category", sortable: false, width: 180 },
  { title: t("tools.metadata_editor.col_tags"), key: "tags", sortable: false },
]);

const loading = ref(false);
const loadingMore = ref(false);
const previewing = ref(false);
const applying = ref(false);
const errorText = ref("");
const previewText = ref("");
const rows = ref([]);
const hasMore = ref(false);
const offset = ref(0);
const limit = 120;
const keyword = ref("");
const gapFilter = ref("none");

const selectedArcids = ref([]);
const bulkMode = ref("add");
const bulkTags = ref([]);
const bulkSuggest = ref([]);
const bulkTagSearch = ref("");
const bulkNamespace = ref("other");
// Only one composer is open at a time, so the suggestion list and the namespace
// dropdown can live here rather than on each row.
const inlineSuggest = ref([]);
const inlineTagSearch = ref("");
const inlineTagNs = ref("other");
const inlineItem = ref(null);
const setUserTitle = ref("");
const clearUserTitle = ref(false);
const setCategory = ref(null);
const clearCategory = ref(false);

const selectedSet = computed(() => new Set((selectedArcids.value || []).map((x) => String(x || "").trim())));
const customNamespaceDefs = computed(() => Array.isArray(settingsStore?.customNamespaceDefs) ? settingsStore.customNamespaceDefs : []);
const inlineSuggestVisible = computed(() => inlineSuggest.value.length > 0);
const categoryOptions = computed(() => [
  { title: t("tools.metadata_editor.category_none"), value: "" },
  ...((settingsStore?.localCategoryDefs || []).map((it) => ({
    title: getCategoryLabel(it, t),
    value: String(it?.key || "").trim().toLowerCase(),
  }))),
]);

function coverThumbUrl(item) {
  const arcid = encodeURIComponent(String(item?.arcid || "").trim());
  const preset = encodeURIComponent(String(settingsStore.config?.LOCAL_THUMB_PRESET || "mid").trim().toLowerCase() || "mid");
  return `/api/thumb/work/${arcid}?preset=${preset}`;
}
const gapFilterOptions = computed(() => [
  { title: t("tools.metadata_editor.gap_filter_none"), value: "none" },
  { title: t("tools.metadata_editor.gap_filter_all"), value: "all" },
  { title: t("tools.metadata_editor.gap_filter_title"), value: "title" },
  { title: t("tools.metadata_editor.gap_filter_category"), value: "category" },
  { title: t("tools.metadata_editor.gap_filter_tags"), value: "tags" },
]);

function t(key, vars = {}) {
  return layoutStore.t(key, vars);
}

function notify(msg, color = "success") {
  settingsStore.notify(String(msg || ""), color);
}

function namespaceSuggestionLabel(key) {
  return getNamespaceDisplayLabel(key, t, customNamespaceDefs.value);
}

// Every namespace the picker offers: the built-ins plus whatever custom ones
// the user defined in settings.
const namespaceOptions = computed(() => {
  const out = [];
  const seen = new Set();
  const push = (rawKey) => {
    const key = normalizeNamespaceKey(rawKey, { fallbackToOther: false });
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({ title: namespaceSuggestionLabel(key), value: key });
  };
  for (const def of BUILTIN_NAMESPACE_DEFS) push(def?.key);
  for (const def of customNamespaceDefs.value || []) push(def?.key);
  return out;
});

/**
 * Turn raw suggestion strings into the labels the composer can show.
 *
 * Shared with the quick-add dialog (`tagNamespaces.tagSuggestLabels`): a hit
 * inside the picked namespace shows as the bare value, a hit from another
 * namespace keeps its `ns:value` label so it commits under its own namespace.
 */
// Suggestions are fetched per keystroke, so a slow early reply must not
// overwrite the list a later one produced.
let tagSuggestSeq = 0;
async function fetchTagSuggestions(kw, nsKey, sink) {
  tagSuggestSeq += 1;
  const seq = tagSuggestSeq;
  try {
    const res = await getHomeTagSuggest({ q: kw, limit: 20, ui_lang: String(layoutStore.lang || "zh") });
    if (seq === tagSuggestSeq) sink.value = tagSuggestLabels(res?.items || [], nsKey);
  } catch {
    if (seq === tagSuggestSeq) sink.value = [];
  }
}

/**
 * Display-side dedupe: drop a retired `user:` marker, collapse duplicates.
 *
 * Deliberately not the add-path normaliser -- that one invents a namespace, and
 * running it on render would rewrite a bare native tag (`source_tag`) into
 * `other:source_tag` just by showing it.
 */
function dedupeTags(tags = []) {
  const out = [];
  const seen = new Set();
  for (const raw of tags || []) {
    const s = stripUserTagMarker(String(raw || "").trim());
    if (!s) continue;
    const key = s.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}

function normalizeUserTagInput(raw, options = {}) {
  return normalizeUserTagInputCore(raw, { fallbackNs: "other", ...options });
}

function displayTag(tag) {
  return stripUserTagMarker(tag);
}

/**
 * Group a work's tags by namespace for the display cell.
 *
 * Same shape PreviewCard renders (`tag-namespace-row` + colored pill per
 * namespace), so the editor reads like the card it edits. A tag without a
 * parsable namespace lands in the `misc` bucket, exactly like the card does.
 */
function rowTagGroups(tags = []) {
  const out = [];
  const idx = new Map();
  for (const raw of tags || []) {
    const s = stripUserTagMarker(String(raw || "").trim());
    if (!s) continue;
    let key = "misc";
    let label = s;
    const i = s.indexOf(":");
    if (i > 0) {
      const ns = normalizeNamespaceKey(s.slice(0, i), { fallbackToOther: false });
      const val = s.slice(i + 1).trim();
      if (ns && val) {
        key = ns;
        label = val;
      }
    }
    if (!idx.has(key)) {
      idx.set(key, out.length);
      out.push({
        key,
        label: getNamespaceDisplayLabel(key, t, customNamespaceDefs.value),
        pillStyle: {
          backgroundColor: getNamespaceColor(key, customNamespaceDefs.value),
          borderColor: "rgba(15, 23, 42, 0.3)",
          color: "#ffffff",
        },
        items: [],
      });
    }
    out[idx.get(key)].items.push({ tag: s, label });
  }
  return out;
}

function goNamespaceSettings() {
  router.push({ name: "settings-local-lib" }).catch(() => null);
}

function normalizeCategory(raw) {
  return String(raw || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function replaceCategoryTag(tags = [], category = "") {
  const nextCategory = normalizeCategory(category);
  const out = [];
  const seen = new Set();
  for (const raw of tags || []) {
    const tag = String(raw || "").trim();
    if (!tag) continue;
    if (tag.toLowerCase().startsWith("category:")) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
  }
  if (nextCategory) {
    out.push(`category:${nextCategory}`);
  }
  return out;
}

function hydrateRows(items = []) {
  return (items || []).map((it) => ({
    ...it,
    category: normalizeCategory(it?.category || ""),
    tags: dedupeTags(it?.tags || []),
    _editingTitle: false,
    _tempUserTitle: String(it?.user_title || ""),
    _editingTags: false,
    _tempTags: dedupeTags(it?.tags || []),
    _savingCategory: false,
  }));
}

async function fetchRows(nextOffset = 0, append = false) {
  const gapMode = String(gapFilter.value || "none");
  const params = { limit, offset: nextOffset, q: String(keyword.value || "").trim() };
  const res = gapMode === "none"
    ? await getLocalMetaList(params)
    : await getLocalMetadataGaps({ ...params, gap_type: gapMode });
  const items = hydrateRows(Array.isArray(res?.items) ? res.items : []);
  rows.value = append ? rows.value.concat(items) : items;
  hasMore.value = Boolean(res?.has_more);
  offset.value = rows.value.length;
  const keep = new Set(rows.value.map((x) => x.arcid));
  selectedArcids.value = selectedArcids.value.filter((x) => keep.has(x));
}

async function reloadRows() {
  loading.value = true;
  errorText.value = "";
  previewText.value = "";
  try {
    await fetchRows(0, false);
  } catch (e) {
    errorText.value = String(e?.response?.data?.detail || e);
  } finally {
    loading.value = false;
  }
}

async function loadMore() {
  if (!hasMore.value) return;
  loadingMore.value = true;
  try {
    await fetchRows(offset.value, true);
  } catch (e) {
    errorText.value = String(e?.response?.data?.detail || e);
  } finally {
    loadingMore.value = false;
  }
}

function toggleSelected(arcid) {
  const id = String(arcid || "").trim();
  if (!id) return;
  const set = new Set(selectedArcids.value || []);
  if (set.has(id)) set.delete(id);
  else set.add(id);
  selectedArcids.value = Array.from(set);
}

function selectAllCurrent() {
  selectedArcids.value = rows.value.map((x) => String(x?.arcid || "").trim()).filter(Boolean);
}

function clearSelection() {
  selectedArcids.value = [];
}

function buildBulkPayload() {
  // Entries go to the API as typed: the picked namespace travels in its own
  // field and the backend applies it, so nothing here may invent `other:`.
  const tags = dedupeTags(bulkTags.value || []);
  const payload = {
    arcids: selectedArcids.value,
    namespace: normalizeNamespaceKey(bulkNamespace.value || "other", { fallbackToOther: true }) || "other",
    clear_user_title: Boolean(clearUserTitle.value),
    clear_category: Boolean(clearCategory.value),
    add_user_tags: bulkMode.value === "add" ? tags : [],
    remove_user_tags: bulkMode.value === "remove" ? tags : [],
  };
  const title = String(setUserTitle.value || "").trim();
  if (title) payload.set_user_title = title;
  const category = normalizeCategory(setCategory.value || "");
  if (category) payload.set_category = category;
  return payload;
}

async function previewUpdate() {
  previewing.value = true;
  previewText.value = "";
  try {
    const res = await previewLocalMetaBatchUpdate(buildBulkPayload());
    previewText.value = t("tools.metadata_editor.preview_result", {
      affected: Number(res?.affected || 0),
      found: Number(res?.found || 0),
      missing: Number((res?.missing || []).length || 0),
    });
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  } finally {
    previewing.value = false;
  }
}

async function applyUpdate() {
  applying.value = true;
  try {
    const res = await batchUpdateLocalMeta(buildBulkPayload());
    notify(t("tools.metadata_editor.apply_result", { done: Number(res?.done || 0), skipped: Number(res?.skipped || 0), failed: Number(res?.failed || 0) }));
    if (typeof dashboardStore?.resetHomeFeed === "function") {
      await dashboardStore.resetHomeFeed();
    }
    await reloadRows();
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  } finally {
    applying.value = false;
  }
}

function startInlineTitle(item) {
  item._editingTitle = true;
  item._tempUserTitle = String(item.user_title || "");
}

async function saveInlineTitle(item) {
  if (!item?._editingTitle) return;
  item._editingTitle = false;
  const nextTitle = String(item._tempUserTitle || "").trim();
  if (nextTitle === String(item.user_title || "").trim()) return;
  try {
    const payload = {
      arcids: [item.arcid],
      set_user_title: nextTitle,
      clear_user_title: !nextTitle,
      add_user_tags: [],
      remove_user_tags: [],
    };
    await batchUpdateLocalMeta(payload);
    item.user_title = nextTitle;
     item.display_title = nextTitle || item.title;
     dashboardStore.updateLocalWorkItem(item.arcid, { user_title: nextTitle, display_title: nextTitle || item.title });
     if (typeof dashboardStore?.resetHomeFeed === "function") {
       await dashboardStore.resetHomeFeed();
     }
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  }
}

async function saveInlineCategory(item, nextValue) {
  const nextCategory = normalizeCategory(nextValue || "");
  const prevCategory = normalizeCategory(item?.category || "");
  if (nextCategory === prevCategory) return;
  item._savingCategory = true;
  try {
    await batchUpdateLocalMeta({
      arcids: [item.arcid],
      set_category: nextCategory,
      clear_category: !nextCategory,
      add_user_tags: [],
      remove_user_tags: [],
      clear_user_title: false,
    });
    item.category = nextCategory;
    item.tags = replaceCategoryTag(item.tags || [], nextCategory);
    dashboardStore.updateLocalWorkItem(item.arcid, { category: nextCategory, tags: item.tags });
    if (typeof dashboardStore?.resetHomeFeed === "function") {
      await dashboardStore.resetHomeFeed();
    }
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  } finally {
    item._savingCategory = false;
  }
}

function resetTagComposer() {
  inlineItem.value = null;
  inlineTagSearch.value = "";
  inlineTagNs.value = "other";
  inlineSuggest.value = [];
}

function startInlineTags(item) {
  item._editingTags = true;
  item._tempTags = dedupeTags(item.tags || []);
  inlineItem.value = item;
  inlineTagSearch.value = "";
  inlineTagNs.value = "other";
  inlineSuggest.value = [];
}

function cancelInlineTags(item) {
  if (item) {
    item._editingTags = false;
    item._tempTags = dedupeTags(item.tags || []);
  }
  resetTagComposer();
}

// Switching namespace invalidates the suggestion list: it was filtered to the
// old namespace on purpose.
function onInlineNamespaceChange(v) {
  inlineTagNs.value = normalizeNamespaceKey(v || "other", { fallbackToOther: true }) || "other";
  inlineSuggest.value = [];
  const kw = String(inlineTagSearch.value || "").trim();
  if (kw) fetchTagSuggestions(kw, inlineTagNs.value, inlineSuggest).catch(() => null);
}

/**
 * Enter (or the add button) turns what is in the box into a tag.
 *
 * The namespace is a separate control now, so the typed text IS the value --
 * it never has to carry its own prefix, and a phrase that matched no suggestion
 * is added just the same. An explicit `ns:value` (e.g. a cross-namespace
 * suggestion) is honored as-is; the picked namespace is only the fallback.
 */
function commitInlineTag() {
  const item = inlineItem.value;
  if (!item) return;
  const label = String(inlineTagSearch.value || "").trim();
  if (!label) return;
  const ns = normalizeNamespaceKey(inlineTagNs.value, { fallbackToOther: true }) || "other";
  const full = normalizeUserTagInput(label, { fallbackNs: ns });
  if (!full) return;
  const next = Array.isArray(item._tempTags) ? item._tempTags : [];
  if (!next.some((x) => String(x).toLowerCase() === full.toLowerCase())) {
    item._tempTags = [...next, full];
  }
  inlineTagSearch.value = "";
  inlineSuggest.value = [];
}

function pickInlineSuggestion(label) {
  inlineTagSearch.value = String(label || "").trim();
  commitInlineTag();
}

function removeInlineTag(item, tag) {
  const key = String(tag || "").toLowerCase();
  item._tempTags = (item._tempTags || []).filter((x) => String(x).toLowerCase() !== key);
}

function onSearchInlineTags(q) {
  inlineTagSearch.value = String(q ?? "");
  const kw = inlineTagSearch.value.trim();
  if (!kw) {
    inlineSuggest.value = [];
    return;
  }
  fetchTagSuggestions(kw, inlineTagNs.value, inlineSuggest).catch(() => null);
}

async function saveInlineTags(item) {
  if (!item?._editingTags) return;
  const next = dedupeTags(item._tempTags || []);
  const prev = dedupeTags(item.tags || []);
  const nextSet = new Set(next.map((x) => x.toLowerCase()));
  const prevSet = new Set(prev.map((x) => x.toLowerCase()));
  const add = next.filter((x) => !prevSet.has(x.toLowerCase()));
  const remove = prev.filter((x) => !nextSet.has(x.toLowerCase()));
  item._editingTags = false;
  resetTagComposer();
  if (!add.length && !remove.length) return;
  // Show the result immediately and undo it if the write fails, so the table
  // never claims a tag is saved when it is not.
  item.tags = next;
  dashboardStore.updateLocalWorkItem(item.arcid, { tags: next });
  try {
    await batchUpdateLocalMeta({
      arcids: [item.arcid],
      add_user_tags: add,
      remove_user_tags: remove,
      clear_user_title: false,
    });
    if (typeof dashboardStore?.resetHomeFeed === "function") {
      await dashboardStore.resetHomeFeed();
    }
  } catch (e) {
    item.tags = prev;
    dashboardStore.updateLocalWorkItem(item.arcid, { tags: prev });
    notify(String(e?.response?.data?.detail || e), "warning");
  }
}

function onSearchBulkTags(q) {
  bulkTagSearch.value = String(q ?? "");
  const kw = bulkTagSearch.value.trim();
  if (!kw) {
    bulkSuggest.value = [];
    return;
  }
  fetchTagSuggestions(kw, bulkNamespace.value, bulkSuggest).catch(() => null);
}

function onBulkNamespaceChange(v) {
  bulkNamespace.value = normalizeNamespaceKey(v || "other", { fallbackToOther: true }) || "other";
  bulkSuggest.value = [];
  const kw = String(bulkTagSearch.value || "").trim();
  if (kw) fetchTagSuggestions(kw, bulkNamespace.value, bulkSuggest).catch(() => null);
}

reloadRows().catch(() => null);
</script>

<style scoped>
.meta-cover {
  width: 45px;
  height: 64px;
  border-radius: 6px;
  border: 1px solid rgba(148, 163, 184, 0.5);
  object-fit: contain;
  background: rgba(15, 23, 42, 0.12);
}

.title-cell {
  max-width: 340px;
}

.meta-table :deep(th),
.meta-table :deep(td) {
  vertical-align: top;
}

.mode-switch {
  min-width: 180px;
}

/* Namespace color now lives on the per-namespace pill (see rowTagGroups /
   .tag-namespace-pill), exactly like PreviewCard -- forcing one color on every
   chip is what made all namespaces look the same. */

/* Keeps a tag-less cell clickable so the double-click target is never 0px tall. */
.meta-tag-cell {
  min-height: 32px;
}

.tag-composer {
  min-width: 320px;
}

/* Explicit width: `flex: 0 0 auto` + max-width lets an outlined Vuetify field
   collapse to zero inside a flex row (its intrinsic content is empty), which is
   how the namespace picker vanished from the quick-add dialog. */
.inline-ns-select {
  flex: 0 0 150px;
  width: 150px;
  max-width: 150px;
}

.inline-tag-input {
  min-width: 160px;
  flex: 1 1 200px;
}

.bulk-ns-select {
  flex: 0 0 150px;
  width: 150px;
  max-width: 150px;
}

.tag-suggest-chip {
  border: 1px dashed rgba(148, 163, 184, 0.7);
}

/* Tag display cell, grouped per namespace like PreviewCard. */
.tag-namespace-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}

.tag-namespace-row:last-child {
  margin-bottom: 0;
}

.tag-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.tag-namespace-row-no-pill {
  gap: 0;
}

.tag-namespace-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 54px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 18px;
  font-weight: 600;
  border: 1px solid rgba(15, 23, 42, 0.3);
  flex-shrink: 0;
}
</style>
