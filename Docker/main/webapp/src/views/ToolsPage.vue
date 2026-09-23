<template>
  <v-card class="pa-4 mb-4" variant="flat">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('tab.tools') }}</div>
    <v-tabs v-model="active" color="primary" density="compact">
      <v-tab value="file_manager">{{ t('tools.file_manager.title') }}</v-tab>
      <v-tab value="metadata_editor">{{ t('tools.metadata_editor.title') }}</v-tab>
      <v-tab value="tasks">{{ t('tools.tasks.title') }}</v-tab>
    </v-tabs>
  </v-card>

  <v-window v-model="active">
    <v-window-item value="file_manager">
      <FileManagerPage />
    </v-window-item>
    <v-window-item value="metadata_editor">
      <MetadataEditorPage />
    </v-window-item>
    <v-window-item value="tasks">
      <ControlPage v-if="active === 'tasks'" />
    </v-window-item>
  </v-window>
</template>

<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import FileManagerPage from "./tools/FileManagerPage.vue";
import MetadataEditorPage from "./tools/MetadataEditorPage.vue";
import ControlPage from "./ControlPage.vue";
import { useLayoutStore } from "../stores/layoutStore";

const route = useRoute();
const router = useRouter();
const active = computed({
  get: () => ['file_manager', 'metadata_editor', 'tasks'].includes(route.query.tab) ? route.query.tab : 'file_manager',
  set: tab => router.replace({ query: { ...route.query, tab } }),
});
const layoutStore = useLayoutStore();
const t = (key, vars = {}) => layoutStore.t(key, vars);
</script>
