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
| 改门禁判据 / 阈值 / 图标判据 | `npx vitest run` | 0.6s |
| 功能收口、FF 并入本地 master 前 | `node scripts/e2e_pool.mjs --slots=4` + 后端全套 | 6–8min + 后端 |
| 每日兜底 | `node scripts/e2e_nightly.mjs` | 同上（前置不过则 SKIPPED） |
| GitHub CI | 自动 | 后端全套 + build + vitest + lint:e2e，**刻意不跑 Playwright** |

硬口径：

- **看到 `NO AFFECTED TESTS` 不等于绿灯**，它表示本轮没有测试承重；快门禁会同时打印 `note:`
  说明那部分改动由哪条通路验证（CI、打包期图标工具、门禁编排器各有各的通路）。
- **判绿/红取日志末尾的 `RESULT:` 行，不取 `$?`**（2026-10-20 实测：`… 2>&1 | tail -45`
  的退出码是 `tail` 的，于是「exit 0」与「FAILED (failures=1)」出自同一条命令）。
  affected 门禁把每档结果打成 `档: <name> ok|FAIL|SKIP|ABORTED` + 末行 `RESULT:`，
  故意放最后 —— 任何 `tail -N` 的窗口都盖不住它。非要读退出码就 `| tee` 或 `set -o pipefail`。
- **每一档都会执行**：`planStages()` 只由改动集决定，签名里没有退出码，所以一档红改不了
  后面跑什么（旧写法 `code ||= runPool('')` 在 code 已非零时连右值都不求值，后端一红
  整条 T3 根本没启动，日志只剩一个非零码，读起来像「跑到浏览器那档才失败」）。
  该跑的档**跑不了**（如 `python` 无 pytest）判 `ABORTED` → `RESULT: FAIL`，不再 print 完就退 0；
  只有显式 `--no-backend` 记成 `SKIP` 且不拦绿，但它必须出现在结论行里。
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
| **T2 前端纯函数** | `frontend/test/unit/`（vitest，node 环境，不装 jsdom） | 入参→出参，无 DOM 无网络 | 353 例 / 26 文件 / 0.60s（2026-10-20 实跑） |
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
  2026-10-20 起编排**判据**（`planStages` / `executePlan` / `gateVerdict`）已从 `e2e_affected.mjs`
  搬进 `affected-rules.mjs`、由 `e2eAffectedDecide.spec.ts` 钉住；脚本里只剩 IO 壳
  （取改动集、探测解释器、spawn）。⚠ **IO 壳仍没有单测**，改完必须自证 `--dry-run` 并核对打印的
  判定、slot 数与末尾 `RESULT:` 行 ——
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
  必须逐级 `/Data/*` → `!/Data/SampleData/` → `/Data/SampleData/*` → `!/Data/SampleData/Gage/`。
  （本仓**最终没走这条路**，见下面「夹具虚拟化」——但这条 gitignore 语义本身是成立的事实，
  将来真要放开某个子树时用得上。）验收判据是 `git status --porcelain --untracked-files=all` 的
  **条数恰好等于放开的文件数**，不能只看目标文件出现了。
  ⚠ 与之相对，`!/test/fixtures/` **一条就够**：`/test/*` 里的 `*` 不跨 `/`，只挡一层
  （本仓 `!/test/backend/` 能跟踪 76 个文件即同例）。两种情形易混，判据是实测条数，不是感觉。
- **测试期望值里别写死路径分隔符**。前端 job 在 ubuntu，实现用 `path.join` 产出 `/`，
  而夹具根路径是字符串字面量 ⇒ 断言整条串必挂。断**basename**或两边都用 `path.join` 构造。
  跨平台断言的验算办法：把 `path.win32` 与 `path.posix` 各跑一遍同一条公式，
  posix 下算出的值应当**与 CI 报的 Received 逐字相同**，这才叫复现。
- **子目录没有 `__init__.py` 就不被收集**。`test/backend/batch_report/` 缺包标记，
  那 160 例从来没进过「后端全量」的账（`DiscoverRunner` 不递归非包目录，Python 3.11+ 起尤严）。
  想让它进账就补 `__init__.py`——注意那文件 `import pytest`，而 `requirements/base.txt` 没有 pytest，
  补了就是新的 CI 红。
- 样例夹具缺了要**显式 skip**，别让它 error：`apps/dashboard/tests.py:165`、
  `apps/export/tests.py:182/269/397`、`apps/export/tests_chart_dpi.py:94` 对 `SampleData/*`
  带 `skipUnless(os.path.exists(...))`，在 CI 上算 skip 不算红。
- **起子进程的解释器别写死 `.venv`**。`.venv/` 不入库 ⇒ 干净检出（含 GitHub runner）里两档候选
  都不存在，`subprocess` 在 `Popen` 处 `FileNotFoundError: [WinError 2]`。
  正确做法是最后回退 `sys.executable`（`test_server_settings_profile.py:27-35`）。
  这 10 条以前不红只是因为 `test/__init__.py` 缺失让整个 `test.backend` 没被收集 —— **解禁旧遮蔽会带出新红，属正常，不是回归**。

### 虚拟化夹具（真实 datalog 不入库的正解）

真实 `Data/SampleData/Gage/` 含内部绝对路径、机台主机名、内部账号与产品代号，而仓库是**公开**的。
所以不给它开入库口子，而是用 `scripts/make_gage_ci_fixture.py` 派生 `test/fixtures/gage/`：
332 个测试项名**按位次**换 `PAR0001..PAR0332`（真实名中 48 个互为前缀，按串替换会互啃）、
料号家族与路径换假值但保住 `B<字母><数字>` 整词 + `_FT` token 与同样的目录层级/扩展名
（`parsers/cta8290d.py` 从 `TestFile` 的 basename 推 product_code/stage）。
**原样保留**：全部数值、行数、`[Data],` 位次、13 个系统列名、`Unit/Min/Max` 三行、
`CTA8290DPlus`（`base.py:70` 靠小写子串 `cta8290d` 判格式）、`LotID`、`Tester_ID=140000`
（S1 出现 15 次、14 次是数据值 `1.140000` 的巧合，禁止全文替换）。

- 两个无守卫的模块（`apps/batch_report/tests.py`、`apps/buyoff/tests.py`、`apps/gage/tests.py`，共 15 例）改指夹具；
  带 `skipUnless` 的仍指真实样例，CI 上继续 skip。
- 夹具入库必须配 `.gitattributes` 的 `test/fixtures/gage/*.csv -text`：
  本仓只有 `core.autocrlf=true` 这一半，Linux 检出会把 CRLF 变 LF、每文件少 534 字节，而行尾形态是解析承重项。
- **派生脚本与 MANIFEST 里禁止出现真实标识符字面量**：第一版把料号/主机名/内部路径写成「禁止残留串」常量表、
  又把 332 条真实名→假名映射写进 `MANIFEST.txt`，而这两者都要入库 —— 等于把刚虚拟化掉的东西再发布一遍。
  现在禁止串运行时从真实输入现取，映射只按需 `--emit-mapping <Data/ 下的路径>` 导出（那儿不入库）。

## 6.5 push 之前的历史自检（2026-10-16 事故）

真实 gage CSV 曾被一笔「放开 `/Data/` 入库」的提交带进历史，随后**被一条无关的 `git push` 一起推上公开仓库**。
前向修复（把文件从树里摘掉）**挡不住这个**：blob 还在历史里，按 commit SHA 可直接取。

1. **push 推的是整条链，不是「我这一笔」。** 提交前要跑 `git log --oneline origin/master..HEAD`
   逐条看会被带出去什么——里面常有别人未推送的提交。
2. 凡动过「本该不入库的目录」（`Data/`、`tasks/`、`.venv/`、密钥类）的提交，
   **要么别提交，要么在 push 前重写历史摘掉**，不能指望后续删除补救。
   绊线：`git log --diff-filter=A --name-only origin/master | grep -E '^Data/'` 应为空。
3. **重写后强推要先验内容、再带 lease**：`git diff --stat <备份ref> master` 必须 0 字节（只动历史不动内容）；
   `git push --force-with-lease=refs/heads/master:<服务端旧值>`。本仓 12 条重写后内容差异为 0。
4. **强推不等于撤回公开。** 已核实：分支链里 `c6b7bd8` 已不可达、新 master 上该路径 404，
   但按旧 SHA 请求 `Data/SampleData/Gage/gage_m_S1.csv` **仍返回 size 291657**（游离提交未被 GC）。
   服务端只剩 `refs/heads/master` 一个引用，没有分支/PR 钉住它，所以 GC 后会自动消失；
   在此之前按「已泄露」处理，不要按「已修复」处理。要立刻抹除得提 GitHub 支持工单。

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
