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

  <!-- Change password: gate first, then the new value. The two pages are not a
       flourish -- asking for the new password before proving the old one lets a
       typo in the *old* field be reported as a mismatch in the *new* one, which
       sends the user looking in the wrong place.

       The gate has a second mode. Someone who can reach this dialog but cannot
       recall the password still has a recovery code, so ticking "forgot" swaps
       the gate field from "current password" to "recovery code": the code is
       burned on use and the password is rewritten without the old one. The
       switch is only offered on the gate page because it changes what the gate
       *is*, not what the new password is. -->
  <v-dialog v-model="passwordDialog" max-width="440" persistent>
    <v-card>
      <v-card-title class="text-h6">{{ t('auth.profile.change_password') }}</v-card-title>
      <v-card-text>
        <template v-if="passwordStep === 'verify'">
          <v-text-field
            v-if="!passwordUseRecovery"
            v-model="passwordOld"
            :label="t('auth.profile.old_password')"
            type="password"
            autocomplete="current-password"
            variant="outlined"
            :disabled="passwordBusy"
          />
          <v-text-field
            v-else
            v-model="passwordOld"
            :label="t('auth.profile.recovery_code')"
            autocomplete="one-time-code"
            variant="outlined"
            :disabled="passwordBusy"
            prepend-inner-icon="mdi-lifebuoy"
            :hint="t('auth.profile.recovery_code_hint')"
            persistent-hint
          />
          <v-checkbox
            v-model="passwordUseRecovery"
            :label="t('auth.profile.forgot_password')"
            density="compact"
            hide-details
            :disabled="passwordBusy"
            class="mt-2"
            @update:model-value="onForgotToggle"
          />
        </template>
        <template v-else>
          <v-alert v-if="passwordUseRecovery" type="warning" variant="tonal" density="comfortable" class="mb-3">
            {{ t('auth.profile.recovery_code_warning') }}
          </v-alert>
          <v-text-field v-model="passwordNew" :label="t('auth.profile.new_password')" type="password" autocomplete="new-password" variant="outlined" :disabled="passwordBusy" />
          <v-text-field v-model="passwordNew2" :label="t('auth.profile.new_password_confirm')" type="password" autocomplete="new-password" variant="outlined" class="mt-2" :disabled="passwordBusy" />
        </template>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="passwordBusy" @click="closePasswordDialog">{{ t('settings.unlock.cancel') }}</v-btn>
        <v-btn
          v-if="passwordStep === 'verify'"
          color="primary"
          :loading="passwordBusy"
          :disabled="!passwordOld"
          @click="verifyPasswordStep"
        >{{ t('auth.profile.next') }}</v-btn>
        <v-btn
          v-else
          color="primary"
          :loading="passwordBusy"
          :disabled="!passwordNew || !passwordNew2"
          @click="submitPasswordChange"
        >{{ t('auth.profile.done') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="renameDialog" max-width="440" persistent>
    <v-card>
      <v-card-title class="text-h6">{{ t('auth.profile.update_username') }}</v-card-title>
      <v-card-text>
        <v-text-field v-model="renamePassword" :label="t('auth.profile.confirm_gate')" type="password" autocomplete="current-password" variant="outlined" :disabled="renameBusy" />
        <v-text-field v-model="renameNewName" :label="t('auth.profile.new_username')" variant="outlined" class="mt-2" :disabled="renameBusy" />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="renameBusy" @click="closeRenameDialog">{{ t('settings.unlock.cancel') }}</v-btn>
        <v-btn color="primary" :loading="renameBusy" :disabled="!renamePassword || !renameNewName" @click="submitRename">{{ t('auth.profile.done') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <v-dialog v-model="deleteDialog" max-width="460" persistent>
    <v-card>
      <v-card-title class="text-h6">{{ t('auth.profile.delete_account') }}</v-card-title>
      <v-card-text>
        <v-alert type="error" variant="tonal" density="comfortable" class="mb-3">{{ t('auth.profile.delete_warning') }}</v-alert>
        <v-text-field v-model="deletePassword" :label="t('auth.profile.confirm_gate')" type="password" autocomplete="current-password" variant="outlined" :disabled="deleteBusy" />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" :disabled="deleteBusy" @click="closeDeleteDialog">{{ t('settings.unlock.cancel') }}</v-btn>
        <v-btn color="error" :loading="deleteBusy" :disabled="!deletePassword" @click="submitDelete">{{ t('auth.profile.delete_account') }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>

  <!-- The unlock switch sits directly on top of the danger zone it governs.
       It has to stay *outside* the .danger-zone wrapper: that wrapper disables
       pointer events while locked, so a switch placed inside would be unable to
       ever unlock itself again. -->
  <v-card class="pa-4 mb-2">
    <div class="d-flex align-center justify-space-between">
      <div class="text-subtitle-1 font-weight-medium">{{ t('settings.unlock.title') }}</div>
      <v-switch v-model="settingsUnlocked" :color="settingsUnlocked ? 'orange' : 'blue'" inset hide-details @update:model-value="onUnlockChange" />
    </div>
  </v-card>

  <div class="danger-zone" :class="{ 'danger-zone-locked': !settingsUnlocked }">
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3 text-warning">{{ t('settings.danger_zone.title') }}</div>
    <v-alert type="info" variant="tonal" density="comfortable" class="mb-3">{{ t('settings.pg.gate_hint') }}</v-alert>
    <v-row>
      <v-col cols="12" md="4"><v-text-field v-model="config.POSTGRES_HOST" :label="t('settings.pg.host')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
      <v-col cols="12" md="2"><v-text-field v-model="config.POSTGRES_PORT" :label="t('settings.pg.port')" type="number" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
      <v-col cols="12" md="3"><v-text-field v-model="config.POSTGRES_DB" :label="t('settings.pg.db')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
      <v-col cols="12" md="3"><v-text-field v-model="config.POSTGRES_USER" :label="t('settings.pg.user')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.POSTGRES_PASSWORD" :label="t('settings.pg.password')" type="password" autocomplete="new-password" :placeholder="t('settings.secret.keep')" :hint="secretHint('POSTGRES_PASSWORD')" persistent-hint variant="outlined" density="compact" color="primary" :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
      <v-col cols="12" md="6"><v-select v-model="config.POSTGRES_SSLMODE" :items="['disable','allow','prefer','require','verify-ca','verify-full']" :label="t('settings.pg.sslmode')" variant="outlined" density="compact" color="primary" hide-details :disabled="!settingsUnlocked" @update:model-value="onDbFieldChanged" /></v-col>
    </v-row>
    <!-- Two buttons, not one. The connection test writes nothing; the save is
         only reachable once that test has passed for *these* values. A single
         "save" that also probes would still let a typo reach the database,
         because the write is what breaks the container, not the probe. -->
    <div class="d-flex align-center ga-2 flex-wrap mt-3">
      <v-btn color="primary" variant="outlined" :loading="dbGateTesting" :disabled="!settingsUnlocked" @click="testDbGate">{{ t('settings.pg.test_connection') }}</v-btn>
      <v-btn color="success" variant="flat" :loading="dbGateSaving" :disabled="!settingsUnlocked || !dbGateVerified" @click="saveDbGate">{{ t('settings.pg.save_verified') }}</v-btn>
      <v-chip :color="dbGateVerified ? 'success' : 'default'" variant="tonal">{{ dbGateVerified ? t('settings.pg.verified') : t('settings.pg.unverified') }}</v-chip>
    </div>
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

  <!-- The account sits below the danger zone, and outside its locked wrapper:
       every action it offers asks for the current password first, so the
       panel-wide unlock switch buys nothing here and, sitting behind it, only
       made "change my password" look like a destructive operation. It keeps its
       own per-flow gate. -->
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.section.account') }}</div>
    <div class="text-body-2 mb-3">
      {{ t('auth.username') }}:
      <span class="font-weight-medium">{{ authUser.username || '-' }}</span>
    </div>
    <div class="d-flex ga-2 flex-wrap">
      <v-btn color="primary" variant="outlined" prepend-icon="mdi-lock-reset" @click="openPasswordDialog">{{ t('auth.profile.change_password') }}</v-btn>
      <v-btn color="primary" variant="outlined" prepend-icon="mdi-account-edit-outline" :disabled="isRecoveryMode" @click="openRenameDialog">{{ t('auth.profile.update_username') }}</v-btn>
      <v-btn color="error" variant="tonal" prepend-icon="mdi-account-remove-outline" @click="openDeleteDialog">{{ t('auth.profile.delete_account') }}</v-btn>
    </div>
  </v-card>

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
</template>

<script>
import { computed, onMounted, ref, watch } from "vue";
import { useSettingsStore } from "../../stores/settingsStore";
import { useAppStore } from "../../stores/appStore";
import { verifyPassword, validateSetupDb } from "../../api";

/**
 * The database coordinates, in the order the panel binds them.
 *
 * Held as a local constant rather than read from the store so the *view* states
 * what it gates; the store's own NO_AUTOSAVE_KEYS is the enforcement, and
 * `test_v102_interactions.mjs` asserts the two lists agree.
 */
const DB_KEYS = [
  "POSTGRES_HOST",
  "POSTGRES_PORT",
  "POSTGRES_DB",
  "POSTGRES_USER",
  "POSTGRES_PASSWORD",
  "POSTGRES_SSLMODE",
];

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const appStore = useAppStore();
    const isRecoveryMode = computed(() => appStore.isRecoveryMode);
    // The account card renders the name as read-only text, so it needs the
    // store's user object in scope. Using it in the template without exposing it
    // here is a render-time crash (Vue resolves the identifier as undefined and
    // `undefined.username` aborts the whole card), not a build error -- which is
    // exactly how it shipped once.
    const authUser = computed(() => appStore.authUser);

    const settingsUnlocked = ref(false);
    const unlockDialog = ref(false);
    const unlockPassword = ref("");
    const unlockLoading = ref(false);
    const unlockPending = ref(false);
    const appVersion = ref("");

    // --- account flows --------------------------------------------------------
    // Three dialogs, each with its own gate. The fields live here rather than in
    // `appStore.accountForm` on purpose: that ref is a *mirror of the account*
    // (what the panel renders), and a form bound to a mirror is how a
    // half-typed name ends up being the thing that gets written.
    const passwordDialog = ref(false);
    const passwordStep = ref("verify");
    const passwordOld = ref("");
    const passwordNew = ref("");
    const passwordNew2 = ref("");
    const passwordBusy = ref(false);
    // The gate has two credentials; this picks which one the dialog asks for.
    // Kept on the view (like the other dialog fields) so a remount cannot leave
    // a half-typed recovery code behind in a store that outlives the dialog.
    const passwordUseRecovery = ref(false);
    const renameDialog = ref(false);
    const renamePassword = ref("");
    const renameNewName = ref("");
    const renameBusy = ref(false);
    const deleteDialog = ref(false);
    const deletePassword = ref("");
    const deleteBusy = ref(false);

    function openPasswordDialog() {
      passwordStep.value = "verify";
      passwordOld.value = "";
      passwordNew.value = "";
      passwordNew2.value = "";
      passwordUseRecovery.value = false;
      passwordDialog.value = true;
    }

    function closePasswordDialog() {
      passwordDialog.value = false;
      passwordOld.value = "";
      passwordNew.value = "";
      passwordNew2.value = "";
      passwordUseRecovery.value = false;
      passwordStep.value = "verify";
    }

    /**
     * Ticking "forgot password" changes the meaning of the gate field, so a
     * value typed under the old meaning must not be carried over as if the user
     * had typed it for the new one -- that is how a password ends up being
     * submitted where a recovery code was meant, or the reverse.
     */
    function onForgotToggle() {
      passwordOld.value = "";
    }

    async function verifyPasswordStep() {
      if (passwordBusy.value) return;
      passwordBusy.value = true;
      try {
        // Proving a recovery code here would burn it, and the user may still
        // change their mind about the new password -- so on the recovery path
        // the gate is not consumed up front: the code travels with the write
        // and is burned by the server exactly once, in the same call.
        if (passwordUseRecovery.value) {
          passwordStep.value = "new";
          return;
        }
        // The same shared gate the other two flows use, so "wrong password"
        // cannot mean three different things depending on which button opened
        // the dialog.
        const ok = await appStore.verifyCurrentPassword(passwordOld.value);
        if (ok) passwordStep.value = "new";
      } finally {
        passwordBusy.value = false;
      }
    }

    async function submitPasswordChange() {
      if (passwordBusy.value) return;
      passwordBusy.value = true;
      try {
        const ok = await appStore.changeAccountPassword(
          passwordOld.value,
          passwordNew.value,
          passwordNew2.value,
          { useRecoveryCode: passwordUseRecovery.value },
        );
        // On success the account is signed out (the session was issued under the
        // old credential -- and on the recovery path it is revoked outright);
        // closing first keeps the dialog from flashing over the auth gate on the
        // way out.
        if (ok) closePasswordDialog();
      } finally {
        passwordBusy.value = false;
      }
    }

    function openRenameDialog() {
      renamePassword.value = "";
      renameNewName.value = String(accountForm.value.username || "");
      renameDialog.value = true;
    }

    function closeRenameDialog() {
      renameDialog.value = false;
      renamePassword.value = "";
      renameNewName.value = "";
    }

    async function submitRename() {
      if (renameBusy.value) return;
      renameBusy.value = true;
      try {
        const ok = await appStore.renameAccount(renamePassword.value, renameNewName.value);
        if (ok) closeRenameDialog();
      } finally {
        renameBusy.value = false;
      }
    }

    function openDeleteDialog() {
      deletePassword.value = "";
      deleteDialog.value = true;
    }

    function closeDeleteDialog() {
      deleteDialog.value = false;
      deletePassword.value = "";
    }

    async function submitDelete() {
      if (deleteBusy.value) return;
      deleteBusy.value = true;
      try {
        // On success the store has already re-bootstrapped the app into the
        // setup wizard and this component is on its way out, so there is
        // nothing left to restore.
        const ok = await appStore.deleteAccountNow(deletePassword.value);
        if (ok) {
          deleteDialog.value = false;
          deletePassword.value = "";
        }
      } finally {
        deleteBusy.value = false;
      }
    }

    // --- database gate --------------------------------------------------------
    // `verified` is a claim about specific values, not about the panel: it is
    // cleared the moment any of the six fields changes, so "tested then edited
    // the port" cannot save. Storing the tested snapshot (rather than a boolean
    // plus a separate comparison) means the save can send exactly what passed.
    const dbGateVerified = ref(false);
    const dbGateTesting = ref(false);
    const dbGateSaving = ref(false);
    let dbGateSnapshot = null;

    function _dbDraft() {
      return {
        host: String(settingsStore.config.POSTGRES_HOST || "").trim(),
        port: Number(settingsStore.config.POSTGRES_PORT || 5432),
        db: String(settingsStore.config.POSTGRES_DB || "").trim(),
        user: String(settingsStore.config.POSTGRES_USER || "").trim(),
        password: String(settingsStore.config.POSTGRES_PASSWORD || ""),
        sslmode: String(settingsStore.config.POSTGRES_SSLMODE || "prefer"),
      };
    }

    function _sameDraft(a, b) {
      if (!a || !b) return false;
      return a.host === b.host && a.port === b.port && a.db === b.db
        && a.user === b.user && a.password === b.password && a.sslmode === b.sslmode;
    }

    function onDbFieldChanged() {
      // Any edit invalidates the previous pass, even if the user types the same
      // value back: the cheap, predictable rule is worth more here than saving
      // the user a second click.
      if (dbGateVerified.value && !_sameDraft(_dbDraft(), dbGateSnapshot)) {
        dbGateVerified.value = false;
        dbGateSnapshot = null;
      }
    }

    async function testDbGate() {
      if (dbGateTesting.value) return;
      const draft = _dbDraft();
      dbGateTesting.value = true;
      try {
        const r = await validateSetupDb(draft);
        const ok = !!r?.ok;
        dbGateVerified.value = ok;
        dbGateSnapshot = ok ? draft : null;
        settingsStore.notify(
          ok ? String(r?.message || tt("settings.pg.verified")) : String(r?.message || tt("settings.pg.unverified")),
          ok ? "success" : "warning",
        );
      } catch (e) {
        dbGateVerified.value = false;
        dbGateSnapshot = null;
        settingsStore.notify(String(e?.response?.data?.detail || e), "warning");
      } finally {
        dbGateTesting.value = false;
      }
    }

    async function saveDbGate() {
      if (dbGateSaving.value || !dbGateVerified.value) return;
      dbGateSaving.value = true;
      try {
        const ok = await settingsStore.commitConfigKeys(DB_KEYS);
        if (ok) {
          settingsStore.notify(tt("settings.pg.saved"), "success");
          await settingsStore.refreshDbHealth();
          dbGateVerified.value = false;
          dbGateSnapshot = null;
        }
      } finally {
        dbGateSaving.value = false;
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
      authUser,
      settingsUnlocked,
      unlockDialog,
      unlockPassword,
      unlockLoading,
      dbConnState,
      securityDefaults,
      securityDefaultFields,
      appVersion,
      passwordDialog, passwordStep, passwordOld, passwordNew, passwordNew2, passwordBusy, passwordUseRecovery,
      renameDialog, renamePassword, renameNewName, renameBusy,
      deleteDialog, deletePassword, deleteBusy,
      openPasswordDialog, closePasswordDialog, verifyPasswordStep, submitPasswordChange, onForgotToggle,
      openRenameDialog, closeRenameDialog, submitRename,
      openDeleteDialog, closeDeleteDialog, submitDelete,
      onUnlockChange,
      cancelUnlock,
      confirmUnlock,
      dbGateVerified, dbGateTesting, dbGateSaving,
      onDbFieldChanged, testDbGate, saveDbGate,
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
