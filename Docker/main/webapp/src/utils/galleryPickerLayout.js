export function galleryPickerLayout({
  index, columns, dualScreen = false, startX = 0,
  leftWidth = 0, rightWidth = 0, hinge = 0,
}) {
  const groupSize = Math.max(1, Math.floor(Number(columns) || 1));
  const start = Math.floor(Math.max(0, Math.floor(Number(index) || 0)) / groupSize) * groupSize;
  let panel = null;
  if (dualScreen) {
    const right = startX >= leftWidth + hinge / 2;
    panel = { left: right ? leftWidth + hinge : 0, width: right ? rightWidth : leftWidth };
  }
  return { start, end: start + groupSize, panel };
}
