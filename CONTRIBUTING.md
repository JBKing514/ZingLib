# 贡献指南 (Contribution Guide)

> 🌐 语言 / Language: [中文](CONTRIBUTING.md) | [English](CONTRIBUTING_EN.md)

先说实话：**这是纯兴趣项目，不保证更新。** 欢迎提 Issue 和 PR，但本人纯外行，不一定会响应 —— 提之前有个心理预期就好。

如果你想改点什么，下面这些是项目目前的做法，看一眼能省掉来回扯皮。

---

## 项目现在的约定

1. **零配置冷启动**：新功能不要引入必须手动设置的 `.env` 变量。配置项收敛到 WebUI 的 Setup Wizard 与数据库 `app_config` 表里（`constants.py` 提供默认值）。
2. **纯本地不变量（最重要的一条）**：应用只读本机文件系统，不抓取在线内容、不代理远程媒体、不上报遥测、不加载外部在线服务。**新增代码也不要做这几件事。**
3. **安全**：外部 HTTP 端口不裸奔（改为进程内 Worker 调用）、保留 CSRF 双提交 Cookie、危险操作接全局 Sudo 二次鉴权。
4. **算法改动**：涉及推荐算法、XP 聚类（KDE / PCA）这类改动的 PR，描述里能写清推导或思路最好 —— 写清楚主要是对你自己有用。
5. **前端手感**：尽量避免生硬的 DOM 跳变和阻塞主线程的同步请求。

---

## 比较欢迎的方向

* **算法**：视觉（SigLIP）与文本 / 元数据通道的融合权重、推荐势能模型的参数与兴趣漂移。
* **前端**：移动端手势、PWA 深度集成、CSS 动画打磨。
* **本地数据治理**：大库的首次扫描与增量扫描、`ComicInfo.xml` 读写保真度、标签规范化与分类归并。
* **模型接入**：VL（打标 / 描述）与纯文本 LLM 两条链路的配置保持独立；Prompt 统一放在 `constants.py` 与数据库配置里，不要在业务代码里写魔法字符串。

---

## 本地开发环境

前后端同源（前端构建产物由 FastAPI 托管），本地开发可以拆开跑。

1. **数据库**：需要一个带 `pgvector` 的 PostgreSQL 17+。只起一个库容器最省事：
   ```bash
   docker run -d --name zinglib-db \
     -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=zinglib_library \
     -p 5432:5432 -v /path/to/pgvector:/var/lib/postgresql/data \
     pgvector/pgvector:pg17
   ```
2. **后端 (FastAPI)**：
   ```bash
   cd Docker/main
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt   # 想跑测试才需要（httpx2 仅供 TestClient）
   uvicorn webapi.main:app --reload --port 8501
   ```
3. **前端 (Vue 3)**：
   ```bash
   cd Docker/main/webapp
   npm install
   npm run dev
   ```
   需要在 `vite.config.js` 里把 `/api` 代理到本地的 FastAPI 端口，保持同源。

> 完整的开发环境说明、一个干净 clone 能跑什么、CI 跑什么，见 [**STARTUP.md**](STARTUP.md) 第 7 节「开发与验证」。

---

## 提 PR 前（有余力的话）

* [ ] Python 代码是否过了 `black` / `isort`，该有的 Type Hint 有没有
* [ ] **冷启动**：清空数据库、没有任何旧配置的情况下，Setup Wizard 能不能正常走完
* [ ] **纯本地**：有没有引入任何在线获取 / 外部凭据 / 遥测
* [ ] **别阻塞主线程**：大文件同步读、模型推理这类操作要用 `anyio` 丢后台线程或交给进程内 Worker

感谢你愿意花时间看这个项目 🙇
