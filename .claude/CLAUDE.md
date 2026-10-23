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
测试用的文件必须放在test目录下
非指南和Claude.md文件需要放在tasks目录下（临时脚本/日志），正式文档放在docs目录下
所有新完成开发或修改的功能都要添加或维护测试用例，但**先选层再写断言**：
**判据与门禁节奏的正文只有一份，在 `docs/reference/testing-gates.md`（入库跟踪）——必读，本文件不再维护正文。**
实现是 `scripts/affected-rules.mjs`，由 `frontend/test/unit/e2eAffectedDecide.spec.ts` 钉住，
所以**改分层判据/门禁阈值本身只需 `npx vitest run`，不许为此开一轮浏览器全量**。
设计 rationale 与存量普查在 `docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md`、`docs/reference/e2e-tier-triage.md`。

- 一句话口径（详见上面那份文档）：每批 commit 前 `npm run test:e2e:affected`；功能收口 / FF 并入本地 master 前
  `node scripts/e2e_pool.mjs --slots=4` + 后端全套；`NO AFFECTED TESTS` 不是绿灯；并行度只有 `--slots` 一个旋钮；跑完释放端口。
- **本机实测值，不是通用结论**（本文件已入库，换机器先重跑下面这条命令再套用）：给服务选监听端口前先问临时端口区间 `netsh int ipv4 show dynamicport tcp`，本机是 **1024–15000**
  （非默认），slot 基址因此从 8101/3101 挪到 **21001/22001**，这是**端口卫生**；扫占用的正则必须 1–5 位
  （`\d{4}` 会漏掉五位端口，于是永远报「空闲」，两个池就会抢同一组口）。
  **别把这条当掉线的修法**：换基址后 slot 的 preview 照样掉，N=4 轮约半数会掉 1–2 个服务、掉完就成片
  `ERR_CONNECTION_REFUSED`，**真因未定**，别归因给端口。
- 后端套件的失败**不要默认归因给编码**：那条「不带 `PYTHONUTF8=1` 稳定假红 6 条」在 2026-10-16 已被本地 A/B 否证（详见 `docs/reference/testing-gates.md` §4）。
任何前端改动都要去维护两套主题：dark和light
