<template>
  <div class="reader-quick-settings" @click.stop>
    <div class="reader-quick-settings-label">{{ t("settings.reader.mode") }}</div>
    <v-btn-toggle :model-value="readerMode" mandatory density="compact" divided variant="outlined" color="primary" @update:model-value="$emit('update:reader-mode', $event)">
      <v-btn value="paged">{{ t("reader.mode.paged") }}</v-btn>
      <v-btn value="continuous">{{ t("reader.mode.continuous") }}</v-btn>
    </v-btn-toggle>
    <div class="reader-quick-settings-label">{{ t("settings.reader.direction") }}</div>
    <!-- Only left-to-right / right-to-left are offered: the vertical variants
         behave identically to these for a paged layout, so they were noise.
         In continuous scroll the direction has no meaning at all, so the
         control is disabled (ReaderPage forces ltr in that mode). -->
    <v-btn-toggle
      class="reader-dir-toggle"
      :model-value="direction"
      mandatory
      density="compact"
      divided
      variant="outlined"
      color="primary"
      :disabled="readerMode === 'continuous'"
      @update:model-value="$emit('update:direction', $event)"
    >
      <v-btn value="ltr" :title="t('settings.reader.direction_ltr')" :aria-label="t('settings.reader.direction_ltr')">
        <v-icon size="18">mdi-arrow-right-thin</v-icon>
      </v-btn>
      <v-btn value="rtl" :title="t('settings.reader.direction_rtl')" :aria-label="t('settings.reader.direction_rtl')">
        <v-icon size="18">mdi-arrow-left-thin</v-icon>
      </v-btn>
    </v-btn-toggle>
    <div class="reader-quick-settings-label">{{ t("settings.reader.spread_mode") }}</div>
    <v-btn-toggle :model-value="spreadMode" mandatory density="compact" divided variant="outlined" color="primary" @update:model-value="$emit('update:spread-mode', $event)">
      <v-btn value="single">{{ t("settings.reader.spread_single") }}</v-btn>
      <v-btn value="double">{{ t("settings.reader.spread_double") }}</v-btn>
    </v-btn-toggle>
    <div class="reader-quick-settings-label">{{ t("settings.reader.fit_mode") }}</div>
    <v-btn-toggle :model-value="fitMode" mandatory density="compact" divided variant="outlined" color="primary" @update:model-value="$emit('update:fit-mode', $event)">
      <v-btn value="contain">{{ t("settings.reader.fit_contain") }}</v-btn>
      <v-btn value="width">{{ t("settings.reader.fit_width") }}</v-btn>
      <v-btn value="height">{{ t("settings.reader.fit_height") }}</v-btn>
    </v-btn-toggle>
    <div class="reader-quick-settings-label">{{ t("settings.reader.filter_preset") }}</div>
    <v-select
      :model-value="filterPreset"
      :items="filterItems"
      item-title="title"
      item-value="value"
      :menu-props="menuProps"
      density="compact"
      variant="outlined"
      hide-details
      @update:model-value="$emit('update:filter-preset', $event)"
    />
    <div class="reader-quick-settings-label">{{ t("settings.reader.image_quality_mode") }}</div>
    <v-select
      :model-value="imageQualityMode"
      :items="imageQualityItems"
      item-title="title"
      item-value="value"
      :menu-props="menuProps"
      density="compact"
      variant="outlined"
      hide-details
      @update:model-value="$emit('update:image-quality-mode', $event)"
    />
    <div class="reader-quick-settings-label">{{ t("settings.reader.wheel_position") }}</div>
    <v-select
      :model-value="wheelPosition"
      :items="wheelPosItems"
      item-title="title"
      item-value="value"
      :menu-props="menuProps"
      density="compact"
      variant="outlined"
      hide-details
      @update:model-value="$emit('update:wheel-position', $event)"
    />
    <v-slider
      :model-value="wheelCurve"
      :min="0"
      :max="100"
      :step="1"
      density="compact"
      hide-details
      color="deep-orange"
      :label="t('settings.reader.wheel_curve')"
      @update:model-value="$emit('update:wheel-curve', $event)"
    />
    <v-slider
      :model-value="wheelRange"
      :min="2"
      :max="20"
      :step="1"
      density="compact"
      hide-details
      color="deep-orange"
      :label="t('settings.reader.wheel_range')"
      @update:model-value="$emit('update:wheel-range', $event)"
    />
    <v-slider
      :model-value="wheelExtentPct"
      :min="60"
      :max="220"
      :step="1"
      density="compact"
      hide-details
      color="deep-orange"
      :label="t('settings.reader.wheel_extent')"
      @update:model-value="$emit('update:wheel-extent-pct', $event)"
    />
    <v-slider
      :model-value="wheelThumbScalePct"
      :min="60"
      :max="220"
      :step="1"
      density="compact"
      hide-details
      color="deep-orange"
      :label="t('settings.reader.wheel_thumb_scale')"
      @update:model-value="$emit('update:wheel-thumb-scale-pct', $event)"
    />
    <v-switch
      :model-value="pageAnimEnabled"
      inset
      hide-details
      color="primary"
      :label="t('settings.reader.page_anim')"
      @update:model-value="$emit('update:page-anim-enabled', $event)"
    />
    <!-- No save button: these sliders write straight into the shared config, and
         the store's auto-saver persists them. -->
    <div class="reader-quick-settings-autosave">
      <v-icon icon="mdi-cloud-check-outline" size="15" />
      <span>{{ t("settings.autosave.inline") }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useLayoutStore } from "../../stores/layoutStore";

defineProps({
  readerMode: { type: String, default: "paged" },
  direction: { type: String, default: "ltr" },
  spreadMode: { type: String, default: "single" },
  fitMode: { type: String, default: "contain" },
  filterPreset: { type: String, default: "none" },
  imageQualityMode: { type: String, default: "high" },
  wheelPosition: { type: String, default: "bottom" },
  wheelCurve: { type: Number, default: 55 },
  wheelRange: { type: Number, default: 4 },
  wheelExtentPct: { type: Number, default: 100 },
  wheelThumbScalePct: { type: Number, default: 100 },
  pageAnimEnabled: { type: Boolean, default: true },
});

defineEmits([
  "update:reader-mode",
  "update:direction",
  "update:spread-mode",
  "update:fit-mode",
  "update:filter-preset",
  "update:image-quality-mode",
  "update:wheel-position",
  "update:wheel-curve",
  "update:wheel-range",
  "update:wheel-extent-pct",
  "update:wheel-thumb-scale-pct",
  "update:page-anim-enabled",
]);

const layoutStore = useLayoutStore();
const t = (key, vars = {}) => layoutStore.t(key, vars);
const menuProps = { zIndex: 3600, contentClass: "reader-quick-settings-menu" };

const wheelPosItems = computed(() => [
  { title: t("settings.reader.wheel_pos_bottom"), value: "bottom" },
  { title: t("settings.reader.wheel_pos_left"), value: "left" },
  { title: t("settings.reader.wheel_pos_right"), value: "right" },
]);

const filterItems = computed(() => [
  { title: t("settings.reader.filter_none"), value: "none" },
  { title: t("settings.reader.filter_night_eink"), value: "night_eink" },
  { title: t("settings.reader.filter_warm_sepia"), value: "warm_sepia" },
  { title: t("settings.reader.filter_dark_invert"), value: "dark_invert" },
]);
const imageQualityItems = computed(() => [
  { title: t("settings.reader.image_quality_low"), value: "low" },
  { title: t("settings.reader.image_quality_mid"), value: "mid" },
  { title: t("settings.reader.image_quality_high"), value: "high" },
  { title: t("settings.reader.image_quality_original"), value: "original" },
]);
</script>

<style scoped>
.reader-quick-settings {
  position: fixed;
  right: max(10px, env(safe-area-inset-right));
  top: calc(max(54px, env(safe-area-inset-top) + 44px));
  z-index: 3020;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(420px, calc(100vw - env(safe-area-inset-left) - env(safe-area-inset-right) - 20px));
  max-width: calc(100vw - env(safe-area-inset-left) - env(safe-area-inset-right) - 20px);
  max-height: calc(100dvh - env(safe-area-inset-top) - env(safe-area-inset-bottom) - 20px);
  overflow: auto;
  overscroll-behavior: contain;
  background: color-mix(in srgb, rgb(var(--v-theme-surface)) 86%, transparent);
  border: 1px solid color-mix(in srgb, rgb(var(--v-theme-on-surface)) 18%, transparent);
  border-radius: 12px;
  padding: 10px;
  backdrop-filter: blur(6px);
  color: rgb(var(--v-theme-on-surface));
}

:global(.reader-quick-settings-menu) {
  z-index: 3600 !important;
}

.reader-quick-settings-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: color-mix(in srgb, rgb(var(--v-theme-on-surface)) 78%, transparent);
  padding: 2px 2px 0;
}

.reader-quick-settings-autosave {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 2px;
  font-size: 11px;
  color: color-mix(in srgb, rgb(var(--v-theme-on-surface)) 62%, transparent);
}

.reader-quick-settings :deep(.v-btn-toggle) {
  max-width: 100%;
  flex-wrap: wrap;
}

.reader-quick-settings :deep(.reader-dir-toggle) {
  display: flex;
  flex-wrap: nowrap;
}

.reader-quick-settings :deep(.reader-dir-toggle .v-btn) {
  flex: 1 1 0;
  min-width: 0;
  min-height: 34px;
}

@media (max-width: 960px) {
  .reader-quick-settings {
    left: max(8px, env(safe-area-inset-left));
    right: max(8px, env(safe-area-inset-right));
    top: calc(max(50px, env(safe-area-inset-top) + 40px));
    width: auto;
    max-width: none;
    max-height: calc(100dvh - env(safe-area-inset-top) - env(safe-area-inset-bottom) - 8px);
    border-radius: 10px;
  }
}
</style>
