/**
 * Render orchestration for the XP map's two figures.
 *
 * They used to be awaited one after the other:
 *
 *     await renderActiveXpChart();
 *     await renderDendrogram();
 *
 * with the whole `loadXp()` chain wrapped in `.catch(() => null)` at both call
 * sites. One rejection therefore killed everything after it and reported
 * nothing: the default view is the 3D `surface` + `scatter3d` pair, which needs
 * WebGL, so a WebGL-less context produced two blank boxes beside a cluster table
 * that rendered perfectly (the table is plain HTML and never touches plotly).
 *
 * `renderFirstAvailable` runs the attempts in order and returns which one worked
 * instead of throwing, so a figure that cannot be drawn does not silence the
 * next figure, and its failure becomes state the UI can show.
 */

export function errorText(e) {
  const message = String(e?.message || e || "").trim();
  return message || "unknown error";
}

export async function renderFirstAvailable(attempts) {
  const list = Array.isArray(attempts) ? attempts.filter((fn) => typeof fn === "function") : [];
  let lastError = "";
  for (let index = 0; index < list.length; index += 1) {
    try {
      await list[index]();
      return { ok: true, index, error: "" };
    } catch (e) {
      // Keep going: the next attempt is usually the cheaper, more compatible
      // rendering of the same figure.
      lastError = errorText(e);
    }
  }
  return { ok: false, index: -1, error: lastError };
}

export default renderFirstAvailable;
