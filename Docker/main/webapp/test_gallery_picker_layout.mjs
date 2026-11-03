import assert from "node:assert/strict";
import { test } from "node:test";
import { galleryPickerLayout } from "./src/utils/galleryPickerLayout.js";

const duo = { columns: 4, dualScreen: true, leftWidth: 537, rightWidth: 537, hinge: 27 };

test("left-panel presses keep the whole row and position it on the left screen", () => {
  for (const [index, startX] of [[0, 120], [1, 410], [4, 120], [5, 410]]) {
    const layout = galleryPickerLayout({ ...duo, index, startX });
    assert.deepEqual(layout.panel, { left: 0, width: 537 });
    assert.deepEqual([layout.start, layout.end], index < 4 ? [0, 4] : [4, 8]);
  }
});

test("right-panel presses keep the same whole row but position it on the right screen", () => {
  for (const [index, startX] of [[2, 690], [3, 970], [6, 690], [7, 970]]) {
    const layout = galleryPickerLayout({ ...duo, index, startX });
    assert.deepEqual(layout.panel, { left: 564, width: 537 });
    assert.deepEqual([layout.start, layout.end], index < 4 ? [0, 4] : [4, 8]);
  }
});

test("a preview narrows the feed to the left screen but later rows still pair correctly", () => {
  const layout = galleryPickerLayout({ ...duo, columns: 2, index: 3, startX: 410 });
  assert.deepEqual(layout, { start: 2, end: 4, panel: { left: 0, width: 537 } });
});

test("partial rows include every available gallery in that row", () => {
  const items = Array.from({ length: 7 }, (_, i) => i);
  const layout = galleryPickerLayout({ ...duo, index: 6, startX: 690 });
  assert.deepEqual(items.slice(layout.start, layout.end), [4, 5, 6]);
});

test("measured asymmetric screens use their actual widths and hinge", () => {
  const layout = galleryPickerLayout({ ...duo, leftWidth: 490, rightWidth: 610, hinge: 30, index: 3, startX: 900 });
  assert.deepEqual(layout.panel, { left: 520, width: 610 });
});

test("ordinary grids preserve whole-row candidates and viewport-wide placement", () => {
  assert.deepEqual(galleryPickerLayout({ index: 4, columns: 3 }), { start: 3, end: 6, panel: null });
  assert.deepEqual(galleryPickerLayout({ index: 3, columns: 4 }), { start: 0, end: 4, panel: null });
});
