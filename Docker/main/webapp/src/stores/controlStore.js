import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { getHealth, getSchedule, getTasks, runTask, updateSchedule } from "../api";

export const useControlStore = defineStore("control", () => {
  const health = ref({ database: {} });
  const healthLoading = ref(false);
  const schedule = ref({});
  const scheduleVisible = computed(() => {
    const src = schedule.value || {};
    return Object.entries(src)
      .map(([key, item]) => ({ key, item }));
  });
  const tasks = ref([]);

  let _t = (k) => k;
  let _notify = () => {};
  let _formatDateTime = (v) => String(v || "-");
  let dashboardTimer = null;
  let tasksEventSource = null;
  let pollingGeneration = 0;
  const taskStatusSeen = new Map();

  function init(deps = {}) {
    if (typeof deps.t === "function") _t = deps.t;
    if (typeof deps.notify === "function") _notify = deps.notify;
    if (typeof deps.formatDateTime === "function") _formatDateTime = deps.formatDateTime;
  }

  function t(key, vars = {}) {
    return _t(key, vars);
  }

  function formatDateTime(value) {
    return _formatDateTime(value);
  }

  function formatDateMinute(value) {
    if (!value || value === "-") return "-";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value).slice(0, 16).replace("T", " ");
    return d.toLocaleString(undefined, {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function short(id) {
    return id ? String(id).slice(0, 8) : "-";
  }

  function schedulerLabel(key) {
    return t(`scheduler.${key}`);
  }

  function statusColor(status) {
    if (status === "running") return "warning";
    if (status === "stopping") return "warning";
    if (status === "stopped") return "info";
    if (status === "success") return "success";
    return "error";
  }

  function statusText(status) {
    if (status === "running") return t("task.running");
    if (status === "stopping") return t("task.stopping");
    if (status === "stopped") return t("task.stopped");
    if (status === "success") return t("task.success");
    if (status === "timeout") return t("task.timeout");
    return t("task.failed");
  }

  async function loadDashboard() {
    healthLoading.value = true;
    try {
      health.value = await getHealth();
    } catch (e) {
      // Only the database branch is rendered (ControlPage shows
      // `health.database.error`), so an unreachable API is reported there rather
      // than on a `services.llm` slot nothing draws.
      const reason = String(e?.response?.data?.detail || e?.message || e || "unreachable");
      health.value = {
        ...(health.value || {}),
        database: {
          ...(health.value?.database || {}),
          ok: false,
          error: reason,
        },
      };
    } finally {
      healthLoading.value = false;
    }
  }

  async function loadScheduleData() {
    const data = await getSchedule();
    schedule.value = data.schedule || {};
  }

  async function saveSchedule() {
    await updateSchedule(schedule.value);
    _notify(t("control.scheduler.saved"));
  }

  async function triggerTask(task, args = "") {
    await runTask(task, args);
    _notify(`${t("task.start")}: ${task}`);
  }

  async function loadTasks() {
    const data = await getTasks();
    tasks.value = data.tasks || [];
  }

  async function setupTaskStream() {
    if (tasksEventSource) tasksEventSource.close();
    tasksEventSource = new EventSource("/api/tasks/stream");
    tasksEventSource.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data || "{}");
        const next = (payload.tasks || []).sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || ""))).slice(0, 200);
        tasks.value = next;
        next.forEach((task) => {
          const id = String(task?.task_id || "");
          if (!id) return;
          const status = String(task?.status || "");
          const prev = taskStatusSeen.get(id) || "";
          if (prev !== status && (status === "failed" || status === "timeout")) {
            const hint = String(task?.hint || "").trim();
            const summary = String(task?.task_summary || task?.error || "").trim();
            _notify(`${t("task.failed")} ${task?.task || ""}${hint ? `\n${hint}` : ""}${summary ? `\n${summary}` : ""}`, "warning");
          }
          taskStatusSeen.set(id, status);
        });
      } catch {
        // ignore
      }
    };
  }

  function closeTaskStream() {
    if (tasksEventSource) {
      tasksEventSource.close();
      tasksEventSource = null;
    }
  }

  async function startControlPolling() {
    const generation = ++pollingGeneration;
    await Promise.all([loadDashboard(), loadScheduleData(), loadTasks()]);
    if (generation !== pollingGeneration) return;
    setupTaskStream();
    if (dashboardTimer) clearInterval(dashboardTimer);
    dashboardTimer = setInterval(() => {
      loadDashboard().catch(() => null);
    }, 10000);
  }

  function stopControlPolling() {
    pollingGeneration += 1;
    if (dashboardTimer) {
      clearInterval(dashboardTimer);
      dashboardTimer = null;
    }
    closeTaskStream();
  }

  return {
    health,
    healthLoading,
    schedule,
    scheduleVisible,
    tasks,
    init,
    t,
    formatDateTime,
    formatDateMinute,
    short,
    schedulerLabel,
    statusColor,
    statusText,
    loadDashboard,
    loadScheduleData,
    saveSchedule,
    triggerTask,
    loadTasks,
    setupTaskStream,
    closeTaskStream,
    startControlPolling,
    stopControlPolling,
  };
});
