# Changelog

All notable changes to ZingLib are recorded here.

This file is maintained by `scripts/bump_version.py`, which inserts the new
section at every version bump. The format follows Keep a Changelog, and the
versions follow Semantic Versioning:

* `major` -- a change that needs user action, or breaks stored data
* `minor` -- new behaviour, no action needed
* `patch` -- fixes only

## [1.1.1] - 2026-09-26

- Fixed progress capsules missing from newly loaded compact dashboard cards by decoupling manifest page-count lookup from subtitle rendering.

## [1.1.0] - 2026-09-26

- Reader end-screen recommendations now open the selected gallery in the dashboard PreviewCard instead of starting it immediately.
- The thumbnail wheel gives short haptic feedback where supported and shows a lightweight placeholder while a fast drag settles, avoiding unnecessary thumbnail churn.
- Removed the redundant manual dashboard refresh control; stale feeds continue to refresh automatically.
- Mobile dashboard sort and filter actions now use the same compact icon controls as desktop.
- Compact-card progress capsules sit above the title gradient, and completed galleries use a darker treatment.
- Added configurable keyboard and damped mouse-wheel page turning, plus private reading mode that suppresses history and bookmark writes.
- Reader image quality gains an **Auto** tier, now the default: every page request carries the reader's screen size (`devicePixelRatio` capped at 2), and pages **larger** than the screen are Lanczos-downsampled server-side to a contain-fit of it before transfer, while pages that already fit -- and any request without a usable size hint -- are served as their original bytes. Auto can therefore only save bandwidth and decode cost, never reduce source detail; oversized animations pass through untouched rather than being flattened. Derivatives are cached on disk keyed by source hash and screen size, so each page is transformed once per size.
- Reader page derivatives are cached on disk per tier, so a page is only transformed once per quality.
- The reader's quick settings are grouped by purpose (layout / quality / wheel) in a two-column grid, instead of one full-width control per row taking over the screen on mobile. The panel's height follows the actual screen (capped at 80dvh, so ~20% stays visible underneath) instead of a fixed pixel cap that forced scrolling on tall displays, the fit-mode toggle is icon-only, and every option label is shortened to fit its half-width cell without wrapping.
- Private mode now recolours the application palette instead of applying a filter to the app root. The filter also colour-corrected every gallery cover and reader canvas underneath it; the theme-variable route leaves image, video and canvas pixels alone.
- Removed the reader's volume-key paging. No browser hands the hardware volume keys to a page, so the channel could never work and its settings row was noise.

## [1.0.4] - 2026-09-26

- The sidebar edge gesture works at any page zoom. The edge zone was measured in unzoomed CSS pixels while the pointer was read in zoomed ones, so at anything other than 100% the reachable zone was the wrong width and the travel threshold was scaled with it; both sides are normalised against the live zoom now.
- The mobile long-press gallery picker stays open. The touch that summoned it also reported its own release, which committed a selection before the picker had been seen; a short opening grace period distinguishes that release from a real pick.
- A gallery long-press is no longer contested by the browser or the sidebar, at any page zoom. The press used to be fought over three ways: the browser's own long-press text selection cancelled the touch and closed the picker the instant it appeared (90% zoom), and the drawer's edge swipe opened the sidebar out from under the finger mid-hold (130% zoom). The card claims the touch from pointerdown for the whole press, the shell does not track a press that starts on a card at all, and a cancelled opening touch leaves the picker up for a fresh one -- tapping the backdrop is the explicit exit.
- On a left-docked tablet preview pane the feed now makes room for it, the same as the right-docked one. The left side floated over the first column of cards while the right side pushed them aside, so the same feature looked like two different ones depending on which hand you used.
- Closing the preview pane no longer brings back the previous gallery's card. The close went through router history and a fixed delay, so a route that still carried the old preview key could be re-resolved mid-teardown; the pane is now torn down from local state first and the URL is corrected with a replace.
- Editing a gallery's metadata refreshes the open preview card in place. The hydration handler opened with a call to a method that exists nowhere in the tree, so it threw before its merge ran and the card kept the tags the user had just changed.
- A quick metadata edit from a preview card refreshes only that card. The edit used to rebuild the entire feed, which dropped the scroll position and flickered every other row for a change that touched one gallery; the server's answer is now folded into the row already on screen, with a full refresh kept as the fallback for a refused edit.
- Long-pressing on the reader's end screen no longer opens an empty rabbit-hole overlay. The overlay is seeded from the current page's own vector and tags, and the virtual page past the last one has neither.
- A reading started from a rabbit-hole suggestion is now recorded in history. The read-event throttle was keyed to the component rather than the gallery, so the first event of the next gallery fell inside a window that had already been used.
- Search results survive a trip into a gallery and back. The search offset was remembered against the list it was measured on; it is invalidated when the result set is replaced, and a slow first load no longer discards it.

## [1.0.3] - 2026-09-25

- Danger-zone database settings no longer auto-save; a connection test must pass before they can be written
- Account rename now requires the current password
- Removed the unused OpenAI health check and its config key
- The unlock switch and the account panel sit with the danger zone they belong to: the switch is glued to the zone's top edge, and the account (which keeps its own per-flow password gate) moved below it. The account panel had gone missing entirely, because a template binding was never returned from `setup()`.
- A forgotten password can be recovered with a one-time recovery code. Tick "forgot password" in the change-password dialog to swap the current-password field for a recovery code; the code is burned on use and the password is rewritten without the old one, revoking the account's other sessions.
- The reader's double-page spread opens on the side the reading direction starts from. Right-to-left used to draw the pair left-to-right (page 3 beside page 2 instead of page 4), because the two halves were laid out in page order rather than by side.
- The page-turn animation follows the reading direction: a forward turn in right-to-left reading slides in from the left, opposite to left-to-right, instead of both directions using the left-to-right slide.

## [1.0.2] - 2026-09-25

- Fix mobile gallery controls, page scaling, reader wheel tracking, sidebar gestures, and feedback access.

## [1.0.1] - 2026-09-24

- Galleries under a folder named `migrated` are scanned and listed again. The name was skipped as a legacy import graveyard that nothing in the code creates any more, so real galleries under it were neither scanned nor shown in the file manager, with nothing on screen to explain the absence.
- Settings -> Local Library can write the database's metadata back to disk, from the backup area: `ComicInfo.xml` plus the per-gallery `.zinglib_meta` sidecar, with a preview before anything is written. For a library imported by another tool, this is what puts the metadata onto the files.
- The metadata editor's tag suggestions also search the uploaded word list, so a library with no tags yet still gets suggestions.
- A backup restore suspends the visual-embedding watcher and restarts the container afterwards to hand it back.
- Model and dependency downloads can use a mainland-China mirror (DOWNLOAD_MIRROR=cn).
- Database name and host defaults now match the compose template (zinglib_library on zinglib-db).
- Saving settings on the setup screen no longer reports a failure while no database is connected.
- A too-short admin password returns a localised message instead of a raw developer string.
- The local-library setup step explains where uploading lives, and an empty home page offers it.
- The default-credential banner only appears while the shipped database credentials are really in use.
- Reading a gallery right after ingestion no longer claims its tags have not been recomputed against the current word list.
- The XP map renders its panels independently, so one figure that cannot be drawn (the PCA scatter or the dendrogram) no longer leaves the others blank.
- Four surfaces that had nothing left behind them are gone: the always-empty thumbnail-cache chip in Settings -> General, the "refetch metadata" action, the metadata-gap card (the metadata manager in the toolbox does the same job), and "flatten"/"flatten gaps".
- Opening the settings pages no longer throws: app startup still called a settings action that this release removes.

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
