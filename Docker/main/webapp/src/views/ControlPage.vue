<template>
          <v-alert v-if="health.database?.error" type="warning" class="mb-4">{{ t('dashboard.db_warning', { reason: health.database.error }) }}</v-alert>
          <v-card class="pa-4 mb-4">
            <div class="text-subtitle-1 font-weight-medium mb-3">{{ t('control.manual') }}</div>
            <v-row class="manual-task-row" align="stretch">
              <v-col cols="12" sm="6" md="4" lg="3" xl="2"><v-btn block class="manual-task-btn" color="secondary" @click="triggerTask('local_ingest')">{{ t('control.btn.local_ingest') }}</v-btn></v-col>
              <v-col cols="12" sm="6" md="4" lg="3" xl="2"><v-btn block class="manual-task-btn" color="warning" variant="tonal" @click="triggerTask('local_ingest', '--retry-fail-embedding')">{{ t('control.btn.local_ingest_retry_fail') }}</v-btn></v-col>
            </v-row>
          </v-card>

          <v-card class="pa-4 mb-4">
            <div class="text-subtitle-1 font-weight-medium mb-3 d-flex align-center ga-2">
              <span>{{ t('control.scheduler') }}</span>
              <v-tooltip location="top">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    icon="mdi-help-circle-outline"
                    size="x-small"
                    variant="text"
                    href="https://crontab.guru/"
                    target="_blank"
                    rel="noopener noreferrer"
                  />
                </template>
                <span>{{ t('control.cron.help') }} e.g. `*/30 * * * *`, `0 3 * * *`, `0 0 * * 1`</span>
              </v-tooltip>
            </div>
            <v-row v-for="it in scheduleVisible" :key="it.key" class="align-center mb-2">
              <v-col cols="12" md="4">{{ schedulerLabel(it.key) }}</v-col>
              <v-col cols="12" md="3"><v-switch v-model="it.item.enabled" color="primary" hide-details inset/></v-col>
              <v-col cols="12" md="5"><v-text-field v-model="it.item.cron" :label="`Cron (${schedulerLabel(it.key)})`" hide-details variant="outlined" density="comfortable" color="primary"/></v-col>
            </v-row>
            <v-btn color="primary" @click="saveSchedule">{{ t('control.scheduler.save') }}</v-btn>
          </v-card>

          <h2 class="text-subtitle-1 font-weight-medium mb-3">{{ t('tools.task_logs') }}</h2>
          <AuditPage />
</template>

<script>
import { onBeforeUnmount, onMounted } from "vue";
import { useControlStore } from "../stores/controlStore";
import AuditPage from "./AuditPage.vue";

export default {
  components: { AuditPage },
  setup() {
    const store = useControlStore();
    onMounted(() => {
      store.startControlPolling().catch(() => null);
    });
    onBeforeUnmount(() => {
      store.stopControlPolling();
    });
    return store;
  },
};
</script>

<style scoped>
.manual-task-btn {
  min-height: 52px;
}

.manual-task-btn :deep(.v-btn__content) {
  white-space: normal;
  text-align: center;
  line-height: 1.25;
}
</style>
