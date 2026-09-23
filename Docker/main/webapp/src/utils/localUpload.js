const imagePattern = /\.(jpe?g|png|webp|avif|gif)$/i;
const archivePattern = /\.(zip|cbz|cbr)$/i;
const comicInfoPattern = /^comicinfo\.xml$/i;

// The backend's page cap. Keep in sync with MAX_GALLERY_PAGES in
// webapi/services/local_upload_service.py.
const MAX_GALLERY_PAGES = 10000;

/**
 * Build the review list from browser File metadata alone.
 *
 * This runs *before* any network request, which is the whole point: the user
 * sees what will be imported without first transferring gigabytes. It mirrors
 * the backend contract in services/local_upload_service.py -- a leaf folder is
 * a gallery when it holds at least one image, has no subfolder, and contains
 * only images / ComicInfo.xml / dotfiles. Anything else is skipped rather than
 * silently swallowing a real gallery.
 *
 * Rows carry the library path they will land on, so `files` must be the exact
 * set that will be uploaded for that row.
 */
export function describeLocalFiles(files) {
  const folders = new Map();
  for (const file of files) {
    const raw = String(file.webkitRelativePath || "").replace(/\\/g, "/");
    const parts = raw.split("/").filter(Boolean);
    if (!parts.length) continue;
    if (parts.some((p) => p === "." || p === "..")) continue;
    // A picked directory is "name/.../file". Keep the picked name in the path
    // so the staged tree reproduces it, and so a single gallery keeps its own
    // name instead of collapsing to a generic bucket.
    const name = parts[parts.length - 1];
    const parent = parts.slice(0, -1).join("/");
    // `path` is the picked-root-relative path and is what the uploader sends as
    // `relative_paths`. It must travel with the entry: the caller reads
    // `entry.path` per file and an empty value makes the backend skip the file
    // (``if not rel: continue``), which silently uploads nothing at all.
    const path = parent ? `${parent}/${name}` : name;
    if (!folders.has(parent)) folders.set(parent, []);
    folders.get(parent).push({ file, name, path });
  }

  const knownFolders = new Set(folders.keys());
  const rows = [];

  for (const [folder, entries] of folders) {
    const images = entries.filter((e) => imagePattern.test(e.name));
    const archives = entries.filter((e) => archivePattern.test(e.name));
    const comicInfo = entries.filter((e) => comicInfoPattern.test(e.name));
    const hasSubfolder = [...knownFolders].some((k) => k.startsWith(`${folder}/`));

    // A nested archive is its own gallery. Only the archived file is uploaded
    // for that row -- the sibling images stay with the folder gallery below.
    for (const entry of archives) {
      const archivePath = folder ? `${folder}/${entry.name}` : entry.name;
      rows.push({
        path: archivePath,
        name: entry.name.replace(archivePattern, ""),
        kind: "archive",
        page_count: null,
        ingestable: !/\.cbr$/i.test(entry.name),
        files: [entry],
      });
    }

    // A folder is a gallery when it looks like one. Archives are handled as
    // their own rows above, so they do not disqualify the folder. Files that
    // are neither images, archives nor ComicInfo.xml make the folder ambiguous
    // -- skip it, but never let that drop a folder that plainly holds images.
    const unknown = entries.filter(
      (e) =>
        !imagePattern.test(e.name) &&
        !archivePattern.test(e.name) &&
        !comicInfoPattern.test(e.name) &&
        !e.name.startsWith(".")
    );
    if (!images.length || hasSubfolder || unknown.length) continue;

    rows.push({
      path: folder,
      name: folder.split("/").pop(),
      kind: "folder",
      page_count: images.length,
      ingestable: true,
      files: entries,
    });
  }

  return rows
    .sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true }))
    .map((row) => ({
      ...row,
      over_limit: row.page_count != null && row.page_count > MAX_GALLERY_PAGES,
      state: "",
      done: 0,
      pct: 0,
    }));
}

/**
 * Split one gallery's files into request-sized batches.
 *
 * The per-request page ceiling is gone, so the only reason to chunk is to keep
 * an individual HTTP body (and its multipart parse) bounded. Progress is
 * reported per gallery by the caller; chunking is an implementation detail.
 */
export function uploadChunks(entries, count = 200, bytes = 32 * 1024 * 1024) {
  const chunks = [];
  let chunk = [];
  let size = 0;
  for (const entry of entries) {
    if (chunk.length && (chunk.length >= count || size + entry.file.size > bytes)) {
      chunks.push(chunk);
      chunk = [];
      size = 0;
    }
    chunk.push(entry);
    size += entry.file.size || 0;
  }
  if (chunk.length) chunks.push(chunk);
  return chunks;
}
