# Backup & Restore

> 中文版见 [BACKUP.md](BACKUP.md)

ZingLib keeps its data in three places. **They are not copies of each other** — you need all three:

| # | Location | What lives there | How to back it up |
|---|---|---|---|
| 1 | `<YOUR_LOCAL_PATH>/local_lib/` (in the container: `/app/runtime/local_lib`) | **Your comic files themselves** (folders or `.zip`/`.cbz`), plus each gallery's `ComicInfo.xml` | Your own tooling (rsync / snapshot / cloud). This project never copies your files |
| 2 | The PostgreSQL (pgvector) database | `works` (titles, tags, vectors, `raw`), `read_events` (reading history), `app_config` (settings), `ui_users` / `ui_sessions` (accounts and sessions) | `pg_dump` (below) |
| 3 | The rest of the runtime directory `/app/runtime` | Model weights, thumbnails, **the per-gallery backups in `.zinglib_meta/`**, pre-migration snapshots in `backups/`, restore logs in `restore_logs/` | Back up the whole directory |

🔴 **`.zinglib_meta/` holds the expensive output of computation, not "another copy of the database".**
ZingLib writes it automatically and it covers **vectors and history only** — it does **not** contain your
comic files, your settings or your accounts. It is therefore **not** a substitute for #1 or #2 —
but it is what saves you from recomputing hours of SigLIP embeddings after the library moved, the
machine changed, or the database was rebuilt.

---

## 1. What the per-gallery backup (`.zinglib_meta/`) is

Path: `<library root>/.zinglib_meta/<arcid>_zinglib_metadata.json`
(`arcid` is `"local-" + sha1("local:" + relative path inside the library)`.)

It is written automatically at **three moments** (each time as a full, atomically replaced rewrite,
and it **never raises**):

1. **After the embeddings finish** (`[Vectorize]` completing) — this is when it gets **created**;
2. **After metadata is edited** (title / tags / category / bookmark, or a ComicInfo write-back);
3. **After reading** — this only **refreshes** the history inside an existing file and **never creates one**.

Contents (`schema: "zinglib.metadata.v1"`):

```jsonc
{
  "schema": "zinglib.metadata.v1",
  "arcid": "local-…",
  "local_dir": "relative/path/gallery-folder",   // the match key on restore, see §3
  "written_at": "2026-09-23T…Z",
  "siglip": { "dim": 1152, "cover": [...], "page": [...], "model": "…" },
  "text":   { "dim": 1024, "vector": [...] },    // present only if an LLM is configured; absent is normal
  "meta":   { "title": "…", "tags": [...], "bookmark": 12,
              "category": "doujinshi", "comicinfo": {...} },
  "history": [ { "read_time": 1750000000, "source_file": "…", "ingested_at": "…" } ]
}
```

* `history` is capped at **1000** entries (a file-size bound only, not a functional limit).
* `.zinglib_meta/` is hidden from the scanner and from the file manager, so it never shows up in
  "Tools → File manager". **Leave it alone** — and include it when you back up your library directory.

## 2. Backing up the database (#2)

```bash
# Run where the database is reachable; replace the <…> placeholders.
pg_dump -Fc -f zinglib-$(date +%F).dump \
  "postgresql://postgres:<password>@<db-host>:5432/zinglib_library"
```

* Do **not** run `[Vectorize]` or "rebuild database" while dumping — you would capture a half-written state.
* Vector columns make dumps large. That is exactly why #3 (`.zinglib_meta/`) is worth having:
  **you do not need a database dump to get the vectors back** — restore the schema and settings, then
  pull the vectors back per gallery from the sidecars.

### Automatic pre-migration snapshot

On every start the image runs database migrations first. **Before** migrating it copies all 10 tables
into per-table `.csv.gz` files plus a `manifest.json`, under:

```
/app/runtime/backups/pre_<from>_<to>_<timestamp>/
```

Only the newest **3** are kept (`DB_INIT_BACKUP_KEEP`). This is the cheapest rollback point if a
migration went wrong — but it is **migration-specific**; do not treat it as your regular backup.

## 3. Restoring: pick your scenario

### Scenario A — same library, the records are gone (the common case)

Typically: the database was wiped or rebuilt (`works` is empty) while the **files never moved**.

1. Complete the **Setup Wizard** (connect the database, create the admin account);
2. Go to `Settings → Local library` (the wizard's local-library step has the same entry point) → **Restore**;
3. You get a **preview** first (`dry_run`, writes nothing): how many galleries there are, how many
   can be matched, and how many have no backup at all;
4. Confirm to run the real restore;
5. Click **Download full log** for the per-gallery result (see §5).

### Scenario B — new machine, or the library moved

**Keep in mind: `arcid` is a hash of the path, so moving the library changes every arcid.**
The old sidecars' `arcid` values no longer match any row. That is expected, not an error.

ZingLib matches on **`local_dir` (the relative path inside the library) first**, and only falls back
to `arcid`. So:

1. Put the comics back under the **same relative structure** (`LibraryRoot/AuthorA/WorkB/…` with
   `AuthorA/WorkB` preserved);
2. Bring `.zinglib_meta/` along (it sits in the library root, so it travels with the library);
3. Run `[Scan local library]` to rebuild the rows;
4. Then restore as in scenario A.

Unmatched sidecars are reported as **`orphan`** and are **never** written into someone else's row.
Galleries re-vectorized under their new path become **new arcids** and get a fresh sidecar when they
finish.

### Scenario C — restore the database itself (#2)

```bash
pg_restore -d "postgresql://postgres:<password>@<db-host>:5432/zinglib_library" --clean --if-exists zinglib-2026-09-23.dump
```

Start the app afterwards (it re-checks migrations on boot). **This is the path that covers settings
and accounts** — the part sidecars cannot.

## 4. Restore semantics ("the live database is always newer than the backup")

A restore does not overwrite; it **fills gaps only**:

| Object | Rule |
|---|---|
| Visual / text vectors | Written **only into `NULL` columns**; any existing vector wins (live data is newer) |
| Reading history | `ON CONFLICT (arcid, read_time) DO NOTHING` — **running it twice never doubles the history** |
| `raw` (title / tags / bookmark / category / ComicInfo) | **Merged key by key, gaps only**; **never replaced wholesale** (a wholesale replace once silently erased `raw.bookmark`) |
| `category` | The backed-up category is restored into `raw.eh_raw.category` |

So restoring twice is safe and yields the same result as restoring once.

## 5. Reading the restore result

The dialog shows **counters only** (no file-name lists). The per-gallery detail lives in a JSONL log:

* On disk (inside the container): `/app/runtime/restore_logs/metadata_restore_<32-hex-id>.jsonl`,
  newest **20** kept;
* **Only a real restore writes a log** — a preview writes nothing;
* The **Download full log** button in the dialog fetches it (`application/x-ndjson`).

Every line explains itself; you never have to cross-reference the counters:

```jsonc
{"type":"restore_report","status":"restored","ok":true,"reason":"one line per gallery follows",
 "schema":"zinglib.restore_log.v1","started_at":"…","dry_run":false,
 "library_galleries":33,"sidecar_files":31}                  // header: the shape of this run
{"type":"matched","status":"restored","ok":true,"reason":"restored from backup",
 "gallery":"WorkB","arcid":"local-…","local_dir":"AuthorA/WorkB","file":"local-….json",
 "visual":1,"text":0,"history":12,"meta":1}                  // this gallery came back
{"type":"no_sidecar","status":"no_backup","ok":true,
 "reason":"no backup file for this gallery: it must be recomputed",
 "gallery":"WorkC","arcid":"local-…","local_dir":"AuthorA/WorkC"} // no backup -> still needs recomputing
{"type":"summary","ok":true,"dry_run":false,"total_galleries":33,"matched":31,"restored":31,
 "no_sidecar_count":2,"orphan_count":0,"duplicate_count":0,"failed_count":0,
 "unreadable_count":0,"had_failures":false,
 "summary":"31 restored, 31 matched, 2 without backup, 0 orphan, 0 duplicate, 0 failed, 0 unreadable"}
                                                             // footer: counters + one plain sentence
```

Field reference:

| Field | Meaning |
|---|---|
| `status` | `restored` / `preview` (dry run) / `no_backup` (this gallery has no backup) / `orphan` (backup belongs to no gallery in this library) / `duplicate` (a newer backup already covered this gallery) / `failed` / `unreadable` (backup file could not be parsed) |
| `ok` | **Whether this line is an *error*.** Note `no_backup` carries `ok: true` — it is **information you act on**, not a restore failure |
| `reason` | Plain-language cause |
| `gallery` | **The name you recognise** (last path segment); `arcid` alone is a hash nobody can read |
| `arcid` / `local_dir` | Exact identification |
| `file` | The backup file involved |
| footer `summary` | Counters + `had_failures` (any `failed`?) + a one-line sentence |

`no_sidecar_count` in the dialog and `no_backup` in the log are the same thing:
**"these galleries have no backup, so they must be vectorized again"**.

> `duplicate` only appears after a library move leaves both the old and the new backup in place:
> two backups match one live gallery. ZingLib uses the **newest by mtime** and reports the older one as
> `duplicate`, so `matched` never inflates past the number of galleries.

## 6. The dangerous operation: `Settings → Danger zone → Rebuild database`

It runs `DELETE FROM works` (**the foreign key cascades, so `read_events` goes too**) but leaves your
**files and settings untouched**.

* If you have sidecars, most of the loss is recoverable via §3 (vectors + history + hand-picked metadata);
* If you have **no** sidecars, that library's embeddings must be recomputed — which is why finishing the
  first vectorization pass already makes `.zinglib_meta/` your safety net;
* Settings and accounts are outside the sidecars' scope: those come from the database dump in §2.

## 7. One-line checklist

- [ ] The comic files themselves — your own backup strategy (#1)
- [ ] The database — periodic `pg_dump` (#2, includes settings and accounts)
- [ ] The whole runtime directory (including `.zinglib_meta/` and `backups/`) — take it with you when moving
- [ ] After a move: **keep the relative paths identical** → rescan → restore
- [ ] After a restore: check `no_sidecar_count` in the dialog; if it is non-zero, re-vectorize those galleries
