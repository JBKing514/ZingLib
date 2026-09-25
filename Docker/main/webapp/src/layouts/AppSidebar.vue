<template>
  <v-navigation-drawer
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :rail="!mobile && rail"
    :width="280"
    :temporary="mobile"
    class="app-sidebar-drawer"
  >
    <div class="drawer-brand px-3 py-4 d-flex align-center" style="min-height: 64px;">
      <v-avatar rounded="lg" size="36" class="mr-3">
        <img :src="brandLogo" alt="ZingLib" style="width: 100%; height: 100%; object-fit: cover;" />
      </v-avatar>
      <div v-if="!(!mobile && rail)" class="text-subtitle-1 font-weight-bold text-truncate">ZingLib</div>
    </div>

    <v-divider />

    <v-list nav density="comfortable" class="px-2">
      <v-list-item
        v-for="item in homeNavItems"
        :key="`home-${item.homeTab}`"
        :active="tab === 'dashboard' && homeTab === item.homeTab"
        :prepend-icon="item.icon"
        :title="t(item.title)"
        color="primary"
        rounded="lg"
        class="mb-1"
        @click="onNavClick('go-home', item.homeTab)"
      />

      <v-divider class="my-2" />

      <v-list-item
        v-for="item in sideNavItems"
        :key="item.key"
        :active="tab === item.key"
        :prepend-icon="item.icon"
        :title="t(item.title)"
        color="primary"
        rounded="lg"
        class="mb-1"
        @click="onNavClick('go-tab', item.key)"
      />
    </v-list>

    <template #append>
      <v-divider />
      <div class="pa-2">
        <v-btn
          block
          variant="text"
          color="medium-emphasis"
          prepend-icon="mdi-bug-outline"
          href="https://github.com/JBKing514/ZingLib/issues"
          target="_blank"
          rel="noopener noreferrer"
          class="mb-1 justify-start"
        >
          <span v-if="mobile || !rail">{{ t('nav.feedback') }}</span>
        </v-btn>
        <v-btn
          v-if="!mobile"
          block
          variant="text"
          color="medium-emphasis"
          @click="emit('update:rail', !rail)"
          class="px-0"
        >
          <v-icon>{{ rail ? 'mdi-chevron-right' : 'mdi-chevron-left' }}</v-icon>
          <span v-if="!rail" class="ml-2">{{ t('nav.compact') }}</span>
        </v-btn>
      </div>
    </template>
  </v-navigation-drawer>
</template>

<script setup>
import { computed } from "vue";
import { useDisplay } from "vuetify";

const props = defineProps({
  modelValue: { type: Boolean, default: true },
  rail: { type: Boolean, default: false },
  brandLogo: { type: String, default: "" },
  navItems: { type: Array, default: () => [] },
  tab: { type: String, default: "dashboard" },
  // Which dashboard sub-tab the library rail is pointing at, so the active
  // highlight can tell "Local Library" apart from "Favorites" and "History".
  homeTab: { type: String, default: "local_gallery" },
  t: { type: Function, required: true },
});

const emit = defineEmits(["update:modelValue", "update:rail", "go-tab", "go-home"]);

const { mobile } = useDisplay();

// One tap has to both navigate and put the drawer away. Emitting the route change
// on its own left the drawer to close itself through the model round-trip, and on
// a phone the overlay drawer's own close transition swallowed the first tap
// (`inert` while it is momentarily inactive), so the user had to tap twice. Both
// halves are written here, in the order the user means them: the destination is
// chosen first, then the panel that carried the tap gets out of the way.
function onNavClick(event, value) {
  emit(event, value);
  if (mobile.value) emit("update:modelValue", false);
}

const homeNavItems = computed(() => {
  return (props.navItems || []).filter((x) => String(x?.homeTab || "") !== "");
});

const sideNavItems = computed(() => {
  return (props.navItems || []).filter((x) => String(x?.homeTab || "") === "");
});
</script>

<style scoped>
.app-sidebar-drawer {
  flex-shrink: 0;
  z-index: 1006;
  overscroll-behavior: contain;
}

.app-sidebar-drawer :deep(.v-navigation-drawer__content) {
  overscroll-behavior: contain;
  overscroll-behavior-y: contain;
  -webkit-overflow-scrolling: touch;
  touch-action: pan-y;
}

</style>
