<template>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('dashboard.health') }}</div>
    <v-row>
      <v-col cols="12" md="12">
        <div class="text-body-2 text-medium-emphasis mb-2">{{ t('settings.source', { chain: configMeta.sources || 'db > json > env' }) }}</div>
        <div class="d-flex align-center ga-2 flex-wrap">
          <v-chip :color="dbConnState.color" variant="tonal">{{ dbConnState.label }}</v-chip>
          <v-btn size="small" variant="outlined" color="primary" :loading="dbHealthLoading" @click="refreshDbHealth">{{ t('common.refresh') }}</v-btn>
        </div>
      </v-col>
      <v-col v-if="limitedModeMessages.length" cols="12" md="12">
        <v-alert type="warning" variant="tonal">{{ t('settings.limited_mode.title') }} {{ limitedModeMessages.join(' / ') }}</v-alert>
      </v-col>
    </v-row>
  </v-card>

  <!-- Shown only while the shipped database credentials are still in effect.
       The backend decides that from the resolved config (`meta.security_defaults`)
       because a banner that is always on is a banner nobody reads; it is an
       error, not a warning, precisely because it is rare and actionable. -->
  <v-alert v-if="securityDefaults.in_use" closable type="error" variant="tonal" class="mb-4">
    <div class="text-subtitle-2 font-weight-medium mb-1">{{ t('settings.security.password_risky_title') }}</div>
    <div>{{ t('settings.security.password_reminder') }}</div>
    <div v-if="securityDefaultFields" class="text-caption mt-1">
      {{ t('settings.security.password_default_fields', { fields: securityDefaultFields }) }}
    </div>
  </v-alert>

  <v-card class="pa-4 mb-4">
    <div class="d-flex align-center justify-space-between">
      <div class="text-subtitle-1 font-weight-medium">{{ t('settings.unlock.title') }}</div>
      <v-switch v-model="settingsUnlocked" :color="settingsUnlocked ? 'orange' : 'blue'" inset hide-details @update:model-value="onUnlockChange" />
    </div>
  </v-card>

  <v-dialog v-model="unlockDialog" max-width="400">
    <v-card class="pa-4">
      <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.unlock.dialog_title') }}</div>
      <v-text-field v-model="unlockPassword" :label="t('settings.unlock.password')" type="password" autocomplete="new-password" variant="outlined" />
      <div class="d-flex justify-end ga-2">
        <v-btn variant="text" @click="cancelUnlock">{{ t('settings.unlock.cancel') }}</v-btn>
        <v-btn color="primary" :loading="unlockLoading" @click="confirmUnlock">{{ t('settings.unlock.confirm') }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

  <div class="danger-zone" :class="{ 'danger-zone-locked': !settingsUnlocked }">
  <v-card class="pa-4 mb-4">
    <v-btn color="error" variant="outlined" prepend-icon="mdi-database-refresh-outline" :disabled="!settingsUnlocked || isRecoveryMode" @click="rebuildDialog = true">{{ t('settings.rebuild.title') }}</v-btn>
  </v-card>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3 text-warning">{{ t('settings.danger_zone.title') }}</div>
    <v-row>
      <v-col cols="12" md="4"><v-text-field v-model="config.POSTGRES_HOST" :label="t('settings.pg.host')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" /></v-col>
      <v-col cols="12" md="2"><v-text-field v-model="config.POSTGRES_PORT" :label="t('settings.pg.port')" type="number" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" /></v-col>
      <v-col cols="12" md="3"><v-text-field v-model="config.POSTGRES_DB" :label="t('settings.pg.db')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" /></v-col>
      <v-col cols="12" md="3"><v-text-field v-model="config.POSTGRES_USER" :label="t('settings.pg.user')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.POSTGRES_PASSWORD" :label="t('settings.pg.password')" type="password" autocomplete="new-password" :placeholder="t('settings.secret.keep')" :hint="secretHint('POSTGRES_PASSWORD')" persistent-hint variant="outlined" density="compact" color="primary" :disabled="!settingsUnlocked" /></v-col>
      <v-col cols="12" md="6"><v-select v-model="config.POSTGRES_SSLMODE" :items="['disable','allow','prefer','require','verify-ca','verify-full']" :label="t('settings.pg.sslmode')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" /></v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.urls') }}</div>
    <v-row>
      <v-col cols="12" md="12"><v-text-field v-model="config.OPENAI_HEALTH_URL" :label="t('settings.openai.health')" variant="outlined" density="compact" color="primary" hide-details /></v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.account') }}</div>
    <v-row>
      <v-col cols="12" md="6"><v-text-field v-model="accountForm.username" :label="t('auth.username')" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="6" class="d-flex align-center"><v-btn color="primary" variant="outlined" @click="updateAccountUsername" :disabled="isRecoveryMode">{{ t('auth.profile.update_username') }}</v-btn></v-col>
      <v-col v-if="!isRecoveryMode" cols="12" md="4"><v-text-field v-model="accountForm.oldPassword" :label="t('auth.profile.old_password')" type="password" autocomplete="new-password" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-text-field v-model="accountForm.newPassword" :label="t('auth.profile.new_password')" type="password" autocomplete="new-password" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-text-field v-model="accountForm.newPassword2" :label="t('auth.profile.new_password_confirm')" type="password" autocomplete="new-password" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="6" class="d-flex align-center"><v-btn color="warning" variant="outlined" @click="updateAccountPassword">{{ t('auth.profile.change_password') }}</v-btn></v-col>
      <v-col cols="12" md="6" class="d-flex align-center justify-end">
        <v-btn color="error" variant="tonal" @click="deleteAccountNow" :disabled="isRecoveryMode">{{ t('auth.profile.delete_account') }}</v-btn>
      </v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3 text-warning">{{ t('settings.app_config_backup.title') }}</div>
    <div class="text-caption text-medium-emphasis mb-3">{{ t('settings.app_config_backup.hint') }}</div>
    <input ref="appConfigRestoreRef" type="file" accept="application/json,.json" class="d-none" @change="onAppConfigRestoreChange" />
    <div class="d-flex ga-2 flex-wrap">
      <v-btn variant="outlined" color="primary" :disabled="!settingsUnlocked" @click="downloadAppConfigBackupAction">{{ t('settings.app_config_backup.download') }}</v-btn>
      <v-btn variant="outlined" color="warning" :disabled="!settingsUnlocked" @click="appConfigRestoreRef && appConfigRestoreRef.click()">{{ t('settings.app_config_backup.restore') }}</v-btn>
    </div>
  </v-card>
  </div>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.interaction') }}</div>
    <v-row>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.REC_PREVIEW_UI_MODE"
          :items="[
            { title: t('settings.interaction.preview_ui_mode.auto'), value: 'auto' },
            { title: t('settings.interaction.preview_ui_mode.phone'), value: 'phone' },
            { title: t('settings.interaction.preview_ui_mode.tablet'), value: 'tablet' },
            { title: t('settings.interaction.preview_ui_mode.desktop'), value: 'desktop' },
          ]"
          item-title="title"
          item-value="value"
          :label="t('settings.interaction.preview_ui_mode')"
          variant="outlined"
          density="compact"
          color="primary"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.REC_PREVIEW_DRAWER_SIDE"
          :items="[
            { title: t('settings.interaction.preview_drawer_side.right'), value: 'right' },
            { title: t('settings.interaction.preview_drawer_side.left'), value: 'left' },
          ]"
          item-title="title"
          item-value="value"
          :label="t('settings.interaction.preview_drawer_side')"
          variant="outlined"
          density="compact"
          color="primary"
          hide-details
        />
      </v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.appearance') }}</div>
    <v-row>
      <v-col cols="12" md="4"><v-select v-model="config.DATA_UI_THEME_MODE" :items="themeModeOptions" item-title="title" item-value="value" :label="t('settings.ui.theme_mode')" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-select v-model="config.DATA_UI_THEME_PRESET" :items="themeOptions" item-title="title" item-value="value" :label="t('settings.ui.theme_preset')" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-switch v-model="config.DATA_UI_THEME_OLED" :label="t('settings.ui.theme_oled')" color="primary" inset hide-details /></v-col>

      <v-col cols="12" md="4"><v-text-field v-model="config.DATA_UI_THEME_CUSTOM_PRIMARY" :label="t('settings.ui.custom_primary')" type="color" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-text-field v-model="config.DATA_UI_THEME_CUSTOM_SECONDARY" :label="t('settings.ui.custom_secondary')" type="color" variant="outlined" density="compact" color="primary" hide-details /></v-col>
      <v-col cols="12" md="4"><v-text-field v-model="config.DATA_UI_THEME_CUSTOM_ACCENT" :label="t('settings.ui.custom_accent')" type="color" variant="outlined" density="compact" color="primary" hide-details /></v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.runtime') }}</div>
    <v-row>
      <v-col cols="12" md="4">
        <v-autocomplete
          v-model="config.DATA_UI_TIMEZONE"
          :items="timezoneOptions"
          :label="t('settings.ui.timezone')"
          :placeholder="t('settings.ui.timezone_hint')"
          variant="outlined"
          density="compact"
          color="primary"
          hide-details
          auto-select-first
        />
      </v-col>
      <v-col cols="12" md="12">
        <div class="text-caption text-medium-emphasis">Version: {{ appVersion || '-' }}</div>
      </v-col>
      <v-col cols="12" md="12" class="d-flex align-center ga-2 flex-wrap">
        <v-chip variant="tonal" color="secondary">{{ t('settings.model.siglip_status', { mb: modelStatus.siglip?.size_mb || 0 }) }}</v-chip>
        <v-chip variant="tonal" :color="modelStatus.runtime_deps?.ready ? 'success' : 'warning'">{{ t('settings.model.runtime_deps', { mb: modelStatus.runtime_deps?.size_mb || 0, ready: modelStatus.runtime_deps?.ready ? 'yes' : 'no' }) }}</v-chip>
        <v-btn variant="outlined" color="primary" @click="downloadSiglipAction">{{ t('settings.model.siglip_download') }}</v-btn>
        <v-btn variant="outlined" color="error" @click="clearSiglipAction">{{ t('settings.model.siglip_clear') }}</v-btn>
        <v-btn variant="outlined" color="warning" @click="clearRuntimeDepsAction">{{ t('settings.model.runtime_deps_clear') }}</v-btn>
        <v-chip v-if="siglipDownload.status" variant="outlined">{{ t('settings.model.siglip_task', { status: siglipDownload.status, stage: siglipDownload.stage || '-' }) }}</v-chip>
      </v-col>
      <v-col cols="12" md="12" v-if="siglipDownload.status && siglipDownload.status !== 'done'">
        <v-progress-linear :model-value="Number(siglipDownload.progress || 0)" color="primary" height="14">
          <template #default>{{ Number(siglipDownload.progress || 0) }}%</template>
        </v-progress-linear>
        <div class="text-caption text-medium-emphasis mt-1" v-if="siglipDownload.error">{{ siglipDownload.error }}</div>
      </v-col>
      <v-col cols="12" md="12" v-if="Array.isArray(siglipDownload.logs) && siglipDownload.logs.length">
        <div class="model-log-view mono">{{ siglipDownload.logs.slice(-8).join('\n') }}</div>
      </v-col>
    </v-row>
  </v-card>
  <v-dialog v-model="rebuildDialog" max-width="520" persistent>
    <v-card>
      <v-card-title>{{ t('settings.rebuild.title') }}</v-card-title>
      <v-card-text>
        <p class="mb-4">{{ t('settings.rebuild.confirm') }}</p>
        <v-text-field v-model="rebuildPassword" :label="t('auth.password')" type="password" autocomplete="current-password" :disabled="rebuilding" />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :disabled="rebuilding" @click="rebuildDialog = false; rebuildPassword = ''">{{ t('common.cancel') }}</v-btn>
        <v-btn color="error" :loading="rebuilding" :disabled="!rebuildPassword" @click="confirmRebuild">{{ t('settings.rebuild.title') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>

<script>
import { computed, onMounted, ref, watch } from "vue";
import { useSettingsStore } from "../../stores/settingsStore";
import { useAppStore } from "../../stores/appStore";
import { useDashboardStore } from "../../stores/dashboardStore";
import { verifyPassword, rebuildGalleryDatabase } from "../../api";

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const appStore = useAppStore();
    const isRecoveryMode = computed(() => appStore.isRecoveryMode);

    const settingsUnlocked = ref(false);
    const unlockDialog = ref(false);
    const unlockPassword = ref("");
    const unlockLoading = ref(false);
    const unlockPending = ref(false);
    const appVersion = ref("");
    const rebuildDialog = ref(false);
    const rebuildPassword = ref("");
    const rebuilding = ref(false);
    async function confirmRebuild() {
      if (rebuilding.value) return;
      rebuilding.value = true;
      try {
        const result = await rebuildGalleryDatabase(rebuildPassword.value);
        const dashboard = useDashboardStore();
        for (const state of [dashboard.homeLocal, dashboard.homeLocalFavorite, dashboard.homeHistory, dashboard.homeSearchState]) {
          state.items = [];
          state.cursor = '';
          state.hasMore = false;
        }
        dashboard.mobilePreviewItem = null;
        dashboard.localFolderNodes = [];
        rebuildDialog.value = false;
        settingsStore.notify(tt('settings.rebuild.done', { count: result.removed }), 'success');
      } catch (e) {
        settingsStore.notify(String(e?.response?.data?.detail || e), 'warning');
      } finally {
        rebuildPassword.value = '';
        rebuilding.value = false;
      }
    }
    const tt = (key, vars = {}) => settingsStore.t(key, vars);

    const dbConnState = computed(() => {
      const db = settingsStore.dbHealth || {};
      if (db.ok === true) {
        return { label: tt("health.db.available"), color: "success" };
      }
      if (db.ok === false) {
        const msg = String(db.error || "").trim();
        return { label: msg ? `${tt("health.db.unavailable")} (${msg})` : tt("health.db.unavailable"), color: "error" };
      }
      return { label: tt("health.db.unavailable"), color: "warning" };
    });

    // Which shipped default credentials are still in use, decided by the backend
    // from the resolved config (see `/api/config` -> meta.security_defaults).
    const securityDefaults = computed(() => settingsStore.configMeta?.security_defaults || {});
    const securityDefaultFields = computed(() => {
      const fields = Array.isArray(securityDefaults.value.fields) ? securityDefaults.value.fields : [];
      return fields.map((name) => tt(`settings.security.field.${name}`)).join(" / ");
    });

    settingsUnlocked.value = appStore.isRecoveryMode;

    watch(() => appStore.isRecoveryMode, (isRecovery) => {
      if (isRecovery) {
        settingsUnlocked.value = true;
      }
    });

    onMounted(async () => {
      if (settingsStore.dbHealth?.ok === null || settingsStore.dbHealth?.ok === undefined) {
        await settingsStore.refreshDbHealth();
      }
      const embeddedVersion = typeof __APP_VERSION__ !== "undefined" ? String(__APP_VERSION__ || "").trim() : "";
      try {
        const res = await fetch("/version.json", { cache: "no-store" });
        if (!res.ok) {
          appVersion.value = embeddedVersion;
          return;
        }
        const data = await res.json();
        appVersion.value = String(data?.version || "").trim() || embeddedVersion;
      } catch {
        appVersion.value = embeddedVersion;
      }
    });

    function onUnlockChange(val) {
      if (!val) {
        settingsUnlocked.value = false;
        return;
      }
      if (!isRecoveryMode.value) {
        settingsUnlocked.value = false;
        unlockDialog.value = true;
        unlockPending.value = true;
      }
    }

    function cancelUnlock() {
      unlockDialog.value = false;
      unlockPassword.value = "";
      if (unlockPending.value) {
        settingsUnlocked.value = false;
        unlockPending.value = false;
      }
    }

    async function confirmUnlock() {
      unlockLoading.value = true;
      try {
        await verifyPassword(appStore.authUser.username, unlockPassword.value);
        settingsUnlocked.value = true;
        unlockDialog.value = false;
        unlockPassword.value = "";
        unlockPending.value = false;
      } catch (e) {
        settingsStore.notify(String(e?.response?.data?.detail || e), "warning");
      } finally {
        unlockLoading.value = false;
      }
    }

    return {
      ...settingsStore,
      isRecoveryMode,
      settingsUnlocked,
      unlockDialog,
      unlockPassword,
      unlockLoading,
      dbConnState,
      securityDefaults,
      securityDefaultFields,
      appVersion,
      rebuildDialog, rebuildPassword, rebuilding, confirmRebuild,
      onUnlockChange,
      cancelUnlock,
      confirmUnlock,
    };
  },
};
</script>

<style scoped>
.danger-zone {
  border: 2px solid #fbc02d;
  border-radius: 12px;
  padding: 8px;
  margin-bottom: 16px;
  background: rgba(251, 192, 45, 0.08);
}

.danger-zone-locked {
  opacity: 0.6;
  pointer-events: none;
}
</style>
