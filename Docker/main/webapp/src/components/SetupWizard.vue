<template>
  <v-dialog :model-value="app.showSetupWizard" persistent fullscreen :transition="false">
    <v-card class="setup-wizard-wrap pa-4" variant="flat">
      <div v-if="step > 0" class="text-h6 font-weight-bold mb-1">{{ t('setup.title') }}</div>
      <div v-if="step > 0" class="text-body-2 text-medium-emphasis mb-4">{{ t('setup.subtitle') }}</div>

      <v-defaults-provider :defaults="wizardFieldDefaults">
      <v-window v-model="step" class="mb-3">
        <v-window-item :value="0">
          <div
            class="setup-welcome d-flex flex-column align-center justify-center text-center"
            @mousemove="onWelcomeMouseMove"
            @mouseleave="onWelcomeMouseLeave"
          >
            <div class="hello-cloud" aria-hidden="true">
              <span v-for="(w, idx) in helloCloud" :key="`hello-${idx}`" class="hello-word" :style="helloWordStyle(w)">{{ w.text }}</span>
            </div>
            <div class="setup-welcome-foreground">
              <img :src="brandLogo" alt="ZingLib" class="setup-welcome-logo mb-4" />
              <div class="text-h4 font-weight-bold mb-6">ZingLib</div>
              <v-btn icon size="x-large" color="primary" class="setup-welcome-next" @click="step = 1">
                <v-icon size="30">mdi-arrow-right</v-icon>
              </v-btn>
            </div>
          </div>
        </v-window-item>

        <v-window-item :value="1">
          <div class="text-subtitle-1 mb-1">{{ t('setup.step.ui') }}</div>
          <div class="text-body-2 text-medium-emphasis mb-3">{{ t('setup.ui.hint') }}</div>
          <v-row>
            <v-col cols="12" md="4">
              <v-select
                v-model="setupForm.DATA_UI_LANG"
                :items="layout.langOptions"
                item-title="title"
                item-value="value"
                :label="t('settings.ui.lang')"
              />
            </v-col>
            <v-col cols="12" md="4">
              <v-autocomplete
                v-model="setupForm.DATA_UI_TIMEZONE"
                :items="settings.timezoneOptions"
                :label="t('settings.ui.timezone')"
                :placeholder="t('settings.ui.timezone_hint')"
                auto-select-first
              />
            </v-col>
            <v-col cols="12" md="4"><v-select v-model="setupForm.DATA_UI_THEME_MODE" :items="settings.themeModeOptions" item-title="title" item-value="value" :label="t('settings.ui.theme_mode')" /></v-col>
            <v-col cols="12" md="6"><v-select v-model="setupForm.DATA_UI_THEME_PRESET" :items="settings.themeOptions" item-title="title" item-value="value" :label="t('settings.ui.theme_preset')" /></v-col>
            <v-col cols="12" md="6"><v-switch v-model="setupForm.DATA_UI_THEME_OLED" :label="t('settings.ui.theme_oled')" color="primary" inset hide-details /></v-col>
          </v-row>
        </v-window-item>

        <v-window-item :value="2">
          <div class="text-subtitle-1 mb-3">{{ t('setup.step.db') }}</div>
          <v-row>
            <v-col cols="12" md="4"><v-text-field v-model="setupForm.POSTGRES_HOST" :label="t('settings.pg.host')" /></v-col>
            <v-col cols="12" md="2"><v-text-field v-model="setupForm.POSTGRES_PORT" :label="t('settings.pg.port')" type="number" /></v-col>
            <v-col cols="12" md="3"><v-text-field v-model="setupForm.POSTGRES_DB" :label="t('settings.pg.db')" /></v-col>
            <v-col cols="12" md="3"><v-text-field v-model="setupForm.POSTGRES_USER" :label="t('settings.pg.user')" /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.POSTGRES_PASSWORD" :label="t('settings.pg.password')" type="password" autocomplete="new-password" /></v-col>
            <v-col cols="12" md="6"><v-select v-model="setupForm.POSTGRES_SSLMODE" :items="['disable','allow','prefer','require','verify-ca','verify-full']" :label="t('settings.pg.sslmode')" /></v-col>
          </v-row>
          <div class="d-flex ga-2 align-center">
            <v-btn color="primary" variant="outlined" :loading="setupBusy" @click="validateSetupDbStep">{{ t('setup.validate_db') }}</v-btn>
            <v-chip :color="setupDbValid ? 'success' : 'default'" variant="tonal">{{ setupDbValid ? t('setup.valid') : t('setup.pending') }}</v-chip>
          </div>
        </v-window-item>

        <v-window-item v-if="showAdminCreateStep" :value="3">
          <div class="text-subtitle-1 mb-3">{{ t('setup.step.admin') }}</div>
          <v-alert v-if="adminAlreadyConfigured" type="info" variant="tonal" class="mb-3">{{ t('setup.admin.already_configured') }}</v-alert>
          <v-row v-else>
            <v-col cols="12"><div class="text-body-2 text-medium-emphasis">{{ t('setup.admin.hint') }}</div></v-col>
            <v-col cols="12" md="4"><v-text-field v-model="setupForm.ADMIN_USERNAME" :label="t('auth.username')" autocomplete="username" /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model="setupForm.ADMIN_PASSWORD" :label="t('auth.password')" type="password" autocomplete="new-password" /></v-col>
            <v-col cols="12" md="4"><v-text-field v-model="setupForm.ADMIN_PASSWORD2" :label="t('auth.password_confirm')" type="password" autocomplete="new-password" /></v-col>
            <v-col cols="12">
              <v-checkbox v-model="setupForm.AUTO_DOWNLOAD_SIGLIP" :label="t('setup.siglip.auto_download')" color="primary" hide-details />
            </v-col>
            <v-col cols="12" v-if="!setupForm.AUTO_DOWNLOAD_SIGLIP">
              <v-alert type="warning" variant="tonal">{{ t('setup.siglip.skip_warning') }}</v-alert>
            </v-col>
            <v-col cols="12" class="d-flex ga-2 align-center">
              <v-btn color="primary" variant="outlined" :loading="setupBusy" @click="createAdminInSetup">{{ t('auth.register.submit') }}</v-btn>
              <v-chip :color="setupAdminValid ? 'success' : 'default'" variant="tonal">{{ setupAdminValid ? t('setup.valid') : t('setup.pending') }}</v-chip>
            </v-col>
          </v-row>
        </v-window-item>

        <v-window-item :value="4">
          <div class="text-subtitle-1 mb-3">{{ t('setup.step.local_library') }}</div>
          <v-alert type="info" variant="tonal">{{ t('setup.local_library.hint') }}</v-alert>

          <!-- An empty library on first run is the most common dead end, so this
               step points at the uploader explicitly. The upload itself lives in
               the toolbox file manager, not here -- handing over the path is
               honest; a button that pretends the wizard can do it is not. -->
          <div class="d-flex align-center ga-2 flex-wrap mt-4 mb-2">
            <v-btn color="primary" variant="flat" prepend-icon="mdi-upload" @click="goToUploaderFromWizard">
              {{ t('setup.local_library.upload') }}
            </v-btn>
            <span class="text-body-2 text-medium-emphasis">{{ t('setup.local_library.upload_where') }}</span>
          </div>
          <v-alert type="info" variant="tonal" density="comfortable" class="mb-4">
            {{ t('setup.local_library.upload_after') }}
          </v-alert>

          <!-- Restoring before the first scan is the whole point of offering it
               here: the vectors land in the database, and the scan that follows
               only has to fill in what the backups did not cover. -->
          <v-divider class="my-4" />
          <div class="text-subtitle-2 font-weight-medium mb-1">{{ t('setup.local_library.restore_title') }}</div>
          <div class="text-body-2 text-medium-emphasis mb-3">{{ t('setup.local_library.restore_hint') }}</div>
          <div class="d-flex align-center ga-2 flex-wrap mb-3">
            <v-btn
              color="primary"
              variant="tonal"
              prepend-icon="mdi-backup-restore"
              :loading="restoring"
              @click="previewGalleryRestore"
            >
              {{ t('setup.local_library.restore') }}
            </v-btn>
            <v-btn
              v-if="restoreStage === 'preview'"
              color="success"
              :loading="restoring"
              @click="runGalleryRestore"
            >
              {{ t('settings.local_lib.backup.confirm') }}
            </v-btn>
          </div>
          <v-alert v-if="restoreError" type="error" variant="tonal" density="comfortable">
            {{ restoreError }}
          </v-alert>
          <v-alert v-else-if="restoreStage === 'none'" type="info" variant="tonal" density="comfortable">
            {{ t('setup.local_library.restore_none') }}
          </v-alert>
          <v-alert v-else-if="restoreStage" type="success" variant="tonal" density="comfortable">
            <div>
              {{ t('setup.local_library.restore_done', {
                total: restoreTotals.total,
                matched: restoreTotals.matched,
                restored: restoreTotals.restored,
                missing: restoreTotals.missing,
              }) }}
            </div>
            <div v-if="restoreTotals.missing" class="mt-2 text-caption">
              {{ t('settings.local_lib.backup.missing_title', { n: restoreTotals.missing }) }}
            </div>
            <v-btn
              v-if="restoreStage === 'done' && restoreLogId"
              class="mt-3"
              size="small"
              variant="tonal"
              prepend-icon="mdi-download"
              :loading="downloadingRestoreLog"
              @click="downloadRestoreLog"
            >
              {{ t('settings.local_lib.backup.download_log') }}
            </v-btn>
          </v-alert>
        </v-window-item>

        <v-window-item :value="6">
          <div class="text-subtitle-1 mb-3">{{ t('setup.step.ingest') }}</div>
          <v-alert type="warning" variant="tonal" class="mb-3">{{ t('setup.optional_limited') }}</v-alert>
          <div class="d-flex ga-2 align-center mb-3">
            <v-btn color="primary" :loading="siglipDownloading" @click="settings.downloadSiglipAction">{{ t('settings.model.siglip_download') }}</v-btn>
            <v-chip variant="tonal" :color="settings.modelStatus.siglip?.usable ? 'success' : 'warning'">{{ settings.modelStatus.siglip?.usable ? t('setup.valid') : t('setup.pending') }}</v-chip>
            <v-chip variant="outlined">{{ Number(settings.siglipDownload.progress || 0) }}%</v-chip>
          </div>
          <v-row>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.INGEST_API_BASE" :label="t('settings.provider.ingest_api_base')" /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.INGEST_API_KEY" :label="t('settings.provider.ingest_api_key')" type="password" autocomplete="new-password" /></v-col>
            <v-col cols="12" md="6"><v-combobox v-model="setupForm.INGEST_VL_MODEL" :items="setupIngestModelOptions" :label="t('settings.provider.ingest_vl_model')" clearable /></v-col>
            <v-col cols="12" md="6"><v-combobox v-model="setupForm.INGEST_EMB_MODEL" :items="setupIngestModelOptions" :label="t('settings.provider.ingest_emb_model')" clearable /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.INGEST_VL_MODEL_CUSTOM" :label="t('settings.provider.ingest_vl_model_custom')" /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.INGEST_EMB_MODEL_CUSTOM" :label="t('settings.provider.ingest_emb_model_custom')" /></v-col>
          </v-row>
        </v-window-item>

        <v-window-item :value="7">
          <div class="text-subtitle-1 mb-3">{{ t('setup.step.llm') }}</div>
          <v-alert type="warning" variant="tonal" class="mb-3">{{ t('setup.optional_llm') }}</v-alert>
          <v-row>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.LLM_API_BASE" :label="t('settings.provider.llm_api_base')" /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.LLM_API_KEY" :label="t('settings.provider.llm_api_key')" type="password" autocomplete="new-password" /></v-col>
            <v-col cols="12" md="6"><v-combobox v-model="setupForm.LLM_MODEL" :items="setupLlmModelOptions" :label="t('settings.provider.llm_model')" clearable /></v-col>
            <v-col cols="12" md="6"><v-combobox v-model="setupForm.EMB_MODEL" :items="setupLlmModelOptions" :label="t('settings.provider.emb_model')" clearable /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.LLM_MODEL_CUSTOM" :label="t('settings.provider.llm_model_custom')" /></v-col>
            <v-col cols="12" md="6"><v-text-field v-model="setupForm.EMB_MODEL_CUSTOM" :label="t('settings.provider.emb_model_custom')" /></v-col>
          </v-row>
        </v-window-item>

        <v-window-item :value="8">
          <div class="text-h6 font-weight-bold mb-2">{{ t('setup.done.title') }}</div>
          <div class="text-body-2 text-medium-emphasis">{{ t('setup.done.desc') }}</div>
        </v-window-item>

        <v-window-item :value="9">
          <div class="text-h6 font-weight-bold mb-2">{{ t('setup.recovery.title') }}</div>
          <v-alert type="warning" variant="tonal" class="mb-3">{{ t('setup.recovery.warning') }}</v-alert>
          <div class="recovery-codes-list mb-3">
            <div v-for="(code, idx) in recoveryCodes" :key="idx" class="recovery-code-item">{{ code }}</div>
          </div>
          <v-btn color="primary" variant="outlined" @click="copyRecoveryCodes">{{ t('setup.recovery.copy') }}</v-btn>
        </v-window-item>
      </v-window>
      </v-defaults-provider>

      <div class="d-flex justify-space-between" v-if="step > 0">
        <div class="d-flex ga-2">
          <v-btn variant="text" :disabled="step <= 0" @click="goSetupPrev">{{ t('setup.prev') }}</v-btn>
          <v-btn v-if="canAbortWizard" variant="text" color="warning" @click="cancelSetupWizard">{{ t('setup.cancel') }}</v-btn>
        </div>
        <v-btn v-if="step < 8" color="primary" :disabled="(step === 2 && !setupDbValid) || (step === 3 && showAdminCreateStep && !setupAdminValid)" :loading="setupBusy" @click="goSetupNext(step)">{{ t('setup.next') }}</v-btn>
        <v-btn v-else-if="step === 8" color="success" :loading="setupBusy" @click="finishSetupWizard">{{ t('setup.finish') }}</v-btn>
        <v-btn v-else color="primary" @click="closeRecoveryStep">{{ t('setup.recovery.acknowledge') }}</v-btn>
      </div>
    </v-card>
  </v-dialog>

</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { completeSetup, downloadLocalMetadataRestoreLog, getAuthBootstrap, getProviderModels, getSetupStatus, registerAdmin, restoreLocalMetadata, setCsrfToken, validateSetupDb } from "../api";
import { useAppStore } from "../stores/appStore";
import { useLayoutStore } from "../stores/layoutStore";
import { useSettingsStore } from "../stores/settingsStore";
import { apiErrorMessage, MIN_PASSWORD_LENGTH, MIN_USERNAME_LENGTH } from "../utils/apiErrors";
// Served from `public/ico/` so the PWA manifest and the in-app chrome share it.
const brandLogo = "/ico/ZingLibLogo_128.png";

const { t } = defineProps({ t: { type: Function, required: true } });

const app = useAppStore();
const router = useRouter();
const layout = useLayoutStore();
const settings = useSettingsStore();

const step = ref(0);
const setupBusy = ref(false);
const setupDbValid = ref(false);
const setupIngestModelOptions = ref([]);
const setupLlmModelOptions = ref([]);
const recoveryCodes = ref([]);
const canAbortWizard = ref(false);
const showAdminCreateStep = ref(true);
const adminAlreadyConfigured = ref(false);
const setupAdminValid = ref(false);
const siglipNoticeArmed = ref(false);
const lastSiglipStatus = ref("");
// Gallery-backup restore, offered on the local-library step. Two stages because
// one endpoint answers both: a count-only dry run previews what would come back,
// and only then does the user commit to the write.
const restoring = ref(false);
const restoreStage = ref(""); // "" | "preview" | "none" | "done"
const restoreReport = ref(null);
const restoreError = ref("");
const downloadingRestoreLog = ref(false);
const restoreLogId = computed(() => String(restoreReport.value?.log_id || "").trim());
const restoreTotals = computed(() => ({
  total: Number(restoreReport.value?.total_galleries || 0),
  matched: Number(restoreReport.value?.matched || 0),
  restored: Number(restoreReport.value?.restored || 0),
  missing: Number(restoreReport.value?.no_sidecar_count || 0),
}));

async function previewGalleryRestore() {
  restoring.value = true;
  restoreError.value = "";
  try {
    const report = await restoreLocalMetadata({ dry_run: true });
    restoreReport.value = report;
    restoreStage.value = Number(report?.sidecars || 0) > 0 ? "preview" : "none";
  } catch (e) {
    restoreReport.value = null;
    restoreStage.value = "";
    restoreError.value = String(e?.response?.data?.detail || e);
  } finally {
    restoring.value = false;
  }
}

async function runGalleryRestore() {
  restoring.value = true;
  restoreError.value = "";
  try {
    restoreReport.value = await restoreLocalMetadata({ dry_run: false });
    restoreStage.value = "done";
    // The backend suspends the visual watcher for the restore and then restarts
    // the container to bring it back; say so, because the page is about to stop
    // responding and that otherwise looks like the restore killed the app.
    if (restoreReport.value?.restart_scheduled) {
      settings.notify(t("settings.local_lib.backup.restarting"), "info");
    }
  } catch (e) {
    restoreError.value = String(e?.response?.data?.detail || e);
  } finally {
    restoring.value = false;
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
    restoreError.value = String(e?.response?.data?.detail || e);
  } finally {
    downloadingRestoreLog.value = false;
  }
}
const helloCloudFocus = ref({ x: 50, y: 50 });
const helloCloudFocusTo = ref({ x: 50, y: 50 });
const isMouseActive = ref(false);
let helloCloudRaf = 0;
let helloCloudT0 = 0;
let mouseTimeout = null;
const pureHelloWords = [
  "Hello", "你好", "こんにちは", "안녕하세요", "Bonjour", "Hola", "Hallo",
  "Ciao", "Привет", "Olá", "مرحبا", "नमस्ते", "שָׁלוֹם", "Sawubona",
  "Merhaba", "Γεια σας", "Hej", "Ahoj", "Hei", "Moi", "Cześć",
  "Szia", "Buna", "Salut", "Halo", "Sveiki", "Përshëndetje",
  "Aloha", "Kamusta", "Xin chào", "Salam", "Barev", "Kaixo",
  "Gamarjoba", "Slav", "Namaste", "Mingalaba", "Sabaidi",
  "Sua s'dei", "Kumusta", "Sveiks", "Tere", "Goeiedag", "Dobrý den",
  "Halló", "Terve", "Saluton", "God dag", "Ahalan"
];
const denseWords = [...pureHelloWords, ...pureHelloWords].sort(() => Math.random() - 0.5);
const rawCloud = Array.from({ length: denseWords.length }).map((_, idx) => {
  const cols = 11;
  const rows = Math.ceil(denseWords.length / cols);
  const row = Math.floor(idx / cols);
  const col = idx % cols;
  const xOffset = (row % 2 === 0) ? 0 : (100 / cols / 2);
  const baseX = (col / (cols - 1)) * 120 - 10 + xOffset;
  const baseY = (row / (rows - 1)) * 120 - 10;
  const jx = (Math.random() - 0.5) * 6;
  const jy = (Math.random() - 0.5) * 6;
  return {
    text: denseWords[idx],
    x: baseX + jx,
    y: baseY + jy,
    baseSize: 12 + Math.random() * 4
  };
});
const helloCloud = rawCloud.filter(item => {
  const dx = Math.abs(item.x - 50);
  const dy = Math.abs(item.y - 50);
  const inSafeZone = (dx < 16) && (dy < 22);
  return !inSafeZone;
});

const wizardFieldDefaults = {
  VTextField: { variant: "outlined", density: "comfortable", color: "primary" },
  VSelect: { variant: "outlined", density: "comfortable", color: "primary" },
  VCombobox: { variant: "outlined", density: "comfortable", color: "primary" },
  VTextarea: { variant: "outlined", density: "comfortable", color: "primary" },
};
const setupForm = reactive({
  DATA_UI_LANG: "zh",
  DATA_UI_TIMEZONE: "UTC",
  DATA_UI_THEME_MODE: "system",
  DATA_UI_THEME_PRESET: "modern",
  DATA_UI_THEME_OLED: false,
  POSTGRES_HOST: "localhost",
  POSTGRES_PORT: 5432,
  POSTGRES_DB: "lrr_library",
  POSTGRES_USER: "postgres",
  POSTGRES_PASSWORD: "",
  POSTGRES_SSLMODE: "prefer",
  ADMIN_USERNAME: "",
  ADMIN_PASSWORD: "",
  ADMIN_PASSWORD2: "",
  AUTO_DOWNLOAD_SIGLIP: true,
  SIGLIP_MODEL: "google/siglip-so400m-patch14-384",
  INGEST_API_BASE: "",
  INGEST_API_KEY: "",
  INGEST_VL_MODEL: "",
  INGEST_EMB_MODEL: "",
  INGEST_VL_MODEL_CUSTOM: "",
  INGEST_EMB_MODEL_CUSTOM: "",
  LLM_API_BASE: "",
  LLM_API_KEY: "",
  LLM_MODEL: "",
  EMB_MODEL: "",
  LLM_MODEL_CUSTOM: "",
  EMB_MODEL_CUSTOM: "",
});

const siglipDownloading = computed(() => settings.siglipDownload.status && settings.siglipDownload.status !== "done");

function syncUiPreview() {
  const lang = String(setupForm.DATA_UI_LANG || "zh").trim().toLowerCase() === "en" ? "en" : "zh";
  layout.setLangValue(lang);
  settings.config.DATA_UI_LANG = lang;
  settings.config.DATA_UI_TIMEZONE = String(setupForm.DATA_UI_TIMEZONE || "UTC");
  settings.config.DATA_UI_THEME_MODE = String(setupForm.DATA_UI_THEME_MODE || "system");
  settings.config.DATA_UI_THEME_PRESET = String(setupForm.DATA_UI_THEME_PRESET || "modern");
  settings.config.DATA_UI_THEME_OLED = !!setupForm.DATA_UI_THEME_OLED;
}

function onWelcomeMouseMove(e) {
  isMouseActive.value = true;
  const rect = e.currentTarget.getBoundingClientRect();
  const x = ((e.clientX - rect.left) / rect.width) * 100;
  const y = ((e.clientY - rect.top) / rect.height) * 100;
  helloCloudFocusTo.value = { x, y };

  clearTimeout(mouseTimeout);
  mouseTimeout = setTimeout(() => {
    isMouseActive.value = false;
  }, 2000);
}

function onWelcomeMouseLeave() {
  isMouseActive.value = false;
}

function helloWordStyle(item) {
  const dx = item.x - helloCloudFocus.value.x;
  const dy = item.y - helloCloudFocus.value.y;
  const d = Math.sqrt(dx * dx + (dy * 1.5) * (dy * 1.5));
  const sigma = 26;
  const k = Math.exp(-(d * d) / (2 * sigma * sigma));
  const scale = 0.6 + k * 2.8;
  const opacity = 0.08 + k * 0.85;
  const zIndex = Math.floor(k * 100);

  return {
    left: `${item.x}%`,
    top: `${item.y}%`,
    fontSize: `${item.baseSize}px`,
    opacity: opacity.toFixed(3),
    zIndex: zIndex,
    transform: `translate(-50%, -50%) scale(${scale.toFixed(3)})`,
    fontWeight: 700,
  };
}

function _tickHelloCloud(ts) {
  if (!helloCloudT0) helloCloudT0 = ts;
  const t = (ts - helloCloudT0) / 1000;

  if (!isMouseActive.value) {
    const speed = 0.35;
    helloCloudFocusTo.value = {
      x: 50 + Math.sin(t * speed) * 35,
      y: 50 + Math.sin(t * speed * 1.3) * 30,
    };
  }
  helloCloudFocus.value.x += (helloCloudFocusTo.value.x - helloCloudFocus.value.x) * 0.06;
  helloCloudFocus.value.y += (helloCloudFocusTo.value.y - helloCloudFocus.value.y) * 0.06;

  helloCloudRaf = requestAnimationFrame(_tickHelloCloud);
}

async function refreshCanAbortWizard() {
  try {
    const st = await getSetupStatus();
    canAbortWizard.value = !!st?.initialized && !!st?.user_configured;
  } catch {
    canAbortWizard.value = false;
  }
}

async function refreshAdminStepState() {
  try {
    const b = await getAuthBootstrap();
    const configured = !!b?.configured;
    const adminSession = !!b?.is_admin_session;
    showAdminCreateStep.value = !configured || adminSession;
    adminAlreadyConfigured.value = configured;
    setupAdminValid.value = configured;
  } catch {
    showAdminCreateStep.value = true;
    adminAlreadyConfigured.value = false;
    setupAdminValid.value = false;
  }
}

function goSetupPrev() {
  if (step.value === 6) {
    step.value = 4;
    return;
  }
  if (step.value === 4 && !showAdminCreateStep.value) {
    step.value = 2;
    return;
  }
  step.value = Math.max(0, step.value - 1);
}

function applySetupFormToConfig() {
  Object.entries(setupForm).forEach(([k, v]) => {
    settings.config[k] = v;
  });
}

watch(
  () => app.showSetupWizard,
  async (open) => {
    if (!open) return;
    step.value = 0;
    setupDbValid.value = false;
    await refreshCanAbortWizard();
    await refreshAdminStepState();
    await settings.loadConfigData();
    Object.assign(setupForm, {
      DATA_UI_LANG: settings.config.DATA_UI_LANG || layout.lang || setupForm.DATA_UI_LANG,
      DATA_UI_TIMEZONE: settings.config.DATA_UI_TIMEZONE || setupForm.DATA_UI_TIMEZONE,
      DATA_UI_THEME_MODE: settings.config.DATA_UI_THEME_MODE || setupForm.DATA_UI_THEME_MODE,
      DATA_UI_THEME_PRESET: settings.config.DATA_UI_THEME_PRESET || setupForm.DATA_UI_THEME_PRESET,
      DATA_UI_THEME_OLED: !!settings.config.DATA_UI_THEME_OLED,
      POSTGRES_HOST: settings.config.POSTGRES_HOST || setupForm.POSTGRES_HOST,
      POSTGRES_PORT: Number(settings.config.POSTGRES_PORT || setupForm.POSTGRES_PORT),
      POSTGRES_DB: settings.config.POSTGRES_DB || setupForm.POSTGRES_DB,
      POSTGRES_USER: settings.config.POSTGRES_USER || setupForm.POSTGRES_USER,
      POSTGRES_PASSWORD: settings.config.POSTGRES_PASSWORD || "",
      POSTGRES_SSLMODE: settings.config.POSTGRES_SSLMODE || "prefer",
      ADMIN_USERNAME: String(app?.authUser?.username || "").trim(),
      ADMIN_PASSWORD: "",
      ADMIN_PASSWORD2: "",
      AUTO_DOWNLOAD_SIGLIP: true,
      SIGLIP_MODEL: settings.config.SIGLIP_MODEL || setupForm.SIGLIP_MODEL,
      INGEST_API_BASE: settings.config.INGEST_API_BASE || "",
      INGEST_API_KEY: settings.config.INGEST_API_KEY || "",
      INGEST_VL_MODEL: settings.config.INGEST_VL_MODEL || "",
      INGEST_EMB_MODEL: settings.config.INGEST_EMB_MODEL || "",
      INGEST_VL_MODEL_CUSTOM: settings.config.INGEST_VL_MODEL_CUSTOM || "",
      INGEST_EMB_MODEL_CUSTOM: settings.config.INGEST_EMB_MODEL_CUSTOM || "",
      LLM_API_BASE: settings.config.LLM_API_BASE || "",
      LLM_API_KEY: settings.config.LLM_API_KEY || "",
      LLM_MODEL: settings.config.LLM_MODEL || "",
      EMB_MODEL: settings.config.EMB_MODEL || "",
      LLM_MODEL_CUSTOM: settings.config.LLM_MODEL_CUSTOM || "",
      EMB_MODEL_CUSTOM: settings.config.EMB_MODEL_CUSTOM || "",
    });
    syncUiPreview();
  },
  { immediate: true },
);

watch(() => setupForm.DATA_UI_LANG, syncUiPreview);
watch(() => setupForm.DATA_UI_TIMEZONE, syncUiPreview);
watch(() => setupForm.DATA_UI_THEME_MODE, syncUiPreview);
watch(() => setupForm.DATA_UI_THEME_PRESET, syncUiPreview);
watch(() => setupForm.DATA_UI_THEME_OLED, syncUiPreview);
watch(
  () => ({
    status: String(settings.siglipDownload?.status || ""),
    progress: Number(settings.siglipDownload?.progress || 0),
    error: String(settings.siglipDownload?.error || ""),
  }),
  (st) => {
    if (!st.status) return;
    if (st.status === "done") {
      siglipNoticeArmed.value = false;
      if (Array.isArray(layout.notices)) {
        const it = layout.notices.find((x) => x.type === "setup-siglip");
        if (it?.id) layout.dismissNotice(it.id);
      }
      lastSiglipStatus.value = st.status;
      return;
    }
    if (lastSiglipStatus.value === st.status && st.status === "failed") return;
    lastSiglipStatus.value = st.status;
    if (st.status === "failed") {
      layout.pushNotice("setup-siglip", t("setup.siglip.notice_title"), t("setup.siglip.notice_failed", { error: st.error || "unknown error" }));
      settings.notify(t("setup.siglip.failed", { error: st.error || "unknown error" }), "warning");
      siglipNoticeArmed.value = false;
      return;
    }
    siglipNoticeArmed.value = true;
    layout.pushNotice("setup-siglip", t("setup.siglip.notice_title"), t("setup.siglip.notice_running", { progress: st.progress }));
  },
  { deep: true },
);

watch(() => setupForm.INGEST_API_BASE, async () => {
  const base = String(setupForm.INGEST_API_BASE || "").trim();
  if (!base) {
    setupIngestModelOptions.value = [];
    return;
  }
  try {
    const r = await getProviderModels(base, String(setupForm.INGEST_API_KEY || "").trim());
    setupIngestModelOptions.value = Array.isArray(r.models) ? r.models : [];
  } catch {
    setupIngestModelOptions.value = [];
  }
});
watch(() => setupForm.INGEST_API_KEY, async () => {
  const base = String(setupForm.INGEST_API_BASE || "").trim();
  if (!base) return;
  try {
    const r = await getProviderModels(base, String(setupForm.INGEST_API_KEY || "").trim());
    setupIngestModelOptions.value = Array.isArray(r.models) ? r.models : [];
  } catch {
    setupIngestModelOptions.value = [];
  }
});
watch(() => setupForm.LLM_API_BASE, async () => {
  const base = String(setupForm.LLM_API_BASE || "").trim();
  if (!base) {
    setupLlmModelOptions.value = [];
    return;
  }
  try {
    const r = await getProviderModels(base, String(setupForm.LLM_API_KEY || "").trim());
    setupLlmModelOptions.value = Array.isArray(r.models) ? r.models : [];
  } catch {
    setupLlmModelOptions.value = [];
  }
});
watch(() => setupForm.LLM_API_KEY, async () => {
  const base = String(setupForm.LLM_API_BASE || "").trim();
  if (!base) return;
  try {
    const r = await getProviderModels(base, String(setupForm.LLM_API_KEY || "").trim());
    setupLlmModelOptions.value = Array.isArray(r.models) ? r.models : [];
  } catch {
    setupLlmModelOptions.value = [];
  }
});

async function validateSetupDbStep() {
  setupBusy.value = true;
  try {
    const r = await validateSetupDb({
      host: setupForm.POSTGRES_HOST,
      port: Number(setupForm.POSTGRES_PORT || 5432),
      db: setupForm.POSTGRES_DB,
      user: setupForm.POSTGRES_USER,
      password: setupForm.POSTGRES_PASSWORD,
      sslmode: setupForm.POSTGRES_SSLMODE || "prefer",
    });
    setupDbValid.value = !!r.ok;
    settings.notify(r.ok ? t('setup.valid') : String(r.message || 'invalid'), r.ok ? 'success' : 'warning');
    if (r.ok) {
      applySetupFormToConfig();
      await settings.saveConfig();
      await refreshAdminStepState();
    }
  } catch (e) {
    setupDbValid.value = false;
    settings.notify(String(e?.response?.data?.detail || e), 'warning');
  } finally {
    setupBusy.value = false;
  }
}

async function createAdminInSetup() {
  const username = String(setupForm.ADMIN_USERNAME || "").trim();
  const password = String(setupForm.ADMIN_PASSWORD || "");
  const password2 = String(setupForm.ADMIN_PASSWORD2 || "");
  if (!username || !password) {
    settings.notify(String(t("auth.register.hint") || "missing username/password"), "warning");
    return;
  }
  // Answer the two length rules here, so the common mistake never needs a round
  // trip and never surfaces a server message written for developers.
  if (username.length < MIN_USERNAME_LENGTH) {
    settings.notify(t("auth.username_too_short", { n: MIN_USERNAME_LENGTH }), "warning");
    return;
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    settings.notify(t("auth.password_too_short", { n: MIN_PASSWORD_LENGTH }), "warning");
    return;
  }
  if (password !== password2) {
    settings.notify(t("auth.profile.password_mismatch"), "warning");
    return;
  }
  setupBusy.value = true;
  try {
    const res = await registerAdmin(username, password);
    setCsrfToken(res?.session?.csrf_token || "");
    setupAdminValid.value = true;
    settings.notify(t("setup.admin.created"), "success");
    await app.bootstrap();
    await refreshAdminStepState();
  } catch (e) {
    setupAdminValid.value = false;
    settings.notify(apiErrorMessage(e, t), "warning");
  } finally {
    setupBusy.value = false;
  }
}

async function goToUploaderFromWizard() {
  // Uploading galleries lives in the toolbox file manager, not in the wizard, so
  // this persists whatever the wizard has collected, closes it, and lands the
  // user where the uploader actually is. Without it, "your library is empty" is
  // a dead end for anyone who skipped this step.
  try {
    await settings.saveConfig();
  } catch {
    // A wizard that cannot save the config is a problem for the setup step, not
    // for getting the user to the uploader; still take them there.
  }
  app.showSetupWizard = false;
  router.push({ path: "/tools", query: { tab: "file_manager" } }).catch(() => null);
}

async function maybeTriggerSiglipDownload() {
  if (!setupForm.AUTO_DOWNLOAD_SIGLIP) return;
  try {
    await settings.loadModelStatus();
    const hasSiglip = !!settings.modelStatus?.siglip?.usable;
    const hasDeps = !!settings.modelStatus?.runtime_deps?.ready;
    if (hasSiglip && hasDeps) return;
    settings.notify(t("setup.siglip.downloading"), "info");
    siglipNoticeArmed.value = true;
    layout.pushNotice("setup-siglip", t("setup.siglip.notice_title"), t("setup.siglip.notice_running", { progress: Number(settings.siglipDownload.progress || 0) }));
    await settings.downloadSiglipAction();
  } catch (e) {
    settings.notify(String(e?.response?.data?.detail || e), "warning");
  }
}

async function goSetupNext(currentStep) {
  setupBusy.value = true;
  try {
    if ([5, 6, 7].includes(Number(currentStep))) {
      applySetupFormToConfig();
      await settings.saveConfig();
    }
    const cur = Number(currentStep);
    if (cur === 2 && !showAdminCreateStep.value) {
      step.value = 4;
      return;
    }
    if (cur === 4) {
      step.value = 6;
      return;
    }
    if (cur === 3 && showAdminCreateStep.value) {
      await maybeTriggerSiglipDownload();
    }
    step.value = cur + 1;
  } finally {
    setupBusy.value = false;
  }
}

async function finishSetupWizard() {
  setupBusy.value = true;
  try {
    applySetupFormToConfig();
    await settings.saveConfig();
    const result = await completeSetup();
    if (result.recovery_codes && result.recovery_codes.length > 0) {
      recoveryCodes.value = result.recovery_codes;
      step.value = 9;
    } else {
      app.closeSetupWizard();
      settings.notify(t('setup.done.toast'), 'success');
    }
  } catch (e) {
    settings.notify(String(e?.response?.data?.detail || e), 'warning');
  } finally {
    setupBusy.value = false;
  }
}

function closeRecoveryStep() {
  recoveryCodes.value = [];
  app.closeSetupWizard();
  settings.notify(t('setup.done.toast'), 'success');
}

async function cancelSetupWizard() {
  try {
    await settings.loadConfigData();
    if (settings.config.DATA_UI_LANG === "en" || settings.config.DATA_UI_LANG === "zh") {
      layout.setLangValue(settings.config.DATA_UI_LANG);
    }
  } catch {
    // ignore reload failures on cancel
  }
  app.closeSetupWizard();
}

function copyRecoveryCodes() {
  const text = recoveryCodes.value.join('\n');
  navigator.clipboard.writeText(text).then(() => {
    settings.notify(t('setup.recovery.copied'), 'success');
  }).catch(() => {
    settings.notify(t('setup.recovery.copy_failed'), 'warning');
  });
}

onMounted(() => {
  helloCloudRaf = requestAnimationFrame(_tickHelloCloud);
});

onBeforeUnmount(() => {
  if (helloCloudRaf) cancelAnimationFrame(helloCloudRaf);
  helloCloudRaf = 0;
});
</script>

<style scoped>
.setup-wizard-wrap {
  min-height: 100vh;
  background: linear-gradient(160deg, rgba(var(--v-theme-surface), 0.98), rgba(var(--v-theme-background), 0.98));
}

:global(.v-theme--light) .setup-wizard-wrap {
  background: linear-gradient(160deg, rgba(var(--v-theme-background), 0.98), rgba(var(--v-theme-surface), 0.98));
}

.setup-welcome {
  position: relative;
  min-height: calc(100vh - 90px);
  overflow: hidden;
  z-index: 1;
}

.hello-cloud {
  position: absolute;
  inset: 0;
  pointer-events: none;
  user-select: none;
  z-index: 0;
}

.setup-welcome-foreground {
  position: relative;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  background: radial-gradient(closest-side, rgba(var(--v-theme-surface), 0.95) 30%, rgba(var(--v-theme-surface), 0) 100%);
  padding: 60px 80px;
  border-radius: 50%;
  pointer-events: none;
}

:global(.v-theme--light) .setup-welcome-foreground {
  background: radial-gradient(closest-side, rgba(var(--v-theme-surface), 0.96) 34%, rgba(var(--v-theme-surface), 0) 100%);
}
.setup-welcome-logo,
.setup-welcome-next {
  pointer-events: auto;
}

.hello-word {
  position: absolute;
  color: rgba(var(--v-theme-on-surface), 0.85);
  letter-spacing: 0.02em;
  white-space: nowrap;
  will-change: transform, opacity;
}

.setup-welcome-logo {
  width: 96px;
  height: 96px;
  border-radius: 24px;
}

.setup-welcome-next {
  box-shadow: 0 10px 26px rgba(var(--v-theme-primary), 0.35);
}

.first-run-guide-card {
  background: rgba(var(--v-theme-surface), 0.98);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.14);
  box-shadow: 0 20px 56px rgba(0, 0, 0, 0.35);
}

:global(.v-theme--light) .first-run-guide-card {
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.12);
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 16px;
}

.recovery-codes-list {
  background: rgba(var(--v-theme-surface), 0.35);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.2);
  padding: 12px;
  border-radius: 8px;
  max-height: 200px;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.recovery-code-item {
  font-family: monospace;
  font-size: 15px;
  font-weight: 700;
  color: rgb(var(--v-theme-on-surface));
  background: rgba(var(--v-theme-surface-variant), 0.55);
  border: 1px solid rgba(var(--v-theme-on-surface), 0.16);
  border-radius: 8px;
  padding: 10px 12px;
  word-break: break-all;
}

@media (max-width: 700px) {
  .recovery-codes-list {
    grid-template-columns: 1fr;
  }
}
</style>
