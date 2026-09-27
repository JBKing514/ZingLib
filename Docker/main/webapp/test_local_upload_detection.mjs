import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { describeLocalFiles } from "./src/utils/localUpload.js";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");

function file(path, size = 1) {
  return { name: path.split("/").pop(), webkitRelativePath: path, size };
}

test("folder detection keeps supported files and ignores sidecars", () => {
  const rows = describeLocalFiles([
    file("Gallery/001.jpg"),
    file("Gallery/ComicInfo.xml"),
    file("Gallery/metadata", 0),
    file("Gallery/notes.txt"),
  ]);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].path, "Gallery");
  assert.equal(rows[0].page_count, 1);
  assert.deepEqual(rows[0].files.map((entry) => entry.name).sort(), ["001.jpg", "ComicInfo.xml"]);
});

test("a folder with no supported image is rejected", () => {
  const rows = describeLocalFiles([
    file("Documents/metadata", 0),
    file("Documents/notes.txt"),
    file("Documents/ComicInfo.xml"),
  ]);
  assert.equal(rows.length, 0);
});

test("upload results stay visible until the user presses Done", () => {
  const panel = read("./src/components/tools/ToolsUploadPanel.vue");
  assert.match(panel, /const uploadFinished = ref\(false\)/);
  assert.match(panel, /uploadFinished \? finishReview\(\) : startUpload\(\)/);
  assert.match(panel, /row\.errorText/);
  assert.match(panel, /detail\?\.code === "no_recognizable_images"/);
  assert.match(panel, /detailText\.includes\("gallery has no readable images"\)/);
  const tail = panel.slice(panel.indexOf("async function startUpload"), panel.indexOf("function finishReview"));
  assert.doesNotMatch(tail, /reviewOpen\.value = false/);
  assert.match(tail, /uploadFinished\.value = true/);
});
