/**
 * XP map: one figure failing must not silence the other.
 *
 * The XP page draws a cluster table (plain HTML), a PCA/MAP chart and a
 * dendrogram. Both figures are plotly, and the chart's default form is the 3D
 * `surface` + `scatter3d` pair, which needs WebGL. The two were awaited one
 * after the other inside `loadXp()`, with the whole chain wrapped in
 * `.catch(() => null)`, so a single rejection produced two blank boxes and said
 * nothing -- while the table, which never touches plotly, rendered fine.
 *
 * These tests pin the orchestration: every attempt is made, the failure is
 * reported rather than thrown, and the degradation ladder is walked in order.
 */
import { errorText, renderFirstAvailable } from "./src/utils/xpRenderPlan.js";

function assertTrue(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`);
  }
}

async function main() {
  console.log("========================================================================");
  console.log("XP render isolation");
  console.log("========================================================================");

  let pass = 0;
  async function check(name, fn) {
    await fn();
    pass += 1;
    console.log(`PASS  ${name}`);
  }

  await check("the first attempt wins and later ones are skipped", async () => {
    const calls = [];
    const result = await renderFirstAvailable([
      async () => { calls.push("a"); },
      async () => { calls.push("b"); },
    ]);
    assertTrue(result.ok, "expected ok");
    assertEqual(result.index, 0, "expected the first attempt to be used");
    assertEqual(calls.join(","), "a", "later attempts must not run once one succeeded");
  });

  await check("a throwing attempt does not stop the next one", async () => {
    const calls = [];
    const result = await renderFirstAvailable([
      async () => { calls.push("3d"); throw new Error("WebGL is not supported"); },
      async () => { calls.push("2d-webgl"); throw new Error("still no WebGL"); },
      async () => { calls.push("2d-svg"); },
    ]);
    assertTrue(result.ok, "expected the SVG fallback to be used");
    assertEqual(calls.join(","), "3d,2d-webgl,2d-svg", "every attempt must be made, in order");
    assertEqual(result.index, 2, "expected the third attempt to be reported");
  });

  // The regression itself: a broken PCA chart must not blank the dendrogram.
  await check("a failed chart does not prevent the dendrogram from drawing", async () => {
    const rendered = [];
    const chart = await renderFirstAvailable([
      async () => { throw new Error("WebGL is not supported"); },
      async () => { throw new Error("WebGL is not supported"); },
      async () => { throw new Error("WebGL is not supported"); },
    ]);
    const dendro = await renderFirstAvailable([
      async () => { rendered.push("dendrogram"); },
    ]);
    assertTrue(!chart.ok, "the chart is expected to fail in this scenario");
    assertTrue(dendro.ok, "the dendrogram must still be attempted");
    assertEqual(rendered.join(","), "dendrogram", "the dendrogram must actually have rendered");
    assertTrue(chart.error.includes("WebGL"), "the chart failure must be reported");
  });

  await check("every attempt failing reports the last error, not an empty string", async () => {
    const result = await renderFirstAvailable([
      async () => { throw new Error("first"); },
      async () => { throw new Error("last"); },
    ]);
    assertTrue(!result.ok, "expected not ok");
    assertEqual(result.index, -1, "no attempt succeeded");
    assertEqual(result.error, "last", "the last failure is the most informative one");
  });

  await check("a rejected non-Error still yields a message", async () => {
    const result = await renderFirstAvailable([async () => { throw "plain string"; }]);
    assertTrue(!result.ok, "expected not ok");
    assertTrue(result.error.length > 0, "the message must not be empty");
    assertEqual(errorText(undefined), "unknown error", "an empty rejection still needs a message");
  });

  await check("an empty attempt list fails cleanly", async () => {
    const result = await renderFirstAvailable([]);
    assertTrue(!result.ok, "expected not ok");
    assertEqual(result.error, "", "no attempt means no error text");
  });

  console.log(`\nSUMMARY ${pass} passed`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((err) => {
    console.error(`FAIL  ${err?.message || err}`);
    process.exit(1);
  });
