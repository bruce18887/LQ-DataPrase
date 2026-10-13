# e2e 三层判据 + 改动范围门禁（2026-09-26）

## 背景与实测基线

e2e 套件已长到全量一轮 ≥20 min，功能继续加就会线性变慢。本轮不改产品行为，
改「断言落在哪一层」与「提交前跑哪些用例」这两条规则。基线数字全部实测：

| 项 | 值 | 出处 |
|---|---|---|
| spec 文件 / 选中用例 | 74 → **75 文件 / 393 → 399 例** | `npx playwright test --list` |
| spec 代码量 | 16,665 行 | `find e2e -name '*.spec.ts' \| xargs wc -l` |
| 增长速度 | 07-01:17 → 08-01:22 → 09-01:56 → 09-24:74 文件 | `git log --diff-filter=A` |
| 优先级分布 | P0 15 / P1 228 / P2 141 / 无标签 15 | 同上 |
| 单例成本 | 分析页 P1 97 例 / 8.7 min @`workers=1` ≈ 5.4 s/例 | 2026-09-02 实测 |
| 并发上限 | 6 workers，分析页必须 1 | `playwright.config.ts:47` |
| 冷启动 | 255 处 `gotoApp` = 每例一次完整 SPA 启动 | grep |
| 构建开销 | 6.6 s（**不是**瓶颈） | `time npm run build` |
| 硬编码 sleep | 91 处 / 50.8 s（噪声级） | grep `waitForTimeout` |
| 前端更便宜的层 | 本轮之前**不存在**（`frontend/test/` 空、无 vitest） | 核实 |
| 后端层 | 58 文件 / 888 例 / 243 s ≈ 3.6 例每秒 | lessons 2026-09 |

结论：P1 装了 58% 的用例，所以「快档」不省时间；真正的天花板是串行约束，
加核买不到速度。要同时动斜率（断言下沉）和常量（按改动选用例）。

## 三层判据（写断言前先选层，取第一个成立的最便宜落点）

- **T1 后端契约层**（已有 `test/backend/` + `apps/*/tests_*.py`）：判据能只用
  HTTP 响应体 / service 返回值表达 —— 断言对象是数字、状态码、错误码、字段存在性，
  不依赖 CSS、DOM、渲染时序。归属例：CPK 计算、bin 边界、IQR 乘数、KDE、离群处理、
  分页排序、`no_valid_params`/`no_site_column` 这类 400 守卫语义、设置生效链路。
- **T2 前端纯函数层**（本轮新建 vitest，`frontend/test/unit/`）：入参→出参、无 DOM 无网络。
- **T3 浏览器不可替代**（Playwright，5.4 s/例），只有五类留在这里：
  1. 真实渲染（canvas 出图、ag-grid 虚拟化横向滚动、轴标签像素精度）
  2. 双主题视觉（dark/light 对比度；jsdom 拿不到真实 computed style）
  3. 跨页 / 跨 tab 状态与路由守卫
  4. 上传 / 下载 / Electron IPC
  5. 选择器契约本身（`data-file-picker` / `data-filter` / `data-wafer-*` 等锚点是产品对外契约，
     见 `frontend/e2e/README.md` 的「已验证选择器」章节）

**冲突裁决**：同一判据在 T1 与 T3 都能表达时，T1 写全组合，T3 只留一条「接线证明」。
例：CPK 的 8 组限值边界进后端，e2e 只断「页面渲染出 CPK 且非空」，
不再在浏览器里逐组合点按钮。这就是「1 条冒烟 + 契约层断言」的可执行定义。

## T2 层落地

- `frontend/vitest.config.ts`：`environment: 'node'`（纯函数不需要 DOM，故**不装 jsdom**）、
  `include: ['test/unit/**/*.spec.ts']`。
- `frontend/tsconfig.unit.json` 并进根 `tsconfig.json` references —— 让 `npm run build`
  的 `vue-tsc -b` 一并类型检查单测（R8①：门禁必须是 build）。
- 首批白名单按实测 import 圈定（零运行时依赖）：`format.ts`、`minmax.ts`、
  `batchAggregation.ts`、`error.ts`。
- **明确排除** `filenameWrap.ts` / `echarts-theme.ts`：它们 `import { authApi }` 与
  `useThemeStore`，测它们要起 pinia + 网络桩，属于已被否掉的组件层。这类逻辑继续留 T3，
  或先把纯计算函数拆出来（拆分是产品代码改动，不在本设计内）。
- 实测收益：**31 例 / 162 ms**。同样 31 条断言走 e2e ≈ 2.8 min。

## 分诊清单（`docs/reference/e2e-tier-triage.md`，待产出）

393/399 例逐条标四档，用来定量「可下沉比例」而不是猜：

| 标记 | 含义 | 处置 |
|---|---|---|
| `T1` | 判据可只用响应体表达 | 搬后端，删 e2e |
| `T2` | 前端纯函数输出 | 搬 vitest，删 e2e |
| `T3` | 浏览器不可替代五类之一 | 留 |
| `T0` | 陈旧：断言与产品决策已脱节 | 删或改判（`batch.spec` 的 /batch 重定向、`admin.spec` 的「已禁用」、gzip 断言） |
| `T1+T3` | 混合（**实测最常见**） | 拆：数值下沉，接线/竞态留 |

**试点簇 = CPK / 限值族 3 文件**，每个都有一句话可核的依据：

1. `e2e/analysis/boxplot-bool-params.spec.ts` — 全仓唯一「整文件就是 API 级契约」的 spec
   （`POST /statistics/boxplot/` → 400 `no_valid_params` + `requested` 载荷）。
   T1 缺口已核实：后端 `tests_param_guards.py:323` 证的是 service 层容忍 bool，
   `:533` 证的是 unknown param → 400；「文件里存在的 bool / str 元数据列被 view 层过滤成空
   → 400 且载荷正确」无覆盖。搬迁复用 `:542` 的 `APIRequestFactory + force_authenticate` harness（R6①）。
2. `e2e/analysis/custom-limit-cpk.spec.ts` — 混合样本：数值判据下沉，
   「二次修改是否重发请求」「快速连改最终生效」两条竞态留 T3。用来验证 T1+T3 拆分动作做得通。
3. `e2e/settings/cpk-thresholds.spec.ts` — PUT 用户级持久化设置 + 生效链路，
   是 T1 与判据第 ③ 类的边界冲突点，专门用来试出判据缺陷。

试点的验收物不是省了多少分钟，而是两个单价：搬迁一例的机械成本、判据撞墙的次数与形态。
撞墙记录必须写回本文件的「撞墙记录」节。

## B：改动范围门禁（`scripts/e2e_affected.mjs`）

- 输入：`--base <ref>` 显式优先；否则 worktree vs HEAD（含 untracked）；
  工作区干净则退回 `HEAD~1..HEAD`；**git 读不到 → 判全量**，不猜。
  另有 `--files a,b,c` 喂虚构改动集，只核判定不碰工作区（映射表就靠它验的）。
- 映射键用**页面目录 / api 文件 / 端点所在 app**，不用宽泛词：实测 `analysis`、`files`
  这类单词在 e2e 里扇出到 6+ 模块，当键等于每次改动跑大半套件。
- 三条升级为全量的兜底：① 全局清单命中（`src/router|stores|layouts|styles|theme|types|
  constants|composables`、未映射的 `src/utils/*`、`api/index.ts`、`main.ts`、`App.vue`、
  `e2e/helpers|fixtures|global|smoke`、`playwright.config.ts`、`config/`、`requirements/`、
  `manage.py`、`standalone.py`、`scripts/`、`Data/`、`package*`、任何 `**/migrations/*.py`、
  `apps/common`、`apps/accounts`）；② 命中模块数 > 6；③ base 不可解析。未知路径一律全量。
- 永远附带：vitest 全量 + 未命中模块的 P0 补跑（按模块路径排除已选模块，避免同一用例跑两遍）。
- `apps/*/tests*` 与 `test/backend/` 不牵动 e2e 选择，由后端标签跑（`backendLabels()`）。
- 后端解释器按实测钉：用 `python`（`Python313`，pytest 9.0.3 在），**不用** `.venv`
  （无 pytest，`test_outliers.py` 的 import 失败会伪装成 `Ran 247 / FAILED (errors=1)`）；
  跑前自检 `import pytest`，失败即拒绝执行而不是静默跑。
- **反假绿输出契约**：无受影响用例时打印 `NO AFFECTED TESTS (...)` + exit 0，
  绝不允许显示成「0 failed」的绿；`DataPrase-ExcelAddin/**` 等子项目打印各自的验证通路提示。

## 夜间全量兜底轮（`scripts/e2e_nightly.mjs`）

决策全在脚本里，cron 的 agent 只负责执行与汇报（无人值守 + 共享工作区下，
每轮让 agent 自由判断"要不要杀进程"就是不可复现的风险面）。

- 前置三门，任一不过 → `SKIPPED` + 原因 + **exit 0**（跳过不是失败）：
  ① 8000/3000 有监听；② `tasks/e2e-nightly/e2e-nightly.lock` 存在（<4h 视为在跑，
  陈旧锁视为崩溃残留才清）；③ `git status --porcelain` 非空（结果会算到别的会话头上）。
- **绝不做**：`taskkill`/`Stop-Process`、任何 git 写、改 `docs/tasks/*`（多会话共享，R1）。
- 真跑时 `CI=1`：同时拿到 `reuseExistingServer:false`（不复用旧包假绿）、`forbidOnly`、`retries:2`。
- 产物：`tasks/e2e-nightly/<date>/results.json` + `latest.json`（最近 30 轮，同日期只留最后一轮）
  + `LATEST.md`（人读表）。`--dry-run` 只打印计划、不写时间序列。
- 退化阈值（命中即 `⚠ DEGRADED`）：墙钟 > 35 min；用例 > 450；flake > 5。
  2026-09-26 基线：393→399 例。阈值是脚本常量，改阈值=改代码。

## 门禁节奏（谁承载「可发布」保证）

| 场合 | 跑什么 | 目标时长 |
|---|---|---|
| 每批 commit 前 | `npm run test:e2e:affected` = vitest + 后端受影响 + e2e 受影响模块 + P0 补跑 | < 5 min |
| 功能收口 / FF 并入本地 master 前 | 全量 e2e（`npm run test:e2e`）+ 后端 888 例 | ≥ 20 min |
| 每日 03:30（cron，`executionAuthorization=false`） | 夜间全量轮，写时间序列 | ≥ 20 min |

## 撞墙记录（实施中发现、已改设计的四条）

1. **纯契约 spec 稀少**：27 个「做 API 级断言」的文件里只有 1 个整文件是契约断言，
   其余把 API 当造数据/取证手段（`chart-error-state`、`wafermap-model-not-found`、
   `serial-no-column`、`histogram-first-row-empty` 都核实过）。
   → 省时间的主要来源是「新断言不再写进 T3」，不是「删存量」。
2. **`frontend/test/` 未进映射表**：dry-run 当场暴露——任何 T2 改动都被未知路径兜底成全量。
   → 加 `['frontend/test/', ['unit']]`。
3. **Playwright JSON 墙钟在 `stats.duration`**，顶层 `duration` 是 `undefined`（`--list` 实测）。
   → `parseReport` 取 `stats.duration`。
4. **`PLAYWRIGHT_JSON_OUTPUT_NAME` 在 1.60 仍有效但 `grep node_modules` 找不到**
   （代码被打包）。→ 这类"能不能用"只能实测，不能靠 grep 结论。
5. **映射表复查（2026-10-13，因新增 `tsconfig.e2e.json` 而起）**：用 `--files` 虚构改动集再探一遍
   未覆盖路径 —— `frontend/src/pages/` 实际只有 admin/analysis/auth/dashboard/data/settings/sftp
   七个子目录，与表内条目**一一对上，没有漏网的页面目录**；`scripts/e2e_affected.mjs` 自身与
   `frontend/src/pages/batch/`（不存在的路径）都走「未知路径 → 全局清单」这条**安全**分支，
   不会退化成 `NO AFFECTED TESTS`；新文件 `frontend/tsconfig.e2e.json` 被既有前缀
   `frontend/tsconfig` 命中 → 全量（对 tsconfig.app/node 是对的，对 e2e 那份偏保守但安全）。

## 未验证清单（下一轮实施要补）

- 夜间轮的 T3 真实执行路径未跑过一轮（本机 8000/3000 被另一会话占用，前置门当场拦住）。
  需要一次空闲时段的真跑，核 `results.json` 解析与 `LATEST.md` 表格。
- 分诊清单未产出 → 「可下沉比例」仍是未知数，试点簇的选取依据是文件级证据而非全量普查。
- 基线在漂移（本轮内 393 → 399 例，共享工作区有并行会话在加 spec）→ 分诊以实施当时的快照为准。
- 判据第 ⑤ 类（选择器契约留 T3）意味着这类 spec 永不下沉，成本随行数线性增长，
  当前接受，若夜间轮连续 DEGRADED 由它引起再议。

## 本轮改动的文件

新增：`frontend/vitest.config.ts`、`frontend/tsconfig.unit.json`、`frontend/test/unit/{format,minmax,error,batchAggregation}.spec.ts`、
`scripts/e2e_affected.mjs`、`scripts/e2e_nightly.mjs`。
修改：`frontend/package.json`（`vitest` devDep + `test:unit` / `test:e2e:affected` / `e2e:nightly`；
保留既有 `test:e2e:quick`）、`frontend/tsconfig.json`（references 加 unit）。
未改：任何既有 e2e spec、`playwright.config.ts`、产品代码。
