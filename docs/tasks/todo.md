# 任务：端口配置的定案（2026-10-27）

## 结论

**开发启动器（`scripts/dev.mjs` + `scripts/dev-launcher.mjs`）已实现后删除**，只保留它的接线部分。
用户定案的原话是「删壳留接线」。

## 为什么删

需求收敛后剩下两个真实场景，两个都不需要启动器：

1. 「单独启动后端，前端只提供网页」 —— `.venv\Scripts\python.exe standalone.py --host 127.0.0.1 --port 8124`
   一条命令就够。实测 `/` 200（`<title>LQ-DataPrase</title>` + `<div id="app">`）、`/dashboard` 200、
   `/api/v1/ready/` 200，一个进程。前提是 `frontend/dist` 存在（`config/settings/standalone.py` 非冻结时读它）。
2. 「旧方式双击 exe 直接拉起」 —— 现成的，Electron 自己 spawn `resources/LQ-DataPrase.exe --port 0`。

而启动器起的是 `manage.py runserver`（development 档），那份 settings 没注册 `frontend_dist`，
根路径实测 **500 `TemplateDoesNotExist: index.html`** —— 它天生服务不了场景 1。它唯一不可替代的价值
是那两处 Electron 常量的接线，所以留下接线、删掉壳。启动器剩下的便利价值只有「改代码要 HMR」那一档，
用户没选。

## 保留的改动

- `electron/backend.ts`：`DEV_BACKEND_PORT` 由 `const = 8000` 改为 `Number(process.env.E2E_PORT || 8000)`。
  改之前「自定义后端口 + Electron」这个组合是坏的（Electron 硬去 8000 找后端）。
- `electron/main.ts`：dev 渲染 URL 由写死 `'http://localhost:3000'` 改为读 `E2E_FRONTEND_PORT`，兜底 3000。
- `electron/load-failure.ts`：dev 分支的排查文案不再写死 `:3000`，改引用 `attemptedUrl`（实际试过的那个地址）。
- `frontend/test/unit/portWiring.spec.ts`：新增 T2，钉「四个读者读同一对变量名」+ 两处兜底值与
  `standalone.py` / `vite.config.ts` 的默认值同源 + Vite 是 `strictPort`（这条是同源的成立前提）。
- `README.md`：「单独启动后端」与「自定义端口」两节，含 `E2E_*` 用法、`electron:dev` 的 `wait-on 3000` 写死这个坑、
  `ELECTRON_DEV=true` 必须加、以及数据目录的真实落点。

## 顺带量到的两条本机事实（写进 README 了）

- `LQDP_BASE_DIR` 只是锚点（`secret.key` 在那），`data_dir` 由锚点下的 `system_config.json` 决定，
  没配则用内建默认 `~\LQ-DataPrase`（`apps/common/system_config.py` 的 `apply_system_config`）。
  仓库根的 `system_config.json` 指的也是这里 ⇒ **开发态与打包态共用同一个 `db.sqlite3`**，两个后端不要同开。
- `electron-builder.yml` 顶部注释称 user data 在 `%APPDATA%/lq-dataprase` —— 实测那目录只有 Chromium 的
  profile 件（`Cache/Local Storage/Preferences`），没有库也没有 `system_config.json`。**这条注释是过期的**，
  要不要顺手改由用户定（属于文档缺陷，不是行为缺陷）。

## 已随壳一起消失的两个缺陷（无需再修）

- `down` 的竞态假警：两条收摊路径抢跑时会把已消失的进程报成「收不掉，请手查」（实测端口其实干净）。
- 我给后端计划注入的 `PYTHONUTF8=1` 与仓库既有决定冲突：`electron/backend-env.ts` 明写「刻意不设
  PYTHONUTF8=1，治乱码用 `PYTHONIOENCODING=utf-8`」并由 `backendEnv.spec.ts` 钉住。壳删了这条就不存在了；
  **但「自己接管子进程 stdout 时会撞到 cp936 乱码」这个现象是真的**，日后任何 spawn Python 并读管道的代码
  都要按 `PYTHONIOENCODING=utf-8` 那套办。

## 我这次实跑的一个操作失误

第一次跑打包 exe 前没先确认 `data_dir` 的解析结果，于是它落到了与开发实例共用的那个库上，
两个后端挤同一个 SQLite 约 14 分钟。日志 0 条 Traceback/ERROR、无 `Applying` 迁移行、进程已收干净、
临时件已删。**教训是：起第二个后端前先问一句它用的是哪个库文件。**

## 待用户定

- 这批要不要提交（含 `README.md` / `electron/*` / 新 spec / `affected-rules.mjs` 的回退）。
- `electron-builder.yml` 那条过期注释改不改。
- WSL 里的 `lqdp` 还是 `inactive`（我为了腾 8000 停的）：`wsl -u root systemctl start lqdp` 恢复。

# 任务：前端性能审查与整改台账（2026-10-28）

12 个子代理逐行通读 `frontend/src`（242 文件 / 39,082 行）+ `electron/`（9 文件 / 1,801 行），
主控对每条承重断言现跑命令复核实。用户口径：P0 四批一路做完，**P1/P2 只出清单不动手**。

## 已做（四批，均在本地 master，未 push）

- `10bd373` 首屏：入口退出 586 个图标的全局注册 + 两套 ag-grid CSS 移到 3 个真实消费者 +
  分块改用 `output.codeSplitting.groups`+priority（函数式 manualChunks 把 Vue 并进了
  ag-grid-vendor，见 lessons 2026-10-28）。**首屏 2,994,611B → 1,483,213B（−50.4%）**，
  新绊线 `test/unit/firstScreenChunks.spec.ts` 带对照组（旧产物上为红）。
- `ed795a6` 交互风暴：`useChart` 渲染合并到帧（弃用 150ms 时间窗，见 lessons）+ 每次重建前
  `getOption()` 的全量深克隆改为 `legendselectchanged` 缓存 + ChartDock 行高拖拽改松手落盘 +
  `WaferMapPanel` 的 `Math.min(...vals)` 换 `minMax` 并从触发源删掉不读的 `zonalData`。
- `d1146dd` 大列表：新增 `constants/dropdown.ts` 的 `DROPDOWN_RENDER_CAP=300`，
  ParamSelector（删无效 `:virtual`，改「过滤→排序→截断→高亮」）、TestColumnSelector、
  ExportParamSelector 一律封顶 + 可见提示；`formatTime` 改 Intl 单例；FileSelect 高亮正则
  每次查询编译一次。
- `2ad4b9b` 正确性五条：重置密码（旧实现恒 400，从未成功过）、用户列表跟 `next` 取全
  （内核 `utils/paging.ts` + T2 5 例）、`SettingsPage` 三处浅拷贝污染模块级 defaults
  （+ 子组件不再就地改 props）、UPH 双请求收敛为页面单一持有、导出失败文案不再被吞。

每批提交前都跑了 affected 门禁（`docs/reference/testing-gates.md` §1）：全量档 78 文件，
四批分别 PASS 或「真红 0 · 负载抖动 2 · 悬而未决 0」；用例数 418 → 421（三条新 T3）。

## 待拍板：P1 结构性（本轮明确未动）

- **全仓 `src` 39,082 行里 `shallowRef` 出现 0 次**（`markRaw` 仅 7 处 / 2 文件）。大 payload
  走深度代理的靶点：`stores/weight.ts:7,31`（后端 1024 点/系列 × 2000 系列）、
  `pages/dashboard/DashboardPage.vue:136-142` + `batch/BatchYieldTab.vue:189`、
  `stores/sftpSearch.ts:127`、`pages/data/DataManagement.vue:114`（page_size 9999）。
- `layouts/MainLayout.vue:12` `keep-alive :max="10"` 而可缓存页面恰好 9 个 ⇒ 永不淘汰；
  `composables/useChart.ts:296` 的 window resize 只在 `onUnmounted` 摘（keep-alive 走
  deactivated）⇒ 每进过一次图表页永久 +1 监听，且与 :220-254 的 ResizeObserver 双轨。
- `pages/data/DataBrowserAgGrid.vue:495` 每加载一块都跑 `applyMeta`，:512-513 无条件整体
  替换 `allCols/colMeta` ⇒ 千列文件的列定义随滚动反复重建（`browserColumns.ts:94-99` 的
  `.includes` 线性查找同批可换 Set）。
- `components/layout/Sidebar.vue:138` `transition: width` 逐帧重排整棵内容树；
  `styles/element-plus-theme.css:772-855` 四处 `backdrop-filter blur(14px)` 覆盖
  dialog/message-box/drawer/message。
- dashboard 多卡在 keep-alive 下 `onActivated` 里 dispose+重 init
  （`SiteYieldAnalysis.vue:192`、`YieldTrendChart.vue:132`、`BinSiteCrossTable.vue:288`），
  深 watch 白扫整棵数据树（`BatchBinSection.vue:134`、`BinSiteCrossTable.vue:273`），
  4 个图表各自手写 init/resize/dispose 而未迁 `useChart`。
- API 层：`api/datafiles.ts:175` 等不收 `AxiosRequestConfig` ⇒ 最热端点不可 abort
  （`DataBrowserAgGrid.vue:480-494` 只有 seq 守卫，丢弃响应但服务端照样算完）；
  `api/auth.ts:152` refresh 走裸 axios 无超时（挂起会让 `refreshPromise` 永不 settle）；
  `api/jobs.ts:54` 轮询失败弹两条 toast；`utils/ssePost.ts:60-76` 异常路径不 cancel 流。
- SFTP：`pages/sftp/components/SftpFileTable.vue:3-11` + `SftpBrowser.vue:327` 大目录整表
  渲染，后端 `apps/sftp/views.py:226-251` 无返回上限 ⇒ 要拍的是「后端封顶+truncated 标志」
  还是「el-table-v2 虚拟滚动」，两条都是语义变更，未擅自动。
- Electron：`backend.ts:77-92` 与 `main.ts:100-115` 各 monkey-patch 一次 console ⇒ 一行日志
  两次同步 `appendFileSync`；`main.ts:585-590` 的 `before-quit` 不 await async ⇒ 可留孤儿
  python（全目录无 `will-quit`/`uncaughtException` 兜底）。

## 待拍板：P2 死代码（零行为变更，纯减法）

- 整文件零引用：`pages/data/FileManager.vue`(545)、`dashboard/components/batch/AggregatedBinChart.vue`(83)、
  `components/common/BinTag.vue`(70)、`constants/icons.ts`(27)、`theme/spacing.ts`(21)。
- 死导出：`api/datafiles.ts:178 history()`、`api/auth.ts:161 updateProfile()`、
  `api/jobs.ts:72 cancelJob()`、`utils/sftpTimeout.ts:43`、`utils/batchAggregation.ts:189 aggregateUph`、
  `stores/sftpSearch.ts:375 apply/finalize`、`pages/data/composables/useRowHighlight.ts:13`；
  `utils/echarts-init.ts:87,157,166,178` 的 `cleanup` 数组只 push 从不执行。
- 重复实现：`utils/exportTimeout.ts:20-23` / `utils/sftpTimeout.ts:20-23` / `utils/filenameWrap.ts:26`
  三份同构 clamp/ensure。`style.css:19` 与 `:44-46` 同规则写两遍；
  `components/layout/Topbar.vue:107-108` 两个永不写入的 ref；
  `components/common/index.ts` + `README.md` 整体过期且无人 import。

## 待拍板：Element Plus 按需（我量完天花板后主动停手）

- 现状：首屏 1,483,213B 里 element-vendor JS 896,954B + CSS 356,008B（占 84%）。
- 实测上限：EP chunk 的源码字节里「src 未用到的组件目录」约 **27%**（1,061,823B 里
  `date-picker-panel`143,560 + `time-picker`77,227 是 `el-date-picker` 的传递依赖，删不掉），
  `theme-chalk` 单组件 css 合计 773,761B 而用到的只占 26% ⇒ 按需的净收益约 **400–550KB（~30%）**。
- 为什么停：**验证是瓶颈，不是实现**。本仓 `toHaveScreenshot` 只有 2 处（`dashboard-loading.spec.ts`、
  `global/type-snapshot.spec.ts`），而按需的风险面恰恰是「漏了某个组件的 style 入口 ⇒ 弹层/滚动条/
  过渡态样式缺失」——这些要**交互态开着**才看得见，`tsconfig.app.json:5` 没引 `element-plus/global`
  且 `strictTemplates` 关 ⇒ 漏注册在类型层不可见。
- 建议顺序：先补一层「关键交互态 × 双主题」的截图回归（dialog/dropdown/popover/table/loading 各一），
  再单独开工按需，配一条 T2 绊线枚举 src 里全部 `el-*` 标签 ⊆ 注册清单。要我做第 1 步请点名。
# 任务：账号角色收敛与操作审计（2026-11-09）

## 边界

- 本批 14 笔提交（`126ee48` viewer 归并内核 … `da63bac` 教训与计划回写）现在都在**本地 `master`** 上；过程分支 `feat/account-role-audit` 已删（合并方式见下面「并入 master」一节）。**全程未 push**：`origin` 是公开仓库，一次 push 即全球发布——本批确实误发过一次并已撤回，也记在那一节。
- 只动账号 / 审计面。数据面零改动；真实 dev 库 `~/LQ-DataPrase/db.sqlite3` 收口实测 mtime 仍是本轮开跑之前的值，e2e 与 T1 都落在 `test/e2e-data` / `test/unit-data` / 各 slot 目录。
- `docs/user-guide/**` 整目录被 `.gitignore:170` 忽略 ⇒ Task 13 的用户指南同步只能本机生效，无入库文件可提。
- 本节原先按 Task 14 Step 6 的约定「只本机追加、不提交」（当时 todo.md 里压着另一会话 396 行未提交正文，`git add` 会把别人的正文一起带进来）。后来那一坨被它自己提交走了，本批收尾又并进了 master，所以这条约定作废：现在这节是**随本批一起入库**的，且只含本节自己的正文。

## 各批（每批收口都跑 affected 门禁，判据来自 `docs/reference/testing-gates.md`）

- [x] **Task 1** `126ee48`：`apps/accounts/role_migration.py` 归并内核 + `0012_normalize_user_roles`（三类计数任一非零必出声，文案刻意 ASCII —— cp1252 下中文 print 会在迁移事务里趴下，判据 `test_role_normalization.MigrationPrintCodepageTests`）。
- [x] **Task 2** `2f636a8`：`apps/accounts/permissions.py` 收敛为五项 + `role_can`；未列出的功能名一律拒绝（fail closed）。
- [x] **Task 3** `4813aa2`：`role` choices 去掉 viewer，后端引用与 `seed_users` 同步。
- [x] **Task 4** `caf4aac`：前端角色标签 / 部署探针去 viewer，`README` 与 `docs/reference/server-deployment.md` 两级。
- [x] **Task 5** `2edc632`：`AuditEvent` 模型 + `apps/accounts/audit.py` best-effort 写入器（外层已在事务里时走 savepoint）。
- [x] **Task 6** `1ad0182`：登录写 `last_login` 并记 `login_success` / `login_failure` / `account_locked`。
- [x] **Task 7** `9d56163`：账号 CRUD / 重置 / 解锁 / 改密 + 存储路径变更写审计，detail 走白名单（绝不含口令）。
- [x] **Task 8** `ca09a53`：只读查询端点 `/api/v1/auth/audit-events/`，按项目时区取整日边界，参数错误走统一信封。
- [x] **Task 9** `cad0540`：`frontend/src/utils/audit.ts` 纯函数 + `test/unit/audit.spec.ts` 与后端源码的双向绊线（事件码 / 两个分页数 / username 列宽 / 查询参数名）。
- [x] **Task 10** `9f169f0`：用户管理编辑弹窗（用户名只读、角色两级、走 partial PUT 不冲洗启用态）；顺带修掉后端 `/auth/users/` 的**无序分页**（`views.py` 补 `.order_by('id')`，判据 `test/backend/test_user_list_pagination.py`）与清理脚本误杀兄弟 worker 活账号的 flaky（`mine` 登记 + `Date.now()` 年龄闸）。
- [x] **Task 11** `d5666f8`：`/admin/audit` 页（筛选 + 倒序分页 + 展开行原始 JSON）、`requiresAdmin` 守卫与侧栏入口；失败与空态分开写；可空性收进纯层契约；两个格式化器搬进 `utils/audit.ts`，判据新建 `test/unit/auditFormat.spec.ts`。
- [x] **Task 12** `ae43c3b`：`frontend/e2e/admin/admin.spec.ts` 直达用例改断守卫**最终**落点（旧断言抢在 `fetchProfile` 往返之前匹配，钉的是假事实），文件头那段「没有任何基于角色的拦截」与 `.hidden(display:none)` 一并作废。
- [x] **Task 13**（本机生效）：`docs/user-guide/README.md` / `01-quickstart.md` / `08-admin.md` 去 viewer，权限矩阵重写为两级并**逐条对齐** `apps/accounts/permissions.py`（旧表把「删除数据文件」写成 user ✅(自己的)，与代码里的 `data_delete: ['administrator']` 不符）；新增「编辑账号」「操作审计」两节；`npm run build` 后 `dist/` 三份 HTML 的 `grep -c viewer` 全为 0，顺带补齐原先落后的 3 份 `dist/reference/*.html`。

## 收口（判据来自 `docs/reference/testing-gates.md`，每条都是可复制的原始输出行）

- **后端全量**：`CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test` ⇒ `Ran 2477 tests in 529.203s` / `OK (skipped=8)`，整段落盘在 `tasks/t14-backend-full.log`，`grep -cE "^(FAIL|ERROR):"` = **0**。（计划稿 §Step 1 写的 1652 是上一轮基线，本批只增不减：2477。）
- **T2**：`npx vitest run` ⇒ `Test Files  58 passed (58)` / `Tests  802 passed (802)`（Task 10 收口是 57 / 780）。
- **前端构建与 e2e 类型档**：`npm run build`（含 `vue-tsc -b`）⇒ `✓ built in 810ms`；`npm run lint:e2e` ⇒ 静默通过（exit 0）。
- **全量池（收口那一轮）**：runId `063322-34872`，4 slot ⇒ `[pool] 用例 438 · 墙钟 8.7min · 单价 3.14s/例 · 效率 2.50（目标 ≥2.8） · unexpected 0 · flaky 1 · skipped 21` + `[pool] 结论 MEASURED`，affected 门禁末行 `RESULT:   PASS · 计划 3 档全部执行`。**没有 VOID**。
  - 口径要说清：这一轮跑在 14:33–14:42，树里已经是 Task 11 + Task 12 的**最终字节**（两笔提交只是把同样的内容记进历史），此后只动过 `docs/`（计划、lessons、本台账）⇒ 直接当收口轮的 e2e 结论用，不再重跑一遍同样的东西（核对方式：`git diff --stat ae43c3b da63bac` 只有 `lessons.md` 9 行 + 计划文档 27 行，代码零改动）。
  - `flaky 1` 是 `e2e/data/view-data.spec.ts:1393 › @p2 顶部带：操作按钮在文件横幅内，表格高度与实测占位对齐`（首跑失败、retry #1 过）。本批没碰过 `e2e/data/` 与该页任何组件，形状与 lessons 里「dev server 长时间运行后劣化」同族 ⇒ 判为存量抖动，不因此调重试或跳过。
- **手工验收**：spec §13 七条逐条现量 + light/night 双主题计算值对照，记录在计划 Task 14 Step 3.5。核心几条：登录后审计页倒序第一行就是那次 `登录成功`（14:56:53，`Total 2564`）；按事件筛 `login_failure` 得 43 行且事件列全是中文；展开行给 `{"reason": "unknown_user"}` 原文；倒置日期区间 ⇒ 400 + 空态说「审计记录加载失败，请调整条件后重试」而**不是**「暂无符合条件的审计记录」，三个输入框的值全保留。
- **升级路径**：历史 viewer 的**副本**上 `migrate` ⇒ `[0012] role normalization: {'viewer_to_administrator': 0, 'viewer_to_user': 1, 'superuser_promoted': 0}`，终态 `viewer rows left: 0`；`seed_users` 之后仍是 `administrator 1 / user 2`。源库未被写过：`test/e2e-data/db.sqlite3` 角色分布不变，`~/LQ-DataPrase/db.sqlite3` mtime 仍是本轮开跑前的值。
- **未 push**：`git log --oneline master..HEAD` 共 12 笔（`126ee48` … `ae43c3b`），全部只在本地分支 `feat/account-role-audit`。


## 并入 master 与一次误推（2026-11-10 收口之后）

- **误推**：界面上点错了，本批那条分支被 push 到公开 origin（`git ls-remote origin` 当时真有 `refs/heads/feat/account-role-audit = 293e022`，本地 reflog 记 `update by push`）。处置按既有口径**只删远端引用**：`git push origin --delete feat/account-role-audit` ⇒ `- [deleted]`，复看远端只剩 `refs/heads/master a02be88` 与历史遗留的 `refs/pull/1/head`；顺带 `git branch --unset-upstream` 清掉悬空跟踪，免得一句普通 `git push` 把公开分支原地重建。诚实记一句：那条引用公开挂过几分钟，删引用只是关掉入口，不保证已缓存/被抓取的副本同步消失。
- **合并**：`master` 是分支尖的祖先（`git rev-list --count HEAD..master` = 0），所以是纯快进，`git merge-base` 与 tree 双向核过：合并前后 `master^{tree}` == 分支 `^{tree}` == `71f37d32baaebf6be7a39f819ce3e1c6f40cd9e7` ⇒ 上面那三档收口证据原样覆盖合并结果，不重跑。
- **一处故意偏离仓里既有手续**：没走 `git checkout master && git merge --ff-only`，改用 `git branch -f master <sha>`。原因是这是**共享工作树**，另一会话正在同一条分支上提交（`293e022` 就是它刚落的），切 HEAD 会把它下一笔提交静悄悄送进 master。
- **排除与安置**：按用户点名，master 最终指 `da63bac`（本批自己的尖），不带那会话的 `293e022`（Site 山脊图规范 137 行 + 它自己的 todo 正文 396 行）。`git branch -d` 先按预期拒了一次（`not fully merged`），留 `backup/other-session-293e022` 之后才 `-D` 删分支。回退点：`backup/master-3392781`（合并前的 master）。
- **一条连带教训**：那笔 `293e022` 提交时把本节**当时还未提交**的台账正文一起卷走了（+451 行 = 它的 396 + 本节 ~55）。所以排除它也等于把本节从磁盘抹掉，`git status` 干净这件事完全看不出这层耦合 —— 台账正文当时逐字留在 `tasks/t14-todo-entry.md` 才没真丢。**规则**：共享工作树里判断「谁拥有什么」不能只看 `git status`，未提交的追加段落会被别人的 `git add` 顺走；要么当场提交自己的，要么别把正文只留在工作树。

## 明确不做

- 跨用户文件共享与「真正只读 viewer」（spec §14）—— 删掉 viewer 的代价就是这条：没有跨用户数据共享的产品里，viewer 只剩「不能上传」这一条与 user 不同，不值得第三份角色语义。
- 数据操作级审计（上传 / 删单文件 / SFTP 下载）、邮件自助找回密码、MFA/SSO、Django Groups、TLS/CORS 整改、审计日志自动过期与批量删除 UI（均 spec §14）。
- 删除用户时清理磁盘上传目录与作业产物 —— 现状「删除用户不会删除该用户上传的数据文件」仍是产品事实，用户指南里明写着。
- 审计写入的「必须成功」语义：`audit.record()` 仍是 best-effort（外层提交时抛出的 IntegrityError 罩不住），已接受的取舍见 `apps/accounts/audit.py` 的 `_live` 注释。

## 遗留（交给下一轮，别当已解决）

- `setup` 项目 `PUT /api/v1/auth/settings/` 的 500：三次目击（Task 10 两次、Task 12 一次），**同一轮 4-slot 池跑里 `Internal Server Error` 计数为 0** ⇒ 方向是「单文件直跑的 webServer 通路」，不是池。未归因，两条候选（SQLite deferred-transaction 写死锁 / 别的）都别照抄，拿到 traceback 再判。
- `:deep(.el-select .el-input__wrapper)` 这条恒不命中的死规则仍在 `frontend/src/pages/admin/UserManagement.vue:555` 与 `frontend/src/styles/element-plus-theme.css:598`；且**主题一致性本身没有自动化判据**（Task 11 变异表 C 记：删掉那条生效规则，vitest 与 e2e 全绿）。
- **night 下审计页筛选行的控件底色是分叉的**（Task 14 手工验收现量）：日期/账号框走全局 night 的 `rgba(255,255,255,.05)`（叠在卡片 `rgb(22,33,62)` 上合成 ≈ `rgb(34,44,72)`），事件下拉走 scoped 的 `var(--bg)` = `rgb(26,26,46)`。根因是特异度账（全局 `:root[data-theme="night"] .el-input__wrapper` (0,3,0) 压过 scoped (0,2,0)），修法属于「night/light 块对称」那一批全局收敛，不在本批扩面 —— 详见 Task 11 Step 4.5 第 6 条的订正段。
- **审计页没有 URL 状态**：筛选条件只活在组件里，刷新/粘贴链接都回默认视图，也没法把一次取证结果分享给另一个管理员。spec 没要求，本轮按现状交付；要做要先定「query 参数与 `buildAuditQuery` 谁 owns 形状」。
- `frontend/.vitest`（vitest 缓存目录）没被任何忽略规则覆盖：`.gitignore` 与 `frontend/.gitignore` 里 `grep -n vitest` 均 0 命中。本轮该目录不存在，所以只是记一笔——一旦出现就会以未跟踪文件的形式混进 `git status`。
- `apps/accounts/views.py` 的 `perform_create` 非原子（建号成功而审计行失败时不回滚）。
- 自我降级那条 `fetchProfile` 分支目前无法被任何判据覆盖（拿不到可观察差异）。
- `docs/tasks/todo.md:335` 那句「另核清 `last_login` 从来没人写」是 D2 那批的现量，Task 6 之后**不再成立**（现在登录会写）。该行属于历史评审稿，本批不就地改——改别人的历史结论要单独点名。

# 任务：部署入口 TLS 终结（方案2，2026-11-11）

runbook：`docs/reference/deployment-tls-termination-runbook-2026-11-11.md`；取证：`deployment-http-method-block-forensics-2026-11-11.md` §9.7 方案2。分支 `feat/tls-proxy-support`。根因：公网入口认证网关按方法拦 PUT/DELETE，TLS 终结让写请求以密文穿过。

- [x] Task1 代码适配：base.py `SECURE_PROXY_SSL_HEADER` + audit `_client_ip` 取 XFF 最右 + 6 测试（提交 `04f4515`，spec/质量双复审通过）
- [x] Task2 服务器 base.py 外科插入（区块 sha256 与本地逐字节一致；服务器落后 86 提交、audit.py 不存在 ⇒ 只插 base.py 一行）
- [x] Task4 自签证书（IP SAN 三地址，10 年，key 600，RSA2048，配对一致）
- [x] Task5 nginx TLS server 块（8124 ssl → 127.0.0.1:18000，全文哈希一致，nginx -t 通过）
- [x] Task6 Django 换绑回环（start_backend.sh 18000 127.0.0.1，PPID=1 脱离会话，env 保留，health 200）
- [x] Task7 nginx reload 接管 8124（reload 非 restart，tplms/discuzq 零回归）
- [x] Task8 验收 + 回写取证 §8（已提交）

## review

- 门禁：lint:e2e / vitest / e2e 全量（438 例 unexpected 0）ok；backend 首跑 1 红 `test_sftp_host_keys::test_forget_removes_entry`，单文件 17 绿 + 原命令全套 1753 复跑 OK ⇒ 判既有顺序抖动（与本批无调用交集）。证据 `tasks/tls-task1-gate.log` + `tls-task1-backend-rerun.log`。
- **验收全绿（三方一致：本地真实客户端 + 服务器 hairpin + 独立复审）**：公网 PUT/DELETE 探针 → Django 形状 404（不再 RST；明文 PUT 仍 RST 作对照，公网与上游 Content-Length 恒差 5=URL 前缀差）；`PUT /auth/settings/`、`PUT /auth/profile/` 均 200；分页 `next=https://<公网host:port>/api/v1/files/?page=2…`；浏览器（ignoreHTTPSErrors）登录→/dashboard→/analysis（自动加载文件）→勾 QQ 图 PUT 200→**刷新勾选保留**→还原，全程 consoleErrors/reqFailed 均空。管理端 CRUD/审计 IP 跳过（账号 role=user、审计未部署）。
- 质量复审 Minor 未做项已记 runbook「已知边界」与「公网安全 follow-up」：`::ffff:127.0.0.1` 映射形态、server.py 文件头描述过时、DRF 节流 XFF 既有行为、DEBUG=True+匿名文档/admin 暴露（切 server 档）、nginx 可选硬化（均另立工单）。
- 仓库卫生：根目录 `ssh.txt`（含凭据）已按用户指示加入 `.gitignore`（Secrets 段），origin PUBLIC 误 push 风险解除；本批已本地 FF 并入 master（**未 push**）。
- 取证文档 §8 收口提交同时带入上一会话未提交的 §9 服务器侧取证正文（同主题、已完整）。

# 任务：服务器整体升级 a02be88 → 4bb5bcd（92 提交，方案待拍板，2026-11-11）

前置事实：本地 92 提交已于 2026-11-11 push 到 origin（prepush-history-check RESULT: PASS，上一批台账「未 push」状态就此失效）。
服务器 git ls-remote 直连 GitHub 可达 ⇒ 走 git pull，不需要 rsync 源码。

## 事实基线（2026-11-11 全部现测）

- 服务器 bpsemi-CD：`ssh -i ~/.ssh/lq_windows bpsemi@100.121.94.114`；仓库 `/home/bpsemi/project/LQ_DataPrase`，master@a02be88（10-28），是本地 HEAD 直接祖先，FF 无分叉。
- 运行形态：`start_backend.sh 18000 127.0.0.1`（runserver **带 autoreload**，PPID=1）；`DJANGO_SETTINGS_MODULE=tasks.dev_spa`、`DJANGO_DEBUG=True`；nginx 8124 TLS → 127.0.0.1:18000，公网 125.69.67.169:18124。**不是 systemd 方案 A**，server-deployment.md §8 的 systemctl 命令不适用，按本条目执行。
- 数据库：`/home/bpsemi/LQ-DataPrase/db.sqlite3`（WAL，-shm/-wal 在）；media 同目录；无 system_config.json（默认 data_dir）。
- Python 3.13.17；**无 Node** ⇒ 前端在开发机构建传 dist。requirements 无变更 ⇒ 不动 pip；package.json 仅 +echarts-gl（本地 dist 已含）。
- 服务器漂移：`base.py` 仅 TLS 外科区块（与本地 04f4515 逐字一致，已核对）；`playwright.config.ts` 为 PW_CHANNEL Linux 适配（92 提交未触碰该文件 ⇒ stash pop 无冲突）；未跟踪 start_backend.sh/.bat、base.py.bak-tls 保留。
- 新增迁移 3 条：accounts 0012 角色归并（**不可逆**，reverse=no_op；服务器现有 1 个 viewer 账号将归并为 user）、0013 choices 收敛、0014 AuditEvent 表。
- 本地 dist 新鲜：构建 11-11 12:51 晚于最后前端源码变更 d5666f8（11-10 14:43）；web 构建绝对路径、57 assets、含 AuditLogPage/Site3DChart。服务器 dist 是 11-05 旧构建（52 assets，无审计页/3D）。
- 账号：21 个，admin=administrator/superuser；**zhuliqun 是 role=user** ⇒ 审计页验收需 admin 凭据（用户提供或用户自验）。

## 步骤（单一维护窗口，预计 2–5 分钟；停→升→起在同一 SSH 会话背靠背）

- [ ] 0 预检：health 200；`manage.py shell` 打印 DATABASES NAME 确认库路径；记录 runserver 父子 PID；当日再核 base.py 漂移仍只有 TLS 区块
- [ ] 1 备份：`DJANGO_SETTINGS_MODULE=tasks.dev_spa .venv/bin/python manage.py backup_db --dest ~/lqdp-backup`（VACUUM INTO，WAL 安全）；`tar czf ~/dist-backup-a02be88.tar.gz -C frontend dist`
- [ ] 2 停后端：kill runserver 父进程，确认 18000 释放（先停再拉代码，避开 autoreload 的「新代码+旧 schema」窗口）
- [ ] 3 解漂移：`git checkout -- config/settings/base.py`（TLS 区块由 04f4515 原样带回，.bak-tls 仍在）；`git stash push -m "pw-channel-linux" -- frontend/playwright.config.ts`
- [ ] 4 更新：`git fetch origin && git merge --ff-only origin/master`（a02be88→4bb5bcd）；`git stash pop`（恢复 PW_CHANNEL 适配）
- [ ] 5 迁移：`DJANGO_SETTINGS_MODULE=tasks.dev_spa .venv/bin/python manage.py migrate`（0012 会打印 role counts；showmigrations 确认 0012/0013/0014 已应用）
- [ ] 6 传 dist：开发机 `tar czf dist.tar.gz -C frontend dist` → scp → 服务器解包覆盖 frontend/dist；两侧 index.html sha256 一致
- [ ] 7 起后端：`nohup ./start_backend.sh 18000 127.0.0.1 >> ~/lqdp-backend.log 2>&1 &`（脚本自动选 dev_spa）；health 200
- [ ] 8 验收：服务器本地 `/` 200 且 index 哈希=新、`/pages/analysis` 200；公网 https 登录（zhuliqun）→ PUT /auth/settings/ 200 → 分页 next=https；viewer 账号 role=user（0012 生效）；tplms/discuzq :80 回归 200；审计页 /admin/audit 与 3D 站点柱阵按凭据/数据可得性验（缺则显式记跳过）
- [ ] 9 回写：本条目收口 + review；有新教训追 lessons

## 回滚

- 代码层：`git checkout a02be88` + 解开 dist 备份 + 重启；**base.py 需从 base.py.bak-tls 恢复 TLS 区块**（a02be88 没有该行，丢了会致 https 入口分页 next 变 http）。
- 数据层：0012 不可逆 ⇒ 需停服后用步骤 1 备份恢复 db.sqlite3（连同 -wal/-shm 一起处置），再起服务。

## 明确不做（另立工单，勿夹带）

- 切 server 档（DEBUG=False）：已知 follow-up；会牵动 SFTP 存密 KDF 差异（re-key 未解决），本次保持 dev_spa 原档。
- nginx 硬化 / 限流 XFF / systemd 化（方案 A）/ 服务器装 Node：均不在本次范围。

## 已知边界

- 自签证书：浏览器验收需 ignoreHTTPSErrors（同上批）。
- 0012 归并 viewer 是已批准决策的产品行为，不是事故；升级后该账号以 user 身份登录。
- 服务器 media 无自动回收（既有约束），升级不改变磁盘累积趋势。

## review（2026-11-11 升级收口）

- **执行形态修正**：用户提示「可能已执行了一些」→ 现查证实整套升级**已由先前执行完成**（HEAD=4bb5bcd、0012–0014 已应用、dist 哈希与本地一致、后端 15:27 已重启、DB 备份 15:24、旧 dist 留档 `dist.old-a02be88`、.bak-tls 在位）。本轮只做核证 + 验收，未重跑任何已完成步骤。
- **验收全绿（实测证据）**：公网 https `/` 200（新 index 1707B）、`/pages/analysis` 200；admin/zlq0104. 登录 OK；`GET/PUT /auth/settings/` 200 且写入生效；审计端点分页 `next=https://…`；审计 API 200 + 页面 13 条事件（真实 XFF IP、失败行带 reason）；viewer 归并：角色计数 0、原 viewer 账号 role=user；分析页 1017 列含 `Site_No`，勾选「显示3D柱状图」→ 真数据渲染（Site3 × 26 bins，console 零错误、同页 API 全 200）；用户管理页 21 账号 + 编辑/重置/启停入口在线；tplms `:80`、discuzq `:18081` 均 200 零回归。
- **发现并修复缺陷（本批新页面）**：`/admin/users`、`/admin/audit` 深链/刷新被 Django admin catch-all 302 到 `/admin/login/`（侧栏客户端路由正常）。修法：`config/urls.py` 在 admin 挂载前把两条精确路径交给 SPA（commit `0d4067c`），T1 新增 3 例（含「/admin/ 仍归 admin」对照组），RED 302→GREEN。门禁 4 档 PASS：lint / vitest / backend 1704 例 OK / e2e 438 例 unexpected 0。**该修复尚未部署**（服务器仍是 4bb5bcd）：待 push 后做第二轮小升级 = `git pull --ff-only` + 重启（无迁移、无 dist 重建）。
- **已知不拦收口**：Topbar 版本按钮 aria-label 含未插值的 `{{ APP_VERSION }}`（可见文本正常 v0.8.0，仅无障碍名；既有缺陷，非本批引入，另记）。
- 升级形态仍是 dev_spa 档（DEBUG=True、无 systemd）——切 server 档与 nginx 硬化维持既有 follow-up 工单，本批不夹带。

## review 追加（修复部署，2026-11-11）

- **已 push + 已部署**：`4bb5bcd..154205c` 推到 origin 后，服务器 `git pull --ff-only` + 背靠背重启（**无迁移、无 dist 重建**，中断约半分钟），服务器 HEAD=`154205c`，health 200。
- **部署后复验（公网 https）**：`/admin/users`、`/admin/audit` 整页加载均 200（1707B = SPA 外壳）；`/admin/` 仍 302 到 admin 登录（对照组不变）；浏览器**整页刷新**两页均正常渲染（用户管理 21 账号 + 编辑/添加表单、审计页 20 条事件）。修复闭环。

# 任务：开发垃圾统一回收器（扩展 test_data_gc.py，2026-11-11）

背景：只读盘点实测当前可回收 ≈6.3GB（测试槽 5GB + 构建产物 1GB + tasks 草稿 133M + 缓存 37M + Electron profile 缓存 474M）。现有 `scripts/test_data_gc.py` 只覆盖 3 棵测试树、无触发机制（18 天内槽从 1.1GB 涨回 5GB，这是垃圾反复堆积的根因）。用户拍板：**统一工具·手动触发**（不挂 cron）。

设计：复用现有护栏管线（dry-run 默认 / 白名单 / 真实数据禁区 / 龄限守卫 / inode 去重），泛化成分类回收器。新增类别 `artifacts`/`caches`/`scratch`/`electron`(opt-in)。新增「被 git 跟踪的文件绝不删」守卫。**600 行硬约束**：实施中引擎与测试都触顶，已拆出 `scripts/gc_categories.py`（纯注册表+选择器，166 行）与 `test/backend/test_gc_categories.py`（96 行），引擎测试加载器把 `scripts/` 加进 sys.path 解析 sibling import。终态四文件行数：引擎 468 / 注册表 166 / 引擎测试 537 / 注册表测试 96，均 < 600。

## TDD 清单（先红后绿，全在临时目录，绝不指真实根）

- [x] C1 `self` 模式 + DataRoot 扩字段（category/keep/age_guard）：整目录成候选、保护区拒绝、正对照（合法路径必须放行）
- [x] C2 `artifacts` 注册表：out/dist/build/frontend-dist/electron-dist 进候选（可再生，无龄限）
- [x] C3 `caches`：显式缓存目录 + `__pycache__` 递归发现（pycache 模式），不碰 node_modules/.venv 本体
- [x] C4 `scratch`：tasks/* 龄限 + 保 LATEST.md/latest.json/最新轮；根 db 备份（glob）；probe.local；空 worktree 残壳
- [x] C5 跟踪文件守卫：候选自身或内含被跟踪文件则拒绝（LATEST.md 承重断言：跑完 --apply 仍在）
- [x] C6 `electron`(opt-in)：只清白名单缓存子目录，media/secret.key/Local Storage 跑完 --apply 仍原样
- [x] C7 CLI：`--only` 接受类别名 / `--all` 含 electron / 默认不含 electron；报告按类别分组
- [x] C8 npm `clean` / `clean:apply`（根 package.json，cross-env PYTHONUTF8=1 + .venv python）
- [x] C9 文档：testing-gates.md §1 回收段（「自动触发待拍板」→「统一手动回收入口」）+ 脚本 docstring
- [x] 收口：后端全套 + 600 行判据（lineLimit.spec.ts）+ 现跑 du 交叉核对体积

## 收口验证（2026-11-11，全绿）

- 回收器套件 `test.backend.test_test_data_gc test.backend.test_gc_categories`：`Ran 39 … OK (skipped=1)`（skip 是 Windows 目录联接需特权那条，交真机）。
- 后端全套 `manage.py test test.backend apps.<12 个目录>`：`Ran 2509 … OK (skipped=11)` / 714.8s（日志末尾 verdict 为准，非 exit code）。
- T2 `npm run test:unit`（在 frontend/）：`58 文件 / 802 例 OK`，含 `lineLimit.spec.ts` 15 例 ⇒ 四文件均 < 600 行得证。
- 现跑 dry-run `npm run clean`：四类分组（test-data/artifacts/caches/scratch），electron 默认不含；合计「删完即掉」**6387.1MB**。slots 表观 22904.1M → 唯一 4440.8M（硬链接去重），2 轮在跑被龄限挡下。
- du 交叉核对：`du -sh C:\lqdp-e2e\slots` = 4.4G ≈ 唯一 4440.8M。**du 连 `--apparent-size` 也按 inode 去重**，核对的是「唯一」不是表观 22.4G（已把这条口径写进 testing-gates.md §1）。
- electron opt-in `--only electron`：只注册 6 个白名单 Chromium 缓存子目录（433.2MB），media/secret.key/Local Storage/Network 一律不进候选。
- 跟踪守卫承重核对：`git ls-files tasks/` 仅 `tasks/e2e-nightly/LATEST.md` 一条（keep + 跟踪双重保护）；`db.sqlite3.bak*` glob 只命中 3.3M 备份，活库 `db.sqlite3` 永不成候选。

## 禁区（绝不自动碰）

`~/LQ-DataPrase`、`Data/`、`C:\lqdp-e2e\template`、Electron profile 的 media/secret.key/Local Storage/Preferences、node_modules/.venv 本体、任何被 git 跟踪的文件。

# 任务：圈选子图四点跟进改动（2026-11-12）

计划：`docs/superpowers/plans/2026-11-12-subset-followup.md`（SDD 子代理驱动，台账在
`.superpowers/sdd/2026-11-12-subset-followup/progress.md`，gitignored）。
Spec：`docs/superpowers/specs/2026-11-11-chart-region-subset-design.md`（四处决策经用户批准反转，
修订节已由 Task 6 写回：「修订（2026-11-12）」）。

- [x] Task 1 后端 value_range 选区固化 serials（selection_serials/selection_serial_col，T1 TDD）
- [x] Task 2 子集面板跟随测试项切换（fixateSelection + epoch 竞态守卫 + e2e 反转）
- [x] Task 3 选区一次性消费 + 光标 bug（preventDefault + user-select:none，先复现）
- [x] Task 4 serial 圈选改跨参数芯片高亮（useSerialHighlight 单例 + 叠加系列 + 菜单 highlight 模式）
- [x] Task 5 直方子图滚轮缩放 + 拖拽平移（enableDataZoom 默认关，仅子图开）
- [x] Task 6 收口：e2e 补强 + spec 修订 + 全量门禁（4-slot 池 + 后端全套）

## 提交清单（2026-11-12 收口，git log 现读）

| 任务 | 提交 | 摘要 |
|---|---|---|
| T1 | `5902485` | value_range 选区固化 serials 随 histogram 响应回传 + T1 |
| T2 | `3956bf7` | 子集面板跟随测试项切换（fixateSelection + epoch 竞态守卫）+ T2/T3 反转 |
| T3 | `6b7577a` | 选区一次性消费 + 框选插入光标修复（按下/移动/抬起三清选区） |
| T4 | `c148315` | serial 框选改跨参数芯片高亮（mouseup 立即消费 + 会话单例按 serial 重画）+ T2/T3 |
| T5 | `4c2ee07` | 子集直方图 inside dataZoom 滚轮缩放/拖拽平移（enableDataZoom 默认关）+ T3 |
| T6 | 本提交 | 收口：e2e 补强（关闭按钮用例 + 菜单等待硬化 + 缩放收窄判据）+ epoch 竞态 T2 + EOF×5 + spec 修订节 + 本条目 |

（用户 intro 提交 ab1490a/7a0faba 插在 T4 与 T5 之间、d207806 插在 T5 与 T6 之间，
属正常历史，非本任务产物。）

## 收口验证（2026-11-12，全绿）

- 前端三件套（frontend/）：`npx vitest run` **61 文件 / 843 例全过**（含新增 epoch 竞态案）；
  `npm run lint:e2e` 无错；`npm run build`（vue-tsc -b + vite build）✓。日志 `tasks/t6-vitest-lint-build.log`。
- 4-slot 全量池（仓库根，runId 065504-26520）：`用例 445 · 墙钟 9.3min · 单价 3.04s/例 ·
  unexpected 0 · flaky 6 · skipped 21` → **`结论 MEASURED`**。日志 `tasks/t6-close-e2e.log`，
  明细 `tasks/t6-close-e2e/merged.json` + `main-run-slots/`（slot 日志已归档）。
  效率 2.31<2.8 不判退化（本轮有 retry，testing-gates §4「效率只在无重跑时判」）。
- 后端全套（仓库根，与池并跑，落盘面已分离）：**`Ran 2571 tests in 601.848s` / `OK (skipped=16)`**。
  日志 `tasks/t6-backend.log`（例数多于旧账 1789：用户 intro 批新增 test_static_assets 等，以 OK 行为准）。
- flaky 6 定性＝**负载抖动**（serial-no-column ×5：waitForResponse 20s ×4 + 图表可见 15s ×1；
  wafermap-redesign ×1：SVG 布局 null；全部未触碰文件、retry #1 转绿）。独占复跑
  （runId 070642-48704，`--slots=1` 两文件）**13/13 绿 · unexpected 0 · flaky 0 · MEASURED**，
  日志 `tasks/t6-close-e2e/recheck-solo.log` + `recheck-solo/`。multi-file:152 本轮未再现。
- 补强落地：菜单等待硬化（attached+visible 20s，判据不削弱）；关闭按钮 × 用例（双面板按 id
  移除→计数 0→区域撤下）；epoch 交错双 load T2 案（变异刀自证承重：禁守卫→RED→还原→绿）；
  滚轮缩放补 end<100 收窄判据；EOF 换行 ×5。独占验证轮 7/7 绿（tasks/t6-solo-e2e.log）。

# 任务：flake 治理批（2026-11-12）

承接「圈选子图四点跟进」收口遗留两项 + 验证中新发现一项。只改测试/e2e helper，产品代码零改动。
根因与规则详见 lessons.md「2026-11-12 flake 治理批」；证据日志在仓库根 tasks/flakefix-*。

- [x] waitForResponse 负载族：9 处 raw 序列开关迁 enableChartAndWait（30s）+ expectChartRendered boundingBox 条件轮询 + :406 补响应同步
- [x] test_job_cancel 真池时序：管道占用替代 time.sleep(2.0) 固定窗口（Event 过不了 call queue，探针实测；判据逐字未动）
- [x] file-list-completeness 上传等待三缺陷（弱阈值/导航中断/代理丢响应）：串行上传 + 逐文件响应等待 + afterAll 删 DB 行

## 提交清单（git log 现读）

| 笔 | 提交 | 摘要 |
|---|---|---|
| 1 | `4b0156c` | e2e 负载族治理（charts.ts + serial-no-column + serial-fail-count） |
| 2 | `977c4a5` | file-list-completeness 上传等待三缺陷修复 |
| 3 | `6e52a93` | jobs 真池取消窗口用例改管道占用 |
| 4 | 本提交 | lessons 三条根因与规则 + 本条目 |

## 门禁（最终树，全绿）

- 前端三件套：vitest 61 文件 843 例全过 / lint:e2e 无错 / build ✓。
- 后端全套（与池并跑）：**Ran 2573 tests / OK (skipped=16)**（2573 = T6 账 2571 + 修复轮 F1 边界 2 例）。
- 4-slot 全量池 runId 094319-22016：**445 例 · unexpected 0 · flaky 2 · skipped 21 · MEASURED**。
  flaky 2 均在未触碰文件（tiny-fail-bar:79 / view-data:1393），独占复跑 38/38 零重试 ⇒ 负载抖动。
- 目标四文件（serial-no-column / wafermap-redesign / serial-fail-count / file-list-completeness）
  全量池零 flaky；独占回归 14/14 + file-list 串行版 ×2 零 flaky。
