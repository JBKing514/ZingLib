<template>
  <v-card class="pa-4 mb-4">
    <div class="d-flex align-center justify-space-between mb-3">
      <div class="text-subtitle-1 font-weight-medium">{{ t('settings.tab.data_clean') }}</div>
      <v-btn size="small" variant="tonal" color="primary" :prepend-icon="settingsLocked ? 'mdi-lock' : 'mdi-lock-open-variant'" @click="settingsLocked = !settingsLocked">
        {{ settingsLocked ? t('settings.lock.unlock') : t('settings.lock.lock') }}
      </v-btn>
    </div>
    <v-alert v-if="settingsLocked" type="warning" variant="tonal" class="mb-3">{{ t('settings.lock.hint') }}</v-alert>
    <div :class="{ 'settings-locked': settingsLocked }">
    <v-row>
      <v-col cols="12" md="8"><v-text-field v-model="config.INGEST_API_BASE" :label="t('settings.provider.ingest_api_base')" variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="4" class="d-flex align-center"><v-btn variant="outlined" block @click="reloadIngestModels">{{ t('settings.models.reload') }}</v-btn></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.INGEST_API_KEY" :label="t('settings.provider.ingest_api_key')" type="password" autocomplete="new-password" :placeholder="t('settings.secret.keep')" :hint="secretHint('INGEST_API_KEY')" persistent-hint variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-combobox v-model="config.INGEST_VL_MODEL" :items="ingestModelOptions" :label="t('settings.provider.ingest_vl_model')" clearable variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-combobox v-model="config.INGEST_EMB_MODEL" :items="ingestModelOptions" :label="t('settings.provider.ingest_emb_model')" clearable variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.INGEST_VL_MODEL_CUSTOM" :label="t('settings.provider.ingest_vl_model_custom')" clearable variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.INGEST_EMB_MODEL_CUSTOM" :label="t('settings.provider.ingest_emb_model_custom')" clearable variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.SIGLIP_MODEL" :label="t('settings.provider.siglip_model')" variant="outlined" density="compact" color="primary" /></v-col>
      <!-- The direct fetch is often too slow to finish from mainland China, and a
           download that never progresses reads as a hang; this swaps both the
           model host and the package index without touching anything else. -->
      <v-col cols="12" md="6">
        <v-select
          v-model="config.DOWNLOAD_MIRROR"
          :items="downloadMirrorOptions"
          :label="t('settings.provider.download_mirror')"
          :hint="t('settings.provider.download_mirror_hint')"
          persistent-hint
          variant="outlined"
          density="compact"
          color="primary"
        />
      </v-col>
      <v-col cols="12" md="6"><v-switch v-model="config.SIGLIP_WORKER_ENABLED" :label="t('settings.provider.siglip_worker_enabled')" color="primary" inset hide-details @update:model-value="onToggleSiglipWorker" /></v-col>

      <v-col cols="12"><v-divider class="my-2" /></v-col>

      <v-col cols="12" md="6"><v-text-field v-model="config.WORKER_BATCH" :label="t('settings.provider.worker_batch')" type="number" variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-text-field v-model="config.WORKER_SLEEP" :label="t('settings.provider.worker_sleep')" type="number" variant="outlined" density="compact" color="primary" /></v-col>
      <v-col cols="12" md="6"><v-switch v-model="config.WORKER_ONLY_MISSING" :label="t('settings.worker.only_missing')" color="primary" inset hide-details /></v-col>
    </v-row>
    </div>
  </v-card>
</template>

<script>
import { computed, ref } from "vue";
import { useSettingsStore } from "../../stores/settingsStore";

export default {
  setup() {
    const store = useSettingsStore();
    const tt = (key, vars = {}) => store.t(key, vars);

    const downloadMirrorOptions = computed(() => [
      { value: "", title: tt("settings.provider.download_mirror_upstream") },
      { value: "cn", title: tt("settings.provider.download_mirror_cn") },
    ]);

    async function onToggleSiglipWorker(v) {
      await store.toggleSiglipWorkerEnabled(!!v);
    }

    return {
      ...store,
      settingsLocked: ref(true),
      onToggleSiglipWorker,
      downloadMirrorOptions,
    };
  },
};
</script>

<style scoped>
.settings-locked {
  pointer-events: none;
  opacity: 0.58;
}
</style>
