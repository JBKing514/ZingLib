// Round 40: the reader grows an end screen -- one page past the last one.
//
// Crossing the last page lands there (never straight into another gallery), the
// *next* forward action continues into the next gallery of the order the reader
// was opened with, and the bottom of that screen carries a "guess you like"
// strip scored from this gallery's own cover vector plus its tags.
//
// The ordering cannot be recomputed server-side from an arcid alone (the feed's
// sort, filters and search all live in the client), so the reader is handed the
// list it was opened from. That hand-off and the two-step exit are what this
// file pins down.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { ref } from "vue";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const json = value => JSON.stringify(value);

function makeQueueStore() {
  const source = read("./src/stores/readerQueueStore.js");
  const body = source
    .split("\n")
    .filter(line => !line.trimStart().startsWith("import "))
    .join("\n")
    .replace("export const useReaderQueueStore", "const useReaderQueueStore");
  const factory = runInNewContext(`(() => { ${body}\nreturn useReaderQueueStore; })()`, {
    ref,
    // Real Pinia unwraps refs on access; the stub must too, or `entries` would
    // hand back a ref instead of the array.
    defineStore: (_id, setup) => () => {
      const raw = setup();
      return new Proxy(raw, {
        get(target, key) { const v = target[key]; return v && v.__v_isRef ? v.value : v; },
      });
    },
  });
  return factory();
}

const feed = [
  { arcid: "a", title: "A" },
  { arcid: "b", title: "B" },
  { arcid: "c", title: "C" },
];

test("the queue walks forward through the feed it was handed", () => {
  const queue = makeQueueStore();
  queue.setQueue(feed, "local_gallery");

  assert.equal(queue.knows("b"), true);
  assert.equal(queue.knows("zz"), false);
  assert.equal(json(queue.nextAfter("a")), json({ arcid: "b", title: "B" }));
  assert.equal(json(queue.nextAfter("b")), json({ arcid: "c", title: "C" }));
  // The last one has nowhere to go -- and a gallery outside the list never
  // advertises a "next" either, so the affordance simply hides.
  assert.equal(queue.nextAfter("c"), null);
  assert.equal(queue.nextAfter("zz"), null);
  assert.equal(queue.nextAfter(""), null);
});

test("a hand-off that carries no title still yields a usable next entry", () => {
  const queue = makeQueueStore();
  queue.setQueue([{ arcid: "x" }, { arcid: "y" }, { arcid: "" }, null], "local_search");
  assert.equal(json(queue.nextAfter("x")), json({ arcid: "y", title: "" }));
  assert.equal(queue.knows(""), false, "empty arcids are dropped at hand-off");
  queue.clear();
  assert.equal(queue.knows("x"), false);
});

test("the reader clamps to the end screen and keeps progress off it", () => {
  const page = read("./src/views/ReaderPage.vue");

  assert.match(page, /const endScreenPage = computed\(\(\) => Math\.max\(1, Number\(totalPages\.value \|\| 1\)\) \+ 1\);/);
  assert.match(page, /const onEndScreen = computed\(\(\) => Number\(currentPage\.value \|\| 1\) > Number\(totalPages\.value \|\| 1\)\);/);
  assert.match(page, /const progressPage = computed\(\(\) => Math\.max\(1, Math\.min\(Number\(totalPages\.value \|\| 1\), Number\(currentPage\.value \|\| 1\)\)\)\);/);

  // setPage's upper clamp is the end screen, not the last page...
  assert.match(page, /Math\.min\(endScreenPage\.value, Number\(next\) \|\| 1\)/);
  // ...and the side effects that only make sense on a real page are gated.
  assert.match(page, /if \(manifestReady\.value && !isEnd\) \{\s*\n\s*syncBookmarkDebounced\(clamped, false\);/);
  assert.match(page, /else if \(!isEnd\) preloadNearby\(\);/);
  assert.match(page, /if \(turned && !isEnd\) \{/);

  // Progress must never be published as page N+1, or the preview card would
  // offer "resume at" a page that does not exist.
  assert.doesNotMatch(page, /previewProgressStore\.publish\(\{ arcid: arcid\.value, page: currentPage\.value \}\)/);
  assert.equal((page.match(/previewProgressStore\.publish\(\{ arcid: arcid\.value, page: progressPage\.value \}\)/g) || []).length, 2);
  assert.match(page, /page: Number\(progressPage\.value \|\| 1\),/);

  // The end screen draws no archive page, so it must not light the load overlay.
  assert.match(page, /if \(Number\(p \|\| 1\) > Number\(totalPages\.value \|\| 1\)\) \{/);
});

test("leaving the gallery takes two deliberate forward actions", () => {
  const page = read("./src/views/ReaderPage.vue");

  assert.match(page, /function nextPage\(\) \{[\s\S]*?if \(onEndScreen\.value\) \{\s*\n\s*goNextGallery\(\);\s*\n\s*return;/);
  assert.match(page, /function goNextGallery\(\) \{/);
  assert.match(page, /router\.replace\(\{ name: "reader", params: \{ arcid: next \}, query: \{ page: "1" \} \}\)/);
});

test("a gallery switch cannot write its page number onto the gallery being left", () => {
  const page = read("./src/views/ReaderPage.vue");
  // params and query change in one navigation and the query watcher runs first.
  assert.match(
    page,
    /watch\(\(\) => route\.query\.page, \(\) => \{\s*\n\s*if \(route\.name !== "reader"\) return;\s*\n(?:\s*\/\/[^\n]*\n)*\s*if \(String\(route\.params\.arcid \|\| ""\)\.trim\(\) !== arcid\.value\) return;/,
  );
  // ...and the candidates of the old gallery are dropped with it.
  assert.match(page, /function resetEndRecs\(\) \{[\s\S]*?endRecsSeq \+= 1;/);
  assert.match(page, /resetEndRecs\(\);\s*\n\s*resetContinuousPageRefs\(\);/);
  assert.match(page, /localPrefetchSeen\.clear\(\);\s*\n\s*resetEndRecs\(\);/);
});

test("the candidates load lazily, from this gallery, once", () => {
  const page = read("./src/views/ReaderPage.vue");
  assert.match(page, /import \{ closeReaderSession, getReaderManifest, getReaderSessionStatus, getReaderSimilar,/);
  assert.match(page, /if \(isEnd\) loadEndRecs\(\);/);
  assert.match(page, /if \(!force && \(endRecsLoading\.value \|\| endRecs\.value\.length\)\) return;/);
  assert.match(page, /const generation = \+\+endRecsSeq;/);
  assert.match(page, /if \(generation !== endRecsSeq\) return;/);
  assert.match(page, /if \(el\.scrollHeight - el\.scrollTop - el\.clientHeight > 700\) return;/);
  // Disabled by config, and the strip simply does not render.
  assert.match(page, /settingsStore\.config\?\.READER_REC_ENABLED !== false/);
  assert.match(page, /:show-recs="endRecsEnabled"/);

  const api = read("./src/api.js");
  assert.match(api, /export async function getReaderSimilar\(arcid, limit = 6\) \{/);
  assert.match(api, /`\/reader\/\$\{encodeURIComponent\(String\(arcid \|\| ""\)\)\}\/similar`/);
});

test("the end panel is click-through except for its two islands", () => {
  const panel = read("./src/components/reader/ReaderEndPanel.vue");
  assert.match(panel, /reader-end-hint/);
  assert.match(panel, /reader-end-recs/);
  assert.match(panel, /t\('reader\.end\.rec_title'\)/);
  assert.match(panel, /t\('reader\.end\.hint'\)/);
  assert.match(panel, /t\('reader\.end\.next'\)/);
  assert.match(panel, /inline: \{ type: Boolean, default: false \}/);
  assert.match(panel, /class="reader-end" :class="\{ 'reader-end-inline': inline \}"/);
  // The root must not swallow the reader's tap zones underneath it.
  assert.match(panel, /\.reader-end \{[\s\S]*?pointer-events: none;/);
  assert.match(panel, /\.reader-end-hint \{[\s\S]*?pointer-events: auto;/);
  assert.match(panel, /\.reader-end-recs \{[\s\S]*?pointer-events: auto;/);

  // Both reader modes render it: overlay in paged, a trailing block in continuous.
  const page = read("./src/views/ReaderPage.vue");
  assert.equal((page.match(/<ReaderEndPanel/g) || []).length, 2);
  assert.match(page, /<ReaderEndPanel\s*\n\s*inline/);
  assert.match(page, /@next-gallery="goNextGallery"/);
  assert.match(page, /@open-item="openEndRec"/);
});

test("the dashboard hands over the order that is on screen", () => {
  const page = read("./src/views/DashboardScopePage.vue");
  assert.match(page, /import \{ useReaderQueueStore \} from "\.\.\/stores\/readerQueueStore";/);
  assert.match(page, /useReaderQueueStore\(\)\.setQueue\(/);
  assert.match(page, /\(this\.filteredHomeItems \|\| \[\]\)\.map\(\(row\) => \(\{/);
  assert.match(page, /__queue_title: this\.getGalleryTitle\(row\),/);
  // A missing queue must never block opening the reader.
  assert.match(page, /useReaderQueueStore\(\)\.setQueue\([\s\S]*?\} catch \{/);
});

test("the endpoint scores cover cosine plus tag overlap, never the page vectors", () => {
  const service = read("../webapi/services/rec_service_local.py");
  const start = service.indexOf("def similar_items_for_gallery(");
  assert.ok(start > 0, "similar_items_for_gallery must exist");
  const similar = service.slice(start, service.indexOf("\ndef _local_cache_lock", start) > 0
    ? service.indexOf("\ndef _local_cache_lock", start)
    : undefined);

  assert.match(similar, /def similar_items_for_gallery\(arcid: str, \*, limit: int = 6, cfg: dict\[str, Any\] \| None = None\)/);
  // Reference = this gallery's own cover vector, deliberately not the page one
  // (the reader asks at the end, where the page is blank credits art).
  assert.match(similar, /SELECT arcid, tags, visual_embedding::text AS cover_vec FROM works /);
  assert.match(similar, /visual_embedding IS NOT NULL AND arcid <> %s /);
  assert.doesNotMatch(similar, /page_visual_embedding/);
  // Normalised weights, normalised cosine, Dice overlap.
  assert.match(similar, /visual_weight \/= total_w\n/);
  assert.match(similar, /tag_weight \/= total_w\n/);
  assert.match(similar, /vis = max\(0\.0, min\(1\.0, float\(cos\)\)\)/);
  assert.match(service, /return float\(\(2\.0 \* inter\) \/ \(len\(ref\) \+ len\(other\)\)\)/);
  assert.match(service, /_REC_TAG_IGNORE_PREFIXES = \("uploader:", "timestamp:", "date_", "source:", "system:"\)/);

  const router = read("../webapi/routers/reader.py");
  assert.match(router, /@router\.get\("\/api\/reader\/\{arcid\}\/similar"\)/);
  assert.match(router, /return similar_items_for_gallery\(safe_arcid, limit=int\(limit\), cfg=cfg\)/);
  assert.match(router, /if not _as_bool\(cfg\.get\("READER_REC_ENABLED"\), True\):/);

  const constants = read("../webapi/core/constants.py");
  assert.match(constants, /"READER_REC_ENABLED": \{"type": "bool", "default": True\}/);
  assert.match(constants, /"READER_REC_VISUAL_WEIGHT": \{"type": "float", "default": 0\.6/);
  assert.match(constants, /"READER_REC_TAG_WEIGHT": \{"type": "float", "default": 0\.4/);
  assert.match(constants, /"READER_REC_LIMIT": \{"type": "int", "default": 6/);
});

test("the new reader copy exists in both languages", () => {
  const zh = JSON.parse(read("./src/i18n/zh.json"));
  const en = JSON.parse(read("./src/i18n/en.json"));
  const keys = [
    "reader.end.title",
    "reader.end.hint",
    "reader.end.hint_last",
    "reader.end.next",
    "reader.end.back_shelf",
    "reader.end.rec_title",
    "reader.end.rec_loading",
    "reader.end.rec_empty",
    "reader.end.rec_failed",
  ];
  for (const key of keys) {
    assert.ok(zh[key], `zh missing ${key}`);
    assert.ok(en[key], `en missing ${key}`);
  }
  assert.equal(zh["reader.end.rec_title"], "猜你想看");
  assert.equal(json(Object.keys(zh).sort()), json(Object.keys(en).sort()), "i18n key sets must stay identical");
});
