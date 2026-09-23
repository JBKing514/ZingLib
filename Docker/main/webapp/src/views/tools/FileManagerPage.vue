<template>
  <v-card class="pa-4" variant="flat">
    <div class="d-flex align-center justify-space-between flex-wrap ga-2 mb-3">
      <div class="text-subtitle-1 font-weight-medium">{{ t("tools.file_manager.title") }}</div>
      <div class="d-flex ga-2 flex-wrap">
        <v-btn size="small" variant="tonal" prepend-icon="mdi-refresh" @click="loadList()">{{ t("common.refresh") }}</v-btn>
        <v-btn size="small" variant="tonal" prepend-icon="mdi-folder-plus-outline" @click="mkdirDialog = true">{{ t("tools.file_manager.new_folder") }}</v-btn>
        <v-btn size="small" color="primary" :disabled="!selectedArcids.length" prepend-icon="mdi-file-move-outline" @click="openMoveDialog">{{ t("tools.file_manager.move") }} {{ selectedArcids.length ? `(${selectedArcids.length})` : '' }}</v-btn>
        <v-btn size="small" color="error" variant="tonal" :disabled="!selectedArcids.length && !selectedFolderPaths.length" prepend-icon="mdi-delete-outline" @click="openBulkDeleteDialog">{{ t("common.delete") }} {{ totalSelected ? `(${totalSelected})` : '' }}</v-btn>
      </div>
    </div>

    <!-- Upload lives here now: the user navigates to the folder they want and
         uploads into it. The panel stages the picked tree, opens a confirm
         dialog listing the destination and the detected galleries, then imports
         one gallery at a time. -->
    <ToolsUploadPanel :target-path="currentPath" class="mb-3" @uploaded="loadList()" />

    <div class="d-flex align-center ga-1 flex-wrap mb-3 text-caption text-medium-emphasis">
      <template v-for="(bc, idx) in breadcrumbs" :key="`bc-${bc.path}`">
        <v-btn size="x-small" variant="text" @click="openFolder(bc.path)">{{ bc.name }}</v-btn>
        <span v-if="idx < breadcrumbs.length - 1">/</span>
      </template>
    </div>

    <v-alert v-if="errorText" type="warning" variant="tonal" density="compact" class="mb-3">{{ errorText }}</v-alert>

    <v-progress-linear v-if="loading" indeterminate color="primary" class="mb-3" />

    <div class="d-flex align-center justify-space-between mb-1 mt-1">
      <div class="text-caption text-medium-emphasis d-flex flex-wrap ga-3" aria-live="polite">
        <span>{{ t("tools.file_manager.folder_count", { count: folderGalleryCount ?? '-' }) }}</span>
        <span>{{ t("tools.file_manager.library_count", { count: libraryGalleryCount ?? '-' }) }}</span>
      </div>
      <div class="d-flex align-center ga-1">
        <v-checkbox-btn
          :model-value="allSelected"
          :indeterminate="someSelected"
          @update:model-value="toggleSelectAll"
        />
        <span class="text-caption text-medium-emphasis">{{ t("tools.file_manager.select_all") }}</span>
      </div>
    </div>

    <v-list lines="two" class="bg-transparent">
      <v-list-item
        v-for="f in folders"
        :key="`fd-${f.path}`"
        :title="f.name"
        :subtitle="f.gallery_count ? `${f.gallery_count} ${t('home.local.folder_galleries')}` : ''"
        @click="openFolder(f.path)"
      >
        <template #prepend>
          <v-checkbox-btn :model-value="selectedFolderSet.has(f.path)" @update:model-value="toggleSelectedFolder(f.path)" @click.stop />
          <v-icon size="20" color="amber">mdi-folder-outline</v-icon>
        </template>
        <template #append>
          <v-btn icon="mdi-delete-outline" size="x-small" color="error" variant="text" @click.stop="confirmDeleteFolder(f.path)" />
        </template>
      </v-list-item>
    </v-list>

    <v-list lines="two" class="bg-transparent">
      <v-list-item
        v-for="g in galleries"
        :key="`gl-${g.arcid}`"
      >
        <template #prepend>
          <v-checkbox-btn :model-value="selectedSet.has(g.arcid)" @update:model-value="toggleSelected(g.arcid)" />
          <img v-if="g.thumb_url" :src="g.thumb_url" alt="cover" class="fm-thumb" loading="lazy" />
          <v-icon v-else size="20">mdi-image-outline</v-icon>
        </template>
        <v-list-item-title>{{ g.title || g.arcid }}</v-list-item-title>
        <v-list-item-subtitle>{{ g.local_dir || '-' }}</v-list-item-subtitle>
        <template #append>
          <v-btn icon="mdi-delete-outline" size="x-small" color="error" variant="text" @click.stop="confirmDeleteGallery(g)" />
        </template>
      </v-list-item>
    </v-list>

    <div v-if="!loading && !folders.length && !galleries.length" class="text-caption text-medium-emphasis py-4 text-center">{{ t("tools.file_manager.empty") }}</div>
  </v-card>

  <v-dialog v-model="mkdirDialog" max-width="420">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t("tools.file_manager.new_folder") }}</div>
      <v-text-field v-model="mkdirName" density="compact" variant="outlined" :label="t('tools.file_manager.folder_name')" @keyup.enter="applyMkdir" />
      <div class="d-flex justify-end ga-2">
        <v-btn variant="text" @click="mkdirDialog = false">{{ t("home.favorite.dialog.cancel") }}</v-btn>
        <v-btn color="primary" @click="applyMkdir">{{ t("tools.file_manager.create") }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <v-dialog v-model="moveDialog" max-width="720">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t("tools.file_manager.move") }}</div>
      <div class="text-caption text-medium-emphasis mb-2">{{ t("tools.file_manager.selected", { count: selectedArcids.length }) }}</div>
      <div class="d-flex align-center ga-1 flex-wrap mb-2 text-caption text-medium-emphasis">
        <template v-for="(bc, idx) in moveBrowseBreadcrumbs" :key="`mvbc-${bc.path}`">
          <v-btn size="x-small" variant="text" @click="loadMoveBrowse(bc.path)">{{ bc.name }}</v-btn>
          <span v-if="idx < moveBrowseBreadcrumbs.length - 1">/</span>
        </template>
      </div>
      <div class="d-flex ga-2 mb-2">
        <v-btn size="x-small" variant="tonal" prepend-icon="mdi-arrow-up" :disabled="!moveBrowsePath" @click="moveBrowseParent">{{ t("tools.file_manager.up") }}</v-btn>
      </div>
      <v-list class="bg-transparent mb-2" density="compact" lines="one">
        <v-list-item v-for="f in moveBrowseFolders" :key="`mfd-${f.path}`" prepend-icon="mdi-folder-outline" :title="f.name" @click="loadMoveBrowse(f.path)" />
      </v-list>
      <div class="text-caption text-medium-emphasis mb-2">{{ t('tools.file_manager.target_path') }}: {{ moveBrowsePath || '/' }}</div>
      <v-radio-group v-model="conflictPolicy" color="primary" hide-details>
        <v-radio :label="t('tools.file_manager.conflict_skip')" value="skip" />
        <v-radio :label="t('tools.file_manager.conflict_rename')" value="auto_rename" />
      </v-radio-group>
      <div class="d-flex justify-end ga-2 mt-2">
        <v-btn variant="text" @click="moveDialog = false">{{ t("home.favorite.dialog.cancel") }}</v-btn>
        <v-btn color="primary" :loading="moving" :disabled="!selectedArcids.length" @click="applyMove">{{ t("tools.file_manager.move") }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <v-dialog v-model="moveReportOpen" max-width="760">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t("tools.file_manager.move_report") }}</div>
      <div class="text-caption mb-3">{{ t("tools.file_manager.move_report_stat", { done: moveReport.done || 0, failed: moveReport.failed || 0 }) }}</div>
      <v-list density="compact" class="bg-transparent">
        <v-list-item v-for="r in moveReport.rows || []" :key="`mv-${r.arcid}-${r.target_path || ''}`">
          <v-list-item-title>{{ r.arcid }}</v-list-item-title>
          <v-list-item-subtitle>{{ r.ok ? `OK -> ${r.target_path}` : `FAIL: ${r.reason}` }}</v-list-item-subtitle>
        </v-list-item>
      </v-list>
      <div class="d-flex justify-end mt-2">
        <v-btn color="primary" @click="moveReportOpen = false">{{ t("home.favorite.dialog.confirm") }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <v-dialog v-model="deleteGalleryDialog" max-width="560">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('home.local.delete.title') }}</div>
      <div class="text-body-2 mb-2">{{ t('home.local.delete.hint') }}</div>
      <v-switch v-model="deleteDialogDeleteFiles" color="error" inset hide-details :label="t('home.local.delete.files')" class="mb-2" />
      <v-switch v-model="deleteDialogDeleteDb" color="warning" inset hide-details :label="t('home.local.delete.db')" class="mb-2" />
      <v-switch v-model="deleteDialogDeleteReadEvents" color="error" inset hide-details :label="t('home.local.delete.events')" class="mb-2" />
      <v-alert v-if="deleteDialogDeleteReadEvents" type="error" variant="tonal" density="compact" class="mb-2">{{ t('home.local.delete.events_warn') }}</v-alert>
      <v-checkbox v-if="deleteDialogDeleteReadEvents" v-model="deleteDialogDangerConfirmed" density="compact" hide-details :label="t('home.local.delete.events_confirm')" />
      <div class="d-flex justify-end ga-2 mt-3">
        <v-btn variant="text" @click="deleteGalleryDialog = false">{{ t('home.favorite.dialog.cancel') }}</v-btn>
        <v-btn color="error" variant="flat" :disabled="deleteDialogDeleteReadEvents && !deleteDialogDangerConfirmed" @click="applyDeleteGallery">{{ t('common.delete') }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <v-dialog v-model="deleteFolderDialog" max-width="480">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('common.delete') }}</div>
      <div class="text-body-2 mb-3">{{ t('tools.file_manager.delete_folder_confirm', { path: deleteFolderPath || '/' }) }}</div>
      <div class="d-flex justify-end ga-2">
        <v-btn variant="text" @click="deleteFolderDialog = false">{{ t('home.favorite.dialog.cancel') }}</v-btn>
        <v-btn color="error" variant="flat" @click="applyDeleteFolder">{{ t('common.delete') }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <v-dialog v-model="bulkDeleteDialog" max-width="560">
    <v-card class="pa-4" variant="flat">
      <div class="text-subtitle-1 font-weight-medium mb-2">{{ t('tools.file_manager.bulk_delete_title') }}</div>
      <div class="text-caption text-medium-emphasis mb-2">{{ t('tools.file_manager.bulk_delete_selected', { folders: selectedFolderPaths.length, galleries: selectedArcids.length }) }}</div>
      <div v-if="selectedArcids.length" class="mb-2">
        <v-switch v-model="deleteDialogDeleteFiles" color="error" inset hide-details :label="t('home.local.delete.files')" class="mb-2" />
        <v-switch v-model="deleteDialogDeleteDb" color="warning" inset hide-details :label="t('home.local.delete.db')" class="mb-2" />
        <v-switch v-model="deleteDialogDeleteReadEvents" color="error" inset hide-details :label="t('home.local.delete.events')" class="mb-2" />
        <v-alert v-if="deleteDialogDeleteReadEvents" type="error" variant="tonal" density="compact" class="mb-2">{{ t('home.local.delete.events_warn') }}</v-alert>
        <v-checkbox v-if="deleteDialogDeleteReadEvents" v-model="deleteDialogDangerConfirmed" density="compact" hide-details :label="t('home.local.delete.events_confirm')" />
      </div>
      <div class="d-flex justify-end ga-2 mt-3">
        <v-btn variant="text" @click="bulkDeleteDialog = false">{{ t('home.favorite.dialog.cancel') }}</v-btn>
        <v-btn color="error" variant="flat" :disabled="deleteDialogDeleteReadEvents && !deleteDialogDangerConfirmed" @click="applyBulkDelete">{{ t('common.delete') }}</v-btn>
      </div>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { createLocalFolder, deleteLocalFolder, deleteLocalGallery, getLocalFolderList, moveLocalFolders } from "../../api";
import ToolsUploadPanel from "../../components/tools/ToolsUploadPanel.vue";
import { useSettingsStore } from "../../stores/settingsStore";
import { useLayoutStore } from "../../stores/layoutStore";

const settingsStore = useSettingsStore();
const layoutStore = useLayoutStore();
const loading = ref(false);
const errorText = ref("");
const currentPath = ref("");
const breadcrumbs = ref([{ name: "local_lib", path: "" }]);
const folders = ref([]);
const galleries = ref([]);
const folderGalleryCount = ref(null);
const libraryGalleryCount = ref(null);
const selectedArcids = ref([]);
const selectedFolderPaths = ref([]);
const mkdirDialog = ref(false);
const mkdirName = ref("");
const moveDialog = ref(false);
const moveBrowsePath = ref("");
const moveBrowseBreadcrumbs = ref([{ name: "local_lib", path: "" }]);
const moveBrowseFolders = ref([]);
const conflictPolicy = ref("skip");
const moving = ref(false);
const moveReportOpen = ref(false);
const moveReport = ref({ done: 0, failed: 0, rows: [] });
const deleteGalleryDialog = ref(false);
const deleteGalleryItem = ref(null);
const deleteDialogDeleteFiles = ref(false);
const deleteDialogDeleteDb = ref(false);
const deleteDialogDeleteReadEvents = ref(false);
const deleteDialogDangerConfirmed = ref(false);
const deleteFolderDialog = ref(false);
const deleteFolderPath = ref("");
const bulkDeleteDialog = ref(false);

const selectedSet = computed(() => new Set((selectedArcids.value || []).map((x) => String(x || "").trim())));
const selectedFolderSet = computed(() => new Set((selectedFolderPaths.value || []).map((x) => String(x || "").trim())));
const totalRows = computed(() => Number((galleries.value || []).length) + Number((folders.value || []).length));
const totalSelected = computed(() => Number(selectedArcids.value.length) + Number(selectedFolderPaths.value.length));
const allSelected = computed(() => totalRows.value > 0 && totalSelected.value === totalRows.value);
const someSelected = computed(() => totalSelected.value > 0 && totalSelected.value < totalRows.value);

function t(key, vars = {}) {
  return layoutStore.t(key, vars);
}

function notify(msg, color = "success") {
  settingsStore.notify(String(msg || ""), color);
}

async function loadList(path = currentPath.value) {
  loading.value = true;
  errorText.value = "";
  try {
    const targetPath = String(path || "");
    const first = await getLocalFolderList({ path: targetPath, limit: 120, lite: 1 });
    folderGalleryCount.value = first?.folder_gallery_count ?? null;
    libraryGalleryCount.value = first?.library_gallery_count ?? null;
    let galleriesAll = Array.isArray(first?.galleries) ? first.galleries : [];
    let cursor = String(first?.next_cursor || "");
    let guard = 0;
    while (cursor && guard < 200) {
      guard += 1;
      const next = await getLocalFolderList({ path: targetPath, cursor, limit: 120, lite: 1 });
      const rows = Array.isArray(next?.galleries) ? next.galleries : [];
      if (!rows.length) break;
      galleriesAll = galleriesAll.concat(rows);
      cursor = String(next?.next_cursor || "");
    }
    currentPath.value = String(first?.path || "");
    breadcrumbs.value = Array.isArray(first?.breadcrumbs) && first.breadcrumbs.length ? first.breadcrumbs : [{ name: "local_lib", path: "" }];
    folders.value = Array.isArray(first?.folders) ? first.folders : [];
    galleries.value = Array.isArray(galleriesAll) ? galleriesAll.map((x) => ({
      arcid: String(x?.arcid || ""),
      title: String(x?.title || ""),
      thumb_url: String(x?.thumb_url || ""),
      local_dir: String(x?.local_dir || ""),
    })) : [];
    const keep = new Set(galleries.value.map((x) => x.arcid));
    selectedArcids.value = (selectedArcids.value || []).filter((x) => keep.has(String(x || "")));
    const keepFolders = new Set(folders.value.map((x) => String(x?.path || "").trim()));
    selectedFolderPaths.value = (selectedFolderPaths.value || []).filter((x) => keepFolders.has(String(x || "").trim()));
  } catch (e) {
    errorText.value = String(e?.response?.data?.detail || e);
  } finally {
    loading.value = false;
  }
}

function openFolder(path = "") {
  loadList(String(path || "")).catch(() => null);
}

function toggleSelected(arcid) {
  const id = String(arcid || "").trim();
  if (!id) return;
  const set = new Set(selectedArcids.value || []);
  if (set.has(id)) set.delete(id);
  else set.add(id);
  selectedArcids.value = Array.from(set);
}

function toggleSelectedFolder(path) {
  const p = String(path || "").trim();
  if (!p) return;
  const set = new Set(selectedFolderPaths.value || []);
  if (set.has(p)) set.delete(p);
  else set.add(p);
  selectedFolderPaths.value = Array.from(set);
}

function toggleSelectAll(v) {
  if (v) {
    selectedArcids.value = (galleries.value || []).map((x) => String(x?.arcid || "").trim()).filter(Boolean);
    selectedFolderPaths.value = (folders.value || []).map((x) => String(x?.path || "").trim()).filter(Boolean);
    return;
  }
  selectedArcids.value = [];
  selectedFolderPaths.value = [];
}

async function applyMkdir() {
  const name = String(mkdirName.value || "").trim();
  if (!name) return;
  try {
    await createLocalFolder({ parent_path: currentPath.value, name });
    mkdirDialog.value = false;
    mkdirName.value = "";
    notify(t("tools.file_manager.created"), "success");
    await loadList();
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  }
}

async function loadMoveBrowse(path = moveBrowsePath.value) {
  const res = await getLocalFolderList({ path: String(path || ""), limit: 1 });
  moveBrowsePath.value = String(res?.path || "");
  moveBrowseBreadcrumbs.value = Array.isArray(res?.breadcrumbs) && res.breadcrumbs.length ? res.breadcrumbs : [{ name: "local_lib", path: "" }];
  moveBrowseFolders.value = Array.isArray(res?.folders) ? res.folders : [];
}

function moveBrowseParent() {
  const cur = String(moveBrowsePath.value || "");
  if (!cur) return;
  const parts = cur.split("/").filter(Boolean);
  parts.pop();
  loadMoveBrowse(parts.join("/")).catch(() => null);
}

function openMoveDialog() {
  conflictPolicy.value = "skip";
  moveDialog.value = true;
  loadMoveBrowse(currentPath.value).catch((e) => {
    notify(String(e?.response?.data?.detail || e), "warning");
  });
}

async function applyMove() {
  if (!selectedArcids.value.length) return;
  moving.value = true;
  try {
    const res = await moveLocalFolders({
      arcids: selectedArcids.value,
      target_path: String(moveBrowsePath.value || ""),
      conflict_policy: String(conflictPolicy.value || "skip"),
    });
    moveDialog.value = false;
    moveReport.value = {
      done: Number(res?.done || 0),
      failed: Number(res?.failed || 0),
      rows: Array.isArray(res?.rows) ? res.rows : [],
    };
    moveReportOpen.value = true;
    notify(t("tools.file_manager.move_done", { done: moveReport.value.done, failed: moveReport.value.failed }), moveReport.value.failed > 0 ? "warning" : "success");
    selectedArcids.value = [];
    selectedFolderPaths.value = [];
    await loadList();
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  } finally {
    moving.value = false;
  }
}

function confirmDeleteGallery(item) {
  deleteGalleryItem.value = item || null;
  deleteDialogDeleteFiles.value = false;
  deleteDialogDeleteDb.value = false;
  deleteDialogDeleteReadEvents.value = false;
  deleteDialogDangerConfirmed.value = false;
  deleteGalleryDialog.value = true;
}

async function applyDeleteGallery() {
  const item = deleteGalleryItem.value;
  deleteGalleryDialog.value = false;
  deleteGalleryItem.value = null;
  const arcid = String(item?.arcid || "").trim();
  if (!arcid) return;
  try {
    await deleteLocalGallery({
      arcid,
      delete_files: !!deleteDialogDeleteFiles.value,
      delete_db: !!deleteDialogDeleteDb.value,
      delete_read_events: !!deleteDialogDeleteReadEvents.value,
    });
    notify(t("common.delete"), "success");
    await loadList();
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  }
}

function confirmDeleteFolder(path) {
  deleteFolderPath.value = String(path || "").trim();
  if (!deleteFolderPath.value) return;
  deleteFolderDialog.value = true;
}

async function applyDeleteFolder() {
  const p = String(deleteFolderPath.value || "").trim();
  deleteFolderDialog.value = false;
  if (!p) return;
  try {
    await deleteLocalFolder({ path: p });
    notify(t("common.delete"), "success");
    selectedFolderPaths.value = (selectedFolderPaths.value || []).filter((x) => String(x || "").trim() !== p);
    await loadList();
  } catch (e) {
    notify(String(e?.response?.data?.detail || e), "warning");
  }
}

function openBulkDeleteDialog() {
  deleteDialogDeleteFiles.value = false;
  deleteDialogDeleteDb.value = false;
  deleteDialogDeleteReadEvents.value = false;
  deleteDialogDangerConfirmed.value = false;
  bulkDeleteDialog.value = true;
}

async function applyBulkDelete() {
  bulkDeleteDialog.value = false;
  const folderList = [...selectedFolderPaths.value];
  const arcidList = [...selectedArcids.value];
  let done = 0;
  let failed = 0;
  for (const p of folderList) {
    try {
      await deleteLocalFolder({ path: String(p || "") });
      done += 1;
    } catch (e) {
      failed += 1;
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }
  for (const arcid of arcidList) {
    try {
      await deleteLocalGallery({
        arcid: String(arcid || ""),
        delete_files: !!deleteDialogDeleteFiles.value,
        delete_db: !!deleteDialogDeleteDb.value,
        delete_read_events: !!deleteDialogDeleteReadEvents.value,
      });
      done += 1;
    } catch (e) {
      failed += 1;
      notify(String(e?.response?.data?.detail || e), "warning");
    }
  }
  selectedArcids.value = [];
  selectedFolderPaths.value = [];
  notify(t("tools.file_manager.bulk_delete_done", { done, failed }), failed > 0 ? "warning" : "success");
  await loadList();
}

onMounted(() => {
  loadList("").catch(() => null);
});
</script>

<style scoped>
.fm-thumb {
  width: 28px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
  border: 1px solid rgba(255, 255, 255, 0.16);
}
</style>
