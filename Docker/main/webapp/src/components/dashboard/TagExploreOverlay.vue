<template>
  <teleport to="body">
    <transition :name="presentationMode === 'phone' ? 'tag-explore-slide-up' : 'tag-explore-fade'">
      <div
        v-if="open"
        class="tag-explore-host"
        :class="`mode-${presentationMode}`"
        @click.self="onBackdropSelf"
      >
        <v-card class="tag-explore-shell" :class="shellClass" :style="shellStyle" variant="flat">
          <div class="tag-explore-toolbar">
            <div class="d-flex ga-2 align-center flex-shrink-0">
              <v-btn icon="mdi-arrow-left" variant="text" color="primary" @click="onBack" />
              <v-btn icon="mdi-home-variant-outline" variant="text" color="secondary" @click="emit('close-all')" />
            </div>
            <v-text-field
              v-model="searchQuery"
              class="tag-explore-search"
              density="compact"
              hide-details
              variant="outlined"
              :label="t('home.search.placeholder')"
              @keyup.enter="runSearch"
            />
            <v-btn icon="mdi-magnify" variant="text" color="primary" @click="runSearch" />
            <v-btn icon="mdi-filter-variant" variant="text" color="primary" @click="filtersOpen = true" />
          </div>

          <div class="tag-explore-seed-row px-4 pb-2">
            <v-chip v-if="currentSeed" size="small" variant="tonal" color="primary">{{ currentSeed }}</v-chip>
            <span v-if="currentSeed" class="text-caption text-medium-emphasis">{{ t('home.search.quick_title') }}</span>
          </div>

          <div v-if="previewItem" class="tag-explore-preview-body" :class="previewBodyClass">
            <PreviewCard
              :item="previewItem"
              :is-mobile="presentationMode !== 'desktop'"
              :hide-start-button="false"
              :t="t"
              :get-gallery-title="getGalleryTitle"
              :item-hover-tags="itemHoverTags"
              :is-tag-filter-active="isTagActive"
              :show-rec-debug="!!config.REC_DEBUG_DETAILS"
              :is-favorited="isFavorited(previewItem)"
              :item-rating-value="itemRatingValue"
              :allow-delete-local="allowDeleteLocal"
              @start-reader="emit('start-reader', $event)"
              @start-reader-at-page="emit('start-reader-at-page', $event)"
              @favorite-toggle="emit('favorite-toggle', $event)"
              @delete-local="emit('delete-local', $event)"
              @apply-tag-filter="onApplyTagFilter"
              @set-rating="emit('set-rating', $event)"
              @hydrated="onPreviewHydrated"
              @image-error="emit('image-error', $event)"
              @quick-add-tag="emit('quick-add-tag', $event)"
            />
          </div>

          <div
            v-else
            ref="bodyRef"
            class="tag-explore-body px-4 pb-4"
            @scroll.passive="onBodyScroll"
          >
            <v-alert v-if="error" type="warning" density="compact" variant="tonal" class="mb-3">{{ error }}</v-alert>
            <div v-if="loading" class="text-center py-8">
              <v-progress-circular indeterminate color="primary" size="26" />
            </div>
            <template v-else>
              <v-row v-if="items.length" class="ma-0">
                <v-col
                  v-for="item in items"
                  :key="`te-${item.id || (String(item.source || '') + '-' + String(item.arcid || item.gid || ''))}`"
                  cols="12"
                  sm="6"
                  md="6"
                  lg="6"
                  class="pb-3"
                >
                  <v-card class="home-card tag-explore-item-card" variant="flat" @click="openItemPreview(item)">
                    <div class="cover-anchor" @contextmenu.prevent>
                      <div class="cover-ph">
                        <img
                          v-if="item.thumb_url"
                          :src="item.thumb_url"
                          alt="cover"
                          class="cover-img"
                          loading="lazy"
                          draggable="false"
                          @dragstart.prevent
                        />
                        <v-icon v-else size="30">mdi-image-outline</v-icon>
                        <div class="cover-guard" @contextmenu.prevent />
                        <div
                          v-if="categoryLabel(item)"
                          class="cat-badge"
                          :style="categoryBadgeStyle(item)"
                        >{{ categoryLabel(item) }}</div>
                      </div>
                    </div>
                    <div class="pa-2">
                      <div class="text-body-2 font-weight-medium text-truncate d-block">{{ getGalleryTitle(item) }}</div>
                      <div class="text-caption text-medium-emphasis text-truncate">{{ itemSubtitle(item) }}</div>
                      <div v-if="itemRatingValue(item) !== null" class="d-flex align-center ga-1 mt-1">
                        <v-rating
                          :model-value="itemRatingValue(item)"
                          readonly
                          half-increments
                          density="compact"
                          size="x-small"
                          color="amber"
                          empty-icon="mdi-star-outline"
                          full-icon="mdi-star"
                          half-icon="mdi-star-half-full"
                        />
                        <span class="text-caption text-medium-emphasis">{{ Number(itemRatingValue(item)).toFixed(1) }}</span>
                      </div>
                    </div>
                  </v-card>
                </v-col>
              </v-row>
              <div v-else class="text-center text-medium-emphasis py-8">{{ t('home.empty') }}</div>
              <div v-if="loadingMore" class="text-center py-3">
                <v-progress-circular indeterminate color="primary" size="20" />
              </div>
              <div v-if="hasMore && !loading && !loadingMore" class="text-center py-2">
                <v-btn color="primary" variant="tonal" prepend-icon="mdi-chevron-down" @click="loadMoreManual">{{ t('common.load_more') }}</v-btn>
              </div>
            </template>
          </div>

          <v-dialog v-model="filtersOpen" max-width="680" :z-index="3200">
            <v-card class="pa-4" variant="flat">
              <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.filter.title') }}</div>
              <div class="text-caption text-medium-emphasis mb-3">{{ t('home.filter.hint') }}</div>

              <div class="d-flex align-center justify-space-between mb-2">
                <div class="text-body-2">{{ t('home.filter.categories') }}</div>
                <div class="d-flex ga-2">
                  <v-btn size="small" variant="text" color="primary" @click="selectAllCategories">{{ t('home.filter.select_all') }}</v-btn>
                  <v-btn size="small" variant="text" color="medium-emphasis" @click="clearAllCategories">{{ t('home.filter.select_none') }}</v-btn>
                </div>
              </div>

              <div
                class="mb-4"
                :style="{ display: 'grid', gridTemplateColumns: isMobile ? 'repeat(2, max-content)' : 'repeat(5, 1fr)', gap: isMobile ? '6px' : '8px' }"
              >
                <v-btn
                  v-for="cat in categoryDefs"
                  :key="`tef-${cat.key}`"
                  class="category-btn text-caption font-weight-bold"
                  :height="isMobile ? 40 : 32"
                  rounded="lg"
                  variant="flat"
                  :style="categoryStyle(cat.key, cat.color)"
                  @click="toggleCategory(cat.key)"
                >
                  <span class="text-truncate">{{ getCategoryLabel(cat, t) }}</span>
                </v-btn>
              </div>

              <v-autocomplete
                v-model="filters.tags"
                v-model:search="filterTagInput"
                :items="filterTagSuggestions"
                multiple
                chips
                closable-chips
                clearable
                variant="outlined"
                density="compact"
                color="primary"
                :label="t('home.filter.tags')"
                :hint="t('home.filter.tags_hint')"
                persistent-hint
                class="mb-2"
                @update:search="onTagSearch"
              />

              <div class="mt-1 mb-2">
                <div class="d-flex align-center justify-space-between mb-1">
                  <div class="text-body-2">{{ t('home.filter.min_rating') }}</div>
                  <div class="text-caption text-medium-emphasis">{{ Number(filters.minRating || 0).toFixed(1) }}★</div>
                </div>
                <v-slider
                  v-model="filters.minRating"
                  :min="0"
                  :max="5"
                  :step="0.5"
                  color="amber"
                  thumb-label
                  density="compact"
                  hide-details
                />
              </div>

              <div class="d-flex justify-space-between align-center mt-3">
                <v-btn variant="text" @click="clearFilters">{{ t('home.filter.clear') }}</v-btn>
                <div class="d-flex ga-2">
                  <v-btn variant="text" @click="filtersOpen = false">{{ t('home.filter.cancel') }}</v-btn>
                  <v-btn color="primary" variant="flat" @click="applyFilters">{{ t('home.filter.apply') }}</v-btn>
                </div>
              </div>
            </v-card>
          </v-dialog>
        </v-card>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { getHomeTagSuggest, searchByText } from "../../api";
import { getCategoryLabel } from "../../utils/categoryPresets";
import PreviewCard from "./PreviewCard.vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  seedTag: { type: String, default: "" },
  isMobile: { type: Boolean, default: false },
  previewUiMode: { type: String, default: "phone" },
  previewDrawerSide: { type: String, default: "right" },
  desktopAnchorX: { type: Number, default: 0 },
  desktopAnchorY: { type: Number, default: 0 },
  categoryDefs: { type: Array, default: () => [] },
  config: { type: Object, default: () => ({}) },
  allowDeleteLocal: { type: Boolean, default: false },
  t: { type: Function, required: true },
  getGalleryTitle: { type: Function, required: true },
  itemSubtitle: { type: Function, required: true },
  itemHoverTags: { type: Function, required: true },
  isFavorited: { type: Function, required: true },
  itemRatingValue: { type: Function, required: true },
  categoryLabel: { type: Function, default: () => "" },
  categoryBadgeStyle: { type: Function, default: () => ({}) },
});

const emit = defineEmits([
  "update:modelValue",
  "close-all",
  "start-reader",
  "start-reader-at-page",
  "favorite-toggle",
  "delete-local",
  "set-rating",
  "hydrated",
  "image-error",
  "quick-add-tag",
]);

const open = computed({
  get: () => !!props.modelValue,
  set: (v) => emit("update:modelValue", !!v),
});

const presentationMode = computed(() => {
  const raw = String(props.previewUiMode || "phone").trim().toLowerCase();
  if (raw === "desktop") return "desktop";
  if (raw === "tablet") return "tablet";
  return "phone";
});

const shellClass = computed(() => {
  if (presentationMode.value === "desktop") return "tag-explore-shell-desktop";
  if (presentationMode.value === "tablet") {
    return props.previewDrawerSide === "left"
      ? "tag-explore-shell-tablet drawer-left"
      : "tag-explore-shell-tablet drawer-right";
  }
  return "tag-explore-shell-phone";
});

const previewBodyClass = computed(() => {
  return {
    "preview-body-phone": presentationMode.value === "phone",
  };
});

const shellStyle = computed(() => {
  if (presentationMode.value !== "desktop") return {};
  const x = Number(props.desktopAnchorX || 0);
  const y = Number(props.desktopAnchorY || 0);
  if (x > 0 || y > 0) {
    return {
      left: `${Math.max(12, x)}px`,
      top: `${Math.max(12, y)}px`,
    };
  }
  return { right: "20px", top: "80px" };
});

const bodyRef = ref(null);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref("");
const items = ref([]);
const cursor = ref("");
const hasMore = ref(false);
const searchQuery = ref("");
const filtersOpen = ref(false);
const filters = ref({ categories: [], tags: [], minRating: 0 });
const filterTagInput = ref("");
const filterTagSuggestions = ref([]);
const seedStack = ref([]);
const previewItem = ref(null);
const seedScrollTopMap = ref(new Map());
const pendingRestoreSeed = ref("");

const pushedOpenState = ref(false);
const pushedPreviewState = ref(false);

const currentSeed = computed(() => {
  const stack = Array.isArray(seedStack.value) ? seedStack.value : [];
  return stack.length ? String(stack[stack.length - 1] || "") : "";
});

function initFromSeed(tag) {
  const seed = String(tag || "").trim();
  if (!seed) return;
  error.value = "";
  previewItem.value = null;
  searchQuery.value = "";
  seedStack.value = [seed];
  filters.value = {
    categories: (props.categoryDefs || []).map((x) => x.key),
    tags: [seed],
    minRating: 0,
  };
  cursor.value = "";
  hasMore.value = false;
  items.value = [];
  seedScrollTopMap.value = new Map();
  pendingRestoreSeed.value = "";
  loadExplore(true).catch(() => null);
}

function rememberCurrentSeedScroll() {
  const seed = String(currentSeed.value || "").trim().toLowerCase();
  const el = bodyRef.value;
  if (!seed || !el) return;
  const next = new Map(seedScrollTopMap.value || []);
  next.set(seed, Math.max(0, Number(el.scrollTop || 0)));
  seedScrollTopMap.value = next;
}

function restoreScrollForSeed(seedRaw) {
  const seed = String(seedRaw || "").trim().toLowerCase();
  if (!seed) return;
  const top = Number((seedScrollTopMap.value || new Map()).get(seed) || 0);
  nextTick(() => {
    const el = bodyRef.value;
    if (!el) return;
    el.scrollTop = Math.max(0, top);
    if (top > 0) {
      requestAnimationFrame(() => {
        const el2 = bodyRef.value;
        if (el2) el2.scrollTop = Math.max(0, top);
      });
    }
  });
}

function pushOverlayHistory(kind) {
  if (typeof window === "undefined") return;
  try {
    window.history.pushState({ __tagExplore: kind }, "");
  } catch {
    // no-op
  }
}

function onPopState() {
  if (!open.value) return;
  if (filtersOpen.value) {
    filtersOpen.value = false;
    return;
  }
  if (previewItem.value) {
    closeItemPreview();
    pushedPreviewState.value = false;
    return;
  }
  open.value = false;
}

onMounted(() => {
  if (typeof window !== "undefined") {
    window.addEventListener("popstate", onPopState);
  }
});

onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("popstate", onPopState);
  }
});

watch(
  () => [props.modelValue, props.seedTag],
  ([openNow, seed]) => {
    if (!openNow) return;
    initFromSeed(seed);
  },
  { immediate: true },
);

watch(
  () => open.value,
  (v) => {
    if (v) {
      if (!pushedOpenState.value) {
        pushOverlayHistory("overlay");
        pushedOpenState.value = true;
      }
      return;
    }
    filtersOpen.value = false;
    previewItem.value = null;
    pushedOpenState.value = false;
    pushedPreviewState.value = false;
  },
);

watch(
  () => !!previewItem.value,
  (v) => {
    if (v) {
      if (open.value && !pushedPreviewState.value) {
        pushOverlayHistory("preview");
        pushedPreviewState.value = true;
      }
      return;
    }
    pushedPreviewState.value = false;
  },
);

function effectiveCategories() {
  const all = (props.categoryDefs || []).map((x) => x.key);
  const selected = Array.isArray(filters.value?.categories) ? filters.value.categories : [];
  if (selected.length === all.length) return [];
  if (selected.length === 0) return ["__none__"];
  return selected;
}

async function loadExplore(reset = false) {
  if (!open.value) return;
  if (loading.value || loadingMore.value) return;
  if (!reset && !hasMore.value) return;
  if (reset) loading.value = true;
  else loadingMore.value = true;
  error.value = "";
  try {
    const params = { limit: 24 };
    if (!reset && cursor.value) params.cursor = cursor.value;
    const cats = effectiveCategories();
    if (cats.length) params.include_categories = cats.join(",");
    const tags = Array.isArray(filters.value?.tags)
      ? filters.value.tags.map((x) => String(x || "").trim()).filter(Boolean)
      : [];
    if (!tags.length && currentSeed.value) tags.push(currentSeed.value);
    if (tags.length) params.include_tags = tags.join(",");
    const minRating = Number(filters.value?.minRating || 0);
    if (Number.isFinite(minRating) && minRating > 0) params.min_rating = minRating;
    const q = String(searchQuery.value || "").trim();
    if (q) params.q = q;

    const res = await searchByText({
      query: q || (tags[0] || ""),
      scope: "works",
      limit: 24,
      use_llm: false,
      ui_lang: String(props.config?.DATA_UI_LANG || "zh"),
      include_categories: cats,
      include_tags: tags,
      min_rating: minRating,
    });
    const rows = Array.isArray(res?.items) ? res.items : [];
    if (reset) items.value = rows;
    else items.value = [...(items.value || []), ...rows];
    cursor.value = String(res?.next_cursor || "");
    hasMore.value = !!res?.has_more;
  } catch (e) {
    error.value = String(e?.response?.data?.detail || e);
  } finally {
    loading.value = false;
    loadingMore.value = false;
    setTimeout(() => {
      maybeLoadMoreForViewport();
    }, 0);
  }
}

function runSearch() {
  previewItem.value = null;
  loadExplore(true).catch(() => null);
}

function onBackdropSelf() {
  open.value = false;
}

function onBack() {
  if (previewItem.value) {
    closeItemPreview();
    return;
  }
  const stack = Array.isArray(seedStack.value) ? [...seedStack.value] : [];
  if (stack.length > 1) {
    rememberCurrentSeedScroll();
    stack.pop();
    const prev = String(stack[stack.length - 1] || "").trim();
    seedStack.value = stack;
    filters.value.tags = prev ? [prev] : [];
    searchQuery.value = "";
    pendingRestoreSeed.value = prev;
    loadExplore(true).catch(() => null);
    return;
  }
  open.value = false;
  filtersOpen.value = false;
  previewItem.value = null;
}

function openItemPreview(item) {
  rememberCurrentSeedScroll();
  previewItem.value = item || null;
}

function closeItemPreview() {
  previewItem.value = null;
  restoreScrollForSeed(currentSeed.value);
}

function isTagActive(tag) {
  const t = String(tag || "").trim().toLowerCase();
  return (filters.value?.tags || []).map((x) => String(x || "").trim().toLowerCase()).includes(t);
}

function exploreItemKey(item) {
  const it = (item && typeof item === "object") ? item : {};
  const arcid = String(it.arcid || "").trim();
  if (arcid) return `works:${arcid}`;
  return String(it.id || "").trim();
}

function mergeHydratedItem(current, incoming) {
  const cur = (current && typeof current === "object") ? current : {};
  const row = (incoming && typeof incoming === "object") ? incoming : {};
  return {
    ...cur,
    ...row,
    meta: { ...(cur.meta || {}), ...(row.meta || {}) },
    raw: { ...(cur.raw || {}), ...(row.raw || {}) },
    tags: Array.isArray(row.tags) ? row.tags : (cur.tags || []),
    tags_translated: Array.isArray(row.tags_translated) ? row.tags_translated : (cur.tags_translated || []),
  };
}

function onPreviewHydrated(item) {
  const key = exploreItemKey(item);
  if (!key) {
    emit("hydrated", item);
    return;
  }
  if (exploreItemKey(previewItem.value) === key && previewItem.value) {
    previewItem.value = mergeHydratedItem(previewItem.value, item);
  }
  items.value = (items.value || []).map((row) => {
    if (exploreItemKey(row) !== key) return row;
    return mergeHydratedItem(row, item);
  });
  emit("hydrated", item);
}

async function onApplyTagFilter(payload) {
  const tag = String(typeof payload === "object" && payload !== null ? (payload.tag || "") : (payload || "")).trim();
  if (!tag) return;
  rememberCurrentSeedScroll();
  const stack = Array.isArray(seedStack.value) ? [...seedStack.value] : [];
  if (!stack.length || String(stack[stack.length - 1] || "").toLowerCase() !== tag.toLowerCase()) {
    stack.push(tag);
  }
  seedStack.value = stack;
  filters.value.tags = [tag];
  searchQuery.value = "";
  previewItem.value = null;
  await loadExplore(true);
}

function toggleCategory(key) {
  const k = String(key || "");
  const set = new Set(filters.value.categories || []);
  if (set.has(k)) set.delete(k);
  else set.add(k);
  filters.value.categories = Array.from(set);
}

function selectAllCategories() {
  filters.value.categories = (props.categoryDefs || []).map((x) => x.key);
}

function clearAllCategories() {
  filters.value.categories = [];
}

function categoryStyle(key, color) {
  const on = (filters.value.categories || []).includes(key);
  return {
    backgroundColor: on ? color : "#424242",
    color: "#ffffff",
    opacity: on ? 1 : 0.45,
  };
}

function clearFilters() {
  const seed = String(currentSeed.value || "").trim();
  filters.value = {
    categories: (props.categoryDefs || []).map((x) => x.key),
    tags: seed ? [seed] : [],
    minRating: 0,
  };
  filterTagInput.value = "";
  filterTagSuggestions.value = [];
}

function applyFilters() {
  filtersOpen.value = false;
  previewItem.value = null;
  loadExplore(true).catch(() => null);
}

async function onTagSearch(q) {
  filterTagInput.value = String(q || "");
  const kw = String(q || "").trim();
  if (kw.length < 2) {
    filterTagSuggestions.value = [];
    return;
  }
  try {
    const res = await getHomeTagSuggest({ q: kw, limit: 10, ui_lang: String(props.config?.DATA_UI_LANG || "zh") });
    filterTagSuggestions.value = Array.isArray(res?.items) ? res.items : [];
  } catch {
    filterTagSuggestions.value = [];
  }
}

function onBodyScroll(event) {
  const el = event?.target || bodyRef.value;
  if (!el) return;
  rememberCurrentSeedScroll();
  if (loading.value || loadingMore.value || !hasMore.value) return;
  const nearBottom = Number(el.scrollTop || 0) + Number(el.clientHeight || 0) >= Number(el.scrollHeight || 0) - 180;
  if (!nearBottom) return;
  loadExplore(false).catch(() => null);
}

function maybeLoadMoreForViewport() {
  if (previewItem.value) return;
  const el = bodyRef.value;
  if (!el || loading.value || loadingMore.value || !hasMore.value) return;
  const canScroll = Number(el.scrollHeight || 0) > Number(el.clientHeight || 0) + 8;
  if (canScroll) return;
  loadExplore(false).catch(() => null);
}

function loadMoreManual() {
  if (!hasMore.value || loading.value || loadingMore.value) return;
  loadExplore(false).catch(() => null);
}

watch(
  () => `${currentSeed.value}|${items.value.length}`,
  () => {
    const seed = String(pendingRestoreSeed.value || "").trim();
    if (!seed) return;
    if (seed.toLowerCase() !== String(currentSeed.value || "").trim().toLowerCase()) return;
    restoreScrollForSeed(seed);
    pendingRestoreSeed.value = "";
  },
);
</script>

<style scoped>
.tag-explore-shell {
  background: rgba(var(--v-theme-background), 0.98);
  display: flex;
  flex-direction: column;
}

.tag-explore-host {
  position: fixed;
  inset: 0;
  z-index: 2600;
  background: rgba(9, 12, 18, 0.32);
  overscroll-behavior: contain;
}

.tag-explore-host.mode-phone {
  background: rgba(9, 12, 18, 0.4);
}

.tag-explore-shell-phone {
  position: fixed;
  inset: 0;
  min-height: 100vh;
}

.tag-explore-shell-tablet {
  position: fixed;
  top: 0;
  bottom: 0;
  width: min(520px, 94vw);
  min-height: 100vh;
  border-left: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  box-shadow: -12px 0 32px rgba(0, 0, 0, 0.45);
}

.tag-explore-shell-tablet.drawer-right {
  right: 0;
}

.tag-explore-shell-tablet.drawer-left {
  left: 56px;
  border-left: 0;
  border-right: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  box-shadow: 12px 0 32px rgba(0, 0, 0, 0.45);
}

.tag-explore-shell-desktop {
  position: fixed;
  width: min(560px, 94vw);
  max-width: min(560px, 94vw);
  max-height: min(90vh, calc(100dvh - 24px));
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.14);
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.42);
}

.tag-explore-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  background: rgba(var(--v-theme-surface), 0.9);
}

.tag-explore-search {
  flex: 1;
  min-width: 220px;
}

.tag-explore-seed-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tag-explore-body {
  flex: 1;
  overflow: auto;
  overscroll-behavior: contain;
  overscroll-behavior-y: contain;
  -webkit-overflow-scrolling: touch;
}

.tag-explore-item-card {
  cursor: pointer;
}

.tag-explore-preview-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: rgba(var(--v-theme-background), 0.98);
  overscroll-behavior: contain;
}

.tag-explore-preview-body :deep(.preview-card) {
  width: 100%;
  max-height: none;
  height: 100%;
  border-radius: 0;
}

.tag-explore-preview-body.preview-body-phone :deep(.preview-card) {
  width: 100vw;
}

.tag-explore-fade-enter-active,
.tag-explore-fade-leave-active {
  transition: opacity 0.18s ease;
}

.tag-explore-fade-enter-from,
.tag-explore-fade-leave-to {
  opacity: 0;
}

.tag-explore-slide-up-enter-active,
.tag-explore-slide-up-leave-active {
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.22s ease;
}

.tag-explore-slide-up-enter-from,
.tag-explore-slide-up-leave-to {
  transform: translateY(24px);
  opacity: 0;
}

@media (max-width: 960px) {
  .tag-explore-toolbar {
    gap: 6px;
  }

  .tag-explore-search {
    min-width: 0;
    width: 100%;
    order: 2;
  }
}
</style>
