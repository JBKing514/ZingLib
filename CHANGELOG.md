# Changelog

All notable changes to ZingLib are recorded here.

This file is maintained by `scripts/bump_version.py`, which inserts the new
section at every version bump. The format follows Keep a Changelog, and the
versions follow Semantic Versioning:

* `major` -- a change that needs user action, or breaks stored data
* `minor` -- new behaviour, no action needed
* `patch` -- fixes only

## [1.0.0] - 2026-09-23

First version carried under version-number iteration. The application had been
feature-complete for some time; what made 1.0.0 the right line was the release
engineering below, which is what lets later versions be upgraded into place.

ZingLib manages a comic library that is already on your own disk. It reads those
files and nothing else: there is no online content source, no external
credentials, no remote media proxy and no telemetry.

### Added

#### Home and browsing

- The local library is the home page. The rail's *Local library*, *Favorites*
  and *History* entries share one route and are told apart by a `homeTab`, which
  is mirrored into the URL as `?local_tab=` so a bookmark reopens the same feed.
- Two feed display modes: infinite scroll (the default) and paged, with a page
  size of 10..100 and an optional "another page" pull at the bottom of the feed.
  The feed is rebuilt in place when the mode changes.
- Each feed remembers where it was scrolled to. The offset is held outside the
  component, and restoring it does not write to the store, so passing through a
  shorter page on the way back cannot leave the feed at the top.

#### Reading

- An end screen, presented as a virtual final page: it offers the next gallery
  in the current sort order and a "guess you like" strip. The strip is ranked
  from the gallery's own visual embedding and its tags, both normalised onto one
  scale before they are mixed; it is not derived from page imagery, and it can
  be switched off.
- Reading progress is published from the reader as a session-level overlay, so
  the history list and the preview cards stay in step without a reload. With no
  session to overlay, the stored bookmark is used.
- Preview cards are patched in place after reading instead of reloading the
  feed, so the reader's exit does not lose the scroll position.

#### Local library

- Tags are stored as `namespace:tag` everywhere. The old `user:` marker is
  retired (legacy values are still read), and the manual-tag protection list
  lives in `raw.user_meta.tags`, so re-fetching metadata or re-applying a word
  list cannot silently drop tags.
- Category tags come from the source metadata on both read paths, and the
  built-in category pills are deliberately left untranslated.
- A tag-translation word list, plus `POST /api/local-lib/tags/reapply` to replay
  it across the library with progress and a cancel.
- Tag suggestions come from the library *and* the uploaded word list. A tag the
  library already uses always ranks first; the word list fills the rest, so a
  user who has not tagged anything yet still gets suggestions instead of an
  empty box. Suggestions are emitted in the stored `namespace:tag` shape.
- A metadata editor and a two-column quick-tag composer (pick a namespace, then
  a tag), with every tag namespace shown as a column and localised headers.
- Uploads run as staging -> review -> per-gallery import, and the toolbox file
  manager can hold one gallery per session with 50 rows per page.
- Metadata edits are written back to `ComicInfo.xml`: created when absent,
  overwritten whole when present, and rewritten member by member inside archives.

#### Per-gallery metadata backup and restore

- Every vector that cost compute to produce is banked next to the gallery, in
  `<local library>/.zinglib_meta/<arcid>_zinglib_metadata.json` -- the SigLIP
  visual vector, an optional text vector, the reading history and ZingLib's own
  metadata. `.zinglib_meta` is skipped by the scanner and hidden from the file
  manager, so it is not something that can be deleted by accident.
- Writes happen at three moments: after an embedding is committed, after a
  metadata edit, and after a read. None of them may fail the operation they are
  attached to, and the read path only refreshes a file that already exists.
- `POST /api/local-lib/metadata/restore` restores them, with a dry run first.
  Galleries are matched by relative path before arcid, because arcid is a hash
  of the path and moving a library changes every one of them. Restore fills only
  the vectors that are missing (the database is always the newer copy), inserts
  history with `ON CONFLICT DO NOTHING`, and merges the metadata key by key
  rather than replacing it. A backup belonging to no gallery is reported as an
  orphan instead of failing the run; when a move leaves two backups for one
  gallery, the newest wins and the older one is reported as a duplicate.
- A real restore writes a line-delimited JSON log: a header naming the log
  schema, one line per gallery, and a closing summary. Every line says what
  happened (`status`), whether that is a failure (`ok`), why in plain words
  (`reason`), and which gallery (`gallery`, `arcid`, `local_dir`) -- "no backup"
  is information, not a failure. The newest 20 logs are kept, and the completion
  dialog offers to download the one just written. See `BACKUP.md`.

#### Settings

- Settings save as you edit them; there is no save button. Values are compared
  per schema type (so `20` and `"20"` are not a change), and overlapping edits
  are serialised, so a dragged slider cannot put two requests out of order.
- An XP map view, with the clustering ported to a local service
  (`GET /api/xp-map`).

#### Release engineering

- Versioned, re-entrant database migrations. The schema now lives in
  `Docker/main/textIngest/migrations/` and is applied on every container start,
  with the applied set recorded in the database's `schema_version` table.
  A pre-migration snapshot of the application tables is written to
  `/app/runtime/backups/` before anything is applied.
- `scripts/bump_version.py`, which treats `package.json` as the single source of
  truth and derives `/version.json` and this file from it.
- Guards for release state: `check_version_consistency.py`,
  `check_migrations.py`, `check_deps_pinned.py`.
- `BACKUP.md` / `BACKUP_EN.md`, describing the three places data lives, what a
  sidecar contains, and what restore does and does not touch.

### Changed

- The database bootstrap no longer runs once and remembers that in a file. The
  old marker lived in the persisted `/app/runtime` bind mount, so it survived
  image upgrades and silently skipped every schema change after the first
  start -- an upgrade shipped new code against an unmodified database.
  `DB_INIT_FAIL_HARD` now defaults to 1: a failed migration refuses to start
  instead of continuing on a half-migrated database.
- Account and session tables (`ui_users`, `ui_sessions`, `ui_meta`) are owned by
  the versioned database baseline, so there is one schema source instead of two.
- Python dependencies are pinned with `==`, and both base images are pinned by
  digest, so a given version builds to the same contents later.
- Favourites toggle optimistically: the card flips first and the request
  follows, rolling back if it fails. This covers the hover card and the mobile
  long-press dialog as well.
- Leaving a gallery from the end screen needs a second, explicit forward action,
  so a stray page-turn at the end does not drop the reader somewhere else.
- The licence is **MIT** (see `LICENSE`). The README was cut back to what the app
  does and how to run it: the model section now says plainly that nothing has to
  be configured, and that SigLIP approximate search on its own is enough; the
  contributing section says plainly that this is a hobby project.

### Fixed

- Stored metadata (`raw`) is merged key by key everywhere instead of being
  written wholesale; a wholesale write had been silently erasing the stored
  bookmark.
- Uploads: every file entry carries the relative path the panel sends, and an
  archive submission keeps its file extension. Either one being lost made the
  whole upload fail rather than importing fewer files.
- Restore now really restores `category`, the arcid fallback no longer queries a
  path as if it were an arcid, and duplicate backups after a move no longer
  inflate the match count past the number of galleries.
- Switching the feed display mode no longer leaves the list blank, and returning
  to a feed no longer lands at the top of it.
- The reader's end screen no longer swallows clicks meant for paging, and a
  gallery opened from a bare URL hides the "next gallery" entry point instead of
  offering one that has no queue behind it.
- Thumbnail loading can no longer hold up the reader: cancellation points, a
  generation counter, low-resolution thumbnails and low-priority lazy images.
- A sidecar carrying an unknown schema is refused rather than half-applied.

### Removed

- The legacy one-shot schema bootstrap and its compatibility tombstone are gone;
  startup now uses only the numbered migration runner.
- The plugin and developer surface, and the residue of the online service the
  library used to talk to.
- Internal regression notes and the compose files that pointed at a private
  network, along with documentation links to a third-party runtime bundle.

### Security

- Rollback guard: a database whose schema is newer than the image is refused at
  startup rather than run against. Override with `DB_INIT_ALLOW_DOWNGRADE=1`.
