<template>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-2">{{ t("settings.local_lib.title") }}</div>
    <div class="text-body-2 text-medium-emphasis mb-3">{{ t("settings.local_lib.hint_local") }}</div>
    <div class="d-flex ga-2 flex-wrap">
      <v-btn color="primary" :loading="scanning" prepend-icon="mdi-refresh" @click="scanNow">{{ t("settings.local_lib.scan") }}</v-btn>
      <v-btn color="secondary" variant="tonal" prepend-icon="mdi-restore" @click="reloadAll">{{ t("settings.local_lib.reload") }}</v-btn>
      <v-btn color="warning" variant="tonal" :loading="clearingThumbCache" prepend-icon="mdi-image-off-outline" @click="clearLocalThumbCacheNow">{{ t("settings.local_lib.clear_thumb_cache") }}</v-btn>
    </div>
    <!-- Housekeeping that belongs with the library itself (not with the vector
         ingest settings it used to be stranded in): both act on the live
         database, and both are irreversible, so they keep a confirmation. -->
    <v-divider class="my-3" />
    <div class="text-subtitle-2 font-weight-medium mb-2">{{ t("settings.local_lib.maintenance.title") }}</div>
    <div class="text-body-2 text-medium-emphasis mb-3">{{ t("settings.local_lib.maintenance.hint") }}</div>
    <div class="d-flex ga-2 flex-wrap">
      <v-btn color="warning" variant="tonal" prepend-icon="mdi-content-duplicate" @click="clearWorksDuplicatesAction">{{ t("settings.data_clean.dedup_works") }}</v-btn>
      <v-btn color="warning" variant="tonal" prepend-icon="mdi-history" @click="openReadEventsConfirm">{{ t("settings.data_clean.clear_read_events") }}</v-btn>
      <!-- Rebuilding the gallery database asks for the administrator password, so
           it belongs with the other housekeeping that acts on the live database
           rather than in the danger zone, which is now only the connection. -->
      <v-btn color="error" variant="tonal" prepend-icon="mdi-database-refresh-outline" :disabled="isRecoveryMode" @click="openRebuildDialog">{{ t("settings.rebuild.title") }}</v-btn>
    </div>
    <v-row class="mt-2">
      <v-col cols="12" md="6">
        <div class="d-flex align-center ga-2 flex-wrap">
          <v-switch
            v-model="showJpnTitle"
            color="primary"
            inset
            :loading="savingDisplayPrefs"
            hide-details
            :label="t('settings.local_lib.show_jpn_title')"
            @update:model-value="onShowJpnTitleToggle"
          />
          <v-chip size="x-small" variant="tonal" color="info">{{ t("settings.local_lib.comicinfo_badge") }}</v-chip>
        </div>
        <div class="text-caption text-medium-emphasis ms-1">{{ t("settings.local_lib.show_jpn_title_hint") }}</div>
      </v-col>
      <v-col cols="12" md="6">
        <div class="d-flex align-center ga-2 flex-wrap">
          <v-switch
            v-model="useTranslatedTags"
            color="primary"
            inset
            :loading="savingDisplayPrefs"
            hide-details
            :label="t('settings.local_lib.use_translated_tags')"
            @update:model-value="onUseTranslatedTagsToggle"
          />
          <v-tooltip location="top" max-width="360">
            <template #activator="{ props: tipProps }">
              <v-icon v-bind="tipProps" icon="mdi-help-circle-outline" size="18" class="text-medium-emphasis reapply-help-icon" />
            </template>
            <span>{{ t("settings.local_lib.reapply.tip") }}</span>
          </v-tooltip>
          <v-chip size="x-small" variant="tonal" color="info">{{ t("settings.local_lib.comicinfo_badge") }}</v-chip>
        </div>
        <div class="text-caption text-medium-emphasis ms-1">{{ t("settings.local_lib.use_translated_tags_hint") }}</div>
      </v-col>
    </v-row>
    <div class="d-flex align-center ga-2 flex-wrap mt-1">
      <v-btn
        size="small"
        color="primary"
        variant="tonal"
        prepend-icon="mdi-tag-check-outline"
        :loading="startingReapply"
        :disabled="reapplyRunning"
        @click="startReapplyNow()"
      >
        {{ t("settings.local_lib.reapply.run") }}
      </v-btn>
      <v-tooltip location="top" max-width="360">
        <template #activator="{ props: tipProps }">
          <v-icon v-bind="tipProps" icon="mdi-help-circle-outline" size="18" class="text-medium-emphasis reapply-help-icon" />
        </template>
        <span>{{ t("settings.local_lib.reapply.tip") }}</span>
      </v-tooltip>
      <v-chip v-if="reapplyRunning" size="small" color="primary" variant="tonal">
        {{ t("settings.local_lib.reapply.running_chip", { done: reapplyProcessed, total: reapplyTotal }) }}
      </v-chip>
      <v-chip v-else-if="reapplyPending > 0" size="small" color="warning" variant="tonal">
        {{ t("settings.local_lib.reapply.pending", { n: reapplyPending }) }}
      </v-chip>
      <v-chip v-else size="small" color="success" variant="tonal">
        {{ t("settings.local_lib.reapply.up_to_date") }}
      </v-chip>
    </div>
    <v-alert
      v-if="!reapplyRunning && reapplySummaryText"
      class="mt-2"
      :type="reapplySummaryType"
      variant="tonal"
      density="comfortable"
    >
      <div class="d-flex align-center justify-space-between ga-3 flex-wrap">
        <div class="text-body-2">{{ reapplySummaryText }}</div>
        <v-btn
          v-if="reapplyPending > 0"
          size="small"
          :color="reapplySummaryType"
          variant="flat"
          :loading="startingReapply"
          @click="startReapplyNow()"
        >
          {{ t("settings.local_lib.reapply.resume_run") }}
        </v-btn>
      </div>
    </v-alert>
    <v-alert v-if="resultText" class="mt-3" type="info" variant="tonal" density="compact">{{ resultText }}</v-alert>
  </v-card>

  <v-card class="pa-4 mb-4" variant="flat">
    <div class="text-subtitle-2 font-weight-medium">{{ t("settings.local_lib.backup.title") }}</div>
    <div class="text-body-2 text-medium-emphasis mb-3">{{ t("settings.local_lib.backup.hint") }}</div>
    <div class="d-flex align-center ga-2 flex-wrap">
      <v-btn
        color="primary"
        variant="tonal"
        prepend-icon="mdi-backup-restore"
        :loading="restoring"
        @click="openRestoreDialog"
      >
        {{ t("settings.local_lib.backup.restore") }}
      </v-btn>
      <!-- The other direction: the database is the source of truth here, and the
           files on disk are stale. Needed when a library was imported by another
           tool, so nothing ever wrote a ComicInfo.xml back. -->
      <v-btn
        color="secondary"
        variant="tonal"
        prepend-icon="mdi-file-export-outline"
        :loading="writebackBusy"
        @click="openWritebackDialog"
      >
        {{ t("settings.local_lib.writeback.action") }}
      </v-btn>
    </div>
    <div class="text-caption text-medium-emphasis mt-2">{{ t("settings.local_lib.writeback.hint") }}</div>
  </v-card>

  <v-dialog v-model="writebackDialog" max-width="560">
    <v-card>
      <v-card-title class="text-subtitle-1">{{ t("settings.local_lib.writeback.dialog_title") }}</v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" density="compact" class="mb-3">
          {{ t("settings.local_lib.writeback.preview_note") }}
        </v-alert>
        <div class="text-body-2">
          {{ t("settings.local_lib.writeback.preview", {
            total: Number(writebackReport?.total || 0),
            skipped: Number(writebackReport?.skipped || 0),
          }) }}
        </div>
        <v-alert v-if="writebackDone" type="success" variant="tonal" density="compact" class="mt-3">
          {{ t("settings.local_lib.writeback.done", {
            comicinfo: Number(writebackReport?.comicinfo_written || 0),
            sidecar: Number(writebackReport?.sidecar_written || 0),
            failed: Number(writebackReport?.failed || 0),
          }) }}
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="writebackDialog = false">{{ t("settings.local_lib.backup.close") }}</v-btn>
        <v-btn color="primary" :loading="writebackBusy" :disabled="writebackDone" @click="runWriteback">
          {{ t("settings.local_lib.writeback.confirm") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- The restore is a two-step flow on purpose: the same endpoint is asked
       twice, once as a dry run so the user can see the plan, then for real.
       Writing hours of recomputed vectors is not something to do blind. -->
  <v-dialog v-model="restoreDialog" max-width="640" scrollable>
    <v-card>
      <v-card-title class="text-subtitle-1">{{ t("settings.local_lib.backup.dialog_title") }}</v-card-title>
      <v-card-text>
        <v-alert v-if="!restoreDone" type="info" variant="tonal" density="compact" class="mb-3">
          {{ t("settings.local_lib.backup.preview_note") }}
        </v-alert>
        <template v-if="restoreShowsAny">
          <div class="text-body-2 mb-2">
            {{ t("settings.local_lib.backup.summary", { total: restoreTotal, matched: restoreMatched, restored: restoreRestored }) }}
          </div>
          <div class="text-caption text-medium-emphasis mb-3">
            {{ t("settings.local_lib.backup.vectors", { visual: restoreVisual, text: restoreText, history: restoreHistory, meta: restoreMeta }) }}
          </div>
          <v-alert v-if="restoreMovedCount" type="info" variant="tonal" density="comfortable" class="mb-2">
            <div>{{ t("settings.local_lib.backup.moved_title", { n: restoreMovedCount }) }}</div>
            <div class="text-caption">
              {{ t("settings.local_lib.backup.moved_detail", { cover: restoreMovedByCover, name: restoreMovedByName }) }}
            </div>
          </v-alert>
          <v-alert v-if="restoreMissingCount" type="warning" variant="tonal" density="comfortable" class="mb-2">
            {{ t("settings.local_lib.backup.missing_title", { n: restoreMissingCount }) }}
          </v-alert>
          <v-alert v-else type="success" variant="tonal" density="comfortable" class="mb-2">
            {{ t("settings.local_lib.backup.missing_empty") }}
          </v-alert>
          <v-alert v-if="restoreOrphanCount" type="info" variant="tonal" density="comfortable" class="mb-2">
            {{ t("settings.local_lib.backup.orphan_title", { n: restoreOrphanCount }) }}
          </v-alert>
          <v-alert v-if="restoreUnreadableCount" type="warning" variant="tonal" density="comfortable" class="mb-2">
            {{ t("settings.local_lib.backup.unreadable_title", { n: restoreUnreadableCount }) }}
          </v-alert>
          <v-alert v-if="restoreFailedCount" type="error" variant="tonal" density="comfortable" class="mb-2">
            {{ t("settings.local_lib.backup.failed_title", { n: restoreFailedCount }) }}
          </v-alert>
        </template>
        <v-alert v-else type="info" variant="tonal" density="comfortable">
          {{ t("settings.local_lib.backup.none") }}
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-btn
          v-if="restoreDone && restoreLogId"
          variant="tonal"
          prepend-icon="mdi-download"
          :loading="downloadingRestoreLog"
          @click="downloadRestoreLog"
        >
          {{ t("settings.local_lib.backup.download_log") }}
        </v-btn>
        <v-spacer />
        <v-btn variant="text" @click="restoreDialog = false">{{ t("settings.local_lib.backup.close") }}</v-btn>
        <v-btn
          v-if="!restoreDone && restoreShowsAny"
          color="primary"
          :loading="restoring"
          @click="confirmRestore"
        >
          {{ t("settings.local_lib.backup.confirm") }}
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-card class="pa-4 mb-4" variant="flat">
    <div class="text-subtitle-2 font-weight-medium">{{ t("settings.local_lib.display_mode.title") }}</div>
    <div class="text-body-2 text-medium-emphasis mb-3">{{ t("settings.local_lib.display_mode.hint") }}</div>

    <!-- One choice, two values -- not two switches. "Infinite and paged at the
         same time" is not a state the feed can be in, so the UI must not be able
         to express it. -->
    <v-btn-toggle
      :model-value="feedMode"
      mandatory
      variant="outlined"
      divided
      density="comfortable"
      rounded="lg"
      color="primary"
      class="bg-surface mb-1 flex-wrap"
      :disabled="savingDisplayMode"
      @update:model-value="onFeedModeChange"
    >
      <v-btn value="infinite" prepend-icon="mdi-autorenew" :data-feed-mode="'infinite'">
        {{ t("settings.local_lib.display_mode.infinite") }}
      </v-btn>
      <v-btn value="paged" prepend-icon="mdi-book-open-page-variant-outline" :data-feed-mode="'paged'">
        {{ t("settings.local_lib.display_mode.paged") }}
      </v-btn>
    </v-btn-toggle>
    <div class="text-caption text-medium-emphasis mb-4">{{ feedModeHint }}</div>

    <!-- The page size and the pull gesture only exist in paged mode, so they are
         disabled rather than hidden: the user can still see what the other mode
         would offer, and nothing here silently takes effect while greyed out. -->
    <div :class="{ 'display-mode-gated': !feedPagedMode }" data-feed-mode-gated>
      <v-select
        v-model="feedPageSize"
        :items="feedPageSizeItems"
        item-title="title"
        item-value="value"
        :label="t('settings.local_lib.display_mode.page_size')"
        :disabled="!feedPagedMode || savingDisplayMode"
        density="compact"
        variant="outlined"
        hide-details
        class="mb-1 display-mode-page-size"
        :menu-props="{ contentClass: 'display-mode-page-size-menu' }"
        @update:model-value="onFeedPageSizeChange"
      />
      <div class="text-caption text-medium-emphasis mb-3">{{ t("settings.local_lib.display_mode.page_size_hint") }}</div>

      <v-switch
        v-model="feedPullToPage"
        color="primary"
        inset
        data-feed-pull
        :disabled="!feedPagedMode || savingDisplayMode"
        hide-details
        :label="t('settings.local_lib.display_mode.pull_to_page')"
        @update:model-value="onFeedPullToPageToggle"
      />
      <div class="text-caption text-medium-emphasis ms-1">{{ t("settings.local_lib.display_mode.pull_to_page_hint") }}</div>
    </div>
  </v-card>

  <v-card class="pa-4 mb-4" variant="flat">
    <div class="d-flex align-center justify-space-between ga-2 mb-3 flex-wrap">
      <div>
        <div class="text-subtitle-2 font-weight-medium">{{ t("settings.local_lib.translation.title") }}</div>
        <div class="text-body-2 text-medium-emphasis">{{ t("settings.local_lib.translation.hint") }}</div>
      </div>
      <div class="d-flex ga-2 flex-wrap">
        <v-btn size="small" variant="tonal" prepend-icon="mdi-refresh" :loading="loadingTranslationTable" @click="loadTranslationTableStatus">{{ t("settings.local_lib.translation.reload") }}</v-btn>
        <v-btn size="small" variant="tonal" color="error" prepend-icon="mdi-delete-outline" :disabled="!translationTable.exists" @click="clearTranslationTable">{{ t("settings.local_lib.translation.clear") }}</v-btn>
      </div>
    </div>

    <v-row density="comfortable">
      <v-col cols="12" md="6">
        <v-chip variant="outlined" class="mb-2 text-truncate">{{ t("settings.local_lib.translation.dir", { dir: translationTable.dir || "-" }) }}</v-chip>
      </v-col>
      <v-col cols="12" md="6">
        <v-chip variant="tonal" :color="translationTable.exists ? 'success' : 'warning'" class="mb-2">
          {{
            translationTable.exists
              ? t("settings.local_lib.translation.file", { name: translationTable.file_name, size: translationTableSizeLabel, time: translationTable.updated_at })
              : t("settings.local_lib.translation.missing")
          }}
        </v-chip>
      </v-col>
      <v-col cols="12" md="6">
        <div class="text-caption text-medium-emphasis">
          {{ t("settings.local_lib.translation.stats", { ns: translationTable.namespaces || 0, tags: translationTable.tags || 0 }) }}
        </div>
      </v-col>
      <v-col cols="12" md="6">
        <v-file-input
          v-model="translationTableFile"
          :label="t('settings.local_lib.translation.upload')"
          accept=".json,.jsonl,.txt"
          density="compact"
          variant="outlined"
          prepend-icon="mdi-upload"
          hide-details
          :loading="uploadingTranslationTable"
          @update:model-value="onTranslationTablePicked"
        />
      </v-col>
    </v-row>
    <v-alert v-if="translationTableResultText" class="mt-3" type="info" variant="tonal" density="compact">{{ translationTableResultText }}</v-alert>
    <v-alert v-if="translationNeedsReapply" class="mt-2" type="warning" variant="tonal" density="comfortable">
      <div class="d-flex align-center justify-space-between ga-3 flex-wrap">
        <div class="text-body-2">{{ t("settings.local_lib.reapply.table_changed") }}</div>
        <v-btn
          size="small"
          color="warning"
          variant="flat"
          prepend-icon="mdi-tag-check-outline"
          :loading="startingReapply"
          :disabled="reapplyRunning"
          @click="startReapplyNow()"
        >
          {{ t("settings.local_lib.reapply.apply_now") }}
        </v-btn>
      </div>
    </v-alert>
  </v-card>

  <v-card class="pa-4 mb-4" variant="flat">
    <div class="d-flex align-center justify-space-between ga-2 mb-3 flex-wrap">
      <div>
        <div class="text-subtitle-2 font-weight-medium">{{ t("settings.local_lib.category.title") }}</div>
        <div class="text-body-2 text-medium-emphasis">{{ t("settings.local_lib.category.hint") }}</div>
      </div>
      <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="openCreateCategoryDialog">{{ t("settings.local_lib.category.add") }}</v-btn>
    </div>

    <v-select
      v-model="settingsStore.config.LOCAL_THUMB_PRESET"
      :items="thumbPresetItems"
      item-title="title"
      item-value="value"
      :label="t('settings.local_lib.thumb_preset')"
      density="compact"
      variant="outlined"
      hide-details
      class="mb-4"
      @update:model-value="saveThumbPreset"
    />

    <div class="text-caption text-medium-emphasis mb-2">{{ t("settings.local_lib.category.builtin") }}</div>
    <div class="d-flex flex-column ga-2 mb-4">
      <div v-for="cat in builtinCategoryDefs" :key="`builtin-cat-${cat.key}`" class="namespace-row">
        <div class="d-flex align-center ga-3 flex-wrap">
          <v-chip size="small" class="namespace-pill" :style="categoryPillStyle(cat.color)">{{ categoryLabel(cat) }}</v-chip>
          <span class="text-caption text-medium-emphasis">{{ cat.key }}</span>
          <v-chip size="x-small" variant="outlined" :color="isCategoryPinned(cat.key) ? 'primary' : 'default'">
            {{ isCategoryPinned(cat.key) ? t("settings.local_lib.category.pinned") : t("settings.local_lib.category.unpinned") }}
          </v-chip>
        </div>
        <div class="d-flex ga-1">
          <v-btn
            size="small"
            variant="text"
            :color="isCategoryPinned(cat.key) ? 'primary' : 'default'"
            :icon="isCategoryPinned(cat.key) ? 'mdi-pin' : 'mdi-pin-outline'"
            @click="toggleCategoryPinned(cat.key)"
          />
        </div>
      </div>
    </div>

    <div class="text-caption text-medium-emphasis mb-2">{{ t("settings.local_lib.category.custom") }}</div>
    <div v-if="customCategoryDefs.length" class="d-flex flex-column ga-2">
      <div v-for="cat in customCategoryDefs" :key="`custom-cat-${cat.key}`" class="namespace-row">
        <div class="d-flex align-center ga-3 flex-wrap">
          <v-chip size="small" class="namespace-pill" :style="categoryPillStyle(cat.color)">{{ categoryLabel(cat) }}</v-chip>
          <span class="text-caption text-medium-emphasis">{{ cat.key }}</span>
          <v-chip size="x-small" variant="outlined" :color="isCategoryPinned(cat.key) ? 'primary' : 'default'">
            {{ isCategoryPinned(cat.key) ? t("settings.local_lib.category.pinned") : t("settings.local_lib.category.unpinned") }}
          </v-chip>
        </div>
        <div class="d-flex ga-1">
          <v-btn
            size="small"
            variant="text"
            :color="isCategoryPinned(cat.key) ? 'primary' : 'default'"
            :icon="isCategoryPinned(cat.key) ? 'mdi-pin' : 'mdi-pin-outline'"
            @click="toggleCategoryPinned(cat.key)"
          />
          <v-btn size="small" variant="text" icon="mdi-pencil-outline" @click="openEditCategoryDialog(cat)" />
          <v-btn size="small" variant="text" color="error" icon="mdi-delete-outline" @click="deleteCustomCategory(cat)" />
        </div>
      </div>
    </div>
    <div v-else class="text-medium-emphasis">{{ t("settings.local_lib.category.empty") }}</div>
  </v-card>

  <v-card class="pa-4 mb-4" variant="flat">
    <div class="d-flex align-center justify-space-between ga-2 mb-3 flex-wrap">
      <div>
        <div class="text-subtitle-2 font-weight-medium">{{ t("settings.local_lib.namespace.title") }}</div>
        <div class="text-body-2 text-medium-emphasis">{{ t("settings.local_lib.namespace.hint") }}</div>
      </div>
      <v-btn color="primary" variant="tonal" prepend-icon="mdi-plus" @click="openCreateNamespaceDialog">{{ t("settings.local_lib.namespace.add") }}</v-btn>
    </div>

    <div class="text-caption text-medium-emphasis mb-2">{{ t("settings.local_lib.namespace.builtin") }}</div>
    <div class="d-flex ga-2 flex-wrap mb-4">
      <v-chip
        v-for="ns in builtinNamespaceDefs"
        :key="`builtin-${ns.key}`"
        size="small"
        class="namespace-pill"
        :style="namespacePillStyle(ns.color)"
      >
        {{ namespaceLabel(ns.key) }}
      </v-chip>
    </div>

    <div class="text-caption text-medium-emphasis mb-2">{{ t("settings.local_lib.namespace.custom") }}</div>
    <div v-if="customNamespaceDefs.length" class="d-flex flex-column ga-2">
      <div v-for="ns in customNamespaceDefs" :key="`custom-${ns.key}`" class="namespace-row">
        <div class="d-flex align-center ga-3 flex-wrap">
          <v-chip size="small" class="namespace-pill" :style="namespacePillStyle(ns.color)">{{ ns.key }}</v-chip>
          <span class="text-caption text-medium-emphasis">{{ ns.color }}</span>
        </div>
        <div class="d-flex ga-1">
          <v-btn size="small" variant="text" icon="mdi-pencil-outline" @click="openEditNamespaceDialog(ns)" />
          <v-btn size="small" variant="text" color="error" icon="mdi-delete-outline" @click="deleteCustomNamespace(ns)" />
        </div>
      </div>
    </div>
    <div v-else class="text-medium-emphasis">{{ t("settings.local_lib.namespace.empty") }}</div>
  </v-card>

  <v-dialog v-model="reapplyDialog" persistent max-width="620">
    <v-card>
      <v-card-title class="text-h6 d-flex align-center ga-2">
        <v-icon :icon="reapplyRunning ? 'mdi-progress-clock' : 'mdi-tag-check-outline'" />
        <span>{{ t("settings.local_lib.reapply.dialog_title", { mode: reapplyModeLabel }) }}</span>
      </v-card-title>
      <v-card-text>
        <v-alert type="info" variant="tonal" density="comfortable" class="mb-4">
          {{ t("settings.local_lib.reapply.dialog_warning") }}
        </v-alert>
        <v-progress-linear
          :model-value="reapplyPercent"
          :indeterminate="reapplyRunning && reapplyTotal <= 0"
          :color="reapplyRunning ? 'primary' : reapplySummaryType"
          height="10"
          rounded
          striped
        />
        <div class="d-flex justify-space-between ga-2 text-caption text-medium-emphasis mt-2 flex-wrap">
          <span>{{ t("settings.local_lib.reapply.dialog_progress", { done: reapplyProcessed, total: reapplyTotal }) }}</span>
          <span>{{ reapplyPercent }}%</span>
        </div>
        <div class="text-caption text-medium-emphasis mt-1">
          {{ t("settings.local_lib.reapply.dialog_counters", { updated: reapplyUpdated, skipped: reapplySkipped, failed: reapplyFailed }) }}
        </div>
        <div v-if="reapplyRunning" class="text-caption text-medium-emphasis mt-1">
          {{ t("settings.local_lib.reapply.dialog_leave_hint") }}
        </div>
        <v-alert
          v-for="note in reapplyNotes"
          :key="note.key"
          class="mt-3"
          :type="note.type"
          variant="tonal"
          density="compact"
        >
          {{ note.text }}
        </v-alert>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn v-if="reapplyRunning" variant="text" color="warning" :loading="cancellingReapply" @click="cancelReapplyNow">
          {{ t("settings.local_lib.reapply.cancel") }}
        </v-btn>
        <v-btn v-else color="primary" @click="closeReapplyDialog">{{ t("settings.unlock.confirm") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="namespaceDialogOpen" max-width="520">
    <v-card>
      <v-card-title class="text-h6">{{ namespaceDialogMode === "edit" ? t("settings.local_lib.namespace.edit_title") : t("settings.local_lib.namespace.add_title") }}</v-card-title>
      <v-card-text>
        <v-text-field
          v-model="namespaceFormKey"
          :label="t('settings.local_lib.namespace.name')"
          density="compact"
          variant="outlined"
          :readonly="namespaceDialogMode === 'edit'"
        />
        <div class="d-flex align-center ga-3 mb-3 flex-wrap">
          <v-text-field
            v-model="namespaceFormColor"
            :label="t('settings.local_lib.namespace.color')"
            density="compact"
            variant="outlined"
            style="max-width: 180px"
          />
          <input v-model="namespaceFormColor" type="color" class="namespace-color-input" />
          <v-chip size="small" class="namespace-pill" :style="namespacePillStyle(namespaceFormColor)">
            {{ namespacePreviewLabel }}
          </v-chip>
        </div>
        <div class="text-caption text-medium-emphasis">{{ t("settings.local_lib.namespace.preview_hint") }}</div>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="closeNamespaceDialog">{{ t("settings.unlock.cancel") }}</v-btn>
        <v-btn color="primary" :loading="savingNamespaces" @click="saveNamespaceDialog">{{ t("settings.unlock.confirm") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="categoryDialogOpen" max-width="560">
    <v-card>
      <v-card-title class="text-h6">{{ categoryDialogMode === "edit" ? t("settings.local_lib.category.edit_title") : t("settings.local_lib.category.add_title") }}</v-card-title>
      <v-card-text>
        <v-text-field
          v-model="categoryFormLabel"
          :label="t('settings.local_lib.category.name')"
          density="compact"
          variant="outlined"
          :readonly="categoryDialogMode === 'edit'"
        />
        <div class="d-flex align-center ga-3 mb-3 flex-wrap">
          <v-text-field
            v-model="categoryFormColor"
            :label="t('settings.local_lib.category.color')"
            density="compact"
            variant="outlined"
            style="max-width: 180px"
          />
          <input v-model="categoryFormColor" type="color" class="namespace-color-input" />
          <v-chip size="small" class="namespace-pill" :style="categoryPillStyle(categoryFormColor)">
            {{ categoryPreviewLabel }}
          </v-chip>
        </div>
        <div class="text-caption text-medium-emphasis">{{ t("settings.local_lib.category.preview_hint") }}</div>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="closeCategoryDialog">{{ t("settings.unlock.cancel") }}</v-btn>
        <v-btn color="primary" :loading="savingCategories" @click="saveCategoryDialog">{{ t("settings.unlock.confirm") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="confirmReadEventsDialog" max-width="460">
    <v-card>
      <v-card-title class="text-h6">{{ t("settings.data_clean.clear_read_events") }}</v-card-title>
      <v-card-text>{{ t("settings.data_clean.clear_read_events_confirm") }}</v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="confirmReadEventsDialog = false">{{ t("settings.unlock.cancel") }}</v-btn>
        <v-btn color="error" @click="confirmClearReadEventsNow">{{ t("settings.unlock.confirm") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="rebuildDialog" max-width="520" persistent>
    <v-card>
      <v-card-title>{{ t("settings.rebuild.title") }}</v-card-title>
      <v-card-text>
        <p class="mb-4">{{ t("settings.rebuild.confirm") }}</p>
        <v-text-field v-model="rebuildPassword" :label="t('auth.password')" type="password" autocomplete="current-password" :disabled="rebuilding" />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :disabled="rebuilding" @click="closeRebuildDialog">{{ t("common.cancel") }}</v-btn>
        <v-btn color="error" :loading="rebuilding" :disabled="!rebuildPassword" @click="confirmRebuild">{{ t("settings.rebuild.title") }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  cancelTagReapply,
  clearLocalThumbCache,
  clearTranslationTableFile,
  downloadLocalMetadataRestoreLog,
  getConfig,
  getTagReapplyStatus,
  getTranslationStatus,
  rebuildGalleryDatabase,
  restoreLocalMetadata,
  writebackLocalMetadata,
  startTagReapply,
  triggerLocalLibScan,
  updateConfig,
  uploadTranslationFile,
} from "../../api";
import { useAppStore } from "../../stores/appStore";
import { useDashboardStore } from "../../stores/dashboardStore";
import { useLayoutStore } from "../../stores/layoutStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { useToastStore } from "../../stores/useToastStore";
// The mode names, the offered page sizes and the normalisers come from the store
// the dashboard reads: if the settings invented their own, a value could be
// stored here that the feed immediately normalises into something else -- a
// setting that silently does not stick.
import {
  FEED_DEFAULT_PAGE_SIZE,
  FEED_MODE_INFINITE,
  FEED_MODE_PAGED,
  FEED_PAGE_SIZES,
  normalizeFeedMode,
  normalizeFeedPageSize,
} from "../../stores/dashboardStore";
import {
  getCategoryLabel,
  normalizeCategoryColor,
  normalizeCategoryKey,
  parseCustomCategoryConfig,
  stringifyCustomCategoryConfig,
  stringifyPinnedCategoryKeys,
} from "../../utils/categoryPresets";
import {
  getNamespaceDisplayLabel,
  normalizeNamespaceColor,
  normalizeNamespaceKey,
  parseCustomNamespaceConfig,
  stringifyCustomNamespaceConfig,
} from "../../utils/tagNamespaces";

const layoutStore = useLayoutStore();
const settingsStore = useSettingsStore();
const toast = useToastStore();
const appStore = useAppStore();

const scanning = ref(false);
const clearingThumbCache = ref(false);
const resultText = ref("");
// Clearing the read history is irreversible and deletes every row in
// `read_events`, so it goes through a confirmation before touching the DB.
const confirmReadEventsDialog = ref(false);
const showJpnTitle = ref(false);
const useTranslatedTags = ref(true);
const savingDisplayPrefs = ref(false);
// Presentation mode. Mirrored locally (like showJpnTitle) so the write can be
// read back and confirmed, instead of trusting the optimistic switch state.
const feedMode = ref(FEED_MODE_INFINITE);
const feedPageSize = ref(FEED_DEFAULT_PAGE_SIZE);
const feedPullToPage = ref(false);
const savingDisplayMode = ref(false);
const feedPagedMode = computed(() => feedMode.value === FEED_MODE_PAGED);
const translationTable = ref({ dir: "", file_name: "", path: "", exists: false, size: 0, updated_at: "-", namespaces: 0, tags: 0 });
const translationTableFile = ref(null);
const loadingTranslationTable = ref(false);
const uploadingTranslationTable = ref(false);
const translationTableResultText = ref("");
// State of the gallery-backup restore. `restoreDone` is what separates the
// preview (a dry run, nothing written) from the real thing: the dialog is the
// same, only the confirm button appears in between.
const restoring = ref(false);
const restoreDialog = ref(false);
const writebackDialog = ref(false);
const writebackBusy = ref(false);
const writebackDone = ref(false);
const writebackReport = ref(null);
const restoreDone = ref(false);
const restoreReport = ref(null);
const downloadingRestoreLog = ref(false);
const restoreMissingCount = computed(() => Number(restoreReport.value?.no_sidecar_count || 0));
const restoreLogId = computed(() => String(restoreReport.value?.log_id || "").trim());
const restoreTotal = computed(() => Number(restoreReport.value?.total_galleries || 0));
const restoreMatched = computed(() => Number(restoreReport.value?.matched || 0));
const restoreRestored = computed(() => Number(restoreReport.value?.restored || 0));
const restoreVisual = computed(() => Number(restoreReport.value?.visual_restored || 0));
const restoreText = computed(() => Number(restoreReport.value?.text_restored || 0));
const restoreHistory = computed(() => Number(restoreReport.value?.history_rows || 0));
const restoreMeta = computed(() => Number(restoreReport.value?.meta_restored || 0));
const restoreOrphanCount = computed(() => Number(restoreReport.value?.orphan_count || 0));
const restoreUnreadableCount = computed(() => Number(restoreReport.value?.unreadable_count || 0));
const restoreFailedCount = computed(() => Number(restoreReport.value?.failed_count || 0));
// A match that needed a fallback is a *different* event from an exact-id match:
// the gallery's folder was moved or renamed, and the backup was found by its
// cover or by a unique folder name. The counters alone look identical to a clean
// run, so this is surfaced rather than left to the downloadable log.
const restoreMovedByCover = computed(
  () => Number(restoreReport.value?.matched_by_tier?.cover_hash || 0),
);
const restoreMovedByName = computed(
  () => Number(restoreReport.value?.matched_by_tier?.gallery_name || 0),
);
const restoreMovedCount = computed(() => restoreMovedByCover.value + restoreMovedByName.value);
// "Anything worth showing": a library with no sidecars at all gets the "no
// backups yet" hint instead of a row of zeroes.
const restoreShowsAny = computed(() => Number(restoreReport.value?.sidecars || 0) > 0);
const savingCategories = ref(false);
const categoryDialogOpen = ref(false);
const categoryDialogMode = ref("create");
const categoryEditingKey = ref("");
const categoryFormLabel = ref("");
const categoryFormColor = ref("#475569");
const savingNamespaces = ref(false);
const namespaceDialogOpen = ref(false);
const namespaceDialogMode = ref("create");
const namespaceEditingKey = ref("");
const namespaceFormKey = ref("");
const namespaceFormColor = ref("#6b7280");
const reapplyDialog = ref(false);
const startingReapply = ref(false);
const cancellingReapply = ref(false);
const reapplyState = ref(blankReapplyState());
const reapplyPending = ref(0);
const translationNeedsReapply = ref(false);
let reapplyTimer = null;

function blankReapplyState() {
  return {
    status: "idle",
    mode: "",
    total: 0,
    processed: 0,
    updated: 0,
    skipped: 0,
    failed: 0,
    pending: 0,
    cancel_requested: false,
    current_arcid: "",
    error: "",
    skipped_reasons: {},
    skipped_sample: [],
    failed_sample: [],
  };
}

const MODE_LABEL_KEYS = {
  translated: "settings.local_lib.reapply.mode_translated",
  raw: "settings.local_lib.reapply.mode_raw",
  translated_plus_raw: "settings.local_lib.reapply.mode_translated_plus_raw",
};

const reapplyRunning = computed(() => ["running", "cancelling"].includes(String(reapplyState.value.status || "")));
const reapplyTotal = computed(() => Number(reapplyState.value.total || 0));
const reapplyProcessed = computed(() => Number(reapplyState.value.processed || 0));
const reapplyUpdated = computed(() => Number(reapplyState.value.updated || 0));
const reapplySkipped = computed(() => Number(reapplyState.value.skipped || 0));
const reapplyFailed = computed(() => Number(reapplyState.value.failed || 0));
const reapplyModeLabel = computed(() => {
  const key = MODE_LABEL_KEYS[String(reapplyState.value.mode || "")];
  return key ? t(key) : t("settings.local_lib.reapply.mode_default");
});
const reapplyPercent = computed(() => {
  if (!reapplyRunning.value) return 100;
  if (reapplyTotal.value <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((reapplyProcessed.value / reapplyTotal.value) * 100)));
});
const reapplySummaryType = computed(() => {
  const status = String(reapplyState.value.status || "");
  if (status === "failed") return "error";
  if (status === "cancelled" || reapplyFailed.value > 0 || reapplySkipped.value > 0) return "warning";
  return "success";
});
const reapplySummaryText = computed(() => {
  const status = String(reapplyState.value.status || "");
  if (status === "idle") {
    return reapplyPending.value > 0 ? t("settings.local_lib.reapply.pending_hint", { n: reapplyPending.value }) : "";
  }
  if (status === "cancelled") {
    return t("settings.local_lib.reapply.cancelled_hint", { updated: reapplyUpdated.value, pending: reapplyPending.value });
  }
  if (status === "failed") {
    return t("settings.local_lib.reapply.job_failed", { error: String(reapplyState.value.error || "-") });
  }
  return t("settings.local_lib.reapply.done_hint", {
    updated: reapplyUpdated.value,
    skipped: reapplySkipped.value,
    failed: reapplyFailed.value,
  });
});
const reapplyNotes = computed(() => {
  const notes = [];
  const reasons = reapplyState.value.skipped_reasons || {};
  const noSource = Number(reasons.no_raw_tags || 0);
  if (!reapplyRunning.value && noSource > 0) {
    notes.push({ key: "no-source", type: "warning", text: t("settings.local_lib.reapply.skipped_no_source", { n: noSource }) });
  }
  if (!reapplyRunning.value && reapplyFailed.value > 0) {
    const sample = Array.isArray(reapplyState.value.failed_sample) ? reapplyState.value.failed_sample : [];
    const first = sample[0] || {};
    notes.push({
      key: "failed",
      type: "error",
      text: t("settings.local_lib.reapply.failed_note", { n: reapplyFailed.value, arcid: String(first.arcid || "-"), reason: String(first.reason || "-") }),
    });
  }
  if (!reapplyRunning.value && String(reapplyState.value.status || "") === "cancelled") {
    notes.push({ key: "cancelled", type: "info", text: t("settings.local_lib.reapply.cancelled_note") });
  }
  return notes;
});

function t(key, vars = {}) {
  return layoutStore.t(key, vars);
}

const builtinCategoryDefs = computed(() => Array.isArray(settingsStore.builtinCategoryDefs) ? settingsStore.builtinCategoryDefs : []);
const customCategoryDefs = computed(() => Array.isArray(settingsStore.customCategoryDefs) ? settingsStore.customCategoryDefs : []);
const pinnedCategoryKeys = computed(() => Array.isArray(settingsStore.pinnedCategoryKeys) ? settingsStore.pinnedCategoryKeys : []);
const builtinNamespaceDefs = computed(() => Array.isArray(settingsStore.builtinNamespaceDefs) ? settingsStore.builtinNamespaceDefs : []);
const customNamespaceDefs = computed(() => Array.isArray(settingsStore.customNamespaceDefs) ? settingsStore.customNamespaceDefs : []);
const thumbPresetItems = computed(() => ([
  { title: t("settings.local_lib.thumb_preset_low"), value: "low" },
  { title: t("settings.local_lib.thumb_preset_mid"), value: "mid" },
  { title: t("settings.local_lib.thumb_preset_high"), value: "high" },
  { title: t("settings.local_lib.thumb_preset_ultra"), value: "ultra" },
]));
const feedPageSizeItems = computed(() => FEED_PAGE_SIZES.map((value) => ({
  title: t("settings.local_lib.display_mode.page_size_item", { n: value }),
  value,
})));
const feedModeHint = computed(() => t(
  feedPagedMode.value
    ? "settings.local_lib.display_mode.paged_hint"
    : "settings.local_lib.display_mode.infinite_hint"
));
const categoryPreviewLabel = computed(() => {
  const label = String(categoryFormLabel.value || "").trim().replace(/\s+/g, " ");
  const key = normalizeCategoryKey(label);
  return label || key || t("settings.local_lib.category.preview_fallback");
});
const namespacePreviewLabel = computed(() => {
  const key = normalizeNamespaceKey(namespaceFormKey.value, { fallbackToOther: false });
  return key || t("settings.local_lib.namespace.preview_fallback");
});

function namespaceLabel(key) {
  return getNamespaceDisplayLabel(key, t, customNamespaceDefs.value);
}

function categoryLabel(row) {
  return getCategoryLabel(row, t);
}

function namespacePillStyle(color) {
  return {
    backgroundColor: normalizeNamespaceColor(color),
    color: "#ffffff",
  };
}

function categoryPillStyle(color) {
  return {
    backgroundColor: normalizeCategoryColor(color),
    color: "#ffffff",
  };
}

function isCategoryPinned(key) {
  const safeKey = normalizeCategoryKey(key);
  return pinnedCategoryKeys.value.includes(safeKey);
}

function openCreateCategoryDialog() {
  categoryDialogMode.value = "create";
  categoryEditingKey.value = "";
  categoryFormLabel.value = "";
  categoryFormColor.value = "#475569";
  categoryDialogOpen.value = true;
}

function openEditCategoryDialog(row) {
  categoryDialogMode.value = "edit";
  categoryEditingKey.value = String(row?.key || "").trim();
  categoryFormLabel.value = String(row?.label || row?.key || "").trim();
  categoryFormColor.value = normalizeCategoryColor(row?.color || "#475569");
  categoryDialogOpen.value = true;
}

function closeCategoryDialog() {
  categoryDialogOpen.value = false;
}

async function persistCustomCategories(rows = []) {
  savingCategories.value = true;
  try {
    await updateConfig({
      LOCAL_LIB_CUSTOM_CATEGORIES: stringifyCustomCategoryConfig(rows),
    });
    await settingsStore.loadConfigData();
  } finally {
    savingCategories.value = false;
  }
}

async function persistPinnedCategories(nextKeys = []) {
  savingCategories.value = true;
  try {
    await updateConfig({
      LOCAL_LIB_PINNED_CATEGORY_KEYS: stringifyPinnedCategoryKeys(nextKeys, customCategoryDefs.value),
    });
    await settingsStore.loadConfigData();
  } finally {
    savingCategories.value = false;
  }
}

async function saveThumbPreset(value) {
  const nextValue = String(value || settingsStore.config.LOCAL_THUMB_PRESET || "mid").trim().toLowerCase() || "mid";
  try {
    await updateConfig({ LOCAL_THUMB_PRESET: nextValue });
    await settingsStore.loadConfigData();
    toast.success(t("settings.saved_json"));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

async function toggleCategoryPinned(key) {
  const safeKey = normalizeCategoryKey(key);
  if (!safeKey) return;
  const next = [...pinnedCategoryKeys.value];
  const idx = next.indexOf(safeKey);
  if (idx >= 0) {
    next.splice(idx, 1);
  } else {
    if (next.length >= 10) {
      toast.warning(t("settings.local_lib.category.pin_limit"));
      return;
    }
    next.push(safeKey);
  }
  try {
    await persistPinnedCategories(next);
    toast.success(t("settings.saved_json"));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

async function saveCategoryDialog() {
  const label = String(categoryFormLabel.value || "").trim().replace(/\s+/g, " ");
  const key = normalizeCategoryKey(label);
  if (!key) {
    toast.warning(t("settings.local_lib.category.invalid_name"));
    return;
  }
  if (builtinCategoryDefs.value.some((it) => String(it?.key || "") === key)) {
    toast.warning(t("settings.local_lib.category.builtin_conflict"));
    return;
  }
  const color = normalizeCategoryColor(categoryFormColor.value);
  const nextRows = parseCustomCategoryConfig(customCategoryDefs.value);
  if (categoryDialogMode.value === "edit") {
    const idx = nextRows.findIndex((it) => String(it?.key || "") === String(categoryEditingKey.value || ""));
    if (idx < 0) {
      toast.warning(t("settings.local_lib.category.not_found"));
      return;
    }
    nextRows[idx] = {
      ...nextRows[idx],
      label,
      color,
    };
  } else {
    if (nextRows.some((it) => String(it?.key || "") === key)) {
      toast.warning(t("settings.local_lib.category.duplicate"));
      return;
    }
    nextRows.push({
      key,
      label,
      color,
      order: nextRows.length,
    });
  }
  try {
    await persistCustomCategories(nextRows);
    toast.success(t("settings.saved_json"));
    categoryDialogOpen.value = false;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

async function deleteCustomCategory(row) {
  const key = String(row?.key || "").trim();
  if (!key) return;
  const nextRows = parseCustomCategoryConfig(customCategoryDefs.value).filter((it) => String(it?.key || "") !== key);
  try {
    await persistCustomCategories(nextRows);
    toast.success(t("settings.saved_json"));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

function openCreateNamespaceDialog() {
  namespaceDialogMode.value = "create";
  namespaceEditingKey.value = "";
  namespaceFormKey.value = "";
  namespaceFormColor.value = "#6b7280";
  namespaceDialogOpen.value = true;
}

function openEditNamespaceDialog(row) {
  namespaceDialogMode.value = "edit";
  namespaceEditingKey.value = String(row?.key || "").trim();
  namespaceFormKey.value = namespaceEditingKey.value;
  namespaceFormColor.value = normalizeNamespaceColor(row?.color || "#6b7280");
  namespaceDialogOpen.value = true;
}

function closeNamespaceDialog() {
  namespaceDialogOpen.value = false;
}

async function persistCustomNamespaces(rows = []) {
  savingNamespaces.value = true;
  try {
    await updateConfig({
      LOCAL_LIB_CUSTOM_NAMESPACES: stringifyCustomNamespaceConfig(rows),
    });
    await settingsStore.loadConfigData();
  } finally {
    savingNamespaces.value = false;
  }
}

async function saveNamespaceDialog() {
  const key = normalizeNamespaceKey(namespaceFormKey.value, { fallbackToOther: false });
  if (!key) {
    toast.warning(t("settings.local_lib.namespace.invalid_name"));
    return;
  }
  if (builtinNamespaceDefs.value.some((it) => String(it?.key || "") === key)) {
    toast.warning(t("settings.local_lib.namespace.builtin_conflict"));
    return;
  }
  const nextRows = parseCustomNamespaceConfig(customNamespaceDefs.value);
  const color = normalizeNamespaceColor(namespaceFormColor.value);
  if (namespaceDialogMode.value === "edit") {
    const idx = nextRows.findIndex((it) => String(it?.key || "") === String(namespaceEditingKey.value || ""));
    if (idx < 0) {
      toast.warning(t("settings.local_lib.namespace.not_found"));
      return;
    }
    nextRows[idx] = { key: nextRows[idx].key, color };
  } else {
    if (nextRows.some((it) => String(it?.key || "") === key)) {
      toast.warning(t("settings.local_lib.namespace.duplicate"));
      return;
    }
    nextRows.push({ key, color });
    nextRows.sort((a, b) => String(a.key || "").localeCompare(String(b.key || "")));
  }
  try {
    await persistCustomNamespaces(nextRows);
    toast.success(t("settings.saved_json"));
    namespaceDialogOpen.value = false;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

async function deleteCustomNamespace(row) {
  const key = String(row?.key || "").trim();
  if (!key) return;
  const nextRows = parseCustomNamespaceConfig(customNamespaceDefs.value).filter((it) => String(it?.key || "") !== key);
  try {
    await persistCustomNamespaces(nextRows);
    toast.success(t("settings.saved_json"));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  }
}

async function scanNow() {
  scanning.value = true;
  try {
    const res = await triggerLocalLibScan({ reason: "settings_manual" });
    const r = res?.result || {};
    resultText.value = `upserts=${r.upserts || 0}, missing=${r.marked_missing || 0}, recovered=${r.recovered || 0}, enriched=${r.enriched || 0}`;
    toast.success(t("settings.local_lib.scan_done"));
    await reloadAll();
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    scanning.value = false;
  }
}

async function clearLocalThumbCacheNow() {
  clearingThumbCache.value = true;
  try {
    const res = await clearLocalThumbCache();
    toast.success(t("settings.local_lib.clear_thumb_cache_done", { n: Number(res?.removed_files || 0), mb: Number(res?.removed_mb || 0) }));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    clearingThumbCache.value = false;
  }
}

function openReadEventsConfirm() {
  confirmReadEventsDialog.value = true;
}

async function confirmClearReadEventsNow() {
  confirmReadEventsDialog.value = false;
  await settingsStore.clearReadEventsAction();
}

// --- rebuild the gallery database ------------------------------------------
// Moved here from the danger zone: it is destructive, but it is gated on the
// administrator password (the same gate the read-events wipe above uses
// server-side), not on the panel-wide unlock switch. The dialog is persistent
// because the password must be typed before it can be dismissed.
//
// The dashboard's cached feed is explicitly emptied afterward: every one of
// those entries now points at a row this call just deleted, and letting the
// store re-fetch on its own would show phantom cards until each request
// happened to land.
const rebuildDialog = ref(false);
const rebuildPassword = ref("");
const rebuilding = ref(false);
const isRecoveryMode = computed(() => appStore.isRecoveryMode);

function openRebuildDialog() {
  rebuildPassword.value = "";
  rebuildDialog.value = true;
}

function closeRebuildDialog() {
  if (rebuilding.value) return;
  rebuildDialog.value = false;
  rebuildPassword.value = "";
}

async function confirmRebuild() {
  if (rebuilding.value) return;
  rebuilding.value = true;
  try {
    const result = await rebuildGalleryDatabase(rebuildPassword.value);
    const dashboard = useDashboardStore();
    for (const state of [dashboard.homeLocal, dashboard.homeLocalFavorite, dashboard.homeHistory, dashboard.homeSearchState]) {
      state.items = [];
      state.cursor = "";
      state.hasMore = false;
    }
    dashboard.mobilePreviewItem = null;
    dashboard.localFolderNodes = [];
    rebuildDialog.value = false;
    toast.success(t("settings.rebuild.done", { count: result.removed }));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    rebuildPassword.value = "";
    rebuilding.value = false;
  }
}

// These two live on the settings store because they were written for the vector
// ingest page; the buttons moved here, so the template reads them through
// wrappers rather than pulling the whole store into scope.
function clearWorksDuplicatesAction() {
  return settingsStore.clearWorksDuplicatesAction();
}

/**
 * Re-read the display preferences from the server.
 *
 * This used to be "reload the two gap lists" (`缺失` + `展平`), both of which are
 * gone: the metadata-gap report now lives only in 工具箱 -> 元数据管理器, and
 * flattening a nested gallery is a one-time migration the scanner handles. What
 * is left to refresh on this page is the set of display preferences, so the
 * button reads them back instead of leaving a no-op.
 */
async function reloadAll() {
  await loadLocalDisplayPrefs();
}

function boolPref(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  return ["1", "true", "yes", "y", "on"].includes(String(value).toLowerCase());
}

async function loadLocalDisplayPrefs() {
  try {
    const cfg = await getConfig();
    const vals = (cfg && cfg.values) || {};
    showJpnTitle.value = boolPref(vals.LOCAL_LIB_SHOW_JPN_TITLE, false);
    useTranslatedTags.value = boolPref(vals.LOCAL_LIB_USE_TRANSLATED_TAGS, true);
    feedMode.value = normalizeFeedMode(vals.LOCAL_LIB_FEED_MODE);
    // The stored value is a string on the wire ("20"), and a hand-edited config
    // could hold a size the endpoint would reject -- both are handled by the
    // store's normaliser rather than by re-parsing here.
    feedPageSize.value = normalizeFeedPageSize(vals.LOCAL_LIB_PAGE_SIZE);
    feedPullToPage.value = boolPref(vals.LOCAL_LIB_PULL_TO_PAGE, false);
  } catch {
    showJpnTitle.value = false;
    useTranslatedTags.value = true;
    feedMode.value = FEED_MODE_INFINITE;
    feedPageSize.value = FEED_DEFAULT_PAGE_SIZE;
    feedPullToPage.value = false;
  }
}

/**
 * Persist the presentation mode and read it back.
 *
 * The read-back matters more here than for the other display preferences: the
 * dashboard normalises whatever it finds, so a write that silently did not land
 * would look like "the setting is on but the feed ignores it". The refresh goes
 * through the shared settings store because that is the copy the dashboard
 * actually reads -- a bare PUT would leave the feed on the old mode until the
 * next full page load.
 */
async function saveFeedDisplayMode() {
  const wanted = {
    LOCAL_LIB_FEED_MODE: normalizeFeedMode(feedMode.value),
    LOCAL_LIB_PAGE_SIZE: normalizeFeedPageSize(feedPageSize.value),
    LOCAL_LIB_PULL_TO_PAGE: !!feedPullToPage.value,
  };
  savingDisplayMode.value = true;
  try {
    const res = await updateConfig(wanted);
    if (res && res.saved_db === false) {
      toast.warning(t("settings.local_lib.save_db_failed", { reason: res.db_error || "n/a" }));
    }
    await settingsStore.loadConfigData();
    const persisted = settingsStore.config || {};
    feedMode.value = normalizeFeedMode(persisted.LOCAL_LIB_FEED_MODE);
    feedPageSize.value = normalizeFeedPageSize(persisted.LOCAL_LIB_PAGE_SIZE);
    feedPullToPage.value = persisted.LOCAL_LIB_PULL_TO_PAGE === true;
    const ok = (
      feedMode.value === wanted.LOCAL_LIB_FEED_MODE
      && feedPageSize.value === wanted.LOCAL_LIB_PAGE_SIZE
      && feedPullToPage.value === wanted.LOCAL_LIB_PULL_TO_PAGE
    );
    if (!ok) toast.warning(t("settings.local_lib.save_not_persisted"));
    return ok;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
    await loadLocalDisplayPrefs();
    return false;
  } finally {
    savingDisplayMode.value = false;
  }
}

function onFeedModeChange(value) {
  const next = normalizeFeedMode(value);
  if (next === feedMode.value) return;
  feedMode.value = next;
  // The page size and the pull flag are kept as they are -- they are not "off"
  // in infinite mode, they are merely not in effect, so flipping back to paged
  // restores the user's earlier choices.
  saveFeedDisplayMode();
}

function onFeedPageSizeChange(value) {
  feedPageSize.value = normalizeFeedPageSize(value);
  if (!feedPagedMode.value) return;
  saveFeedDisplayMode();
}

function onFeedPullToPageToggle(value) {
  feedPullToPage.value = !!value;
  if (!feedPagedMode.value) return;
  saveFeedDisplayMode();
}

function onShowJpnTitleToggle(v) {
  showJpnTitle.value = !!v;
  saveLocalDisplayPrefs();
}

async function onUseTranslatedTagsToggle(v) {
  useTranslatedTags.value = !!v;
  const persisted = await saveLocalDisplayPrefs();
  if (!persisted) return;
  // Switching the representation only changes future ingests; the rows already
  // in the database still hold the old one, so the library has to be rewritten
  // before the switch is actually visible. Without this the user would see the
  // switch flip while every gallery kept the previous tags.
  await startReapplyNow({ mode: useTranslatedTags.value ? "translated" : "raw" });
}

async function saveLocalDisplayPrefs() {
  const wanted = {
    LOCAL_LIB_SHOW_JPN_TITLE: !!showJpnTitle.value,
    LOCAL_LIB_USE_TRANSLATED_TAGS: !!useTranslatedTags.value,
  };
  savingDisplayPrefs.value = true;
  try {
    const res = await updateConfig(wanted);
    if (res && res.saved_db === false) {
      toast.warning(t("settings.local_lib.save_db_failed", { reason: res.db_error || "n/a" }));
    }
    // Read back what actually persisted: without this a failed write would be
    // masked by the optimistic local switch state and look like "won't save".
    await loadLocalDisplayPrefs();
    const persisted = {
      LOCAL_LIB_SHOW_JPN_TITLE: !!showJpnTitle.value,
      LOCAL_LIB_USE_TRANSLATED_TAGS: !!useTranslatedTags.value,
    };
    const ok = (
      persisted.LOCAL_LIB_SHOW_JPN_TITLE === wanted.LOCAL_LIB_SHOW_JPN_TITLE
      && persisted.LOCAL_LIB_USE_TRANSLATED_TAGS === wanted.LOCAL_LIB_USE_TRANSLATED_TAGS
    );
    if (!ok) {
      toast.warning(t("settings.local_lib.save_not_persisted"));
    }
    return ok;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
    await loadLocalDisplayPrefs();
    return false;
  } finally {
    savingDisplayPrefs.value = false;
  }
}

function stopReapplyPolling() {
  if (reapplyTimer) {
    clearInterval(reapplyTimer);
    reapplyTimer = null;
  }
}

async function loadReapplyStatus(mode = "") {
  try {
    const res = await getTagReapplyStatus(mode);
    reapplyState.value = { ...blankReapplyState(), ...(res || {}) };
    const pending = res?.pending;
    if (pending !== null && pending !== undefined) reapplyPending.value = Number(pending || 0);
  } catch {
    // A status probe must never break the settings page.
  }
  return reapplyState.value;
}

function startReapplyPolling() {
  stopReapplyPolling();
  reapplyTimer = setInterval(async () => {
    const st = await loadReapplyStatus();
    if (!["running", "cancelling"].includes(String(st.status || ""))) {
      stopReapplyPolling();
      await onReapplySettled(st);
    }
  }, 900);
}

async function onReapplySettled(st) {
  const status = String(st?.status || "");
  if (status === "failed") {
    toast.error(t("settings.local_lib.reapply.job_failed", { error: String(st?.error || "-") }));
  } else if (status === "cancelled") {
    toast.warning(t("settings.local_lib.reapply.cancelled_hint", { updated: reapplyUpdated.value, pending: reapplyPending.value }));
  } else {
    const msg = t("settings.local_lib.reapply.done_hint", {
      updated: reapplyUpdated.value,
      skipped: reapplySkipped.value,
      failed: reapplyFailed.value,
    });
    if (reapplyFailed.value > 0 || reapplySkipped.value > 0) {
      toast.warning(msg);
    } else {
      toast.success(msg);
    }
  }
  // The display preferences are the only server state this page mirrors.
  await reloadAll().catch(() => null);
}

async function startReapplyNow(opts = {}) {
  if (reapplyRunning.value || startingReapply.value) return;
  startingReapply.value = true;
  try {
    const payload = {};
    if (opts.mode) payload.mode = opts.mode;
    if (opts.force) payload.force = true;
    const res = await startTagReapply(payload);
    reapplyState.value = { ...blankReapplyState(), ...(res?.state || {}) };
    reapplyPending.value = reapplyTotal.value;
    translationNeedsReapply.value = false;
    reapplyDialog.value = true;
    startReapplyPolling();
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
    await loadReapplyStatus();
  } finally {
    startingReapply.value = false;
  }
}

async function cancelReapplyNow() {
  cancellingReapply.value = true;
  try {
    const res = await cancelTagReapply();
    reapplyState.value = { ...blankReapplyState(), ...(res?.state || {}) };
    toast.info(t("settings.local_lib.reapply.cancel_requested"));
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    cancellingReapply.value = false;
  }
}

function closeReapplyDialog() {
  reapplyDialog.value = false;
}

const translationTableSizeLabel = computed(() => {
  const n = Number(translationTable.value?.size || 0);
  if (n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
});

async function loadTranslationTableStatus() {
  loadingTranslationTable.value = true;
  try {
    const res = await getTranslationStatus();
    const info = (res && res.manual_file) || {};
    translationTable.value = {
      dir: info.dir || "",
      file_name: info.file_name || "manual_tags.json",
      path: info.path || "",
      exists: !!info.exists,
      size: Number(info.size || 0),
      updated_at: info.updated_at || "-",
      namespaces: Number(info.namespaces || 0),
      tags: Number(info.tags || 0),
    };
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    loadingTranslationTable.value = false;
  }
}

async function onTranslationTablePicked(file) {
  const picked = Array.isArray(file) ? file[0] : file;
  if (!picked) return;
  uploadingTranslationTable.value = true;
  translationTableResultText.value = "";
  try {
    const res = await uploadTranslationFile(picked);
    const msg = t("settings.local_lib.translation.uploaded", { ns: res?.namespaces ?? "-", tags: res?.tags ?? "-" });
    translationTableResultText.value = msg;
    toast.success(msg);
    await loadTranslationTableStatus();
    // Only prompt: replacing the table does not touch the database by itself.
    translationNeedsReapply.value = true;
    await loadReapplyStatus();
  } catch (e) {
    translationTableResultText.value = String(e?.response?.data?.detail || e);
    toast.warning(translationTableResultText.value);
  } finally {
    uploadingTranslationTable.value = false;
    translationTableFile.value = null;
  }
}

async function clearTranslationTable() {
  loadingTranslationTable.value = true;
  try {
    await clearTranslationTableFile();
    translationTableResultText.value = t("settings.local_lib.translation.cleared");
    await loadTranslationTableStatus();
    // Removing the table leaves the already-translated rows as they were.
    translationNeedsReapply.value = true;
    await loadReapplyStatus();
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    loadingTranslationTable.value = false;
  }
}

// Step one of the restore: ask the server what it *would* do. Same endpoint,
// `dry_run` only. The dialog stays count-only; a real run writes the complete
// per-gallery detail to a downloadable server-side log.
async function openRestoreDialog() {
  restoring.value = true;
  restoreDone.value = false;
  try {
    restoreReport.value = await restoreLocalMetadata({ dry_run: true });
    restoreDialog.value = true;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    restoring.value = false;
  }
}

// Step two: the same call without `dry_run`. Re-runnable and idempotent -- a
// second pass adds no history rows and never overwrites a live vector.
async function confirmRestore() {
  restoring.value = true;
  try {
    restoreReport.value = await restoreLocalMetadata({ dry_run: false });
    restoreDone.value = true;
    const restored = Number(restoreReport.value?.restored || 0);
    const matched = Number(restoreReport.value?.matched || 0);
    toast.success(t("settings.local_lib.backup.done", { restored, matched }));
    if (restoreReport.value?.restart_scheduled) {
      // The backend suspends the visual watcher for the restore and restarts
      // the container to hand it back. Reloading here would race the shutdown
      // and surface a spurious network error, so stop at the explanation.
      toast.info(t("settings.local_lib.backup.restarting"));
      return;
    }
    await reloadAll();
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    restoring.value = false;
  }
}

async function openWritebackDialog() {
  writebackBusy.value = true;
  writebackDone.value = false;
  try {
    writebackReport.value = await writebackLocalMetadata({ dry_run: true });
    writebackDialog.value = true;
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    writebackBusy.value = false;
  }
}

// Step two: the same call without `dry_run`. Writing to disk for every gallery is
// not undoable, so the plan is always shown first.
async function runWriteback() {
  writebackBusy.value = true;
  try {
    writebackReport.value = await writebackLocalMetadata({ dry_run: false });
    writebackDone.value = true;
    toast.success(
      t("settings.local_lib.writeback.done_short", {
        n: Number(writebackReport.value?.comicinfo_written || 0),
      }),
    );
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    writebackBusy.value = false;
  }
}

async function downloadRestoreLog() {
  if (!restoreLogId.value) return;
  downloadingRestoreLog.value = true;
  try {
    const blob = await downloadLocalMetadataRestoreLog(restoreLogId.value);
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `zinglib_metadata_restore_${restoreLogId.value}.jsonl`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    toast.warning(String(e?.response?.data?.detail || e));
  } finally {
    downloadingRestoreLog.value = false;
  }
}

onMounted(async () => {
  loadLocalDisplayPrefs().catch(() => null);
  loadTranslationTableStatus().catch(() => null);
  reloadAll().catch(() => null);
  // A job started from another tab (or left running before navigating away)
  // keeps going in the background; reattach to it instead of hiding it.
  const st = await loadReapplyStatus();
  if (["running", "cancelling"].includes(String(st?.status || ""))) {
    reapplyDialog.value = true;
    startReapplyPolling();
  }
});

onUnmounted(() => {
  // The job itself is server-side and keeps running; only the polling stops.
  stopReapplyPolling();
});
</script>

<style scoped>
.namespace-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
}

.namespace-pill {
  border: none !important;
}

.namespace-color-input {
  width: 40px;
  height: 32px;
  border: none;
  background: transparent;
  padding: 0;
  cursor: pointer;
}

.reapply-help-icon {
  cursor: help;
}

/* Paged-only options while infinite scrolling is selected. The controls are
   already `disabled`; this only makes the "not in effect right now" state
   readable at a glance instead of relying on the user noticing a faint label. */
.display-mode-gated {
  opacity: 0.55;
}

.display-mode-page-size {
  max-width: 240px;
}
</style>
