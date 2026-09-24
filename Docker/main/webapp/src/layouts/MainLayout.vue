<template>
  <div v-if="ui.t">
    <app-sidebar
      v-if="!appStore.isRecoveryMode && !hideReaderChrome"
      :model-value="ui.drawer"
      :rail="ui.rail"
      :brand-logo="ui.brandLogo"
      :nav-items="ui.navItems"
      :tab="ui.tab"
      :home-tab="dashboardStore.homeTab"
      :t="ui.t"
      @update:model-value="ui.drawer = $event"
      @update:rail="ui.rail = $event"
      @go-tab="onSidebarGoTab"
      @go-home="onSidebarGoHome"
    />

    <app-top-bar
      v-if="!hideReaderChrome"
      :current-title-key="ui.currentTitleKey"
      :theme-mode-icon="ui.themeModeIcon"
      :lang-options="ui.langOptions"
      :lang="ui.lang"
      :zoom-options="ui.pageZoomOptions"
      :page-zoom="ui.pageZoom"
      :notices="ui.notices"
      :auth-user="appStore.authUser"
      :safe-area-top-inset="settingsStore.config?.READER_VIEWPORT_FIT_COVER !== false"
      :t="ui.t"
      @toggle-drawer="ui.drawer = !ui.drawer"
      @cycle-theme="ui.cycleThemeMode"
      @update:lang="ui.setLangValue($event)"
      @update:zoom="ui.setPageZoom($event)"
      @dismiss-notice="ui.dismissNotice"
      @notice-action="ui.runNoticeAction"
      @clear-all-notices="ui.clearAllNotices"
      @go-settings="ui.goTab('settings')"
      @logout="ui.logoutNow"
    />

    <v-main>
      <v-container fluid :class="[hideReaderChrome ? 'pa-0' : 'pa-6', ui.tab === 'chat' ? 'chat-page-container' : '']">
        <RouterView v-slot="{ Component }">
          <KeepAlive include="DashboardPage">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </v-container>
    </v-main>

    <div v-if="!hideReaderChrome && ui.tab === 'dashboard' && dashboardStore.showScrollQuickActions" class="quick-fab-wrap" :style="dashboardStore.quickFabStyle">
      <v-btn color="secondary" icon="mdi-magnify" size="large" class="quick-fab" @click="dashboardStore.quickSearchOpen = true" />
      <v-btn color="info" icon="mdi-filter-variant" size="large" class="quick-fab" @click="dashboardStore.homeFiltersOpen = true" />
      <v-btn
        v-if="dashboardTab === 'local_gallery'"
        color="primary"
        icon="mdi-sort"
        size="large"
        class="quick-fab"
        @click="dashboardStore.openLocalSortDialog()"
      />
      <v-btn color="primary" icon="mdi-arrow-up" size="large" class="quick-fab" @click="dashboardStore.scrollToTop" />
    </div>
  </div>
</template>

<script setup>
import { computed, toRef } from "vue";
import { useRoute } from "vue-router";
import { useLayoutStore } from "../stores/layoutStore";
import { useDashboardStore } from "../stores/dashboardStore";
import { useSettingsStore } from "../stores/settingsStore";
import { useAppStore } from "../stores/appStore";
import { useSidebarSwipe } from "../composables/useSidebarSwipe";
import AppSidebar from "./AppSidebar.vue";
import AppTopBar from "./AppTopBar.vue";

const ui = useLayoutStore();
const dashboardStore = useDashboardStore();
const settingsStore = useSettingsStore();
const appStore = useAppStore();
const route = useRoute();

const hideReaderChrome = computed(() => {
  if (route.name !== "reader") return false;
  return settingsStore.config?.READER_HIDE_APP_UI !== false;
});

const dashboardTab = computed(() => String(dashboardStore.homeTab || "local_gallery"));

// The shell, not the page, owns the sidebar gesture -- so the toolbox, the XP map
// and the settings pages all behave like the feed does. The reader hides the whole
// chrome, and the recovery screen has no sidebar, so both opt out: there the swipe
// would move something the user cannot see.
const sidebarSwipeEnabled = computed(() => !appStore.isRecoveryMode && !hideReaderChrome.value);

useSidebarSwipe({
  drawer: toRef(ui, "drawer"),
  rail: toRef(ui, "rail"),
  enabled: sidebarSwipeEnabled,
});

function onSidebarGoTab(key) {
  ui.goTab(key);
}

function onSidebarGoHome(homeTab) {
  const key = String(homeTab || "local_gallery");
  // Set the store value first so `pathForTab("dashboard")` builds the right
  // ?local_tab= URL, then let goTab drive the navigation and the highlight.
  ui.setHomeTab(key);
  dashboardStore.setHomeTab(key);
  ui.goTab("dashboard");
}

</script>
