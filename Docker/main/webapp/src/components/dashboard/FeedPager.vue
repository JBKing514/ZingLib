<template>
  <div v-if="visible" class="feed-pager d-flex align-center justify-center flex-wrap ga-2">
    <v-btn
      size="small"
      variant="tonal"
      color="primary"
      icon="mdi-chevron-left"
      :disabled="loading || !canPrev"
      :aria-label="t('home.pager.prev')"
      @click="emit('prev')"
    />
    <span class="feed-pager-label text-body-2">
      {{ t('home.pager.page', { page }) }}
      <span class="text-medium-emphasis">· {{ t('home.pager.per_page', { n: pageSize }) }}</span>
    </span>
    <v-btn
      size="small"
      variant="tonal"
      color="primary"
      icon="mdi-chevron-right"
      :disabled="loading || !canNext"
      :aria-label="t('home.pager.next')"
      @click="emit('next')"
    />
    <v-text-field
      ref="jumpRef"
      class="feed-pager-jump"
      density="compact"
      variant="outlined"
      type="number"
      hide-details
      :min="1"
      :max="maxPage"
      :placeholder="t('home.pager.jump')"
      :disabled="loading"
      :model-value="jumpText"
      @update:model-value="jumpText = $event"
      @keydown.enter="submit"
    />
    <v-btn size="small" variant="text" color="primary" :disabled="loading" @click="submit">
      {{ t('home.pager.go') }}
    </v-btn>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";

const props = defineProps({
  visible: { type: Boolean, default: false },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 0 },
  canPrev: { type: Boolean, default: false },
  canNext: { type: Boolean, default: false },
  // The highest page the jump box may target. Derived from the pages actually
  // reached (plus one when the server says there is more) -- the feeds report
  // `has_more` but no total, so a real page count does not exist to enforce.
  maxPage: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
  t: { type: Function, required: true },
});

const emit = defineEmits(["prev", "next", "jump"]);

const jumpRef = ref(null);
// Kept as a string so the field can sit empty while the user types; the number is
// only parsed on submit.
const jumpText = ref("");
watch(
  () => props.page,
  () => {
    jumpText.value = "";
  }
);

function submit() {
  const raw = String(jumpText.value ?? "").trim();
  if (!raw) return;
  const n = Number(raw);
  if (!Number.isFinite(n)) return;
  const target = Math.max(1, Math.min(Math.floor(n), Math.max(1, Number(props.maxPage) || 1)));
  jumpText.value = "";
  jumpRef.value?.blur?.();
  if (target === Number(props.page || 1)) return;
  emit("jump", target);
}
</script>

<style scoped>
/* An outlined Vuetify field inside a flex row resolves to zero intrinsic width
   when it is allowed to shrink -- it ships in the bundle and never renders.
   Fixed basis, like every other inline picker in this app. */
.feed-pager-jump {
  flex: 0 0 92px;
  width: 92px;
}
.feed-pager-label {
  white-space: nowrap;
}
</style>
