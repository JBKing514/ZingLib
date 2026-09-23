import { reactive } from "vue";
import { defineStore } from "pinia";

// Session-only overlay: previews update without replacing or reordering feed rows.
export const usePreviewProgressStore = defineStore("previewProgress", () => {
  const pages = reactive(new Map());

  function publish({ arcid, page } = {}) {
    const key = String(arcid || "").trim();
    const value = Number(page);
    if (!key || !Number.isFinite(value) || value < 1) return;
    pages.set(key, Math.floor(value));
  }

  function resumePage(item) {
    const key = String(item?.arcid || "").trim();
    const value = Number(pages.get(key) ?? item?.raw?.bookmark ?? 1);
    return Number.isFinite(value) ? Math.max(1, Math.floor(value)) : 1;
  }

  return { publish, resumePage };
});
