# Contribution Guide

> 🌐 Language / 语言: [English](CONTRIBUTING_EN.md) | [中文](CONTRIBUTING.md)

To be upfront: **this is a spare-time hobby project with no promise of updates.** Issues and PRs are welcome,
but I am not a professional developer and may not get to them.

If you do want to change something, the notes below describe how the project currently works.

---

## How this project works

1. **Zero-config cold start**: new features must not introduce `.env` variables a user has to set by hand.
   Configuration lives in the WebUI Setup Wizard and the `app_config` table (`constants.py` holds defaults).
2. **The local-only invariant (the important one)**: the app only reads the local filesystem. It does not
   fetch online content, proxy remote media, report telemetry, or load external online services.
   **New code must not add any of those.**
3. **Security**: no unauthenticated external HTTP ports (use in-process workers), keep the CSRF
   double-submit cookie, and keep the global Sudo re-authentication for dangerous operations.
4. **Algorithm changes**: for PRs touching the recommendation algorithm or XP clustering (KDE / PCA),
   a short note on the reasoning is appreciated -- mostly so future you can follow it.
5. **Frontend feel**: avoid stiff DOM jumps and synchronous requests that block the main thread.

---

## Automated agent workflow

`agent-dev` is the long-lived integration branch cut from `main`: automated agent PRs and merges land only on `agent-dev`, and a human-reviewed `agent-dev` is merged into `main` by the user.

1. **Default target branch**: every agent PR must specify `--base agent-dev` (for example `gh pr create --base agent-dev`); a PR to `main` is forbidden.
2. **Branch naming**: each task cuts an independent branch from the latest `origin/agent-dev`, for example `agent/<task-name>`; do not commit directly on `agent-dev`, so concurrent tasks cannot collide on a shared branch.
3. **Self-check before merge**: confirm the local build/tests pass before merging into `agent-dev` (the `scripts/` release guards, frontend `npm ci && npm run build && node --test test_*.mjs`, backend `webapi/test_*.py`). On conflicts, `git pull origin agent-dev` and resolve locally; never force-push.
4. **Deliver clean**: delete the task branch as soon as it is merged into `agent-dev`, and drop machine-generated branches (`dependabot/*` and friends) once their PR is closed or merged. `origin` should carry nothing but `main` and `agent-dev` besides those. The one exception is being stuck mid-task: keep the branch, and say in the issue why it is being kept and what happens next.
5. **Review before merge**: only reviewed `in_review` changes merge into `agent-dev`; do not merge intermediate `todo` / `in_progress` results early. If review finds a problem, return the task to `todo` instead of opening a new duplicate task.
6. **Version and tag discipline**: run `scripts/bump_version.py` and create a tag only when the task names a version or explicitly asks for a release. Without an explicit version, merge the code into `agent-dev` and let the human release step decide the version and tag.

---

## Areas where help is genuinely useful

* **Algorithms**: fusing the SigLIP visual channel with text / metadata, recommendation potential-energy
  parameters, interest drift.
* **Frontend**: mobile gestures, deeper PWA integration, CSS animation polish.
* **Local data governance**: first-scan and incremental scanning of large libraries, `ComicInfo.xml`
  read/write fidelity, tag normalisation and category merging.
* **Model integration**: keep the VL (tagging / descriptions) and plain-LLM chains separately configurable;
  keep prompts in `constants.py` and the config table rather than as magic strings in business code.

---

## Development setup

Frontend and backend share one origin (the built frontend is served by FastAPI), but can be run separately.

1. **Database**: you need PostgreSQL 17+ with `pgvector`. Starting a database-only container is the quickest way:
   ```bash
   docker run -d --name zinglib-db \
     -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=zinglib_library \
     -p 5432:5432 -v /path/to/pgvector:/var/lib/postgresql/data \
     pgvector/pgvector:pg17
   ```
2. **Backend (FastAPI)**:
   ```bash
   cd Docker/main
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt   # only needed to run the tests (httpx2, for TestClient)
   uvicorn webapi.main:app --reload --port 8501
   ```
3. **Frontend (Vue 3)**:
   ```bash
   cd Docker/main/webapp
   npm install
   npm run dev
   ```
   Configure a proxy in `vite.config.js` to forward `/api` to your local FastAPI port, keeping things same-origin.

> The full development notes, what a fresh clone can run, and what CI runs live in
> [**STARTUP_EN.md**](STARTUP_EN.md), section 7 ("Development & Verification").

---

## Before opening a PR (if you have the time)

* [ ] Does the Python code pass `black` / `isort`, and are the type hints there
* [ ] **Cold start**: with an empty database and no prior configuration, does the Setup Wizard complete
* [ ] **Local-only**: did anything online-fetching, credential-storing, or telemetry-shaped creep in
* [ ] **Don't block the main thread**: big synchronous file reads and model inference belong in a background
      thread (`anyio`) or an in-process worker

Thanks for taking the time to look at this project 🙇
