# ZingLib Quick Start Guide

> 🌐 Language / 语言: [English](STARTUP_EN.md) | [中文](STARTUP.md)

ZingLib is a **local-first** private manga / illustration library application: it does not crawl content from the network and stores no third-party site credentials. Core library features run locally; only AI requests are sent to an endpoint when the user explicitly configures an OpenAI-compatible service. This document covers deployment from scratch, initialisation, model configuration, and troubleshooting.

## 0. Prerequisites

* **Docker Environment**: Docker Engine v27+ or Docker Desktop recommended.
* **PostgreSQL 17+**: the `pgvector` extension must be enabled (the `pgvector/pgvector:pg17` image works out of the box).
* **OpenAI-Compatible Backend (Optional)**: any `/v1` interface (LM Studio / vLLM / Ollama, etc.) used for multimodal description generation and text-enhanced retrieval.
* **Note**: the LLM connection is optional. Without it the system still runs SigLIP-based visual retrieval, cluster recommendations, and the basic data pipeline.

## 1. Basic Steps

1. **Clone the Project**
   ```bash
   git clone <your-repository-url>
   cd <repository-folder>
   ```

2. **Build and Run (recommended: reproducible from source)**
   ```bash
   cd Docker/main
   docker build -t zinglib:local .
   docker run -d --name zinglib \
     -p 8501:8501 \
     -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/<db>?sslmode=disable' \
     -v /path/to/runtime:/app/runtime \
     zinglib:local data-ui
   ```

   Alternatively use the compose template:
   ```bash
   docker compose -f Docker/quick_deploy_docker-compose.yml up -d
   ```

   That template spins up two services: `pg17` (PostgreSQL + pgvector) and `data-ui` (the application).
   Note that `image: {ACTUAL_IMAGE}` in the template is a **placeholder** you must replace with your own built or pulled image. Data lands in `./zinglib/` by default; override with `POSTGRES_DATA_DIR` and `YOUR_LOCAL_PATH`.

   All backend APIs, scheduled tasks, and the WebUI are unified inside the application container.

3. **Access the WebUI**
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
   docker compose -f Docker/main_docker-compose.yml up -d
   ```

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

The project's **only** development and integration-test environment is a dedicated Linux host (Ubuntu):

```bash
ssh <user>@<dev-host>
```

* Run image builds, container deployment, and integration regressions on that host. **Do not** use the development Windows Docker Desktop.
* Inspect remote containers, ports, and mounts before changing anything; keep test data isolated.

Contract tests:

```bash
# Backend
cd Docker/main/webapi
python test_local_only_contract.py
python -m webapi.test_xp_local

# Frontend
cd Docker/main/webapp
npm run build
```

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
