# 渲染进程内存基线（2026-10-22 实测，Task 2 交付常数）

> 本文只写**有命令产出过的数字**。判据问题（Q1–Q4）与验收线在
> `docs/superpowers/specs/2026-10-22-desktop-lag-renderer-memory-design.md:122-137`；
> 探针是 Task 1 的 `frontend/e2e/data/renderer-memory.spec.ts` + `frontend/e2e/helpers/rendererMetrics.ts`。
> 原始产物 `tasks/renderer-probe-<键>.json` 在被 gitignore 的 `tasks/` 下，所以 §3.1 把关键摘录**内联**进本文。
> **本文交付数值，不创建 `blockCap.ts`** —— 那个文件由 Task 3 建（裁定 R8：原计划 Step 5 把顺序写反了）。

**证据文件对照**（本文引用的现场，全部只在本机、不入库）：
产物 `tasks/renderer-probe-{ETS88_FT,STS8200_CP}.json` 与逐轮留底
`tasks/t2-{wide-ets88-task1copy,wide-ets88-r4,narrow-ps50-r1,narrow-ps50-r2,narrow-ps500-r1,narrow-ps500-r2}.json`
（`.gitignore:148 /tasks/`）；池日志 `tasks/t2-*.log`；slot 现场 `C:\lqdp-e2e\slots\<RUN_ID>\slot0.run.log`；
推导脚本 `tasks/t2-derive.py`（§4/§6/§7/§9.3 的每个商都是它的输出；输出留底 `tasks/t2-derive.out`，
本机控制台默认 GBK，复跑要 `PYTHONIOENCODING=utf-8` 前缀才不落乱码）。
「Task 1 报告」= `.superpowers/sdd/2026-10-22-renderer-memory-and-request-dedupe/task-1-report.md`
（`.gitignore:206 /.superpowers/`）。
⚠ 本文还引 `docs/superpowers/specs/2026-10-22-desktop-lag-renderer-memory-design.md` 与
`docs/superpowers/plans/2026-10-22-…-dedupe.md`，**这两份截至本任务提交时是未跟踪文件**（`git status` 里是 `??`）
⇒ 单独 checkout 本文的机器按行号取不到它们，要么收口时把那两份一起入库，要么把 §4/§5/§7 的引用改成落地路径。

## 1. 复跑方式

```bash
# 全部从 worktree 根跑。本树没有 .venv ⇒ PYTHON_BIN 必填，否则起不了后端
# 宽形状（ETS88，1,728 列 × 每块 50 行 × 20 块 × 4 标签）
LQDP_PERF_PROBE=1 PYTHON_BIN='C:\Users\Administrator\Desktop\DataPrase\LQ-DataPrase\.venv\Scripts\python.exe' \
  node scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts

# 窄形状对照（本任务选的键，见 §2）
LQDP_PERF_PROBE=1 LQDP_PROBE_FILE=STS8200_CP PYTHON_BIN='…' node scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts
# 窄形状 + 深块（把「窄但每页 500 行」这一档压出来，行数字节都×10，信号才可分辨）
LQDP_PERF_PROBE=1 LQDP_PROBE_FILE=STS8200_CP LQDP_PROBE_PAGE_SIZE=500 PYTHON_BIN='…' \
  node scripts/e2e_pool.mjs --slots=1 -- data/renderer-memory.spec.ts
```

**判绿取日志末尾 `[pool] 结论` / `RESULT:` 行，不取 `$?`**（`docs/reference/testing-gates.md:24-27`）。
本任务 5 轮全部 `[pool] 结论 MEASURED`。形状只换 env，不改代码（裁定 R3）：

| env | 默认 | 作用 / 为什么本任务要动它 |
|---|---|---|
| `LQDP_PROBE_FILE` | `ETS88_FT` | 被测文件键（`frontend/e2e/fixtures/test-data.ts:50-68`） |
| `LQDP_PROBE_PAGE_SIZE` | `50` | 每块行数 = 探针自己钉的账号设置（50..500）。**分母就是它 × 列数** |
| `LQDP_PROBE_BLOCKS` | `20` | 翻满的块数 = 今天 `DataBrowserAgGrid.vue:69` 写死的 `maxBlocksInCache` |
| `LQDP_PROBE_TABS` | `CTA8290D_FT,BUYOFF_FT,CTA8280F_FT` | 标签 2..4 的文件（同一 fileId 开不出两个标签，Task 1 报告 §4.4） |

产物里的 `shape` 段自带分母（`probeKey/rowsPerBlock/blocks/colCount/totalRows/cellsPerBlock/tabs`），
读数和复算都以它为准，不需要猜分母 —— 这是 Task 1 复审 Important 2 的产物形状。

## 2. 采了哪两组形状，窄文件为什么选 `STS8200_CP`

brief Step 1 要求「列数最少（≤200 列）的种子文件」。种子清单 11 个键按列数排序（源：
`frontend/e2e/fixtures/test-data.ts:50-68` 的键值 = 文件名，联 `C:\lqdp-e2e\template\db.sqlite3`
的 `datafiles_datafile.col_count/row_count`）：

| 键 | 列数 | 行数 | 键 | 列数 | 行数 |
|---|---|---|---|---|---|
| **`STS8200_CP`** | **45** | **14,174** | `GAGE_S1..S4` | 346 | 100 |
| `CTA8280F_FT` | 188 | 10,000 | `BUYOFF_FT` | 556 | 2,301 |
| `BUYOFF_QA1/QA2` | 297 | 1,908 / 1,992 | `CTA8290D_FT` | 557 | 2,525 |
| | | | `ETS88_FT` | 1,728 | 1,436 |

选 `STS8200_CP`（最窄 45 列），且它 14,174 行 ⇒ **`BLOCKS` 不用降**：形状可行性判据是探针自己的
承重前置③ `totalRows ≥ BLOCKS × rowsPerBlock`（`renderer-memory.spec.ts:373-376`），
20×50=1,000 与 20×500=10,000 都装得下，所以既没改 spec 也没放宽任何东西。
对照：宽形状那只 `ETS88_FT` 只有 1,436 行 ⇒ 生产 `page_size=100` 时整表只有 15 页（末页 36 行），
「20 块满缓存」这个形状在生产设置下**不存在**，所以探针把块大小钉在 50（Task 1 报告 §4.5，收尾写回原值）。

DB 的 `col_count` 与探针从 `/browse/` 的 `headers` 取到的 `colCount` 两边核对一致：
ETS88 1,728 = 1,728、STS8200_CP 45 = 45 ⇒ 分母口径同一个数。

## 3. 实测原始数字（6 轮，全部 MEASURED）

`d(19块)` = `heap(20 块) − heap(1 块)`；`B/格` = `mib_per_cell × 1024 × 1024`。
heap 由 CDP `Runtime.getHeapUsage` 取，**取样前先 `HeapProfiler.collectGarbage`**（不 GC 时同一形状
两轮 Δ 差 53%，Task 1 报告 §4.7）。

| # | 形状 | 键 / 每块行×列 | cellsPerBlock | heap 1 块 | heap 20 块 | Δ(19 块) | 每块 | mib_per_cell | B/格 | 证据 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 宽（Task 1 末轮 17:45） | 50×1,728 | 86,400 | 94.4 | 149.8 | **55.4** | 2.916 | 3.3748e-5 | 35.4 | slot `094526-39212` |
| 2 | 宽（本任务 18:07 复跑） | 50×1,728 | 86,400 | 94.1 | 149.6 | **55.5** | 2.921 | 3.3808e-5 | 35.5 | slot `100759-37676` |
| 3 | 窄（18:05） | 50×45 | 2,250 | 43.3 | 43.5 | 0.2 | 0.011 | 4.68e-6 | 4.9 | slot `100518-34704` |
| 4 | 窄（18:10 复跑） | 50×45 | 2,250 | 43.2 | 43.5 | 0.3 | 0.016 | 7.02e-6 | 7.4 | slot `101057-14240` |
| 5 | 窄·深块（18:06） | 500×45 | 22,500 | 40.8 | 62.6 | **21.8** | 1.147 | 5.0994e-5 | 53.5 | slot `100625-35504` |
| 6 | 窄·深块（18:07 复跑） | 500×45 | 22,500 | 40.8 | 62.6 | **21.8** | 1.147 | 5.0994e-5 | 53.5 | slot `100725-43296` |

两轮一致性（spec §5 Q1 要求 <20%）：宽 **0.2%**（55.4 vs 55.5，且第 1 轮是 Task 1 的树）、
窄·深 **0.0%**（21.8 vs 21.8，逐字相同）、窄·浅 33% —— 后者的绝对值是 **0.2–0.3 MiB**，
已经在 0.1 MiB 的采样量化噪声里，见 §9 第 4 条。

每个形状的第 3 行（4 个标签那一档）：宽 176.6 / 176.7，窄·浅 86.9 / 87.0，窄·深 123.3 / 123.3。

### 3.1 产物摘录（本轮宽形状第 2 轮 `tasks/t2-wide-ets88-r4.json`，逐字）

```json
{"shape": {"probeKey":"ETS88_FT","rowsPerBlock":50,"blocks":20,"colCount":1728,
           "totalRows":1436,"cellsPerBlock":86400,
           "tabs":["ETS88_FT","CTA8290D_FT","BUYOFF_FT","CTA8280F_FT"]}}
rows[0] 1 块（首屏）          heap=94.1MiB longTask=1045ms max=475ms tasks=5 reqs=2
rows[1] 20 块满缓存（1 个标签） heap=149.6MiB longTask=1123ms max=475ms tasks=6 reqs=21
rows[2] 4 个标签（各 1 块）     heap=176.7MiB longTask=1322ms max=475ms tasks=9 reqs=27
requests: page=1 durationMs=1216 responseEndMs=2122 transferMiB=0.67
          page=2..20 durationMs=19..60 每条 transferMiB=0.63
longTasks: [176,127] [384,176] [566,67] [2122,475] [2602,200] | 形状2 多一条 [2959,78]
```

窄形状（`tasks/t2-narrow-ps500-r1.json`）同格式：`colCount=45, cellsPerBlock=22500, totalRows=14174`，
首块 `durationMs=24 responseEndMs=827 transferMiB=0.15`，续块 7–9 ms。

### 3.2 卫生核对（探针会写用户级设置，必须写回）

5 轮的 slot 日志都打了同一行，且模板库读回没有残留 50/500：

```
[probe] page_size 写回：目标 100（读到的原值 100） PUT=200 写回后读回 100
accounts_user_setting.page_size = [100, 100, 100]   # admin/user/viewer，模板库直读
```

## 4. Q1：单块堆成本，以及与生产传输字节的数量级校验

```
mib_per_cell = Δheap / ((BLOCKS−1) × cellsPerBlock) = 55.5 / (19 × 86,400) = 3.381e-5  → 交付 3.38e-5
```

| 问的东西 | 算法 | 值 |
|---|---|---|
| Q1 的字面问题：单块 **100 行 × 1,728 列** | `172,800 × 3.38e-5` | **5.84 MiB** |
| 实测量到的那一级（50 行 × 1,728 列） | `86,400 × 3.38e-5` | 2.92 MiB |
| 窄·深块那一格（500 行 × 45 列） | `22,500 × 3.38e-5` | 0.76 MiB（**实测** 1.147，即窄曲线单价 5.10e-5，见 §7 敏感性那条） |

**数量级校验**（spec §5 Q2 的判据「与生产 file 178 传输字节同数量级」）：
生产一次 `/browse/` 单次最大 **2,968 KB / 100 行**（spec:47）= 2.90 MiB；本文的 5.84 MiB/块
= 传输字节的 **2.0 倍**，同量级 ✅。本地 ETS88 一块传输 0.63 MiB / 50 行 = 1.26 MiB / 100 行，
与生产的 2.90 MiB / 100 行同量级（差 2.3 倍，数据密度不同）。
**与初稿估算的对照**：SDD 台账 `.superpowers/sdd/2026-10-22-…/progress.md:26`（不入库）用占位
`CELL_PER_BLOCK_MAX / CELL_RETAIN_BUDGET = 200k / 400k` 验算过 Task 3，那档隐含单价
`48 / 400,000 = 1.2e-4`（≈126 B/格）= 实测的 **3.6 倍**；若把 200k 那一档当驻留预算则是
`2.4e-4`（≈250 B/格）= 实测的 **7.1 倍** —— Task 1 报告 §5.1（第 183 行）写的是后者并把它归给 plan，
而 `grep -n '2\.4e-4\|250 B' docs/superpowers/{plans,specs}/2026-10-22-*` **无命中**（`传输字节` 只出现在
spec:127 那条 Q2 判据里，本文上面正是在满足它）⇒ 这处引用口径分叉记进 §9 第 2 条，本文只用自己算得出的数。
按 `2.4e-4` 算的单块（172,800 格）= 41.5 MiB = 生产那一块传输字节 2.90 MiB 的 **14 倍** ——
方向上确实是高估（那个量级一张表就吃穿 7.4 GB 的可用提交内存，与生产 oom 的形态并不吻合）。

## 5. Q2：满缓存与 4 标签峰值 ⇒ `RETAIN_MIB_TARGET` 维持 48 MiB

判据（brief Step 2）：**4 个标签同时驻留**的堆峰值必须低于生产机可用提交内存的十分之一。

| 量 | 值 | 源 |
|---|---|---|
| 生产机可用提交内存 | 7.4 GB（⇒ 阈值 **740 MiB**） | spec §1.4 那条 `WARN apps.common.memory: 系统可用提交内存 7.4GB 低于预算 8.0GB` |
| 实测 4 标签堆峰值（宽，两轮） | **176.6 / 176.7 MiB** | §3 行 1、2 |
| 4 张表的悲观上界 | 4 × 48 = **192 MiB** | 与实测 176.7 同量级（差 8%）⇒ 目标不是拍脑袋的小数 |
| 本机今天的可用提交内存 | 16.8 GB（`commit=24.0GB/40.8GB`） | 本轮池日志 `tasks/t2-*.log` 里 `apps.common.memory` 那行 |

⇒ **判据过，余量 4 倍，`RETAIN_MIB_TARGET` 保持 48 MiB。** brief 给的下调条件是「实测**远超**预期」，
而实测方向相反（单价比台账占位那一档小 3.6 倍，§9 第 2 条），所以不动它。本机内存不是约束，生产机才是。

⚠ **但 4 标签的增量不受格数模型约束**，这条要带给 Task 4/7：3 个新标签各只 1 块
（`CTA8290D`+`BUYOFF_FT`+`CTA8280F` = 65,050 格 ⇒ 模型只算 2.2 MiB），实测增量是
宽形状 **+26.8/+27.1**、窄·浅 **+43.4/+43.5**、窄·深 **+60.7** MiB。
扣掉格数成本后每张网格的固定成本约 **8.3 / 13.8 / 12.9 MiB**
（宽 `(27.1−2.2)/3`、窄·浅 `(43.5−2.2)/3`、窄·深 `(60.7−22.0)/3`；65,050 格与 650,500 格的模型值由 §4 单价算出），
且同一形状跨轮就不等（26.8 vs 43.4 是同样的 3 只文件）。
这部分是 **D4（非激活标签 `purgeInfiniteCache`）** 要吃掉的东西，本文的预算模型不覆盖它 ——
**别用格数预算去预测 4 标签峰值**，只能用同环境整改前后的相对值（spec §6:137 就是这么写的）。

## 6. 常数反推与交付值（Task 3 照抄这一节）

`RETAIN_MIB_TARGET`（= 48 MiB）与 Q1 的 `mib_per_cell` 是两个输入；下表是交付值 ——
brief Interfaces 点名三个常数（`CELL_PER_BLOCK_MAX`、`CELL_RETAIN_BUDGET`、`RETAIN_MIB_TARGET`），
连单价一起四个数，Task 3 只需前三个 + `mib_per_cell` 作为注释里的推导依据。
**`CELL_PER_BLOCK_MAX` 取预算的四分之一，不是等于预算**（裁定 R9）：

```bash
$ python -c "import math; b=math.floor(48/3.38e-5); print(b, b//4, b//(100*142), b//(100*1728))"
1420118 355029 100 8
```

四个数依次是 `CELL_RETAIN_BUDGET` / `CELL_PER_BLOCK_MAX` / 窄文件钳前商 / 宽文件 cap。
**第三个数是 100 不是 99**（`100 × 14,200 = 1,420,000 ≤ 1,420,118`），它被 `MAX_BLOCKS=20` 钳回 20
⇒ 窄文件行为不变。同一组商也是推导脚本的输出，`tasks/t2-derive.out` 第 17-19 行逐字：

```
== §6 一行式的展开（与文档引用的那条 `python -c` 同一组数）==
budget=1420118  budget//4=355029  budget//(100*142)=100  budget//(100*1728)=8
其中 budget//(100*142)=100 会被 MAX_BLOCKS=20 钳回 20 ⇒ 窄文件行为不变
```

> 本文初稿这行是**手写**的 `# → 1420118 355029 99 8`，那条命令产不出 99（复审 Important 1）⇒ 已换成实跑输出。
> 交付的两个常数与「窄文件仍 20」的结论都不受影响：99 与 100 都被 20 钳住。

| 常数 | 公式 | **交付值** | 含义 |
|---|---|---|---|
| `RETAIN_MIB_TARGET` | 初值，按 §5 校准 | **48**（MiB） | 单表驻留目标 |
| `mib_per_cell` | §4 | **3.38e-5** MiB/格（≈35 B/格） | 宽形状实测单价 |
| `CELL_RETAIN_BUDGET` | `floor(48 / 3.38e-5)` | **1,420,118** 格 | 驻留总格数上限 |
| `CELL_PER_BLOCK_MAX` | `floor(1,420,118 / 4)` | **355,029** 格（≈12.0 MiB） | 单块格数上限 |

**为什么除以 4**：若 `CELL_PER_BLOCK_MAX = CELL_RETAIN_BUDGET`，一块就吃满预算 ⇒ ETS88 在
`page_size=500` 时 `cap=1`，每翻一页都要发请求 —— 与 `apps/datafiles/views/browse_views.py:93`
「设置页的 50 下限是为『滚动别变成请求风暴』」、`apps/common/constants.py:13-14` 同一条理由。
除 4 之后最坏情况仍驻留 4 块（§7 表里 `ETS88@500 → cap=4` 就是这条的实测代入）。

**取整方向**：按两轮里较大的 Δ=55.5 不取整反推是 `budget=1,419,762 / perblock=354,940`，
与交付值差 **0.025%** ⇒ 无影响。交付值选 `3.38e-5`（两轮 3.3748e-5/3.3808e-5 都往它归）是为了让
Task 3 与本文能用一行算式复现，不引入「常数来自哪个私有中间量」的歧义。

**今天的写死值换算成同一口径**（单价 × 格数的**推导**，不是实测）：
`maxBlocksInCache=20` × 172,800 格 = 3.456e6 格 ≈ **116.8 MiB/表**（够多行的千列表满缓存那一档；
ETS88 因为只有 1,436 行，100 行/页时整表就 15 页 ⇒ 1,436 × 1,728 = 2.481e6 格 ≈ **83.9 MiB**）。
新 cap=8 后是 **46.7 MiB** ⇒ 宽文件驻留降一半以上，
窄文件一个字节都不变（§7）。

## 7. 代入验算（判据不许事后补）

把 §6 的常数代进 Task 3 的公式（`frontend/src/pages/data/components/browser/blockCap.ts` 的
`effectiveBlockSize` / `maxBlocksInCache`，plan Task 3 Step 3 那两份实现）：

| 文件 | 设置页大小 | 列数 | `effectiveBlockSize` | `maxBlocksInCache` | 驻留格数 → 堆（推导） |
|---|---|---|---|---|---|
| **窄（142 列）** | **100** | 142 | `min(100, floor(355029/142)=2500)` = **100** | `min(20, floor(1420118/14200)=100)` = **20** ✅ | 284,000 → 9.6 MiB |
| ETS88 | 100 | 1,728 | 100（`floor(355029/1728)=205` 不夹） | **8**（brief 期望 2–4 ⇒ §9 第 3 条） | 1,382,400 → 46.7 MiB |
| ETS88 | 500 | 1,728 | **205** = `floor(CELL_PER_BLOCK_MAX/1728)`，≥50 ✅ | **4** ≥1 ✅ | 1,416,960 → 47.9 MiB ≤ 48 |
| ETS88（探针形状） | 50 | 1,728 | 50 | 16 | 1,382,400 → 46.7 MiB |
| 窄 `STS8200_CP`（**实测量**） | 500 | 45 | 500（不夹） | 20 | 450,000 → 15.2 MiB（实测 Δ 21.8 + 首块） |
| 窄 `STS8200_CP`（**实测量**） | 50 | 45 | 50 | 20 | 45,000 → 1.5 MiB（实测 Δ 0.2–0.3） |
| 极宽 | 500 | 4,000 | 88 | 4 | 1,408,000 → 47.6 MiB |
| 列数未知 | 100 | null | 100（**不压**，压低会静默改分页语义） | 20 | — |

- **窄文件控制行：142 列 × 100 行 ⇒ cap 必须仍是 20 ⇒ 实测单价算出 20 ✅**（今天的行为不变）。
  这条**有判别力**：cap 保持 20 的条件是 `CELL_RETAIN_BUDGET ≥ 20 × 14,200 = 284,000 格`
  ⇔ `mib_per_cell ≤ 1.69e-4`（177 B/格）= 实测值的 **5.0 倍**。所以占位不能用：
  把台账那对 200k/400k 里的 200k 当驻留预算 ⇒ `cap = floor(200000/14200) = 14` ⇒
  **窄文件从 20 被砍到 14，验收行直接红**（brief 说的「阈值定错，窄文件也被砍」就是这个形状）；
  400k 那一档 ⇒ 20 ✓，边界正好在 284,000 格。
- Task 3 那 7 条单测断言（plan Task 3 Step 1）在交付常数下全可绿：
  `ebs(500,142)=500`、`ebs(100,60)=100`、`ebs(500,null)=500`、`ebs(500,0)=500`、
  `mbic(100,142)=20`、`mbic(100,null)=20`、`mbic(100,1728)=8`（`<20` 且 `≥1` ✅）、`mbic(500,4000)=1` ✅。
  单调性 `ebs(500, cols)`：`50→500, 200→500, 800→443, 1728→205, 4000→88`（不增 ✅）。
- 敏感性：若改用窄·深实测的 `5.0994e-5`，`budget=941,287 / perblock=235,321` ⇒
  `mbic(100,142)=20`（窄文件仍不变 ✅）、`mbic(100,1728)=5`、`ebs(500,1728)=136` ⇒
  **结论在 1.5 倍的单价不确定带内不翻**。

## 8. Q3：本地复现不出生产的延迟量级 —— 延迟阈值不许由本文来定

**这是发现，不是可以抹掉的偏差。** 本地（浏览器档，`vite preview` + Chromium）量到的形状：

| 段 | 本地实测（宽形状第 2 轮） | 生产（spec §1.2，同一 URL 同一体积） |
|---|---|---|
| 后端 / 网络（`durationMs`） | 首块 **1,216 ms**；块 2..20 **19–60 ms** | 848 / 3,743 ms（`/browse/`）；550 ms（`/summary/`） |
| 渲染侧「收到响应 → JS 处理完」 | `responseEndMs=2122` 处一条 **475 ms** long task（+续帧 200 ms） | **9,514 ms**（总 10,064 − 后端 550） |
| 19 个续块的 long-task 增量 | **78 ms**（`tasks=6 − tasks=5`，唯一新增一条 `[2959,78]`，`startMs` 正好是 page 2 的 `responseEndMs`） | —— |
| 空闲时的对照 | 无（本地没有「刚重启的空闲进程」这一档） | 同一请求 **51 ms** |

⇒ 本地最大一条是生产渲染侧 tail 的 **1/20**（475 vs 9,514 ms），形状方向一致（**首块最贵**）但幅度差一个数量级。
不可比的成因，能核实的都列出来：

1. **缺 Electron 那一段**：探针跑在 `vite preview` + Chromium，生产 tail 含 axios 拦截器 + `console`
   跨进程转发到主进程（spec §1.2 明说现有日志**拆不出** GC / AG Grid 布局 / IPC 各占多少）。
2. **后端解析缓存已热**：首块 1,216 ms、续块 19–60 ms；生产是 3,743/848 ms。
   19 块只多出**一条** 78 ms 的 long task，说明这一轮「渲染排队」根本没发生。
3. **本机没有 commit 压力**：可用提交内存 16.8 GB（§5），生产是 7.4 GB 且当天崩过
   `Renderer process gone: oom`（spec §1.1）——GC thrash 这一维在本地不存在。
4. **long task 的绝对值随机器负载摆动**：同一形状同一代码，Task 1 报告 §2 两轮 `longTasksMsTotal`
   首屏 1,599/1,626 ms，本轮是 1,045/1,071 ms（Task 1 报告 §9.1 已定性：每块渲染本就压在 50 ms
   longtask 门槛附近，机器一忙就整块越线）。

**口径裁定（给下游）**：Q1/Q2 的**驻留量**环境无关，可以进预算（本文 §4–§7 就是这么用的）；
**Q3 的延迟量级在本档不可复现，所以本文不给任何「首块 < X ms」的阈值**。
要判「卡顿改善」只有两条合法通路：(a) 同一环境整改前后的相对值（spec §6:137 的写法）；
(b) 回生产机用 Electron 档量 —— 那属于本轮未授权的 D 项，不在 E 的范围里。
任何从本节 475/78 ms 反推阈值的做法，都是把本地量级当生产量级。

## 9. 被实测推翻 / 修正的四条

1. **分母不是 172,800 格/块，是 86,400。** plan Task 2 Step 2 写「每块 100 行 × 1,728 列 = 172,800 格」，
   那是**生产设置**那一档；探针实测定的是 50 行/块（`shape.cellsPerBlock=86400`），
   因为 ETS88 只有 1,436 行，100 行/页时凑不出 20 块。照抄 172,800 会把单价**低估一半**
   （`55.5/(19×172,800)=1.6904e-5`）⇒ `budget=2,839,524` ⇒ `cap(100,1728)=16` ⇒
   按真实单价算实际驻留 **93.5 MiB**，是 48 MiB 目标的两倍（窄文件那一档倒是仍为 20，
   所以这条只有宽文件那一侧暴露 —— 光靠验收表抓不住，得核对分母本身）。
2. **上游那句「plan 里的占位 `2.4e-4`，比实测大 7 倍」对不上原文。** 可核实的占位在台账
   `progress.md:26`，是 `CELL_PER_BLOCK_MAX / CELL_RETAIN_BUDGET = 200k / 400k` 一对：
   驻留预算那一档隐含单价 `1.2e-4`（比实测大 **3.6 倍**），`2.4e-4` 只有把 **200k 的单块上限**
   误当驻留预算时才成立。两档后果不同 —— `1.2e-4`：窄文件仍 20 ✅；`2.4e-4`：窄文件掉到 14 ❌（§7）。
   plan/spec 正文里 `2.4e-4` 与 `250 B` 都 grep 不到（§4 末尾那条），所以本文只用自己算得出的数，
   并把这处口径分叉留档：下游若撞见「7 倍」的说法，按 §4 的三档对照读。
3. **brief 期望 ETS88@100 的 cap 落在 2–4，按实测单价是 8。** 那个带不是新证据，它就是占位算式
   `floor(400,000 / 172,800) = 2` 的输出（台账 `progress.md:26`），基数是被实测推翻的 `1.2e-4`。
   我没有为了落进那个带而回头调小目标：`RETAIN_MIB_TARGET` 的调整条件（brief Step 2「实测**远超**预期」）
   没触发（§5），而 8 块 × 172,800 格 = 46.7 MiB ≤ 48 ⇒ 与目标自洽。
   **如果仍要把宽文件压进 2–4，正确的旋钮是预算而不是断言，且备选值必须按整数格定义**：
   `CELL_RETAIN_BUDGET := 691,200`（= 4 × 172,800 格）⇒ `CELL_PER_BLOCK_MAX = 691200//4 = 172,800`、
   `ebs(500,1728)=100`、`mbic(100,1728)=4`（4 块正好吃满预算）、**窄文件仍算出 20**
   （`691200 // (100×142) = 48` → 被 `MAX_BLOCKS=20` 钳住）。
   ⚠ **别把它写成 `RETAIN_MIB_TARGET = 23.36 MiB`（本文初稿正是这么写的，复审 Important 2 不复现）**：
   走 `budget = floor(目标 / 单价)` 那条链路时 `floor(23.36/3.38e-5) = 691,124` ⇒ `perblock=172,781`
   ⇒ `ebs(500,1728)` 掉到 **99**、`mbic(100,1728)` 掉到 **3**（拿 4 块只发生在把 `ebs=99` 代进去那一支，
   也就是这块到底按 99 还是 100 行算要看传进去的是设置值还是 `effectiveBlockSize`）⇒ 采纳者会少发一块；
   连本文原来括注的精确值 `23.36256` 也一样 —— 浮点除法 floor 到 `691,199`，差 1 格，
   而 `691,200 = 4 × 172,800` 正好压在刀口上，所以**旋钮定义只能抄整数，不能从 MiB 目标反推**。
   这是一个**新裁定**，不该由本任务默认改方向，所以本文交付 48 MiB 那一版，把这条留给收口评审拍板
   （正反三档都由 `tasks/t2-derive.py` 末节产出，命令与输出逐字如下）：

   ```
   $ PYTHONIOENCODING=utf-8 python tasks/t2-derive.py | tail -n 8
   == §9.3 备选旋钮：先证「写成 MiB 目标」不复现，再给可复现的整数定义 ==
   反例 RETAIN_MIB_TARGET=23.36 MiB -> budget=691124 perblock=172781 ebs(500,1728)=99 mbic(99,1728)=4 但 mbic(100,1728)=3（窄 mbic(100,142)=20）
   反例 RETAIN_MIB_TARGET=23.36256 MiB -> budget=691199 perblock=172799 ebs(500,1728)=99 mbic(99,1728)=4 但 mbic(100,1728)=3（窄 mbic(100,142)=20）
   CELL_RETAIN_BUDGET := 691200 -> CELL_PER_BLOCK_MAX = 691200//4 = 172800
     宽 ebs(500,1728)=100  mbic(100,1728)=4（钳前 691200//172800=4） 驻留=691200 格 = 4 块吃满预算
     窄 ebs(100,142)=100  budget//(100*142)=48  mbic(100,142)=20（被 MAX_BLOCKS=20 钳住 ⇒ 窄文件不变）
     等价 MiB 目标 = 691200 × 3.38e-05 = 23.36256 MiB（但别把它写回旋钮定义，见上两行反例）
     极宽 4000 列 @500：ebs=50 mbic=3
   ```

4. **窄·浅（45 列 × 50 行）的 Δ 不可分辨**：0.2 / 0.3 MiB，两轮相对差 33%（超过 spec 的 <20%），
   但绝对值是 48 MiB 预算的 **0.6%** ⇒ 该形状量不到东西，不是形状坏。要在这只文件上拿到可分辨的信号，
   就把它压到 §3 行 5/6 那一档（500 行/块，Δ 21.8 MiB，两轮逐字相同）。
   这一维的**结论**是好消息：窄文件 20 块满缓存的实际驻留 ≤0.3 MiB，与「窄文件行为必须不变」完全一致。

## 10. 数据边界（Task 4/7 复跑前先读这一段）

- **本机、单 slot、同一 slot 模板与同一构建**。跨机、跨构建未验；Task 1 报告 §5.6 同一条提醒。
- **列数口径 = `/browse/` 的 `headers.length`**（含 `default_hidden_columns` 隐藏的列；行数据由
  `zipBrowserRows` 按 headers 全量拼），比真实驻留格数**少 2 列**（`__fail_cells__`/`__borderline_cells__`），
  方向保守（Task 1 报告 §9.4）。Task 3/4 若改「每块格数」的定义，本文 §4 的单价要一起改口径。
- **单价只在这两只文件的数据类型上是实测的**（ETS88 千列数值为主、STS8200_CP 45 列混合）。
  两只可分辨形状相差 1.5 倍（3.38e-5 vs 5.10e-5，§7 的敏感性那条）；换数据类型未知，超出该带要重跑。
- **`heap` 是 `Runtime.getHeapUsage` 的 used 且取样前强制 GC**：量的是驻留，不是 RSS / 提交内存占用，
  与生产 oom 那一维之间没有换算关系（§8 第 3 条）。
- 只量了「查看数据」网格。分析页图表（`analysis_chart_state`/ECharts 实例）、导出通路、
  Electron 主进程与后端内存在本文之外（后者在 `2026-10-21` 那批）。
- **整改后复跑该怎么打**（Task 4/7，形状不换代码只换 env）：
  宽形状 `LQDP_PROBE_BLOCKS=16`（= §7 的 `maxBlocksInCache(50,1728)`）。驻留块数按 ag-grid 自己的
  `blocksToKeep = maxBlocksInCache − 1`（实测代码：
  `frontend/node_modules/ag-grid-community/dist/package/main.cjs.js:55995`），但本轮**实测**形状 2 是
  「cap=20 ⇒ 去重 20 页都驻留 ⇒ Δ 正好是 19 块的增量」，所以同口径外推 cap=16 是「16 块驻留 = 15 次增量」：
  `94.1 + 15 × 2.921 ≈ 137.9 MiB`（**单价外推，不是实测**，实测才算数；若实际只留 15 块则是 134.9 MiB，
  两者都远低于今天的 149.6）。
  生产那一档宽形状 `LQDP_PROBE_PAGE_SIZE=100 LQDP_PROBE_BLOCKS=8`（ETS88 1,436 行够 800 行 ✅）；
  4 标签那一行**不能**用格数模型预测（§5 末尾那条 ⚠）。

---

**交付摘要（Task 3 直接抄 §6）**：`RETAIN_MIB_TARGET=48` MiB、`mib_per_cell=3.38e-5`、
`CELL_RETAIN_BUDGET=1,420,118` 格、`CELL_PER_BLOCK_MAX=355,029` 格；
窄文件（142 列 @100）`maxBlocksInCache` 仍 = 20。
