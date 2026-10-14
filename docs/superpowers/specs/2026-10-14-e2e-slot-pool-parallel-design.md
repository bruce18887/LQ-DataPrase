# e2e slot 池并行化设计（全量轮压到 10 分钟级）

日期：2026-10-14 · 状态：待评审
前置阅读：`docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md`（三层判据 T1/T2/T3，本设计不动它）
清理台账：`docs/reference/e2e-tier-triage.md`

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

最贵的 12 个文件（pass 时长）：`serial-overlap` 85.0 · `outlier-handling` 76.1 · `view-data` 55.2 ·
`sftp/search` 54.3 · `analysis.spec` 53.5 · `multi-file` 43.8 · `axis-label-precision` 42.6 ·
`data.spec` 41.5 · `file-correlation` 32.6 · `exports` 29.4 · `gage-qqbox-repro` 28.7 · `legend-color` 26.9。

**推演**：1056s / 4 slot = 264s 理想下限；按并发争用 ×1.3 → **~5.7min**，加 slot 池启动（预算 20–40s）→ **~6.3min**。
`specs=450` 天花板：450×2.89×1.3/4 ≈ 424s + 启动 ≈ **7.6min**，仍在 10min 级。
串行化的最大单文件 85s 远小于 makespan，不构成并行瓶颈。

## 3. 为什么必须动隔离模型，以及为什么不是「worker 绑 slot」

串行的三个理由（都不是产品问题，是 harness 问题）：

1. **共享 admin 单账号 + 账号级持久态**：`UserSetting` / `analysis_chart_state`（`analysis_chart_memory` 默认 true，
   翻动即写回）/ `page_size` / 主题。`e2e/fixtures/auth.setup.ts:58-82` 只能在**开跑前**钉一次默认值，
   治跨轮不治跨用例（`docs/tasks/lessons.md:385`、`docs/reference/e2e-tier-triage.md:396` 都把这条判为
   「组合范围验证必须 workers=1」的根因）。
2. **单库单进程**：一个 `db.sqlite3`（`config/settings/development.py:27-31`）+ 一个 `runserver 8000 --noreload`
   + 一个 preview 3000（`frontend/playwright.config.ts:130-170`）。
3. **快照-还原助手天然要求串行**：`settings.spec.ts:68-78` 这类「读原值→改→finally 还原」在并发下会读到别人的中间态
   （`lessons.md:1612`）。

上一轮我推荐「每个 Playwright worker 绑一个 slot」，**现改为「1 进程 = 1 worker = 1 slot」**，理由是要保住两件事：

- **文件不跨 slot 拆**。`fullyParallel: true` 下同文件的用例会散到不同 worker；即便每 worker 一套独立库，
  也会让「同文件的第 3 条在第 3 个 slot 看到与第 1 条不同的起始账号态」，这是新的、无法复现的故障面。
- **文件→slot 的组合要可复现**。由 Playwright 决定谁和谁同 slot，则每次运行组合都在变，污染只能反复重发现。
  自己按文件分区后，同一份分区表决定组合，红了能原地复跑。

代价是报告要合并（用官方 `npx playwright merge-reports` + blob reporter），换来的是分区可控、
崩池隔离（一个 slot 挂其余继续，这是 `lessons.md:640` 那类 dev server 死亡事故的正确形状），
以及每个 slot 进程仍跑 `workers=1` —— **现在这套按串行调好的 helper 一行都不用改**。

## 4. 架构

```
scripts/e2e_pool.mjs                     ← 新增：池编排器（唯一入口）
  ├─ ① 构建模板  migrate + seed_users + seed_test_data → tasks/e2e-slots/template/db.sqlite3
  ├─ ② 前端构建  npm run build 一次（实测 6.6s）
  ├─ ③ 分区      LPT(files, durations from 最近夜跑 JSON) → N 桶
  ├─ ④ 起 slot   N 个 `npx playwright test <该桶文件> --workers=1` 子进程
  │              每进程 env: E2E_PORT=810i / E2E_FRONTEND_PORT=310i /
  │                          LQDP_E2E_SLOT_DIR=<%TEMP%>\lqdp-e2e-slot-i / LQDP_E2E_TEMPLATE_DB
  │              每进程自带 webServer 对（Playwright 自己起、自己收），各自写 slot<i>/run.log
  └─ ⑤ 合并      blob → merge-reports → 单一 results.json + playwright-report
```

**slot 目录内容**（每 slot 独占，`%TEMP%\lqdp-e2e-slot-<i>\`）

- `db.sqlite3` ← 模板库**整文件拷贝**（4MB，实测）
- `system-config.json` ← 只含 `data_dir` 指向本 slot 目录（沿用 `playwright.config.ts:17-22` 的写法，改为 per-slot 路径）
- `media/` ← 对仓库 `media/` 做**硬链镜像**：实测只有 **154 个文件 / 12 个目录 / 1.1GB**，
  建链是元数据操作、不占磁盘、不搬数据（同盘 C:，TEMP 也在 C:）。
  ```
  这样 slot 的上传写新 inode、删除只摘自己这份链，**既不会互相覆盖，也不会毁掉别的 slot 与模板的种子输入**。

**模板建在哪（决定「e2e 不再写仓库」这句成不成立）**：今天 e2e 的 `data_dir = 项目根`，seed 直接落仓库
`media/`（`apps/common/system_config.py:387-390` 的 `data_target==orig` 会跳过迁移，正是因为目标就是原地）。
本设计要求**模板构建到 TEMP**（`tasks/e2e-slots/template/` 或 `%TEMP%\lqdp-e2e-template\`），slot 从模板树镜像，
仓库 `media/` 全程只读 —— 否则「收口门禁与后端套件并跑」这类顺带收益是假的，且每次夜跑都在写 1.1GB 进工作区。
前提是 `seed_test_data` 的数据来源能从仓库外取得（它生成/拷贝什么、从哪取，见 §10-4）；**取不到就退一步**：
模板仍建在仓库 `media/`，但 slot 镜像照旧，代价是「e2e 写仓库 media」这条现状不变，§9 的回滚说明相应减弱。
- `.downloads/` ← 从全局单目录（现 `e2e/fixtures/test-data.ts:31`）改为 slot 内目录

**为什么不拷 1.1GB × N**：4 slot 就是 4.4GB 与几十秒纯 IO，且把「删盘文件」变成跨 slot 破坏风险；硬链一次解决两条。

## 5. 隔离边界逐项

| 共享物 | 现在的形状 | slot 化后的机制 | 需要动的代码 |
|---|---|---|---|
| SQLite 库 | 仓库根单库，globalSetup `migrate`+seed（`e2e/global-setup.ts:40-46`） | 每 slot 一份模板拷贝；slot 模式下 globalSetup **跳过** migrate/seed | `global-setup.ts` 加 slot 分支 |
| 账号持久态 | 全体用例共用一个 admin 行 | 每 slot 是自己的库副本 ⇒ 同名 admin 行的**副本**，写回互不可见 | 无（副本天然隔离） |
| storageState/token | 一份 `admin.json`，开跑时铸 | 每 slot 进程各自跑 setup 铸一份；同 SECRET_KEY + 同 user id ⇒ 逻辑一致但落在各自库 | 无 |
| 上传落盘 | `media/data/admin/{single,batch}/`，只清 `e2e_` 前缀（`seed_test_data.py:137,148-153`） | slot 的 `data_dir` → `media/` 硬链镜像，上传写进自己目录 | slot 目录构造 |
| 删除语义 | 删记录可能连带删盘文件（待探针证实，见 §10） | 摘硬链，不动仓库与其它 slot | 无 |
| `media/sftp/known_hosts.json` | 全局单文件 | slot 内副本 | 无 |
| SFTP 测试服务器 | 本地 paramiko，随机端口 + `mkdtemp` root（`e2e/helpers/sftpServer.ts:46,57-59,94-104`） | **已经并行安全** | 无 |
| Django / preview | 8000 / 3000 各一 | `810i` / `310i`，`E2E_PORT`·`E2E_FRONTEND_PORT` 已参数化，preview 代理目标跟随（`vite.config.ts:43-66`，2026-10-14 刚修过写死 8000 的坑） | 无 |
| 用例里的 URL | 22 处 `page.goto` **全部相对路径**，spec 内零硬编码端口（实测 grep） | 各自 project 的 baseURL | 无 |
| 后端进程级单例 | Redis 不可达即降级 None（`apps/sftp/cache.py:75`）；Celery `config/settings/base.py:202-203` | 每 slot 独立进程 + 独立降级，无共享 | 待 §10 探针复核 |

**分区器**：LPT（最长处理时间优先）—— 按最近夜跑的 per-file pass 时长降序逐个投进当前最轻的桶。
用实测时长而非文件数，因为 top5 占 31%、median 只有 7.8s，等文件数切分会让一个桶拖尾。
无夜跑 JSON 时退化为按文件数均分，并在输出里标注「分区未加权」。
排序稳定（文件名字母序 tie-break），使组合跨运行尽量不变。

**分区与 tag 项目的关系**（别混）：分区只按**文件**切，选择器一个都不传；`setup` / `Edge` / `P0` / `P1` / `P2`
五个 project 仍在每个 slot 进程内各自生效（`playwright.config.ts:89-127`），于是每个 slot 跑的是
「分给它那批文件 × 全部 project」的交集，覆盖集与今天一次全量完全相同。§8-3 的不变量检查就是在验这条。

## 6. 失败与错误处理

- **端口块不足即 fail fast**：分配前探测 8101..810N / 3101..310N 是否空闲；被占（本机已有其它会话在服务，
  历史上夜跑因此 SKIPPED 过）就换基址重试一次，仍不行就报错退出，**绝不静默复用别人在跑的服务**
  （`lessons.md` 记过复用旧包/旧代码导致的假绿）。
- **单 slot 进程非零退出**：其余 slot 继续跑完，合并阶段照收，汇总里标 `slot<i> EXIT=<code>` 与其文件清单，
  便于原地复跑：`node scripts/e2e_pool.mjs --only-slot=<i>`。
- **webServer readiness 超时**（`GET /api/schema/`，`playwright.config.ts:135-140`）：该 slot 记为 INFRA 失败，
  不参与「产品红」计数——沿用 `LATEST.md` 里 2026-10-14 VOID 轮的处理姿势（指标不可信就不进时间序列）。
- **合并报告缺一份 blob**：直接判本轮 INFRA 并保留各 slot 原始 JSON，不产出半份结论。
- **资源上限**：32GB RAM / 28 逻辑核。预算每 slot ≈ Chromium 0.5GB + Django 0.3GB + preview 0.15GB ≈ 1GB ⇒
  N 默认 **4**，可用 `E2E_SLOTS` 调到 6（≈6GB，留够余量给同机的其它会话）。

## 7. 门禁与阈值重定义（`scripts/e2e_nightly.mjs:28-37`）

并行后「单价」的含义变了：争用会让每例 wall 时间上升，而墙钟同时下降——串行时代拿 3.5s/例当退化信号的做法
在 slot 模型下会**误报退化**。改成：

- `wallMs`：30min → **12min**（既是挂死探测也是目标闸门；10min 级目标 + 2min 余量）。
- 新增 `efficiencyFloor`：`Σ(通过用例时长) / 墙钟` 应 ≥ **0.7 × N**。这是「并行是否在空转」的唯一硬信号，
  低于它说明要么争用要么分区拖尾，比看单价有判别力。
- `perSpecMs`：保留但按 N 标定，先放 **6000ms@N=4**（串行实测 2.89s，翻倍余量），跑两轮后收紧。
- `specs` 450 / `flakes` 5 不变（flake 跨 slot 求和）。
- 目标数字不靠估：Phase 1 用 N=2 与 N=4 各跑一轮真全量，按实测把 `wallMs`/`perSpecMs`/`efficiencyFloor` 钉死
  （上一轮教训：旧阈值从「未实测估计」推出来，比实测慢近 2 倍，形同不存在）。

## 8. 这个改造自身怎么验

1. **加速比探针**：N=1 / 2 / 4 各一轮全量，报墙钟、单价、效率。若 N=4 效率 <1.5×N=1 的收益，停下重议（说明瓶颈不是串行本身）。
2. **隔离性正证**（不靠改坏源码反证）：拿两个已知互踩的真实文件对 ——
   `settings/settings.spec.ts`（「恢复默认」会洗全部 `UserSetting`）与 `settings/fonts.spec`（历史实测从 0 红变 5 红，
   `lessons.md` 10-13 条目），强制把它们分到**不同** slot 与**同一** slot 各跑一次。
   不同 slot 必绿 = 隔离成立；同 slot 绿 = 快照-还原已够。两种结论都是有效信息，且不碰产品代码。
3. **不变量**：改造前后各跑一轮全量，`--list` 用例数一致（386）、JSON 里 per-file 断言集合 diff 为空 ——
   证明只动了编排，没动判据。
4. **回归面**：`npm run lint:e2e`（e2e 不在 `npm run build` 的 include 里，只有这条通路能查失效 import）
   + `test:e2e:affected` 走一遍新池。

## 9. 分阶段

- **P0 前置事实**（半天，只查不改）：§10 四个未决点 + 硬链镜像可行性实测（154 文件建链耗时、删除语义）。
- **P1 池骨架**：`scripts/e2e_pool.mjs` + 模板库构建 + slot 目录（含硬链镜像）+ globalSetup slot 分支 + N=1 跑通。
  验收：N=1 结果与今天串行**等价**（红数、文件集一致），先证明「没改坏」再谈提速。
- **P2 并行**：N=2 → N=4，逐轮按 §8-2 归因新出现的红；把 §10 探针结论落到分区表。
- **P3 门禁收口**：`e2e_nightly.mjs` 阈值重标定 + `merge-reports` 接进时间序列 + `e2e_affected.mjs` 走同一个池。
  这一步之后 `E2E_SLOTS` 是唯一并行度旋钮（符合「开关要收敛」）。
- **回滚**：`E2E_SLOTS=1` 即回到今天形态（同一模板库、同一份 globalSetup 分支，只是路径挪到 TEMP）。
  仓库根 `db.sqlite3`/`media/` 在 slot 模型下不再被 e2e 写，回滚不需要清场。

## 10. 未决事实（探针在跑，落笔前必须换成实测结论）

1. `/api/v1/files/` 列表是否按 `request.user` 过滤；`FileRecord` 有无 owner 外键 —— 决定「同名 admin + 各自库」是否真的隔离了列表残留。
2. 上传路径怎么拼（是否含用户名）、DB 存**绝对还是相对**路径 —— 若存绝对路径，硬链镜像对读是冗余的（仍保留，因为删除语义需要它）。
3. 删 `FileRecord` 是否连带删盘文件（决定镜像是不是**必需**而非可选）。
4. `seed_test_data --refresh` 的耗时、幂等性与**数据来源**（是合成生成，还是从某个既有库/目录拷贝 —— 决定 §5「模板建在 TEMP」能不能成立）；
   以及 `data_target==orig` 的跳过逻辑在 TEMP 目标下会走哪条分支。
5. 跨目录硬链可行性实测：`%TEMP%`（C:）↔ 仓库（C:）同卷 ⇒ 理论上可建，但要实测 154 文件耗时、以及
   删除/覆盖（写同名新文件）时链的行为是否符合「只摘自己这份」的预期。

这四点任一推翻上面的机制，就回到本节改设计，不硬推。

## 11. 明确不做

- 不删/不降级任何 T3 判据；不为了让并行好看而加大超时。
- 不引入跨用例共享 context（省冷启的另一条路，会把刚消掉的账号态重新请回来）。
- 不动 T1/T2/T3 三层判据与 `test:e2e:affected` 的选例逻辑。
- 不做 CI/多机；不把后端 888 例并入这 10min。
