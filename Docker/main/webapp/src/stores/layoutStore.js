import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { getInitialLang, setLang, t as tr } from "../i18n";
// Served from `public/ico/` so the PWA manifest and the in-app chrome share it.
const brandLogo = "/ico/ZingLibLogo_128.png";
import { useSettingsStore } from "./settingsStore";
import { useAppStore } from "./appStore";

const TAB_ROUTE_MAP = {
  dashboard: "/dashboard",
  xp: "/xp",
  tools: "/tools",
  settings: "/settings/general",
};

// The dashboard's sub-tab key. DashboardScopePage owns the same string and both
// reads and writes it, so a sidebar entry can address a sub-tab by URL instead
// of racing the page's own state.
const HOME_TAB_QUERY_KEY = "local_tab";
const HOME_TAB_DEFAULT = "local_gallery";

// The primary rail: the local library is the home page, and its two feeds are
// siblings in the sidebar rather than tabs buried inside the page.
const HOME_NAV = [
  { key: "dashboard", homeTab: HOME_TAB_DEFAULT, title: "nav.section.local", icon: "mdi-bookshelf" },
  { key: "dashboard", homeTab: "local_favorite", title: "nav.section.favorite", icon: "mdi-star" },
  { key: "dashboard", homeTab: "local_history", title: "nav.section.history", icon: "mdi-history" },
];

export const useLayoutStore = defineStore("layout", () => {
  const settingsStore = useSettingsStore();
  const appStore = useAppStore();

  const drawer = ref(true);
  const rail = ref(false);
  const tab = ref("dashboard");
  const homeTab = ref(HOME_TAB_DEFAULT);
  const lang = ref(getInitialLang());
  const notices = ref([]);
  const pageZoomOptions = [
    { title: "90%", value: 90 },
    { title: "100%", value: 100 },
    { title: "110%", value: 110 },
    { title: "120%", value: 120 },
    { title: "130%", value: 130 },
  ];
  const pageZoom = ref(100);

  const langOptions = [
    { title: "简体中文", value: "zh" },
    { title: "English", value: "en" },
  ];

  let _navigate = null;
  let _logout = null;

  function clampZoom(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 100;
    return Math.max(90, Math.min(130, Math.round(n / 10) * 10));
  }

  function applyPageZoom() {
    if (typeof document === "undefined") return;
    document.documentElement.style.setProperty("--zgl-page-zoom", String(pageZoom.value / 100));
  }

  if (typeof window !== "undefined") {
    // `autoeh_page_zoom` is the legacy key kept for continuity with pre-rebrand browsers.
    pageZoom.value = clampZoom(window.localStorage.getItem("zgl_page_zoom") || window.localStorage.getItem("autoeh_page_zoom") || 100);
    applyPageZoom();
  }

  const navItems = computed(() => {
    if (appStore.isRecoveryMode) {
      return [
        { key: "settings", title: "tab.settings", icon: "mdi-cog-outline" },
      ];
    }
    return [
      ...HOME_NAV.map((x) => ({ ...x })),
      { key: "tools", title: "tab.tools", icon: "mdi-toolbox-outline" },
      { key: "xp", title: "tab.xp_map", icon: "mdi-chart-bubble" },
      { key: "settings", title: "tab.settings", icon: "mdi-cog-outline" },
    ];
  });

  const currentTitleKey = computed(() => {
    const items = navItems.value;
    // Every home entry shares `key: "dashboard"`, so the sub-tab has to pick
    // the title or the top bar would read "Local Library" on the history feed.
    if (tab.value === "dashboard") {
      const hit = items.find((x) => x.homeTab === homeTab.value);
      if (hit) return hit.title;
    }
    return items.find((x) => x.key === tab.value)?.title || "tab.dashboard";
  });

  const themeModeIcon = computed(() => {
    const mode = String(settingsStore.config.DATA_UI_THEME_MODE || "system");
    if (mode === "light") return "mdi-weather-sunny";
    if (mode === "dark") return "mdi-weather-night";
    return "mdi-brightness-auto";
  });

  function init(deps = {}) {
    if (typeof deps.navigate === "function") _navigate = deps.navigate;
    if (typeof deps.logout === "function") _logout = deps.logout;
  }

  function t(key, vars = {}) {
    return tr(lang.value, key, vars);
  }

  function setLangValue(next) {
    lang.value = setLang(next);
  }

  function pathForTab(key) {
    // The home entries all live on /dashboard, so the sub-tab rides in the query
    // -- pushing a bare "/dashboard" would leave the page on whatever sub-tab it
    // was already showing.
    if (String(key || "") === "dashboard") {
      return { path: "/dashboard", query: { [HOME_TAB_QUERY_KEY]: homeTab.value } };
    }
    return TAB_ROUTE_MAP[key] || "/dashboard";
  }

  function setHomeTab(next) {
    homeTab.value = String(next || HOME_TAB_DEFAULT) || HOME_TAB_DEFAULT;
  }

  function routeToTab(pathname) {
    if (pathname.startsWith("/settings")) return "settings";
    if (pathname.startsWith("/control") || pathname.startsWith("/audit")) return "tools";
    if (pathname.startsWith("/xp")) return "xp";
    if (pathname.startsWith("/tools")) return "tools";
    return "dashboard";
  }

  function goTab(key) {
    tab.value = String(key || "dashboard");
    if (_navigate) _navigate(pathForTab(tab.value));
  }

  function cycleThemeMode() {
    const now = String(settingsStore.config.DATA_UI_THEME_MODE || "system");
    if (now === "system") settingsStore.config.DATA_UI_THEME_MODE = "light";
    else if (now === "light") settingsStore.config.DATA_UI_THEME_MODE = "dark";
    else settingsStore.config.DATA_UI_THEME_MODE = "system";
  }

  function setPageZoom(next) {
    pageZoom.value = clampZoom(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem("zgl_page_zoom", String(pageZoom.value));
    }
    applyPageZoom();
  }

  function pushNotice(type, title, text, options = {}) {
    const id = `${type}-${Date.now()}`;
    const actionLabel = String(options?.actionLabel || "").trim();
    const onAction = typeof options?.onAction === "function" ? options.onAction : null;
    notices.value = (notices.value || []).filter((x) => x.type !== type);
    notices.value.unshift({ id, type, title, text, actionLabel, onAction, ts: Date.now() });
    notices.value = notices.value.slice(0, 100);
  }

  function dismissNotice(id) {
    notices.value = (notices.value || []).filter((x) => x.id !== id);
  }

  function clearAllNotices() {
    notices.value = [];
  }

  function dismissNoticeType(type) {
    notices.value = (notices.value || []).filter((x) => x.type !== type);
  }

  async function runNoticeAction(id) {
    const it = (notices.value || []).find((x) => x.id === id);
    if (!it || typeof it.onAction !== "function") return;
    await it.onAction();
  }

  async function logoutNow() {
    if (_logout) await _logout();
  }

  return {
    drawer,
    rail,
    tab,
    homeTab,
    HOME_TAB_QUERY_KEY,
    lang,
    notices,
    pageZoom,
    pageZoomOptions,
    brandLogo,
    langOptions,
    navItems,
    currentTitleKey,
    themeModeIcon,
    init,
    t,
    setLangValue,
    pathForTab,
    setHomeTab,
    routeToTab,
    goTab,
    cycleThemeMode,
    setPageZoom,
    pushNotice,
    dismissNotice,
    clearAllNotices,
    dismissNoticeType,
    runNoticeAction,
    logoutNow,
  };
});
