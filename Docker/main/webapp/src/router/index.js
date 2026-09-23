import { createRouter, createWebHashHistory } from "vue-router";

const routes = [
  {
    path: "/",
    component: () => import("../layouts/MainLayout.vue"),
    children: [
      { path: "", redirect: "/dashboard" },
      { path: "dashboard", name: "dashboard", component: () => import("../views/DashboardPage.vue") },
      { path: "reader/:arcid", name: "reader", component: () => import("../views/ReaderPage.vue") },
      { path: "control", name: "control", redirect: { name: "tools", query: { tab: "tasks" } } },
      { path: "audit", name: "audit", redirect: { name: "tools", query: { tab: "tasks" } } },
      { path: "xp", name: "xp", component: () => import("../views/XpPage.vue") },
      { path: "tools", name: "tools", component: () => import("../views/ToolsPage.vue") },
      {
        path: "settings",
        component: () => import("../views/SettingsPage.vue"),
        children: [
          { path: "", redirect: { name: "settings-general" } },
          { path: "general", name: "settings-general", component: () => import("../views/settings/GeneralSettingsPage.vue") },
          { path: "data-clean", name: "settings-data-clean", component: () => import("../views/settings/DataCleanSettingsPage.vue") },
          { path: "search", name: "settings-search", component: () => import("../views/settings/SearchSettingsPage.vue") },
          { path: "reader", name: "settings-reader", component: () => import("../views/settings/ReaderSettingsPage.vue") },
          { path: "other", name: "settings-other", component: () => import("../views/settings/OtherSettingsPage.vue") },
          { path: "local-lib", name: "settings-local-lib", component: () => import("../views/settings/LocalLibSettingsPage.vue") },
        ],
      },
    ],
  },
  {
    path: "/login",
    name: "login",
    component: () => import("../views/AuthPage.vue"),
  },
  {
    path: "/:pathMatch(.*)*",
    redirect: "/dashboard",
  },
];

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
});
