# ZingLib Quick Start Guide

> 🌐 Language / 语言: [English](STARTUP_EN.md) | [中文](STARTUP.md)

ZingLib is a **local-first** private manga / illustration library application: it does not crawl content from the network and stores no third-party site credentials. Core library features run locally; only AI requests are sent to an endpoint when the user explicitly configures an OpenAI-compatible service. This document covers deployment from scratch, initialisation, model configuration, and troubleshooting.

## 0. Prerequisites

* **Docker Environment**: Docker Engine v27+ or Docker Desktop recommended.
* **PostgreSQL 17+**: the `pgvector` extension must be enabled (the `pgvector/pgvector:pg17` image works out of the box).
* **OpenAI-Compatible Backend (Optional)**: any `/v1` interface (LM Studio / vLLM / Ollama, etc.) used for multimodal description generation and text-enhanced retrieval.
* **Note**: the LLM connection is optional. Without it the system still runs SigLIP-based visual retrieval, cluster recommendations, and the basic data pipeline.

## 1. Deployment

The image is public on Docker Hub (`jbking114514/zinglib`) and ships both `linux/amd64` and `linux/arm64` (a NAS, a Raspberry Pi or a Mac all work).

**The deployment options are ordered by preference: 1.1 one-command compose (recommended) -> 1.2 manual containers (your own `docker` commands) -> 1.3 build from source (fallback).**

### 1.1 One-command deployment: the single compose file (recommended)

`Docker/` holds **exactly one** compose file, and it brings up the database and the application together.
⚠️ **Do not try to start the application container alone** -- without a database you cannot even get past the login
screen, which is why there is no longer a template that starts only the app.

```bash
git clone https://github.com/JBKing514/ZingLib.git && cd ZingLib
docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

It starts two containers:

| Container | Role | Published port |
|---|---|---|
| `zinglib-db` | PostgreSQL 17 + `pgvector` | 5432 |
| `zinglib` | ZingLib itself (published image) | 8501 |

* The application uses the public image `jbking114514/zinglib:latest` by default; add `ZINGLIB_IMAGE=zinglib:local` for your own build.
* The database defaults to **`zinglib_library`**, user `postgres`, password `postgres`; override with `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD`.
* Data lands in **`Docker/zinglib/`, beside the compose file** (relative paths inside a compose file resolve against that
  file, not against your current directory): the database in `Docker/zinglib/pgvector/`, the application runtime in
  `Docker/zinglib/runtime/`. Use `POSTGRES_DATA_DIR` and `YOUR_LOCAL_PATH` to move either elsewhere (the repository-root
  `zinglib/`, for instance).

All backend APIs, scheduled tasks and the WebUI are unified inside the application container.

> **In the Setup Wizard, enter**: host `zinglib-db`, port `5432`, user `postgres`, password `postgres`, database `zinglib_library`.
> The application and the database share the compose network, where both `zinglib-db` (container name) and `pg17`
> (service name) resolve.
> ⚠️ The database name must be **`zinglib_library`** -- the built-in default inside the application code is
> `lrr_library`, so do not just accept the prefilled value.
>
> On first start `docker logs zinglib` shows `WARN db-init skipped: POSTGRES_DSN is empty` -- **that is expected**:
> with no connection details there is nothing to migrate, and the application still starts so you can reach the
> wizard. Once the wizard saves the connection the application creates the schema and applies migrations itself;
> no container restart is needed.

### 1.2 Manual containers (your own `docker` commands)

For when you want to control each step, or reuse a PostgreSQL you already run. The essential point: **the two
containers must share a network you create**, or the application cannot resolve the database (unless the database is
on another machine).

```bash
# 1) a dedicated network
docker network create zinglib-net

# 2) the database (PostgreSQL 17 + pgvector)
docker run -d --name zinglib-db --network zinglib-net \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=zinglib_library \
  -p 5432:5432 \
  -v /path/to/pgvector:/var/lib/postgresql/data \
  pgvector/pgvector:pg17

# 3) the application
docker run -d --name zinglib --network zinglib-net \
  -p 8501:8501 \
  -v /path/to/runtime:/app/runtime \
  jbking114514/zinglib:latest data-ui
```

* In the Setup Wizard the database host is **`zinglib-db`** (resolved by container name inside the network you created).
* **Another machine / an external database**: drop `--network` and hand the application a DSN instead, so the wizard
  needs no connection details at all:
  ```bash
  -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/zinglib_library?sslmode=disable'
  ```
* Back up both data directories (`/path/to/pgvector` and `/path/to/runtime`); `runtime/` holds the model weights, the
  local library, thumbnails and the per-gallery `.zinglib_meta/` backups.

### 1.3 Build from source (fallback)

```bash
cd Docker/main
docker build -t zinglib:local .
```

Then feed that image to the 1.1 compose file:

```bash
ZINGLIB_IMAGE=zinglib:local docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

or start it yourself with the 1.2 `docker run` commands (substituting `zinglib:local` for the image name).

Reasons to build it yourself: you are changing the code, you want different base images or dependency versions, or you
need a CPU architecture the published image does not cover.

### 1.4 Access the WebUI and the Setup Wizard

* Open `http://<host>:8501` in your browser.
* **On first entry the system guides you into the Setup Wizard**: complete the database connection and create the first admin account in the web interface. **No manual `.env` editing is required.**

## 2. First Initialization and Library Ingestion

After completing the Setup Wizard, put your manga folders under the host's `runtime/local_lib/` (inside the container: `/app/runtime/local_lib`), then run the following on the `Control` page:

1. `[Scan local library]`: detect the directory structure and create gallery records.
2. `[Enrich metadata]` (optional): read and parse `ComicInfo.xml`, staying interoperable with third-party tools (Komga, LANraragi, etc.).
3. `[Vectorise]`: compute SigLIP cover / page visual vectors and, if an LLM is configured, generate text descriptions. Vector computation takes some time.

> For daily maintenance, use the built-in **Schedule** page to run incremental ingestion of newly added folders.

## 3. Model Connection Strategy (Optional)

**Nothing here is required.** Browsing, reading, the file manager, `ComicInfo`, the SigLIP visual vectors and
"more like this" all run locally -- the built-in SigLIP model is downloaded and loaded by the application
container itself (zero-config automatic download, and it can be cleared at any time to release memory),
with no external endpoint involved.

You only need an OpenAI `/v1`-compatible endpoint (Ollama / LM Studio / vLLM, ...) if you want
**natural-language search or gallery descriptions**. The endpoint may run locally or be a remote service you choose; using a remote service sends the relevant requests off-device:

* `INGEST_API_BASE`: ingestion channel (image descriptions + text embeddings).
* `LLM_API_BASE`: retrieval channel (text embeddings and search intent routing).

Fill in one, both, or point them at the same endpoint; everything lives on the `Settings` page and can be
changed at any time. Leave them empty and the local capabilities stay in place -- **SigLIP approximate
search on its own is entirely enough.**

* **Advice**: given the sensitivity of this project's data, cloud APIs are not recommended.
* **Gotcha**: if your endpoint serves a reasoning model (such as DeepSeek-R1), **disable** "Separate
  reasoning_content and content in API responses" in LM Studio's **Developer Settings**, or use a plain
  Instruct / Chat model -- otherwise you may get empty descriptions back.

## 4. Runtime Suggestions

* The system runs the SigLIP model on CPU by default, so the first full ingestion (tens of thousands of books) may take a long time; daily incremental ingestion is effortless.
* Given the complexity introduced by ROCm, CUDA, and other GPU acceleration dependencies, hardware acceleration is not offered. If you want to experiment, you can try forcing GPU usage via `Docker/main/requirements.txt` and environment variables — no technical support is provided for that.

## 5. Sudo Privilege Escalation and Disaster Recovery

Because configuration is managed uniformly by the database, the system ships with a robust disaster-recovery mechanism:

* **Sudo Lock**: dangerous operations such as changing the database connection under `Settings -> General` require re-entering the current user's login password.
* **Configuration Backup**:
  * Download a runtime `app_config.json` backup with one click from the danger zone.
  * If configuration is lost due to a database migration, upload and restore it there.
* **Recovery Codes**: during initialisation/reset the system generates and prints 10 burn-after-reading recovery keys (stored as SHA256) in the logs. If you forget your password, or lock yourself out by mistyping the database IP, use any recovery code on the login page to enter **Recovery Mode** and force-correct the configuration and reset the admin password.

## 6. Network Configuration Advice

ZingLib **does not** contact external sites at runtime. A proxy is only relevant when:

* pulling base images and Python / Node dependencies;
* downloading the SigLIP model weights for the first time;
* your LLM / embedding endpoint sits behind a network that needs a proxy.

The container accepts standard proxy environment variables:

```
http_proxy=http://{proxy-host}:8888
https_proxy=http://{proxy-host}:8888
no_proxy=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12 # keep LAN and the database off the proxy
```

> Make sure `no_proxy` includes the database host, otherwise the application's database connections will be intercepted by the proxy.

## 7. Development & Verification

### 7.1 What a fresh clone can run

Everything below is **in this repository** and needs neither a container nor any dedicated host:

```bash
# Release-engineering guards (migrations / version single source / pinned deps)
python scripts/check_migrations.py
python scripts/check_version_consistency.py
python scripts/check_deps_pinned.py

# Backend unit tests -- run as modules (a script run cannot import webapi), cwd = Docker/main
cd Docker/main && python -m webapi.test_local_only_contract
# ... plus every test_*.py under webapi/; that directory is the authoritative list

# Frontend build + the node-side contract tests
cd Docker/main/webapp && npm ci && npm run build && node --test test_*.mjs
```

⚠️ The repository's `.gitignore` deliberately excludes `/tools/` and `AGENTS.md`: the workspace-level guard scripts,
mutation tests, container probes and deploy scripts **do not ship in a clone**. So the answer to "which guards does this
repository have" is **the three under `scripts/` above** -- do not present scripts that are not in the repository as the
project's guards.

### 7.2 What CI runs

`.github/workflows/ci.yml` runs three jobs on every push / PR, mirroring the three commands in 8.1:

| job | what it does |
| --- | --- |
| `release-guards` | the three guards under `scripts/` |
| `frontend` | `npm ci` → `npm run build` → `node --test test_*.mjs` |
| `backend` | starts a pgvector PostgreSQL, installs dependencies and the built frontend bundle **the way the image does**, and runs **every** `webapi/test_*.py` module (through the same migration entry point `entrypoint.sh` calls) |

Only after all three pass does CI publish the multi-architecture image to Docker Hub on a `v*` tag -- and it requires the
tag to match the application version exactly, so a mistyped tag is never published.

### 7.3 This project's deployment verification environment

The project's **only** deployment and integration-test environment is a dedicated Linux host (Ubuntu):

```bash
ssh <user>@<dev-host>
```

* Run image builds, container deployment, and integration regressions on that host. **Do not** use the development Windows Docker Desktop.
* Inspect remote containers, ports, and mounts before changing anything; keep test data isolated.
* 🔴 **A successful build, a live process or an empty log is not a regression pass**: report build, unit tests, runtime/API checks and visual checks **separately**.

## 8. Troubleshooting

* If you hit network problems downloading the SigLIP model or dependencies, fetch the model weights through a mirror or proxy of your choice and place them under `runtime/models/` (`runtime/` holds model weights and Python dependencies only — never library data). **This project does not ship or endorse any third-party bundle**; if you obtain files from an unofficial source, verify their origin and checksums yourself.
* If the WebUI is unreachable after startup, check `docker logs <container>` first. The usual cause is that the database in `POSTGRES_DSN` is not ready, or the `pgvector` extension is not enabled.
* Data lives on the host (default `./zinglib/`), so recreating the container does not lose configuration or library records.

## 9. Backup & Restore

**The one thing to remember: `.zinglib_meta/` holds the output of computation (SigLIP vectors +
reading history + hand-edited metadata). It contains neither your comic files nor your settings
and accounts.**

So after moving to a new machine, relocating the library, or `Settings → Danger zone → Rebuild database`:

* **Comic files** — your own backup strategy (this project never copies your files);
* **Settings and accounts** — a database `pg_dump` (`works` / `read_events` / `app_config` / `ui_users`);
* **Vectors and reading history** — the per-gallery backups in `.zinglib_meta/`: go to
  `Settings → Local library → Restore`, preview before confirming, and use the dialog's
  "Download full log" for the per-gallery result (success/failure, reason, gallery name, arcid).

🔴 **After a move every `arcid` changes** (it is a hash of the path), so a restore matches on the
**relative path inside the library** — keep the original directory structure.

Full steps, the meaning of every log field, and how to read "no backup ⇒ still needs recomputing":
see **[BACKUP_EN.md](BACKUP_EN.md)**.
