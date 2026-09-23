<template>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('settings.tab.other') }}</div>
    <v-row>
      <v-col v-if="!appStore.isRecoveryMode" cols="12" class="mt-2">
        <v-btn size="small" variant="outlined" @click="openSetupWizardManual">{{ t('setup.reopen') }}</v-btn>
      </v-col>
    </v-row>
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
