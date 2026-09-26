/**
 * Which reader actions are available on which page.
 *
 * The reader's "end screen" is a virtual page: page `N+1` of an `N`-page
 * gallery, drawn by the reader itself rather than served as an image. It has no
 * page content to seed from, so anything derived from "the page you are looking
 * at" has nothing to work with there.
 *
 * Kept out of the SFC on purpose: `ReaderPage.vue` is `<script setup>`, which
 * cannot carry an ES module export, and these are plain predicates with no
 * component state in them -- exactly what a unit test can pin directly.
 */

/** The virtual end-screen page: one past the last real page. */
export function readerEndScreenPage(total) {
  return Math.max(1, Number(total || 1)) + 1;
}

/** True when `page` is the end screen rather than a real page. */
export function isReaderEndScreen(page, total) {
  return Number(page || 1) > Math.max(1, Number(total || 1));
}

/**
 * May the rabbit-hole overlay be opened from `page`?
 *
 * It is seeded from the current page's own vector and tags, so on the end screen
 * it could only ever open empty. Long-pressing there used to open that empty
 * overlay; refusing here is the whole fix.
 */
export function canOpenReaderRabbitHole(page, total) {
  return !isReaderEndScreen(page, total);
}
