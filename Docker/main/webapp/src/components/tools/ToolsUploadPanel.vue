<template>
  <div>
    <!-- Upload entry point. The user browses to the folder they want, then
         clicks this; the files are staged and the confirm dialog opens. -->
    <div class="d-flex align-center ga-2 flex-wrap mb-3">
      <v-btn
        color="primary"
        variant="flat"
        size="small"
        prepend-icon="mdi-folder-upload-outline"
        :disabled="busy"
        @click="triggerPicker"
      >
        {{ t("tools.upload.pick") }}
      </v-btn>
      <span class="text-caption text-medium-emphasis">{{ t("tools.upload.dest_hint", { path: destLabel }) }}</span>
      <input
        ref="pickerRef"
        type="file"
        webkitdirectory
        directory
        multiple
        class="d-none"
        @change="onPick"
      />
    </div>

    <!-- Confirm dialog: where the files go, and which galleries will be added.
         Names only (no thumbnails); everything selectable is checked by
         default and the user can uncheck, or cancel the whole upload below. -->
    <v-dialog v-model="reviewOpen" max-width="860" persistent scrollable>
      <v-card variant="flat">
        <v-card-title class="text-subtitle-1 font-weight-medium">
          {{ t("tools.upload.review_title") }}
        </v-card-title>
        <v-card-subtitle class="pb-2">
          {{ t("tools.upload.dest_line", { path: destLabel }) }}
        </v-card-subtitle>
        <v-divider />

        <v-card-text style="max-height: 56vh">
          <div class="d-flex align-center justify-space-between mb-2">
            <div class="text-caption text-medium-emphasis">
              {{ t("tools.upload.review_hint", { count: rows.length, selected: selectedCount }) }}
            </div>
            <div class="d-flex ga-1">
              <v-btn size="x-small" variant="text" :disabled="busy" @click="selectAll">{{ t("tools.upload.select_all") }}</v-btn>
              <v-btn size="x-small" variant="text" :disabled="busy" @click="selectNone">{{ t("tools.upload.select_none") }}</v-btn>
            </div>
          </div>

          <v-table density="compact" class="tools-upload-table">
            <thead>
              <tr>
                <th style="width: 44px" />
                <th>{{ t("tools.upload.col_name") }}</th>
                <th style="width: 84px">{{ t("tools.upload.col_pages") }}</th>
                <th style="width: 200px">{{ t("tools.upload.col_progress") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in pagedRows" :key="row.path">
                <td>
                  <v-checkbox-btn
                    :model-value="isChecked(row.path)"
                    :disabled="busy || !row.ingestable || row.over_limit"
                    @update:model-value="toggle(row.path)"
                  />
                </td>
                <td>
                  <div class="text-body-2">{{ row.name }}</div>
                  <div v-if="!row.ingestable || row.over_limit" class="text-caption text-error">
                    {{ row.over_limit ? t("tools.upload.over_limit", { max: maxPages }) : t("tools.upload.not_ingestable") }}
                  </div>
                </td>
                <td>
                  <span class="text-body-2">{{ row.page_count ?? "—" }}</span><span v-if="row.page_count != null" class="text-caption text-medium-emphasis">P</span>
                </td>
                <td>
                  <div v-if="row.state" class="d-flex align-center ga-2">
                    <v-progress-linear
                      :model-value="row.pct"
                      :color="row.state === 'error' ? 'error' : row.state === 'done' ? 'success' : 'primary'"
                      height="6"
                      rounded
                      class="flex-grow-1"
                    />
                    <span class="text-caption text-medium-emphasis tools-upload-pct">
                      {{ row.state === "error" ? t("tools.upload.state_error") : `${row.done}/${row.page_count}P` }}
                    </span>
                  </div>
                  <span v-else class="text-caption text-medium-emphasis">{{ t("tools.upload.state_pending") }}</span>
                </td>
              </tr>
            </tbody>
          </v-table>

          <div class="d-flex align-center justify-space-between mt-2">
            <span class="text-caption text-medium-emphasis">
              {{ t("tools.upload.page_of", { page: page, pages: pageCount }) }} · {{ t("tools.upload.per_page") }}
            </span>
            <v-pagination
              v-if="pageCount > 1"
              v-model="page"
              :length="pageCount"
              density="compact"
              :total-visible="7"
            />
          </div>
        </v-card-text>

        <v-divider />
        <v-card-actions class="flex-wrap ga-2">
          <span v-if="statusText" class="text-caption text-medium-emphasis flex-grow-1">{{ statusText }}</span>
          <v-spacer />
          <v-btn variant="text" color="error" :disabled="busy" @click="cancelAll">
            {{ t("tools.upload.cancel_review") }}
          </v-btn>
          <v-btn
            color="primary"
            variant="flat"
            :loading="busy"
            :disabled="!selectedCount"
            @click="startUpload"
          >
            {{ t("tools.upload.start") }}
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { commitStagedGallery, discardStagedBatch, uploadLocalFolder } from "../../api";
import { describeLocalFiles, uploadChunks } from "../../utils/localUpload";
import { useLayoutStore } from "../../stores/layoutStore";
import { useSettingsStore } from "../../stores/settingsStore";

const props = defineProps({
  // Library-relative directory the user is currently browsing in the file
  // manager. Uploads land here; "" means the library root.
  targetPath: { type: String, default: "" },
});

const emit = defineEmits(["uploaded"]);

const layoutStore = useLayoutStore();
const settingsStore = useSettingsStore();

// Fixed at 50 rows per page -- deliberately not infinite-scrolling, matching
// the rest of the file manager's list behaviour.
const PAGE_SIZE = 50;

const pickerRef = ref(null);
const reviewOpen = ref(false);
const busy = ref(false);
const statusText = ref("");
const batchId = ref("");
const rows = ref([]);
const checkedPaths = ref([]);
const maxPages = ref(10000);
const page = ref(1);

function t(key, vars = {}) {
  return layoutStore.t(key, vars);
}

function notify(msg, color = "success") {
  settingsStore.notify(String(msg || ""), color);
}

const destLabel = computed(() => (props.targetPath ? `/${props.targetPath}` : "/"));
const pageCount = computed(() => Math.max(1, Math.ceil(rows.value.length / PAGE_SIZE)));
const pagedRows = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE;
  return rows.value.slice(start, start + PAGE_SIZE);
});
const checked = computed(() => new Set(checkedPaths.value));
const selectedCount = computed(() => checkedPaths.value.length);

function isChecked(path) {
  return checked.value.has(path);
}

function triggerPicker() {
  if (busy.value) return;
  pickerRef.value?.click?.();
}

function onPick(event) {
  const files = Array.from(event?.target?.files || []);
  if (!files.length) return;
  stageFiles(files)
    .catch((e) => notify(friendlyError(e), "warning"))
    .finally(() => {
      if (event?.target) event.target.value = "";
    });
}

/**
 * Build the review list from browser File metadata without uploading content.
 */
async function stageFiles(files) {
  if (busy.value) return;
  busy.value = true;
  statusText.value = t("tools.upload.staging");
  rows.value = [];
  checkedPaths.value = [];
  batchId.value = "";
  page.value = 1;
  reviewOpen.value = true;
  try {
    rows.value = describeLocalFiles(files);
    // Everything usable is selected by default; the user unchecks what they do
    // not want.
    checkedPaths.value = rows.value.filter((r) => r.ingestable && !r.over_limit).map((r) => r.path);
    statusText.value = rows.value.length
      ? t("tools.upload.detected", { count: rows.value.length })
      : t("tools.upload.detected_none");
  } catch (e) {
    reviewOpen.value = false;
    throw e;
  } finally {
    busy.value = false;
  }
}

function toggle(path) {
  const set = new Set(checkedPaths.value);
  if (set.has(path)) set.delete(path);
  else set.add(path);
  checkedPaths.value = Array.from(set);
}

function selectAll() {
  checkedPaths.value = rows.value.filter((r) => r.ingestable && !r.over_limit).map((r) => r.path);
}

function selectNone() {
  checkedPaths.value = [];
}

/**
 * Import one gallery per request, computing progress as it goes.
 *
 * Sequential by design: the backend moves and ingests exactly one gallery per
 * call, so the page budget is per gallery instead of per upload. A mother
 * folder whose galleries together exceed the old 1000-page request budget now
 * imports fine, one volume at a time, and one oversized volume fails alone
 * instead of poisoning its siblings.
 */
async function startUpload() {
  if (busy.value) return;
  const targets = rows.value.filter((r) => checkedPaths.value.includes(r.path));
  if (!targets.length) return;
  busy.value = true;
  let done = 0;
  let failed = 0;
  try {
    for (const target of targets) {
      setRow(target.path, { state: "running", done: 0, pct: 0 });
      statusText.value = t("tools.upload.importing", { name: target.name });
      try {
        let uploaded = 0;
        for (const chunk of uploadChunks(target.files)) {
          const staged = await uploadLocalFolder(
            chunk.map(e => e.file), chunk.map(e => e.path), target.path.split("/")[0],
            { batchId: batchId.value, inspect: false },
          );
          batchId.value = String(staged.batch_id);
          uploaded += chunk.length;
          setRow(target.path, { pct: Math.round(uploaded / target.files.length * 90) });
        }
        const res = await commitStagedGallery({
          batch_id: batchId.value,
          path: target.path,
          name: target.name,
          kind: target.kind,
          target_path: String(props.targetPath || ""),
        });
        const pages = Math.max(Number(res?.pages) || target.page_count, 0);
        target.page_count = pages || target.page_count;
        setRow(target.path, { state: "done", done: pages, pct: 100 });
        done += 1;
      } catch (e) {
        setRow(target.path, { state: "error", done: 0, pct: 100 });
        failed += 1;
        notify(friendlyError(e), "warning");
      }
    }
  } finally {
    if (batchId.value) {
      try { await discardStagedBatch(batchId.value); }
      catch (e) { notify(friendlyError(e), "warning"); }
    }
    busy.value = false;
  }
  reviewOpen.value = false;
  rows.value = [];
  checkedPaths.value = [];
  batchId.value = "";
  statusText.value = "";
  emit("uploaded");
  notify(t("tools.upload.import_summary", { done, failed }), failed > 0 ? "warning" : "success");
}

function setRow(path, patch) {
  const idx = rows.value.findIndex((r) => r.path === path);
  if (idx < 0) return;
  rows.value[idx] = { ...rows.value[idx], ...patch };
}

/** Abort the whole batch: drop the staging directory, import nothing. */
async function cancelAll() {
  if (busy.value) return;
  const id = batchId.value;
  reviewOpen.value = false;
  rows.value = [];
  checkedPaths.value = [];
  batchId.value = "";
  statusText.value = "";
  page.value = 1;
  if (id) {
    try {
      await discardStagedBatch(id);
    } catch {
      // The staging dir is transient; a failed cleanup is not worth a toast.
    }
  }
}

/**
 * Turn an upload failure into something actionable.
 *
 * `net::ERR_ACCESS_DENIED` / `ERR_FAILED` with no HTTP response is the
 * browser's network layer refusing the request (cross-origin / private-network
 * access), not an application error; axios reports it with no `response`, so a
 * bare `String(e)` would hide the cause behind "Network Error".
 */
function friendlyError(e) {
  const detail = e?.response?.data?.detail;
  if (detail) {
    return String(typeof detail === "object" ? detail.message || JSON.stringify(detail) : detail);
  }
  if (e?.response?.status === 413) return t("tools.upload.error_over_limit");
  if (e?.request && !e?.response) return t("tools.upload.error_network");
  return String(e?.message || e);
}

defineExpose({ stageFiles });
</script>

<style scoped>
.tools-upload-table :deep(td),
.tools-upload-table :deep(th) {
  white-space: nowrap;
}
.tools-upload-pct {
  min-width: 56px;
  text-align: right;
}
</style>
