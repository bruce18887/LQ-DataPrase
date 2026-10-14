# e2e slot 池并行化设计（全量轮压到 10 分钟级）

日期：2026-10-14 · 状态：待评审
前置阅读：`docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md`（三层判据 T1/T2/T3，本设计不动它）
清理台账：`docs/reference/e2e-tier-triage.md`
§10 的隔离事实已由一轮只读探针 + 我逐条回读源码确认（每条带行号）。

## 1. 目标与非目标

**目标**

- 夜间全量轮 **与** 「功能收口 / FF 并入本地 master 前的全量」都要进 10 分钟级。用户 2026-10-14 明确两处都算。
- 不减少任何判据：一条断言都不删、不降超时、不靠 skip 换时间。
- `test:e2e:affected` 快门禁不退化（仍 <5min）。

**非目标**

- 后端 888 例不进 10min 口径（用户拍：只 e2e 全量轮）。slot 化之后 e2e 不再写仓库根 `db.sqlite3`/`media/`，
  「与后端套件并跑」变成顺带可行，**本轮不做**。
- 不砍单例成本（2.89s/例里主要是 SPA 冷启 vendor：echarts 1.1MB + ag-grid 1.2MB + element-plus 1.0MB）。
  4 slot 已够达标，先不引入跨用例共享 context 这种新的状态耦合面。
- 不做多机分片、不建 CI。

## 2. 现取基线（2026-10-14，不是引用旧记录）

| 指标 | 值 | 来源 |
|---|---|---|
| 用例数 / 文件数 | **386 例 / 74 文件**（剔除 setup） | `cd frontend && npx playwright test --list --reporter=json` |
| 墙钟 | **19.7min**（workers=1 串行） | `tasks/e2e-nightly/LATEST.md` 轮次 `2026-10-14-1108` |
| 单价 | **2.89s/例**（只计通过用例） | 同上，由 `results.json` 复算 |
| 通过用例时长合计 | **1056s** | `tasks/e2e-nightly/2026-10-14-1108/results.json` |
| 文件时长分布 | max **85.0s**（`analysis/serial-overlap`）· median **7.8s** · top5 占 **31%** | 同上 |
| 单例最长 | 30.5s（`analysis/axis-label-precision` 直方图 X 轴） | 同上 |
| 种子媒体规模 | **154 文件 / 12 目录 / 1.1GB**（含 `media/sftp/`）· 源 `SampleData` 88 CSV / 715MB | 实测 `find media` |

最贵的 12 个文件（pass 时长）：`serial-overlap` 85.0 · `outlier-handling` 76.1 · `view-data` 55.2 ·
`sftp/search` 54.3 · `analysis.spec` 53.5 · `multi-file` 43.8 · `axis-label-precision` 42.6 ·
`data.spec` 41.5 · `file-correlation` 32.6 · `exports` 29.4 · `gage-qqbox-repro` 28.7 · `legend-color` 26.9。

**推演**：1056s / 4 slot = 264s 理想下限；按并发争用 ×1.3 → **~5.7min**，加 slot 池启动（预算 20–40s）→ **~6.3min**。
`specs=450` 天花板：450×2.89×1.3/4 ≈ 424s + 启动 ≈ **7.6min**，仍在 10min 级。
最大单文件 85s 远小于 makespan，不构成并行拖尾瓶颈。

## 3. 为什么必须动隔离模型，以及为什么不是「worker 绑 slot」

串行的三个理由（都不是产品问题，是 harness 问题）：

1. **共享 admin 单账号 + 账号级持久态**：`UserSetting` 一人一行（`apps/accounts/models.py:56-111`）、
   `analysis_chart_state`（`analysis_chart_memory` 默认 true，翻动即写回）、`page_size`、主题。
   `e2e/fixtures/auth.setup.ts:58-82` 只能在**开跑前**钉一次默认值，治跨轮不治跨用例
   （`docs/tasks/lessons.md:385`、`docs/reference/e2e-tier-triage.md:396` 把这条判为「组合范围验证必须 workers=1」的根因）。
2. **单库单进程**：一个 `db.sqlite3`（`config/settings/development.py:29-33`）+ 一个 `runserver 8000 --noreload`
   + 一个 preview 3000（`frontend/playwright.config.ts:130-170`）。
3. **快照-还原助手天然要求串行**：`settings.spec.ts:68-78` 这类「读原值→改→finally 还原」并发下会读到别人的中间态
   （`lessons.md:1612`）。

上一轮我推荐「每个 Playwright worker 绑一个 slot」，**改为「1 进程 = 1 worker = 1 slot」**，理由是要保住两件事：

- **文件不跨 slot 拆**。`fullyParallel: true`（`playwright.config.ts:50`）下同文件的用例会散到不同 worker；
  即便每 worker 一套独立库，也会让「同文件第 3 条在第 3 个 slot 看到与第 1 条不同的起始账号态」——
  新的、无法复现的故障面。
- **文件→slot 的组合要可复现**。交给 Playwright 决定谁和谁同 slot，则组合每次运行都在变，污染只能反复重发现；
  自己按文件分区后，同一张分区表决定组合，红了能原地复跑。

代价是报告要合并（官方 `npx playwright merge-reports` + blob reporter），换来分区可控、崩池隔离
（一个 slot 挂其余继续，这是 `lessons.md:640` 那类 dev server 死亡事故的正确形状），
且每个 slot 进程内仍 `workers=1` —— **现在这套按串行调好的 helper 一行都不用改**。

## 4. 架构

```
scripts/e2e_pool.mjs                     ← 新增：池编排器（并行全量的唯一入口）
  ├─ ① 构建模板  在 %TEMP%\lqdp-e2e-template\ 里 migrate + seed_users + seed_test_data
  │              → template\db.sqlite3(4MB) + template\media(1.1GB，源锚在仓库 SampleData)
  ├─ ② 前端构建  npm run build 一次（实测 6.6s）
  ├─ ③ 分区      LPT(files, 每文件 pass 时长取自最近夜跑 results.json) → N 桶
  ├─ ④ 起 slot   N 个 `npx playwright test <该桶文件列表> --workers=1` 子进程
  │              每进程 env（全部已存在，无需新增 settings 档）：
  │                LQDP_SYSTEM_CONFIG_FILE=<slot>\system-config.json  （data_dir + temp_dir 指向 slot）
  │                LQDP_SKIP_STORAGE_MIGRATION=1                     ← 承重，见 §4.1
  │                SECRET_KEY=slot-<i>                               （base.py:17 已读 env）
  │                SFTP_SESSION_REDIS_URL=redis://localhost:6379/<i>  （base.py:271 已读 env）
  │                E2E_PORT=810i / E2E_FRONTEND_PORT=310i             （config:31,38 已参数化）
  │                LQDP_ACCESS_TOKEN_MINUTES=720
  │              每进程自带 webServer 对（Playwright 自起自收），各自写 slot<i>/run.log
  └─ ⑤ 合并      blob → merge-reports → 单一 results.json + playwright-report
```

**slot 目录**（每 slot 独占，`%TEMP%\lqdp-e2e-slot-<i>\`）

- `db.sqlite3` ← 模板库**整文件拷贝**（4MB）。库名硬编码 `BASE_DIR/db.sqlite3`，而 `BASE_DIR` 由 `data_dir` 重定向
  （`development.py:12-22`）⇒ **不需要任何代码改动**就能让每 slot 各有一份库。
- `system-config.json` ← 两个字段都要给：`data_dir` 与 `temp_dir` 指向本 slot 目录。
- `media/` ← 对模板 media 做**硬链镜像**（154 文件，元数据操作、不占磁盘、不搬数据；同卷 C:）。
- `.downloads/`、`.auth/admin-slot<i>.json` ← 从全局单路径改为 slot 内路径。

### 4.1 承重安全阀：`LQDP_SKIP_STORAGE_MIGRATION=1`

`apply_system_config` 在 `data_target != orig` 时会执行 `_migrate(original_base_dir, data_target)`
（`apps/common/system_config.py:389-391`），而 `_migrate` 是**搬走并删源**的语义。
把 slot 的 `data_dir` 指到 `%TEMP%` 而不设这个开关，等于让 Django 启动时把**仓库根的 `db.sqlite3` 搬走、
`media/` rmtree 掉** —— 这正是 `playwright.config.ts:11-13` 今天把 `data_dir` 钉在项目根的原因（注释写得很清楚：
否则首次启动会把项目根数据搬到 `~/LQ-DataPrase`，测试数据全丢）。
该开关已存在且语义正确（`system_config.py:71-83`：置位时 `data_target` 直接取配置值，跳过迁移）。
**本设计把它当作硬前提**，P1 第一步就是「不带这个开关时故意跑一次单 slot，确认它确实会毁仓库根 media」
这条只做代码走读、**不做破坏性实测**（改坏/删数据来证明断言承重是被明令禁止的验证方式）。

### 4.2 为什么仍然保留同名 `admin`，不做 per-slot 用户

探针建议「每 slot 独立用户名」，我不采纳，因为它要的前提这里不成立：

- 列表按 `owner` 过滤（`apps/datafiles/views/file_views.py:99`，且 `bulk_delete/product_codes/combine/…` 全部 owner-scoped），
  而 **owner 是每 slot 自己那份库里的行** ⇒ 副本之间本来就不互见。
- 上传落盘 `MEDIA_ROOT/data/<username>/<single|batch>/`（`apps/datafiles/views/_helpers.py:147-160`），
  `MEDIA_ROOT` 跟着 slot `data_dir` 走 ⇒ 同名 `admin` 也写在各自目录树里。
- 改成 per-slot 用户要动 `seed_users`（用户名硬编码、无 `--owner`，`apps/accounts/management/commands/seed_users.py:14-33`）
  外加 e2e 里 28 行 / 9 文件的 `admin` 字面量 —— **付钱买一个已经存在的隔离**。
  保留同名用户只需要把 `batch-phase.spec.ts:27` 那类硬编码路径 `media/data/admin/batch` 改成从 slot 目录推导。

## 5. 隔离边界逐项

| 共享物 | 今天的形状 | slot 化后的机制 | 要动的代码 |
|---|---|---|---|
| SQLite 库 | 仓库根单库，globalSetup 跑 `migrate`+seed（`e2e/global-setup.ts:40-46`） | 每 slot 一份模板拷贝；slot 模式下 globalSetup **跳过** migrate/seed | `global-setup.ts` 加分支 |
| 账号持久态 | 全体用例共用一个 admin 行 | 每 slot 是自己的库副本，同名行的**副本**，写回互不可见 | 无 |
| 上传与删除 | `media/data/admin/…`，只清 `e2e_` 前缀；**删记录会 `os.remove` 盘文件并向上 rmdir 空目录到 MEDIA_ROOT**（`_helpers.py:191-207`，批次走 rmtree） | 硬链镜像 ⇒ 上传写新 inode、删除只摘本 slot 的链，模板与其它 slot 的输入不受影响 | slot 目录构造 |
| storageState / token | 一份 `admin.json` 开跑时铸（`playwright.config.ts:100,109,116,123`） | 每 slot 各自铸；**per-slot `SECRET_KEY` 是必需的**：每份副本里 user PK 都是 1，共用默认密钥时 slot A 的 token 能在 B 认证，端口搞错会从 401 变成**静默写别人的库** | config 4 处路径 + env |
| `temp_dir` | `apply_system_config` 把 `TMP/TEMP/TMPDIR` 与 `tempfile.tempdir` 统一指向 `%TEMP%\LQ-DataPrase-Temp`（`system_config.py:394-409`） | slot config 里显式给 `temp_dir` ⇒ 导出/合并的中间文件天然隔离 | 无（配置字段已有） |
| SFTP 会话缓存 | key `sftp:conn:<user_id>`（`apps/sftp/cache.py:43,116`），URL 解析 `SFTP_SESSION_REDIS_URL`→`REDIS_URL`→`CELERY_BROKER_URL`（`cache.py:64-67`、`base.py:271,277`） | **每 slot 一个 Redis db index**。今天 Redis 没起、降级进程内 LocMem（`cache.py:75`）所以还没炸；一旦 Redis 起来，4 份副本的 `user_id` 相同 ⇒ 直接串号 | env |
| `known_hosts.json` | `MEDIA_ROOT/sftp/known_hosts.json` 固定名 + 固定 `.tmp` 原子替换（`apps/sftp/host_keys.py:33,63,114-126`） | 落在 slot 的 media 镜像里，天然隔离 | 无 |
| SFTP 测试服务器 | 本地 paramiko，随机端口 + `mkdtemp` root（`e2e/helpers/sftpServer.ts:46,57-59,94-104`） | **已经并行安全** | 无 |
| Django / preview | 8000 / 3000 各一 | `810i` / `310i`；preview 不继承 server.proxy，两处代理目标都已跟随 `E2E_PORT`（`vite.config.ts:43-66`，2026-10-14 刚修过写死 8000 的坑） | 无 |
| 用例里的 URL | 22 处 `page.goto` **全部相对路径**，spec 内零硬编码端口（实测 grep） | 各进程自己的 baseURL | 无 |
| `.downloads` | 全局单目录（`e2e/fixtures/test-data.ts:31`） | slot 内目录 | 1 处常量 |

**分区器**：LPT（最长处理时间优先）—— 按最近夜跑的 per-file pass 时长降序，逐个投进当前最轻的桶。
用实测时长而非文件数，因为 top5 占 31%、median 只有 7.8s，等文件数切分会让一个桶拖尾。
无夜跑 JSON 时退化为按文件数均分，并在输出里标注「分区未加权」。
排序稳定（文件名 tie-break），使组合跨运行尽量不变。

**分区与 tag 项目的关系**（别混）：分区只按**文件**切，选择器一个都不传；`setup`/`Edge`/`P0`/`P1`/`P2`
五个 project 仍在每个 slot 进程内各自生效（`playwright.config.ts:89-127`），于是每个 slot 跑的是
「分给它那批文件 × 全部 project」的交集，覆盖集与今天一次全量完全相同。§8-3 的不变量检查就是验这条。

## 6. 失败与错误处理

- **端口块不足即 fail fast**：分配前探测 `8101..810N` / `3101..310N`；被占（本机常有其它会话在服务，
  夜跑历史上因此 SKIPPED 过）就换基址重试一次，仍不行就报错退出，**绝不静默复用别人在跑的服务**
  （`reuseExistingServer` 复用旧包导致假绿是记过账的）。
- **单 slot 进程非零退出**：其余继续跑完，汇总标 `slot<i> EXIT=<code>` 与其文件清单，支持原地复跑
  `node scripts/e2e_pool.mjs --only-slot=<i>`。
- **webServer readiness 超时**（`GET /api/schema/`，`playwright.config.ts:135-140`）：该 slot 记 INFRA 失败，
  不进「产品红」计数 —— 沿用 `LATEST.md` 对 2026-10-14 VOID 轮的处理姿势（指标不可信就不进时间序列）。
- **合并报告缺一份 blob**：直接判本轮 INFRA 并保留各 slot 原始 JSON，不产出半份结论。
- **资源预算**：32GB RAM / 28 逻辑核。每 slot ≈ Chromium 0.5GB + Django 0.3GB + preview 0.15GB ≈ 1GB
  ⇒ N 默认 **4**，`E2E_SLOTS` 可调到 6（≈6GB，给同机其它会话留余量）。

## 7. 门禁与阈值重定义（`scripts/e2e_nightly.mjs:28-37`）

并行后「单价」的含义变了：争用会抬高每例 wall 时间、同时压低墙钟 —— 串行时代拿 3.5s/例当退化信号的做法
在 slot 模型下会**误报退化**。改成：

- `wallMs`：30min → **12min**（既是挂死探测也是目标闸门；10min 级目标 + 2min 余量）。
- 新增 `efficiencyFloor`：`Σ(通过用例时长) / 墙钟` ≥ **0.7 × N**。这是「并行有没有在空转」的唯一硬信号，
  比单价有判别力：低于它说明争用或分区拖尾。
- `perSpecMs`：保留但按 N 标定，先放 **6000ms@N=4**（串行实测 2.89s，翻倍余量），两轮后收紧。
- `specs` 450 / `flakes` 5 不变（flake 跨 slot 求和）。
- 目标数字不靠估：P2 用 N=2 与 N=4 各跑一轮真全量，按实测把三个阈值钉死。
  上一轮的教训就是从「未实测估计」推阈值，比实测慢近 2 倍，形同不存在。

## 8. 这个改造自身怎么验

1. **加速比探针**：N=1 / 2 / 4 各一轮全量，报墙钟、单价、效率。N=4 若效率 <1.5×N=1，停下重议
   （说明瓶颈不是串行本身）。
2. **隔离性正证**（不靠改坏源码反证）：拿两个已知互踩的真实文件对 —— `settings/settings.spec.ts`
   （「恢复默认」洗全部 `UserSetting`）与 `settings/fonts.spec`（历史实测从 0 红变 5 红），
   强制分到**不同 slot** 与**同一 slot** 各跑一次。不同 slot 必绿 = 隔离成立；同 slot 也绿 = 快照-还原本身已够。
   两种结论都是有效信息，且不碰产品代码。
3. **不变量**：改造前后各一轮全量，`--list` 用例数一致（386）、JSON 里 per-file 断言集合 diff 为空
   —— 证明只动编排，没动判据。
4. **回归面**：`npm run lint:e2e`（e2e 不在 `npm run build` 的 include 覆盖内，只有这条通路能查失效 import）
   + `test:e2e:affected` 走一遍新池。

## 9. 分阶段

- **P0 前置实测**（半天，不改代码）：`seed_test_data --refresh` 在 TEMP 目标下的耗时与幂等、
  154 文件硬链镜像的建链耗时、以及删除/覆盖时链的行为实测（在临时目录里，不碰仓库 media）。
- **P1 池骨架**：`scripts/e2e_pool.mjs` + 模板构建 + slot 目录（含硬链镜像与两个 config 字段）
  + `global-setup.ts` slot 分支 + `.auth`/`.downloads` 路径参数化 + N=1 跑通。
  验收：N=1 结果与今天串行**等价**（红数、文件集一致）—— 先证明没改坏，再谈提速。
- **P2 并行**：N=2 → N=4，逐轮按 §8-2 归因新出现的红；把 `batch-phase.spec.ts:27`、`repair-center.spec.ts:71,161,231`、
  `cleanup.ts:65`、`system-paths.spec.ts` 这几处按 slot 目录校正。
- **P3 门禁收口**：`e2e_nightly.mjs` 阈值重标定 + `merge-reports` 接进时间序列 + `e2e_affected.mjs` 走同一个池。
  此后 `E2E_SLOTS` 是唯一并行度旋钮（符合「开关要收敛」）。
- **回滚**：`E2E_SLOTS=1` 即回到今天形态（同一份 globalSetup 分支，只是数据落在 TEMP）。
  仓库根 `db.sqlite3`/`media/` 在 slot 模型下不再被 e2e 写，回滚不需要清场。

## 10. 已实测确认的隔离事实（探针 + 逐条回读源码）

1. 列表 owner-scoped：`apps/datafiles/views/file_views.py:99`，跨 app 查询亦如此
   （`apps/dashboard/views.py:34-42`、`apps/batch_report/services.py:63-65`、`browse_views.py:355,459`）。
2. 上传路径含用户名、DB 存 **MEDIA_ROOT 下的相对路径**（`_helpers.py:147-160`、`apps/datafiles/utils.py:80-116`）
   ⇒ 硬链镜像对「读」是充分的。
3. 删除**会删盘文件**并向上 rmdir 到 MEDIA_ROOT，批次走 rmtree，无「这是共享种子」的守卫（`_helpers.py:180-211`）
   ⇒ 镜像不是可选优化，是**必需**。（本文初稿写的「种子 media 保持共享只读」由此作废。）
4. `seed_test_data` 有 `--owner/--clear/--refresh`，`--refresh` 只清 `e2e_` 前缀，幂等靠
   (owner,filename,file_path)+size/mtime；源目录锚在仓库（`parents[4]`），写侧走 MEDIA_ROOT
   （`apps/accounts/management/commands/seed_test_data.py:21,36-55,104-157`）⇒ 模板建在 TEMP 可行。
5. `LQDP_SKIP_STORAGE_MIGRATION` 已存在（`system_config.py:71-83`）；不设它而改 `data_dir` 会触发搬走并删源的
   `_migrate`（`:389-391`）⇒ §4.1 的硬前提。
6. `SECRET_KEY` 读 env（`base.py:17`）、`SFTP_SESSION_REDIS_URL` 读 env（`base.py:271`）
   ⇒ 两项隔离纯靠注入，不需要新增 settings 档。
7. e2e 侧 `admin` 字面量 28 行 / 9 文件，统一入口已存在（`ACCOUNTS` + `ADMIN_STATE`）；
   真正要改的只有硬编码 media 路径那几处（§9-P2）。

## 11. 明确不做

- 不删/不降级任何 T3 判据；不为了让并行好看而加大超时。
- 不引入跨用例共享 context（省冷启的另一条路，会把刚消掉的账号态重新请回来）。
- 不动 T1/T2/T3 三层判据与 `test:e2e:affected` 的选例逻辑。
- 不做 per-slot 用户名（理由见 §4.2）。
- 不用「故意不带 `LQDP_SKIP_STORAGE_MIGRATION` 跑一次」来证明该开关承重（§4.1 明确只走代码读）。
- 不做 CI/多机；不把后端 888 例并入这 10min。
