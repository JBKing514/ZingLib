---
name: code-review
description: Review a pull request, diff or patch against ZingLib, the local-first manga and illustration library (FastAPI + Vue 3/Pinia + PostgreSQL/pgvector). Use when reviewing changes in this repository, judging whether a change is safe to merge, deciding what to flag or not flag, or checking that a test actually proves something. Encodes this project's local-first invariant, its cross-file contracts, and what counts as verification evidence here.
license: MIT
---

# Reviewing a change to ZingLib

ZingLib is a **local-first** private gallery: it reads the local filesystem only.
FastAPI/Python 3.11 lives in `Docker/main/webapi`, the Vue 3 + Pinia + Vuetify PWA
in `Docker/main/webapp`, storage is PostgreSQL 17 + `pgvector` (SigLIP SO400m
embeddings, 1152 dims).

Two things make reviewing here different from a generic review, and they are the
reason this skill exists:

1. Several rules are **cross-file contracts** that no single file reveals. A diff
   can be internally consistent, fully green, and still be wrong because it broke
   one of them.
2. This project's tests are **mutation-tested on purpose**. "The suite is green"
   is a weaker claim here than usual, and a new assertion that cannot fail is a
   defect, not a test.

## Sources of truth — read these instead of trusting a summary

| Question | Authoritative answer |
| --- | --- |
| What can a clean clone run? | `STARTUP.md` §7.1 (English: `STARTUP_EN.md` §7.1) |
| What does CI run? | `STARTUP.md` §7.2 and `.github/workflows/ci.yml` |
| Project conventions | `CONTRIBUTING.md` |
| Backup / restore behaviour | `BACKUP.md` |

If the checkout you are reviewing has an `AGENTS.md` at its root: it is
**gitignored on purpose** and is not part of the published repository, so it is
not something a contributor can see. Never cite it as documentation a cloner will
find, and do not ask for it to be updated as part of a code change.

## Severity order

Rank findings in this order, and say which one applies:

1. Breaks the local-first invariant (below) — always blocking.
2. Can destroy or silently lose user data — always blocking.
3. Breaks a cross-file contract — blocking.
4. A test that cannot fail, or a "pass" that does not prove the claim — blocking.
5. Documentation / i18n drift — request a change.
6. Style, naming, structure — optional.

Do not invent problems to fill a report. If a diff is fine, say it is fine.

## 1. The local-first invariant

The application reads the local machine and nothing else. A change violates this
invariant if it adds any of: fetching or crawling online content, storing or using
third-party site credentials, proxying remote media, telemetry/reporting, or
loading code from outside the repository at runtime.

Two shapes of **fake** compliance to reject explicitly:

- Hiding a control in the UI, or defaulting a flag such as
  `external_source_enabled` to `false`, is **not** removal. The behaviour must be
  gone, along with the routes, jobs, settings and dependencies that carried it.
- A generic local feature must not be deleted merely because its name originated
  upstream. Preserve local gallery import, ZIP/CBZ reading, ComicInfo metadata,
  user tags and categories, favorites, ratings, history, thumbnails and local
  search.

**Never delete user data as part of a cleanup.** Dropping tables, wiping settings,
deleting libraries, or removing private extension archives requires its own
explicit migration decision and is never a side effect of a refactor.

## 2. Cross-file contracts

These are the ones a green test suite will not protect. Check every diff that
touches the listed area against them.

**Uploads and archives**

- `entry.path` is a two-sided contract. The client must send it and the server
  must read it. Dropping either side makes every upload fail with 400.
- When an archive's leaf name is shortened during commit, the commit must put
  `source.suffix` (`.zip` / `.cbz`) back. Without it scanning fails with
  `scan root not found` and surfaces as a 500.
- In an archive gallery a "page" is a **zip member name**, not a path. Read page
  bytes by deciding archive-first and then `zf.read(member)`; never `os.path.join`
  a page name onto the gallery directory.

**Identity and caches**

- `arcid = sha1("local:" + normalized_relative_path)`. It is derived, so it is
  stable — but every write path that changes a gallery's file or its row must call
  `reader.invalidate_reader_caches(arcid)`. The reader caches are process-level;
  a stale entry is directly user-visible as a wrong page or a stale manifest.

**The `works.raw` JSON column**

- `raw` is **merged key by key**, never replaced wholesale:
  `raw = COALESCE(w.raw, '{}'::jsonb) || (...)`. Replacing the object silently
  drops `raw.bookmark` (the reader's only progress key) and
  `raw.user_meta.tags` (hand-made tags only). This has shipped as a real bug more
  than once, so treat any new writer of `raw` as a red flag until it merges.
- Any writer that rebuilds `raw` must also exclude `user_meta` from what it
  overwrites.
- The title shown to the user is **`raw.user_meta.title || works.title`**. The rule
  is repeated at each surface that renders a title (`display_title` in the list
  endpoints, `search_service`, the metadata editor) — so any new code that either
  displays **or writes** a title must apply the same fallback. Reading `works.title`
  alone is how the metadata writeback stamped the stale official title back over
  every gallery the user had renamed, undoing the very metadata it exists to keep.

**Categories**

- There are two read paths — `search_service` and `routers/local_lib._extract_category`
  — and both need the `raw.eh_raw.category` fallback (the lowercased first
  ComicInfo `<Genre>`). Two read paths that disagree is itself the bug; if a diff
  touches one, check the other.
- On the write side, the tag-picking helper must append the extra tags
  (`category:` / `uploader:` / `timestamp:` / `source_tag`) in **every** tag mode,
  not only when `<Tags>` is empty — otherwise a file with any `<Tags>` never gets
  a category and the filter silently never matches it.

**Tag suggestions and the glossary**

- The suggestion pool is `works.tags` ∪ the uploaded glossary. Glossary entries
  must be emitted with the **English namespace key** (`female:glasses`, not
  `女性:glasses`). Library hits always take precedence; the glossary only fills
  gaps, and a missing table degrades to empty rather than raising.
- Built-in category chips are deliberately **not** translated; namespace chips
  are. Do not "fix" one by changing the other.

**Per-gallery sidecar backups**

- Each gallery has `.zinglib_meta/<arcid>_zinglib_metadata.json`. None of the
  three write points may raise. Restore fills only `IS NULL` vectors, uses
  `DO NOTHING` for history, only fills gaps in `raw`, and matches galleries by
  **relative path — not by arcid**. A restore that matches on arcid attaches
  metadata to the wrong gallery.
- `.zinglib_meta` and `.staging` belong in `SCAN_SKIP_PREFIXES`, which the scanner
  and the file manager share. That set may contain **only our own internal
  directories**: adding a name a user actually uses makes real galleries vanish
  with no explanation.

**Reader and UI state**

- Reading progress is a **session-level overlay**; preview thumbnails must never
  block the reader; the end screen is a virtual page N+1 rather than a route.
- Favorites are **optimistic**: flip local state, POST, roll back on failure.
- Feed scroll offsets live in the module-level `feedScrollMemory.js`, and
  switching display mode must rebuild the feed in place.
- A panel that can be dismissed **without its handler running** — `v-dialog`
  defaults to `persistent: false`, so a backdrop click or Esc writes the `v-model`
  directly — must put its "rollback on close" on the close edge of a watcher, with
  the explicit Apply as the one path that commits. A Cancel-button-only rollback
  leaks the edit through the other exits.

**Configuration and security**

- Config values are **strings**. `"0"` is truthy in JavaScript, so booleans must
  go through `boolPref` / be unwrapped by `schema.type`; both ends need the guard.
- Resolved config precedence is `db > json > env`.
- Every mutating route is administrator-only, enforced centrally in
  `webapi/core/middleware.py`, with a short allow-list for routes that only touch
  the caller's own account or session. A new mutating route is covered
  automatically — but a new **self-service** route needs to be added to that
  allow-list explicitly, and a new route that a non-admin must be able to call is
  a design question, not a whitelist entry.
  **Do not report a destructive route that has no per-handler role check.** The
  check is in the middleware, so it is invisible in that route's diff hunk; asking
  for a second copy at each route is how the two lists would drift apart.

**Release engineering — single sources**

- `schema_guard.py` is the only DDL entry point; migrations are a single squashed
  baseline.
- `webapp/package.json` is the **only** version source. Do not hand-edit a version
  anywhere else; a release tag must equal it exactly.
- Dependencies are `==`-pinned, base images pinned by digest, and frontend installs
  use `npm ci` (not `npm install`). An unpinned test dependency turns "the suite is
  green" into a claim about a different day's dependency tree.

## 3. What counts as evidence

Four classes of result are **reported separately** and must not be conflated. A
successful build, a live process, or an empty log is not a regression pass.

1. build
2. unit tests
3. runtime / API behaviour
4. visual / interaction

The commands a clean clone can run are listed in `STARTUP.md` §7.1 — cite that.
In shape: three stdlib-only scripts under `scripts/`, `npm ci && npm run build &&
node --test test_*.mjs` in `Docker/main/webapp`, and the `webapi/test_*.py` modules
run as modules (`python -m webapi.test_x`) from `Docker/main`, because a script run
cannot import `webapi.*`.

When judging test output, apply these:

- **`RESULT PASS` does not mean the module ran.** `unittest` prints PASS for a
  class-level `SKIP` too. The tally line (`Ran N tests`, and whether `skipped=` is
  present) is the evidence; a module that matters should be run on its own and its
  tally read.
- **A test that cannot fail is not a test.** Every new guard or probe must be
  mutation-tested: break the thing it guards, confirm it goes red, then restore.
  A guard that stays green under mutation is the finding.
- Assertions must survive minification. Assert on DOM attributes, form field
  names, CSS class names or **i18n values** — never on identifiers such as
  function or component names, which the production bundle strips. A `grep` for a
  function name in the built bundle is a guaranteed-zero check, not a test.
- Anything data-dependent must **SKIP** when its fixture is absent — never FAIL,
  and never a relaxed assertion standing in for a pass.
- Real-database tests must select their rows by their **own fixture key** (arcid or
  filename), never by position: an index like `rows[0]` returns whatever the
  developer happens to have in their library, which is how these tests pass
  everywhere and fail for users.
- Probe cleanup must target **exact paths or arcids, never substrings**. A cleanup
  predicate like `strpos(local_dir, 'Solo') > 0` deletes a real gallery that the
  probe never created.
- Cleanup assertions compare **arcid sets**, not counts: earlier probes in the same
  run legitimately add and remove rows, so a matching count proves nothing. Assert
  both halves — the rows I created are gone, and the rows I did not create are
  still there.

## 4. Frontend specifics

- i18n keys are **flat dotted strings** (`"xp.title"`), not nested objects, in
  `webapp/src/i18n/{zh,en}.json`. Both languages must have identical key sets and
  identical placeholders — a key present in one language only is a defect.
  Adding a key to only one file is the most common frontend review finding here.
- Every config key referenced by the frontend must exist in `CONFIG_SPECS`
  (`webapi/core/constants.py`). A key that is not in the spec is **silently
  dropped** by `PUT /api/config`, which users experience as "my setting will not
  save" with no error anywhere.
- Vue 3 does **not** proxy `data()` keys that begin with `_` (Vue 2 did). A
  `_`-prefixed key that used to be reactive is now a plain non-reactive property —
  flag it.
- `v-dialog` defaults to `persistent: false`, so backdrop click and Esc dismiss it
  without calling any handler. Any state that must survive, or must be rolled
  back, has to be handled on the close edge rather than in a Cancel handler.

## 5. Do not flag these

These are deliberate, and reporting them is a false positive:

- `tools/` at the workspace level and `AGENTS.md` are **gitignored on purpose**.
  They are not in a clone. Do not ask for them to be updated, and do not describe
  them as "the repository's guards" — the repository's guards are the three
  scripts under `scripts/` plus what CI runs.
- `Docker/` ships **exactly one** compose file, which starts the database and the
  application together. An application container without its database is unusable,
  so the app-only and database-only templates were deleted intentionally. Do not
  suggest restoring them.
- The development host in `STARTUP.md` §7.3 appears as `ssh <user>@<dev-host>`.
  That is intentional desensitisation, not an unfinished document.
- The CI service in `.github/workflows/ci.yml` uses the database name
  `lrr_library`. That is a CI fixture name; the shipped default is
  `zinglib_library`, set by `docker-compose` and the built-in config defaults.
- `Docker/main/NUL` is an ignored build artifact (a stray Windows redirect), not a
  source file.
- Both `node_modules/` and the built `webapp/dist/` are excluded from review.

## 6. Documentation changes

The project's documents exist as Chinese/English pairs: `README`, `STARTUP`,
`BACKUP` and `CONTRIBUTING` each have an `_EN` twin, and `CHANGELOG.md` carries the
release history. A behavioural change that updates only one half of a pair, or that
changes user-visible behaviour without touching `CHANGELOG.md`, should be sent back.

`STARTUP.md` §7 is the single place that states what a clean clone can run and what
CI runs. Keep it there; do not duplicate that command list into a second document,
where it will drift.

## 7. Reporting

For each finding give: severity (per the order above), `file:line`, what breaks, and
a concrete suggested change. Then state the evidence explicitly, separated into
build / unit tests / runtime API / visual, and name anything you could not verify
rather than assuming it works. If a change is correct but under-tested, say that
plainly instead of reporting a bug.
