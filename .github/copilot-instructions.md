# ZingLib — review instructions

ZingLib is a **local-first** private manga/illustration library: FastAPI/Python 3.11
(`Docker/main/webapi`), Vue 3 + Pinia + Vuetify PWA (`Docker/main/webapp`),
PostgreSQL 17 + `pgvector`. It reads the local filesystem and nothing else.

This file is deliberately short. The detailed playbook — this project's cross-file
contracts, its verification rules and the false positives to avoid — lives in the
`code-review` skill. **Do not restate it here**; a second copy drifts from the first.

## Always apply

- **The local-first invariant is blocking.** No online fetching or crawling, no
  third-party site credentials, no remote media proxying, no telemetry, no loading
  code from outside the repository at runtime. Hiding a control in the UI, or
  defaulting a flag to `false`, is not removal.
- **Never lose user data.** No dropping tables, wiping settings, deleting libraries
  or removing private extension archives as a side effect of a cleanup. That needs
  its own explicit migration decision.
- **`works.raw` is merged key by key, never replaced.** A wholesale replace silently
  drops reading progress (`raw.bookmark`) and hand-made tags (`raw.user_meta.tags`).
  The title a user sees is `raw.user_meta.title || works.title`, so any code that
  renders *or writes* a title has to apply that fallback — reading `works.title`
  alone republishes the stale official title over a gallery the user renamed.
- **Every mutating route is administrator-only**, enforced centrally in
  `webapi/core/middleware.py`; `SELF_SERVICE_PATHS` lists the routes that only touch
  the caller's own account (`logout`, `password`, `profile`, `verify-password`).
  This is a deliberate central gate: a new mutating route is covered automatically.
  **Do not report a missing per-handler role check** — a route with no visible
  `role == "admin"` test is normally guarded by that middleware, and adding a second
  copy at each route is how the two would drift apart. Only a new *self-service*
  route needs an explicit allow-list entry.
- **`webapp/package.json` is the only version source**, and a release tag must equal
  it exactly. Dependencies are `==`-pinned, base images pinned by digest, frontend
  installs use `npm ci`.

## Verification

Report build, unit tests, runtime/API and visual results **separately**. A
successful build, a live process or an empty log is not a regression pass.

- `RESULT PASS` does not mean a module ran — `unittest` prints PASS for a
  class-level `SKIP` too. The tally line (`Ran N tests`, and whether `skipped=` is
  present) is the evidence.
- A new test must be mutation-tested: break what it guards, confirm it goes red,
  then restore. A test that cannot fail is a defect, not a test.
- Assertions must survive minification — DOM attributes, form field names, CSS
  classes, i18n **values**. Never identifiers such as function or component names.
- Anything data-dependent must SKIP when its fixture is absent, never FAIL and never
  pass on a relaxed assertion.
- Database tests must select rows by their own fixture key, never by position.
  Probe cleanup must target exact paths/arcids, never substrings, and must assert
  arcid sets rather than counts.

## Do not flag

- `tools/` and `AGENTS.md` are gitignored on purpose and are **not** in a clone.
  The repository's guards are the three scripts under `scripts/` plus what CI runs.
- **A destructive-looking route with no visible role check.** See the central gate
  above — `/api/system/restart`, the metadata writeback and the restore endpoint are
  all administrative, and the check lives in the middleware rather than at each
  route. Reporting these again is a false positive.
- **The `pg_isready` healthcheck naming a database.** `pg_isready -d <name>` only
  reports whether the *server* answers; it returns "accepting connections" for a
  database that does not exist, so it cannot make a healthy server look unhealthy.
  `-d` is there to name the server, not to probe the database.
- `Docker/` ships exactly one compose file on purpose; the app-only and
  database-only templates were deleted deliberately.
- `ssh <user>@<dev-host>` in `STARTUP.md` §7.3 is intentional desensitisation.
- `lrr_library` in `.github/workflows/ci.yml` is a CI fixture name; the shipped
  default is `zinglib_library`.
- `Docker/main/NUL` is an ignored build artifact, not source.

## Sources of truth

`STARTUP.md` §7 for what a clean clone and CI can run, `CONTRIBUTING.md` for project
conventions, `BACKUP.md` for backup/restore behaviour. Read the current code before
trusting any summary or older document.
