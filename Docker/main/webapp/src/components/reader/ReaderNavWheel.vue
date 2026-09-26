<template>
  <div
    class="wheel-shell"
    :class="`wheel-${wheelPosition}`"
    :style="shellStyle"
    @wheel.prevent="onWheelMouse"
  >
    <div v-if="wheelPosition !== 'bottom'" class="wheel-side-mask" :class="`mask-${wheelPosition}`" />

    <div
      class="wheel-track-clip"
      @pointerdown="onWheelPointerDown"
      @pointermove="onWheelPointerMove"
      @pointerup="onWheelPointerEnd"
      @pointercancel="onWheelPointerEnd"
    >
      <div class="wheel-track" :class="`wheel-track-${wheelPosition}`">
        <button
          v-for="entry in wheelPages"
          :key="`w-${entry.page}`"
          class="wheel-item"
          :class="{ active: Number(entry.page) === cursorPageSafe, current: Number(entry.page) === currentPage }"
          :style="wheelItemStyle(entry.page)"
          @click="onThumbClick(entry, $event)"
        >
          <div class="wheel-thumb-placeholder" aria-hidden="true">
            <v-icon size="24">mdi-image-outline</v-icon>
          </div>
          <img v-if="!canUseSprite(entry)" :src="String(entry.src || '')" alt="thumb" class="wheel-thumb" loading="lazy" />
          <div v-else class="wheel-thumb wheel-thumb-sprite" :style="wheelSpriteStyle(entry)" />
          <div class="wheel-mask" />
          <div class="wheel-label-wrap">
            <span class="wheel-label">{{ entry.page }}</span>
          </div>
        </button>
      </div>
    </div>

    <div class="wheel-slider-row" :class="`wheel-slider-${wheelPosition}`">
      <div class="wheel-progress-text">{{ progressText }}</div>
      <v-slider
        :model-value="sliderValue"
        :min="1"
        :max="Math.max(1, totalPages)"
        :step="1"
        :direction="wheelPosition === 'bottom' ? 'horizontal' : 'vertical'"
        :reverse="sliderReverse"
        hide-details
        color="deep-orange"
        thumb-color="white"
        track-color="rgba(255,255,255,0.35)"
        @update:model-value="onSliderChange"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";
import { WHEEL_DRAG_THRESHOLD_PX, pageForWheelDrag } from "../../utils/readerWheelDrag";

const props = defineProps({
  currentPage: { type: Number, required: true },
  cursorPage: { type: Number, default: 1 },
  totalPages: { type: Number, required: true },
  wheelPages: { type: Array, default: () => [] },
  wheelPosition: { type: String, default: "bottom" },
  wheelRadius: { type: Number, default: 320 },
  wheelVisibleRange: { type: Number, default: 4 },
  wheelExtentPct: { type: Number, default: 100 },
  wheelThumbScalePct: { type: Number, default: 100 },
  rtl: { type: Boolean, default: false },
});

const emit = defineEmits(["jump-to-page", "preview-page"]);

const dragState = ref({
  active: false,
  pointerId: -1,
  x: 0,
  y: 0,
  page: 1,
  emittedPage: 1,
  captured: false,
});
// Set the moment a gesture becomes a real drag; consumed by the click that the
// same gesture would otherwise synthesise on release.
let draggedThisGesture = false;
let lastHapticPage = -1;

function emitPreviewPage(page) {
  const next = Number(page || 1);
  emit("preview-page", next);
  if (next === lastHapticPage) return;
  lastHapticPage = next;
  try {
    if (typeof navigator !== "undefined" && typeof navigator.vibrate === "function") {
      navigator.vibrate(8);
    }
  } catch {
    // Haptics are optional; unsupported browsers keep normal wheel behavior.
  }
}

const cursorPageSafe = computed(() => {
  const max = Math.max(1, Number(props.totalPages || 1));
  const p = Number(props.cursorPage || props.currentPage || 1);
  if (!Number.isFinite(p)) return 1;
  return Math.max(1, Math.min(max, Math.round(p)));
});

const sliderValue = computed(() => Number(cursorPageSafe.value || 1));

const isSideWheel = computed(() => props.wheelPosition === "left" || props.wheelPosition === "right");

const extentScaleNorm = computed(() => {
  const raw = Math.max(60, Math.min(220, Number(props.wheelExtentPct || 100)));
  const snapped = isSideWheel.value ? Math.round(raw / 4) * 4 : raw;
  return snapped / 100;
});

const thumbScaleNorm = computed(() => {
  const raw = Math.max(60, Math.min(220, Number(props.wheelThumbScalePct || 100)));
  const snapped = isSideWheel.value ? Math.round(raw / 4) * 4 : raw;
  return snapped / 100;
});

const sliderReverse = computed(() => {
  if (props.wheelPosition === "bottom") return !!props.rtl;
  return true;
});

const progressText = computed(() => {
  const cur = Number(props.currentPage || 1);
  const cursor = Number(cursorPageSafe.value || 1);
  const total = Math.max(1, Number(props.totalPages || 1));
  if (cur === cursor) return `${cursor} / ${total}`;
  return `${cursor} / ${total} · current ${cur}`;
});

const shellStyle = computed(() => {
  const r = Math.max(120, Number(props.wheelRadius || 320));
  const extentScale = Number(extentScaleNorm.value || 1);
  const thumbScale = Number(thumbScaleNorm.value || 1);
  const h = Math.max(56, Math.min(280, Math.round(96 * thumbScale)));
  const w = Math.max(44, Math.min(220, Math.round(74 * thumbScale)));
  const maskSize = Math.max(170, Math.min(620, Math.round(r * 0.92 * extentScale)));
  const hClip = Math.max(h + 24, Math.min(360, Math.round((h + 26) * extentScale)));
  const vClip = Math.max(w + 32, Math.min(300, Math.round((w + 56) * extentScale)));
  const vTrackH = Math.max(220, Math.min(760, Math.round((h * 3.6) * extentScale)));
  const sliderVh = Math.max(180, Math.min(520, Math.round(280 * extentScale)));
  return {
    "--edge-mask-size": `${maskSize}px`,
    "--wheel-thumb-w": `${w}px`,
    "--wheel-thumb-h": `${h}px`,
    "--wheel-item-half-w": `${Math.round(w / 2)}px`,
    "--wheel-item-half-h": `${Math.round(h / 2)}px`,
    "--wheel-clip-h": `${hClip}px`,
    "--wheel-clip-vw": `${vClip}px`,
    "--wheel-track-h": `${Math.max(h + 20, Math.round(h * 1.22))}px`,
    "--wheel-track-vw": `${Math.max(w + 18, Math.round(w * 1.55))}px`,
    "--wheel-track-vh": `${vTrackH}px`,
    "--wheel-slider-vh": `${sliderVh}px`,
  };
});

const pageEntryMap = computed(() => {
  const m = new Map();
  for (const e of props.wheelPages || []) {
    const p = Number(e?.page || 0);
    if (!Number.isFinite(p) || p <= 0) continue;
    m.set(p, e || {});
  }
  return m;
});

function pageAspect(page) {
  const e = pageEntryMap.value.get(Number(page || 0)) || {};
  const explicit = Number(e?.thumb_aspect || 0);
  if (Number.isFinite(explicit) && explicit > 0) {
    return Math.max(0.45, Math.min(2.2, explicit));
  }
  const w = Number(e?.width || 0);
  const h = Number(e?.height || 0);
  if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
    return Math.max(0.45, Math.min(2.2, w / h));
  }
  return 0.77;
}

function thumbSize(page) {
  const thumbScale = Number(thumbScaleNorm.value || 1);
  const h = Math.max(56, Math.min(280, Math.round(96 * thumbScale)));
  const aspect = pageAspect(page);
  const w = Math.max(44, Math.min(240, Math.round(h * aspect)));
  return { w, h };
}

function wheelItemStyle(page) {
  const rawOffset = Number(page) - Number(cursorPageSafe.value || 1);
  const offset = props.rtl ? -rawOffset : rawOffset;
  const abs = Math.abs(offset);
  const { w, h } = thumbSize(page);
  const spacing = props.wheelPosition === "bottom"
    ? Math.max(44, w + 14)
    : Math.max(44, h * 0.76);
  const r = Math.max(120, Number(props.wheelRadius || 320));
  const flat = r >= 900000;
  const visibleRange = Math.max(2, Math.min(80, Number(props.wheelVisibleRange || 4)));

  let x = 0;
  let y = 0;
  let rotate = "";
  if (props.wheelPosition === "bottom") {
    x = offset * spacing;
    y = flat ? 0 : (x * x) / (2 * r);
    rotate = ` rotateY(${offset * -2.4}deg)`;
  } else {
    // Side strips are pinned so page 1 is always at the TOP: later pages drift
    // downward, independent of reading direction. Previously this used the
    // rtl-flipped `offset`, which put page 1 at the bottom for left-to-right
    // reading and made the strip read the wrong way round. It also now matches
    // the vertical slider below, whose `reverse` already means "1 at the top".
    y = rawOffset * spacing;
    const curve = flat ? 0 : (y * y) / (2 * r);
    x = props.wheelPosition === "left" ? -curve : curve;
    rotate = ` rotateX(${rawOffset * 1.8}deg)`;
  }

  const scale = Math.max(0.56, 1.12 - abs * 0.12);
  const opacity = abs > (visibleRange + 2) ? 0 : Math.max(0.28, 1 - abs * 0.16);
  const zIndex = 400 - abs;
  return {
    transform: `translate3d(${x}px, ${y}px, 0) scale(${scale})${rotate}`,
    opacity: String(opacity),
    zIndex: String(zIndex),
    width: `${w}px`,
    height: `${h}px`,
    marginLeft: `${-Math.round(w / 2)}px`,
    marginTop: `${-Math.round(h / 2)}px`,
    pointerEvents: abs > (visibleRange + 2) ? "none" : "auto",
  };
}

function previewStep(step) {
  const next = Math.max(1, Math.min(Number(props.totalPages || 1), Number(cursorPageSafe.value || 1) + step));
  if (next !== Number(cursorPageSafe.value || 1)) emitPreviewPage(next);
}

function onSliderChange(v) {
  const raw = Number(v || 1);
  const max = Math.max(1, Number(props.totalPages || 1));
  emitPreviewPage(Math.max(1, Math.min(max, raw)));
}

function onWheelPointerDown(event) {
  if (event?.isPrimary === false) return;
  const pointerId = Number(event?.pointerId ?? -1);
  // Deliberately NOT capturing here. A pointer captured on `pointerdown`
  // retargets the matching `pointerup` to the capture element, and the browser
  // derives the `click` target from that retargeted event -- so the `@click` on
  // a thumbnail would never fire and a mouse click on the strip would do
  // nothing. Capture is deferred to the first move past the drag threshold,
  // where a click can no longer be the outcome anyway.
  dragState.value = {
    active: true,
    pointerId,
    x: Number(event?.clientX || 0),
    y: Number(event?.clientY || 0),
    page: Number(cursorPageSafe.value || 1),
    emittedPage: Number(cursorPageSafe.value || 1),
    captured: false,
  };
}

function onWheelPointerMove(event) {
  const state = dragState.value;
  if (!state.active || Number(event?.pointerId ?? -1) !== state.pointerId) return;
  const currentX = Number(event?.clientX || 0);
  const currentY = Number(event?.clientY || 0);
  let origin = state;
  if (!state.captured) {
    const travel = Math.hypot(currentX - state.x, currentY - state.y);
    if (travel < WHEEL_DRAG_THRESHOLD_PX) return;
    // From here on this is a drag, not a tap: take the pointer so the strip
    // keeps tracking even when the finger leaves it. Falling back to the event
    // target keeps a stray move working in environments without capture.
    const target = event?.currentTarget || event?.target;
    try {
      target?.setPointerCapture?.(state.pointerId);
    } catch {
      // A capture that fails is not fatal: the move handler still tracks.
    }
    origin = { ...state, captured: true };
    dragState.value = origin;
  }
  event?.preventDefault?.();
  const next = pageForWheelDrag({
    startPage: origin.page,
    startX: origin.x,
    startY: origin.y,
    currentX,
    currentY,
    totalPages: props.totalPages,
    position: props.wheelPosition,
    rtl: props.rtl,
  });
  if (next === origin.emittedPage) return;
  draggedThisGesture = true;
  dragState.value = { ...origin, emittedPage: next };
  emitPreviewPage(next);
}

function onWheelPointerEnd(event) {
  const state = dragState.value;
  if (!state.active || Number(event?.pointerId ?? -1) !== state.pointerId) return;
  if (state.captured) {
    try {
      event?.currentTarget?.releasePointerCapture?.(state.pointerId);
    } catch {
      // The element can already be gone (strip rebuilt mid-drag); ignore.
    }
  }
  // A release that never passed the drag threshold is a tap: the `click` it
  // produces is left alone so it reaches the thumbnail's own handler.
  dragState.value = { ...state, active: false, captured: false };
}

// The drag lives on the strip, but the `click` belongs to the thumbnail. Once a
// drag has actually started, the click the browser synthesises on release must
// not also jump a page -- that would make one gesture move twice.
function onThumbClick(entry, event) {
  if (draggedThisGesture) {
    draggedThisGesture = false;
    event?.preventDefault?.();
    event?.stopPropagation?.();
    return;
  }
  emit("jump-to-page", Number(entry?.page || 1));
}

function onWheelMouse(event) {
  const dy = Number(event?.deltaY || 0);
  if (!Number.isFinite(dy) || Math.abs(dy) < 4) return;
  previewStep(dy > 0 ? 1 : -1);
}

function wheelSpriteStyle(entry) {
  const w = Math.max(20, Number(entry?.width || 74));
  const h = Math.max(20, Number(entry?.height || 96));
  const bgwRaw = Number(entry?.sheet_w || 0);
  const bghRaw = Number(entry?.sheet_h || 0);
  const hasSheetSize = bgwRaw > 1 && bghRaw > 1;
  const p = Number(entry?.page || 1);
  const sz = thumbSize(p);
  const itemW = Math.max(24, Number(sz.w || 74));
  const itemH = Math.max(24, Number(sz.h || 96));
  const sx = itemW / w;
  const sy = itemH / h;
  const bgw = hasSheetSize ? Math.max(1, bgwRaw * sx) : 0;
  const bgh = hasSheetSize ? Math.max(1, bghRaw * sy) : 0;
  const px = Number(entry?.offset_x || 0) * sx;
  const py = Number(entry?.offset_y || 0) * sy;
  return {
    backgroundImage: `url(${String(entry?.src || "")})`,
    backgroundRepeat: "no-repeat",
    backgroundPosition: `${px}px ${py}px`,
    backgroundSize: hasSheetSize ? `${bgw}px ${bgh}px` : "auto",
    width: "100%",
    height: "100%",
    margin: "0",
  };
}

function canUseSprite(entry) {
  if (String(entry?.mode || "") !== "sprite") return false;
  const src = String(entry?.src || "").trim();
  if (!src) return false;
  const w = Number(entry?.width || 0);
  const h = Number(entry?.height || 0);
  const ox = Number(entry?.offset_x || 0);
  const oy = Number(entry?.offset_y || 0);
  const sw = Number(entry?.sheet_w || 0);
  const sh = Number(entry?.sheet_h || 0);
  const hasSpriteMeta = Math.abs(ox) > 0 || Math.abs(oy) > 0 || (sw > 1 && sh > 1);
  return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0 && hasSpriteMeta;
}
</script>

<style scoped>
.wheel-shell {
  position: fixed;
  z-index: 7;
  pointer-events: none;
  display: flex;
}

.wheel-bottom {
  left: 0;
  right: 0;
  bottom: 0;
  padding-bottom: calc(16px + env(safe-area-inset-bottom));
  flex-direction: column;
  gap: 12px;
  background: radial-gradient(ellipse 100% var(--edge-mask-size) at bottom center, rgba(15, 15, 15, 0.82) 0%, rgba(15, 15, 15, 0.36) 40%, transparent 100%);
}

.wheel-left,
.wheel-right {
  top: 0;
  bottom: 0;
  height: 100%;
  will-change: transform;
  backface-visibility: hidden;
  align-items: center;
  gap: 12px;
}

.wheel-left {
  left: 0;
  padding-left: calc(16px + env(safe-area-inset-left));
  flex-direction: row;
}

.wheel-right {
  right: 0;
  padding-right: calc(16px + env(safe-area-inset-right));
  flex-direction: row-reverse;
}

.wheel-side-mask {
  position: absolute;
  top: 0;
  bottom: 0;
  width: var(--edge-mask-size);
  pointer-events: none;
  filter: none;
}

.mask-left {
  left: 0;
  background: linear-gradient(to right, rgba(12, 14, 20, 0.92) 0%, rgba(12, 14, 20, 0.46) 46%, rgba(12, 14, 20, 0.16) 72%, transparent 100%);
}

.mask-right {
  right: 0;
  background: linear-gradient(to left, rgba(12, 14, 20, 0.92) 0%, rgba(12, 14, 20, 0.46) 46%, rgba(12, 14, 20, 0.16) 72%, transparent 100%);
}

.wheel-track-clip {
  position: relative;
  pointer-events: auto;
  overflow: hidden;
  touch-action: none;
}

.wheel-bottom .wheel-track-clip {
  height: var(--wheel-clip-h);
}

.wheel-left .wheel-track-clip,
.wheel-right .wheel-track-clip {
  width: calc(var(--wheel-thumb-w) + 16px);
  height: 100%;
  overflow: visible;
}

.wheel-track {
  position: relative;
}

.wheel-thumb-placeholder {
  position: absolute;
  inset: 0;
  z-index: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(24, 28, 38, 0.92);
  pointer-events: none;
}

.wheel-track-bottom {
  height: var(--wheel-track-h);
}

.wheel-track-left,
.wheel-track-right {
  width: 100%;
  height: 100%;
}

.wheel-item {
  position: absolute;
  left: 50%;
  top: 50%;
  width: var(--wheel-thumb-w);
  height: var(--wheel-thumb-h);
  margin-left: calc(-1 * var(--wheel-item-half-w));
  margin-top: calc(-1 * var(--wheel-item-half-h));
  border: 0;
  border-radius: 12px;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.16);
  box-shadow: 0 10px 20px rgba(0, 0, 0, 0.4);
  pointer-events: auto;
  cursor: pointer;
  padding: 0;
  transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.25s ease;
}

.wheel-mask {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  transition: background 0.25s ease;
  pointer-events: none;
  z-index: 2;
}

.wheel-item.active .wheel-mask {
  background: rgba(0, 0, 0, 0);
}

.wheel-label-wrap {
  position: absolute;
  right: 6px;
  bottom: 6px;
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  pointer-events: none;
  z-index: 3;
}

.wheel-label {
  background: rgba(12, 14, 20, 0.62);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  opacity: 0.84;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.32);
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.wheel-item:not(.active) .wheel-label {
  opacity: 0.5;
  transform: scale(0.85);
}

.wheel-item.active {
  outline: 2px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 0 0 3px rgba(255, 136, 0, 0.45), 0 12px 22px rgba(0, 0, 0, 0.46);
}

.wheel-item.current {
  box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.5), 0 10px 20px rgba(0, 0, 0, 0.42);
}

.wheel-thumb {
  position: absolute;
  inset: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

.wheel-thumb-sprite {
  background-color: transparent;
}

.wheel-slider-row {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.wheel-slider-bottom {
  width: min(60vw, 560px);
  max-width: calc(100vw - 24px);
  margin: 0 auto;
  flex-direction: column;
}

.wheel-slider-bottom :deep(.v-slider) {
  width: 100%;
}

.wheel-slider-left,
.wheel-slider-right {
  width: auto;
  min-width: 72px;
  height: var(--wheel-slider-vh);
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.wheel-progress-text {
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
  text-align: center;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.8);
}

.wheel-slider-left :deep(.v-slider),
.wheel-slider-right :deep(.v-slider) {
  height: 100%;
  width: 28px;
}

.wheel-slider-left :deep(.v-slider .v-input__control),
.wheel-slider-right :deep(.v-slider .v-input__control) {
  min-height: 100%;
}
</style>
