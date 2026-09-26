<template>
  <div class="reader-root">
    <v-alert v-if="manifestError" type="warning" class="ma-4">
      {{ manifestError }}
      <v-btn variant="text" @click="router.push('/dashboard')">{{ settingsStore.t('tab.dashboard') }}</v-btn>
    </v-alert>
    <div
      v-if="manifestReady && readerMode === 'paged'"
      class="reader-stage"
      @click="toggleUi"
      @contextmenu.prevent
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @pointerleave="onPointerCancel"
    >
      <ReaderEndPanel
        v-if="onEndScreen"
        :next-title="nextGalleryEntry?.title || ''"
        :has-next="!!nextGalleryEntry"
        :items="endRecs"
        :loading="endRecsLoading"
        :error="endRecsError"
        :show-recs="endRecsEnabled"
        :t="settingsStore.t"
        @next-gallery="goNextGallery"
        @back-shelf="goHome"
        @open-item="openEndRec"
      />
      <template v-else>
      <transition :name="pageTransitionName" mode="out-in">
        <div :key="`p-${currentPage}-${spreadDouble ? 'd' : 's'}`" class="paged-spread" :class="{ double: spreadDouble }">
          <!-- The two slots are bound by *side*, not by page number. Flowing
               the lower page first puts page 3 in the left slot, so an RTL
               spread drew 3|2 -- the start page was right but the pair read
               left-to-right, which is precisely the complaint this layout
               answers. A manga spread has to open with the earlier page on the
               right, so the halves swap with the direction and nothing else
               about the order (start page, step, wheel strip) has to move. -->
          <img
            :src="pageRenderUrl(spreadLeftPage)"
            class="reader-image"
            :class="`fit-${fitMode}`"
            :style="readerFilterStyle"
            alt="page-left"
            draggable="false"
            @dragstart.prevent
            @load="onPagedImageLoad"
            @error="onPagedImageError"
          />
          <img
            v-if="spreadDouble && spreadRightPage > 0"
            :src="pageRenderUrl(spreadRightPage)"
            class="reader-image"
            :class="`fit-${fitMode}`"
            :style="readerFilterStyle"
            alt="page-right"
            draggable="false"
            @dragstart.prevent
            @load="onPagedImageLoad"
            @error="onPagedImageError"
          />
        </div>
      </transition>

      <div class="paged-window-ghost" aria-hidden="true">
        <img
          v-for="p in ghostPages"
          :key="`g-${p}`"
          :src="pageRenderUrl(p)"
          class="reader-image ghost-image"
          :class="`fit-${fitMode}`"
          :style="readerFilterStyle"
          alt="ghost"
          draggable="false"
          @dragstart.prevent
          @load="onGhostImageLoad(p)"
          @error="onGhostImageError(p)"
        />
      </div>

        <div v-if="pagedImageState.loading || pagedImageState.error" class="reader-load-overlay">
          <div class="reader-load-card" @click.stop>
          <template v-if="pagedImageState.loading">
            <v-progress-circular :model-value="pagedLoadProgress" color="white" :size="44" :width="4" />
            <div class="reader-load-percent">{{ pagedLoadProgress }}%</div>
          </template>
          <template v-else>
            <v-icon size="42" color="warning">mdi-image-off-outline</v-icon>
            <div class="reader-load-title">图片加载失败</div>
            <div class="reader-load-hint">点击中央区域重试</div>
            <v-btn size="small" color="warning" variant="tonal" prepend-icon="mdi-refresh" @click.stop="retryCurrentPage">立即重试</v-btn>
          </template>
        </div>
      </div>

      </template>

      <div v-if="tapToTurn" class="tap-zones" :class="{ vertical: isVertical }">
        <button class="tap-zone left" @click.stop="onLeftZone" aria-label="Turn from left zone" />
        <button class="tap-zone center" @click.stop="onCenterZone" aria-label="Retry or toggle UI" />
        <button class="tap-zone right" @click.stop="onRightZone" aria-label="Turn from right zone" />
      </div>
    </div>

    <div
      v-else-if="manifestReady"
      ref="continuousRoot"
      class="reader-stage continuous-stage"
      :class="{ 'continuous-btt': isBottomToTop }"
      @click="toggleUi"
      @contextmenu.prevent
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @pointerleave="onPointerCancel"
      @scroll.passive="onContinuousScrollEvent"
    >
      <div class="continuous-list">
        <div
          v-for="page in continuousPages"
          :key="`c-${page}`"
          class="continuous-page"
          :ref="(el) => setContinuousPageRef(el, page - 1)"
        >
          <img
            :src="continuousRenderUrl(page)"
            class="reader-image continuous-image"
            :class="`fit-${fitMode}`"
            :style="readerFilterStyle"
            alt="page"
            loading="lazy"
            draggable="false"
            @dragstart.prevent
            @load="onContinuousImageLoad(page)"
            @error="onContinuousImageError(page)"
          />
          <div v-if="isContinuousLoading(page) || isContinuousError(page)" class="continuous-overlay">
            <v-progress-circular v-if="isContinuousLoading(page)" indeterminate color="white" :size="28" :width="3" />
            <v-btn
              v-else
              size="x-small"
              color="warning"
              variant="tonal"
              prepend-icon="mdi-refresh"
              @click.stop="retryContinuousPage(page)"
            >重试</v-btn>
          </div>
        </div>
      </div>
      <ReaderEndPanel
        inline
        :next-title="nextGalleryEntry?.title || ''"
        :has-next="!!nextGalleryEntry"
        :items="endRecs"
        :loading="endRecsLoading"
        :error="endRecsError"
        :show-recs="endRecsEnabled"
        :t="settingsStore.t"
        @next-gallery="goNextGallery"
        @back-shelf="goHome"
        @open-item="openEndRec"
      />
    </div>

    <v-fade-transition>
      <ReaderTopBar
        v-if="showUi"
        :title="title || arcid"
        :settings-open="showQuickSettings"
        @back="closeReader"
        @home="goHome"
        @toggle-settings="showQuickSettings = !showQuickSettings"
      />
    </v-fade-transition>

    <v-fade-transition>
      <ReaderNavWheel
        v-if="showUi"
        :current-page="currentPage"
        :cursor-page="wheelCursorPage"
        :total-pages="totalPages"
        :wheel-pages="wheelPages"
        :wheel-position="wheelPosition"
        :wheel-radius="wheelRadius"
        :wheel-visible-range="wheelRange"
        :wheel-extent-pct="wheelExtentPct"
        :wheel-thumb-scale-pct="wheelThumbScalePct"
        :rtl="isRtl"
        @preview-page="onWheelPreviewPage"
        @jump-to-page="jumpToPage"
      />
    </v-fade-transition>

    <v-fade-transition>
      <ReaderQuickSettings
        v-if="showUi && showQuickSettings"
        :reader-mode="readerMode"
        :direction="direction"
        :spread-mode="spreadMode"
        :fit-mode="fitMode"
        :filter-preset="filterPreset"
        :image-quality-mode="readerImageQualityMode"
        :wheel-position="wheelPosition"
        :wheel-curve="wheelCurve"
        :wheel-range="wheelRangeValue"
        :wheel-extent-pct="wheelExtentPctValue"
        :wheel-thumb-scale-pct="wheelThumbScalePct"
        :page-anim-enabled="pageAnimEnabled"
        @update:reader-mode="readerMode = $event"
        @update:direction="direction = $event"
        @update:spread-mode="spreadMode = $event"
        @update:fit-mode="fitMode = $event"
        @update:filter-preset="filterPreset = $event"
        @update:image-quality-mode="readerImageQualityMode = $event"
        @update:wheel-position="wheelPosition = $event"
        @update:wheel-curve="wheelCurve = $event"
        @update:wheel-range="wheelRangeValue = $event"
        @update:wheel-extent-pct="wheelExtentPctValue = $event"
        @update:wheel-thumb-scale-pct="wheelThumbScalePct = $event"
        @update:page-anim-enabled="pageAnimEnabled = $event"
      />
    </v-fade-transition>

    <ReaderLongPressSearch
      v-model="longPressSearchOpen"
      :arcid="arcid"
      :current-page="currentPage"
      :current-image-src="pageImageUrl(currentPage)"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { closeReaderSession, getReaderManifest, getReaderSessionStatus, getReaderSimilar, openReaderSession, postReaderBookmarkSet, postReaderReadEvent, updateReaderSessionCursor } from "../api";
import { useSettingsStore } from "../stores/settingsStore";
import { useDashboardStore } from "../stores/dashboardStore";
import { usePreviewProgressStore } from "../stores/previewProgressStore";
import { useReaderQueueStore } from "../stores/readerQueueStore";
import { useViewportFit } from "../composables/useViewportFit";
import { useContinuousScroll } from "../composables/useContinuousScroll";
import ReaderNavWheel from "../components/reader/ReaderNavWheel.vue";
import ReaderTopBar from "../components/reader/ReaderTopBar.vue";
import ReaderQuickSettings from "../components/reader/ReaderQuickSettings.vue";
import ReaderLongPressSearch from "../components/reader/ReaderLongPressSearch.vue";
import ReaderEndPanel from "../components/reader/ReaderEndPanel.vue";
import { canOpenReaderRabbitHole, readerEndScreenPage } from "../utils/readerPageActions";
import { bindReaderShortcuts, parseTurnKeys, resolveKeyAction, resolveWheelAction } from "../utils/readerShortcuts";
import { readerResParam } from "../utils/readerRes";

const route = useRoute();
const router = useRouter();
const settingsStore = useSettingsStore();
const previewProgressStore = usePreviewProgressStore();
const readerQueue = useReaderQueueStore();

// Keep the session identity when the router has already switched to the dashboard.
const arcid = ref(String(route.params.arcid || "").trim());
const title = ref("");
const totalPages = ref(1);
const manifestError = ref('');
const currentPage = ref(1);
const wheelCursorPage = ref(1);
const showUi = ref(false);
const showQuickSettings = ref(false);
const transitionName = ref("reader-slide-next");
const touchStart = ref({ x: 0, y: 0 });
const continuousRoot = ref(null);
const longPressSearchOpen = ref(false);
const longPressTriggered = ref(false);
const localReaderSessionId = ref("");
const pagedImageState = ref({ page: 1, loading: true, error: false });
const pagedLoadProgress = ref(0);
const pageRetryNonce = ref({});
const continuousImageState = ref({});
const continuousRetryNonce = ref({});
const manifestReady = ref(false);
const localSessionStatus = ref(null);
// End-of-gallery screen. It is a *virtual* page one past the last one: the tap
// or swipe that crosses the last page lands here, and only the next forward
// action actually leaves the gallery -- so a stray tap at the end never dumps
// the reader into a different gallery.
const endRecs = ref([]);
const endRecsLoading = ref(false);
const endRecsError = ref("");
let endRecsSeq = 0;
let longPressTimer = 0;
let bookmarkSyncTimer = 0;
let lastReadEventAt = 0;
// Which gallery `lastReadEventAt` belongs to. The throttle exists to coalesce
// repeated events for *one* reading session, not to suppress a different
// gallery's first read -- and the router reuses this component when moving
// gallery -> gallery (a rabbit-hole suggestion, the end screen's "next"), so a
// bare timestamp swallowed the new gallery's history entry whenever the user
// switched within 15s.
let lastReadEventArcid = "";
let readQualifyTimer = 0;
let readTurnCount = 0;
let readDwellQualified = false;
let pagedProgressTimer = 0;
let localStatusPollTimer = 0;
const localPrefetchSeen = new Set();
const wheelThumbAspectMap = ref({});
const wheelThumbPreloadLoaders = new Map();
// The cursor the *thumbnail strip* is built from, which lags the slider by the
// settle delay. Keeping the two apart is the whole point: the slider has to track
// the finger, the <img> tags must not.
const wheelStripPage = ref(1);
let wheelStripSettleTimer = 0;

const tapToTurn = computed(() => settingsStore.config?.READER_TAP_TO_TURN !== false);
const swipeEnabled = computed(() => settingsStore.config?.READER_SWIPE_ENABLED !== false);

// Global shortcuts. The bound keys are read as one string each; parsing and the
// direction rules live in `utils/readerShortcuts.js` so they can be unit-tested
// without mounting the reader.
const shortcutKeys = computed(() => {
  const parse = (raw, fallback) => {
    const list = String(raw ?? "").trim() ? String(raw).trim() : fallback;
    return parseTurnKeys(list);
  };
  return {
    nextKeys: parse(settingsStore.config?.READER_KEY_NEXT, "d"),
    prevKeys: parse(settingsStore.config?.READER_KEY_PREV, "a"),
  };
});
const wheelPagingEnabled = computed(() => settingsStore.config?.READER_WHEEL_PAGING_ENABLED === true);
const wheelNatural = computed(() => settingsStore.config?.READER_WHEEL_NATURAL === true);

const localPreloadCount = computed(() => {
  const v = Number(settingsStore.config?.READER_PRELOAD_COUNT ?? 10);
  if (!Number.isFinite(v)) return 10;
  return Math.max(10, Math.min(20, Math.round(v)));
});
const readerImageQualityMode = computed({
  get: () => String(settingsStore.config?.READER_IMAGE_QUALITY_MODE || "auto"),
  set: (v) => {
    settingsStore.config.READER_IMAGE_QUALITY_MODE = String(v || "auto");
  },
});

const readerMode = computed({
  get: () => String(settingsStore.config?.READER_MODE || "paged"),
  set: (v) => {
    settingsStore.config.READER_MODE = String(v || "paged");
  },
});

// Only left-to-right / right-to-left exist now: the vertical variants looked
// identical to these in a paged layout, so they are folded back to ltr. Values
// persisted by an older build are migrated on read instead of being honoured.
const SUPPORTED_DIRECTIONS = ["ltr", "rtl"];

function normalizeDirection(raw) {
  const v = String(raw || "").trim().toLowerCase();
  return SUPPORTED_DIRECTIONS.includes(v) ? v : "ltr";
}

const direction = computed({
  get: () => normalizeDirection(settingsStore.config?.READER_DIRECTION),
  set: (v) => {
    settingsStore.config.READER_DIRECTION = normalizeDirection(v);
  },
});

const spreadMode = computed({
  get: () => String(settingsStore.config?.READER_SPREAD_MODE || "single"),
  set: (v) => {
    settingsStore.config.READER_SPREAD_MODE = String(v || "single");
  },
});

const fitMode = computed({
  get: () => String(settingsStore.config?.READER_FIT_MODE || "contain"),
  set: (v) => {
    settingsStore.config.READER_FIT_MODE = String(v || "contain");
  },
});

const filterPreset = computed({
  get: () => String(settingsStore.config?.READER_FILTER_PRESET || "none"),
  set: (v) => {
    settingsStore.config.READER_FILTER_PRESET = String(v || "none");
  },
});

const wheelPosition = computed({
  get: () => String(settingsStore.config?.READER_WHEEL_POSITION || "bottom"),
  set: (v) => {
    settingsStore.config.READER_WHEEL_POSITION = String(v || "bottom");
  },
});

const wheelCurve = computed({
  get: () => {
    const n = Number(settingsStore.config?.READER_WHEEL_CURVE ?? 55);
    if (!Number.isFinite(n)) return 55;
    return Math.max(0, Math.min(100, Math.round(n)));
  },
  set: (v) => {
    const n = Number(v ?? 55);
    settingsStore.config.READER_WHEEL_CURVE = Number.isFinite(n) ? Math.max(0, Math.min(100, Math.round(n))) : 55;
  },
});

const wheelRadius = computed(() => {
  const t = wheelCurve.value / 100;
  const minR = 120;
  const maxR = 1000000;
  return minR * Math.exp(Math.log(maxR / minR) * t);
});
const pageAnimEnabled = computed({
  get: () => settingsStore.config?.READER_PAGE_ANIM_ENABLED !== false,
  set: (v) => {
    settingsStore.config.READER_PAGE_ANIM_ENABLED = !!v;
  },
});
const pageTransitionName = computed(() => (pageAnimEnabled.value ? transitionName.value : ""));

const isRtl = computed(() => direction.value === "rtl");
const isVertical = computed(() => direction.value === "ttb" || direction.value === "btt");
const isBottomToTop = computed(() => direction.value === "btt");
const spreadDouble = computed(() => readerMode.value === "paged" && String(spreadMode.value || "single") === "double");
const pageStep = computed(() => (spreadDouble.value ? 2 : 1));
// The end screen is addressable as page N+1 but is not a real page: nothing is
// rendered from the archive there, and progress must never be recorded there.
// `endScreenPage`/`onEndScreen` come from utils/readerPageActions so the long-press
// guard and this addressable page cannot drift apart.
const endScreenPage = computed(() => readerEndScreenPage(totalPages.value));
const onEndScreen = computed(() => !canOpenReaderRabbitHole(currentPage.value, totalPages.value));
const progressPage = computed(() => Math.max(1, Math.min(Number(totalPages.value || 1), Number(currentPage.value || 1))));
// "Next gallery" is only meaningful when this gallery came out of a feed the
// reader was handed (see readerQueueStore); opened from a bare URL there is no
// order to follow and the affordance stays hidden.
const hasReadingQueue = computed(() => readerQueue.knows(arcid.value));
const nextGalleryEntry = computed(() => (hasReadingQueue.value ? readerQueue.nextAfter(arcid.value) : null));
const endRecsLimit = computed(() => {
  const n = Number(settingsStore.config?.READER_REC_LIMIT ?? 6);
  if (!Number.isFinite(n)) return 6;
  return Math.max(3, Math.min(12, Math.round(n)));
});
const endRecsEnabled = computed(() => settingsStore.config?.READER_REC_ENABLED !== false);
const readerFilterStyle = computed(() => {
  const key = String(filterPreset.value || "none");
  if (key === "night_eink") return { filter: "grayscale(1) contrast(1.2) brightness(0.8)" };
  if (key === "warm_sepia") return { filter: "sepia(0.3) contrast(1.05) brightness(0.9)" };
  if (key === "dark_invert") return { filter: "invert(0.9) hue-rotate(180deg) brightness(0.85)" };
  return { filter: "none" };
});
// Which page sits in each half of a double spread.
//
// The earlier page always goes in the slot on the *leading* side of the
// reading direction: the right-hand half for RTL, the left for LTR. The old
// shape computed a primary/secondary pair and then flowed them into the DOM in
// that order, so RTL rendered the earlier page on the left -- a spread of 3|2,
// i.e. a right-to-left cursor drawn left-to-right. Splitting the two values by
// side (instead of by rank) makes the binding independent of DOM order.
//
// The start page and the step are deliberately untouched: `currentPage` is
// already the leading page of the spread in both directions, exactly as the
// page-turn code assumes when it advances by `pageStep`.
const spreadLeftPage = computed(() => {
  const cur = Number(currentPage.value || 1);
  if (!spreadDouble.value) return cur;
  return isRtl.value ? cur + 1 : cur;
});
const spreadRightPage = computed(() => {
  const cur = Number(currentPage.value || 1);
  if (!spreadDouble.value) return 0;
  const leading = isRtl.value ? cur : cur + 1;
  return leading <= Number(totalPages.value || 1) ? leading : 0;
});
const ghostPages = computed(() => {
  const maxPage = Math.max(1, Number(totalPages.value || 1));
  const inRange = (p) => Number.isFinite(p) && p >= 1 && p <= maxPage;
  const unique = [];
  const seen = new Set();
  const pushPage = (p) => {
    const n = Math.floor(Number(p || 0));
    if (!inRange(n) || seen.has(n)) return;
    seen.add(n);
    unique.push(n);
  };
  const primary = Number(spreadLeftPage.value || 1);
  const secondary = Number(spreadRightPage.value || 0);
  if (!spreadDouble.value) {
    [primary - 1, primary + 1].forEach(pushPage);
    return unique;
  }
  // Prefetch walks the *page* axis, not the slot axis, so the neighbours are
  // taken from the leading page and its partner rather than from "left/right".
  const step = 2;
  const lead = Number(currentPage.value || 1);
  const prevPrimary = lead - step;
  const nextPrimary = lead + step;
  pushPage(primary);
  if (secondary > 0) pushPage(secondary);
  pushPage(prevPrimary);
  pushPage(prevPrimary + 1);
  pushPage(nextPrimary);
  pushPage(nextPrimary + 1);
  return unique;
});
const wheelRange = computed(() => {
  const n = Number(settingsStore.config?.READER_WHEEL_RANGE ?? 4);
  if (!Number.isFinite(n)) return 4;
  return Math.max(2, Math.min(20, Math.round(n)));
});
const wheelRangeValue = computed({
  get: () => Number(wheelRange.value || 4),
  set: (v) => {
    const n = Number(v ?? 4);
    settingsStore.config.READER_WHEEL_RANGE = Number.isFinite(n) ? Math.max(2, Math.min(20, Math.round(n))) : 4;
  },
});
const wheelExtentPct = computed(() => {
  const n = Number(settingsStore.config?.READER_WHEEL_EXTENT_PCT ?? 100);
  if (!Number.isFinite(n)) return 100;
  return Math.max(60, Math.min(220, Math.round(n)));
});
const wheelExtentPctValue = computed({
  get: () => Number(wheelExtentPct.value || 100),
  set: (v) => {
    const n = Number(v ?? 100);
    settingsStore.config.READER_WHEEL_EXTENT_PCT = Number.isFinite(n) ? Math.max(60, Math.min(220, Math.round(n))) : 100;
  },
});
const wheelThumbScalePct = computed({
  get: () => {
    const n = Number(settingsStore.config?.READER_WHEEL_THUMB_SCALE_PCT ?? 100);
    if (!Number.isFinite(n)) return 100;
    return Math.max(60, Math.min(220, Math.round(n)));
  },
  set: (v) => {
    const n = Number(v ?? 100);
    settingsStore.config.READER_WHEEL_THUMB_SCALE_PCT = Number.isFinite(n) ? Math.max(60, Math.min(220, Math.round(n))) : 100;
  },
});
const wheelPages = computed(() => {
  const out = [];
  const range = Number(wheelRange.value || 4);
  // Built from the settled cursor, not the live one: `src` here becomes an <img>,
  // and building it per tick is what buried the reader's own page request behind
  // dozens of skipped-past thumbnails.
  const center = Math.max(1, Math.min(Number(totalPages.value || 1), Number(wheelStripPage.value || currentPage.value || 1)));
  const max = Math.max(1, totalPages.value);
  const start = Math.max(1, center - range);
  const end = Math.min(max, center + range);
  for (let p = start; p <= end; p += 1) {
    const td = pageThumbData(p);
    out.push({ page: p, ...(td || {}), src: td?.src || pageImageUrl(p) });
  }
  return isRtl.value ? out.reverse() : out;
});
// The top-of-screen "12/12" preload indicator was removed as noise. The session
// status itself is still polled -- it drives preloading and the page URLs.

const { setContinuousPageRef, resetContinuousPageRefs, scrollToContinuousPage, onContinuousScroll, disposeContinuousScroll } = useContinuousScroll({
  continuousRootRef: continuousRoot,
  currentPageRef: currentPage,
  onPageChange: (nextPage) => {
    currentPage.value = nextPage;
    updateRoutePage();
  },
});

useViewportFit(computed(() => settingsStore.config?.READER_VIEWPORT_FIT_COVER !== false));

function pageImageUrl(page) {
  if (!manifestReady.value) return '';
  const sid = String(localReaderSessionId.value || "").trim();
  const mode = encodeURIComponent(String(readerImageQualityMode.value || "auto").trim().toLowerCase() || "auto");
  // feat-16 auto resolution: the auto tier pairs the mode with a `res=WxH`
  // screen hint so the server can Lanczos-downsample pages larger than the
  // screen; manual tiers keep byte-stable URLs and never send it.
  const res = readerResParam(readerImageQualityMode.value);
  const resQuery = res ? `&res=${encodeURIComponent(res)}` : "";
  if (sid) return `/api/reader/session/${encodeURIComponent(sid)}/page/${Number(page || 1)}?mode=${mode}${resQuery}`;
  return `/api/reader/${encodeURIComponent(arcid.value)}/page/${page}?mode=${mode}${resQuery}`;
}

// The nav wheel used to reuse `pageImageUrl`, i.e. a full-size read-quality
// transform per thumbnail. A drag crosses dozens of pages, so those requests
// queued ahead of the page the reader was waiting for on the browser's 6-per-
// origin connection limit -- the正文 arrived last, behind images nobody stopped
// to look at. `thumb` is the wheel's own cheap mode (200px/q55), and a browser
// cache hit is guaranteed because the URL no longer changes with the reader's
// quality setting.
const WHEEL_THUMB_MODE = "thumb";
function wheelThumbUrl(page) {
  if (!manifestReady.value) return '';
  const sid = String(localReaderSessionId.value || "").trim();
  if (sid) return `/api/reader/session/${encodeURIComponent(sid)}/page/${Number(page || 1)}?mode=${WHEEL_THUMB_MODE}`;
  return `/api/reader/${encodeURIComponent(arcid.value)}/page/${page}?mode=${WHEEL_THUMB_MODE}`;
}

function withNonce(url, nonce) {
  const src = String(url || "").trim();
  if (!src) return "";
  const n = Number(nonce || 0);
  if (!n) return src;
  return `${src}${src.includes("?") ? "&" : "?"}r=${n}`;
}

function pageRenderUrl(page) {
  return withNonce(pageImageUrl(page), Number(pageRetryNonce.value?.[Number(page || 1)] || 0));
}

function continuousRenderUrl(page) {
  return withNonce(pageImageUrl(page), Number(continuousRetryNonce.value?.[Number(page || 1)] || 0));
}

function pageThumbUrl(page) {
  return wheelThumbUrl(page);
}

function pageThumbData(page) {
  const src = pageThumbUrl(page);
  const aspect = Number(wheelThumbAspectMap.value?.[Number(page || 1)] || 0);
  if (!src) return null;
  return {
    mode: "image",
    src,
    thumb_aspect: Number.isFinite(aspect) && aspect > 0 ? aspect : 0,
    width: 72,
    height: 96,
  };
}

function resetWheelThumbPreload() {
  for (const img of wheelThumbPreloadLoaders.values()) {
    try {
      img.onload = null;
      img.onerror = null;
      img.src = "";
    } catch {
      // ignore
    }
  }
  wheelThumbPreloadLoaders.clear();
  wheelThumbAspectMap.value = {};
}

// Measure only the strip that is on screen. This used to loop from page 1 to the
// last page of the gallery, i.e. one request per page of the book, all of them
// querying the reader's quality mode: opening a 400-page gallery queued 400
// full-size images ahead of the page the user was actually waiting on. Bounded to
// the wheel's own window, and only for pages the strip is showing.
function preloadWheelStripThumbs() {
  resetWheelThumbPreload();
  const max = Math.max(1, Number(totalPages.value || 1));
  const range = Number(wheelRange.value || 4);
  const center = Math.max(1, Math.min(max, Number(wheelStripPage.value || currentPage.value || 1)));
  const start = Math.max(1, center - range);
  const end = Math.min(max, center + range);
  for (let p = start; p <= end; p += 1) {
    const src = pageThumbUrl(p);
    if (!src) continue;
    const img = new Image();
    wheelThumbPreloadLoaders.set(p, img);
    img.decoding = "async";
    img.loading = "eager";
    img.onload = () => {
      const nw = Number(img.naturalWidth || 0);
      const nh = Number(img.naturalHeight || 0);
      if (nw > 0 && nh > 0) {
        const r = nw / nh;
        if (Number.isFinite(r) && r > 0) {
          wheelThumbAspectMap.value = { ...wheelThumbAspectMap.value, [p]: r };
        }
      }
      wheelThumbPreloadLoaders.delete(p);
    };
    img.onerror = () => {
      wheelThumbPreloadLoaders.delete(p);
    };
    img.src = src;
  }
}

function pageFromRoute() {
  const p = Number(route.query.page || 1);
  if (!Number.isFinite(p) || p < 1) return 1;
  return Math.floor(p);
}

function hasRoutePage() {
  return !!String(route.query.page || "").trim();
}

function toggleFullscreen() {
  if (typeof document === "undefined") return;
  if (!document.fullscreenElement) {
    const el = document.documentElement;
    if (!el || typeof el.requestFullscreen !== "function") return;
    const p = el.requestFullscreen();
    if (p && typeof p.catch === "function") {
      p.catch((err) => {
        console.warn("全屏请求被拒绝:", err);
      });
    }
  } else {
    if (typeof document.exitFullscreen !== "function") return;
    const p = document.exitFullscreen();
    if (p && typeof p.catch === "function") {
      p.catch(() => null);
    }
  }
}

function closeReader() {
  if (typeof window !== "undefined" && window.history.length <= 1) {
    goHome();
    return;
  }
  router.back();
}

function goHome() {
  router.replace({ name: "dashboard" }).catch(() => null);
}

function updateRoutePage() {
  const q = { page: String(currentPage.value) };
  router.replace({
    name: "reader",
    params: { arcid: arcid.value },
    query: q,
  }).catch(() => null);
}

function setPage(next, directionHint = 1, opts = {}) {
  // The clamp allows one page past the last one: that is the end screen.
  const clamped = Math.max(1, Math.min(endScreenPage.value, Number(next) || 1));
  if (clamped === currentPage.value && !opts.force) return;
  const isEnd = clamped > Number(totalPages.value || 1);
  const turned = manifestReady.value && clamped !== currentPage.value;
  if (turned && !isEnd) {
    readTurnCount += 1;
  }
  // `directionHint` is +1 when the page *number* advances and -1 when it
  // retreats. The on-screen motion is not the same thing: reading direction
  // decides which edge the incoming page enters from. In LTR a forward turn
  // brings the next page in from the right; in RTL it comes in from the left,
  // because the content itself flows the other way. Encoding both in the name
  // (rather than negating the hint) is what makes the two directions animate
  // differently -- negating alone cancelled out and left both directions using
  // the LTR slide.
  const forward = directionHint >= 0;
  transitionName.value = isRtl.value
    ? (forward ? "reader-slide-rtl-next" : "reader-slide-rtl-prev")
    : (forward ? "reader-slide-next" : "reader-slide-prev");
  currentPage.value = clamped;
  if (turned && !isEnd) {
    recordReadEvent("reader-page-turn");
    scheduleReadDwellQualify();
  }
  // Nothing on the end screen belongs to the gallery: bookmarking it would
  // store a page number that does not exist.
  if (manifestReady.value && !isEnd) {
    syncBookmarkDebounced(clamped, false);
  }
  if (!opts.skipRoute) updateRoutePage();
  if (readerMode.value === "continuous") scrollToContinuousPage(Math.min(clamped, Number(totalPages.value || 1)));
  else if (!isEnd) preloadNearby();
  if (isEnd) loadEndRecs();
}

function nextPage() {
  // One forward action past the last page opens the end screen; the *next* one
  // is what actually leaves the gallery. Two deliberate steps, so finishing a
  // gallery never flings the reader into another one.
  if (onEndScreen.value) {
    goNextGallery();
    return;
  }
  setPage(currentPage.value + Number(pageStep.value || 1), isRtl.value ? -1 : 1);
}

function prevPage() {
  setPage(currentPage.value - Number(pageStep.value || 1), isRtl.value ? 1 : -1);
}

/** Leave this gallery for the next one in the order the reader was opened with. */
function goNextGallery() {
  const entry = nextGalleryEntry.value;
  const next = String(entry?.arcid || "").trim();
  if (!next || next === arcid.value) return;
  // `replace`, not `push`: a long run of galleries should not fill the back
  // stack one gallery at a time. The arcid watcher below publishes progress for
  // the gallery we are leaving and loads the manifest for the new one.
  router.replace({ name: "reader", params: { arcid: next }, query: { page: "1" } }).catch(() => null);
}

function openEndRec(item) {
  const next = String(item?.arcid || "").trim();
  if (!next || next === arcid.value) return;
  useDashboardStore().setPendingPreviewItem({ ...(item || {}), source: "works", arcid: next });
  router.replace({ name: "dashboard", query: { pv: `works:${next}`, detail: "1" } }).catch(() => null);
}

/**
 * Fetch the "guess you like" strip lazily -- only once the reader actually
 * reaches the end screen (or the bottom of a continuous strip), so opening a
 * gallery costs nothing extra. The sequence number retires a reply that lands
 * after the user already moved to another gallery.
 */
async function loadEndRecs(force = false) {
  if (!endRecsEnabled.value || !arcid.value) return;
  if (!force && (endRecsLoading.value || endRecs.value.length)) return;
  const generation = ++endRecsSeq;
  endRecsLoading.value = true;
  endRecsError.value = "";
  try {
    const res = await getReaderSimilar(arcid.value, endRecsLimit.value);
    if (generation !== endRecsSeq) return;
    endRecs.value = Array.isArray(res?.items) ? res.items : [];
  } catch (e) {
    if (generation !== endRecsSeq) return;
    endRecs.value = [];
    endRecsError.value = settingsStore.t("reader.end.rec_failed");
  } finally {
    if (generation === endRecsSeq) endRecsLoading.value = false;
  }
}

function resetEndRecs() {
  endRecsSeq += 1;
  endRecs.value = [];
  endRecsError.value = "";
  endRecsLoading.value = false;
}

function onContinuousScrollEvent(event) {
  onContinuousScroll(event);
  maybeLoadEndRecsInContinuous();
}

function maybeLoadEndRecsInContinuous() {
  if (readerMode.value !== "continuous") return;
  const el = continuousRoot.value;
  if (!el) return;
  if (el.scrollHeight - el.scrollTop - el.clientHeight > 700) return;
  loadEndRecs().catch(() => null);
}

function onLeftZone() {
  if (longPressTriggered.value) {
    longPressTriggered.value = false;
    return;
  }
  if (isVertical.value) {
    if (isBottomToTop.value) nextPage();
    else prevPage();
    return;
  }
  if (isRtl.value) nextPage();
  else prevPage();
}

function onRightZone() {
  if (longPressTriggered.value) {
    longPressTriggered.value = false;
    return;
  }
  if (isVertical.value) {
    if (isBottomToTop.value) prevPage();
    else nextPage();
    return;
  }
  if (isRtl.value) prevPage();
  else nextPage();
}

function onCenterZone() {
  if (pagedImageState.value.error && Number(pagedImageState.value.page || 0) === Number(currentPage.value || 1)) {
    retryCurrentPage();
    return;
  }
  toggleUi();
}

function clearPagedProgressTimer() {
  if (pagedProgressTimer) {
    window.clearInterval(pagedProgressTimer);
    pagedProgressTimer = 0;
  }
}

function clearBookmarkSyncTimer() {
  if (bookmarkSyncTimer) {
    window.clearTimeout(bookmarkSyncTimer);
    bookmarkSyncTimer = 0;
  }
}

function syncBookmarkDebounced(page = currentPage.value, immediate = false) {
  const p = Math.max(1, Math.min(Number(totalPages.value || 1), Number(page || 1)));
  const payload = { arcid: arcid.value, page: p };
  const run = () => {
    // Bookmarks are a persisted "where I was", i.e. exactly what private mode
    // promises not to keep. The timer is still armed/cleared as usual so the
    // resume position within this session is unaffected.
    if (useDashboardStore().isPrivateMode()) return;
    postReaderBookmarkSet(payload).catch(() => null);
  };
  if (immediate) {
    clearBookmarkSyncTimer();
    run();
    return;
  }
  clearBookmarkSyncTimer();
  bookmarkSyncTimer = window.setTimeout(() => {
    bookmarkSyncTimer = 0;
    run();
  }, 800);
}

function beginPagedProgress() {
  clearPagedProgressTimer();
  pagedLoadProgress.value = 2;
  pagedProgressTimer = window.setInterval(() => {
    const cur = Number(pagedLoadProgress.value || 0);
    if (cur >= 92) return;
    pagedLoadProgress.value = Math.min(92, cur + (cur < 45 ? 4 : 2));
  }, 110);
}

// The strip the user can actually see. When it moves, the previous strip's
// in-flight requests are dropped -- `resetWheelThumbPreload` clears each loader's
// `src`, which is what frees the connection slot for the page being read.
watch(wheelStripPage, () => {
  if (!manifestReady.value) return;
  preloadWheelStripThumbs();
});

function jumpToPage(page) {
  const p = Number(page || 1);
  if (!Number.isFinite(p)) return;
  const dirHint = p >= currentPage.value ? 1 : -1;
  wheelCursorPage.value = Math.max(1, Math.min(Number(totalPages.value || 1), Math.round(p)));
  setPage(p, dirHint);
}

function onWheelPreviewPage(page) {
  const p = Number(page || 1);
  if (!Number.isFinite(p)) return;
  const clamped = Math.max(1, Math.min(Number(totalPages.value || 1), Math.round(p)));
  // Move the slider and the label straight away -- the drag has to feel attached
  // to the finger -- but only rebuild the thumbnail strip once the drag settles.
  // `wheelPages` is what creates <img> tags, so following every tick meant a fast
  // drag fired a request per page it merely passed over.
  wheelCursorPage.value = clamped;
  // Keep the cheap settle delay for small movements, but never let the live
  // cursor outrun the old strip's visible range. Crossing that boundary used
  // to make every thumbnail transparent until the timer caught up.
  const recenterGap = Math.max(1, Number(wheelRange.value || 4) - 1);
  if (Math.abs(clamped - Number(wheelStripPage.value || 1)) >= recenterGap) {
    clearWheelStripSettle();
    wheelStripPage.value = clamped;
  } else {
    armWheelStripSettle();
  }
}

// Long enough that a flick does not emit its whole path, short enough that
// letting go feels immediate.
const WHEEL_STRIP_SETTLE_MS = 150;
function armWheelStripSettle() {
  clearWheelStripSettle();
  wheelStripSettleTimer = window.setTimeout(() => {
    wheelStripSettleTimer = 0;
    wheelStripPage.value = wheelCursorPage.value;
  }, WHEEL_STRIP_SETTLE_MS);
}

function clearWheelStripSettle() {
  if (wheelStripSettleTimer) {
    window.clearTimeout(wheelStripSettleTimer);
    wheelStripSettleTimer = 0;
  }
}

function toggleUi() {
  if (longPressTriggered.value) {
    longPressTriggered.value = false;
    return;
  }
  showUi.value = !showUi.value;
  if (!showUi.value) showQuickSettings.value = false;
}

function clearLongPressTimer() {
  if (longPressTimer) {
    window.clearTimeout(longPressTimer);
    longPressTimer = 0;
  }
}

function onPointerDown(event) {
  if (event?.pointerType === "mouse" && Number(event?.button) !== 0) return;
  touchStart.value = { x: Number(event?.clientX || 0), y: Number(event?.clientY || 0) };
  longPressTriggered.value = false;
  clearLongPressTimer();
  // The rabbit hole is seeded from the current page, so it has nothing to suggest
  // on the end screen (page N+1). Long-pressing there used to open an overlay
  // that could only ever be empty; we simply do not arm the timer in that state.
  if (!canOpenReaderRabbitHole(currentPage.value, totalPages.value)) return;
  longPressTimer = window.setTimeout(() => {
    longPressTriggered.value = true;
    longPressSearchOpen.value = true;
  }, 520);
}

function onPointerMove(event) {
  if (!longPressTimer) return;
  const dx = Math.abs(Number(event?.clientX || 0) - touchStart.value.x);
  const dy = Math.abs(Number(event?.clientY || 0) - touchStart.value.y);
  if (dx > 15 || dy > 15) clearLongPressTimer();
}

function onPointerUp(event) {
  clearLongPressTimer();
  if (longPressTriggered.value) return;
  if (!swipeEnabled.value || readerMode.value !== "paged") return;
  if (event?.pointerType !== "touch" && event?.pointerType !== "pen") return;
  const dx = Number(event?.clientX || 0) - touchStart.value.x;
  const dy = Number(event?.clientY || 0) - touchStart.value.y;
  if (isVertical.value) {
    if (Math.abs(dy) < 48 || Math.abs(dy) < Math.abs(dx) * 1.25) return;
    if (dy < 0) {
      if (isBottomToTop.value) prevPage();
      else nextPage();
    } else if (isBottomToTop.value) {
      nextPage();
    } else {
      prevPage();
    }
    return;
  }
  if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
  if (dx < 0) {
    if (isRtl.value) prevPage();
    else nextPage();
  } else if (isRtl.value) {
    nextPage();
  } else {
    prevPage();
  }
}

function onPointerCancel() {
  clearLongPressTimer();
}

async function recordReadEvent(source = "reader-ui") {
  const nowMs = Date.now();
  if (!arcid.value) return;
  // Private mode must not leave a trace, so the event is dropped *before* the
  // throttle bookkeeping: a suppressed write must not consume the window that a
  // later, legitimate one would need.
  if (useDashboardStore().isPrivateMode()) return;
  if (!readDwellQualified && readTurnCount <= 0) return;
  // The throttle is per gallery. A different gallery is a new reading, and its
  // first qualifying event must go through even if the previous gallery wrote
  // one a moment ago.
  if (String(arcid.value) === lastReadEventArcid && nowMs - lastReadEventAt < 15000) return;
  lastReadEventAt = nowMs;
  lastReadEventArcid = String(arcid.value);
  const reason = readTurnCount > 0 ? "page_turn" : "dwell_3s";
  const turns = Number(readTurnCount || 0);
  readTurnCount = 0;
  readDwellQualified = false;
  try {
    await postReaderReadEvent({
      arcid: arcid.value,
      read_time: Math.floor(nowMs / 1000),
      source_file: String(source || "reader-ui"),
      ingested_at: new Date(nowMs).toISOString(),
      raw: {
        arcid: arcid.value,
        page: Number(progressPage.value || 1),
        mode: String(readerMode.value || "paged"),
        qualify_reason: reason,
        page_turn_count: turns,
      },
    });
  } catch {
    // ignore read event failures in reader flow
  }
}

function clearReadQualifyTimer() {
  if (readQualifyTimer) {
    window.clearTimeout(readQualifyTimer);
    readQualifyTimer = 0;
  }
}

function scheduleReadDwellQualify() {
  clearReadQualifyTimer();
  if (!manifestReady.value || !arcid.value) return;
  readQualifyTimer = window.setTimeout(() => {
    readDwellQualified = true;
    recordReadEvent("reader-dwell");
  }, 3000);
}

function preloadNearby() {
  syncLocalReaderCursor(currentPage.value);
}

function isPageWarm(page) {
  const base = String(pageImageUrl(page) || "").trim();
  if (!base) return false;
  return localPrefetchSeen.has(base);
}

function syncLocalReaderCursor(page = currentPage.value) {
  const sid = String(localReaderSessionId.value || "").trim();
  if (!sid) return;
  const p = Math.max(1, Math.min(totalPages.value, Number(page || 1)));
  updateReaderSessionCursor(sid, { page: p, ahead: localPreloadCount.value }).catch(() => null);
  pollLocalReaderStatusOnce().catch(() => null);
}

async function closeLocalReaderSession() {
  const sid = String(localReaderSessionId.value || "").trim();
  if (!sid) return;
  clearLocalReaderStatusPolling();
  localReaderSessionId.value = "";
  localSessionStatus.value = null;
  try {
    await closeReaderSession(sid);
  } catch {
    // ignore close failures on navigation/unmount
  }
}

function clearLocalReaderStatusPolling() {
  if (localStatusPollTimer) {
    window.clearInterval(localStatusPollTimer);
    localStatusPollTimer = 0;
  }
}

async function pollLocalReaderStatusOnce() {
  const sid = String(localReaderSessionId.value || "").trim();
  if (!sid) return;
  try {
    localSessionStatus.value = await getReaderSessionStatus(sid);
  } catch {
    // ignore transient status polling failures
  }
}

function startLocalReaderStatusPolling() {
  clearLocalReaderStatusPolling();
  if (!String(localReaderSessionId.value || "").trim()) return;
  pollLocalReaderStatusOnce().catch(() => null);
  localStatusPollTimer = window.setInterval(() => {
    pollLocalReaderStatusOnce().catch(() => null);
  }, 900);
}

function onGhostImageLoad(page) {
  const base = String(pageImageUrl(page) || "").trim();
  if (!base) return;
  localPrefetchSeen.add(base);
  if (localPrefetchSeen.size > 3000) localPrefetchSeen.clear();
}

function onGhostImageError() {
  // Keep silent: ghost window only warms cache outside viewport.
}

function markPagedLoading(page) {
  pagedImageState.value = { page: Number(page || 1), loading: true, error: false };
  beginPagedProgress();
}

function onPagedImageLoad() {
  if (Number(pagedImageState.value.page || 0) !== Number(currentPage.value || 1)) return;
  const base = String(pageImageUrl(currentPage.value) || "").trim();
  if (base) {
    localPrefetchSeen.add(base);
  }
  clearPagedProgressTimer();
  pagedLoadProgress.value = 100;
  pagedImageState.value = { page: Number(currentPage.value || 1), loading: false, error: false };
}

function onPagedImageError() {
  const page = Number(currentPage.value || 1);
  const src = String(pageRenderUrl(page) || "").trim();
  if (!src || !manifestReady.value) {
    markPagedLoading(page);
    return;
  }
  if (Number(pagedImageState.value.page || 0) !== Number(currentPage.value || 1)) return;
  clearPagedProgressTimer();
  pagedImageState.value = { page: Number(currentPage.value || 1), loading: false, error: true };
}

function retryCurrentPage() {
  const p = Number(currentPage.value || 1);
  const base = String(pageImageUrl(p) || "").trim();
  if (base) {
    localPrefetchSeen.delete(base);
  }
  pageRetryNonce.value = { ...pageRetryNonce.value, [p]: Number(pageRetryNonce.value?.[p] || 0) + 1 };
  markPagedLoading(p);
}

function initContinuousState(page) {
  const p = Number(page || 1);
  if (!continuousImageState.value[p]) {
    continuousImageState.value = { ...continuousImageState.value, [p]: { loading: true, error: false } };
  }
}

function onContinuousImageLoad(page) {
  const p = Number(page || 1);
  continuousImageState.value = { ...continuousImageState.value, [p]: { loading: false, error: false } };
}

function onContinuousImageError(page) {
  const p = Number(page || 1);
  if (!manifestReady.value || !String(continuousRenderUrl(p) || "").trim()) {
    continuousImageState.value = { ...continuousImageState.value, [p]: { loading: true, error: false } };
    return;
  }
  continuousImageState.value = { ...continuousImageState.value, [p]: { loading: false, error: true } };
}

function isContinuousLoading(page) {
  return continuousImageState.value?.[Number(page || 1)]?.loading === true;
}

function isContinuousError(page) {
  return continuousImageState.value?.[Number(page || 1)]?.error === true;
}

function retryContinuousPage(page) {
  const p = Number(page || 1);
  continuousRetryNonce.value = { ...continuousRetryNonce.value, [p]: Number(continuousRetryNonce.value?.[p] || 0) + 1 };
  continuousImageState.value = { ...continuousImageState.value, [p]: { loading: true, error: false } };
}

function resetImageStates() {
  clearPagedProgressTimer();
  pagedLoadProgress.value = 0;
  pagedImageState.value = { page: Number(currentPage.value || 1), loading: true, error: false };
  pageRetryNonce.value = {};
  continuousImageState.value = {};
  continuousRetryNonce.value = {};
}

async function loadManifest() {
  manifestReady.value = false;
  manifestError.value = '';
  localPrefetchSeen.clear();
  resetEndRecs();
  let res = null;
  if (!arcid.value) return;
  await closeLocalReaderSession();
  try {
    res = await getReaderManifest(arcid.value);
  } catch (e) {
    manifestError.value = settingsStore.t('reader.gallery_unavailable');
    return;
  }
  if (!Number(res?.page_count)) {
    manifestError.value = settingsStore.t('reader.gallery_unavailable');
    return;
  }
  resetWheelThumbPreload();
  const startPage = Math.max(1, Number(pageFromRoute() || 1));
  try {
    const sess = await openReaderSession(arcid.value, { page: startPage, ahead: localPreloadCount.value });
    localReaderSessionId.value = String(sess?.session_id || "").trim();
    localSessionStatus.value = sess || null;
    startLocalReaderStatusPolling();
  } catch {
    localReaderSessionId.value = "";
    localSessionStatus.value = null;
  }
  totalPages.value = Math.max(1, Number(res?.page_count || 1));
  title.value = String(res?.title || "");
  currentPage.value = Math.max(1, Math.min(totalPages.value, pageFromRoute()));
  if (!hasRoutePage()) {
    const bm = Number(res?.bookmark || 1);
    if (Number.isFinite(bm) && bm > 1) {
      currentPage.value = Math.max(1, Math.min(totalPages.value, Math.floor(bm)));
    }
  }
  wheelCursorPage.value = Number(currentPage.value || 1);
  // An authoritative jump, not a drag: the strip follows at once.
  wheelStripPage.value = wheelCursorPage.value;
  resetImageStates();
  manifestReady.value = true;
  updateRoutePage();
  await nextTick();
  readTurnCount = 0;
  readDwellQualified = false;
  scheduleReadDwellQualify();
  if (readerMode.value === "continuous") scrollToContinuousPage(currentPage.value);
  else preloadNearby();
}

watch(() => route.query.page, () => {
  if (route.name !== "reader") return;
  // Mid-switch guard: leaving for another gallery rewrites params *and* query in
  // one navigation, and this watcher runs first -- applying the new page number
  // here would write "page 1" onto the gallery we are leaving. `arcid` holds the
  // loaded gallery, so a mismatch means the swap is already under way.
  if (String(route.params.arcid || "").trim() !== arcid.value) return;
  const p = pageFromRoute();
  wheelCursorPage.value = Math.max(1, Math.min(Number(totalPages.value || 1), Number(p || 1)));
  // Back/forward and deep links are authoritative too -- no settle delay.
  wheelStripPage.value = wheelCursorPage.value;
  if (p !== currentPage.value) {
    const dirHint = p > currentPage.value ? 1 : -1;
    setPage(p, dirHint, { skipRoute: true, force: true });
  }
});

watch(() => currentPage.value, (p) => {
  // The end screen renders no archive page at all, so it must not light up the
  // "loading" overlay that the paged stage draws for a missing image.
  if (Number(p || 1) > Number(totalPages.value || 1)) {
    clearPagedProgressTimer();
    pagedLoadProgress.value = 100;
    pagedImageState.value = { page: Number(p || 1), loading: false, error: false };
    return;
  }
  if (isPageWarm(p)) {
    clearPagedProgressTimer();
    pagedLoadProgress.value = 100;
    pagedImageState.value = { page: Number(p || 1), loading: false, error: false };
    return;
  }
  markPagedLoading(p);
});

watch(() => route.params.arcid, () => {
  if (route.name !== "reader") return;
  if (manifestReady.value) {
    previewProgressStore.publish({ arcid: arcid.value, page: progressPage.value, total: Number(totalPages.value || 0) });
    syncBookmarkDebounced(currentPage.value, true);
  }
  arcid.value = String(route.params.arcid || "").trim();
  // Candidates belong to the gallery that was open, not to the one arriving.
  resetEndRecs();
  resetContinuousPageRefs();
  loadManifest().catch(() => null);
});

const continuousPages = computed(() => {
  const max = Math.max(1, Number(totalPages.value || 1));
  const full = Array.from({ length: max }, (_, i) => i + 1);
  return isBottomToTop.value ? full.reverse() : full;
});

watch(() => localPreloadCount.value, () => {
  syncLocalReaderCursor(currentPage.value);
});
watch(() => readerImageQualityMode.value, () => {
  if (!manifestReady.value) return;
  resetImageStates();
});

watch(() => readerMode.value, async (next) => {
  // Continuous scroll has no reading direction: every page simply flows
  // top-to-bottom. Pin it to ltr so a stored rtl value cannot leave the strip
  // and the scroll maths disagreeing with each other.
  if (next === "continuous" && direction.value !== "ltr") direction.value = "ltr";
  await nextTick();
  if (next === "continuous") scrollToContinuousPage(currentPage.value);
  else preloadNearby();
});

// Same coercion for a reader that *opens* in continuous mode (the watcher above
// only fires on a change). Kept separate so the watcher's preload/scroll side
// effects keep their original timing.
watch(() => [readerMode.value, direction.value], () => {
  if (readerMode.value === "continuous" && direction.value !== "ltr") direction.value = "ltr";
}, { immediate: true });

watch(() => continuousPages.value.join(","), () => {
  for (const p of continuousPages.value) initContinuousState(p);
}, { immediate: true });

// Global input bindings. Re-bound whenever a relevant setting changes so a
// toggle takes effect without leaving the reader -- the settings panel is
// reachable from the reader's own quick settings, so "reload to apply" would
// be a visible wart.
let disposeShortcuts = null;

function rebindShortcuts() {
  if (typeof disposeShortcuts === "function") disposeShortcuts();
  disposeShortcuts = bindReaderShortcuts({
    onNext: () => nextPage(),
    onPrev: () => prevPage(),
    nextKeys: shortcutKeys.value.nextKeys,
    prevKeys: shortcutKeys.value.prevKeys,
    // The visible wheel owns wheel events while the reader chrome is open.
    // Letting the global binding see the same event turned both the strip and
    // the page at once.
    wheelEnabled: wheelPagingEnabled.value && !showUi.value,
    wheelNatural: wheelNatural.value,
  });
}

watch(
  [shortcutKeys, wheelPagingEnabled, wheelNatural, showUi],
  () => rebindShortcuts(),
);

onMounted(() => {
  if (typeof document !== "undefined" && !document.fullscreenElement) {
    toggleFullscreen();
  }
  loadManifest().catch(() => null);
  rebindShortcuts();
});

watch(() => route.fullPath, () => {
  if (route.name !== "reader") {
    disposeContinuousScroll();
  }
});

onBeforeUnmount(() => {
  if (typeof disposeShortcuts === "function") {
    disposeShortcuts();
    disposeShortcuts = null;
  }
  if (typeof document !== "undefined" && document.fullscreenElement) {
    toggleFullscreen();
  }
  clearLongPressTimer();
  clearBookmarkSyncTimer();
  clearReadQualifyTimer();
  if (manifestReady.value) {
    // Publish before any network wait, including when returning via browser Back.
    previewProgressStore.publish({ arcid: arcid.value, page: progressPage.value, total: Number(totalPages.value || 0) });
    syncBookmarkDebounced(currentPage.value, true);
    if (readDwellQualified || readTurnCount > 0) {
      recordReadEvent("reader-unmount").catch(() => null);
    }
  }
  clearPagedProgressTimer();
  localPrefetchSeen.clear();
  clearWheelStripSettle();
  resetWheelThumbPreload();
  clearLocalReaderStatusPolling();
  closeLocalReaderSession().catch(() => null);
  disposeContinuousScroll();
});
</script>

<style scoped>
.reader-root {
  background: #090909;
  min-height: 100dvh;
  height: 100dvh;
  overflow: hidden;
  position: relative;
  z-index: 3000;
}

.reader-stage {
  position: relative;
  width: 100%;
  height: 100dvh;
  overflow: hidden;
  touch-action: pan-y;
  -webkit-touch-callout: none;
  user-select: none;
}

.continuous-stage {
  overflow-y: auto;
  overflow-x: hidden;
}

.continuous-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 6px 0 calc(20px + env(safe-area-inset-bottom));
}

.continuous-btt .continuous-list {
  flex-direction: column-reverse;
}

.continuous-page {
  min-height: 32px;
  position: relative;
}

.reader-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
  display: block;
  pointer-events: none;
  -webkit-user-drag: none;
  -webkit-touch-callout: none;
}

.paged-spread {
  display: flex;
  width: 100%;
  height: 100%;
}

.paged-spread.double {
  gap: 8px;
}

.paged-spread.double .reader-image {
  width: 50%;
}

.continuous-image {
  width: 100%;
  height: auto;
  min-height: 180px;
}

.reader-image.fit-width,
.continuous-image.fit-width {
  width: 100%;
  height: auto;
  min-height: 100%;
}

.reader-image.fit-height,
.continuous-image.fit-height {
  width: auto;
  height: 100%;
  min-width: 100%;
}

.paged-window-ghost {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0;
  overflow: hidden;
}

.ghost-image {
  position: absolute;
  top: -200vh;
  left: -200vw;
  width: 100vw;
  height: 100dvh;
}

.tap-zones {
  position: absolute;
  inset: 0;
  display: grid;
  grid-template-columns: 1fr 2fr 1fr;
}

.tap-zones.vertical {
  grid-template-columns: 1fr;
  grid-template-rows: 1fr 2fr 1fr;
}

.tap-zone {
  border: 0;
  background: transparent;
  cursor: pointer;
}

.reader-load-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 5;
}

.reader-load-card {
  min-width: 180px;
  max-width: min(88vw, 320px);
  padding: 14px 16px;
  border-radius: 12px;
  background: rgba(8, 10, 14, 0.76);
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.45);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: auto;
}

.reader-load-title {
  color: #fff;
  font-size: 14px;
  font-weight: 700;
}

.reader-load-hint {
  color: rgba(255, 255, 255, 0.78);
  font-size: 12px;
}

.reader-load-percent {
  color: rgba(255, 255, 255, 0.92);
  font-size: 12px;
  font-weight: 700;
}

.continuous-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.22);
}

/* Four transitions, not two: the reading direction decides which edge the
   incoming page slides in from. LTR forward comes from the right; RTL forward
   comes from the left. Collapsing this to a single axis is what made the RTL
   reader animate as though it were LTR. */
.reader-slide-next-enter-active,
.reader-slide-next-leave-active,
.reader-slide-prev-enter-active,
.reader-slide-prev-leave-active,
.reader-slide-rtl-next-enter-active,
.reader-slide-rtl-next-leave-active,
.reader-slide-rtl-prev-enter-active,
.reader-slide-rtl-prev-leave-active {
  transition: transform 0.2s ease-out, opacity 0.2s ease-out;
}

.reader-slide-next-enter-from {
  transform: translateX(28px);
  opacity: 0.75;
}

.reader-slide-next-leave-to {
  transform: translateX(-28px);
  opacity: 0.75;
}

.reader-slide-prev-enter-from {
  transform: translateX(-28px);
  opacity: 0.75;
}

.reader-slide-prev-leave-to {
  transform: translateX(28px);
  opacity: 0.75;
}

/* RTL mirrors both: a forward turn enters from the left and leaves to the
   right, and a backward turn does the opposite. */
.reader-slide-rtl-next-enter-from {
  transform: translateX(-28px);
  opacity: 0.75;
}

.reader-slide-rtl-next-leave-to {
  transform: translateX(28px);
  opacity: 0.75;
}

.reader-slide-rtl-prev-enter-from {
  transform: translateX(28px);
  opacity: 0.75;
}

.reader-slide-rtl-prev-leave-to {
  transform: translateX(-28px);
  opacity: 0.75;
}
</style>
