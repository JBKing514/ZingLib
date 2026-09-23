import axios from "axios";

export async function rebuildGalleryDatabase(password) {
  const { data } = await api.post("/local-lib/rebuild-database", { confirm: true, password }, { timeout: 0 });
  return data;
}

const api = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

let csrfToken = "";

export function setCsrfToken(token) {
  csrfToken = String(token || "");
}

api.interceptors.request.use((config) => {
  const method = String(config?.method || "get").toUpperCase();
  if (csrfToken && ["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const headers = config.headers || {};
    headers["x-csrf-token"] = csrfToken;
    config.headers = headers;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("zgl-auth-required"));
    }
    try {
      const data = error?.response?.data;
      if (data && typeof data === "object") {
        const detailObj = data.detail;
        const detail = String(
          (detailObj && typeof detailObj === "object" && detailObj.message) || detailObj || error?.message || "request failed",
        ).trim();
        const tb = String(
          data.traceback || (detailObj && typeof detailObj === "object" ? detailObj.traceback : "") || "",
        ).trim();
        if (tb) {
          data.detail = `${detail}\n\nTraceback:\n${tb}`;
          error.message = data.detail;
        } else if (detail) {
          error.message = detail;
        }
      }
    } catch {
      // ignore error decoration failures
    }
    return Promise.reject(error);
  },
);

export async function getHealth() {
  const { data } = await api.get("/health", {
    timeout: 8000,
    params: { t: Date.now() },
    headers: { "Cache-Control": "no-cache" },
  });
  return data;
}

export async function getDbHealth() {
  const { data } = await api.get("/health/db", {
    timeout: 8000,
    params: { t: Date.now() },
    headers: { "Cache-Control": "no-cache" },
  });
  return data;
}

export async function getAuthBootstrap() {
  const { data } = await api.get("/auth/bootstrap");
  return data;
}

export async function registerAdmin(username, password) {
  const { data } = await api.post("/auth/register-admin", { username, password });
  return data;
}

export async function login(username, password) {
  const { data } = await api.post("/auth/login", { username, password });
  return data;
}

export async function logout() {
  const { data } = await api.post("/auth/logout");
  return data;
}

export async function getMe() {
  const { data } = await api.get("/auth/me");
  return data;
}

export async function getCsrfToken() {
  const { data } = await api.get("/auth/csrf");
  return data;
}

export async function updateProfile(username) {
  const { data } = await api.put("/auth/profile", { username });
  return data;
}

export async function changePassword(oldPassword, newPassword, username = "") {
  const { data } = await api.put("/auth/password", { old_password: oldPassword, new_password: newPassword, username });
  return data;
}

export async function verifyPassword(username, password) {
  const { data } = await api.post("/auth/verify-password", { username, password });
  return data;
}

export async function deleteAccount(password) {
  const { data } = await api.delete("/auth/account", { data: { password } });
  return data;
}

export async function getSetupStatus() {
  const { data } = await api.get("/setup/status");
  return data;
}

export async function validateSetupDb(payload = {}) {
  const { data } = await api.post("/setup/validate-db", payload);
  return data;
}

export async function completeSetup() {
  const { data } = await api.post("/setup/complete");
  return data;
}

export async function getConfig() {
  const { data } = await api.get("/config");
  return data;
}

export async function updateConfig(values) {
  const { data } = await api.put("/config", { values });
  return data;
}

export async function downloadAppConfigBackup() {
  const res = await api.get("/config/app-config/download", { responseType: "blob" });
  return res.data;
}

export async function restoreAppConfigBackup(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/config/app-config/restore", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function getConfigSchema() {
  const { data } = await api.get("/config/schema");
  return data;
}

export async function getSchedule() {
  const { data } = await api.get("/schedule");
  return data;
}

export async function updateSchedule(schedule) {
  const { data } = await api.put("/schedule", { schedule });
  return data;
}

export async function runTask(task, args = "") {
  const { data } = await api.post("/task/run", { task, args });
  return data;
}

export async function stopTask(taskId) {
  const { data } = await api.post("/task/stop", { task_id: String(taskId || "") });
  return data;
}

export async function clearWorksDuplicates() {
  const { data } = await api.post("/db/works/deduplicate");
  return data;
}

export async function clearReadEvents() {
  const { data } = await api.delete("/db/read-events");
  return data;
}

export async function getTasks() {
  const { data } = await api.get("/tasks");
  return data;
}

export async function getVisualTaskStatus() {
  const { data } = await api.get("/visual-task/status");
  return data;
}

export async function stopVisualTask() {
  const { data } = await api.post("/visual-task/stop");
  return data;
}

export async function enableVisualTask() {
  const { data } = await api.post("/visual-task/enable");
  return data;
}

export async function disableVisualTask() {
  const { data } = await api.post("/visual-task/disable");
  return data;
}

export async function getAuditHistory(params = {}) {
  const { data } = await api.get("/audit/history", {
    params: {
      limit: 15,
      offset: 0,
      task: "",
      status: "",
      keyword: "",
      ...params,
    },
  });
  return data;
}

export async function getAuditLogs() {
  const { data } = await api.get("/audit/logs");
  return data;
}

export async function clearAuditLogs() {
  const { data } = await api.delete("/audit/logs");
  return data;
}

export async function getAuditTasks() {
  const { data } = await api.get("/audit/tasks");
  return data;
}

export async function getAuditLogContent(name) {
  const { data } = await api.get(`/audit/logs/${encodeURIComponent(name)}`);
  return data;
}

export async function getAuditLogTail(name, offset = 0, chunkSize = 8000) {
  const { data } = await api.get(`/audit/logs/${encodeURIComponent(name)}/tail`, {
    params: { offset, chunk_size: chunkSize },
  });
  return data;
}

export async function getXpMap(params) {
  const { data } = await api.get("/xp-map", { params });
  return data;
}

export async function getHomeHistory(params = {}) {
  const { data } = await api.get("/home/history", { params });
  return data;
}

export async function getHomeLocal(params = {}) {
  const { data } = await api.get("/home/local", { params });
  return data;
}

export async function getHomeFavorite(params = {}) {
  const { data } = await api.get("/home/favorite", { params });
  return data;
}

export async function postHomeFavoriteToggle(payload = {}) {
  const { data } = await api.post("/home/favorite/toggle", payload || {});
  return data;
}

export async function postHomeRatingSet(payload = {}) {
  const { data } = await api.post("/home/rating/set", payload || {});
  return data;
}

export async function searchByImage(payload = {}) {
  const { data } = await api.post("/home/search/image", payload);
  return data;
}

export async function searchByImageUpload(file, payload = {}) {
  const form = new FormData();
  form.append("file", file);
  Object.entries(payload || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null) form.append(k, String(v));
  });
  const { data } = await api.post("/home/search/image/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function getHomeTagSuggest(params = {}) {
  const { data } = await api.get("/home/filter/tag-suggest", { params });
  return data;
}

export async function getReaderManifest(arcid) {
  const { data } = await api.get(`/reader/${encodeURIComponent(String(arcid || ""))}/manifest`);
  return data;
}

// "Guess you like" candidates for the reader's end screen: cover-vector cosine
// plus tag overlap against the gallery being read.
export async function getReaderSimilar(arcid, limit = 6) {
  const { data } = await api.get(`/reader/${encodeURIComponent(String(arcid || ""))}/similar`, {
    params: { limit: Number(limit) || 6 },
  });
  return data;
}

export async function openReaderSession(arcid, params = {}) {
  const { data } = await api.post(`/reader/${encodeURIComponent(String(arcid || ""))}/session`, null, { params });
  return data;
}

export async function updateReaderSessionCursor(sessionId, params = {}) {
  const { data } = await api.post(`/reader/session/${encodeURIComponent(String(sessionId || ""))}/cursor`, null, { params });
  return data;
}

export async function getReaderSessionStatus(sessionId) {
  const { data } = await api.get(`/reader/session/${encodeURIComponent(String(sessionId || ""))}/status`);
  return data;
}

export async function closeReaderSession(sessionId) {
  const { data } = await api.delete(`/reader/session/${encodeURIComponent(String(sessionId || ""))}`);
  return data;
}

export async function postReaderReadEvent(payload = {}) {
  const { data } = await api.post("/reader/read-event", payload || {});
  return data;
}

export async function postReaderBookmarkSet(params = {}) {
  const { data } = await api.post("/reader/bookmark/set", null, { params: params || {} });
  return data;
}

export async function triggerLocalLibScan(payload = {}) {
  const { data } = await api.post("/local-lib/scan", payload || {});
  return data;
}

export async function uploadLocalFolder(files = [], relativePaths = [], folderName = "", options = {}) {
  const form = new FormData();
  for (const f of files || []) {
    form.append("files", f);
  }
  for (const rel of relativePaths || []) {
    form.append("relative_paths", String(rel || ""));
  }
  form.append("folder_name", String(folderName || ""));
  form.append("batch_id", options.batchId || "");
  form.append("inspect", options.inspect === false ? "false" : "true");
  // No client-side file ceiling and no short timeout: this stages the tree on
  // disk now and the backend reports the galleries it found, so the request size
  // is bounded by the folder the user picked rather than an arbitrary limit.
  const { data } = await api.post("/local-lib/upload-folder", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 0,
  });
  return data;
}

export async function getStagedGalleries(batchId, subPath = "", namesOnly = false) {
  const params = { batch_id: String(batchId || ""), sub_path: String(subPath || "") };
  if (namesOnly) params.names_only = 1;
  const { data } = await api.get("/local-lib/upload/staged", { params });
  return data;
}

export async function commitStagedGallery(payload = {}) {
  const { data } = await api.post("/local-lib/upload/commit", payload || {}, { timeout: 0 });
  return data;
}

export async function discardStagedBatch(batchId) {
  const { data } = await api.post("/local-lib/upload/discard", { batch_id: String(batchId || "") });
  return data;
}

/**
 * Absolute-path URL for one staged gallery's first-page thumbnail.
 *
 * A plain <img src> cannot carry the CSRF header, and the endpoint is a GET
 * behind `auth_guard`, so the session cookie alone authorises it.
 */
export function stagedGalleryThumbUrl(batchId, path, preset = "") {
  const params = new URLSearchParams({
    batch_id: String(batchId || ""),
    path: String(path || ""),
  });
  if (preset) params.set("preset", String(preset));
  return `/api/local-lib/upload/thumb?${params.toString()}`;
}

export async function getLocalMetadataGaps(params = {}) {
  const { data } = await api.get("/local-lib/metadata-gaps", { params });
  return data;
}

export async function refetchLocalMetadata(payload = {}) {
  const { data } = await api.post("/local-lib/metadata/refetch", payload || {});
  return data;
}

// Replays the per-gallery sidecars (`.zinglib_meta/<arcid>_zinglib_metadata.json`)
// back into the database. `{ dry_run: true }` only answers what would happen, so
// the caller can show the plan before it writes anything.
export async function restoreLocalMetadata(payload = {}) {
  const { data } = await api.post("/local-lib/metadata/restore", payload || {}, { timeout: 0 });
  return data;
}

export async function downloadLocalMetadataRestoreLog(logId) {
  const safe = String(logId || "").trim();
  const res = await api.get(`/local-lib/metadata/restore-log/${encodeURIComponent(safe)}`, { responseType: "blob" });
  return res.data;
}

export async function getLocalFlattenGaps(params = {}) {
  const { data } = await api.get("/local-lib/flatten-gaps", { params });
  return data;
}

export async function runLocalFlatten(payload = {}) {
  const { data } = await api.post("/local-lib/flatten", payload || {});
  return data;
}

export async function deleteLocalGallery(payload = {}) {
  const { data } = await api.post("/local-lib/delete", payload || {});
  return data;
}

export async function getLocalFolderList(params = {}) {
  const { data } = await api.get("/local-lib/folder/list", { params });
  return data;
}

export async function createLocalFolder(payload = {}) {
  const { data } = await api.post("/local-lib/folder/mkdir", payload || {});
  return data;
}

export async function moveLocalFolders(payload = {}) {
  const { data } = await api.post("/local-lib/folder/move", payload || {});
  return data;
}

export async function deleteLocalFolder(payload = {}) {
  const { data } = await api.post("/local-lib/folder/delete", payload || {});
  return data;
}

export async function clearLocalThumbCache() {
  const { data } = await api.delete("/local-lib/thumb-cache");
  return data;
}

export async function getLocalMetaList(params = {}) {
  const { data } = await api.get("/local-lib/meta/list", { params });
  return data;
}

export async function getLocalTagNamespaceSuggest(params = {}) {
  const { data } = await api.get("/local-lib/tag-namespaces/suggest", { params });
  return data;
}

export async function previewLocalMetaBatchUpdate(payload = {}) {
  const { data } = await api.post("/local-lib/meta/preview", payload || {});
  return data;
}

export async function batchUpdateLocalMeta(payload = {}) {
  const { data } = await api.post("/local-lib/meta/batch-update", payload || {});
  return data;
}

export async function searchByTextPlaceholder(payload = {}) {
  const { data } = await api.post("/home/search/text", payload);
  return data;
}

export async function searchByText(payload = {}) {
  const { data } = await api.post("/home/search/text", payload);
  return data;
}

export async function searchHybridPlaceholder(payload = {}) {
  const { data } = await api.post("/home/search/hybrid", payload);
  return data;
}

export async function searchHybrid(payload = {}) {
  const { data } = await api.post("/home/search/hybrid", payload);
  return data;
}

export async function getThumbCacheStats() {
  const { data } = await api.get("/cache/thumbs");
  return data;
}

export async function clearThumbCache() {
  const { data } = await api.delete("/cache/thumbs");
  return data;
}

export async function getThumbRuntimeStats() {
  const { data } = await api.get("/thumb/runtime-stats");
  return data;
}

export async function getTranslationStatus() {
  const { data } = await api.get("/translation/status");
  return data;
}

export async function uploadTranslationFile(file) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/translation/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 120000,
  });
  return data;
}

export async function clearTranslationTableFile() {
  const { data } = await api.delete("/translation/table");
  return data;
}

export async function getTagReapplyStatus(mode = "") {
  const { data } = await api.get("/local-lib/tags/reapply/status", {
    params: mode ? { mode } : {},
  });
  return data;
}

export async function startTagReapply(payload = {}) {
  const { data } = await api.post("/local-lib/tags/reapply", payload || {});
  return data;
}

export async function cancelTagReapply() {
  const { data } = await api.post("/local-lib/tags/reapply/cancel", {});
  return data;
}

export async function getModelStatus() {
  const { data } = await api.get("/models/status");
  return data;
}

export async function downloadSiglip(params = {}) {
  const { data } = await api.post("/models/siglip/download", null, { params });
  return data;
}

export async function getSiglipDownloadStatus(taskId) {
  const { data } = await api.get(`/models/siglip/download/${encodeURIComponent(taskId)}`);
  return data;
}

export async function clearSiglip() {
  const { data } = await api.delete("/models/siglip");
  return data;
}

export async function clearRuntimeDeps() {
  const { data } = await api.delete("/models/runtime-deps");
  return data;
}

export async function getProviderModels(baseUrl, apiKey = "") {
  const { data } = await api.post("/provider/models", { base_url: baseUrl || "", api_key: apiKey || "" });
  return data;
}
