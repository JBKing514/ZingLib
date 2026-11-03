<template>
  <img :src="deferredKeys.has(coverKey) ? FEED_THUMB_PLACEHOLDER : String(item.thumb_url || '')" />
</template>

<script setup>
import { FEED_THUMB_PLACEHOLDER } from "../utils/feedCoverWindow";

defineProps({
  item: { type: Object, required: true },
  coverKey: { type: String, required: true },
  deferredKeys: { type: Set, required: true },
});
</script>
