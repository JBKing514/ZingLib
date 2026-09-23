<p align="center">
  <img src="Media/ico/ZingLibLogo_256.png" width="256" alt="ZingLib">
  <br>
</p>

# ZingLib

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 🌐 Language / 语言: [English](README_EN.md) | [中文](README.md)

## What it is

A **local-first** manga / illustration library manager. Everything comes from your own disks: it does not crawl content from the network, stores no third-party site credentials, and has no telemetry. Core library features run locally; only AI requests are sent to an endpoint when you explicitly configure an OpenAI-compatible service.

Point it at folders as they are -- no repacking into CBZ. SigLIP visual vectors give you reverse image search and "more like this". It works on phone, tablet and desktop, and installs as a PWA.

## Features

* Adaptive layout for phone / tablet / desktop, installable as a PWA
* Reads native folders plus ZIP / CBZ in place; built-in file manager and metadata editor
* Reads and writes `ComicInfo.xml`, interoperable with Komga, LANraragi and friends
* SigLIP visual search: reverse image search and "more like this"
* Reader: single page / double page / continuous scroll, preloading, thumbnail navigation, dominant-hand setting
* Reading history, favourites, custom categories, and a preference map (KMeans + PCA + KDE) built from your reading behaviour
* With a local LLM attached: natural-language search, gallery descriptions, an AI assistant

## Requirements

* **Minimum**: 4-core CPU / 4GB RAM / any system that runs Docker (NAS / Linux / Windows)
* **External dependency**: PostgreSQL 17+ with the `pgvector` extension enabled

### Model configuration (optional)

**Nothing here is required.** Browsing, reading, the file manager, `ComicInfo`, the SigLIP visual vectors and "more like this" all run inside the application container -- the vision model is downloaded and loaded by the container itself, with no external endpoint.

You only need a backend speaking the OpenAI `/v1` API (Ollama, LM Studio, vLLM, ...) if you want **natural-language search or gallery descriptions**. The endpoint may be local or a remote service you choose; using a remote service sends the relevant requests off-device. Without one, SigLIP approximate search on its own is entirely enough. Everything is configurable in the settings page and can be changed at any time.

Prefer local models over cloud APIs -- this is your own library.

### Quick start

**Option 1 -- build from source (recommended)**

```bash
cd Docker/main
docker build -t zinglib:local .
docker run -d --name zinglib \
  -p 8501:8501 \
  -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/<db>?sslmode=disable' \
  -v /path/to/runtime:/app/runtime \
  zinglib:local data-ui
```

Open `http://<your-ip>:8501` and follow the **Setup Wizard** to configure the database and create the first admin account. No `.env` editing.

**Option 2 -- use `Docker/quick_deploy_docker-compose.yml`** (application + pgvector)

`image: {ACTUAL_IMAGE}` there is a placeholder you must replace with your own built or pulled image. Data lands in `./zinglib/` by default; override with `POSTGRES_DATA_DIR` and `YOUR_LOCAL_PATH`.

> Deployment details, directory layout, proxy settings -> [**STARTUP_EN.md**](STARTUP_EN.md)
> New machine, relocated library, or a rebuilt database -- how to get back the hours of embeddings and your reading history -> [**BACKUP_EN.md**](BACKUP_EN.md)

---

## Motivation

This project is the result of me thinking about what is wrong with the readers I have used: the existing ones either look dated, or are not built for touch, or take too many taps to do anything, or make uploading a chore. I was tired of compromising, so I vibed one myself -- which also counts as practice.

## Contributing

A spare-time hobby project. There is no promise of updates. Issues and PRs are welcome, but I am not a professional developer and may not get to them.

Stack: Vue 3 / Pinia / Vuetify / Vite · FastAPI / Psycopg 3 · PostgreSQL + pgvector · PyTorch / Transformers (SigLIP) · SciPy / Scikit-learn.
Development environment and how to run the tests -> [**AGENTS.md**](AGENTS.md).

## Credits

Architecture and layout inspired by [AstrBot](https://github.com/AstrBotDevs/AstrBot); local gallery and reader logic informed by [Komga](https://github.com/gotson/komga). 🙇

---

## Screenshots

### Mobile

<p align="center">
  <img src="Media/screenshots/phone_dashboard.png" width="250" alt="phone_dashboard">
  <br>
</p>

### Tablet

<p align="center">
  <img src="Media/screenshots/tablet_dashboard.png" width="770" alt="tablet_dashboard">
  <br>
</p>

### Desktop

<p align="center">
  <img src="Media/screenshots/desktop_dashboard.png" width="770" alt="desktop_dashboard">
  <br>
</p>

### Gallery details

<p align="center">
  <img src="Media/screenshots/gallery_detail.png" width="250" alt="gallery_detail">
  <br>
</p>

### Reader & search while reading

<p align="center">
  <img src="Media/screenshots/phone_reader.png" width="400" alt="phone_reader"><img src="Media/screenshots/phone_search.png" width="400" alt="phone_search">
  <br>
</p>

---

## ⚠️ Disclaimer

This tool is intended for **personal library archiving and information-retrieval research**. Users assume full responsibility for all content they import, store, or access, and must ensure its origin and use comply with the laws and regulations of their jurisdiction as well as any applicable terms of service.

## License

[MIT](LICENSE).
