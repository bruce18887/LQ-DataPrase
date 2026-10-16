# 测试分层与门禁节奏

本文是「一次改动该跑哪一档验证」的**唯一事实来源**，被 git 跟踪。`.claude/CLAUDE.md` 与 `AGENTS.md`
只做入口指向本文，不复制正文（避免双份漂移）。判据表的实现是 `scripts/affected-rules.mjs`，
由 `frontend/test/unit/e2eAffectedDecide.spec.ts` 钉住——**改判据只需跑 vitest，不需要开浏览器**。

设计 rationale 与存量普查在 `docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md`、
`docs/reference/e2e-tier-triage.md`；本文只写**当下该执行什么**。

## 1. 该跑哪一档

| 时机 | 命令 | 实测成本 |
|---|---|---|
| 每批 commit 前 | `cd frontend && npm run test:e2e:affected` | 命中模块档 1–3min；无门禁 ~3s |
| 改门禁判据 / 阈值 / 图标判据 | `npx vitest run` | 0.4s |
| 功能收口、FF 并入本地 master 前 | `node scripts/e2e_pool.mjs --slots=4` + 后端全套 | 6–8min + 后端 |
| 每日兜底 | `node scripts/e2e_nightly.mjs` | 同上（前置不过则 SKIPPED） |
| GitHub CI | 自动 | 后端全套 + build + vitest + lint:e2e，**刻意不跑 Playwright** |

三条硬口径：

- **看到 `NO AFFECTED TESTS` 不等于绿灯**，它表示本轮没有测试承重；快门禁会同时打印 `note:`
  说明那部分改动由哪条通路验证（子项目、CI、打包脚本各有各的通路）。
- **并行度只有 `--slots` / `E2E_SLOTS` 一个旋钮**，不要手改 playwright 的 `workers`。
  判据是**打印出来的实际 slot 数与加权总量**，不是命令行写了什么：缺 `tasks/e2e-nightly` 产物时
  分区未加权，`--slots=4` 会静默折成 1 个 slot（墙钟退回 20min 级）。
- **e2e 与后端套件的落盘面已分开（2026-10-16）**：e2e 的库 / `MEDIA_ROOT` / 临时区由
  `config.settings.e2e_slot` 指认（串行 = `test/e2e-data`，池 = 各 slot 自己的目录），后端套件由
  `config.settings.unit` 指认（`test/unit-data`，`manage.py test` 默认走这档）。旧那条「绝不可并跑：
  共用 `media/` 与 `db.sqlite3`」的**根因**（两边都写仓库根 `media/`）已经消失 —— 但并跑本身
  还没实测过，真要同批跑请先各自单独跑绿一次，别把「目录分开了」当成「已验证可并发」。
  跑完全量要释放端口。

## 2. 三层判据（写新断言之前先选层）

| 层 | 位置 | 判据 | 实测规模与单价 |
|---|---|---|---|
| **T1 后端契约** | `test/backend/`、`apps/*/tests_*.py` | 响应体 / service 返回值就能表达：数值、状态码、错误码、字段存在性 | `def test_` 计数 1561（test/backend 935 + apps/* 626）；2026-10-16 实跑 `Ran 1427`；≈3.6 例/秒 |
| **T2 前端纯函数** | `frontend/test/unit/`（vitest，node 环境，不装 jsdom） | 入参→出参，无 DOM 无网络 | 194 例 / 13 文件 / 0.42s |
| **T3 浏览器不可替代** | `frontend/e2e/`（Playwright） | 只有五类：真实渲染（canvas / ag-grid 虚拟化 / 轴像素）、双主题对比度、跨页跨 tab 状态与路由守卫、上传下载与 Electron IPC、`data-*` 契约本身 | 390 次展开 / 75 文件（P1 232 · P2 133 · P0 13 · Edge 10 · setup 2）；单价 2.9–3.1 s/例 |

**冲突裁决**：同一判据 T1 与 T3 都能表达时，T1 写全组合，T3 只留一条「接线证明」（例：CPK 八组边界进后端，
e2e 只断页面渲染出 CPK 且非空）。**不要在浏览器里逐组合点按钮。**

**单价不由断言条数决定**，由 SPA 冷启动（echarts 1.1MB + ag-grid 1.2MB + element-plus 1.0MB）与
`gotoApp`/sleep/poll 决定。所以真正省墙钟只有三条路：整条用例消失、砍掉不必要的昂贵前置、
删掉被 `.catch` 吞掉的等待。**混合用例拆薄几乎不省时间**。

## 3. 门禁会升级成全量的三种情形

1. 改动命中「明确的全局清单」——`config/`、`frontend/playwright.config.ts`、`frontend/src/stores|router|layouts|styles|theme|types|constants|composables|utils/`、
   未被 T2 钉住的 `frontend/e2e/helpers|fixtures|global|smoke/`、`manage.py`、`standalone.py`、`build.bat`、依赖清单等。
2. 命中 `*/*/migrations/*.py`（schema 变了谁都说不准）或 `.env*`。
3. 命中 **6 个以上** e2e 模块（`MAX_MODULES_BEFORE_FULL`）。

以及**兜底：未知路径一律全量，宁可多跑也不漏**。这条方向不许改——要放宽只能把具体类目
写进 `RULES` 并说清「它为什么不由浏览器承载」，同时在 vitest 里钉住双向判据。

### 已被实测确认的放行类目（2026-10-16）

这些改动一行产品代码都不动，跑浏览器只是把没变的东西再测一遍：

- `.gitignore`（任意层级）、`.lqdp_startup.lock`、`.commandcode/`、`.superpowers/`、`.workbuddy-ai/`、
  根级诊断截图（`frontend/xxx.png` 这类单层位图；入库资产住 `frontend/public/` 与 `src/assets/`）；
- `.github/`——CI 配置由 CI 自己验；
- 打包期图标工具：`scripts/icon-lib.cjs`（判据已由 `iconLib.spec.ts` / `appIcon.spec.ts` 钉住）、
  `icon-audit.cjs`、`icon-metrics.cjs`、`gen-icon.ico.js`、`generate_icon.py`；
- 门禁自己的判据与编排器：`nightly-gates.mjs`（`e2eNightlyGates.spec.ts`）、`pool-core.mjs`
  （`e2ePoolCore.spec.ts` 42 例）、`scripts/e2e_*`。
  ⚠ **编排器本身没有单测**（IO 重），改完必须自证 `--dry-run` 并核对打印的判定与 slot 数——
  「门禁坏了但没人知道」不能被判成绿灯（2026-10-13 就撞过一次：后端分支 cwd 拼错，那条快门禁从没跑通过）。
- `apps/<app>/tests*` 只出后端测试标签，**不牵动 e2e 选例**。这 11 条规则此前写在 `apps/<app>/` 之后，
  而判据表是「首条命中即生效」，于是它们全是死规则；2026-10-16 调整顺序后由
  `e2eAffectedDecide.spec.ts` 钉住。

**效果实测**：最近 25 个提交（跨约 29 小时）逐个重放判定，升级成全量的比例
**13/25（52%）→ 5/25（20%）**；剩下的 5 个确实动了 `playwright.config.ts` / `apps/*` 视图 / 产品代码。

## 4. 退化阈值

单源在 `frontend/e2e/helpers/nightly-gates.mjs`，改阈值只改那里（`e2e_nightly.mjs` 与池都引它）：
墙钟 >12min、单价 >4.5s/例、效率 <0.7×N、用例 >450、flake >5。

- **崩池轮什么都不判**：池自判 `verdict=VOID (infra)`（退出码 3、现场不清），那种轮的单价/红数不可信，
  **重跑才是结论**，别当退化读、更别去改用例。
- **效率只在「本轮没有重跑」时判**（`hasRetries`）：失败的 attempt 吃墙钟却不进分子，
  实测零红轮 3.04、有两个红文件被复跑的两轮 2.73 / 2.34。
- 改完阈值用 `--report-only <既有 results.json|merged.json>` 验算，**不要为确认一个公式再跑一轮全量**。
- ⚠ **后端套件的子进程捕获必须显式给 `encoding`**。旧断言在此撤回：本文件先前写「夜跑给后端那步注入
  `PYTHONIOENCODING=utf-8`，无害，先留着」—— **实测不成立**。那次「中文 Windows 不带 `PYTHONUTF8=1`
  稳定假红 6 条」被 A/B 否证时只填了**读文件**那一半，另一半在**捕获子进程输出**：
  `subprocess.run(..., text=True)` 不给 `encoding=` 就按本机 locale（cp936）解码，父进程一带上
  `PYTHONIOENCODING=utf-8`，子进程那份 UTF-8 中文 traceback 会让 `_readerthread` 抛
  `UnicodeDecodeError`，而**该异常被读取线程吞掉、`result.stderr` 落成 `None`** ⇒ 断言收到空串。
  实测因果：`test_server_settings_profile` + `test_e2e_slot_settings` 不带该变量 **21 例全绿**，
  带上即 **5 FAIL + 1 ERROR**。现已修 —— 三处捕获统一加 `encoding='utf-8', errors='replace'`，
  并在子进程 env 里钉死 `PYTHONIOENCODING=utf-8`（两种父环境各跑一遍 **27 例 OK**）。
  留给将来的判据：红项报 `not found in ''` 或 `argument of type 'NoneType' is not iterable`，
  先查捕获有没有给 encoding，**别靠预设环境变量来"防"**。
  残留同族写法：`test/backend/test_sftp_search_integration.py:66`（stderr 走文件句柄），本轮未动。

## 5. 各入口速查（哪个贵、哪个已没人用）

| 命令 | 实际覆盖 |
|---|---|
| `npm run test:e2e:affected` | **默认该用的**，按改动选例 |
| `node scripts/e2e_pool.mjs --slots=N -- <files>` | 并行全量/小集合的唯一入口；`--slots=1` 用于同桶顺序污染复现 |
| `npx playwright test --project=P1 --workers=1` | 单模块定向；SFTP 用例**必须**带 `--project=P1`，否则被 Edge project 的 `grepInvert` 静默跳过（假绿） |
| `npm run test:e2e` | 裸跑 390 次全量，且 `workers=6` 打单进程 Django 会造出与改动无关的硬红——**不要用** |
| `npm run test:e2e:quick` | 名义 quick，实为 Edge+P0+P1 = 255/390 ≈ **65% 套件**；不在本节奏表里、无人认领，别当快档用 |
| `npm run lint:e2e` | e2e 静态体检（`tsconfig.e2e.json`）。**e2e 不在 `npm run build` 的 include 覆盖内**，删用例留下的死 import 只有这条通路能发现 |

每次提交前的检查集：`npx vitest run` + `npm run lint:e2e` + `npm run build`（含 `vue-tsc -b`）。

## 6. CI 检出的自足性（2026-10-16 三条根因）

CI 跑的是**干净检出**，本机绿不代表它绿。这三条都是「本机在跑、CI 永远红」的形状：

- **包标记必须入库**。`.gitignore` 的 `/test/*` 曾只例外了 `test/backend/` 与 `test/type-snapshot/`，
  漏了 `test/__init__.py` ⇒ CI 检出里 77 个测试文件都在、`import test.backend` 却失败
  （`ModuleNotFoundError` 逐字可复现：只造 `test/backend/__init__.py` 而不造 `test/__init__.py`）。
- **对被忽略的目录，git 不会往下找例外**。`/Data/` + `!/Data/SampleData/Gage/` 这个组合**不生效**，
  必须先 `/Data/*` → `!/Data/SampleData/` → `/Data/SampleData/*` → `!/Data/SampleData/Gage/` 逐级放开。
  验收判据是 `git status --porcelain --untracked-files=all` 的**条数恰好等于放开的文件数**
  （本次改前 0 → 改后 4），不能只看目标文件出现了。
- **测试期望值里别写死路径分隔符**。前端 job 在 ubuntu，实现用 `path.join` 产出 `/`，
  而夹具根路径是字符串字面量 ⇒ 断言整条串必挂。断**basename**或两边都用 `path.join` 构造。
  跨平台断言的验算办法：把 `path.win32` 与 `path.posix` 各跑一遍同一条公式，
  posix 下算出的值应当**与 CI 报的 Received 逐字相同**，这才叫复现。
- 样例夹具缺了要**显式 skip**，别让它 error：`apps/dashboard/tests.py:284`、`apps/export/tests.py:52`
  对 `SampleData/CTA8280F` 就带 `skipUnless(os.path.exists(...))`，在 CI 上算 skip 不算红。

⚠ 放开 `Data/SampleData/Gage/` 入库等于把机台 datalog 头（内部路径、主机名、账号）放进**公开仓库的历史**。
推之前先确认这几个字段可见，或先把仓库转 private。

## 7. 未闭环（截至 2026-10-16）

- **夜跑 cron 已注册但 `enabled=false`（manual pause）**，且 automation 的 prompt 仍描述 slot 池之前的
  串行旧形态（「CI=1、workers=1、整轮约 25 分钟」）。历史上 6 条记录 = 3 SKIPPED / 2 FAILED / 1 VOID，
  **没有一次成功真跑** ⇒ 兜底层实际不存在，全量都落在开发会话里手动跑。
  重启前要先处置：`e2e_nightly.mjs` 的工作区必须干净这条门会被别的会话留下的一项删除永久挡死。
- 32 例（分诊的 8%）无处可落：缺「ECharts option 层断言 / 前端出站请求体 / 组件内联逻辑」这一档，
  而当初明确选了「不做组件/DOM 层」，这个矛盾待重新拍板。
- 试点簇 #2 `custom-limit-cpk`、#3 `settings/cpk-thresholds` 未做。
- 套件里仍有点同一个图表开关的盲点写法（已收敛 13 处，其余目前绿所以没动），
  清单见 `docs/tasks/todo.md`「遗留地雷清单」。
