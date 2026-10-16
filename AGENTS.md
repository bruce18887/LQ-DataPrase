# 项目代理指令（AGENTS.md）

本项目由 Claude Code 与 DSH（DeepSeek Harness）两款代理协作，本文件是两款代理**都会在会话开始时自动加载**的入口文件。项目规则与教训的唯一事实来源仍是下列原始文件，本文件只负责把两款代理引向它们，不复制正文（避免双份漂移）。

## 会话开始必读（两款代理相同）

1. **`.claude/CLAUDE.md`** — 项目工作流规则与硬性约束（计划模式 / 子代理策略 / lessons 迭代 / 完成前验证 / 任务管理 / 600 行限制 / 双主题维护等）。**必须完整阅读并遵守**。⚠ 该文件所在目录**被 gitignore**，只对本机生效；其中凡是「入库正文另有唯一事实来源」的规则（目前是测试分层与门禁节奏），以入库那一份为准。
2. **`docs/reference/testing-gates.md`** — 测试分层（T1/T2/T3）与门禁节奏（批内 affected / 收口全量 / 夜跑 / CI）的**唯一事实来源**，入库跟踪。写新断言前先选层、提交前按它选验证档位；判据表的实现是 `scripts/affected-rules.mjs`（由 `frontend/test/unit/e2eAffectedDecide.spec.ts` 钉住，**改判据本身只需 vitest，不开浏览器**）。
3. **`docs/tasks/lessons.md`** — 历史教训库热区（R1–R8 + 近期日期条目，约 45KB，禁止整体内联进指令文件）；2026-07-02 及更早条目在 `docs/tasks/lessons-archive.md`，回查 grep 该文件。开始工作前先复习**文首「通用高频规则 R1–R8」**与最近几个日期条目，再动手；开发中遇到疑似踩过的坑先回查对应条目（先 grep 热区，再 grep 归档）。
4. **`docs/tasks/todo.md`** — 当前任务清单与进度（如存在）。

## 维护约定

- 规则正文只维护在 `.claude/CLAUDE.md`；**例外**：测试分层与门禁节奏维护在 `docs/reference/testing-gates.md`（入库，
  因为 `.claude/` 整目录被 gitignore，换机器或换代理就拿不到——那正是「每批都跑全量」这类行为反复出现的根因）。
  `CLAUDE.md` 里只保留指向它的入口 + 本机专属事实（如本机 TCP 动态端口区间）。
- 教训只追加到 `docs/tasks/lessons.md`。
- 本文件保持最小，仅做入口指引；如两款代理的行为出现分歧，以本文件声明的“原始文件为唯一事实来源”为准。
每个项目会话开始时先读该项目根 AGENTS.md / CLAUDE.md
