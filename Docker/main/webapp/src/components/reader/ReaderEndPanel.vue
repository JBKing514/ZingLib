<template>
  <!--
    Shown one page past the last one. The panel itself is click-through so the
    reader's tap zones keep working underneath it -- only the two interactive
    islands (the hint and the candidate strip) take pointer events.
  -->
  <div class="reader-end" :class="{ 'reader-end-inline': inline }">
    <div class="reader-end-hint" @click.stop="onForward">
      <v-icon size="34" class="mb-1">{{ hasNext ? 'mdi-book-arrow-right-outline' : 'mdi-bookshelf' }}</v-icon>
      <div class="reader-end-title">{{ t('reader.end.title') }}</div>
      <div class="reader-end-sub">
        {{ hasNext ? t('reader.end.hint') : t('reader.end.hint_last') }}
      </div>
      <div v-if="hasNext && nextTitle" class="reader-end-next-title">{{ nextTitle }}</div>
      <v-btn
        v-if="hasNext"
        class="mt-2"
        color="primary"
        variant="tonal"
        prepend-icon="mdi-arrow-right-circle-outline"
        @click.stop="$emit('next-gallery')"
      >{{ t('reader.end.next') }}</v-btn>
      <v-btn
        v-else
        class="mt-2"
        color="secondary"
        variant="tonal"
        prepend-icon="mdi-bookshelf"
        @click.stop="$emit('back-shelf')"
      >{{ t('reader.end.back_shelf') }}</v-btn>
    </div>

    <div v-if="showRecs" class="reader-end-recs" @click.stop>
      <div class="reader-end-recs-head">
        <v-icon size="18" class="mr-1">mdi-auto-fix</v-icon>
        <span>{{ t('reader.end.rec_title') }}</span>
      </div>
      <div v-if="loading" class="reader-end-recs-state">
        <v-progress-circular indeterminate size="18" width="2" />
        <span class="ml-2">{{ t('reader.end.rec_loading') }}</span>
      </div>
      <div v-else-if="error" class="reader-end-recs-state">{{ error }}</div>
      <div v-else-if="!items.length" class="reader-end-recs-state">{{ t('reader.end.rec_empty') }}</div>
      <div v-else class="reader-end-recs-rail">
        <button
          v-for="item in items"
          :key="item.id || item.arcid"
          class="reader-end-rec-card"
          type="button"
          @click.stop="$emit('open-item', item)"
        >
          <div class="reader-end-rec-cover-wrap">
            <img
              v-if="item.thumb_url"
              :src="item.thumb_url"
              class="reader-end-rec-cover"
              alt=""
              loading="lazy"
              decoding="async"
              fetchpriority="low"
              draggable="false"
            />
            <div v-else class="reader-end-rec-cover reader-end-rec-fallback">
              <v-icon size="20">mdi-image-outline</v-icon>
            </div>
          </div>
          <div class="reader-end-rec-label">{{ item.title || item.arcid }}</div>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  nextTitle: { type: String, default: "" },
  hasNext: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: "" },
  showRecs: { type: Boolean, default: true },
  // Continuous scroll has no "virtual page" to overlay -- the panel is simply
  // the last block of the strip.
  inline: { type: Boolean, default: false },
  t: { type: Function, required: true },
});

const emit = defineEmits(["next-gallery", "back-shelf", "open-item"]);

function onForward() {
  if (props.hasNext) emit("next-gallery");
}
</script>

<style scoped>
.reader-end {
  position: absolute;
  inset: 0;
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 24px 16px calc(180px + env(safe-area-inset-bottom));
  pointer-events: none;
  color: rgba(255, 255, 255, 0.92);
  text-align: center;
}

.reader-end-hint {
  pointer-events: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 18px 22px;
  border-radius: 16px;
  background: rgba(8, 10, 14, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.14);
  backdrop-filter: blur(8px);
  max-width: min(88vw, 460px);
}

.reader-end-title {
  font-size: 15px;
  font-weight: 600;
}

.reader-end-sub {
  margin-top: 2px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

.reader-end-next-title {
  margin-top: 6px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.9);
  word-break: break-word;
}

.reader-end-recs {
  pointer-events: auto;
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 10px 12px calc(10px + env(safe-area-inset-bottom));
  border-radius: 16px 16px 0 0;
  background: color-mix(in srgb, rgb(var(--v-theme-surface)) 88%, transparent);
  border-top: 1px solid color-mix(in srgb, rgb(var(--v-theme-on-surface)) 16%, transparent);
  backdrop-filter: blur(10px);
  color: rgb(var(--v-theme-on-surface));
  text-align: left;
}

.reader-end-recs-head {
  display: flex;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
}

.reader-end-recs-state {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: rgba(var(--v-theme-on-surface), 0.7);
  padding: 8px 0;
}

.reader-end-recs-rail {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.reader-end-rec-card {
  flex: 0 0 auto;
  width: 92px;
  border: 0;
  padding: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.reader-end-rec-cover-wrap {
  width: 92px;
  height: 128px;
  border-radius: 8px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid color-mix(in srgb, rgb(var(--v-theme-on-surface)) 14%, transparent);
}

.reader-end-rec-cover {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.reader-end-rec-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
}

.reader-end-rec-label {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.25;
  max-height: 2.6em;
  overflow: hidden;
  color: rgba(var(--v-theme-on-surface), 0.85);
}

/* Continuous mode: the panel is a normal block at the end of the strip, so it
   must not float above the pages and the candidate box sits inline. */
.reader-end-inline {
  position: static;
  inset: auto;
  min-height: 320px;
  padding: 24px 16px calc(24px + env(safe-area-inset-bottom));
  gap: 12px;
  pointer-events: auto;
}

.reader-end-inline .reader-end-recs {
  position: static;
  left: auto;
  right: auto;
  bottom: auto;
  width: 100%;
  max-width: 640px;
  border-radius: 16px;
  border: 1px solid color-mix(in srgb, rgb(var(--v-theme-on-surface)) 16%, transparent);
}
</style>
