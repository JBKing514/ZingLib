<template>
  <div ref="rootRef" class="feed-pull" :class="{ 'is-armed': armed, 'is-busy': busy }">
    <button
      type="button"
      class="feed-pull-circle"
      :disabled="busy"
      :aria-label="t('home.pull.action')"
      @click="advance"
    >
      <v-icon icon="mdi-chevron-triple-down" size="26" class="feed-pull-arrow" />
    </button>
    <div class="feed-pull-hint text-caption text-medium-emphasis">
      {{ busy ? t('home.pull.loading') : t('home.pull.hint', { page: nextPage }) }}
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
  // The page a successful pull would land on -- shown so the hint is concrete.
  nextPage: { type: Number, default: 2 },
  busy: { type: Boolean, default: false },
  t: { type: Function, required: true },
});

const emit = defineEmits(["advance"]);

// How long the affordance must have been on screen before a downward gesture
// counts. Without it the very flick that brought the user to the bottom would
// turn the page -- which is exactly the behaviour that makes manual paging
// impossible.
const ARM_DELAY_MS = 550;
// Pause after a turn so one long inertial scroll cannot burn through pages.
const COOLDOWN_MS = 700;
const WHEEL_STEP = 12;
const TOUCH_STEP = 28;

const rootRef = ref(null);
const armed = ref(false);

let observer = null;
let armedAt = 0;
let lastAdvanceAt = 0;
let touchStartY = 0;
let touchActive = false;

function atBottom() {
  if (typeof window === "undefined") return false;
  const doc = document;
  const scrolled = Math.max(
    Number(window.scrollY || 0),
    Number(doc?.documentElement?.scrollTop || 0),
    Number(doc?.body?.scrollTop || 0)
  );
  const viewport = Number(window.innerHeight || 0);
  const height = Math.max(
    Number(doc?.documentElement?.scrollHeight || 0),
    Number(doc?.body?.scrollHeight || 0)
  );
  return scrolled + viewport >= height - 48;
}

function canAdvance() {
  if (props.busy) return false;
  if (!armed.value) return false;
  if (Date.now() - lastAdvanceAt < COOLDOWN_MS) return false;
  // The delay is what separates "just arrived at the bottom" from "pulled again".
  if (Date.now() - armedAt < ARM_DELAY_MS) return false;
  return atBottom();
}

function advance() {
  // The explicit tap path ignores the arming delay on purpose: a click is already
  // an unambiguous request, and it is what keyboard/mouse users will reach for.
  if (props.busy) return;
  if (Date.now() - lastAdvanceAt < COOLDOWN_MS) return;
  if (!atBottom()) return;
  lastAdvanceAt = Date.now();
  armed.value = false;
  emit("advance");
}

function onWheel(event) {
  if (Number(event?.deltaY || 0) < WHEEL_STEP) return;
  if (!canAdvance()) return;
  lastAdvanceAt = Date.now();
  armed.value = false;
  emit("advance");
}

function onTouchStart(event) {
  const y = Number(event?.touches?.[0]?.clientY);
  if (!Number.isFinite(y)) return;
  touchStartY = y;
  touchActive = true;
}

function onTouchMove(event) {
  if (!touchActive) return;
  const y = Number(event?.touches?.[0]?.clientY);
  if (!Number.isFinite(y)) return;
  // Finger moving up = content moving down = "keep pulling".
  if (touchStartY - y < TOUCH_STEP) return;
  touchActive = false;
  if (!canAdvance()) return;
  lastAdvanceAt = Date.now();
  armed.value = false;
  emit("advance");
}

function onTouchEnd() {
  touchActive = false;
}

onMounted(() => {
  if (typeof window === "undefined") return;
  if (typeof IntersectionObserver !== "undefined" && rootRef.value) {
    observer = new IntersectionObserver(
      (entries) => {
        const first = entries[0];
        if (!first) return;
        if (first.isIntersecting && !armed.value) {
          armed.value = true;
          armedAt = Date.now();
        } else if (!first.isIntersecting) {
          armed.value = false;
        }
      },
      { root: null, rootMargin: "0px 0px -8px 0px", threshold: 0.6 }
    );
    observer.observe(rootRef.value);
  } else {
    // No observer: behave as if it were always on screen rather than never arming.
    armed.value = true;
    armedAt = Date.now();
  }
  window.addEventListener("wheel", onWheel, { passive: true });
  window.addEventListener("touchstart", onTouchStart, { passive: true });
  window.addEventListener("touchmove", onTouchMove, { passive: true });
  window.addEventListener("touchend", onTouchEnd, { passive: true });
  window.addEventListener("touchcancel", onTouchEnd, { passive: true });
});

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  if (typeof window === "undefined") return;
  window.removeEventListener("wheel", onWheel);
  window.removeEventListener("touchstart", onTouchStart);
  window.removeEventListener("touchmove", onTouchMove);
  window.removeEventListener("touchend", onTouchEnd);
  window.removeEventListener("touchcancel", onTouchEnd);
});
</script>

<style scoped>
.feed-pull {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 14px 0 22px;
  user-select: none;
}
.feed-pull-circle {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  background: rgba(var(--v-theme-surface-variant), 0.4);
  color: rgba(var(--v-theme-primary), 1);
  cursor: pointer;
  transition: transform 0.18s ease, background 0.18s ease;
}
.feed-pull-circle:disabled {
  cursor: default;
  opacity: 0.55;
}
.feed-pull.is-armed .feed-pull-circle {
  background: rgba(var(--v-theme-primary), 0.14);
}
.feed-pull-arrow {
  /* Arrow points down while at rest; the nudge says "there is another page this
     way" without ever moving the user there by itself. */
  animation: feed-pull-nudge 1.6s ease-in-out infinite;
}
/* While a page is loading the arrow only dims. It used to spin, which read as
   decoration rather than progress -- the disabled button and the "loading" hint
   already say everything the spin was saying. */
.feed-pull.is-busy .feed-pull-arrow {
  animation: none;
  opacity: 0.45;
}
@keyframes feed-pull-nudge {
  0%, 100% { transform: translateY(0); opacity: 0.7; }
  50% { transform: translateY(3px); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .feed-pull-arrow {
    animation: none;
  }
}
</style>
