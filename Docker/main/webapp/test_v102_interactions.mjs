import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { pageForWheelDrag } from "./src/utils/readerWheelDrag.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

test("reader wheel tracks total pointer travel until release", () => {
  const base = { startPage: 20, startX: 200, startY: 300, totalPages: 100, position: "bottom", rtl: false };
  assert.equal(pageForWheelDrag({ ...base, currentX: 182, currentY: 300 }), 21);
  assert.equal(pageForWheelDrag({ ...base, currentX: 110, currentY: 300 }), 25);
  assert.equal(pageForWheelDrag({ ...base, currentX: 20, currentY: 300 }), 30);
  assert.equal(pageForWheelDrag({ ...base, currentX: 380, currentY: 300 }), 10);
  assert.equal(pageForWheelDrag({ ...base, position: "left", currentX: 200, currentY: 210 }), 25);
});

test("reader wheel captures one pointer and uses absolute drag state", () => {
  const wheel = read("./src/components/reader/ReaderNavWheel.vue");
  assert.match(wheel, /@pointerdown="onWheelPointerDown"/);
  assert.match(wheel, /setPointerCapture/);
  assert.match(wheel, /pageForWheelDrag\(\{/);
  assert.doesNotMatch(wheel, /touchAnchor|onWheelTouchMove/);
  assert.match(wheel, /touch-action: none/);
});

test("page zoom scales the application surface instead of the root font", () => {
  const css = read("./src/styles/app.css");
  assert.match(css, /#app \{[\s\S]*?zoom: var\(--zgl-page-zoom\)/);
  assert.match(css, /#app \{[\s\S]*?width: 100%/);
  assert.doesNotMatch(css, /width: calc\([^\n]*zgl-page-zoom/);
  assert.doesNotMatch(css, /font-size: calc\(16px \* var\(--zgl-page-zoom\)\)/);
});

test("dashboard view buttons remain complete independent capsules", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.doesNotMatch(dash, /<v-btn-toggle[\s\S]*?\bdivided\b[\s\S]*?<\/v-btn-toggle>/);
  assert.match(dash, /\.home-view-toggle :deep\(\.v-btn\)[\s\S]*?border-radius: 999px !important/);
  assert.match(dash, /\.home-view-toggle \{[\s\S]*?overflow: visible/);
});

test("mobile PreviewCard follows the scaled preview pane instead of raw viewport units", () => {
  const dash = read("./src/views/DashboardScopePage.vue");
  assert.match(dash, /\.mobile-preview-fullscreen \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0/);
  assert.match(dash, /\.mobile-preview-body :deep\(\.preview-card\) \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0/);
  assert.doesNotMatch(dash, /\.mobile-preview-body :deep\(\.preview-card\) \{[\s\S]*?width: 100vw/);
});

test("sidebar exposes the real GitHub issues feedback link", () => {
  const sidebar = read("./src/layouts/AppSidebar.vue");
  assert.match(sidebar, /href="https:\/\/github\.com\/JBKing514\/ZingLib\/issues"/);
  assert.match(sidebar, /rel="noopener noreferrer"/);
  for (const locale of ["zh", "en"]) {
    const dict = JSON.parse(read(`./src/i18n/${locale}.json`));
    assert.ok(String(dict["nav.feedback"] || "").trim(), `${locale} carries the feedback label`);
  }
});

test("the app shell reserves horizontal touch travel for the sidebar", () => {
  const css = read("./src/styles/app.css");
  assert.match(css, /\.v-main \{[\s\S]*?touch-action: pan-y/);
});
