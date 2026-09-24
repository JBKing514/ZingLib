<template>
  <v-card
    ref="cardEl"
    class="pa-2 hover-preview-card preview-card"
    variant="flat"
    @scroll.passive="onCardScroll"
    @touchstart.stop
    @touchmove.stop
    @touchend.stop
    @touchcancel.stop
    @pointerdown.stop
  >
    <div class="preview-cover-wrap mb-2" @contextmenu.prevent>
      <img
        v-if="item?.thumb_url"
        :src="item.thumb_url"
        alt="cover"
        class="preview-cover"
        draggable="false"
        @dragstart.prevent
        @error="emit('image-error', item)"
      />
      <div v-else class="preview-cover preview-fallback"><v-icon size="42">mdi-image-outline</v-icon></div>
    </div>

    <div class="text-body-2 font-weight-medium mb-1 cover-link-title">{{ getGalleryTitle(item) }}</div>

    <div v-if="canRateItem || resolvedRating !== null" class="d-flex align-center ga-1 mb-2">
      <v-rating
        :model-value="resolvedRating ?? 0"
        :readonly="!canRateItem"
        :hover="canRateItem"
        :clearable="canRateItem"
        half-increments
        density="compact"
        :size="isMobile ? 'default' : 'x-small'"
        color="amber"
        empty-icon="mdi-star-outline"
        full-icon="mdi-star"
        half-icon="mdi-star-half-full"
        @update:model-value="onRatingChange"
      />
      <span class="text-caption text-medium-emphasis">{{ (resolvedRating ?? 0).toFixed(1) }}</span>
    </div>


    <div class="d-flex ga-2 mb-2 flex-wrap">
      <v-btn
        v-if="canStartReader"
        size="small"
        color="primary"
        variant="tonal"
        prepend-icon="mdi-eye-outline"
        @click.stop="onStartReaderClick"
      >{{ t('reader.start') }}</v-btn>
      <v-btn
        v-if="canStartReader && resumePage > 1"
        size="small"
        color="secondary"
        variant="outlined"
        prepend-icon="mdi-history"
        @click.stop="onResumeClick"
      >{{ t('reader.resume_at', { page: resumePage }) }}</v-btn>
      <v-btn
        v-if="String(item?.source || '') === 'works'"
        size="small"
        :color="isFavorited ? 'warning' : 'secondary'"
        variant="tonal"
        :prepend-icon="isFavorited ? 'mdi-star' : 'mdi-star-outline'"
        @click.stop="emit('favorite-toggle', item)"
      >{{ isFavorited ? t('home.favorite.on') : t('home.favorite.off') }}</v-btn>
      <v-btn
        v-if="allowDeleteLocal && String(item?.source || '') === 'works'"
        size="small"
        color="error"
        variant="tonal"
        prepend-icon="mdi-delete-outline"
        @click.stop="emit('delete-local', item)"
      >{{ t('common.delete') }}</v-btn>
    </div>

    <div v-if="item?.category" class="text-caption text-medium-emphasis mb-1">{{ item.category }}</div>
    <div class="mb-2">
      <div v-for="group in groupedDisplayTags" :key="`${item?.id}-${group.key}`" class="tag-namespace-row" :class="{ 'tag-namespace-row-no-pill': !group.label }">
        <span v-if="group.label" class="tag-namespace-pill" :style="group.pillStyle">{{ group.label }}</span>
        <div class="tag-chip-list">
          <v-chip
            v-for="row in group.items"
            :key="`${item?.id}-${group.key}-${row.tag}`"
            size="x-small"
            variant="outlined"
            class="hover-tag"
            :class="{ active: isTagActive(row.tag) }"
            @click.stop="emit('apply-tag-filter', { tag: row.tag, source: String(item?.source || '') })"
          >{{ row.label }}</v-chip>
        </div>
      </div>
      <div v-if="String(item?.source || '') === 'works'" class="tag-quick-add-row">
        <v-chip
          size="x-small"
          class="mr-1 mb-1 dashed-add-btn"
          variant="outlined"
          @mousedown.stop.prevent
          @click.stop.prevent="onQuickAddChipClick"
        >
          <v-icon size="small" class="mr-1">mdi-plus</v-icon>
          {{ t('home.preview.quick_add_tag') }}
        </v-chip>
      </div>
    </div>

    <div v-if="renderedThumbSlots.length || thumbLoading || initialThumbLoading" class="preview-thumb-grid mt-2">
      <button
        v-for="th in renderedThumbSlots"
        :key="`${item?.id}-p-${th.page}-${th.__placeholder ? 'ph' : 'ok'}`"
        class="preview-thumb-item"
        :class="{ masked: item?.source === 'works', placeholder: th.__placeholder, shimmer: th.__placeholder && !deferLoadingActive }"
        type="button"
        :disabled="th.__placeholder"
        @click.stop="onThumbClick(th)"
      >
        <div v-if="th.__placeholder" class="preview-thumb-skeleton" />
        <template v-else>
          <img
            v-if="!canUseSprite(th)"
            :src="th.src"
            :alt="`p${th.page}`"
            class="preview-thumb-img"
            loading="lazy"
            decoding="async"
            fetchpriority="low"
            draggable="false"
            @dragstart.prevent
          />
          <div
            v-else
            class="preview-thumb-sprite"
            :style="spriteStyle(th)"
          />
        </template>
        <span class="preview-thumb-label">{{ th.page }}</span>
      </button>
      <div v-if="thumbLoading || initialThumbLoading" class="preview-thumb-loading">...</div>
    </div>

  </v-card>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { getReaderManifest } from "../../api";
import { useSettingsStore } from "../../stores/settingsStore";
import { usePreviewProgressStore } from "../../stores/previewProgressStore";
import {
  getNamespaceColor,
  getNamespaceDisplayLabel,
  normalizeNamespaceKey,
} from "../../utils/tagNamespaces";

const props = defineProps({
  item: { type: Object, default: null },
  isMobile: { type: Boolean, default: false },
  hideStartButton: { type: Boolean, default: false },
  isFavorited: { type: Boolean, default: false },
  t: { type: Function, required: true },
  getGalleryTitle: { type: Function, required: true },
  itemHoverTags: { type: Function, required: true },
  isTagFilterActive: { type: Function, required: true },
  itemRatingValue: { type: Function, default: null },
  allowDeleteLocal: { type: Boolean, default: false },
  deferThumbLoadMs: { type: Number, default: 0 },
});

const emit = defineEmits(["start-reader", "start-reader-at-page", "favorite-toggle", "delete-local", "toggle-tag", "apply-tag-filter", "set-rating", "image-error", "meta-updated", "quick-add-tag"]);
const settingsStore = useSettingsStore();
const previewProgressStore = usePreviewProgressStore();

const thumbItems = ref([]);
const renderedCount = ref(0);
const thumbLoading = ref(false);
const initialThumbLoading = ref(false);
const deferLoadingActive = ref(false);
// The card is its own scroll container, so it survives the gallery switch that
// swaps `item` -- and would otherwise keep the previous gallery's offset.
const cardEl = ref(null);
let warmLoadTimer = null;

// A preview only ever shows its page images in ~140px grid cells, while the
// reader renders full quality (1080px / q85 WEBP) -- about 9x the pixels. The
// page endpoint takes the quality per request and keeps no cache, so asking for
// "low" (360px / q60) here cannot degrade or poison what the reader serves.
const THUMB_PAGE_QUALITY = "low";
// Bumped by every cancel. Async thumbnail work re-checks it before touching
// state, so a manifest that lands after the user already left cannot refill the
// grid behind their back.
let loadGeneration = 0;
// True while the grid is deliberately stopped (reader entry / deactivation).
let thumbCancelled = false;
const debugSignals = computed(() => (props.item && typeof props.item.signals === "object" ? props.item.signals : {}));
const tagContribMap = computed(() => {
  const terms = Array.isArray(debugSignals.value?.tag_terms) ? debugSignals.value.tag_terms : [];
  const m = new Map();
  const put = (k, payload) => {
    const key = String(k || "").trim().toLowerCase();
    if (!key) return;
    if (m.has(key)) return;
    m.set(key, payload || { weightPct: 0, raw: 0 });
  };
  for (const row of terms) {
    const payload = {
      weightPct: Number(row?.weight_pct ?? row?.contrib_pct ?? 0),
      raw: Number(row?.raw ?? 0),
    };
    put(row?.tag, payload);
    put(row?.tag_short, payload);
    put(row?.translated, payload);
    put(row?.translated_short, payload);
  }
  return m;
});
const customNamespaceDefs = computed(() => Array.isArray(settingsStore.customNamespaceDefs) ? settingsStore.customNamespaceDefs : []);
const canRateItem = computed(() => {
  const src = String(props.item?.source || "").trim();
  return src === "works";
});
const resolvedRating = computed(() => {
  if (typeof props.itemRatingValue === "function") {
    const v = Number(props.itemRatingValue(props.item || null));
    if (Number.isFinite(v)) return Math.max(0, Math.min(5, v));
  }
  const raw = props.item?.raw?.rating ?? props.item?.meta?.rating ?? props.item?.rating;
  const n = Number(raw);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(5, n));
});
const displayTags = computed(() => {
  const tags = props.itemHoverTags(props.item || {});
  return tags.map((tag) => {
    const t = String(tag || "").trim();
    if (!t) return { tag: t, label: t };
    if (!debugSignals.value || !Object.keys(debugSignals.value).length) return { tag: t, label: t };
    const row = tagContribMap.value.get(t.toLowerCase()) || {};
    const pct = Number(row?.weightPct || 0);
    const raw = Number(row?.raw || 0);
    if ((!Number.isFinite(pct) || pct <= 0) && (!Number.isFinite(raw) || raw <= 0)) return { tag: t, label: t };
    if (Number.isFinite(pct) && pct > 0) {
      return { tag: t, label: `${t} (${pct.toFixed(1)}% | ${fmtNum(raw)})` };
    }
    return { tag: t, label: `${t} (${fmtNum(raw)})` };
  }).filter((x) => {
    const raw = String(x.tag || "").trim();
    if (!raw) return false;
    return !shouldHideSystemTag(raw);
  });
});
const groupedDisplayTags = computed(() => {
  const out = [];
  const idx = new Map();
  for (const row of displayTags.value) {
    const part = parseTagPartsResolved(row.tag);
    const key = part.key;
    if (!idx.has(key)) {
      idx.set(key, out.length);
      out.push({
        key,
        label: displayNsLabelResolved(part.nsLabel, { allowRaw: !!part.allowRawNsLabel }),
        pillStyle: namespacePillStyleResolved(key),
        items: [],
      });
    }
    const g = out[idx.get(key)];
    g.items.push({
      tag: row.tag,
      label: part.tagLabel,
    });
  }
  return out;
});
const placeholderCount = 20;
const renderedThumbItems = computed(() => thumbItems.value.slice(0, Math.max(0, Number(renderedCount.value || 0))));
const renderedThumbSlots = computed(() => {
  const loaded = renderedThumbItems.value;
  const loadingAny = !!thumbLoading.value || !!initialThumbLoading.value;
  if (!loadingAny) return loaded.map((x) => ({ ...x, __placeholder: false }));
  const base = Math.max(loaded.length, placeholderCount);
  const slots = [];
  for (let i = 0; i < base; i += 1) {
    const row = loaded[i];
    if (row) slots.push({ ...row, __placeholder: false });
    else slots.push({ page: i + 1, __placeholder: true, mode: "image", src: "" });
  }
  return slots;
});
const canStartReader = computed(() => {
  if (props.hideStartButton) return false;
  const it = props.item || {};
  if (String(it.source || "") === "works") return !!String(it.arcid || "").trim();
  return false;
});
const resumePage = computed(() => previewProgressStore.resumePage(props.item));

function isTagActive(tag) {
  return props.isTagFilterActive(tag);
}

function shouldHideSystemTag(rawTag) {
  const s = String(rawTag || "").trim().toLowerCase();
  if (!s) return true;
  if (s === "favorited") return true;
  if (s.startsWith("system:favorite")) return true;
  if (s.startsWith("system:reader")) return true;
  if (s.startsWith("system:bookmark")) return true;
  if (s.startsWith("system:progress")) return true;
  return false;
}

function canonicalNs(raw) {
  const s = String(raw || "").trim();
  const lower = s.toLowerCase();
  const normalized = normalizeNamespaceKey(s, { fallbackToOther: false });
  if (normalized) return normalized;
  if (lower.startsWith("date_")) return "date";
  if (lower.includes("uploader")) return "uploader";
  if (lower.includes("source")) return "source";
  if (lower.includes("date") || lower.includes("time")) return "date";
  return "other";
}

function displayNsLabel(nsKey) {
  const key = canonicalNs(nsKey);
  if (typeof props.t !== "function") return "";
  const k = `home.tag_ns.${key}`;
  const translated = String(props.t(k) || "").trim();
  if (!translated || translated === k) return "";
  return translated;
}

function parseTagParts(rawTag) {
  const raw = String(rawTag || "").trim();
  if (!raw) return { key: "misc", nsLabel: "misc", tagLabel: raw };
  if (raw.toLowerCase().startsWith("user:")) {
    const parts = raw.split(":", 3);
    if (parts.length >= 3) {
      const ns = canonicalNs(parts[1]);
      const val = String(parts.slice(2).join(":") || "").trim();
      if (val) return { key: ns, nsLabel: ns, tagLabel: val };
    }
  }
  const sep = raw.includes(":") ? ":" : "";
  if (!sep) return { key: "misc", nsLabel: "misc", tagLabel: raw };
  const pos = raw.indexOf(sep);
  const ns = raw.slice(0, pos).trim();
  const val = raw.slice(pos + 1).trim();
  if (!ns || !val) return { key: "misc", nsLabel: "misc", tagLabel: raw };
  const nsKey = canonicalNs(ns);
  return {
    key: nsKey,
    nsLabel: nsKey,
    tagLabel: val,
  };
}

function namespaceToneClass(nsKey) {
  const k = canonicalNs(nsKey);
  if (k === "parody") return "tone-peach";
  if (k === "character") return "tone-indigo";
  if (k === "group") return "tone-lavender";
  if (k === "artist") return "tone-mint";
  if (k === "female") return "tone-violet";
  if (k === "male") return "tone-blue";
  if (k === "language") return "tone-sky";
  if (k === "reclass") return "tone-amber";
  if (k === "uploader") return "tone-neutral";
  if (k === "source") return "tone-neutral";
  if (k === "date") return "tone-neutral";
  if (k === "other") return "tone-neutral";
  return "tone-neutral";
}

function resolveNamespaceKey(raw) {
  const normalized = normalizeNamespaceKey(raw, { fallbackToOther: false });
  if (normalized) return normalized;
  return canonicalNs(raw);
}

function displayNsLabelResolved(nsKey, options = {}) {
  const key = resolveNamespaceKey(nsKey);
  const label = getNamespaceDisplayLabel(key, props.t, customNamespaceDefs.value);
  if (label) return label;
  return options.allowRaw ? key : "";
}

function parseTagPartsResolved(rawTag) {
  const raw = String(rawTag || "").trim();
  if (!raw) return { key: "misc", nsLabel: "misc", tagLabel: raw, allowRawNsLabel: false };
  if (raw.toLowerCase().startsWith("user:")) {
    const parts = raw.split(":", 3);
    if (parts.length >= 3) {
      const ns = resolveNamespaceKey(parts[1]);
      const val = String(parts.slice(2).join(":") || "").trim();
      if (val) return { key: ns, nsLabel: ns, tagLabel: val, allowRawNsLabel: true };
    }
  }
  const sep = raw.includes(":") ? ":" : "";
  if (!sep) return { key: "misc", nsLabel: "misc", tagLabel: raw, allowRawNsLabel: false };
  const pos = raw.indexOf(sep);
  const ns = raw.slice(0, pos).trim();
  const val = raw.slice(pos + 1).trim();
  if (!ns || !val) return { key: "misc", nsLabel: "misc", tagLabel: raw, allowRawNsLabel: false };
  const nsKey = resolveNamespaceKey(ns);
  return {
    key: nsKey,
    nsLabel: nsKey,
    tagLabel: val,
    allowRawNsLabel: false,
  };
}

function namespacePillStyleResolved(nsKey) {
  const k = resolveNamespaceKey(nsKey);
  return {
    backgroundColor: getNamespaceColor(k, customNamespaceDefs.value),
    borderColor: "rgba(15, 23, 42, 0.3)",
    color: "#ffffff",
  };
}

function onQuickAddChipClick() {
  emit("quick-add-tag", props.item || null);
}

function fmtNum(v) {
  const n = Number(v || 0);
  if (!Number.isFinite(n)) return "0";
  return n.toFixed(4);
}

function onRatingChange(v) {
  if (!canRateItem.value) return;
  const n = Number(v);
  const rating = Number.isFinite(n) ? Math.max(0, Math.min(5, Math.round(n * 2) / 2)) : null;
  emit("set-rating", { item: props.item, rating });
}

async function loadThumbs(generation) {
  const it = props.item || {};
  const arcid = String(it.arcid || "").trim();
  if (String(it.source || "") !== "works" || !arcid) {
    if (generation === loadGeneration) initialThumbLoading.value = false;
    return;
  }
  try {
    const m = await getReaderManifest(arcid);
    // The user may have opened the reader while this was still in flight;
    // dropping the result leaves the <img> rows unmounted, and an unmounted
    // <img> is how the browser is told to drop its queued page requests.
    if (generation !== loadGeneration) return;
    const n = Math.max(0, Number(m?.page_count || 0));
    thumbItems.value = Array.from({ length: n }).map((_, i) => ({
      page: i + 1,
      mode: "image",
      src: `/api/reader/${encodeURIComponent(arcid)}/page/${i + 1}?mode=${THUMB_PAGE_QUALITY}`,
    }));
  } catch {
    if (generation === loadGeneration) thumbItems.value = [];
  } finally {
    if (generation === loadGeneration) initialThumbLoading.value = false;
  }
}

/**
 * Stop the thumbnail grid. This is the whole point of the component's exit
 * paths: every queued thumbnail competes with the reader the user is trying to
 * open, for both the browser's per-origin connections and the server's image
 * threadpool. Emptying the rows unmounts the <img> elements so the browser drops
 * the queued loads, and the generation bump retires whatever is already in
 * flight. Never blocks: callers cancel and then emit immediately.
 */
function cancelThumbLoad() {
  loadGeneration += 1;
  thumbCancelled = true;
  clearWarmLoadTimer();
  thumbItems.value = [];
  renderedCount.value = 0;
  thumbLoading.value = false;
  initialThumbLoading.value = false;
  deferLoadingActive.value = false;
}

function armThumbLoad() {
  thumbCancelled = false;
  renderedCount.value = placeholderCount;
  initialThumbLoading.value = true;
  scheduleWarmLoadInBackground();
}

function onStartReaderClick() {
  cancelThumbLoad();
  emit("start-reader", props.item);
}

function onResumeClick() {
  cancelThumbLoad();
  emit("start-reader-at-page", { item: props.item, page: resumePage.value });
}

function onThumbClick(th) {
  if (!th || th.__placeholder) return;
  cancelThumbLoad();
  emit("start-reader-at-page", { item: props.item, page: Number(th.page || 1) });
}

function ensureRenderMore(step = 18) {
  const n = Math.max(0, Number(renderedCount.value || 0));
  const total = thumbItems.value.length;
  if (n >= total) return;
  renderedCount.value = Math.min(total, n + Math.max(1, Number(step || 18)));
}

function onCardScroll(event) {
  const el = event?.target;
  if (!el) return;
  const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 120;
  if (!nearBottom) return;
  ensureRenderMore(20);
}

async function warmLoadInBackground() {
  const generation = loadGeneration;
  initialThumbLoading.value = true;
  renderedCount.value = Math.max(Number(renderedCount.value || 0), placeholderCount);
  await loadThumbs(generation);
  if (generation !== loadGeneration) return;
  renderedCount.value = Math.min(18, thumbItems.value.length);
}

function clearWarmLoadTimer() {
  if (!warmLoadTimer) return;
  clearTimeout(warmLoadTimer);
  warmLoadTimer = null;
}

function scheduleWarmLoadInBackground() {
  clearWarmLoadTimer();
  const delay = Math.max(0, Number(props.deferThumbLoadMs || 0));
  deferLoadingActive.value = delay > 0;
  if (delay <= 0) {
    warmLoadInBackground().catch(() => null);
    return;
  }
  warmLoadTimer = setTimeout(() => {
    warmLoadTimer = null;
    deferLoadingActive.value = false;
    warmLoadInBackground().catch(() => null);
  }, delay);
}

function spriteStyle(th) {
  const w = Math.max(20, Number(th?.width || 100));
  const h = Math.max(20, Number(th?.height || 140));
  const bgw = Number(th?.sheet_w || 0);
  const bgh = Number(th?.sheet_h || 0);
  const hasSheetSize = bgw > 1 && bgh > 1;
  return {
    backgroundImage: `url(${String(th?.src || th?.sprite_url || "")})`,
    backgroundRepeat: "no-repeat",
    backgroundPosition: `${Number(th?.offset_x || 0)}px ${Number(th?.offset_y || 0)}px`,
    backgroundSize: hasSheetSize ? `${bgw}px ${bgh}px` : "auto",
    width: `${w}px`,
    height: `${h}px`,
    maxWidth: "100%",
    margin: "0 auto",
  };
}

function canUseSprite(th) {
  if (String(th?.mode || "") !== "sprite") return false;
  const src = String(th?.src || th?.sprite_url || "").trim();
  if (!src) return false;
  const w = Number(th?.width || 0);
  const h = Number(th?.height || 0);
  const ox = Number(th?.offset_x || 0);
  const oy = Number(th?.offset_y || 0);
  const sw = Number(th?.sheet_w || 0);
  const sh = Number(th?.sheet_h || 0);
  const hasSpriteMeta = Math.abs(ox) > 0 || Math.abs(oy) > 0 || (sw > 1 && sh > 1);
  return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0 && hasSpriteMeta;
}

/**
 * Put the card back at the top. The tablet pane (and the phone sheet, and the
 * hover ghost) each keep one PreviewCard instance across galleries, so a switch
 * must clear the offset: the user asked for a new gallery, not for the middle of
 * the previous one. A component ref on a Vuetify component is the instance, and
 * `$el` is its single root -- the element that actually scrolls.
 */
function resetCardScroll() {
  const r = cardEl.value;
  if (!r) return;
  const el = r.$el || r;
  if (el && "scrollTop" in el) el.scrollTop = 0;
}

watch(
  () => `${props.item?.source || ""}:${props.item?.arcid || ""}`,
  () => {
    cancelThumbLoad();
    armThumbLoad();
    resetCardScroll();
  },
  { immediate: true },
);

// DashboardPage sits under <KeepAlive include="DashboardPage">, so entering the
// reader deactivates this card rather than unmounting it -- and Vue propagates
// that to nested children. Cancelling here covers every exit, not just the two
// buttons: browser Back/Forward and any programmatic navigation too.
onDeactivated(() => {
  cancelThumbLoad();
});

// Fires on mount too, but by then the immediate watcher above has already armed
// the grid, so the first activation is a no-op. It matters on the way back from
// the reader, where the grid was cancelled and needs re-arming.
onActivated(() => {
  if (thumbCancelled) armThumbLoad();
});

onBeforeUnmount(() => {
  cancelThumbLoad();
});
</script>

<style scoped>
.preview-card {
  width: min(460px, 92vw);
  max-height: 85vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  overscroll-behavior: contain;
  overscroll-behavior-y: contain;
  overscroll-behavior-x: contain;
  -webkit-overflow-scrolling: touch;
  touch-action: pan-y;
}

@media (max-width: 960px) {
  .preview-card {
    width: 100%;
    max-height: none;
    height: 100%;
    border-radius: 0;
  }
}

.preview-cover-wrap {
  width: 100%;
  height: clamp(220px, 42vh, 400px);
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  background: rgba(var(--v-theme-surface-variant), 0.62);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.preview-cover {
  max-width: 100%;
  max-height: 100%;
  width: 100%;
  height: 100%;
  object-fit: contain !important;
  object-position: center;
  display: block;
  user-select: none;
  -webkit-user-drag: none;
}

.preview-fallback {
  min-height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.preview-dislike-banner {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 8px;
  display: flex;
  justify-content: center;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.52), rgba(0, 0, 0, 0.08));
}

.rec-debug {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  padding: 6px 8px;
  background: rgba(12, 16, 22, 0.55);
}

.rec-debug-title {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.9);
  margin-bottom: 4px;
  font-weight: 600;
}

.rec-debug-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 8px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.8);
}

.tag-namespace-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 6px;
}

.tag-chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
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
  color: #0f172a;
  flex-shrink: 0;
}

.tone-neutral { background: #cbd5e1; border-color: #94a3b8; }
.tone-peach { background: #fb7185; border-color: #e11d48; }
.tone-indigo { background: #818cf8; border-color: #4338ca; }
.tone-lavender { background: #a78bfa; border-color: #6d28d9; }
.tone-mint { background: #34d399; border-color: #059669; }
.tone-violet { background: #c084fc; border-color: #9333ea; }
.tone-blue { background: #60a5fa; border-color: #2563eb; }
.tone-sky { background: #38bdf8; border-color: #0284c7; }
.tone-amber { background: #f59e0b; border-color: #b45309; }

.tag-quick-add-row {
  margin-top: 4px;
}

.dashed-add-btn {
  border: 1px dashed #2563eb;
  background: rgba(59, 130, 246, 0.08);
  color: #2563eb;
}

.dashed-add-btn:hover {
  background: rgba(59, 130, 246, 0.16);
}

.preview-thumb-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  padding-bottom: 16px;
}

.preview-thumb-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  border: 0;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(var(--v-theme-surface-variant), 0.45);
  padding: 0;
  min-height: 54px;
  background: linear-gradient(180deg, rgba(var(--v-theme-surface-variant), 0.45), rgba(var(--v-theme-surface), 0.85));
}

.preview-thumb-item > * {
  position: relative;
  z-index: 1;
}

.preview-thumb-item.masked::after {
  content: "";
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
  background: linear-gradient(to bottom, rgba(0, 0, 0, 0.02), rgba(0, 0, 0, 0.35));
}

:global(.v-theme--light) .preview-thumb-item.masked::after {
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0.05), rgba(148, 163, 184, 0.28));
}

:global(.v-theme--light) .preview-thumb-item {
  background: linear-gradient(180deg, rgba(241, 245, 249, 0.72), rgba(226, 232, 240, 0.92));
}

.preview-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: contain !important;
  object-position: center;
  display: block;
}

.preview-thumb-sprite {
  width: 100%;
  min-height: 54px;
  display: block;
}

.preview-thumb-label {
  position: absolute;
  right: 4px;
  bottom: 4px;
  font-size: 10px;
  line-height: 1;
  color: #fff;
  background: rgba(0, 0, 0, 0.7);
  border-radius: 999px;
  padding: 2px 6px;
}

.preview-thumb-loading {
  grid-column: 1 / -1;
  text-align: center;
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  padding: 8px 0;
}

.preview-thumb-item.placeholder {
  background: linear-gradient(90deg, rgba(var(--v-theme-surface-variant), 0.36) 0%, rgba(var(--v-theme-surface), 0.62) 50%, rgba(var(--v-theme-surface-variant), 0.36) 100%);
  background-size: 220% 100%;
}

.preview-thumb-item.placeholder.shimmer {
  animation: thumb-skeleton-shimmer 1.2s linear infinite;
}

.preview-thumb-skeleton {
  width: 100%;
  height: 100%;
  min-height: 54px;
}

@keyframes thumb-skeleton-shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
</style>
