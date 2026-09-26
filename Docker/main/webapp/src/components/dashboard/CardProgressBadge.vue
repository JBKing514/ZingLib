<template>
  <div class="progress-badge" :class="{ 'is-complete': isComplete }" :title="title">
    <svg class="progress-ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle class="ring-track" cx="10" cy="10" r="8" />
      <circle
        class="ring-fill"
        cx="10"
        cy="10"
        r="8"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
      />
    </svg>
    <span class="progress-text">{{ percent }}%</span>
  </div>
</template>

<script>
// A ring on the left and the percentage on the right, sized to sit beside the
// category capsule instead of competing with it. Pure presentational: the
// percentage is passed in already resolved, so this never touches a store.
const RADIUS = 8;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default {
  name: "CardProgressBadge",
  props: {
    percent: { type: Number, required: true },
    title: { type: String, default: "" },
  },
  computed: {
    isComplete() {
      return Number(this.percent) >= 100;
    },
    circumference() {
      return CIRCUMFERENCE.toFixed(2);
    },
    dashOffset() {
      const clamped = Math.max(0, Math.min(100, Number(this.percent) || 0));
      return (CIRCUMFERENCE * (1 - clamped / 100)).toFixed(2);
    },
  },
};
</script>
