<template>
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t("settings.reader.title") }}</div>
    <div class="text-caption text-medium-emphasis mb-4">{{ t("settings.reader.hint") }}</div>

    <v-row>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_MODE"
          :items="modeItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.mode')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <!-- Direction is meaningless while continuously scrolling, and the
             vertical variants are gone: only left-to-right / right-to-left
             remain for the paged layout. -->
        <v-select
          v-model="config.READER_DIRECTION"
          :items="directionItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.direction')"
          :disabled="config.READER_MODE === 'continuous'"
          :hint="config.READER_MODE === 'continuous' ? t('settings.reader.direction_locked_hint') : ''"
          persistent-hint
          variant="outlined"
          density="compact"
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_FIT_MODE"
          :items="fitItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.fit_mode')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_SPREAD_MODE"
          :items="spreadItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.spread_mode')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_FILTER_PRESET"
          :items="filterItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.filter_preset')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_IMAGE_QUALITY_MODE"
          :items="imageQualityItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.image_quality_mode')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-slider
          v-model="config.READER_WHEEL_CURVE"
          :min="0"
          :max="100"
          :step="1"
          :label="t('settings.reader.wheel_curve')"
          color="primary"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-slider
          v-model="config.READER_WHEEL_RANGE"
          :min="2"
          :max="20"
          :step="1"
          :label="t('settings.reader.wheel_range')"
          color="primary"
          density="compact"
          hide-details
          thumb-label
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-slider
          v-model="config.READER_WHEEL_EXTENT_PCT"
          :min="60"
          :max="220"
          :step="1"
          :label="t('settings.reader.wheel_extent')"
          color="primary"
          density="compact"
          hide-details
          thumb-label
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-slider
          v-model="config.READER_WHEEL_THUMB_SCALE_PCT"
          :min="60"
          :max="220"
          :step="1"
          :label="t('settings.reader.wheel_thumb_scale')"
          color="primary"
          density="compact"
          hide-details
          thumb-label
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-select
          v-model="config.READER_WHEEL_POSITION"
          :items="wheelPosItems"
          item-title="title"
          item-value="value"
          :label="t('settings.reader.wheel_position')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-text-field
          v-model="config.READER_PRELOAD_COUNT"
          type="number"
          min="10"
          max="20"
          :label="t('settings.reader.preload')"
          variant="outlined"
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_SWIPE_ENABLED" :label="t('settings.reader.swipe')" color="primary" inset hide-details />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_TAP_TO_TURN" :label="t('settings.reader.tap_turn')" color="primary" inset hide-details />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_PAGE_ANIM_ENABLED" :label="t('settings.reader.page_anim')" color="primary" inset hide-details />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_HIDE_APP_UI" :label="t('settings.reader.hide_app_ui')" color="primary" inset hide-details />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_VIEWPORT_FIT_COVER" :label="t('settings.reader.viewport_fit_cover')" color="primary" inset hide-details />
      </v-col>
    </v-row>
  </v-card>

  <!-- Global shortcuts: three independent input channels, each with its own
       switch so a user who only wants one of them is not forced into all. -->
  <v-card class="pa-4 mb-4">
    <div class="text-subtitle-1 font-weight-medium mb-3">{{ t("settings.reader.shortcuts_title") }}</div>
    <div class="text-caption text-medium-emphasis mb-4">{{ t("settings.reader.shortcuts_hint") }}</div>

    <v-row>
      <v-col cols="12" md="6">
        <v-text-field
          v-model="config.READER_KEY_PREV"
          :label="t('settings.reader.key_prev')"
          :hint="t('settings.reader.key_hint')"
          persistent-hint
          variant="outlined"
          density="compact"
        />
      </v-col>
      <v-col cols="12" md="6">
        <v-text-field
          v-model="config.READER_KEY_NEXT"
          :label="t('settings.reader.key_next')"
          :hint="t('settings.reader.key_hint')"
          persistent-hint
          variant="outlined"
          density="compact"
        />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch v-model="config.READER_WHEEL_PAGING_ENABLED" :label="t('settings.reader.wheel_paging')" color="primary" inset hide-details />
      </v-col>
      <v-col cols="12" md="6" class="d-flex align-center">
        <v-switch
          v-model="config.READER_WHEEL_NATURAL"
          :label="t('settings.reader.wheel_natural')"
          :disabled="config.READER_WHEEL_PAGING_ENABLED !== true"
          color="primary"
          inset
          hide-details
        />
      </v-col>
    </v-row>
  </v-card>
</template>

<script>
import { computed } from "vue";
import { useSettingsStore } from "../../stores/settingsStore";

export default {
  setup() {
    const settingsStore = useSettingsStore();
    const directionItems = computed(() => [
      { title: settingsStore.t("settings.reader.direction_ltr"), value: "ltr" },
      { title: settingsStore.t("settings.reader.direction_rtl"), value: "rtl" },
    ]);
    const modeItems = computed(() => [
      { title: settingsStore.t("reader.mode.paged"), value: "paged" },
      { title: settingsStore.t("reader.mode.continuous"), value: "continuous" },
    ]);
    const fitItems = computed(() => [
      { title: settingsStore.t("settings.reader.fit_contain"), value: "contain" },
      { title: settingsStore.t("settings.reader.fit_width"), value: "width" },
      { title: settingsStore.t("settings.reader.fit_height"), value: "height" },
    ]);
    const spreadItems = computed(() => [
      { title: settingsStore.t("settings.reader.spread_single"), value: "single" },
      { title: settingsStore.t("settings.reader.spread_double"), value: "double" },
    ]);
    const filterItems = computed(() => [
      { title: settingsStore.t("settings.reader.filter_none"), value: "none" },
      { title: settingsStore.t("settings.reader.filter_night_eink"), value: "night_eink" },
      { title: settingsStore.t("settings.reader.filter_warm_sepia"), value: "warm_sepia" },
      { title: settingsStore.t("settings.reader.filter_dark_invert"), value: "dark_invert" },
    ]);
    const imageQualityItems = computed(() => [
      { title: settingsStore.t("settings.reader.image_quality_auto"), value: "auto" },
      { title: settingsStore.t("settings.reader.image_quality_low"), value: "low" },
      { title: settingsStore.t("settings.reader.image_quality_mid"), value: "mid" },
      { title: settingsStore.t("settings.reader.image_quality_high"), value: "high" },
      { title: settingsStore.t("settings.reader.image_quality_original"), value: "original" },
    ]);
    const wheelPosItems = computed(() => [
      { title: settingsStore.t("settings.reader.wheel_pos_bottom"), value: "bottom" },
      { title: settingsStore.t("settings.reader.wheel_pos_left"), value: "left" },
      { title: settingsStore.t("settings.reader.wheel_pos_right"), value: "right" },
    ]);
    return {
      ...settingsStore,
      modeItems,
      directionItems,
      fitItems,
      spreadItems,
      filterItems,
      imageQualityItems,
      wheelPosItems,
    };
  },
};
</script>
