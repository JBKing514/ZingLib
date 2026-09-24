<template>
  <v-app>
    <auth-gate
      :logo="brandLogo"
      :t="t"
    />
    <setup-wizard :t="t" />

    <RouterView />


    <v-snackbar
      v-model="toast.show"
      :color="toast.color"
      timeout="3000"
      :z-index="99999"
      content-class="app-toast-snackbar"
    >{{ toast.text }}</v-snackbar>
  </v-app>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import AuthGate from "./components/AuthGate.vue";
import SetupWizard from "./components/SetupWizard.vue";
import { useLayoutStore } from "./stores/layoutStore";
import { useDashboardStore } from "./stores/dashboardStore";
import { useControlStore } from "./stores/controlStore";
import { useAuditStore } from "./stores/auditStore";
import { useXpStore } from "./stores/xpStore";
import { useSettingsStore } from "./stores/settingsStore";
import { useAppStore } from "./stores/appStore";
import { useToastStore } from "./stores/useToastStore";
import { useThemeManager } from "./composables/useThemeManager";
import { formatDateMinute, formatDateTime } from "./utils/helpers";
import { cancelTagReapply, getTagReapplyStatus, getTasks, getVisualTaskStatus, stopTask, stopVisualTask } from "./api";
// Served from `public/ico/` so the PWA manifest and the in-app chrome share it.
const brandLogo = "/ico/ZingLibLogo_128.png";

const router = useRouter();
const route = useRoute();
const layoutStore = useLayoutStore();
const dashboardStore = useDashboardStore();

const controlStore = useControlStore();
const auditStore = useAuditStore();
const xpStore = useXpStore();
const settingsStore = useSettingsStore();
const appStore = useAppStore();
const toastStore = useToastStore();

const {
  updateViewportFlags,
  onWindowScroll,
  clearTouchPreviewTimer,
  resetHomeFeed,
  bindHomeInfiniteScroll,
  clearHomeObserver,
} = dashboardStore;

const {
  config,
  settingsTab,
  llmReady,
} = storeToRefs(settingsStore);



const {
  showAuthGate: authGateOpen,
  authReady,
} = storeToRefs(appStore);

const toast = toastStore;
let authRequiredListener = null;
let windowScrollListener = null;
let windowResizeListener = null;
let mainScrollEl = null;
let visualTaskTimer = null;
let taskNoticeTimer = null;
let lastVisualErrorSeq = 0;
let appInitialized = false;

function t(key, vars = {}) {
  return layoutStore.t(key, vars);
}

function notify(text, color = "success") {
  toastStore.open(text, color);
}

function visualTaskText(status = {}) {
  const table = String(status?.table || "");
  const current = Math.max(0, Number(status?.current || 0));
  const total = Math.max(current, Number(status?.total || 0));
  if (table === "works") return t("notice.visual_task.works_running", { current, total });
  return t("notice.visual_task.idle");
}

function stopVisualTaskMonitor() {
  if (visualTaskTimer) {
    clearInterval(visualTaskTimer);
    visualTaskTimer = null;
  }
}

function stopTaskNoticeMonitor() {
  if (taskNoticeTimer) {
    clearInterval(taskNoticeTimer);
    taskNoticeTimer = null;
  }
}

function taskNoticeTitle(task) {
  return t("notice.task.title", { task: String(task || "") || "-" });
}

function taskNoticeText(task = {}) {
  const taskName = String(task?.task || "").trim() || "-";
  const shortId = String(task?.task_id || "").slice(0, 8) || "-";
  return t("notice.task.running", { task: taskName, id: shortId });
}

function clearStaleTaskNotices(runningTaskIds = new Set()) {
  for (const n of layoutStore.notices || []) {
    const type = String(n?.type || "");
    if (!type.startsWith("task_running_")) continue;
    const id = type.slice("task_running_".length);
    if (!runningTaskIds.has(id)) {
      layoutStore.dismissNotice(n.id);
    }
  }
}

async function pollTaskNotices() {
  try {
    const data = await getTasks();
    const all = Array.isArray(data?.tasks) ? data.tasks : [];
    const running = all.filter((x) => ["running", "stopping"].includes(String(x?.status || "")));
    const runningIds = new Set(running.map((x) => String(x?.task_id || "")).filter(Boolean));
    clearStaleTaskNotices(runningIds);
    for (const task of running) {
      const tid = String(task?.task_id || "").trim();
      if (!tid) continue;
      const stopping = String(task?.status || "") === "stopping";
      layoutStore.pushNotice(`task_running_${tid}`, taskNoticeTitle(task?.task), taskNoticeText(task), {
        actionLabel: stopping ? "" : t("notice.task.stop_action"),
        onAction: stopping
          ? null
          : async () => {
              try {
                await stopTask(tid);
                notify(t("notice.task.stop_toast"), "warning");
              } catch (e) {
                notify(String(e?.response?.data?.detail || e), "warning");
              }
            },
      });
    }
  } catch {
    // ignore task polling errors
  }
}

function startTaskNoticeMonitor() {
  stopTaskNoticeMonitor();
  pollTaskNotices().catch(() => null);
  pollTagReapply().catch(() => null);
  taskNoticeTimer = setInterval(() => {
    pollTaskNotices().catch(() => null);
    pollTagReapply().catch(() => null);
  }, 2500);
}

// The tag re-apply job is server-side, so it keeps running after the user
// leaves the settings page. Surfacing it here (rather than only inside that
// page's dialog) is what makes "continue in the background" observable.
const TAG_REAPPLY_NOTICE = "local_tag_reapply";

async function pollTagReapply() {
  try {
    const st = await getTagReapplyStatus();
    const status = String(st?.status || "");
    if (!["running", "cancelling"].includes(status)) {
      layoutStore.dismissNoticeType(TAG_REAPPLY_NOTICE);
      return;
    }
    const done = Number(st?.processed || 0);
    const total = Number(st?.total || 0);
    const stopping = status === "cancelling";
    layoutStore.pushNotice(
      TAG_REAPPLY_NOTICE,
      t("notice.tag_reapply.title"),
      t("notice.tag_reapply.running", { done, total }),
      {
        actionLabel: stopping ? "" : t("notice.tag_reapply.cancel_action"),
        onAction: stopping
          ? null
          : async () => {
              try {
                await cancelTagReapply();
                notify(t("notice.tag_reapply.cancel_toast"), "warning");
              } catch (e) {
                notify(String(e?.response?.data?.detail || e), "warning");
              }
            },
      }
    );
  } catch {
    // ignore status polling errors
  }
}

async function pollVisualTaskStatus() {
  try {
    const res = await getVisualTaskStatus();
    const status = res?.status || {};
    const errSeq = Number(status?.last_error_seq || 0);
    if (Number.isFinite(errSeq) && errSeq > lastVisualErrorSeq) {
      lastVisualErrorSeq = errSeq;
      const reason = String(status?.last_error_message || "unknown").trim();
      const table = String(status?.last_error_table || "").trim();
      const item = String(status?.last_error_item || "").trim();
      const tb = String(status?.last_error_traceback || "").trim();
      const lines = [
        table ? `table: ${table}` : "",
        item ? `item: ${item}` : "",
        reason ? `reason: ${reason}` : "",
        tb ? `traceback:\n${tb}` : "",
      ].filter(Boolean);
      const text = lines.join("\n\n").slice(0, 6000);
      layoutStore.pushNotice("visual_task_error", t("notice.visual_task.fail_title"), text);
      notify(t("notice.visual_task.fail_toast", { reason: reason || "unknown" }), "warning");
    }

    if (status?.stopped_by_user) {
      layoutStore.dismissNoticeType("visual_task");
      const hasStoppedNotice = (layoutStore.notices || []).some((x) => x.type === "visual_task_stopped");
      if (!hasStoppedNotice) {
        layoutStore.pushNotice("visual_task_stopped", t("notice.visual_task.title"), t("notice.visual_task.stopped"));
      }
      return;
    }
    if (status?.running && status?.phase === "processing") {
      layoutStore.dismissNoticeType("visual_task_stopped");
      layoutStore.pushNotice("visual_task", t("notice.visual_task.title"), visualTaskText(status), {
        actionLabel: t("notice.visual_task.stop_action"),
        onAction: async () => {
          try {
            await stopVisualTask();
            notify(t("notice.visual_task.stop_toast"), "warning");
            layoutStore.dismissNoticeType("visual_task");
            layoutStore.pushNotice("visual_task_stopped", t("notice.visual_task.title"), t("notice.visual_task.stopped"));
          } catch (e) {
            notify(String(e?.response?.data?.detail || e), "warning");
          }
        },
      });
      return;
    }
    layoutStore.dismissNoticeType("visual_task");
    if (status?.running && status?.phase === "idle") {
      layoutStore.dismissNoticeType("visual_task_stopped");
    }
  } catch {
    // ignore status polling errors
  }
}

function startVisualTaskMonitor() {
  stopVisualTaskMonitor();
  pollVisualTaskStatus().catch(() => null);
  visualTaskTimer = setInterval(() => {
    pollVisualTaskStatus().catch(() => null);
  }, 2500);
}

function formatDateTimeByUi(value) {
  return formatDateTime(value, layoutStore.lang, config.value.DATA_UI_TIMEZONE);
}

function formatDateMinuteByUi(value) {
  return formatDateMinute(value, layoutStore.lang, config.value.DATA_UI_TIMEZONE);
}

// A tab target is either a plain path or a location object: the sidebar's home
// entries all live on /dashboard and carry their sub-tab in `?local_tab=`, so a
// bare path comparison would think "history -> library" needs no navigation.
function sameLocation(target) {
  const to = typeof target === "string" ? { path: target } : (target || {});
  if (String(route.path || "") !== String(to.path || "")) return false;
  const want = String(to.query?.[layoutStore.HOME_TAB_QUERY_KEY] || "");
  if (!want) return true;
  return String(route.query?.[layoutStore.HOME_TAB_QUERY_KEY] || "") === want;
}

function goToLocation(target) {
  const to = typeof target === "string" ? { path: target } : (target || {});
  if (sameLocation(to)) return;
  router.push(to).catch(() => null);
}

layoutStore.init({
  navigate: goToLocation,
  logout: async () => {
    appInitialized = false;
    await appStore.logoutNow();
  },
});

dashboardStore.init({
  configRef: config,
  getConfig: () => config.value,
  getLang: () => layoutStore.lang,
  getTab: () => layoutStore.tab,
  getRail: () => layoutStore.rail,
  t,
  notify,
  formatDateMinute: formatDateMinuteByUi,
});


auditStore.init({
  t,
  notify,
  formatDateTime: formatDateTimeByUi,
});

controlStore.init({
  t,
  notify,
  formatDateTime: formatDateTimeByUi,
});

xpStore.init({
  t,
  getLang: () => layoutStore.lang,
});

settingsStore.init({
  t,
  setLang: layoutStore.setLangValue,
});

appStore.init({
  t,
  afterAuthOk: async () => {
    await initializeAppData();
    if (appStore.isRecoveryMode) {
      router.push("/settings/general");
    }
  },
  afterLogout: () => {
    appInitialized = false;
    controlStore.stopControlPolling();
    stopVisualTaskMonitor();
    stopTaskNoticeMonitor();
  },
});

const { initTheme, stopTheme } = useThemeManager(config);

async function initializeAppData() {
  if (appInitialized) return;
  appInitialized = true;
  await Promise.all([
    settingsStore.loadConfigData(),
    controlStore.loadDashboard(),
    resetHomeFeed(),
    settingsStore.loadTranslationStatus(),
    settingsStore.loadModelStatus(),
  ]);
  startVisualTaskMonitor();
  startTaskNoticeMonitor();
  await nextTick();
  bindHomeInfiniteScroll();
}

const settingsPathMap = {
  general: "general",
  data_clean: "data-clean",
  search: "search",
  reader: "reader",
  other: "other",
  local_lib: "local-lib",
  developer: "developer",
};

const pathSettingsMap = {
  general: "general",
  "data-clean": "data_clean",
  search: "search",
  reader: "reader",
  other: "other",
  "local-lib": "local_lib",
  developer: "developer",
};



watch(
  () => layoutStore.tab,
  (next) => {
    onWindowScroll();
    if (String(route.path || "").startsWith("/login")) return;
    if (route.name === "reader") return;
    const target = layoutStore.pathForTab(next);
    const inSettings = String(route.path || "").startsWith("/settings");
    if (!(next === "settings" && inSettings) && !sameLocation(target)) {
      router.push(target).catch(() => null);
    }
  },
);

// The dashboard owns `homeTab` (the rail, the reader's restore path and the URL
// all change it), so mirror it back into the sidebar's target. Without this,
// coming back to the local library after browsing history would land on history
// again.
watch(
  () => dashboardStore.homeTab,
  (next) => layoutStore.setHomeTab(next),
);

watch(
  () => route.path,
  (pathname) => {
    if (String(pathname || "").startsWith("/login")) return;
    if (String(pathname || "").startsWith("/reader")) return;
    const nextTab = layoutStore.routeToTab(pathname || "");
    if (layoutStore.tab !== nextTab) layoutStore.tab = nextTab;
    if (nextTab === "settings") {
      const seg = String(pathname || "").split("/")[2] || "general";
      settingsTab.value = pathSettingsMap[seg] || "general";
    }
  },
  { immediate: true },
);

watch(settingsTab, (next) => {
  if (layoutStore.tab !== "settings") return;
  const seg = settingsPathMap[next] || "general";
  const target = `/settings/${seg}`;
  if (route.path !== target) router.push(target).catch(() => null);
});

onMounted(async () => {
  initTheme();
  try {
    updateViewportFlags();
    onWindowScroll();
    if (typeof window !== "undefined") {
      windowScrollListener = () => onWindowScroll();
      windowResizeListener = () => updateViewportFlags();
      window.addEventListener("scroll", windowScrollListener, { passive: true });
      window.addEventListener("resize", windowResizeListener);
      mainScrollEl = document?.querySelector?.(".v-main") || null;
      if (mainScrollEl) {
        mainScrollEl.addEventListener("scroll", windowScrollListener, { passive: true });
      }
    }
    await appStore.bootstrap();
    if (typeof window !== "undefined") {
      authRequiredListener = () => appStore.onAuthRequiredEvent();
      window.addEventListener("zgl-auth-required", authRequiredListener);
    }
    if (authReady.value && !authGateOpen.value) {
      await initializeAppData();
    }
  } catch (e) {
    notify(String(e), "error");
  }
});

onBeforeUnmount(() => {
  stopTheme();
  controlStore.stopControlPolling();
  stopVisualTaskMonitor();
  stopTaskNoticeMonitor();
  auditStore.stopLogTailPolling();
  xpStore.clearXpTimer();
  clearTouchPreviewTimer();
  clearHomeObserver();
  if (typeof window !== "undefined" && authRequiredListener) {
    window.removeEventListener("zgl-auth-required", authRequiredListener);
    authRequiredListener = null;
  }
  if (typeof window !== "undefined" && windowScrollListener) {
    window.removeEventListener("scroll", windowScrollListener);
    if (mainScrollEl) {
      mainScrollEl.removeEventListener("scroll", windowScrollListener);
      mainScrollEl = null;
    }
    windowScrollListener = null;
  }
  if (typeof window !== "undefined" && windowResizeListener) {
    window.removeEventListener("resize", windowResizeListener);
    windowResizeListener = null;
  }
});
</script>

<style scoped>
:global(.app-toast-snackbar) {
  z-index: 99999 !important;
}
</style>

<style src="./styles/app.css"></style>
