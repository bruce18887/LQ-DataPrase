## Workflow Orchestration（工作流编排）

### 1. Plan Node Default（默认计划节点）

- 任何非琐碎任务（3+ 步或架构决策）必须进入计划模式。
- 一旦出现偏差，立即停止并重新规划，不要继续硬推。
- 验证步骤也要使用计划模式，而非仅用于构建。
- 提前写详细规格，减少歧义。

### 2. Subagent Strategy（子代理策略）

- 大量使用子代理，保持主上下文窗口干净。
- 将研究、探索、并行分析全部外包给子代理。
- 复杂问题时，通过子代理投入更多算力。
- 每个子代理只专注一个方向。

### 3. Self-Improvement Loop（自我改进循环）

- 用户任何一次纠正后，立即更新 `docs/tasks/lessons.md` 并记录模式。
- 写规则防止自己重复犯错。
- 无情迭代 lessons，直到错误率下降。
- 每次会话开始时，先复习项目相关 lessons。

### 4. Verification Before Done（完成前验证）

- 绝不在证明它能工作前标记任务完成。
- 必要时对比主分支与修改行为。
- 自问：“资深工程师会批准吗？”
- 运行测试、查日志、展示正确性。

### 5. Demand Elegance (Balanced)（要求优雅但平衡）

- 非琐碎改动时暂停：“有没有更优雅的方式？”
- 如果修复感觉 hacky：“基于我现在的一切知识，实现优雅方案。”
- 简单问题不要过度工程化。
- 每次呈现前先挑战自己的工作。

### 6. Autonomous Bug Fixing（自主 Bug 修复）

- 收到 bug 报告后直接修复，无需用户手把手。
- 指向日志、错误、失败测试，然后解决。
- 用户无需上下文切换。
- 自动修复失败的 CI 测试。

## Task Management（任务管理）

1. **先规划**：将计划写入 `docs/tasks/todo.md`，使用可勾选清单。
2. **验证计划**：实现前先 check-in。
3. **跟踪进度**：每完成一项即标记。
4. **解释变更**：每步提供高层总结。
5. **记录结果**：在 `docs/tasks/todo.md` 末尾添加 review 部分。
6. **捕捉教训**：纠正后更新 `docs/tasks/lessons.md`。

## Core Principles（核心原则）

- **简洁优先**：每次变更尽量简单，只影响最小代码。
- **绝不偷懒**：找到根因，不用临时修复，坚持资深开发者标准。
- **最小影响**：只修改必要部分，避免引入新 bug。

<br />

单个前端Vue代码或后端Django代码的行数不能超过600行，否则需要拆分组件或模块

## 600 行约束的适用面

这条从写下起只有散文，2026-10-27 起有机械 owner：判据内核 `scripts/line-limit.mjs`，
IO 壳与全仓断言 `frontend/test/unit/lineLimit.spec.ts`（T2 档，`cd frontend && npm run test:unit`，
约 0.6s、不开浏览器，**CI 的 vitest 步骤已经在跑它**）。以下为适用面界定，红字与豁免都以它为准。

- **计数对象**：`git ls-files '*.py' '*.ts' '*.vue'` 命中的**被跟踪**文件。未跟踪的、被 `.gitignore`
  掉的（含 `.venv/` 第三方包）一律不算——普查必须走 `git ls-files`，不走目录递归。
- **行数口径**：按 `\n` 切分后去掉末尾空串（末尾换行不算一行）。实测与 `wc -l` 在本仓 778 个
  in-scope 文件上**逐字相同**，所以 Windows 工作树（CRLF）与 Linux CI（LF）同值。
- **`.vue` 怎么数**：**整个文件**算一份，即 `<template>` + `<script>` + `<style>` 全部计数，
  不单独放行 style 块。理由（均为 2026-10-27 实测）：最大 style 块 273 行、最大 script 块 445 行、
  最大整文件 590 行——没有哪一块占大头，而「评审时要.scroll 的那个单位」就是 SFC 本身；
  改成只数 script 需要解析 SFC，那是新工具链，本条约束明确不为它引入。
- **测试文件覆盖在内**。这是本条最容易读漏的地方：2026-10-27 实测超阈的**全部**是测试文件
  （`apps/datafiles/tests.py` 1968、`frontend/e2e/data/view-data.spec.ts` 1802、
  `frontend/e2e/data/data.spec.ts` 1042、`apps/jobs/tests_jobs.py` 846、
  `test/backend/test_sftp_search_engine_stream.py` 642），业务代码 0 件。
  五件按**精确行数**冻在 `EXEMPT` 里：豁免只免到登记的那个数，**多一行即红**；
  真拆小或删掉了，必须同时把 `EXEMPT` 条目销掉（spec 里有反向断言拦陈旧豁免）。
  豁免理由写在 `EXEMPT` 每条的 `reason` 上，别在本文复制那份表。
- **不在适用面**：`*.js` / `*.mjs` / `*.cjs`（打包期与门禁工具，规则原文只点名「前端 Vue 代码」与
  「后端 Django 代码」）、`*.md` 与 `docs/**`。这条边界不是遮掩：上述类别 2026-10-27 实测 0 件超 600。
- **要豁免一个新文件**：往 `EXEMPT` 写精确行数 + 理由（哪一次工单、为什么不该由本闸拦当下改动）。
  只拆文件的工单与挂这条绊线是 `docs/tasks/todo.md`「留给拍板」第 6 条的两个取向，别混着做。
测试用的文件必须放在test目录下
非指南和Claude.md文件需要放在tasks目录下（临时脚本/日志），正式文档放在docs目录下
所有新完成开发或修改的功能都要添加或维护测试用例，但**先选层再写断言**：
**判据与门禁节奏的正文只有一份，在 `docs/reference/testing-gates.md`（入库跟踪）——必读，本文件不再维护正文。**
实现是 `scripts/affected-rules.mjs`，由 `frontend/test/unit/e2eAffectedDecide.spec.ts` 钉住，
所以**改分层判据/门禁阈值本身只需 `npx vitest run`，不许为此开一轮浏览器全量**。
设计 rationale 与存量普查在 `docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md`、`docs/reference/e2e-tier-triage.md`。

- 一句话口径（详见上面那份文档）：每批 commit 前 `npm run test:e2e:affected`；功能收口 / FF 并入本地 master 前
  `node scripts/e2e_pool.mjs --slots=4` + 后端全套；`NO AFFECTED TESTS` 不是绿灯；并行度只有 `--slots` 一个旋钮；跑完释放端口。
- **push 前一条命令**（§6.5 那四步的执行体，判据在 `scripts/prepush-history-check.mjs`、钉在 `prepushHistoryCheck.spec.ts`）：
  `node scripts/prepush-history-check.mjs` —— 打印本次会被带出去的提交清单与守卫根/密钥/`.gitignore` 漂移，末行 `RESULT:`。
  `githooks/pre-push` 只是载体，**装了才响，而「装」是仓库本地配置**（`git config core.hooksPath githooks`，换机器就没了）；
  想知道本机此刻到底会不会响：`node scripts/prepush-history-check.mjs --self-check`。别把「写了钩子」当「在跑门禁」。
- **本机实测值，不是通用结论**（本文件已入库，换机器先重跑下面这条命令再套用）：给服务选监听端口前先问临时端口区间 `netsh int ipv4 show dynamicport tcp`，本机是 **1024–15000**
  （非默认），slot 基址因此从 8101/3101 挪到 **21001/22001**，这是**端口卫生**；扫占用的正则必须 1–5 位
  （`\d{4}` 会漏掉五位端口，于是永远报「空闲」，两个池就会抢同一组口）。
  **别把这条当掉线的修法**：换基址后 slot 的 preview 照样掉，N=4 轮约半数会掉 1–2 个服务、掉完就成片
  `ERR_CONNECTION_REFUSED`，**真因未定**，别归因给端口。
- 后端套件的失败**不要默认归因给编码**：那条「不带 `PYTHONUTF8=1` 稳定假红 6 条」在 2026-10-16 已被本地 A/B 否证（详见 `docs/reference/testing-gates.md` §4）。
任何前端改动都要去维护两套主题：dark和light
