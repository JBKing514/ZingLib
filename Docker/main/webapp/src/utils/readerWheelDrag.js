export const WHEEL_DRAG_PAGE_PX = 18;

// How far a pointer must travel before the wheel treats the gesture as a drag
// rather than a tap. Also the threshold below which we refuse to capture the
// pointer: capturing on `pointerdown` retargets the following `pointerup` to the
// capture element, and the browser then computes the `click` target from that
// retargeted event -- so the `@click` on a thumbnail never fires and a mouse
// click on the strip does nothing. Touch was unaffected because a tap is
// resolved from the touch target instead, which is why this only ever showed up
// with a mouse.
export const WHEEL_DRAG_THRESHOLD_PX = 4;

export function pageForWheelDrag(input = {}) {
  const max = Math.max(1, Math.floor(Number(input.totalPages || 1)));
  const startPage = Math.max(1, Math.min(max, Math.round(Number(input.startPage || 1))));
  const dx = Number(input.currentX || 0) - Number(input.startX || 0);
  const dy = Number(input.currentY || 0) - Number(input.startY || 0);
  let distance = String(input.position || "bottom") === "bottom" ? -dx : -dy;
  if (input.rtl && String(input.position || "bottom") === "bottom") distance = -distance;
  const delta = Math.round(distance / WHEEL_DRAG_PAGE_PX);
  return Math.max(1, Math.min(max, startPage + delta));
}
