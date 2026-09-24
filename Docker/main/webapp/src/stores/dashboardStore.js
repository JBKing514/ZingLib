import { computed, markRaw, ref, watch } from "vue";
import { defineStore } from "pinia";
import { getHomeFavorite, getHomeHistory, getHomeLocal, getHomeTagSuggest, getLocalFolderList, getReaderManifest, postHomeFavoriteToggle, postHomeRatingSet, searchByImage, searchByImageUpload, searchByText } from "../api";
import { useSettingsStore } from "./settingsStore";
import { getCategoryLabel } from "../utils/categoryPresets";

// The dashboard tabs that exist in a local-only build.
//
// Both the tab normaliser and the refresh affordance read this one list. They
// used to be maintained separately, and the refresh list was never updated when
// the online tabs were removed: isRealtimeRefreshTab() kept comparing against
// tab keys that no longer existed, so it returned false for every reachable
// tab and silently disabled the refresh button, the refresh hint and the
// stale-feed auto-refresh on the whole dashboard.
export const LOCAL_HOME_TABS = ["local_gallery", "local_favorite", "local_upload", "local_history"];

// How the library feeds present their rows. The two modes are mutually
// exclusive by construction: they are two values of ONE setting, never two
// independent switches that could both be on.
export const FEED_MODE_INFINITE = "infinite";
export const FEED_MODE_PAGED = "paged";
// The sizes the settings offer. The backend caps a page at MAX_HOME_FEED_LIMIT
// (100), so anything above the largest entry here would be a 422.
export const FEED_PAGE_SIZES = [10, 20, 50, 100];
export const FEED_DEFAULT_PAGE_SIZE = 20;
// Rows per request while appending on scroll. Unchanged from the pre-paging
// behaviour so switching nothing keeps nothing different.
export const FEED_INFINITE_LIMIT = 24;

export function normalizeFeedMode(value) {
  return String(value ?? "").trim().toLowerCase() === FEED_MODE_PAGED ? FEED_MODE_PAGED : FEED_MODE_INFINITE;
}

export function normalizeFeedPageSize(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return FEED_DEFAULT_PAGE_SIZE;
  // Snap to the nearest offered size: a hand-edited config must not be able to
  // ask for a page the endpoint would reject.
  return FEED_PAGE_SIZES.reduce(
    (best, size) => (Math.abs(size - n) < Math.abs(best - n) ? size : best),
    FEED_PAGE_SIZES[0]
  );
}

export const useDashboardStore = defineStore("dashboard", () => {
  const settingsStore = useSettingsStore();
  const homeTab = ref("local_gallery");
  const homeViewMode = ref("wide");
  const homeSearchQuery = ref("");
  const imageSearchQuery = ref("");
  const homeSentinel = ref(null);
  const homeHistory = ref({ items: [], cursor: "", hasMore: true, loading: false, error: "" });
  const homeLocal = ref({ items: [], cursor: "", hasMore: true, loading: false, error: "" });
  const homeLocalFavorite = ref({ items: [], cursor: "", hasMore: true, loading: false, error: "" });
  const homeSearchState = ref({ items: [], cursor: "", hasMore: false, loading: false, error: "" });
  const homePlaceholderState = ref({ items: [], cursor: "", hasMore: false, loading: false, error: "" });
  const localSortOpen = ref(false);
  const localSortBy = ref("xp");
  const localSortOrder = ref("desc");
  const localGalleryMode = ref("flat");
  const localFolderPath = ref("");
  const localFolderBreadcrumbs = ref([{ name: "local_lib", path: "" }]);
  const localFolderNodes = ref([]);
  const localSortAsc = computed({
    get: () => String(localSortOrder.value || "desc") === "asc",
    set: (v) => {
      localSortOrder.value = v ? "asc" : "desc";
    },
  });
  const homeFiltersOpen = ref(false);
  const homeFilters = ref({ categories: [], tags: [], minRating: 0 });
  const filterTagInput = ref("");
  const filterTagSuggestions = ref([]);
  const lastSearchContext = ref({ mode: "", query: "", hasImage: false });
  const imageSearchDialog = ref(false);
  const imageDropActive = ref(false);
  const selectedImageFile = ref(null);
  const imageFileInputRef = ref(null);
  const mobilePreviewItem = ref(null);
  const isMobile = ref(false);
  const quickSearchOpen = ref(false);
  const showScrollQuickActions = ref(false);
  const lastWindowScrollY = ref(0);
  const pageCountCache = ref({});
  const pageCountLoading = ref({});
  const feedRequestSeq = ref({});
  const feedLastFetchedAt = ref({});
  // Which page each feed is on (1-based), plus the highest page it has ever
  // loaded. The high-water mark is what bounds the "jump to page" box: an
  // offset-paged feed reports `has_more` but no total, so the only honest limit
  // is "one past the furthest page you have actually reached".
  const feedPages = ref({});
  const feedHighPages = ref({});

  const categoryDefs = computed(() => Array.isArray(settingsStore.localCategoryDefs) ? settingsStore.localCategoryDefs : []);
  const pinnedHomeFilterCategoryDefs = computed(() => Array.isArray(settingsStore.pinnedLocalCategoryDefs) ? settingsStore.pinnedLocalCategoryDefs : []);
  const categoryMap = computed(() => Object.fromEntries((categoryDefs.value || []).map((x) => [String(x.key || "").toLowerCase(), x])));
  watch(
    pinnedHomeFilterCategoryDefs,
    (nextDefs, prevDefs) => {
      const nextKeys = (nextDefs || []).map((x) => String(x?.key || "")).filter(Boolean);
      const prevKeys = (prevDefs || []).map((x) => String(x?.key || "")).filter(Boolean);
      const current = (homeFilters.value.categories || []).map((x) => String(x || "")).filter(Boolean);
      const currentSet = new Set(current);
      const prevMatchesAll = prevKeys.length > 0
        && current.length === prevKeys.length
        && prevKeys.every((key) => currentSet.has(key));
      if (!current.length || prevMatchesAll) {
        homeFilters.value.categories = [...nextKeys];
      }
    },
    { immediate: true }
  );

  let _getConfig = () => ({});
  let _configRef = null;
  let _getLang = () => "zh";
  let _getTab = () => "dashboard";
  let _getRail = () => false;
  let _t = (k) => k;
  let _notify = () => {};
  let _formatDateMinute = (v) => String(v || "-");

  let homeObserver = null;
  const imageTracebackStamp = new Map();

  const activeHomeState = computed(() => {
    if (isUploadTab()) return homePlaceholderState.value;
    if (isHistoryTab()) return homeHistory.value;
    if (isLocalGalleryTab()) return homeLocal.value;
    if (isLocalFavoriteTab()) return homeLocalFavorite.value;
    if (isPlaceholderTab()) return homePlaceholderState.value;
    return homeLocal.value;
  });

  const quickFabStyle = computed(() => {
    if (isMobile.value) return {};
    return { left: `${_getRail() ? 92 : 292}px` };
  });

  const filteredHomeItems = computed(() => {
    const rows = activeHomeState.value?.items || [];
    const minRating = Number(homeFilters.value?.minRating || 0);
    let out = rows;
    if (isLocalHistoryTab()) out = out.filter((x) => String(x?.source || "") === "works");
    if (Number.isFinite(minRating) && minRating > 0) {
      out = out.filter((x) => {
        const r = itemRatingValue(x);
        return r !== null && r >= minRating;
      });
    }
    return out;
  });

  // True when the local feed is empty for the honest reason: this library holds
  // no galleries at all, as opposed to "your filters matched nothing". Only the
  // first deserves an offer to upload, and the difference is invisible from
  // `filteredHomeItems` alone because the category/tag filters are applied by the
  // server, not in that computed.
  const libraryEmptyWithoutFilters = computed(() => {
    if (!isLocalGalleryTab()) return false;
    const f = homeFilters.value || {};
    const anyFilter =
      (f.categories || []).length > 0 || (f.tags || []).length > 0 || Number(f.minRating || 0) > 0;
    if (anyFilter) return false;
    const state = homeLocal.value || {};
    if (state.loading || state.error) return false;
    return !(state.items || []).length;
  });

  // --- presentation mode (infinite scroll vs paged) --------------------------
  // Both modes drive the same feeds through the same endpoints; the difference
  // is whether a fetch appends to what is on screen or replaces it with one
  // page. The mode is a single setting, so it cannot be "both on".
  const feedMode = computed(() => normalizeFeedMode(settingsStore.config?.LOCAL_LIB_FEED_MODE));
  const feedPageSize = computed(() => normalizeFeedPageSize(settingsStore.config?.LOCAL_LIB_PAGE_SIZE));
  const feedPaged = computed(() => feedMode.value === FEED_MODE_PAGED);
  // Meaningless outside paged mode, and deliberately reported as false there so
  // a stale "true" cannot leave the bottom affordance armed.
  const feedPullToPage = computed(() => feedPaged.value && settingsStore.config?.LOCAL_LIB_PULL_TO_PAGE === true);

  const feedPage = computed(() => Math.max(1, Number(feedPages.value?.[currentFeedTabKey()] || 1)));

  function setFeedPage(page) {
    const key = currentFeedTabKey();
    const next = Math.max(1, Math.floor(Number(page) || 1));
    feedPages.value = { ...(feedPages.value || {}), [key]: next };
    const high = Number(feedHighPages.value?.[key] || 0);
    if (next > high) feedHighPages.value = { ...(feedHighPages.value || {}), [key]: next };
    return next;
  }

  const feedCanPrev = computed(() => feedPage.value > 1);
  const feedCanNext = computed(() => !!activeHomeState.value?.hasMore);
  // Furthest page the jump box may target: everything reached so far, plus one
  // more when the server says there is more. Never invented beyond that.
  const feedMaxJump = computed(() => {
    const key = currentFeedTabKey();
    const high = Math.max(Number(feedHighPages.value?.[key] || 0), feedPage.value);
    return high + (feedCanNext.value ? 1 : 0);
  });

  function normalizeHomeTab(raw) {
    const key = String(raw || "").trim();
    const legacy = {
      recommend: "local_gallery",
      favorite: "local_favorite",
      local: "local_gallery",
      history: "local_history",
      search: "local_gallery",
    };
    const next = legacy[key] || key;
    const allowed = new Set(LOCAL_HOME_TABS);
    return allowed.has(next) ? next : "local_gallery";
  }

  function currentFeedTabKey() {
    return String(homeTab.value || "local_gallery");
  }

  function _nextFeedRequestId(tabKey) {
    const key = String(tabKey || "");
    const next = Number(feedRequestSeq.value?.[key] || 0) + 1;
    feedRequestSeq.value = { ...(feedRequestSeq.value || {}), [key]: next };
    return next;
  }

  function _isFeedRequestCurrent(tabKey, requestId) {
    const key = String(tabKey || "");
    return Number(feedRequestSeq.value?.[key] || 0) === Number(requestId || 0);
  }

  function markFeedFetched(tabKey) {
    const key = String(tabKey || "");
    feedLastFetchedAt.value = { ...(feedLastFetchedAt.value || {}), [key]: Date.now() };
  }

  function isRealtimeRefreshTab(tabKey = "") {
    const key = String(tabKey || currentFeedTabKey());
    return LOCAL_HOME_TABS.includes(key);
  }

  function isFeedStale(tabKey = "", ttlMs = 5 * 60 * 1000) {
    const key = String(tabKey || currentFeedTabKey());
    const ts = Number(feedLastFetchedAt.value?.[key] || 0);
    if (!ts) return true;
    return Date.now() - ts > Math.max(1000, Number(ttlMs || 0));
  }

  function setHomeTab(next) {
    homeTab.value = normalizeHomeTab(next);
  }

  function isLocalGalleryTab() {
    return homeTab.value === "local_gallery";
  }

  function isLocalFavoriteTab() {
    return homeTab.value === "local_favorite";
  }

  function isHistoryTab() {
    return homeTab.value === "local_history";
  }

  function isLocalHistoryTab() {
    return homeTab.value === "local_history";
  }

  function isUploadTab() {
    return homeTab.value === "local_upload";
  }

  function isPlaceholderTab() {
    return false;
  }

  function init(deps = {}) {
    if (deps.configRef) _configRef = deps.configRef;
    if (typeof deps.getConfig === "function") _getConfig = deps.getConfig;
    if (typeof deps.getLang === "function") _getLang = deps.getLang;
    if (typeof deps.getTab === "function") _getTab = deps.getTab;
    if (typeof deps.getRail === "function") _getRail = deps.getRail;
    if (typeof deps.t === "function") _t = deps.t;
    if (typeof deps.notify === "function") _notify = deps.notify;
    if (typeof deps.formatDateMinute === "function") _formatDateMinute = deps.formatDateMinute;
  }

  const config = computed({
    get() {
      if (_configRef && typeof _configRef === "object" && "value" in _configRef) {
        return _configRef.value || {};
      }
      return _getConfig();
    },
    set(v) {
      if (_configRef && typeof _configRef === "object" && "value" in _configRef) {
        _configRef.value = v || {};
      }
    },
  });

  function parseBool(value, defaultValue = false) {
    if (value === true || value === false) return value;
    if (value === 1 || value === "1") return true;
    if (value === 0 || value === "0") return false;
    const s = String(value ?? "").trim().toLowerCase();
    if (["true", "yes", "on"].includes(s)) return true;
    if (["false", "no", "off"].includes(s)) return false;
    return !!defaultValue;
  }

  function t(key, vars = {}) {
    return _t(key, vars);
  }

  function getGalleryTitle(item) {
    if (item.display_title) return item.display_title;
    if (item.user_title) return item.user_title;
    if (config.value.REC_SHOW_JPN_TITLE && item.subtitle) {
      return item.subtitle;
    }
    return item.title || "-";
  }

  function searchResultLimit() {
    const config = _getConfig();
    if (config.SEARCH_RESULT_INFINITE) return 300;
    const n = Number(config.SEARCH_RESULT_SIZE || 20);
    if (n === 50 || n === 100) return n;
    return 20;
  }

  function formatEpoch(v) {
    const ep = Number(v || 0);
    if (!ep) return "-";
    return _formatDateMinute(new Date(ep * 1000).toISOString());
  }

  function categoryLabel(item) {
    const raw = String(item?.category || "").trim().toLowerCase();
    if (raw && categoryMap.value[raw]) return getCategoryLabel(categoryMap.value[raw], _t);
    if (raw) return raw;
    return "";
  }

  function itemSubtitle(item) {
    if (String(item?.source || "") === "folder") {
      const c = Number(item?.meta?.folder_gallery_count || 0);
      return c > 0 ? `${_t("home.local.folder_item")} · ${c} ${_t("home.local.folder_galleries")}` : _t("home.local.folder_item");
    }
    const src = "Local";
    const epoch = item?.meta?.read_time || item?.meta?.posted || item?.meta?.date_added;
    const cat = categoryLabel(item);
    const page = isLocalGalleryTab() && isLocalFolderMode() ? "" : pageCountText(item);
    return `${src} · ${formatEpoch(epoch)}${cat ? ` · ${cat}` : ""}${page ? ` · ${page}` : ""}`;
  }

  function itemRatingValue(item) {
    const raw = item?.raw?.rating ?? item?.meta?.rating ?? item?.rating;
    const n = Number(raw);
    if (!Number.isFinite(n)) return null;
    const clamped = Math.max(0, Math.min(5, n));
    return Math.round(clamped * 10) / 10;
  }

  function shouldShowPageCount() {
    return config.value.REC_SHOW_PAGE_COUNT !== false;
  }

  function requestWorkPageCount(item) {
    const arcid = String(item?.arcid || "").trim();
    if (!arcid) return;
    if (pageCountCache.value[arcid] !== undefined) return;
    if (pageCountLoading.value[arcid]) return;
    pageCountLoading.value = { ...pageCountLoading.value, [arcid]: true };
    getReaderManifest(arcid).then((res) => {
      const n = Number(res?.page_count || 0);
      pageCountCache.value = {
        ...pageCountCache.value,
        [arcid]: Number.isFinite(n) && n > 0 ? Math.floor(n) : 0,
      };
    }).catch(() => {
      pageCountCache.value = {
        ...pageCountCache.value,
        [arcid]: 0,
      };
    }).finally(() => {
      const next = { ...pageCountLoading.value };
      delete next[arcid];
      pageCountLoading.value = next;
    });
  }

  function pageCount(item) {
    if (!shouldShowPageCount()) return 0;
    if (String(item?.source || "") === "works") {
      const arcid = String(item?.arcid || "").trim();
      if (!arcid) return 0;
      const cached = Number(pageCountCache.value[arcid]);
      if (Number.isFinite(cached) && cached > 0) return Math.floor(cached);
      requestWorkPageCount(item);
    }
    return 0;
  }

  function pageCountText(item) {
    const n = pageCount(item);
    return n > 0 ? `${n}P` : "";
  }

  function itemPrimaryLink(item) {
    if (String(item?.source || "") === "folder") return "#";
    return item?.link_url || "#";
  }

  function isLocalFolderMode() {
    return String(localGalleryMode.value || "flat") === "folder";
  }

  function normalizeFolderRows(folders = []) {
    return (folders || []).map((f) => {
      const p = String(f?.path || "").trim();
      const n = String(f?.name || p || "folder").trim();
      const count = Math.max(0, Number(f?.gallery_count || 0));
      return {
        id: `folder:${p}`,
        source: "folder",
        title: n,
        subtitle: "",
        tags: [],
        tags_translated: [],
        link_url: "#",
        thumb_url: "",
        category: "",
        score: 0,
        folder_path: p,
        meta: {
          folder_path: p,
          folder_gallery_count: count,
        },
        raw: {},
      };
    });
  }

  async function openLocalFolder(path = "") {
    localFolderPath.value = String(path || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if (!isLocalGalleryTab() || !isLocalFolderMode()) return;
    await loadHomeFeed(true);
  }

  async function enterLocalFolderFromItem(item) {
    const p = String(item?.folder_path || item?.meta?.folder_path || "").trim();
    if (!p) return;
    await openLocalFolder(p);
  }

  async function goParentLocalFolder() {
    const cur = String(localFolderPath.value || "").trim();
    if (!cur) return;
    const parts = cur.split("/").filter(Boolean);
    parts.pop();
    await openLocalFolder(parts.join("/"));
  }

  function normalizeHomeItem(item) {
    return { ...(item || {}) };
  }

  function normalizeHomeRows(rows) {
    return (rows || []).map((x) => markRaw(normalizeHomeItem(x)));
  }

  function categoryBadgeStyle(item) {
    const raw = String(item?.category || "").trim().toLowerCase();
    const c = categoryMap.value[raw]?.color || "#475569";
    return { backgroundColor: c };
  }

  function itemHoverTags(item) {
    const useTranslated = config.value.REC_USE_TRANSLATED_TAGS;
    const tags = useTranslated && Array.isArray(item?.tags_translated) && item.tags_translated.length
      ? item.tags_translated
      : (item?.tags || []);
    return tags.map((x) => String(x || "").trim()).filter(Boolean);
  }

  function isFavorited(item) {
    const tags = [
      ...((item?.tags || []).map((x) => String(x || "").trim().toLowerCase())),
      ...((item?.tags_translated || []).map((x) => String(x || "").trim().toLowerCase())),
    ];
    return tags.includes("favorited");
  }

  function withFavoritedTag(tags, on) {
    const arr = (tags || []).map((x) => String(x || "").trim()).filter(Boolean);
    const filtered = arr.filter((x) => String(x || "").trim().toLowerCase() !== "favorited");
    return on ? [...filtered, "favorited"] : filtered;
  }

  function applyFavoritedToStates(item, on) {
    const key = String(item?.arcid || "").trim();
    if (!key) return;
    const updateState = (stateRef) => {
      stateRef.value = {
        ...(stateRef.value || {}),
        items: (stateRef.value?.items || []).map((row) => String(row?.arcid || "").trim() === key
          ? { ...row, tags: withFavoritedTag(row?.tags || [], on) }
          : row),
      };
    };
    [homeLocal, homeHistory, homeSearchState, homeLocalFavorite].forEach(updateState);
    if (String(mobilePreviewItem.value?.arcid || "").trim() === key) {
      mobilePreviewItem.value = {
        ...mobilePreviewItem.value,
        tags: withFavoritedTag(mobilePreviewItem.value?.tags || [], on),
      };
    }
  }

  function updateLocalWorkItem(arcid, updates) {
    const key = String(arcid || "").trim();
    if (!key) return;
    const patchState = (stateRef) => {
      stateRef.value = {
        ...(stateRef.value || {}),
        items: (stateRef.value?.items || []).map((row) => String(row?.arcid || "").trim() === key
          ? { ...row, ...(updates || {}) }
          : row),
      };
    };
    [homeLocal, homeHistory, homeSearchState, homeLocalFavorite].forEach(patchState);
  }

  /**
   * Flip the star first, talk to the server second -- the same optimistic shape
   * `setItemRating` uses. Waiting for the POST leaves the icon stale for a whole
   * round trip, and the desktop hover preview holds a *snapshot* of the item, so
   * a later "rewrite the feed rows" pass cannot reach it either. Callers that own
   * such a snapshot patch it themselves and roll back when this returns false.
   */
  async function toggleFavorite(item) {
    const arcid = String(item?.arcid || "").trim();
    if (String(item?.source || "") !== "works" || !arcid) return false;
    const prev = isFavorited(item);
    const next = !prev;
    applyFavoritedToStates(item, next);
    try {
      await postHomeFavoriteToggle({ source: "works", arcid, favorited: next });
    } catch (e) {
      applyFavoritedToStates(item, prev);
      _notify(String(e?.response?.data?.detail || e), "warning");
      return false;
    }
    _notify(_t(next ? "home.favorite.added" : "home.favorite.removed"), "success");
    return true;
  }


  function effectiveFilterCategories() {
    const all = pinnedHomeFilterCategoryDefs.value.map((x) => x.key);
    const selected = homeFilters.value.categories || [];
    if (selected.length === all.length) return [];
    if (selected.length === 0) return ["__none__"];
    return selected;
  }

  function isTagFilterActive(tag) {
    const t = String(tag || "").trim().toLowerCase();
    return (homeFilters.value.tags || []).map((x) => String(x || "").trim().toLowerCase()).includes(t);
  }

  function toggleTagFilter(tag) {
    const t = String(tag || "").trim();
    if (!t) return;
    const arr = [...(homeFilters.value.tags || [])];
    const i = arr.findIndex((x) => String(x).toLowerCase() === t.toLowerCase());
    if (i >= 0) arr.splice(i, 1);
    else arr.push(t);
    homeFilters.value.tags = arr;
    if (String(homeSearchQuery.value || "").trim()) rerunSearchWithFilters().catch(() => null);
  }

  async function applyTagFilterFromCard(payload) {
    const t = String(typeof payload === "object" && payload !== null ? (payload.tag || "") : (payload || "")).trim();
    if (!t) return;
    const arr = [...(homeFilters.value.tags || [])];
    const idx = arr.findIndex((x) => String(x || "").toLowerCase() === t.toLowerCase());
    if (idx >= 0) arr.splice(idx, 1);
    else arr.push(t);
    homeFilters.value.tags = arr;
    if (String(homeSearchQuery.value || "").trim()) {
      await rerunSearchWithFilters();
      return;
    }
    await resetHomeFeed();
  }

  function _patchItemRating(row, rating) {
    if (!row || typeof row !== "object") return row;
    const nextMeta = { ...(row.meta || {}) };
    nextMeta.rating = rating;
    const nextRaw = { ...(row.raw || {}) };
    nextRaw.rating = rating === null ? "" : String(rating);
    return { ...row, meta: nextMeta, raw: nextRaw };
  }

  function _matchItemKey(src, row, key) {
    void src;
    return String(row?.arcid || "").trim() === key;
  }

  function _applyRatingToStates(item, rating) {
    const src = String(item?.source || "").trim();
    const key = String(item?.arcid || "").trim();
    if (!key) return;
    const patchState = (stateRef) => {
      stateRef.value = {
        ...(stateRef.value || {}),
        items: (stateRef.value?.items || []).map((row) => (_matchItemKey(src, row, key) ? _patchItemRating(row, rating) : row)),
      };
    };
    patchState(homeHistory);
    patchState(homeLocal);
    patchState(homeSearchState);
    patchState(homeLocalFavorite);
    if (mobilePreviewItem.value && _matchItemKey(src, mobilePreviewItem.value, key)) {
      mobilePreviewItem.value = _patchItemRating(mobilePreviewItem.value, rating);
    }
  }

  async function setItemRating(payload = {}) {
    const item = payload?.item || null;
    const rawRating = payload?.rating;
    if (!item) return;
    const src = String(item?.source || "").trim();
    if (src !== "works") return;
    const parsed = Number(rawRating);
    const rating = Number.isFinite(parsed) ? Math.max(0, Math.min(5, Math.round(parsed * 2) / 2)) : null;
    const prev = itemRatingValue(item);
    _applyRatingToStates(item, rating);
    try {
      await postHomeRatingSet({
        source: src,
        arcid: String(item?.arcid || ""),
        rating,
      });
    } catch (e) {
      _applyRatingToStates(item, prev);
      _notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  function scrollToTop() {
    if (typeof window !== "undefined") {
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function onMobilePreviewToggle(v) {
    if (!v) mobilePreviewItem.value = null;
  }

  function onCoverClick(item) {
    if (!isMobile.value) return;
    mobilePreviewItem.value = item || null;
  }

  function onMobileDetailLinkClick() {
    mobilePreviewItem.value = null;
  }

  function openLocalSortDialog() {
    localSortOpen.value = true;
  }

  async function applyLocalSort() {
    localSortOpen.value = false;
    if (isLocalGalleryTab() && !isLocalFolderMode()) {
      await resetHomeFeed();
    }
  }

  function updateViewportFlags() {
    if (typeof window === "undefined") return;
    isMobile.value = window.innerWidth < 960;
  }

  function onWindowScroll() {
    if (typeof window === "undefined") return;
    const y = Math.max(
      Number(window.scrollY || 0),
      Number(document?.documentElement?.scrollTop || 0),
      Number(document?.body?.scrollTop || 0),
    );
    lastWindowScrollY.value = y;
    const isDashboard = _getTab() === "dashboard";
    showScrollQuickActions.value = isDashboard && (isMobile.value ? y > 220 : y > 120);
  }

  function runQuickSearch() {
    quickSearchOpen.value = false;
    runHomeSearchPlaceholder().catch(() => null);
  }

  function quickImageSearch() {
    quickSearchOpen.value = false;
    imageSearchDialog.value = true;
  }

  function openQuickFilters() {
    quickSearchOpen.value = false;
    homeFiltersOpen.value = true;
  }

  function toggleHomeFilterCategory(key) {
    const k = String(key || "");
    const set = new Set(homeFilters.value.categories || []);
    if (set.has(k)) set.delete(k);
    else set.add(k);
    homeFilters.value.categories = Array.from(set);
  }

  function selectAllHomeFilterCategories() {
    homeFilters.value.categories = pinnedHomeFilterCategoryDefs.value.map((x) => x.key);
  }

  function clearAllHomeFilterCategories() {
    homeFilters.value.categories = [];
  }

  function homeFilterCategoryStyle(key, color) {
    const on = (homeFilters.value.categories || []).includes(key);
    return {
      backgroundColor: on ? color : "#424242",
      color: "#ffffff",
      opacity: on ? 1 : 0.45,
    };
  }

  function clearHomeFilters() {
    homeFilters.value = { categories: pinnedHomeFilterCategoryDefs.value.map((x) => x.key), tags: [], minRating: 0 };
    filterTagInput.value = "";
    filterTagSuggestions.value = [];
  }

  function isNlSearchAllowed(tab = "") {
    const t = String(tab || homeTab.value || "").trim();
    return !isRealtimeRefreshTab(t);
  }

  function searchScopeForCurrentTab(tab = "") {
    void tab;
    return "works";
  }

  function activeSearchTargetState() {
    return activeHomeState.value || homeLocal.value;
  }

  async function loadTagSuggestions() {
    const q = String(filterTagInput.value || "").trim();
    if (q.length < 2) {
      filterTagSuggestions.value = [];
      return;
    }
    try {
      const res = await getHomeTagSuggest({ q, limit: 10, ui_lang: _getLang() });
      filterTagSuggestions.value = res.items || [];
    } catch {
      filterTagSuggestions.value = [];
    }
  }

  async function rerunSearchWithFilters() {
    const config = _getConfig();
    const cats = effectiveFilterCategories();
    const tags = homeFilters.value.tags || [];
    const minRating = Number(homeFilters.value?.minRating || 0);
    const targetTab = String(homeTab.value || "").trim();
    const ctx0 = lastSearchContext.value || {};
    const fallbackQ = String(homeSearchQuery.value || "").trim();
    const q = String(ctx0.query || fallbackQ || "").trim();
    const scope = searchScopeForCurrentTab(targetTab);
    const useLlm = isNlSearchAllowed(targetTab) && !!config.SEARCH_NL_ENABLED;
    const target = activeSearchTargetState();
    if (ctx0.mode === "text" && String(ctx0.query || "").trim()) {
      const res = await searchByText({ query: q, scope, limit: searchResultLimit(), use_llm: useLlm, ui_lang: _getLang(), include_categories: cats, include_tags: tags, min_rating: minRating });
      target.items = normalizeHomeRows(res.items || []);
      target.cursor = "";
      target.hasMore = false;
      lastSearchContext.value = { mode: "text", query: q, hasImage: false };
      return;
    }
    if ((ctx0.mode === "image" || selectedImageFile.value) && selectedImageFile.value) {
      const res = await searchByImageUpload(selectedImageFile.value, {
        scope,
        limit: searchResultLimit(),
        query: q,
        ui_lang: _getLang(),
        text_weight: Number(config.SEARCH_MIXED_TEXT_WEIGHT ?? 0.5),
        visual_weight: Number(config.SEARCH_MIXED_VISUAL_WEIGHT ?? 0.5),
        include_categories: cats.join(","),
        include_tags: tags.join(","),
        min_rating: minRating,
      });
      target.items = normalizeHomeRows(res.items || []);
      target.cursor = "";
      target.hasMore = false;
      lastSearchContext.value = { mode: "image", query: q, hasImage: true };
      return;
    }
    if (q) {
      const res = await searchByText({ query: q, scope, limit: searchResultLimit(), use_llm: useLlm, ui_lang: _getLang(), include_categories: cats, include_tags: tags, min_rating: minRating });
      target.items = normalizeHomeRows(res.items || []);
      target.cursor = "";
      target.hasMore = false;
      lastSearchContext.value = { mode: "text", query: q, hasImage: false };
    }
  }

  async function applyHomeFilters() {
    homeFiltersOpen.value = false;
    if (String(homeSearchQuery.value || "").trim()) {
      await rerunSearchWithFilters();
      return;
    }
    if (isHistoryTab() || isLocalGalleryTab() || isLocalFavoriteTab()) {
      await resetHomeFeed();
    }
  }

  function mergeUniqueItems(oldRows = [], newRows = []) {
    const out = [];
    const seen = new Set();
    for (const row of [...(oldRows || []), ...(newRows || [])]) {
      const key = `works:${String(row?.arcid || "").trim()}`;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push(row);
    }
    return out;
  }

  // Shared request shaping for both presentation modes. `cursor` is an offset in
  // every feed the dashboard shows (all four endpoints parse it as one), which is
  // what makes page arithmetic possible without inventing a new API.
  function _buildHomeFeedParams({ limit, cursor = "" }) {
    const params = { limit: Number(limit) || FEED_INFINITE_LIMIT };
    if (cursor) params.cursor = String(cursor);
    const cats = effectiveFilterCategories();
    const tags = (homeFilters.value.tags || []).map((x) => String(x || "").trim()).filter(Boolean);
    if (cats.length) params.include_categories = cats.join(",");
    if (tags.length) params.include_tags = tags.join(",");
    const minRating = Number(homeFilters.value?.minRating || 0);
    if (Number.isFinite(minRating) && minRating > 0) params.min_rating = minRating;
    if (isLocalGalleryTab() && !isLocalFolderMode()) {
      params.sort_by = String(localSortBy.value || "xp");
      params.sort_order = String(localSortOrder.value || "desc");
    }
    return params;
  }

  async function _requestHomeFeed({ limit, cursor = "" }) {
    const params = _buildHomeFeedParams({ limit, cursor });
    if (isLocalGalleryTab() && isLocalFolderMode()) {
      return getLocalFolderList({
        path: String(localFolderPath.value || ""),
        cursor: String(cursor || ""),
        limit: Number(limit) || FEED_INFINITE_LIMIT,
      });
    }
    if (isHistoryTab()) return getHomeHistory(params);
    if (isLocalFavoriteTab()) return getHomeFavorite(params);
    return getHomeLocal(params);
  }

  // Writes a fetched payload onto the active feed. `replace` is the whole
  // difference between the two modes: paging shows exactly one page, while
  // scrolling appends onto what the user has already seen.
  function _applyHomeFeedPayload(res, { replace }) {
    const state = activeHomeState.value;
    if (isLocalGalleryTab() && isLocalFolderMode()) {
      const folderRows = normalizeFolderRows(res.folders || []);
      const galleryRows = normalizeHomeRows(res.galleries || []);
      localFolderBreadcrumbs.value = Array.isArray(res?.breadcrumbs) && res.breadcrumbs.length ? res.breadcrumbs : [{ name: "local_lib", path: "" }];
      localFolderNodes.value = folderRows;
      const oldGalleries = replace ? [] : (state.items || []).filter((x) => String(x?.source || "") === "works");
      state.items = [...folderRows, ...mergeUniqueItems(oldGalleries, galleryRows)];
    } else {
      const rows = normalizeHomeRows(res.items || []);
      state.items = replace ? rows : mergeUniqueItems(state.items || [], rows);
    }
    state.cursor = String(res?.next_cursor || "");
    state.hasMore = !!res?.has_more;
  }

  async function loadHomeFeed(reset = false) {
    // A paged feed never appends. Every existing trigger (first paint, refresh,
    // the emptied-feed recovery, the scroll observer) still funnels through here,
    // so redirecting is what keeps one entry point instead of two.
    if (feedPaged.value) {
      return loadHomePage(reset ? 1 : feedPage.value);
    }
    const state = activeHomeState.value;
    if (isUploadTab() || state.loading || (!state.hasMore && !reset)) return;
    const tabKey = currentFeedTabKey();
    const requestId = _nextFeedRequestId(tabKey);
    state.loading = true;
    state.error = "";
    try {
      const res = await _requestHomeFeed({
        limit: FEED_INFINITE_LIMIT,
        cursor: (!reset && state.cursor) ? state.cursor : "",
      });
      if (!_isFeedRequestCurrent(tabKey, requestId)) return;
      _applyHomeFeedPayload(res, { replace: !!reset });
      markFeedFetched(tabKey);
    } catch (e) {
      if (_isFeedRequestCurrent(tabKey, requestId)) state.error = String(e?.response?.data?.detail || e);
    } finally {
      if (_isFeedRequestCurrent(tabKey, requestId)) state.loading = false;
    }
  }

  /**
   * Load exactly one page of the active feed, replacing whatever is on screen.
   *
   * The endpoints report `has_more` but no total, so nothing here invents a page
   * count: "next" is enabled by `has_more`, and the jump box is bounded by
   * `feedMaxJump` (the furthest page actually reached, plus one).
   */
  async function loadHomePage(page = 1) {
    const state = activeHomeState.value;
    if (isUploadTab() || state.loading) return;
    const size = Number(feedPageSize.value) || FEED_DEFAULT_PAGE_SIZE;
    const target = Math.max(1, Math.floor(Number(page) || 1));
    const tabKey = currentFeedTabKey();
    const requestId = _nextFeedRequestId(tabKey);
    state.loading = true;
    state.error = "";
    let landed = target;
    try {
      const res = await _requestHomeFeed({ limit: size, cursor: String((target - 1) * size) });
      if (!_isFeedRequestCurrent(tabKey, requestId)) return;
      _applyHomeFeedPayload(res, { replace: true });
      // An empty page is always a page past the end -- either the feed shrank or
      // a jump overshot. Step back instead of parking the user on a blank screen.
      if (!(state.items || []).length && target > 1) landed = target - 1;
    } catch (e) {
      if (_isFeedRequestCurrent(tabKey, requestId)) state.error = String(e?.response?.data?.detail || e);
      return;
    } finally {
      if (_isFeedRequestCurrent(tabKey, requestId)) state.loading = false;
    }
    if (landed !== target) return loadHomePage(landed);
    setFeedPage(target);
  }

  async function goToFeedPage(page) {
    if (!feedPaged.value) return;
    return loadHomePage(page);
  }

  async function nextFeedPage() {
    if (!feedPaged.value || !feedCanNext.value) return;
    return loadHomePage(feedPage.value + 1);
  }

  async function prevFeedPage() {
    if (!feedPaged.value || !feedCanPrev.value) return;
    return loadHomePage(feedPage.value - 1);
  }

  // Switching presentation invalidates what is on screen: the appended pile of an
  // infinite feed is not a page, and a single page is not something infinite
  // scrolling may append onto.
  //
  // Emptying is not enough on its own. The user flips the switch over in the
  // settings tab, so nothing on the dashboard is running to refetch: `activated`
  // only restores the scroll offset, and the tab watcher does not fire because the
  // tab did not change. They came back to a blank feed. Rebuild the active feed
  // here, in the background, so it is already populated on arrival.
  let feedModeSeen = false;
  watch(feedPaged, () => {
    clearHomeObserver();
    [homeLocal, homeHistory, homeLocalFavorite, homeSearchState].forEach((stateRef) => {
      stateRef.value = { ...(stateRef.value || {}), items: [], cursor: "", hasMore: true };
    });
    feedPages.value = {};
    feedHighPages.value = {};

    // The very first observation of `infinite` is just the default being confirmed
    // while the config loads -- the dashboard's own mount already fetches that one.
    // Every other transition leaves a feed that must be fetched again.
    const worthRebuilding = feedModeSeen || feedPaged.value;
    feedModeSeen = true;
    if (!worthRebuilding || isUploadTab()) return;
    setFeedPage(1);
    loadHomeFeed(true).catch(() => null);
  });


  async function refreshCurrentHomeFeed(opts = {}) {
    if (isUploadTab()) return;
    const force = opts?.force !== false;
    if (!force && !isFeedStale(currentFeedTabKey(), 5 * 60 * 1000)) return;
    await loadHomeFeed(true);
  }

  async function resetHomeFeed() {
    const target = activeHomeState.value;
    target.items = [];
    target.cursor = "";
    target.hasMore = !isUploadTab() && !(isLocalGalleryTab() && isLocalFolderMode());
    if (!isUploadTab()) {
      // A reset means "start over", which in paged mode is page one.
      if (feedPaged.value) setFeedPage(1);
      await loadHomeFeed(true);
    }
  }

  async function runHomeSearchPlaceholder() {
    const config = _getConfig();
    const q = String(homeSearchQuery.value || "").trim();
    if (!q) {
      lastSearchContext.value = { mode: "", query: "", hasImage: false };
      await resetHomeFeed();
      _notify(_t("common.refresh"), "success");
      return;
    }
    const targetTab = String(homeTab.value || "").trim();
    try {
      const target = activeSearchTargetState();
      const scope = searchScopeForCurrentTab(targetTab);
      const res = await searchByText({
        query: q,
        scope,
        limit: searchResultLimit(),
        use_llm: isNlSearchAllowed(targetTab) && !!config.SEARCH_NL_ENABLED,
        ui_lang: _getLang(),
        include_categories: effectiveFilterCategories(),
        include_tags: homeFilters.value.tags || [],
        min_rating: Number(homeFilters.value?.minRating || 0),
      });
      target.items = normalizeHomeRows(res.items || []);
      target.cursor = "";
      target.hasMore = false;
      lastSearchContext.value = { mode: "text", query: q, hasImage: false };
      _notify(_t("home.search.done"), "success");
    } catch (e) {
      _notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  async function runImageSearchQuick() {
    try {
      if (!homeHistory.value.items.length) {
        await (isHistoryTab() ? loadHomeFeed(false) : getHomeHistory({ limit: 12 }).then((res) => {
          homeHistory.value.items = res.items || [];
          homeHistory.value.cursor = res.next_cursor || "";
          homeHistory.value.hasMore = !!res.has_more;
        }));
      }
      const refItem = (homeHistory.value.items || []).find((x) => x.source === "works" && x.arcid);
      if (!refItem?.arcid) {
        _notify(_t("home.search.camera_placeholder"), "info");
        return;
      }
      const res = await searchByImage({ arcid: refItem.arcid, scope: "works", limit: searchResultLimit() });
      homeLocal.value.items = normalizeHomeRows(res.items || []);
      homeLocal.value.cursor = "";
      homeLocal.value.hasMore = false;
      homeTab.value = "local_gallery";
      _notify(_t("home.search.image_ready"), "success");
    } catch (e) {
      _notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  function triggerImagePicker() {
    if (imageFileInputRef.value) imageFileInputRef.value.click();
  }

  function onImagePickChange(event) {
    const file = event?.target?.files?.[0];
    selectedImageFile.value = file || null;
  }

  async function onImageDrop(event) {
    imageDropActive.value = false;
    const file = event?.dataTransfer?.files?.[0];
    if (!file) return;
    if (!String(file.type || "").startsWith("image/")) {
      _notify(_t("home.image_upload.only_image"), "warning");
      return;
    }
    selectedImageFile.value = file;
    if (String(homeSearchQuery.value || "").trim()) {
      await runImageUploadSearch();
    }
  }

  async function runImageUploadSearch() {
    if (!selectedImageFile.value) return;
    const config = _getConfig();
    const targetTab = String(homeTab.value || "").trim();
    const target = activeSearchTargetState();
    try {
      const res = await searchByImageUpload(selectedImageFile.value, {
        scope: searchScopeForCurrentTab(targetTab),
        limit: searchResultLimit(),
        ui_lang: _getLang(),
        query: String(imageSearchQuery.value || "").trim(),
        text_weight: Number(config.SEARCH_MIXED_TEXT_WEIGHT ?? 0.5),
        visual_weight: Number(config.SEARCH_MIXED_VISUAL_WEIGHT ?? 0.5),
        include_categories: effectiveFilterCategories().join(","),
        include_tags: (homeFilters.value.tags || []).join(","),
        min_rating: Number(homeFilters.value?.minRating || 0),
      });
      target.items = normalizeHomeRows(res.items || []);
      target.cursor = "";
      target.hasMore = false;
      lastSearchContext.value = { mode: "image", query: String(imageSearchQuery.value || "").trim(), hasImage: true };
      imageSearchDialog.value = false;
      _notify(_t("home.search.image_uploaded_ready"), "success");
    } catch (e) {
      _notify(String(e?.response?.data?.detail || e), "warning");
    }
  }

  function bindHomeInfiniteScroll() {
    clearHomeObserver();
    if (feedPaged.value) {
      // Nothing appends on scroll in paged mode -- but mounting still has to fetch
      // the page that is on screen. Without this, unbinding the observer would
      // leave the feed permanently empty because the observer *was* the trigger.
      const state = activeHomeState.value;
      if (!isUploadTab() && !state.loading && !(state.items || []).length) {
        loadHomePage(feedPage.value).catch(() => null);
      }
      return;
    }
    if (!homeSentinel.value || typeof IntersectionObserver === "undefined") return;
    homeObserver = new IntersectionObserver((entries) => {
      const first = entries[0];
      if (!first?.isIntersecting) return;
      loadHomeFeed(false).catch(() => null);
    }, { root: null, rootMargin: "600px 0px", threshold: 0.01 });
    homeObserver.observe(homeSentinel.value);
  }

  function clearHomeObserver() {
    if (homeObserver) {
      homeObserver.disconnect();
      homeObserver = null;
    }
  }

   async function showImageLoadTraceback(item, failedUrl = "") {
    const url = String(failedUrl || item?._thumb_primary || item?.thumb_url || "").trim();
    if (!url) return;
    const keyBase = String(item?.arcid || "unknown");
    const dedupeKey = `${keyBase}|${url}`;
    const now = Date.now();
    const prev = Number(imageTracebackStamp.get(dedupeKey) || 0);
    if (now - prev < 3000) return;
    imageTracebackStamp.set(dedupeKey, now);
    try {
      const res = await fetch(url, { method: "GET", cache: "no-store", credentials: "same-origin" });
      if (res.ok) return;
      const body = await res.text();
      const detail = String(body || `HTTP ${res.status} ${res.statusText || ""}`).trim();
      _notify(detail || `image load failed: ${url}`, "warning");
    } catch (e) {
      _notify(String(e?.message || e || `image load failed: ${url}`), "warning");
    }
  }

  return {
    config,
    homeTab,
    setHomeTab,
    homeViewMode,
    homeSearchQuery,
    imageSearchQuery,
    homeSentinel,
    homeHistory,
    homeLocal,
    homeLocalFavorite,
    homeSearchState,
    localSortOpen,
    localSortBy,
    localSortOrder,
    localSortAsc,
    localGalleryMode,
    localFolderPath,
    localFolderBreadcrumbs,
    localFolderNodes,
    homeFiltersOpen,
    homeFilters,
    filterTagInput,
    filterTagSuggestions,
    lastSearchContext,
    imageSearchDialog,
    imageDropActive,
    selectedImageFile,
    imageFileInputRef,
    mobilePreviewItem,
    isMobile,
    quickSearchOpen,
    showScrollQuickActions,
    lastWindowScrollY,
    localCategoryDefs: categoryDefs,
    pinnedHomeFilterCategoryDefs,
    activeHomeState,
    filteredHomeItems,
    libraryEmptyWithoutFilters,
    feedLastFetchedAt,
    quickFabStyle,
    t,
    init,
    searchResultLimit,
    itemSubtitle,
    itemRatingValue,
    itemPrimaryLink,
    categoryLabel,
    pageCountText,
    categoryBadgeStyle,
    itemHoverTags,
    isFavorited,
    toggleFavorite,
    effectiveFilterCategories,
    isTagFilterActive,
    toggleTagFilter,
    applyTagFilterFromCard,
    isRealtimeRefreshTab,
    isFeedStale,
    refreshCurrentHomeFeed,
    setItemRating,
    scrollToTop,
    onMobilePreviewToggle,
    onCoverClick,
    onMobileDetailLinkClick,
    openLocalSortDialog,
    applyLocalSort,
    isLocalFolderMode,
    openLocalFolder,
    enterLocalFolderFromItem,
    goParentLocalFolder,
    updateViewportFlags,
    onWindowScroll,
    runQuickSearch,
    quickImageSearch,
    openQuickFilters,
    toggleHomeFilterCategory,
    selectAllHomeFilterCategories,
    clearAllHomeFilterCategories,
    homeFilterCategoryStyle,
    clearHomeFilters,
    loadTagSuggestions,
    rerunSearchWithFilters,
    applyHomeFilters,
    loadHomeFeed,
    resetHomeFeed,
    loadHomePage,
    feedMode,
    feedPageSize,
    feedPaged,
    feedPullToPage,
    feedPage,
    feedCanPrev,
    feedCanNext,
    feedMaxJump,
    goToFeedPage,
    nextFeedPage,
    prevFeedPage,
    runHomeSearchPlaceholder,
    runImageSearchQuick,
    triggerImagePicker,
    onImagePickChange,
    onImageDrop,
    runImageUploadSearch,
    showImageLoadTraceback,
    bindHomeInfiniteScroll,
    clearHomeObserver,
    getGalleryTitle,
    updateLocalWorkItem,
  };
});
