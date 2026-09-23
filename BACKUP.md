# 备份与恢复

> English: [BACKUP_EN.md](BACKUP_EN.md)

ZingLib 的数据分散在三处，**它们不是同一份东西，缺一不可**：

| # | 位置 | 装什么 | 怎么备份 |
|---|---|---|---|
| 1 | `<YOUR_LOCAL_PATH>/local_lib/`（容器内 `/app/runtime/local_lib`） | **你的漫画文件本身**（目录或 `.zip`/`.cbz`），以及每画廊的 `ComicInfo.xml` | 用你自己的方式（rsync / 网盘 / 快照）。本项目不复制你的文件 |
| 2 | PostgreSQL（pgvector）库 | `works`（标题、标签、向量、`raw`）、`read_events`（阅读历史）、`app_config`（设置）、`ui_users` / `ui_sessions`（账号与会话） | `pg_dump`（见下） |
| 3 | 运行目录 `/app/runtime` 的其余部分 | 模型权重、缩略图、**每画廊备份 `.zinglib_meta/`**、迁移前快照 `backups/`、还原日志 `restore_logs/` | 整个目录一起备份 |

🔴 **`.zinglib_meta/` 是算力产物，不是"另一个数据库"。** 它由 ZingLib 自动写出，
**只覆盖向量与历史**，**不覆盖你的漫画文件、也不覆盖设置/账号**。
所以它**不能**代替第 1、2 项的备份，但能让你在"库搬了家 / 换机器 / 重建过数据库"之后
**不必再花几小时重算 SigLIP 向量**。

---

## 1. 每画廊备份（`.zinglib_meta/`）是什么

路径：`<库根>/.zinglib_meta/<arcid>_zinglib_metadata.json`
（`arcid` 是 `"local-" + sha1("local:" + 库内相对路径)`。）

它在**三个时机**自动写（每次都是整份重写、原子替换，**永不抛异常**）：

1. **算完向量之后**（`[向量化入库]` 完成那一刻）—— 这是它被**创建**的时机；
2. **编辑元数据之后**（改标题 / 标签 / 分类 / 书签、回写 ComicInfo 时）；
3. **读书之后** —— 只**刷新**已有文件里的阅读历史，**绝不会因此新建**一个备份。

文件内容（`schema: "zinglib.metadata.v1"`）：

```jsonc
{
  "schema": "zinglib.metadata.v1",
  "arcid": "local-…",
  "local_dir": "相对/路径/画廊目录名",   // 恢复时的匹配键，见第 4 节
  "written_at": "2026-09-23T…Z",
  "siglip": { "dim": 1152, "cover": [...], "page": [...], "model": "…" },
  "text":   { "dim": 1024, "vector": [...] },   // 只有配了 LLM 才有，缺失是正常状态
  "meta":   { "title": "…", "tags": [...], "bookmark": 12,
              "category": "doujinshi", "comicinfo": {...} },
  "history": [ { "read_time": 1750000000, "source_file": "…", "ingested_at": "…" } ]
}
```

* `history` 最多 **1000 条**（只限制文件大小，不影响功能）。
* `.zinglib_meta/` 会被扫描器与文件管理器**过滤掉**：你在"工具箱 → 文件管理器"里看不到它，
  也不用担心误删——**不要去动它**（用户数据目录里请把它和漫画一起备份）。

## 2. 备份数据库（第 2 项）

```bash
# 在能连到数据库的机器上执行；<...> 换成你的值
pg_dump -Fc -f zinglib-$(date +%F).dump \
  "postgresql://postgres:<password>@<db-host>:5432/lrr_library"
```

* 备份/恢复期间**不要**运行 `[向量化入库]` 或"重建数据库"，否则拿到的是半截状态。
* 库里的向量列很大，dump 也会跟着大 —— 这正是第 3 项（`.zinglib_meta/`）值得存在的理由：
  **恢复向量不必靠数据库 dump**，把库结构和设置恢复好，向量可以按画廊从 sidecar 补回来。

### 迁移前的自动快照

镜像每次启动都会先跑数据库迁移。**迁移前**它会把 10 张表逐表 `COPY` 成 `.csv.gz` 并写
`manifest.json`，落在：

```
/app/runtime/backups/pre_<旧版本>_<新版本>_<时间戳>/
```

只保留最近 **3** 份（`DB_INIT_BACKUP_KEEP`）。这是"迁移把库改坏了"时最省事的回退点，
但它是**迁移专用**的，不要指望它当日常备份。

## 3. 恢复：按场景选

### 场景 A · 同一个库、只是把记录弄丢了（最常见）

典型触发：数据库被清空 / 重建过（`works` 为空），但**文件还在原位**。

1. 完成 **Setup Wizard**（连上数据库、建管理员）；
2. 进入 `设置 → 本地库`（安装向导的"本地库"步骤里也有同一个入口）→ 点 **还原**；
3. 先出一份**预览**（`dry_run`，不写任何东西）：告诉你**总共多少画廊、能匹配上多少、多少没有备份**；
4. 确认后执行真实还原；
5. 想看逐条结果就点 **下载完整日志**（见第 5 节）。

### 场景 B · 换了机器 / 库搬了家

**关键：`arcid` 是路径的哈希，所以搬动之后所有 arcid 都变了** ——
旧 sidecar 里的 `arcid` 已经对不上任何行。这不是错误。

ZingLib 先**按 `local_dir`（库内相对路径）匹配**，匹配不到才退回 `arcid`。所以：

1. 先把漫画**放回同样的相对结构**（`库根/作者A/作品B/…` 里的 `作者A/作品B` 保持一致）；
2. 把 `.zinglib_meta/` 一起带过来（它就在库根下，跟着库走）；
3. 重新 `[扫描本地库]` 建立记录；
4. 再执行第 3 步的还原。

匹配不上的 sidecar 会被报成 **`orphan`**（孤立），**不会**被强行写进别人的行里。
用新路径重扫后重新向量化的画廊是**新的 arcid**，它的 sidecar 会在算完后重新生成。

### 场景 C · 恢复数据库本身（第 2 项）

```bash
pg_restore -d "postgresql://postgres:<password>@<db-host>:5432/lrr_library" --clean --if-exists zinglib-2026-09-23.dump
```

恢复完再启动应用（启动时会跑一次迁移检查）。**这条路径覆盖设置与账号**，是 sidecar 覆盖不到的那部分。

## 4. 还原的语义（"库里永远比备份新"）

还原**不是覆盖**，而是"**只补空缺**"：

| 对象 | 规则 |
|---|---|
| 视觉向量 / 文本向量 | **只为 `NULL` 的列写入**；已有向量一律保留（活数据比备份新） |
| 阅读历史 | `ON CONFLICT (arcid, read_time) DO NOTHING` —— **重复执行不会翻倍** |
| `raw`（标题 / 标签 / 书签 / 分类 / ComicInfo） | **按键合并，只补空缺**；**绝不整体替换**（整块替换曾静默抹掉过 `raw.bookmark`） |
| `category` | 备份里的分类会补进 `raw.eh_raw.category` |

所以「还原两次」是安全的，结果与还原一次相同。

## 5. 看懂还原结果

弹窗只给**计数**（不再列文件名），逐条明细在一份 JSONL 日志里：

* 日志位置（容器内）：`/app/runtime/restore_logs/metadata_restore_<32位id>.jsonl`，
  只保留最近 **20** 份；
* **只有真实还原会写日志**，点"预览"不落盘；
* 弹窗上的 **下载完整日志** 按钮会把这份文件下载下来（`application/x-ndjson`）。

日志**每一行都自述**，不需要你去对账计数器：

```jsonc
{"type":"restore_report","status":"restored","ok":true,"reason":"one line per gallery follows",
 "schema":"zinglib.restore_log.v1","started_at":"…","dry_run":false,
 "library_galleries":33,"sidecar_files":31}                  // 首行：这次还原的全景
{"type":"matched","status":"restored","ok":true,"reason":"restored from backup",
 "gallery":"作品B","arcid":"local-…","local_dir":"作者A/作品B","file":"local-….json",
 "visual":1,"text":0,"history":12,"meta":1}                  // 这一张画回来了
{"type":"no_sidecar","status":"no_backup","ok":true,
 "reason":"no backup file for this gallery: it must be recomputed",
 "gallery":"作品C","arcid":"local-…","local_dir":"作者A/作品C"} // 这张没有备份 → 仍需重算
{"type":"summary","ok":true,"dry_run":false,"total_galleries":33,"matched":31,"restored":31,
 "no_sidecar_count":2,"orphan_count":0,"duplicate_count":0,"failed_count":0,
 "unreadable_count":0,"had_failures":false,
 "summary":"31 restored, 31 matched, 2 without backup, 0 orphan, 0 duplicate, 0 failed, 0 unreadable"}
                                                             // 末行：计数器 + 一句人话
```

字段含义：

| 字段 | 含义 |
|---|---|
| `status` | `restored` / `preview`（预览）/ `no_backup`（该画廊没有备份）/ `orphan`（备份不属于本库任何画廊）/ `duplicate`（同一个画廊有多份备份，这份不是最新的）/ `failed` / `unreadable`（备份文件读不出来） |
| `ok` | **这一行是不是"错误"**。注意：`no_backup` 的 `ok` 是 `true` —— 它是**要你去重算的信息**，不是还原失败 |
| `reason` | 人话原因 |
| `gallery` | **你认得的画廊名**（路径最后一段）；`arcid` 只是一串哈希，认不出 |
| `arcid` / `local_dir` | 精确定位用 |
| `file` | 用到/涉及的那个备份文件名 |
| 末行 `summary` | 计数器 + `had_failures`（有没有 `failed`）+ 一句人话总结 |

弹窗里的 `no_sidecar_count` 与日志里的 `no_backup` 是同一件事：
**"这些画廊没有备份 ⇒ 之后必须重新跑一遍向量化"**。

> `duplicate` 只会在"库搬过家、旧路径的备份还没删"时出现：同一个画廊同时存在新旧两份备份，
> ZingLib 按**修改时间**取最新的一份使用，旧的那份报成 `duplicate` —— 这样 `matched` 不会虚高。

## 6. 危险操作：`设置 → 危险区 → 重建数据库`

它会 `DELETE FROM works`（**外键级联，会把 `read_events` 一起删掉**），
但**不动你的文件、也不动设置**。

* 如果你有 sidecar，大多数损失可以按第 3 步还原回来（向量 + 历史 + 手改的元数据）；
* 如果**没有** sidecar，那这一库的向量就得重算 —— 所以**第一次向量化跑完，`.zinglib_meta/` 就已经是你的保险**；
* 设置与账号不在 sidecar 覆盖范围内，靠第 2 项的数据库 dump。

## 7. 一句话清单

- [ ] 漫画文件本身：你自己的备份策略（第 1 项）
- [ ] 数据库：定期 `pg_dump`（第 2 项，含设置与账号）
- [ ] 运行目录整份（含 `.zinglib_meta/`、`backups/`）—— 搬家时**一起带走**
- [ ] 搬家后：**保持相对路径不变** → 重新扫描 → 还原
- [ ] 还原后：看一眼弹窗的 `no_sidecar_count`，非 0 就去重跑那些画廊的向量化
