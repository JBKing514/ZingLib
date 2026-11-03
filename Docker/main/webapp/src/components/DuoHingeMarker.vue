<template>
  <!--
    Calibration overlay. The hinge width is a constant we cannot measure (the
    browser sees one continuous surface), so the only way to get it right is to
    look at the device with a marked band and compare it with the physical
    hinge. Enabled with `?duo=1`, removed once the number is settled.
  -->
  <div v-if="dual.state.active && debugOn" class="duo-marker" aria-hidden="true">
    <div class="duo-marker__band" :style="{ left: `${dual.state.leftWidth}px`, width: `${dual.state.gap}px` }" />
    <div class="duo-marker__edge" :style="{ left: `${dual.state.leftWidth}px` }" />
    <div
      class="duo-marker__edge"
      :style="{ left: `${dual.state.leftWidth + dual.state.gap}px` }"
    />
    <div class="duo-marker__label">
      {{ label }}
      <template v-if="debugOn">
        <br />
        {{ debugInfo }}
        <br />
        {{ dialogInfo }}
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useDualScreen } from "../composables/useDualScreen";

const dual = useDualScreen();

// `?duo_debug=1` prints what the browser actually computed for the feed grid.
// Reading pixels off a screenshot has cost more time than this will.
const debugInfo = ref("");
const dialogInfo = ref("");
let readoutTimer;
// Tied to `?duo=1` because the router rewrites the URL and drops unknown
// parameters, while `duo` survives -- it is read by the composable too.
const debugOn = computed(
  () => Boolean(dual.state.debug)
    || (typeof window !== "undefined"
      && new URLSearchParams(window.location.search).get("duo") === "1")
);

function readFeed() {
  if (!debugOn.value) return;
  // Measure only the active dashboard dialog, not the first overlay in the DOM.
  const overlay = document.querySelector(".home-filter-overlay.v-overlay--active");
  const content = overlay?.querySelector(".home-filter-content");
  const sheet = content?.querySelector(".home-filter-sheet");
  const sort = document.querySelector(".home-sort-overlay.v-overlay--active .home-sort-content");
  const menu = document.querySelector(".home-filter-tag-menu");
  const bounds = (el) => {
    if (!el || !el.getClientRects().length) return "-";
    const r = el.getBoundingClientRect();
    return `${Math.round(r.left)}..${Math.round(r.right)} y${Math.round(r.top)}..${Math.round(r.bottom)}`;
  };
  dialogInfo.value = `filter ${bounds(content)} | sheet ${bounds(sheet)} | sort ${bounds(sort)} | menu ${bounds(menu)}`;
  // The reader is its own full-bleed stage; measure whichever is on screen.
  const stage = document.querySelector(".reader-stage");
  const main = document.querySelector(".v-main");
  if (stage) {
    const sr = stage.getBoundingClientRect();
    const mr = main ? main.getBoundingClientRect() : null;
    const spread = document.querySelector(".paged-spread");
    const spr = spread ? spread.getBoundingClientRect() : null;
    const shots = Array.from(document.querySelectorAll(".paged-spread .reader-image"))
      .slice(0, 2)
      .map((el, i) => {
        const r = el.getBoundingClientRect();
        return `${i}:${Math.round(r.left)}+${Math.round(r.width)}`;
      })
      .join(" ");
    const mc = main ? getComputedStyle(main) : null;
    debugInfo.value =
      `stage ${Math.round(sr.left)}+${Math.round(sr.width)} | main ${mr ? Math.round(mr.left) + "+" + Math.round(mr.width) : "-"}` +
      ` | spread ${spr ? Math.round(spr.left) + "+" + Math.round(spr.width) : "-"}` +
      ` | imgs ${shots}` +
      (mc ? ` | main.w=${mc.width}` : "");
    return;
  }
  const row = document.querySelector(".dashboard-page-shell .v-row");
  if (!row) { debugInfo.value = "no feed row"; return; }
  const cs = getComputedStyle(row);
  const cells = Array.from(row.children).slice(0, 6).map((el, i) => {
    const r = el.getBoundingClientRect();
    return `${i}:${Math.round(r.left)}+${Math.round(r.width)}`;
  });
  debugInfo.value = `row ${Math.round(row.getBoundingClientRect().width)} cols=${cs.gridTemplateColumns || "-"} | ${cells.join(" ")}`;
}

onMounted(() => {
  watch(debugOn, (on) => {
    clearInterval(readoutTimer);
    if (!on) return;
    readFeed();
    readoutTimer = setInterval(readFeed, 1200);
  }, { immediate: true });
});

onUnmounted(() => clearInterval(readoutTimer));

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
  max-width: calc(var(--duo-left-width) - 16px);
  white-space: normal;
}
</style>
