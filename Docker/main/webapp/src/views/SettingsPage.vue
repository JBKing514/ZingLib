<template>
  <v-tabs class="mb-4" color="primary">
    <v-tab value="general" :to="{ name: 'settings-general' }">{{ t("settings.tab.general") }}</v-tab>
    <template v-if="!appStore.isRecoveryMode">
      <!-- Local library first: it is the screen that owns the library itself, so
           it sits directly after the general options rather than at the end. -->
      <v-tab value="local_lib" :to="{ name: 'settings-local-lib' }">{{ t("settings.tab.local_lib") }}</v-tab>
      <v-tab value="reader" :to="{ name: 'settings-reader' }">{{ t("settings.tab.reader") }}</v-tab>
      <v-tab value="data_clean" :to="{ name: 'settings-data-clean' }">{{ t("settings.tab.data_clean") }}</v-tab>
      <v-tab value="search" :to="{ name: 'settings-search' }">{{ t("settings.tab.search") }}</v-tab>
      <v-tab value="other" :to="{ name: 'settings-other' }">{{ t("settings.tab.other") }}</v-tab>
    </template>
  </v-tabs>

  <RouterView />

  <!-- There is no save button any more: every change on these tabs is written
       through the store's auto-saver, so all this row has to do is say what it is
       doing. -->
  <div class="settings-autosave" :class="`is-${saveState.kind}`">
    <v-progress-circular
      v-if="saveState.kind === 'saving'"
      indeterminate
      size="15"
      width="2"
      color="primary"
    />
    <v-icon v-else :icon="saveState.icon" size="17" />
    <span class="text-caption">{{ saveState.label }}</span>
  </div>
</template>

<script>
import { computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAppStore } from "../stores/appStore";
import { useSettingsStore } from "../stores/settingsStore";

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const appStore = useAppStore();
    const route = useRoute();
    const router = useRouter();

    watch(
      () => [appStore.isRecoveryMode, route.name],
      ([isRecovery]) => {
        if (isRecovery && route.name !== "settings-general") {
          router.replace({ name: "settings-general" });
          return;
        }
      },
      { immediate: true },
    );

    const saveState = computed(() => {
      const state = settingsStore.configSaveState;
      if (state === "saving") {
        return { kind: "saving", icon: "", label: settingsStore.t("settings.autosave.saving") };
      }
      if (state === "pending") {
        return { kind: "pending", icon: "mdi-cloud-upload-outline", label: settingsStore.t("settings.autosave.pending") };
      }
      if (state === "saved") {
        return { kind: "saved", icon: "mdi-check-circle", label: settingsStore.t("settings.autosave.saved") };
      }
      if (state === "error") {
        return {
          kind: "error",
          icon: "mdi-alert-circle",
          label: settingsStore.t("settings.autosave.failed", { reason: settingsStore.configSaveError || "n/a" }),
        };
      }
      return { kind: "idle", icon: "mdi-cloud-check-outline", label: settingsStore.t("settings.autosave.idle") };
    });

    return { ...settingsStore, appStore, saveState };
  },
};
</script>

<style scoped>
.settings-autosave {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 20px 0 6px;
  opacity: 0.75;
}
.settings-autosave.is-saved {
  color: rgb(var(--v-theme-success));
  opacity: 1;
}
.settings-autosave.is-error {
  color: rgb(var(--v-theme-error));
  opacity: 1;
}
</style>
