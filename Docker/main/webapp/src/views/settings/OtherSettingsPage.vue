<template>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.tab.other') }}</div>
    <v-row>
      <v-col v-if="!appStore.isRecoveryMode" cols="12" class="mt-2">
        <v-btn size="small" variant="outlined" @click="openSetupWizardManual">{{ t('setup.reopen') }}</v-btn>
      </v-col>
    </v-row>
  </v-card>

  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-1">{{ t('settings.other.debug_title') }}</div>
    <div class="text-caption text-medium-emphasis mb-3">{{ t('settings.other.debug_hint') }}</div>
    <v-switch
      v-model="config.DATA_UI_EXPOSE_TRACEBACK"
      :label="t('settings.other.expose_traceback')"
      :messages="t('settings.other.expose_traceback_hint')"
      color="primary"
      inset
      hide-details="auto"
      persistent-hint
    />
  </v-card>
</template>

<script>
import { useAppStore } from "../../stores/appStore";
import { useSettingsStore } from "../../stores/settingsStore";

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const appStore = useAppStore();
    return { ...settingsStore, appStore };
  },
};
</script>
