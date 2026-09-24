# ZingLib Quick Start Guide

> 🌐 Language / 语言: [English](STARTUP_EN.md) | [中文](STARTUP.md)

ZingLib is a **local-first** private manga / illustration library application: it does not crawl content from the network and stores no third-party site credentials. Core library features run locally; only AI requests are sent to an endpoint when the user explicitly configures an OpenAI-compatible service. This document covers deployment from scratch, initialisation, model configuration, and troubleshooting.

## 0. Prerequisites

* **Docker Environment**: Docker Engine v27+ or Docker Desktop recommended.
* **PostgreSQL 17+**: the `pgvector` extension must be enabled (the `pgvector/pgvector:pg17` image works out of the box).
* **OpenAI-Compatible Backend (Optional)**: any `/v1` interface (LM Studio / vLLM / Ollama, etc.) used for multimodal description generation and text-enhanced retrieval.
* **Note**: the LLM connection is optional. Without it the system still runs SigLIP-based visual retrieval, cluster recommendations, and the basic data pipeline.

## 1. Basic Steps

The image is public on Docker Hub (`jbking114514/zinglib`) and ships both `linux/amd64` and `linux/arm64` (a NAS, a Raspberry Pi or a Mac all work).
**Pulling the image is the recommended path**; building from source is 1.3, and only needed if you intend to change the code, want your own image, or need an architecture the published image does not cover.

### 1.1 Pull and run (recommended)

No clone required:

```bash
docker run -d --name zinglib \
  -p 8501:8501 \
  -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/<db>?sslmode=disable' \
  -v /path/to/runtime:/app/runtime \
  jbking114514/zinglib:latest data-ui
```

* `<db-host>` is whatever runs PostgreSQL (use `host.docker.internal` for the same machine on Docker Desktop).
* Replace `latest` with a pinned version `1.0.0` if you prefer; `1.0`, `1` and `sha-<commit>` are published too.
* `/path/to/runtime` is the host data directory: model weights, the local library, thumbnails, the per-gallery `.zinglib_meta/` backups and the migration log all live there. **Back it up.**

### 1.2 Bring up the compose template (application + database)

```bash
git clone https://github.com/JBKing514/ZingLib.git && cd ZingLib
docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

That template starts two services: `pg17` (PostgreSQL + pgvector) and `data-ui` (the application). `data-ui` uses the
public image above by default and can be repointed with `ZINGLIB_IMAGE`; data lands in **`Docker/zinglib/`, beside the
compose file** (relative paths inside a compose file resolve against that file, not against your current directory).
Override `POSTGRES_DATA_DIR` (database) and `YOUR_LOCAL_PATH` (application runtime) -- point both at `zinglib/` in the
repository root if you would rather keep the data there.

All backend APIs, scheduled tasks and the WebUI are unified inside the application container.

### 1.3 Build from source (fallback)

```bash
cd Docker/main
docker build -t zinglib:local .
docker run -d --name zinglib \
  -p 8501:8501 \
  -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/<db>?sslmode=disable' \
  -v /path/to/runtime:/app/runtime \
  zinglib:local data-ui
```

Reasons to build it yourself: you are changing the code, you want different base images or dependency versions, or you
need a CPU architecture the published image does not cover. A local build feeds the 1.2 template with
`ZINGLIB_IMAGE=zinglib:local`.

### 1.4 Access the WebUI

* Open `http://<host>:8501` in your browser.
* **On first entry the system guides you into the Setup Wizard**: complete the database connection and create the first admin account in the web interface. **No manual `.env` editing is required.**

## 2. Manual Step-by-Step Deployment (Optional)

For scenarios where you want to bring containers up individually or deploy across hosts:

1. PostgreSQL (with the `pgvector` extension)
   ```bash
   docker compose -f Docker/pg17_docker-compose.yml up -d
   ```

2. ZingLib (core service)
   ```bash
   POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/lrr_library?sslmode=disable' \
     docker compose -f Docker/main_docker-compose.yml up -d
   ```

   * 🔴 **`POSTGRES_DSN` must point at the database from step 1** (use `host.docker.internal` for the same machine on Docker Desktop). The template's default is a **placeholder containing `<db-host>`**, so without this override the app cannot reach its database.
   * The image defaults to the published one; add `ZINGLIB_IMAGE=zinglib:local` for your own build.
   * The runtime directory lands in `Docker/zinglib/runtime/` beside the compose file; override with `YOUR_LOCAL_PATH`.

## 3. First Initialization and Library Ingestion

After completing the Setup Wizard, put your manga folders under the host's `runtime/local_lib/` (inside the container: `/app/runtime/local_lib`), then run the following on the `Control` page:

1. `[Scan local library]`: detect the directory structure and create gallery records.
2. `[Enrich metadata]` (optional): read and parse `ComicInfo.xml`, staying interoperable with third-party tools (Komga, LANraragi, etc.).
3. `[Vectorise]`: compute SigLIP cover / page visual vectors and, if an LLM is configured, generate text descriptions. Vector computation takes some time.

> For daily maintenance, use the built-in **Schedule** page to run incremental ingestion of newly added folders.

## 4. Model Connection Strategy (Optional)

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

## 5. Runtime Suggestions

* The system runs the SigLIP model on CPU by default, so the first full ingestion (tens of thousands of books) may take a long time; daily incremental ingestion is effortless.
* Given the complexity introduced by ROCm, CUDA, and other GPU acceleration dependencies, hardware acceleration is not offered. If you want to experiment, you can try forcing GPU usage via `Docker/main/requirements.txt` and environment variables — no technical support is provided for that.

## 6. Sudo Privilege Escalation and Disaster Recovery

Because configuration is managed uniformly by the database, the system ships with a robust disaster-recovery mechanism:

* **Sudo Lock**: dangerous operations such as changing the database connection under `Settings -> General` require re-entering the current user's login password.
* **Configuration Backup**:
  * Download a runtime `app_config.json` backup with one click from the danger zone.
  * If configuration is lost due to a database migration, upload and restore it there.
* **Recovery Codes**: during initialisation/reset the system generates and prints 10 burn-after-reading recovery keys (stored as SHA256) in the logs. If you forget your password, or lock yourself out by mistyping the database IP, use any recovery code on the login page to enter **Recovery Mode** and force-correct the configuration and reset the admin password.

## 7. Network Configuration Advice

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

## 8. Development & Verification

### 8.1 What a fresh clone can run

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

### 8.2 What CI runs

`.github/workflows/ci.yml` runs three jobs on every push / PR, mirroring the three commands in 8.1:

| job | what it does |
| --- | --- |
| `release-guards` | the three guards under `scripts/` |
| `frontend` | `npm ci` → `npm run build` → `node --test test_*.mjs` |
| `backend` | starts a pgvector PostgreSQL, installs dependencies and the built frontend bundle **the way the image does**, and runs **every** `webapi/test_*.py` module (through the same migration entry point `entrypoint.sh` calls) |

Only after all three pass does CI publish the multi-architecture image to Docker Hub on a `v*` tag -- and it requires the
tag to match the application version exactly, so a mistyped tag is never published.

### 8.3 This project's deployment verification environment

The project's **only** deployment and integration-test environment is a dedicated Linux host (Ubuntu):

```bash
ssh <user>@<dev-host>
```

* Run image builds, container deployment, and integration regressions on that host. **Do not** use the development Windows Docker Desktop.
* Inspect remote containers, ports, and mounts before changing anything; keep test data isolated.
* 🔴 **A successful build, a live process or an empty log is not a regression pass**: report build, unit tests, runtime/API checks and visual checks **separately**.

## 9. Troubleshooting

* If you hit network problems downloading the SigLIP model or dependencies, fetch the model weights through a mirror or proxy of your choice and place them under `runtime/models/` (`runtime/` holds model weights and Python dependencies only — never library data). **This project does not ship or endorse any third-party bundle**; if you obtain files from an unofficial source, verify their origin and checksums yourself.
* If the WebUI is unreachable after startup, check `docker logs <container>` first. The usual cause is that the database in `POSTGRES_DSN` is not ready, or the `pgvector` extension is not enabled.
* Data lives on the host (default `./zinglib/`), so recreating the container does not lose configuration or library records.

## 10. Backup & Restore

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
