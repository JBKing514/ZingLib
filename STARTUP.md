# ZingLib 快速启动指南

> 🌐 语言 / Language: [中文](STARTUP.md) | [English](STARTUP_EN.md)

ZingLib 是一个**本地优先**的私人漫画 / 插画库管理应用：它不联网抓取内容，也不保存任何第三方站点凭据。核心图库功能完全在本地运行；只有用户主动配置兼容 OpenAI 的服务时，相关 AI 请求才会发送到所填端点。本文档覆盖从零部署、初始化、模型配置到排障的完整流程。

## 0. 前提条件

* **Docker 环境**：推荐 Docker Engine v27+ 或 Docker Desktop。
* **PostgreSQL 17+**：必须启用 `pgvector` 扩展（可直接使用 `pgvector/pgvector:pg17` 镜像）。
* **OpenAI 兼容后端（可选）**：支持 `/v1` 接口（LM Studio / vLLM / Ollama 等），用于驱动多模态描述生成和文本增强检索。
* **说明**：LLM 连接是可选项；未配置时系统仍可运行基于 SigLIP 的视觉检索、聚类推荐及基础的数据链路。

## 1. 基础步骤

1. **克隆项目**
   ```bash
   git clone <你的仓库地址>
   cd <仓库目录>
   ```

2. **构建并启动（推荐：从源码构建，可复现）**
   ```bash
   cd Docker/main
   docker build -t zinglib:local .
   docker run -d --name zinglib \
     -p 8501:8501 \
     -e POSTGRES_DSN='postgresql://postgres:postgres@<db-host>:5432/<db>?sslmode=disable' \
     -v /path/to/runtime:/app/runtime \
     zinglib:local data-ui
   ```

   也可以使用编排模板：
   ```bash
   docker compose -f Docker/quick_deploy_docker-compose.yml up -d
   ```

   该模板会拉起两个服务：`pg17`（PostgreSQL + pgvector）与 `data-ui`（应用本体）。
   注意模板里的 `image: {ACTUAL_IMAGE}` 是**占位符**，需要替换为你自己构建或拉取的镜像名；数据目录默认落在 `./zinglib/`，可用 `POSTGRES_DATA_DIR` 与 `YOUR_LOCAL_PATH` 覆盖。

   所有后端 API、定时任务与 WebUI 都已经统一收束进应用容器中。

3. **访问 WebUI**
   * 浏览器打开 `http://<host>:8501`。
   * **首次进入时，系统将引导您进入 Setup Wizard（初始化向导）**：在 Web 界面中完成数据库连接、建立首个管理员账号即可，**无需手动修改任何 `.env` 文件**。

## 2. 手动分步部署（可选）

适用于想逐个拉起容器或跨机部署的场景：

1. PostgreSQL（需带有 `pgvector` 扩展）
   ```bash
   docker compose -f Docker/pg17_docker-compose.yml up -d
   ```

2. ZingLib（核心服务）
   ```bash
   docker compose -f Docker/main_docker-compose.yml up -d
   ```

## 3. 首次初始化与数据入库

完成 Setup Wizard 后，把已有的漫画目录放到宿主机的 `runtime/local_lib/` 下（容器内为 `/app/runtime/local_lib`），然后在 `Control`（控制台）页面依次执行：

1. `[扫描本地库]`：识别目录结构，建立画廊记录。
2. `[补齐元数据]`（可选）：读取并解析 `ComicInfo.xml`，与第三方工具（Komga、LANraragi 等）的元数据保持互认。
3. `[向量化入库]`：调用 SigLIP 计算封面 / 内页视觉向量，并（若已配置 LLM）生成文本描述。视觉向量计算需要一定时间。

> 日常维护推荐使用系统内置的 **Schedule（定时任务）** 页面配置自动入库，对新增目录做增量处理。

## 4. 模型连接策略（可选）

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

## 5. 运行建议

* 系统默认使用 CPU 运行 SigLIP 模型，因此首轮全量入库（几十上万本）耗时可能会较长，但日常增量入库毫无压力。
* 考虑到引入 ROCm、CUDA 等图形加速依赖带来的复杂性，暂不提供 GPU 加速；如需自行尝试，可通过修改 `Docker/main/requirements.txt` 与环境变量强制启用，相关配置不提供技术支持。

## 6. Sudo 提权与灾难恢复

考虑到配置统一由数据库管理，本系统设计了完善的容灾机制：

* **Sudo 锁**：在 `Settings -> General` 中修改数据库连接等危险操作时，强制要求验证当前用户的登录密码解锁。
* **配置备份**：
  * 在危险区域内可一键**下载运行时 `app_config.json` 备份**。
  * 若因数据库迁徙导致配置丢失，可在此处**上传恢复**。
* **急救码 (Recovery Codes)**：系统在初始化 / 重置时会生成并在日志中打印 10 个用后即焚的恢复密钥（SHA256 保存）。当您忘记密码或不慎修改错了数据库 IP 导致无法登录时，可在登录页面使用任意一条急救码进入“恢复模式（Recovery Mode）”以强制纠正配置并重置管理员密码。

## 7. 网络配置建议

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

## 8. 开发与验证

本项目的**唯一**开发与集成测试环境是一台专用 Linux 主机（Ubuntu）：

```bash
ssh <user>@<dev-host>
```

* 在该主机上执行镜像构建、容器部署与集成回归；**不要**使用开发用的 Windows 桌面 Docker。
* 改动前先查看远端容器、端口与挂载；测试数据保持隔离。

契约测试：

```bash
# 后端
cd Docker/main/webapi
python test_local_only_contract.py
python -m webapi.test_xp_local

# 前端
cd Docker/main/webapp
npm run build
```

## 9. 故障排查

* 如果下载 SigLIP 模型或安装依赖时遇到网络问题，请自行通过镜像源或代理获取模型权重，放到 `runtime/models/` 下即可（`runtime/` 里只放模型权重与 Python 依赖，不含任何库数据）。**本项目不附带、也不背书任何第三方整合包**：从非官方来源取得的文件，请自行核对来源与校验值。
* 若容器启动后无法访问 WebUI，先用 `docker logs <容器名>` 查看启动日志；常见原因是 `POSTGRES_DSN` 指向的数据库未就绪或 `pgvector` 扩展未启用。
* 数据目录挂在宿主机（默认 `./zinglib/`），重建容器不会丢失配置与库记录。

## 10. 备份与恢复

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
