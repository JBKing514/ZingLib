// Global reader shortcuts: key parsing, key/action mapping and wheel direction.
//
// The module is pure on purpose: everything except `bindReaderShortcuts` can be
// exercised without a DOM, so the decisions are pinned here rather than by
// asserting on the reader's source.
import assert from "node:assert/strict";
import test from "node:test";
import {
  parseTurnKeys,
  resolveKeyAction,
  resolveWheelAction,
  canTurnFromWheel,
  defaultIsEditableTarget,
} from "./src/utils/readerShortcuts.js";

test("turn keys parse from the shapes a settings field actually produces", () => {
  assert.deepEqual(parseTurnKeys("a,d"), ["a", "d"]);
  assert.deepEqual(parseTurnKeys("A D"), ["a", "d"], "case-insensitive and space-separated");
  assert.deepEqual(parseTurnKeys("a，d"), ["a", "d"], "the full-width comma is a real input on zh keyboards");
  assert.deepEqual(parseTurnKeys(""), [], "empty means 'no binding', not 'every key'");
  assert.deepEqual(parseTurnKeys("  "), []);
  assert.deepEqual(parseTurnKeys(null), []);
});

test("only configured keys turn a page", () => {
  const cfg = { nextKeys: ["d"], prevKeys: ["a"] };
  assert.equal(resolveKeyAction({ key: "d" }, cfg), "next");
  assert.equal(resolveKeyAction({ key: "a" }, cfg), "prev");
  assert.equal(resolveKeyAction({ key: "D" }, cfg), "next", "caps lock must not break paging");
  assert.equal(resolveKeyAction({ key: "ArrowRight" }, cfg), "", "an unconfigured key is inert, not guessed");
  assert.equal(resolveKeyAction({}, cfg), "");
});

test("a modified keystroke is never a page turn", () => {
  const cfg = { nextKeys: ["d"], prevKeys: ["a"] };
  // Cmd+D bookmarks, Ctrl+D ends input, Alt+D moves focus -- stealing any of
  // these to page would be a far worse bug than a missing shortcut.
  assert.equal(resolveKeyAction({ key: "d", metaKey: true }, cfg), "");
  assert.equal(resolveKeyAction({ key: "d", ctrlKey: true }, cfg), "");
  assert.equal(resolveKeyAction({ key: "d", altKey: true }, cfg), "");
});

test("a rebound key set replaces the defaults rather than adding to them", () => {
  const cfg = { nextKeys: ["j"], prevKeys: ["k"] };
  assert.equal(resolveKeyAction({ key: "j" }, cfg), "next");
  assert.equal(resolveKeyAction({ key: "d" }, cfg), "", "the old default is gone once rebound");
});

test("wheel direction follows the natural-scrolling switch, without platform sniffing", () => {
  // Default: scrolling down (deltaY > 0) advances.
  assert.equal(resolveWheelAction(120, { natural: false }), "next");
  assert.equal(resolveWheelAction(-120, { natural: false }), "prev");
  // Natural: the same physical gesture is inverted.
  assert.equal(resolveWheelAction(120, { natural: true }), "prev");
  assert.equal(resolveWheelAction(-120, { natural: true }), "next");
  // A zero-delta event is a no-op, not a "next".
  assert.equal(resolveWheelAction(0, { natural: false }), "");
  assert.equal(resolveWheelAction(undefined, { natural: false }), "");
  assert.equal(resolveWheelAction(NaN, { natural: true }), "");
});

test("wheel paging accepts at most one turn per 150ms window", () => {
  assert.equal(canTurnFromWheel(Number.NEGATIVE_INFINITY, 1000), true, "the first notch is immediate");
  assert.equal(canTurnFromWheel(1000, 1149), false);
  assert.equal(canTurnFromWheel(1000, 1150), true);
  assert.equal(canTurnFromWheel(1150, 1301), true);
  assert.equal(canTurnFromWheel(1000, Number.NaN), false, "a broken clock cannot trigger a turn");
});

test("an editable target keeps its keystrokes", () => {
  assert.equal(defaultIsEditableTarget({ tagName: "INPUT" }), true);
  assert.equal(defaultIsEditableTarget({ tagName: "textarea" }), true, "case must not matter");
  assert.equal(defaultIsEditableTarget({ tagName: "SELECT" }), true);
  assert.equal(defaultIsEditableTarget({ tagName: "DIV", isContentEditable: true }), true);
  assert.equal(defaultIsEditableTarget({ tagName: "DIV" }), false);
  assert.equal(defaultIsEditableTarget(null), false);
});
