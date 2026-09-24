# ZingLib 快速启动指南

> 🌐 语言 / Language: [中文](STARTUP.md) | [English](STARTUP_EN.md)

ZingLib 是一个**本地优先**的私人漫画 / 插画库管理应用：它不联网抓取内容，也不保存任何第三方站点凭据。核心图库功能完全在本地运行；只有用户主动配置兼容 OpenAI 的服务时，相关 AI 请求才会发送到所填端点。本文档覆盖从零部署、初始化、模型配置到排障的完整流程。

## 0. 前提条件

* **Docker 环境**：推荐 Docker Engine v27+ 或 Docker Desktop。
* **PostgreSQL 17+**：必须启用 `pgvector` 扩展（可直接使用 `pgvector/pgvector:pg17` 镜像）。
* **OpenAI 兼容后端（可选）**：支持 `/v1` 接口（LM Studio / vLLM / Ollama 等），用于驱动多模态描述生成和文本增强检索。
* **说明**：LLM 连接是可选项；未配置时系统仍可运行基于 SigLIP 的视觉检索、聚类推荐及基础的数据链路。

## 1. 部署

镜像已公开在 Docker Hub（`jbking114514/zinglib`），同时提供 `linux/amd64` 与 `linux/arm64`（NAS / 树莓派 / Mac 都能直接用）。

**部署方式按推荐程度排序：1.1 一键 compose（推荐）→ 1.2 手动单独拉起（自己给 docker 命令）→ 1.3 从源码构建（备选）。**

### 1.1 一键部署：唯一的 compose 脚本（推荐）

`Docker/` 下**只有一个 compose 文件**，它会把数据库和应用一起拉起来。⚠️ **不要试图只起应用容器** ——
没有数据库连界面都进不去，这也是为什么不再提供"只起应用"的模板。

```bash
git clone https://github.com/JBKing514/ZingLib.git && cd ZingLib
docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

它会拉起两个容器：

| 容器名 | 作用 | 对外端口 |
|---|---|---|
| `zinglib-db` | PostgreSQL 17 + `pgvector` | 5432 |
| `zinglib` | ZingLib 本体（公开镜像） | 8501 |

* 应用默认用公开镜像 `jbking114514/zinglib:latest`；要用自己构建的，加 `ZINGLIB_IMAGE=zinglib:local`。
* 数据库默认 **`zinglib_library`**，用户 `postgres`，密码 `postgres`；可用 `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` 覆盖。
* 数据目录默认落在 **compose 文件同级的 `Docker/zinglib/`**（compose 里的相对路径是相对 **compose 文件**解析的，不是相对当前目录）：
  数据库在 `Docker/zinglib/pgvector/`，应用 runtime 在 `Docker/zinglib/runtime/`。
  想把它们挪到别处（比如仓库根的 `zinglib/`），用 `POSTGRES_DATA_DIR` 与 `YOUR_LOCAL_PATH` 指过去即可。

所有后端 API、定时任务与 WebUI 都收束在应用容器里。

> **Setup Wizard 里数据库那一栏填**：主机 `zinglib-db`、端口 `5432`、用户 `postgres`、密码 `postgres`、数据库 `zinglib_library`。
> 应用与数据库在同一个 compose 网络里，`zinglib-db`（容器名）与 `pg17`（服务名）都能解析。
> ⚠️ 数据库名要填 **`zinglib_library`** —— 应用代码里的内置默认库名是 `lrr_library`，别照抄预填值。
>
> 首次启动时 `docker logs zinglib` 里会有 `WARN db-init skipped: POSTGRES_DSN is empty` —— **这是正常的**：
> 还没有连接信息时不可能迁移，应用仍然会起来让你走向导；向导保存连接后**应用会自己建表与跑迁移**，不需要重启容器。

### 1.2 手动单独拉起（自己给 docker 命令）

想自己控制每一步、或者复用你已有的 PostgreSQL 时走这条。要点：**两个容器必须在同一个自建网络里**，
否则应用解析不到数据库（跨机部署除外）。

```bash
# 1) 专用网络
docker network create zinglib-net

# 2) 数据库（PostgreSQL 17 + pgvector）
docker run -d --name zinglib-db --network zinglib-net \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=zinglib_library \
  -p 5432:5432 \
  -v /path/to/pgvector:/var/lib/postgresql/data \
  pgvector/pgvector:pg17

# 3) 应用
docker run -d --name zinglib --network zinglib-net \
  -p 8501:8501 \
  -v /path/to/runtime:/app/runtime \
  jbking114514/zinglib:latest data-ui
```

* Setup Wizard 里数据库主机填 **`zinglib-db`**（同一自建网络内按容器名解析）。
* **跨机 / 用外部数据库**：去掉 `--network`，改用环境变量直接把 DSN 交给应用，
  向导里就不用再填连接信息了：
  ```bash
  -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/zinglib_library?sslmode=disable'
  ```
* 两处数据目录（`/path/to/pgvector` 与 `/path/to/runtime`）都要备份；`runtime/` 里是模型权重、本地库、
  缩略图与每画廊备份 `.zinglib_meta/`。

### 1.3 从源码构建（备选）

```bash
cd Docker/main
docker build -t zinglib:local .
```

然后把镜像喂给 1.1 的 compose：

```bash
ZINGLIB_IMAGE=zinglib:local docker compose -f Docker/quick_deploy_docker-compose.yml up -d
```

或者按 1.2 的 `docker run` 自己起（把镜像名换成 `zinglib:local`）。

需要自己构建的典型情形：要改代码、要换基础镜像或依赖版本、或需要公开镜像未覆盖的 CPU 架构。

### 1.4 访问 WebUI 与 Setup Wizard

* 浏览器打开 `http://<host>:8501`。
* **首次进入时，系统将引导您进入 Setup Wizard（初始化向导）**：在 Web 界面中完成数据库连接、建立首个管理员账号即可，**无需手动修改任何 `.env` 文件**。

## 2. 首次初始化与数据入库

完成 Setup Wizard 后，把已有的漫画目录放到宿主机的 `runtime/local_lib/` 下（容器内为 `/app/runtime/local_lib`），然后在 `Control`（控制台）页面依次执行：

1. `[扫描本地库]`：识别目录结构，建立画廊记录。
2. `[补齐元数据]`（可选）：读取并解析 `ComicInfo.xml`，与第三方工具（Komga、LANraragi 等）的元数据保持互认。
3. `[向量化入库]`：调用 SigLIP 计算封面 / 内页视觉向量，并（若已配置 LLM）生成文本描述。视觉向量计算需要一定时间。

> 日常维护推荐使用系统内置的 **Schedule（定时任务）** 页面配置自动入库，对新增目录做增量处理。

## 3. 模型连接策略（可选）

**不配置任何模型也能用**：浏览、阅读、文件管理、`ComicInfo`、SigLIP 视觉向量与「找相似」全部在本地完成 ——
内置 SigLIP 由应用容器自己下载并加载（零配置自动下载，可随时清理释放内存），不需要任何外部端点。

只有想要**自然语言搜本 / 画廊文字描述**时，才需要接一个兼容 OpenAI `/v1` 的端点（Ollama / LM Studio / vLLM 等）。端点可以位于本机，也可以是用户自行选择的远程服务；使用远程服务意味着相关请求会离开本机：

* `INGEST_API_BASE`：入库通道（图像描述 + 文本向量）。
* `LLM_API_BASE`：检索通道（文本向量与搜索意图路由）。

两者可以只填一个，也可以指向同一个端点；配置项都在 `Settings` 页面，随时可改。不填就一直用本地能力 ——
**只靠 SigLIP 做近似搜索也完全够用。**

* **建议**：基于本项目数据的敏感性，不建议使用云端 API。
* **小坑**：如果端点上是支持「思考 / 推理」的模型（如 DeepSeek-R1），请在 LM Studio 的 **Developer Settings** 里
  **关闭** "Separate reasoning_content and content in API responses"，或直接用 Instruct / Chat 模型 —— 否则可能返回空描述。

## 4. 运行建议

* 系统默认使用 CPU 运行 SigLIP 模型，因此首轮全量入库（几十上万本）耗时可能会较长，但日常增量入库毫无压力。
* 考虑到引入 ROCm、CUDA 等图形加速依赖带来的复杂性，暂不提供 GPU 加速；如需自行尝试，可通过修改 `Docker/main/requirements.txt` 与环境变量强制启用，相关配置不提供技术支持。

## 5. Sudo 提权与灾难恢复

考虑到配置统一由数据库管理，本系统设计了完善的容灾机制：

* **Sudo 锁**：在 `Settings -> General` 中修改数据库连接等危险操作时，强制要求验证当前用户的登录密码解锁。
* **配置备份**：
  * 在危险区域内可一键**下载运行时 `app_config.json` 备份**。
  * 若因数据库迁徙导致配置丢失，可在此处**上传恢复**。
* **急救码 (Recovery Codes)**：系统在初始化 / 重置时会生成并在日志中打印 10 个用后即焚的恢复密钥（SHA256 保存）。当您忘记密码或不慎修改错了数据库 IP 导致无法登录时，可在登录页面使用任意一条急救码进入“恢复模式（Recovery Mode）”以强制纠正配置并重置管理员密码。

## 6. 网络配置建议

ZingLib 运行时**不会**主动访问外部站点。只有在以下场景才可能需要代理：

* 拉取基础镜像与 Python / Node 依赖；
* 首次下载 SigLIP 模型权重；
* 你的 LLM / Embedding 端点位于需要代理才能到达的网络。

容器支持配置简单的 HTTP/HTTPS 代理，可通过环境变量指定：

```
http_proxy=http://{代理地址}:8888
https_proxy=http://{代理地址}:8888
no_proxy=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12 # 局域网与数据库不走代理
```

> 请确保 `no_proxy` 中包含数据库主机，否则容器内应用访问数据库会被代理拦截。

## 7. 开发与验证

### 7.1 一个干净 clone 能跑什么

下面这些**都在仓库里**，不需要容器、也不需要任何专用主机：

```bash
# 发布工程守卫（迁移集 / 版本唯一源 / 依赖与基础镜像锁定）
python scripts/check_migrations.py
python scripts/check_version_consistency.py
python scripts/check_deps_pinned.py

# 后端单元测试 —— 必须以模块方式跑（脚本方式 import 不到 webapi），cwd 在 Docker/main
cd Docker/main && python -m webapi.test_local_only_contract
# ……以及 webapi/ 下的全部 test_*.py，权威清单就是那个目录本身

# 前端构建 + node 侧契约测试
cd Docker/main/webapp && npm ci && npm run build && node --test test_*.mjs
```

⚠️ 仓库的 `.gitignore` 刻意排除了 `/tools/` 与 `AGENTS.md`：**工作区级的守卫脚本、变异测试、容器探针、部署脚本都不随 clone 分发**。
所以"这个仓库有哪些守卫"的答案就是**上面 `scripts/` 里的三个**，别把不在仓库里的脚本说成项目的守卫。

### 7.2 CI 跑什么

`.github/workflows/ci.yml` 在每次 push / PR 上跑三个 job，和 8.1 的三条一一对应：

| job | 内容 |
| --- | --- |
| `release-guards` | `scripts/` 下那三个守卫 |
| `frontend` | `npm ci` → `npm run build` → `node --test test_*.mjs` |
| `backend` | 起一个带 `pgvector` 的 PostgreSQL，按**镜像里的布局**装依赖与前端构建产物，跑**全部** `webapi/test_*.py` 模块（用的是 `entrypoint.sh` 同一个迁移入口） |

三者全绿之后，CI 才在打 `v*` 标签时把多架构镜像发布到 Docker Hub —— 而且要求**标签与应用版本严格一致**，敲错版本号的标签不会被发布。

### 7.3 本项目的部署验证环境

本项目**唯一**的部署与集成回归环境是一台专用 Linux 主机（Ubuntu）：

```bash
ssh <user>@<dev-host>
```

* 在该主机上执行镜像构建、容器部署与集成回归；**不要**使用开发用的 Windows 桌面 Docker。
* 改动前先查看远端容器、端口与挂载；测试数据保持隔离。
* 🔴 **构建成功、进程活着、日志为空都不等于回归通过**：构建、单元测试、运行时 API、视觉这四类结果要**分开**报告。

## 8. 故障排查

* 如果下载 SigLIP 模型或安装依赖时遇到网络问题，请自行通过镜像源或代理获取模型权重，放到 `runtime/models/` 下即可（`runtime/` 里只放模型权重与 Python 依赖，不含任何库数据）。**本项目不附带、也不背书任何第三方整合包**：从非官方来源取得的文件，请自行核对来源与校验值。
* 若容器启动后无法访问 WebUI，先用 `docker logs <容器名>` 查看启动日志；常见原因是 `POSTGRES_DSN` 指向的数据库未就绪或 `pgvector` 扩展未启用。
* 数据目录挂在宿主机（默认 `./zinglib/`），重建容器不会丢失配置与库记录。

## 9. 备份与恢复

**唯一要记住的一句：`.zinglib_meta/` 里是算力产物（SigLIP 向量 + 阅读历史 + 手改的元数据），
它不覆盖你的漫画文件、也不覆盖设置与账号。**

因此在换机器 / 库搬家 / `设置 → 危险区 → 重建数据库` 之后：

* **漫画文件**：用你自己的备份策略（本项目不复制你的文件）；
* **设置与账号**：靠数据库 `pg_dump`（`works` / `read_events` / `app_config` / `ui_users`）；
* **向量与阅读历史**：靠每画廊备份 `.zinglib_meta/` —— 在 `设置 → 本地库 → 还原` 里
  先预览再确认，弹窗上的"下载完整日志"可以拿到逐画廊的结果（成功/失败、原因、画廊名、arcid）。

🔴 **库搬家后 `arcid` 会全变**（它是路径的哈希），所以还原是**按库内相对路径匹配**的 ——
请保持原来的相对目录结构。

完整步骤、日志字段含义、以及"缺备份 ⇒ 仍需重算"的读法，见 **[BACKUP.md](BACKUP.md)**。
