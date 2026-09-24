<p align="center">
  <img src="Media/ico/ZingLibLogo_256.png" width="256" alt="ZingLib">
  <br>
</p>

# ZingLib

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 🌐 语言 / Language: [中文](README.md) | [English](README_EN.md)

## 简介

一个**本地优先**的漫画 / 插画库管理应用。内容全部来自你自己的磁盘：不联网抓取内容，不保存任何第三方站点凭据，也没有遥测。核心图库功能完全在本地运行；只有你主动配置兼容 OpenAI 的服务时，相关 AI 请求才会发送到所填端点。

文件夹怎么放就怎么读，不用打包成 CBZ；用 SigLIP 视觉向量做「以图搜图 / 找相似」；手机、平板、桌面都能用，可以 PWA 安装。

## 功能

* 三端自适应（手机 / 平板 / 桌面），支持 PWA 安装
* 直接读原生文件夹与 ZIP / CBZ，内置文件管理器与元数据编辑器
* `ComicInfo.xml` 双向读写，与 Komga、LANraragi 等工具的元数据互认
* SigLIP 视觉检索：以图搜图、找相似
* 阅读器：单页 / 双页 / 连续滚动、预加载、缩略图导航、利手设置
* 阅读历史、收藏、自定义分类，以及基于阅读行为的偏好图（KMeans + PCA + KDE）
* 接上本地 LLM 后可用：自然语言搜本、画廊文字描述、AI 助理

## 配置要求

* **最低要求**：4 核 CPU / 4GB 内存 / 任意支持 Docker 的系统（NAS / Linux / Windows）
* **外部依赖**：一个启用了 `pgvector` 的 PostgreSQL 17+

### 模型配置（可选）

**不配任何模型也能完整使用。** 浏览、阅读、文件管理、`ComicInfo`、SigLIP 视觉向量与「找相似」全部在应用容器里本地完成 —— 视觉模型由容器自己下载与加载，不需要任何外部端点。

只有想要**自然语言搜本或画廊文字描述**时，才需要接一个兼容 OpenAI `/v1` 的后端（Ollama / LM Studio / vLLM 等）。这个端点既可以在本机，也可以是用户自行选择的远程服务；配置远程服务意味着相关请求会离开本机。不配置的话，靠 SigLIP 做近似搜索也完全够用；配置项都在设置页里，随时能改。

建议用本地模型、别接云端 API —— 这是你自己的库。

### 快速启动

镜像已公开在 Docker Hub（`jbking114514/zinglib`，同时提供 `linux/amd64` 与 `linux/arm64`）。部署方式按推荐程度排序：

**方式一：一键 compose（推荐）**

`Docker/` 下只有**一个** compose 文件，它会把**数据库和应用一起**拉起来。
⚠️ **别只起应用容器** —— 没有数据库连界面都进不去，这也是不再提供"只起应用"模板的原因。

```bash
git clone https://github.com/JBKing514/ZingLib.git && cd ZingLib
docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

起来后是两个容器：`zinglib-db`（PostgreSQL 17 + pgvector，5432）与 `zinglib`（应用，8501）。
库名默认 `zinglib_library`；数据默认落在 **compose 文件同级的 `Docker/zinglib/`**，可用 `POSTGRES_DATA_DIR`（数据库）与
`YOUR_LOCAL_PATH`（应用 runtime）改位置，用 `ZINGLIB_IMAGE` 换成自己构建的镜像。

**方式二：手动单独拉起（自己给 docker 命令）**

想自己控制每一步，或复用你已有的 PostgreSQL：

```bash
docker network create zinglib-net
docker run -d --name zinglib-db --network zinglib-net --restart unless-stopped \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=zinglib_library \
  -p 5432:5432 -v /path/to/pgvector:/var/lib/postgresql/data \
  pgvector/pgvector:pg17
docker run -d --name zinglib --network zinglib-net --restart unless-stopped \
  -p 8501:8501 -v /path/to/runtime:/app/runtime \
  jbking114514/zinglib:latest data-ui
```

两个容器必须在同一个自建网络里，否则应用解析不到数据库。数据库在**另一台机器**时去掉 `--network`，
改用 `-e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/zinglib_library?sslmode=disable'` 直接交给应用。
`--restart unless-stopped` 别省：备份还原完成后应用会**自己重启**来接回自动向量化，没有重启策略就会直接停在关机状态。

**方式三：从源码构建（备选）**

想自己改代码，或需要镜像没提供的架构时才走这条：

```bash
cd Docker/main && docker build -t zinglib:local .
```

然后把镜像喂给方式一的 compose：

```bash
ZINGLIB_IMAGE=zinglib:local docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

三种方式最后都一样：打开 `http://<你的IP>:8501`，跟着 **Setup Wizard** 完成数据库连接与管理员账号创建 ——
走方式一/二的话数据库主机填 `zinglib-db`、库名填 `zinglib_library`，**不需要手动改任何 `.env` 文件**。

> 部署细节、目录结构、代理设置 → [**STARTUP.md**](STARTUP.md)
> 换机器 / 库搬家 / 重建数据库后，怎么找回算了几小时的向量与阅读历史 → [**BACKUP.md**](BACKUP.md)

---

## 开发动机

本项目是因为我个人对目前阅读器方案痛点的一次反思：现有的阅读器要么 UI 老旧，要么不适配触屏，操作繁琐，上传麻烦。我受够了妥协所以自己 vibe 了一个，算是对自己的锻炼。

## 贡献

纯兴趣项目，不保证更新。欢迎提 Issue 和 PR，但本人纯外行，不一定会响应。

技术栈：Vue 3 / Pinia / Vuetify / Vite · FastAPI / Psycopg 3 · PostgreSQL + pgvector · PyTorch / Transformers（SigLIP）· SciPy / Scikit-learn。
想改代码、想跑测试：本地开发环境与「一个干净 clone 能跑什么」都在 [**STARTUP.md**](STARTUP.md) 的 **开发与验证** 一节；这份 README 只讲怎么把它跑起来。

## 致谢

架构与布局参考 [AstrBot](https://github.com/AstrBotDevs/AstrBot)；本地画廊与阅读器逻辑参考 [Komga](https://github.com/gotson/komga)。🙇

---

## 截图

### 手机模式

<p align="center">
  <img src="Media/screenshots/phone_dashboard.png" width="250" alt="phone_dashboard">
  <br>
</p>

### 平板模式

<p align="center">
  <img src="Media/screenshots/tablet_dashboard.png" width="770" alt="tablet_dashboard">
  <br>
</p>

### 桌面模式

<p align="center">
  <img src="Media/screenshots/desktop_dashboard.png" width="770" alt="desktop_dashboard">
  <br>
</p>

### 画廊详情

<p align="center">
  <img src="Media/screenshots/gallery_detail.png" width="250" alt="gallery_detail">
  <br>
</p>

### 阅读器 & 边看边搜

<p align="center">
  <img src="Media/screenshots/phone_reader.png" width="400" alt="phone_reader"><img src="Media/screenshots/phone_search.png" width="400" alt="phone_search">
  <br>
</p>

---

## ⚠️ 免责声明

本工具仅供 **个人图库归档与信息检索技术研究** 使用。用户需对自己导入、存储与访问的所有内容承担全部责任，并确保其来源与使用方式符合所在地法律法规及相应服务条款。

## 许可证

[MIT](LICENSE)。
