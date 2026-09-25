// Round 58: the double-page spread has to open the pair on the side the
// reading direction starts from.
//
// The bug this pins: with `READER_DIRECTION=rtl` the reader landed on the right
// start page (3) but drew the spread as 3|2 -- the earlier page on the left,
// i.e. a right-to-left cursor rendered left-to-right. Left-to-right was fine
// (3|4), which is exactly why it went unnoticed.
//
// The cause was structural rather than arithmetic: the reader computed an
// ordered *primary/secondary* pair and then flowed them into the DOM in that
// order, so the meaning of "first" silently became "left". Any fix that keeps
// two rank-ordered values and swaps them at render time re-introduces the bug
// the moment someone reorders the template, so what is asserted here is that
// the two slots are bound by *side*.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

/** The template region of a double spread: the two page <img> elements. */
function spreadTemplate(page) {
  const start = page.indexOf('class="paged-spread"');
  assert.ok(start > 0, "the double-spread stage is gone");
  const end = page.indexOf("paged-window-ghost", start);
  assert.ok(end > start, "the spread block could not be delimited");
  return page.slice(start, end);
}

test("the spread binds its two halves by side, not by page rank", () => {
  const page = read("./src/views/ReaderPage.vue");
  const tpl = spreadTemplate(page);

  // The left half is the left half; the right half is the right half.
  assert.match(tpl, /:src="pageRenderUrl\(spreadLeftPage\)"/);
  assert.match(tpl, /v-if="spreadDouble && spreadRightPage > 0"/);
  assert.match(tpl, /:src="pageRenderUrl\(spreadRightPage\)"/);

  // The rank-ordered pair is gone. If it comes back in the template the layout
  // is order-dependent again, which is the original defect in one line.
  assert.doesNotMatch(tpl, /spreadPrimaryPage/);
  assert.doesNotMatch(tpl, /spreadSecondaryPage/);
  assert.doesNotMatch(page, /const spreadPrimaryPage/);
  assert.doesNotMatch(page, /const spreadSecondaryPage/);

  // The left half leads the DOM, so the left value must be the one whose slot
  // is unconditional -- a `v-if` on the first <img> would let an RTL spread
  // render only the right page.
  const firstImg = tpl.indexOf("<img");
  const leftAt = tpl.indexOf("spreadLeftPage");
  const rightAt = tpl.indexOf("spreadRightPage");
  assert.ok(leftAt > firstImg && rightAt > leftAt, "the left half must be emitted first");
});

test("the earlier page sits on the leading side of the reading direction", () => {
  const page = read("./src/views/ReaderPage.vue");

  const left = page.slice(page.indexOf("const spreadLeftPage"), page.indexOf("const ghostPages"));
  const rightIdx = page.indexOf("const spreadRightPage");
  const right = page.slice(rightIdx, page.indexOf("const ghostPages"));

  // Single mode has no pair to place.
  assert.match(left, /if \(!spreadDouble\.value\) return cur;/);
  assert.match(right, /if \(!spreadDouble\.value\) return 0;/);

  // RTL: the *next* page is on the left, the current one on the right.
  // LTR: the current page is on the left, the next one on the right.
  assert.match(left, /isRtl\.value \? cur \+ 1 : cur/);
  assert.match(right, /const leading = isRtl\.value \? cur : cur \+ 1;/);
  assert.match(right, /return leading <= Number\(totalPages\.value \|\| 1\) \? leading : 0;/);

  // The last page has no partner, so the right slot empties rather than
  // repeating page N (which is what a naive `cur + 1` without the guard does).
  assert.match(right, /leading <= Number\(totalPages\.value \|\| 1\)/);
});

test("the start page and the step are untouched by the side swap", () => {
  const page = read("./src/views/ReaderPage.vue");

  // `currentPage` is the leading page of the spread in both directions -- the
  // page-turn code advances by `pageStep` from it and the ghost window walks
  // outwards from it. Swapping the *slots* must not move the cursor, or the
  // reader would start RTL on page 2 and skip pages when turning.
  assert.match(page, /const pageStep = computed\(\(\) => \(spreadDouble\.value \? 2 : 1\)\);/);
  assert.match(page, /setPage\(currentPage\.value \+ Number\(pageStep\.value \|\| 1\), isRtl\.value \? -1 : 1\);/);

  // The prefetch window is built on the page axis, so it takes the neighbours of
  // the leading page -- never `spreadLeftPage ± 2`, which would walk the slots.
  const ghost = page.slice(page.indexOf("const ghostPages"), page.indexOf("const wheelRange"));
  assert.match(ghost, /const lead = Number\(currentPage\.value \|\| 1\);/);
  assert.match(ghost, /const prevPrimary = lead - step;/);
  assert.match(ghost, /const nextPrimary = lead \+ step;/);
  assert.doesNotMatch(ghost, /spreadLeftPage\.value - step/);
});

test("the page-turn animation follows the content, not the page number", () => {
  const page = read("./src/views/ReaderPage.vue");
  const setPage = page.slice(page.indexOf("function setPage("), page.indexOf("function nextPage("));

  // `directionHint` is +1 when the page *number* advances. The animation name
  // must additionally depend on the reading direction, because the incoming edge
  // differs: LTR forward enters from the right, RTL forward from the left.
  assert.match(setPage, /const forward = directionHint >= 0;/);
  assert.match(setPage, /isRtl\.value/);
  // The mapping is pinned as a unit: forward must select the *-next name in both
  // directions. Asserting only that the strings appear would let the two arms be
  // swapped, which animates every turn backwards while still reading plausibly.
  assert.match(
    setPage,
    /isRtl\.value\s*\?\s*\(forward \? "reader-slide-rtl-next" : "reader-slide-rtl-prev"\)\s*:\s*\(forward \? "reader-slide-next" : "reader-slide-prev"\)/,
    "forward must map to the -next name in both directions",
  );
  // The old single-axis form negated the hint and reused the LTR classes, which
  // cancelled out and made RTL animate identically to LTR.
  assert.doesNotMatch(setPage, /const slideHint = isRtl\.value \? -directionHint : directionHint;/);
  assert.doesNotMatch(setPage, /transitionName\.value = slideHint >= 0/);
  assert.doesNotMatch(setPage, /transitionName\.value = directionHint >= 0/);
});

test("the four slide directions are distinct, and RTL mirrors LTR", () => {
  const page = read("./src/views/ReaderPage.vue");

  // All four names exist as real transitions, or the class name resolves to
  // nothing and the page snaps instead of sliding.
  for (const name of ["reader-slide-next", "reader-slide-prev", "reader-slide-rtl-next", "reader-slide-rtl-prev"]) {
    assert.match(page, new RegExp(`\\.${name}-enter-from`), `${name} has no enter transition`);
    assert.match(page, new RegExp(`\\.${name}-leave-to`), `${name} has no leave transition`);
  }

  // LTR forward enters from the right (+X); RTL forward enters from the left
  // (-X). Extract each block and read its transform sign so a copy-paste that
  // forgot to flip one of them is caught rather than looking plausible.
  const transformOf = (name) => {
    const at = page.indexOf(`.${name}-enter-from`);
    const block = page.slice(at, page.indexOf("}", at));
    const m = block.match(/translateX\((-?\d+)px\)/);
    assert.ok(m, `${name}-enter-from has no translateX`);
    return Number(m[1]);
  };
  assert.ok(transformOf("reader-slide-next") > 0, "LTR forward must enter from the right");
  assert.ok(transformOf("reader-slide-rtl-next") < 0, "RTL forward must enter from the left");
  assert.ok(transformOf("reader-slide-prev") < 0, "LTR backward must enter from the left");
  assert.ok(transformOf("reader-slide-rtl-prev") > 0, "RTL backward must enter from the right");
});
