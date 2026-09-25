export const WHEEL_DRAG_PAGE_PX = 18;

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
