<template>
  <!--
    Calibration overlay. The hinge width is a constant we cannot measure (the
    browser sees one continuous surface), so the only way to get it right is to
    look at the device with a marked band and compare it with the physical
    hinge. Enabled with `?duo=1`, removed once the number is settled.
  -->
  <div v-if="dual.state.active" class="duo-marker" aria-hidden="true">
    <div class="duo-marker__band" :style="{ left: `${dual.state.leftWidth}px`, width: `${dual.state.gap}px` }" />
    <div class="duo-marker__edge" :style="{ left: `${dual.state.leftWidth}px` }" />
    <div
      class="duo-marker__edge"
      :style="{ left: `${dual.state.leftWidth + dual.state.gap}px` }"
    />
    <div class="duo-marker__label">
      {{ label }}
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useDualScreen } from "../composables/useDualScreen";

const dual = useDualScreen();

const label = computed(() => {
  const s = dual.state;
  return [
    `双屏 ${s.reason || "-"}`,
    s.model ? `型号 ${s.model}` : (s.secure ? "型号未知" : "非安全上下文"),
    `视口 ${s.viewport}`,
    `铰链 ${s.gap}`,
    `左 ${s.leftWidth}`,
    `右 ${s.rightWidth}`,
    s.measured ? "实测分段" : "常量",
  ]
    .filter(Boolean)
    .join(" · ");
});
</script>

<style scoped>
.duo-marker {
  position: fixed;
  inset: 0;
  z-index: 100000;
  pointer-events: none;
}

.duo-marker__band {
  position: absolute;
  top: 0;
  bottom: 0;
  background: rgba(255, 64, 96, 0.28);
  border-left: 2px solid rgba(255, 64, 96, 0.9);
  border-right: 2px solid rgba(255, 64, 96, 0.9);
}

.duo-marker__edge {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(64, 200, 255, 0.8);
}

.duo-marker__label {
  position: absolute;
  top: 6px;
  left: 8px;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(10, 14, 20, 0.86);
  color: #ffd9df;
  font: 12px/1.3 ui-monospace, monospace;
  white-space: nowrap;
}
</style>
