import { reactive } from "vue";
import { defineStore } from "pinia";

// Session-only overlay: previews update without replacing or reordering feed rows.
export const usePreviewProgressStore = defineStore("previewProgress", () => {
  const pages = reactive(new Map());
  // Total page count per gallery, published by the reader once its manifest is
  // known. The capsule needs a denominator to render a percentage; without it a
  // page number alone cannot say how far through the gallery the user is.
  const totals = reactive(new Map());

  function publish({ arcid, page, total } = {}) {
    const key = String(arcid || "").trim();
    if (!key) return;
    const value = Number(page);
    if (Number.isFinite(value) && value >= 1) pages.set(key, Math.floor(value));
    const t = Number(total);
    if (Number.isFinite(t) && t > 0) totals.set(key, Math.floor(t));
  }

  function resumePage(item) {
    const key = String(item?.arcid || "").trim();
    const value = Number(pages.get(key) ?? item?.raw?.bookmark ?? 1);
    return Number.isFinite(value) ? Math.max(1, Math.floor(value)) : 1;
  }

  /**
   * Reading progress as a whole percentage, or `null` when it cannot be stated.
   *
   * Returning `null` rather than 0 matters: "not started" and "no idea" are
   * different, and a card that shows 0% for a gallery the user has never opened
   * would be lying. Callers hide the capsule on `null`.
   *
   * A finished gallery reads 100 by pinning page == total, so the last page is
   * not reported as `(total-1)/total`.
   */
  function progressPercent(item) {
    const key = String(item?.arcid || "").trim();
    if (!key) return null;
    const total = Number(
      totals.get(key)
      ?? item?.page_count
      ?? item?.meta?.page_count
      ?? item?.raw?.page_count
      ?? 0
    );
    if (!Number.isFinite(total) || total <= 0) return null;
    // Home/search rows already carry the persisted bookmark. Session progress
    // wins while the reader is open, then the database value supplies the
    // initial capsule after a reload.
    const page = Number(pages.get(key) ?? item?.raw?.bookmark ?? item?.bookmark ?? 0);
    if (!Number.isFinite(page) || page <= 0) return null;
    const ratio = Math.max(0, Math.min(1, page / total));
    return Math.round(ratio * 100);
  }

  return { publish, resumePage, progressPercent, pages, totals };
});
