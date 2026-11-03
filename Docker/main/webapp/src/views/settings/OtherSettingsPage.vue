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

    <v-divider class="my-3" />
    <v-switch
      :model-value="duoDebug"
      :label="t('settings.other.duo_debug')"
      :messages="t('settings.other.duo_debug_hint')"
      color="teal"
      inset
      hide-details="auto"
      persistent-hint
      @update:model-value="setDuoDebug"
    />
  </v-card>
</template>

<script>
import { useAppStore } from "../../stores/appStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { computed } from "vue";
import { useDualScreen } from "../../composables/useDualScreen";

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const appStore = useAppStore();
    // Debug overlay for the dual-screen layout: forcing it on is the only way to
    // inspect the geometry on a device that does not report itself as a Duo.
    const dual = useDualScreen();
    const duoDebug = computed(() => Boolean(dual.state.debug));
    const setDuoDebug = (on) => dual.setDebug(on);
    return { ...settingsStore, appStore, duoDebug, setDuoDebug };
  },
};
</script>
