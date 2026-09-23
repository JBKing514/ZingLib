import { ref } from "vue";
import { defineStore } from "pinia";

// Session-only reading queue. The reader has to answer "what comes after this
// gallery?" but the ordering lives entirely in the client (the feed's sort is
// applied server-side only per request, and a feed can be filtered/searched in
// ways the server cannot replay from an arcid). So whoever opens the reader
// hands over the ordered list it was looking at, and the reader just walks it.
export const useReaderQueueStore = defineStore("readerQueue", () => {
  const entries = ref([]);
  const origin = ref("");

  function setQueue(items, label = "") {
    const list = Array.isArray(items) ? items : [];
    entries.value = list
      .map((it) => ({
        arcid: String(it?.arcid || "").trim(),
        title: String(it?.__queue_title || it?.title || "").trim(),
      }))
      .filter((row) => !!row.arcid);
    origin.value = String(label || "").trim();
  }

  function clear() {
    entries.value = [];
    origin.value = "";
  }

  /** The entry that follows `arcid` in the list the reader was opened from. */
  function nextAfter(arcid) {
    const key = String(arcid || "").trim();
    if (!key) return null;
    const list = entries.value || [];
    const idx = list.findIndex((row) => String(row?.arcid || "").trim() === key);
    if (idx < 0) return null;
    for (let i = idx + 1; i < list.length; i += 1) {
      const row = list[i];
      const next = String(row?.arcid || "").trim();
      if (next && next !== key) return { arcid: next, title: String(row?.title || "").trim() };
    }
    return null;
  }

  /** True when `arcid` is part of the list, i.e. "next" is a meaningful idea. */
  function knows(arcid) {
    const key = String(arcid || "").trim();
    if (!key) return false;
    return (entries.value || []).some((row) => String(row?.arcid || "").trim() === key);
  }

  return { entries, origin, setQueue, clear, nextAfter, knows };
});
