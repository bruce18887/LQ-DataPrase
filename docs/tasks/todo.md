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
  - `flaky 1` 是 `e2e/data/view-data.spec.ts` 的「@p2 顶部带：操作按钮在文件横幅内，表格高度与实测占位对齐」那条（首跑失败、retry #1 过）。本批没碰过 `e2e/data/` 与该页任何组件，形状与 lessons 里「dev server 长时间运行后劣化」同族 ⇒ 判为存量抖动，不因此调重试或跳过。
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
  flaky 2 均在未触碰文件（tiny-fail-bar:79 / `view-data.spec.ts` 的「@p2 顶部带：操作按钮在文件横幅内」那条），独占复跑 38/38 零重试 ⇒ 负载抖动。
- 目标四文件（serial-no-column / wafermap-redesign / serial-fail-count / file-list-completeness）
  全量池零 flaky；独占回归 14/14 + file-list 串行版 ×2 零 flaky。

# 任务：分析页子集面板手柄 / 文件选择记忆 / 无数据态去重试（2026-11-12）

用户实测反馈三条（截图：子集面板无拖动手柄；文件选择器默认开最新文件；子集无数据态多余重试按钮）。

## 范围与决策

1. **子集面板拖动手柄**：`SubsetPanelArea.vue` 头部补 ⠿ 手柄（对齐 `ChartPanel.chart-h__grip` 视觉），
   指针拖拽在扁平网格里重排面板（move 语义：splice 到目标 index）。`useSubsetPanels` 加纯函数 `move(fromId,toId)`（T2 承载）。
   不做 dock 那套象限分行/分列——子集区是均匀网格，无行列结构可管。
2. **文件选择按 tab 记忆**：新增 `composables/fileMemory.ts`（safeStorage 封装 + 纯函数 `pickFallbackFile`）。
   - 写侧只在**用户交互**落盘：`AnalysisFilePicker` 的 `@change`（el-select change 仅用户触发，程序化 v-model 不触发）
     → `rememberFile(scope, value)`，键 `analysis.lastFile.<scope>`。**自动回退首项不写记忆**——否则「先访问分析页→再上传新文件→重进」会被旧记忆钉死，且破坏依赖「默认最新」的 e2e。
   - 读侧：`useTabFileParams` 加 `memoryKey`，回退时 `pickFallbackFile(list, recallFileId(key))`（记忆失效→最新）；
     `MultiFileTab.onMounted` 在 `initFromQuery` 后、store 为空时 `recallFileIds('multi')`（URL query 优先）。
   - 跨账号安全：文件按 owner 过滤，记忆 id 不在新账号列表→自动回退最新（R5 双层防御的后端那层天然成立），无需登出清键。
   - 仪表板「最新 ready 每次挂载重算」是文档化设计（e2e README:193），**不在本批改动**。
3. **子集无数据态去重试**：`useSubsetPanels.load` 对「result 为 null」不再写 `error`（那是空态不是失败）；
   `SubsetPanelArea` 末尾 `v-else` 渲染中性 `el-empty`（无重试、无红横幅）。真实网络失败仍走 ErrorBanner+重试。
   对齐 ErrorBanner 注释「失败与没有数据要区分」。

## 清单

- [x] fileMemory.ts + T2（pickFallbackFile / recall 解析 / remember 写删）
- [x] useTabFileParams 接 memoryKey；三 tab 传 scope；MultiFileTab 读侧恢复
- [x] AnalysisFilePicker @change 写记忆
- [x] useSubsetPanels.move + load 空态不写 error；T2 补 move/空态用例
- [x] SubsetPanelArea 手柄 + 拖拽重排 + 空态 el-empty（双主题）
- [x] e2e：subset-drilldown 补手柄重排 + 无数据态；file-select 补记忆恢复
- [x] 门禁：affected（analysis 模块档）+ 前端三件套；收口全量池 + 后端

## review

**实现要点（含一处自我纠错）**：
- 子集「没数据」的真实路径是后端 **400 `empty_selection`**（`analysis_views.histogram:235`），
  走前端 load 的 **catch** 分支，不是 200 null result 的 try 分支。第一版只改了 try 分支
  （`if(!panel.result) panel.error=…` 删除），e2e 真实渲染当场抓出仍显示重试按钮 → 补 catch
  分支按 `e.response.data.code==='empty_selection'` 判空态（result=null、error 保持 null），
  面板 `v-else` 渲染中性 `el-empty`（无重试）。真实失败仍写 error 走 ErrorBanner+重试。
  T2 三条钉：200 缺参 / 400 empty_selection / 400 internal_error（后者必须保留 error）。
- 文件记忆**只在用户交互写**（AnalysisFilePicker `@change`，el-select change 仅用户触发）；
  自动回退首项不落盘 → 不破坏「默认最新」的既有 e2e，也不把「先访问→再上传新文件→重进」钉死。
  读侧 `pickFallbackFile(list, recalled)`：记忆失效（删文件/换账号，文件按 owner 过滤）→ 回退最新。
- 子集手柄拖拽用 move（splice）语义，扁平网格无行列结构，不做 dock 象限分行/分列。

**门禁（最终树）**：
- 前端三件套：vitest 62 文件 863 例全过（+fileMemory 14 / subsetPanels +6）/ lint:e2e 无错 / build ✓。
- `npm run test:e2e:affected` → **RESULT: PASS · 计划 4 档全部执行**（lint:e2e / vitest / e2e:analysis / e2e:附带P0）。
  analysis 档 163 例 · unexpected 1 · flaky 2 · 复跑判级**真红 0**；唯一 flaky 是**既有**「散点框选→芯片高亮」
  在 3-slot 负载下的高亮 poll 超时（独占复跑绿），非本批新增用例引入。
- 新增 e2e 独占复跑均绿：手柄重排（[1,2]→[2,1]）、无数据空态（el-empty 文案 + 重试 0 + error-banner 0）、
  单文件记忆刷新恢复、多文件无 query 重进恢复。

**遗留**：仪表板「最新 ready 每次挂载重算」是文档化设计（e2e README:193），本批未改；
收口全量池 + 后端全套待并入 master 前按 testing-gates §1 跑（本批为 affected 档验证）。

# 任务：子集面板并入 dock，可与直方图同排拖拽（2026-11-12 跟进）

用户反馈「拖动手柄有了但是无法拖到和直方图一起」——上一批的独立子集区只能内部重排，
不能与主图同排。本批把子集面板升级为 dock 的会话级 **guest**（`subset:<id>`），复用 dock
既有的象限拖拽（左/右/上/下/交换），即可拖到直方图旁边并排对比。

## 设计（守住 D4/R5 账号记忆契约）

- guest 只存在于内存 rows；`persist()` 经 `guestFreeSnapshot` 剥离 guest 后再写 localStorage/账号，
  **无 guest 时逐字原样**（既有存档不被改写，chart-memory 契约绿）。
- `reconcile` 把 guest 计入 active 保留（切换勾选不丢子集）；`addGuest/removeGuest` 只改内存不落盘。
- `useSubsetDockBridge` 单向把面板集合投影成 guest（新增→addGuest、关/切文件→removeGuest），dock 内拖拽不回环。
- 渲染：ChartDock 对 guest 用 ChartPanel（挂 data-subset-* 契约 + ⠿ data-subset-grip + 关闭子集面板）+ SubsetPanelBody。
- 删除独立 SubsetPanelArea 与 useSubsetPanels.move（重排改由 dock.moveTo 承载）。

## 验证

- T2：dockGuests.spec（guestFreeSnapshot 无 guest 逐字/有 guest 剥离归一、reconcileRows 保留 guest）+ 全量 867 例绿。
- e2e subset-drilldown 10/10：含「子集拖到直方图同排」+「guest 不进持久化」+ 手柄重排 + 空态 + 关闭。
- affected 门禁 RESULT: PASS（真红 0）；settings/chart-memory 独占 unexpected 0（账号契约 intact）。
- 注意：应用滚动在内层容器，e2e 跨行拖拽须 scrollIntoView+调 ancestor.scrollTop、并加高视口（1200/1600）。

# 任务：子图展示联动 serial 芯片高亮，关子图才取消（2026-11-12 跟进）

用户：子图展示后若开启 serial 分布，也应高亮这些芯片，直到关掉子图才取消。
`useSerialHighlight` 的高亮集合改为 **brush ∪ 子集面板**（computed 并集去重保序）：
子集 selection 固化为 serials 后即贡献高亮（serial 后开启也立即可见、跨参数保持）；
右键「清除高亮」只清 brush；关闭子集/切文件清空后子集贡献自然消失。
T2 serialHighlight.spec 钉并集/清除/关子集归零；e2e 补「子图→后开 serial 高亮 {4,5,6}→关子图取消」。
验证：subset-drilldown 11/11；affected 门禁 RESULT: PASS（真红 0）。

# 任务：e2e 内联 `:visible` 清点（批1 Task 9A 记的实数，下一批专项按这个排工，2026-11-13）

计划把这笔账写成「48 处内联 `:visible`（19 个 spec 文件）+ `colfilter.ts` 的 3 处」，
批1 Task 9A 只做谓词入口（`popperOf`）统一、**不碰这批 `:visible`**，同时按 lessons R③
「台账里的计数一律现跑再引用」重数了一遍：**那个 48/19 与实数差一个量级，别照它排工**。

现数（`frontend/`，**口径 = 剔掉注释行后的「命中行数」**，`grep -rn ... | grep -v 注释 | wc -l`；
一条里出现两次 `:visible` 的写法确实存在，所以 occurrence 口径会比行数多（现跑 `grep -roE ':visible'`
连注释一起数是 213）——**排工只认下面这两条命令的行数口径**。数字一律 **2026-11-14 批1 收口重跑**，
命令写在这里，下一批照抄再跑，别信任何一处抄走的数字）：

- **全部 `:visible`：190 处 / 35 个文件**（`grep -rn ":visible" e2e --include=*.ts | grep -vE ':[[:space:]]*(//|\*|/\*)' | wc -l`）。
- **其中属于「下拉/弹层族」的（`.el-select-dropdown__item` / `.el-popper` / `.el-select-dropdown`
  直接带 `:visible`）：81 处 / 27 个文件**（同一条命令把 pattern 换成 `\.(el-select-dropdown__item|el-popper|el-select-dropdown):visible`）。这一族才是 `popperOf` 那套实例级谓词的替代品，
  也是批末该收的范围；其余 109 处是 `p:visible` / `.el-tab-pane:visible` / `.ag-*:visible`
  这类**不是同一个问题**，不要一并换算成「81 之外的债」。
- ⚠ **和上一条 2026-11-13 记的「193 / 84」不可比**：那条只写了「逐行剔注释后数出现点」这句话、没留命令，
  现跑同一条 `git grep -hE` 在 master 上给的是 207 / 93 ⇒ 至少存在「数行」与「数 occurrence」两种口径。
  排工时以本条命令的 190 / 81 为准，**别拿两次之差当本批工作量**（批1 在这一族的净变化用
  `git grep -oE` 现核只有 1 处 `.el-select-dropdown__item:visible` 被换掉，39 → 38）。
- 族内最重的五个文件（同一命令接 `| cut -d: -f1 | sort | uniq -c | sort -rn | head -5`）：
  `outlier-handling.spec.ts` 14、`exports.spec.ts` 8、`view-data.spec.ts` 7、`data.spec.ts` 6、
  `multi-file.spec.ts` 5（上一条把 view-data 记在 exports 前面，实跑 exports 更多）。

排工提醒（不是本批的活）：`e2e/data/` 那两个超限文件（`view-data.spec.ts`、`data.spec.ts`）被
`scripts/line-limit.mjs` 的 `EXEMPT` 账按**精确行数**冻着 —— 那张账是唯一事实来源，**别在计划/台账里
抄那个数字**（抄一次就会像这里原来写的「1802」一样，下一批加完断言之后已经是错的，还会把后排工的人带偏）。
要改这两个文件：先 `cd frontend && wc -l e2e/data/view-data.spec.ts` 现跑，同批把 `EXEMPT` 登记值同步
（多一行 `grew` 红、少一行反向断言红），并在该条 `reason` 里说明这一增一减是哪个工单。
`exports.spec.ts` **不在这张账上**，它受的是通用 `lines > 600` 那道闸（`scripts/line-limit.mjs:197` 是
`<=` 才放行 ⇒ **600 本身合法、601 就红**）⇒ 改它同样要现跑 `wc -l`，且加不进注释行只能就地替换。
这两条差别决定了摊开时谁能加注释、谁只能就地替换。

2026-11-14 批1 Task 9B 复审把上面这本账订正了一遍：`exports.spec.ts` **不在** `EXEMPT` 名单里（名单中的
e2e 文件只有 `data.spec.ts` / `view-data.spec.ts`），受的是通用 `lines > 600` 那道闸 ⇒ 「两个文件都被
EXEMPT 冻着」那句对它不成立，同步登记值这一动作对它也不适用。**它的行数一律现跑**：
`cd frontend && wc -l e2e/exports/exports.spec.ts`（2026-11-14 收口 + 终审修复后现跑 **599**，
距 600 只剩 1 行 ⇒ 下一批动这个文件前先按本节命令重跑，只能就地替换、不能加注释行；
真要塞进新判据就先在那两条长注释里腾）。
批1 终审在这一档留下的净变化：删 `P.length < 2 ⇒ test.skip` 那段（−5）、导出族补「空关键词 footer
不显示」与「并集 ≥3 判别力前提」（+3）、footer 两支措辞统一成 `toHaveText` 逐字（0）。

2026-11-14 批1 Task 10/11 合并复审另记一笔（**只记账，不改产品代码、不加断言**）：设计稿 §7 第 3 条那句
「铃铛/**用户菜单**仍 `--text-2`」字面不成立 —— 用户菜单那颗头像 `.user-avatar` 硬编码 `color: #fff`
（`frontend/src/components/layout/Topbar.vue:387`），两主题恒 `rgb(255, 255, 255)`，不吃 token，
而 `frontend/e2e/theme/intro-icon-contrast.spec.ts:13` 本来就显式声明「本文件不判它」。定性：`--brand` 底反白
是另一个 affordance，**不是产品缺陷**，只是设计稿那句话与实现现实的偏差；已在 §7 第 3 条就地加括号标注。
⇒ **Task 12 收口现量这一条时只判两半**：intro = `--text`、铃铛 = `--text-2`；别为头像补断言。

# 任务：下拉 v2 迁移面普查——9C 复审又数出两个从没上过清单的同类漏项（2026-11-13 记，**只记账不动代码**）

批1 Task 9C（固定列迁 `el-select-v2`）的复审把「未封顶的 v1 `el-select` + `v-for`」这个形状重新数了一遍，
结论：**设计稿 §2 承诺的四个 + §2.9 补的第五个并不是全集**。现跑统计（`frontend/`，`grep -rnE "<el-select([[:space:]>]|$)" src`，
逐字剔掉 `el-select-v2`）：

- `<el-select-v2>` **5 处**：`ParamSelector.vue:4` / `SerialSelector.vue:3` / `TestColumnSelector.vue:3` /
  `ExportParamSelector.vue:16` / `DataBrowserToolbar.vue:63`（即批1 迁的那五个）。
- v1 `<el-select>` **31 处**，其中**选项走 `v-for` 的 9 处**（`CorrelationToolsTab` 2、`FileSelect` 1、
  `CombineBatchDialog` 1、`SftpSearchPage` 1、`DataBrowserToolbar` 的 Site 1、`ColumnHeaderFilter` 1、
  `BatchBinSection` 1、`SearchCriteria` 1），其余 22 处是静态字面量选项。

**9 处 `v-for` 里，两处的参数源与已迁控件同源，属复审点名的「从没上过任何清单」的同类形状（实测同形）：**

1. `frontend/src/pages/analysis/components/CorrelationToolsTab.vue:36` 与 `:41`（X / Y 测试项下拉，
   `el-option` 的 `v-for="p in params"` 在 `:38` / `:43`）。`params` 来自本 tab 的
   `useTabFileParams`（`:210`），与已迁的 `ParamSelector` **同一个数据源** ⇒ 千级参数文件上同形，
   一打开就挂 `params.length` 个完整 `el-option` 实例。
2. `frontend/src/components/common/FileSelect.vue:2`（横幅那个文件选择器，`el-option` 的
   `v-for="f in g.files"` 在 `:29`）。`groupedItems`（`:139` 的 computed）**没有任何 slice / 封顶**，
   条数 = 文件列表条数；量级取决于用户库里有多少文件 ⇒ 形状相同、上限不同，**属待实测**。

另两处**次级候选（形状同族、量级待实测，不预先断言它是千级）**：
`frontend/src/pages/sftp/SftpSearchPage.vue:81`（`el-option` `:83` 遍历 `runOptions` = `store.runs`，
运行记录会随使用单调增长）与 `frontend/src/pages/data/components/CombineBatchDialog.vue:38`
（遍历 props 传入的 `batchOptions`，条数由调用方决定）。

**有意保留的 v1（不是债，别并进这张清单）**：静态字面量选项与有界小集 ——
`DataBrowserToolbar.vue` 另外三颗（Pass/Fail、Site、列宽，选项个位数到十几）、
`ColumnHeaderFilter.vue`、`BatchBinSection.vue`（phases）、`SearchCriteria.vue`（presets）、
admin/settings 那一族（`AuditLogPage.vue` 事件枚举、`UserManagement.vue` 角色、`TableSettingsForm.vue` 每页条数）。

**处置**：是否并入批 1（还是另起一批 + 每条先实测条数）由用户拍板；**未拍板前不动代码、不写判据**。
拍板并入后，机制照 Task 7/9C 现成的形状（`toOptions` + `popper-class` 实例锚点 + 反截断判据），
先跑 `wc -l` 再同步 `scripts/line-limit.mjs` 的登记值。

# 任务：批1 收口门禁与台账（2026-11-14，计划 Task 12）

## 并入 master（2026-11-14 收口完成）

批1 的提交（笔数见下面「提交清单与规模」）以 **`--ff-only` 并入本地 `master`**，随后删掉过程分支
`feature/batch1-dropdown-v2-intro-icon`。**全程未 push**：`origin` 是公开仓库，一次 push 即全球发布。
并入后 `master` 领先 `origin/master` **55 笔**（前 14 批 6 笔 + 批1 全部）。

**门禁为什么可以沿用而不重跑整池（说清依据，别说成"差不多"）**：
- FF 后 `git rev-parse master^{tree}` 与被复审过的分支 tip **逐字相同**
  （`87736ec72a241002a0cd8323eceacdd60ec2cee7`）⇒ 并入本身没带进任何东西。
- 但**全量池 / 后端 / build 跑的是收口第 2 轮那一刻的树**，其后还落了几笔（逐笔标题现读：
  `git log --oneline <池档那一刻>..master`，这里**不抄笔数**——本批已经因为把一次性快照写成长期事实
  踩过三次：`:visible` 的 48/38、行数 592/597/599、changed 44/46/47）。改动面同样现读
  `git diff --name-only <池档那一刻>..master`，核对下来只有四类：
  `frontend/test/unit/`（两份绊线 spec）、`frontend/e2e/**` 的**注释**（`exports.spec.ts` 三处锚、
  `helpers/elplus.ts` 两段）、`docs/`、`scripts/`——既不改产品行为也不改任何 e2e 断言。
- 因此按**改动面**选档重验，不重跑 10 分钟量级的池：`npx vitest run` = 68 files / **951** tests、
  `npm run lint:e2e`（`tsc -p tsconfig.e2e.json`）干净，两档都在 FF 后的 `master` 上现跑。
- 想升级到池档：`node scripts/e2e_pool.mjs --slots=4`（约 10min），判据取末行 `结论 MEASURED`
  与 `unexpected`，**别取退出码**。

## 提交清单与规模（现读，别抄别处的快照）

`git rev-list --count d807eea..master` = **49 笔**；`git diff --shortstat d807eea..master` =
**47 文件 / +3745 / −429**。逐笔标题走 `git log --oneline d807eea..master`。

分支 `feature/batch1-dropdown-v2-intro-icon` 上完成，**全程未 push**（`origin` 是公开仓库），
收口后 `--ff-only` 并入本地 `master` 并删掉该分支（见上面「并入 master」）。
收口这一轮另加九笔：`fa2200d`（池档抓到的 storageState 真红 + 绊线）、`a36f9cb`（终审三笔判据）、
`6255122`（消费者账与两笔谓词债订正）、`1abe68b`（intro 声明的源侧 T2）、`10e12f0` + `69a2119`
（本节台账与一条口径订正），以及**对修复再做复审**那一轮四笔：`2fd6882`（两条绊线重做成真抓得住）、
`69e2901`（collapse-tags 是四颗 + 注释锚改按用例标题）、`ef68ff0`（台账六处重跑订正、普查器入库）、
`4530c86`（changed 数改成"对齐命令不对齐快照"）。

## 门禁实跑（全部这一轮现跑，别引用上一轮）

- **affected**：`node scripts/e2e_affected.mjs --base master` ⇒ changed **46 文件**（这是收口那一轮现跑的快照，
  **别对齐它，对齐命令** —— 同一天为这条台账又把普查器移进 `scripts/`，现在再跑就是 47）、8 条命中全局清单
  （`config/urls.py` + 7 份 `e2e/helpers/`）⇒ `decide: 全量 e2e（兜底命中）`，计划 4 档
  lint:e2e / vitest / backend / e2e 全量。**升全量是预期**，不是异常。
  ⚠ **如实记：这一条是 `--dry-run` 跑的**（末行 `RESULT: PASS · 计划 4 档全部执行 · dry-run（未真正执行）`），
  四档随后**各自单独实跑**（下面逐条），所以判定读了、执行没走脚本。这么切的理由：`--dry-run` 之外它还会
  把四档串成一条命令跑，而本轮需要「先修第 1 轮池的真红，再跑第 2 轮」——串跑会把还没修好的树判成红。
- **全量池第 1 轮（修复前）**：`--slots=4` · 文件 87 · 用例 460 · 墙钟 13.8min · 单价 2.89s/例 ·
  效率 1.52 · unexpected 5 · flaky 1 · skipped 21 · 结论 `MEASURED` · **复跑判级真红 1**
  （独占 slot 仍红，不是负载抖动）。
- **那 1 条真红 = `analysis/param-dropdown-full-list.spec.ts` 五条全红在 `gotoApp`**，判据一条都没跑到。
  根因与教训见 `docs/tasks/lessons.md` 2026-11-14 同日条目 + 提交 `fa2200d`。要点：**这个文件从没进过
  slot 档**，串行档里两条路等价所以每轮都绿。
- **全量池第 2 轮（最终树）**：文件 87 · 用例 460（stats 口径 expected 446 / flaky 1 / skipped 21 /
  **unexpected 0**；446+1+21 = **468 ≠ 460**，差的 8 条正是 4 个 slot 各 2 条 `auth.setup`——
  `用例` 走 `realTests()` 把 setup 剔了（`scripts/e2e_pool.mjs:229-233` 的注释就在说这件事），
  `stats` 没有 ⇒ 两套数本来就差 2×slot，别拿 460 去对 468）· 墙钟 `wallMs 571916` = 9.5min ·
  `passMs 1271818` · 单价 2.90s/例 · 结论 `MEASURED` · 退出码 0。**效率 2.23 < 池自己给的目标 2.8**：
  四个 slot 的用例数是 73 / 116 / 93 / 178（`merged.json.health` 现读）——LPT 是按**时长**分区不是按条数，
  条数悬殊不等于分区坏了；本批判据取 unexpected / flaky，效率只作观察。⇒ 第 1 轮那 13.8min 里含一次
  「逐文件独占 slot 复跑判级」，**两轮墙钟不可直接比**。
- **flaky 那 1 条不归属本批**：`view-data.spec.ts:1474`「@p2 顶部带：操作按钮在文件横幅内，表格高度与
  实测占位对齐」——两轮池都是首发红（`表格上缘位置变了，但 TABLE_TOP_OFFSET 没跟着重量`，实测 y≠413）、
  retry #1 绿。本批对该文件最后一个 hunk 在新版 :894 之前（`git diff master...HEAD` 现读），:1474 未触碰
  ⇒ **留给下一批**：几何绊线要么重量 `TABLE_TOP_OFFSET`，要么补显式等待条件，别当本批的账。
- **skipped 21 条的归属**（现跑 `C:\lqdp-e2e\slots\<run>\slotN.results.json` 统计）：`data.spec` 5、
  `sftp.spec` 4、`dashboard.spec` 3、`toolbar-sticky` 2、`batch` 2、`correlation-inline` /
  `file-list-sort-filter` / `type-snapshot` / `html-report` / `renderer-memory` 各 1
  ⇒ **本批改过的四个 spec 零 skip**（另：单独把导出族在 slot 档跑一轮是 skipped 0）。
- **vitest**：`Test Files 68 passed (68)` / `Tests 940 passed (940)`；批前基线 66/934 ⇒ +2 文件 +6 例
  就是这两道新绊线（`e2eAuthStateHygiene` 4 例、`introTabIconSource` 2 例）。
- **lint:e2e**（`tsc -p tsconfig.e2e.json`）干净；**`npm run build`** 干净（第 2 轮池跑的就是重建后的 dist）。
- **后端全量**：`Ran 2576 tests in 539.961s` / `OK (skipped=16)`。标签枚举照
  `scripts/e2e_nightly.mjs:129-136` 的形状：`test.backend` + 12 个 `apps.*`（**排除 `__*` 目录**），
  绝不写 `apps.*` 通配。日志 `tasks/t12-backend-full.log`（`tasks/` 未入库，只是当轮取证用，别去找它）。
- **行数账（现跑 `wc -l`）**：`exports.spec.ts` 599（600 硬闸内，不在 EXEMPT 名单）、
  `view-data.spec.ts` 1883 = EXEMPT 登记值逐字未变、`file-correlation.spec.ts` 459、
  `param-dropdown-full-list.spec.ts` 154、`selectOptions.ts` 127。`lineLimit.spec.ts` 15 例随 vitest 全绿。

## 探针 Q1–Q4 的实测值（Task 1 取消后由 Task 5 自己的 T3 给数，形状见计划 :38-47）

| 问 | 实测 | 判据出处 |
| --- | --- | --- |
| Q1 `#footer` 是否在虚拟窗口外仍渲染 | **是**，footer 逐字「共 1723 项」 | `param-dropdown-full-list` 第 1 条（`243dff4`） |
| Q2 `filter-method` 是否真的不过滤 | **不过滤**；搜到列表**末项**并选中 ✓ | 同文件第 2/4 条 + `filterByKeyword` 的 T2 |
| Q3 虚拟窗口 DOM 行数 | **11 行**（1,723 项全集；界 20 由 `select-v2/src/defaults.mjs` 的 height 274 / itemHeight 34 推出） | 同文件第 5 条，Task 5 Step 1.5 打印后摘除 |
| Q4 滚到底耗时 | **310ms**（hover 首行 + `mouse.wheel(0, 200_000)`） | 同上 |

- **迁移前对照没有同形计时**：旧实现封顶 300、从没打过 ms。能拿的是形状与后果两条 —— footer 写
  「仅显示前 300」，而 `固定列` 那颗从没封顶过、打开即挂 1,728 个 `el-option`，把
  `view-data.spec.ts`「@p1 固定列：多选」那条的 `toBeVisible({ timeout: 15_000 })` 拖成 Task 7/8 复审里
  唯一反复红的业务用例（迁完绿）。⇒ 「不冻结」这个前提成立，但**别把这句读成「快了多少倍」**。
- 固定列（第 5 个，1,728 列）只有形状判据（窗口行数 < 界 + 每行是真实列名）；打开耗时**并进失败消息
  label、未落断言**（那条永不触发的耗时断言已在 `798e277` 删）⇒ 想要实数得临时打印，别引用 label。
- 设计稿/计划里假设的「4,570 项」在仓内**不存在**。实测最大夹具 = **1,723 参数 / 1,728 列**，同属
  `BPD93204_FT1_ETS163550_12252024.csv`（= `SEEDED_FILES.ETS88_FT`，`fixtures/test-data.ts:60`）。

## e2e 改写条数（现跑，不是设计稿 §2.7 估的 15–20）

`node scripts/e2e-rewritten-census.mjs`（按「describe 链 + 用例标题」当身份，比 master 与 HEAD 的块体正文；
已入库，`tasks/` 那版在 `.gitignore:162` 的忽略面里，下一批跑不到）：
**新增 8 条 / 改写 16 条 / 删除 0 条**（源码 `test(` 计数；`intro-icon-contrast` 是 light/night 循环
⇒ 运行条 +9）。按文件：`param-dropdown-full-list` +5、`view-data` +1（千列那条）/ ~5、
`file-correlation` ~5、`exports` ~2、`chart-filter-switches` ~2、`tab-independent-files` ~1、
`element-plus-styles` ~1、`intro-favicon` +1、`intro-icon-contrast` +1。
交叉核对（异源）：单文件 playwright 条数 = 本脚本条数 + 每项目 2 条 setup（相关性 8→10、参数 5→7、导出 8→10）。
现有 e2e 规模：**87 个 spec 文件 / 460 条**（池口径）。

## 终审（整批只读复审）5 笔 IMPORTANT 的处置

1. `selectOptions.ts` 头注释的消费者账写窄（4→5 个下拉、`filterByKeyword` 2→4 处）—— **已改**，
   命令写进注释（`6255122`）。
2. 导出族「Enter 全选」的关键词界 `命中数 ≥1` 无判别力 —— **已改**成 `pickBoundedKeyword(others, cap)`
   + 「基线那颗不许命中该关键词」前置；**改完当场红**，正是旧界放行无判别力形状的证据（`a36f9cb`）。
3. `view-data.spec.ts:415` 那句「另四族各有各自那条空关键词反例」当时**不成立**（只有 col 族有）——
   serial 与 export 各补一条 `toHaveCount(0)`，句子随之变成真的（`a36f9cb`）。
4. 导出族那记 `P.length < 2 ⇒ test.skip` 与同文件下面那条 `throw` 并存 —— **已删**（skip 是 throw 的
   前件子集，并存等于同一判据上两种出口）。
5. `config.mts` 的 `<link rel=icon>` 声明在 CI 里**零守卫**（CI 四档无 Playwright，T1 ① 在 dist 缺失时
   skip）—— 新增永不 skip 的源侧 T2（`1abe68b`）。

## 记账不做（理由写清楚，别当已解决）

- **三族接线逐字重复三份**：`kw` / `matches` / `filterMethod` / `clearFilterInput` / `onSelectKeydown` /
  `onVisibleChange` / `selectAll` / `clearAll` / `selectMatches` 九个同名符号，位置
  `SerialSelector.vue:75-166`、`TestColumnSelector.vue:72-149`、`ExportParamSelector.vue:60-136`
  （现跑 grep 数出来的）。终审建议抽 `useSelectFilter` composable。**本批不抽**：批1 已越过原设计范围
  （9C 本是漏项），而抽 composable 要同时动三个组件 + 四条判据，风险落在收口档之后。**上面第 2/3 两笔
  就是这份重复的产物** ⇒ 下一批（批2/批3 起手）真要抽就一次做完，做完把这三段注释收敛成一份。
- `ExportParamSelector` 没有 `#empty` 槽（搜不到时显示 EP 的 locale 文案 'No matching data'）。
  **不是本批回归**：`git show master:` 版同样 0 处，v1 时代就是这个形状 ⇒ 与「加载期间显示『无匹配序列』」
  同属文案错位的独立工单（提案留档 `tasks/2026-11-13-loading-slot-proposal.patch`）。
- **v2 的 `popper-class` 会同时挂到 `collapse-tags` 溢出标签 tooltip**（`select-v2/src/select.mjs:117`
  `tagTooltip?.popperClass ?? popperClass`）⇒ 五颗里**四颗**命中（现跑
  `grep -rn "^[[:space:]]*collapse-tags$" frontend/src` = Serial / TestColumn / Export / 固定列，单选的
  ParamSelector 没有），这四份 class 的 `.el-popper.dp-*-popper`
  **可能有两份**，眼下靠同文件 `:108` 的 `disabled: dropdownMenuVisible` 让两者不同时可见。已在
  `popperOf` 注释里写死处置（真报 strict violation 就给 tooltip 单独传类，**不许退成 `.first()`**）。
- `config/urls.py:122` 的 SPA catch-all lookahead 没列 `favicon\.ico`：现在无害（`path()` 排在它之前，
  Django 按序匹配），但那份 lookahead 是挂载表的**第二副本**。**没改**——改 `config/urls.py` 命中
  `testing-gates.md` §3 全局清单 ⇒ 又要升一次全量池，为一个 inert 的防御性改动不值。下一批动 urls.py
  时顺手补，并把 lookahead 与 `urlpatterns` 的重复收成一份。
- 内联 `:visible` 专项与 `visibleSelectOptions` 那 4 个文件的实例级类名：**批1 没做**（上面那节是实数与
  命令）。`elplus.ts:80` 原文写「是本批收口的专项」是错的，已订正（`6255122`）。
- `clearFilterInput()` 是否真洗掉 EP 内部 query、以及「空关键词 + Enter」行为：**零判据**，9B 就记过，
  本批仍未补（要补就在上面那条 composable 工单里一起补）。
- 上一节那两个同类漏项（`CorrelationToolsTab.vue:36/:41` 与 `FileSelect.vue:2/:29`）+ 两个次级候选
  （`SftpSearchPage.vue:81/:83`、`CombineBatchDialog.vue:38`）：**等用户拍板**，未拍板前不动代码、不写判据。

# 任务：批2 磁盘占用（2026-11-14，计划 Task 10 收口；计划 `docs/superpowers/plans/2026-11-14-batch2-disk-usage.md`）

## 状态：**已 `--ff-only` 并入本地 master，未 push**

`master` = `69419a5`（`git rev-parse master` 现读），过程分支 `feature/batch2-disk-usage` 已删
（`git branch -d`，删除时它指向同一笔 ⇒ 没有任何提交只活在分支上）。全程**没有 push**：`origin` 是公开仓库，
一次 push 即全球发布。并入方式沿用批1：先 `git merge-base --is-ancestor master <branch>` 验 FF 可行，
再 `git branch -f master <branch>`（不切工作树，避免那条「切分支会删只活在分支上的文件」的老风险），
最后 `git checkout master` + `git branch -d`。
并入后在 master 上补跑轻量两档：`npx vitest run` = `Test Files 69 passed (69)` exit 0、
`npm run lint:e2e` = 0 处 `error TS`。批2 规模**只写命令**：`git rev-list --count 463b5f4..master`、
`git diff --shortstat 463b5f4..master`（`463b5f4` 是并入那一刻的 master，即批2 的 base；
用 `d95f2ef` 当 base 数出来的是批1+批2 合计 107 笔，别混）。

分支 `feature/batch2-disk-usage`。规模**只写命令不写数**（终审点名：本节初稿写的「45 笔 / 17 文件 /
+5499」在它自己那条规则上过期了——收口那一笔提交没法把自己算进去）：
`git rev-list --count master..HEAD`、`git diff --shortstat master...HEAD`、逐笔标题
`git log --oneline master..HEAD`。工作树状态现读 `git status --porcelain`。
**并入要等用户点头**（批1 的先例是 `--ff-only` 并入本地 master，`origin` 是公开仓库，绝不 push）。

## 收口七档（每档取判据行，不取退出码）

| 档 | 命令 | 实测判据行 |
|---|---|---|
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | 第一轮（F3 之前）：文件 **88** · 用例 **469** · 墙钟 **13.8min** · `unexpected 2 · flaky 2 · skipped 21` · `结论 MEASURED` · 复跑判级 **真红 0 · 负载抖动 1 · 悬而未决 0**。<br>第二轮（F3 之后重跑）：文件 **88** · 用例 **470** · 墙钟 **9.7min** · **`unexpected 0` · flaky 3 · skipped 21** · `结论 MEASURED`；三条 flaky 落在 `wafermap-model-not-found.spec.ts:44`、`wafermap-redesign.spec.ts:73`、`view-data.spec.ts:1474`（批1 就记过名的几何 flake），**一条都不是批2 的** |
| 后端全量 | `CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test` | 第一轮 `Ran 2624 tests in 616.323s` / `OK (skipped=16)` / `grep -cE "^(FAIL|ERROR):"` = **0**；第二轮（F3 加了两条 T1 之后）`Ran 2626 tests in 557.748s` / `OK (skipped=16)` / 计数同样 **0**（基线 2576 + 本批 50） |
| 前端构建 | `npm run build`（含 `vue-tsc -b`） | `✓ built in 853ms`，无 TS 诊断 |
| 全量 vitest | `npx vitest run` | `Test Files 69 passed (69)` / `Tests 967 passed (967)` |
| e2e 类型 | `npm run lint:e2e` | `error TS` **0** 处 |
| 行数闸 | `npx vitest run test/unit/lineLimit.spec.ts` | `Tests 15 passed (15)`；**没有给任何文件加豁免** |
| affected | `npm run test:e2e:affected`（Task 8、Task 9 前后各一次） | `RESULT: PASS · 计划 4 档全部执行` |

三档测试数现读：T1 **50**（`test_storage_usage_scan.py` 34 + `test_storage_usage_cache.py` 4 +
`test_files_usage_api.py` 12，其中 2 条是终审 F3 加的）/ T2 **16**（`diskUsage.spec.ts`）/
T3 **10**（`disk-usage-chip.spec.ts`，Task 8 落 7 + Task 9 追加 2 + F3 一条 204）。

## 那条池档的红：归因结论是「不属批2」

全量池 `unexpected 2` 复跑判级只有 `负载抖动 1`，红点是 `combine.spec.ts:122`
（`TimeoutError`：「组合为批次」按钮恒 `disabled`、`title="请先勾选文件"` ⇒ 勾行没生效）。
批1 收口那一轮它是 unexpected 0，所以没有直接放行走「抖动」，做了三次目击 + 一次对照实验：

1. 全量池 slots=4 ⇒ 同一行红（独占复跑判绿）。
2. 只跑 data 档 11 个文件、同样 slots=4 ⇒ `用例 114 · unexpected 0 · flaky 1`，`^  x ` 还是那一行。
3. **对照实验**（`tasks/b2_task10_attrib.py`）：把 `FileListTab.vue` filesVersion watch 里那一发
   `reloadUsage(true)` 改成 `if (false) reloadUsage(true)`，让请求时序**回到批1**，同一批文件同样 slots=4 ⇒
   `用例 114 · 5.7min · unexpected 2 · flaky 3`，**`combine.spec.ts:59` 与 `:122` 照样出 x 行**
   （`:122` 两次 x 后 retry #2 才过）。⇒ **批2 的写后全盘重扫不是必要条件，这条红不属批2**。
   附带损伤只有 disk-usage 的 case 3/7（判据要的行为被实验本身关掉 ⇒ 真红 1），符合预期。
   实验自己废过两轮，都栽在**池的预检会跑 `npm run build`**：注释掉调用 ⇒ `TS6133 未读符号`；
   变异串里写 `#` ⇒ `TS1127 Invalid character`。
4. 机制仍是真的，而且比「批2 让后端变慢」更底层：表格是 EP 内建 `<el-table-column type="selection">`
   （`FileListTable.vue:25`），**整份替换 `files` 数组会清掉已勾选**，`FileListToolbar.vue:57-58` 的
   disabled 直接绑 `selectedCount < 1`；那条用例在 `uploadSingles` 之后不等列表落地就逐行勾
   （同文件 `:144` 倒是等了）。⇒ 「刷新会吞掉用户刚做的勾选」是**产品缺陷**，修法
   （`row-key` + `reserve-selection`，或刷新不接管勾选）批2 不做，记给 e2e 稳定性 / 交互专项。

## 实现前探针的四个数（决定了实现形状，全部现跑）

- **P2** 最大用户树 112 个文件 / 1,612,886,366 B / **11.4 ms** ⇒ ≤300ms ⇒ 走「实扫 + 30s 分桶缓存」，
  **没有建快照表**（规格 §4.4 那条退路没有被触发，这条验收硬条现在有数背书）。
- **P1** 注册行落在 `MEDIA_ROOT/data/<username>` 之外：**0 条 / 0 B** ⇒ 订正② 的两本账是防御性的；
  「目录外 N 条」这句当前不会显示但保留（遗留装机需要）。
- **P3** 根下第一段目录名：`{'single': 98, 'batch': 14}`，无散文件、无未知键 ⇒ `''` 档只能注入测（Task 8 case 4）。
- **P4** `bytes == unique_bytes`：**True** ⇒ 硬链接目前只在 e2e slot 镜像（`scripts/e2e_pool.mjs:113` 的
  `fs.linkSync`）；`unique_bytes` 是绊线字段、不进界面。**这条实测同时否决了 Task 8 初稿的一条判据**：
  slot 树里两字段天然相等 ⇒ 「读错字段」在浏览器里不可见，必须注入差异才谈得上可失败（见计划 Task 8 处置 I2）。
- 差值成因四量（`tasks/probe_batch2_diff_cause.py`，产出订正⑤）：A 磁盘实扫 112 / 1,612,886,366 B；
  B 注册且在册 112 行、漂移 **0 B / 0 条**；C 注册但文件已删 **73 行 / 286,358,763 B**；D 盘上孤儿 0。
  旧口径 ratio **0.1775**（每个装机常年挂一条修复中心已报过的事）／新口径 **0.0000**。

## 两处用户拍板（代码已照此落）

1. **占用 chip 只显体积**（`磁盘占用 1.20 GB`），文件数只在 hover 浮层的分桶行里。根因是左边那颗
   `{{ total }} 个文件` 是列表作用域、chip 的 `file_count` 是整棵树；Task 7 改成激活刷新后
   「Explorer 拷进来的文件更新 chip 却不更新表格」，两个都写就会真的打架。
2. **dev 库里那条 `AuditEvent login_success` 原样保留**（测量登录造成，不删行、不动 `last_login`，
   原值不可恢复），教训写进 lessons：**测量脚本不得对运行中的服务发登录**。

## 终审与 F3 那一轮（2026-11-14，并入前完成）

整批终审交回 4 条，逐条复验后处置见计划同一文件的「终审（整批一次）判定与处置」一节
（提交 `1434596` 三条 + `2698383` F3）。这里只记 F3 的**结果与代价**，因为它改了产品代码：

- 用户拍板选 (a)：**视图早退 204**，不冒 500。实现把「用户名能否当目录名」这条判据从
  `_user_data_root` 的 raise 条件里提成 `storage_usage.is_safe_username`，视图与存储层共用一份
  （不是各写一份再指望它们同步）。顺手改掉视图头注那句「没有目录穿越面」——用户名照样拼进路径，
  穿越面是有的，只是挡在这一层。
- 判据分两层且互点名字：T1 钉「`..` ⇒ 204 / 空 body / `data is None`」+「带点号的正常账号 `a.b`
  照旧 200 全 13 字段」（后一条证明这是**白名单式早退**，不是「凡 ValueError 都吞」）；
  T3 钉前端半边「204 ⇒ 不画 chip、零条错误提示」。
- **反证跑在错误的层上，被实测当场推翻**：我在 T3 注释里写「视图改回 500 这条必然红」，真改完跑独占池 ⇒
  `unexpected 0` 十例全绿。根因是 `page.route().fulfill()` 把真实响应整个遮掉，后端状态码在这条通路上
  不可观察。同一个变异拿去 T1 ⇒ `Ran 12 … FAILED (failures=1)`，只 FAIL 新加那条 ⇒ 契约归位，
  注释也已改成实话。这是本批第四次「推理说成立的判据，实测一层都过不去」（前三次见计划 Task 8/9 处置）。

## 批2 遗留清单（别当已完成，也别顺手改）

- **F3 的另一半仍待排批（用户选的是只收 (a)）**：同根因的更大那条没动——`_helpers.py:172`
  `_user_upload_dir` 对 `..` 这种用户名会拼出 `<MEDIA_ROOT>/data/../single`，**上传路径等于逃逸用户目录**。
  正解是在账号创建处挡掉 `.`/`..`（`UserCreateSerializer` 是 ModelSerializer，`username` 目前只走
  Django 默认校验器，实测接受 `..`），属 accounts 层，建议并进批4 或单独一小批。
- `combine.spec.ts` 的勾选被迟到列表响应清空（上面第 4 条）⇒ 产品级缺陷 + 争用 flake，两个账都记在这一条上。
- 同形态原型键查表两处未动：`ChartDock.vue:141`、`ExportTemplateSettings.vue:91`（键都是闭合集合，当前不可达）
  ⇒ 谁下次碰这两个文件就顺手换 `Object.hasOwn` 并补一条原型名键判据，别再攒第三次。
- `FileListTab.vue` 那四个 sibling loader 仍是 `onMounted`-only ⇒ 表格不随激活刷新，与 chip 口径不一致；
  要改需要自己的请求计数判据，另批做。
- `USAGE_TRAIL_MS=800` 与 e2e 里那个 2000 ms drain 常数是硬耦合，改一处必须同改另一处。
- `Task 7 的 ③（过期响应序号守卫）与 ⑤⑥` 仍只有代码没有判据。
- `C:\lqdp-e2e\slots` 现有 **362** 个 RUN_ID 目录、`C:\lqdp-e2e` 共 **7.7 GB**（崩池/超时轮有意保留，内含日志与证据）
  ⇒ 没清理，要不要清等用户说。

## 下一步（2026-11-14 用户拍板后订正）

批3 的**两处开口都已定**，设计稿与计划照此订正完毕：

1. **删除作用范围 = 只删已展示的组**（用户复述「只删已展示的组，需要」）⇒ 设计稿 §5.4 决策 A 成立，
   同日探针把它从假想边界变成实测事实：本机 `admin` 有 **73 组**重复，已越过 50 的切片
   ⇒ 改完后一次点击只清前 50 组，剩下 23 组要「重新检查」再删一次，界面必须说清楚。
2. **用户管理的前端搜索 / 角色筛选移出批3、进批4**（用户：「进批4」）⇒ 设计稿 §6.2 决策 D 改写，
   批3b 只交付工具栏**壳**（左槽照建、暂空），批4 往里塞东西不再动结构。

拆批与计划落点：

- **批3a**（第 3 项 重复项选保留）：`docs/superpowers/plans/2026-11-14-batch3a-duplicate-keep-selection.md`
  （10 个 Task，Task 1 是纯搬迁因为 `_helpers.py` 只剩 48 行余量、`tests.py` 冻在 1959 行）。
- **批3b**（第 2 项 两页统一 toolbar）：计划待批3a 收口后写。两处独立、不共用文件，合成一份计划
  只会让门禁档位互相污染。
- **批4** = 未封顶下拉两处 + 批1 遗留 + 决策 D（搜索/角色筛选）+ **修复计划四条**
  （设计稿新增 §10：`combine.spec.ts:122` 的勾选被迟到列表响应清空、`..` 用户名上传逃逸、
  两处原型键查表、`FileListTab.vue` 四个 sibling loader 不随激活刷新）。
- 探针脚本 `tasks/probe_b3a_dup_shapes.py`（gitignore 区，只读、不写库、不发 HTTP）：
  五个数已写回设计稿 §5.2/§5.4 与计划头部，其中「体积最大」那颗策略按钮**因组内 `file_size`
  恒等而作废**。

# 任务：批3a 重复项选保留（2026-11-15，计划 Task 10 收口；计划 `docs/superpowers/plans/2026-11-14-batch3a-duplicate-keep-selection.md`）

## 状态：**已 `--ff-only` 并入本地 master，未 push**

`master` 在**并入那一刻** = `0ecb39d`（本批最后一笔），台账这一笔在它之后 ⇒ 谁再
`git rev-parse --short master` 会数到更大的值，那是对的，别把它当本批的 tip。
base = `77edb01`（批2 收口那一刻的 master）。
过程分支 `feature/batch3a-dup-keep-selection` 已 `git branch -d` 删除（删除时它正指向 `0ecb39d`
⇒ 没有任何提交只活在分支上）。并入写法沿用批1/批2：先 `git merge-base --is-ancestor master <branch>`
验 FF 可行，再 `git branch -f master <branch>`（不切工作树，避开「切分支会删只活在那条分支上的文件」），
最后 `git checkout master` + `git branch -d`。**全程没有 push**：`origin` 是公开仓库，
一次 push 即全球发布（`git status` 那句「ahead of 'origin/master' by 141 commits」就是现状）。
并入时工作树只有**另一会话**未提交的 4 个文件（`apps/export/charts.py`、
`apps/export/export_batch_charts_xlsx.py`、`test/backend/test_export_histogram_grid.py`、
未跟踪 `apps/export/tests_histogram_style.py`）——本批一律没碰、没 stage、没提交。

规模**只写命令不写数**：`git rev-list --count 77edb01..master`、
`git diff --shortstat 77edb01..master`、只算代码 `git diff --shortstat 77edb01..master -- ':(exclude)docs/'`、
逐笔标题 `git log --oneline 77edb01..master`。

## 收口七档（每档取判据行，不取退出码；输出整段落盘再 grep，禁 `| tail`）

| 档 | 命令 | 实测判据行 |
|---|---|---|
| 后端全量 | `CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test` | 第一轮（终审修复前）`Ran 2651 tests in 936.674s` / `OK (skipped=16)`；**终审修复后重跑** `Ran 2662 tests in 936.338s` / `OK (skipped=16)`；两轮 `grep -cE "^(FAIL|ERROR):"` 都是 **0**（`tasks/b3a_backend_full.log` / `b3a_backend_full2.log`） |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | 第一轮 `文件 88 · 用例 472 · 墙钟 10.5min · unexpected 0 · flaky 4 · skipped 21 · 结论 MEASURED`；第二轮（修复后）`用例 474 · 10.8min · unexpected 0 · flaky 1 · skipped 21 · MEASURED`。两轮红点都**不是本批的文件**：第一轮四条是 `wafermap-redesign.spec.ts:41`、`wafermap-model-not-found.spec.ts:124`、`view-data.spec.ts:1474`、`element-plus-styles.spec.ts:343`；第二轮只剩最后那条（从 `slot213956-50964/slot*.run.log` 现挖，不在 merged.json 里） |
| 全量 vitest | `npx vitest run` | `Test Files 71 passed (71)` / `Tests 992 passed (992)`（第一轮 990，终审 +2 条字面判据） |
| e2e 类型 | `npm run lint:e2e` | `error TS` **0** 处 |
| 前端构建 | `npm run build`（含 `vue-tsc -b`） | `✓ built in 823ms`，零 TS 诊断 |
| 行数闸 | `npx vitest run test/unit/lineLimit.spec.ts` | `Tests 15 passed (15)`；**没有给任何文件加豁免** |
| affected | 批内 `node scripts/e2e_affected.mjs`（Task 8 / Task 8 返工各一次）；收口 `--base master --dry-run` | 批内两轮 `RESULT: PASS · 计划 5 档全部执行`；收口判 `decide: 全量 e2e（兜底命中）` 4 档 = lint:e2e / vitest / backend / e2e:全量 ⇒ **上面几轮是它的超集**（`tasks/b3a_affected_base_master.log`） |

三档测试数现读：T1 **31**（`test/backend/test_duplicate_keep_selection.py`，其中 11 条是终审修复轮
`c0b48bf` 加的覆盖闸门与计数判据）/ T2 **25**（`dupKeep.spec.ts` 16 + `dupKeepWiring.spec.ts` 9）/
T3 本批 **5** 条（`repair-center.spec.ts` 里 366/407/437/513/544 那五条；该文件共 9 条）。

## 实现前探针的数（2026-11-15 收口时又跑一遍，`tasks/_b3a_probe_final.log`）

只读脚本 `tasks/probe_b3a_dup_shapes.py`（不写库、不发 HTTP、不登录，跑 dev 库）：

- **P0** 全库重复组 **73**，涉及用户 **1** 个（`admin`）。
- **P1** 组内 distinct `file_size` 分布 `{1: 73}` ⇒ **「体积最大」在数学上不可能选出与「按 id 最小」
  不同的东西**，那颗按钮于 2026-11-14 作废（用户拍板「宁可少一颗」）。
- **P2** 组内 distinct `created_at` 分布 `{2: 73}`，73/73 可分先后 ⇒ 「最早/最新」两颗是真策略。
  样本差的是「同一文件两次导入」，跨度可到两个月。
- **P3** 每组 >2 文件的组数 **0**；单用户最大组数 73；**超过 50 组的用户 = `['admin']`**
  ⇒ 展示切片边界在本机**现实可达**：一次点击只清前 50 组，剩下 23 组要重新检查再删一次。
- **P4** `_group_duplicates(admin)` 两次调用逐字相同 `True`；但「前 50 组」≠「全量组」`False`
  ⇒ 「展示切片 == 处理切片」必须由同一个排序键维持，不能靠两个 limit 常数互相对齐。
- **P5** `DataFile` 总行数 185（读一遍的量级参考）。

## 两处用户拍板 + 一处移出

1. **决策 A：只删已展示的组**（2026-11-14「只删已展示的组，需要」）——语义反转，改前是
   「显示前 N 组、删掉全部」。终审给这条补了**反向闸门**（§5.3 第 3bis 条）才算真钉住。
2. **决策 D：两页 toolbar 的前端搜索/角色筛选移出批3、进批4**（「进批4」）⇒ 批3b 只交付壳。
3. **批2 遗留两条产品级缺陷加入修复计划**（「加入修复计划」）⇒ 设计稿 §10 FIX-1..FIX-4，批4 承接。

## 变异反证表（M1–M25 + F 系列；**等价变异与判据洞按实测写，不许标成「抓住」**）

| 号 | 变异 | 结果 |
|---|---|---|
| M1 切片外 id 放行 / M2 删同组两枚的 raise / M4 默认回落取 `files[-1]` / M6 先删再校验 / M9 POST 切片改回全量 | 后端 | **红**，且红在预期的那一条 |
| M3 去掉 `isinstance(raw, bool)` | **第一版全绿**（本批第一次「反证没咬住」）。根因不是变异等价，是断言只比异常类型（`hash(True)==hash(1)`）⇒ 拆成两条 + `assertRaisesRegex(..., '整数数组')` 钉**是哪道闸门生效**后重跑 `FAILED (failures=1)` |
| M5 `remaining_groups` 回算术 `总数 − len(displayed)` | **实测全绿 = 判据洞**（计划当初预测它会红，错了）。两句在可达形状里恒等；顺带推翻我自己写的「算术会虚报」——塌组发生在调用之前。选实测的真实理由是**不依赖前提**，不是能钉分歧 |
| M8 `except InvalidKeepSelection` → `except ValueError` | **已知不可区分**（子类关系），不许声称判据抓得住它 |
| M7 `or []` 改成直传 `None` | 红，但**机制订正**：红在视图的 `isinstance(list)` 闸门，不是 `for raw in None` 抛 `TypeError`→500 |
| M10 回落改 `files.at(-1)` / M11 一键策略不滤已改选 / M12 截断文案改回「作用于全部」/ M13 比较符互换 / M14 加回 `largest` 标签 | 前端纯函数与文案 | **红**（M12 两条、M13 双向） |
| M15 `@click="submit"` → `@click="emit('fix')"`（丢载荷） | 原判据 `/emit\('fix',\s*resolveKeepIds\(/` **无牙**；换成形状判据后才红。另记：绊线红只覆盖 api 调用点，处理器内丢载荷仍 8/8 绿且 `vue-tsc` 看不见 ⇒ 只能由 T3 case2 抓（`dfb006d`） |
| M16 删 `:data-keep` / M17 恒带 `keep_ids: undefined` / M18 删回执尾巴 | **红**（绊线 + T3） |
| M19 后端 `keep` 恒取 `files[0].id` | 整跑红在 case2；**case3 单跑也独立红**（`--grep=B3A-T8C3`，终态 `K2-B` 期望 vs `K2-A` 实收）⇒ 我先写的「后端侧只是等价推断」作废 |
| M20 `pending` 回 `files[1:]` / M21 `:data-keep` 三元反过来 | **红**（M20 红在终态不是 toast；M21 红在 `toHaveAttribute` 而两支文案照旧通顺） |
| M22 `resolveKeepIds` 只上报 touched | **1 红**（打在 7b3d763 的 15 例上）。⚠ 我曾把「全仓零拦阻」写进提交 `2d44e9c`，那是没实测就传播的结论，`75507fb` 撤回 |
| M23 一键策略盖到所有组 / M24 `:disabled` 去掉 `!deleteConfirmed` / M25 `applyStrategy` 硬编码 `earliest` | 返工轮（`ec458bc`）**各自红**：M23/M25 在 case3，M24 在 case1 那句 `toBeDisabled()`。M25 在返工**前**三档全绿 ⇒ 那颗策略选项当时在全仓是隐形的 |
| F-1a 摘掉反向覆盖闸门 | 3 例红，其中 HTTP 那条报 `200 != 400 : {'deleted_count': 2}` —— 就是那次静默删除本身 |
| F-1b 覆盖闸门不分空载荷（把兼容写死） | module 8 / tier3 9 条红，含 `test_51组…` `400 != 200` 与 `apps.datafiles` 2 条 ⇒ 反向证明 legacy 分支**真有靶子**，不是空话 |
| F-2 `deleted_count += 1` 改回无条件 | 恰 1 条红（`2 != 1 : 被占用那只不算进计数`）。`本来就没有文件` 那条**故意不红** —— 它防的是反向过度修正 `if unlinked is None: continue` |
| F2-a 标签改回「未改选的组默认保留」 | T2 绊线 + T3 `[B3A-F2A]` `toHaveText` 红（Exp「一键策略…」/ Recv「未改选的组默认保留」） |
| F2-b 未改选也跟随策略（回落 `strategyKeepId(g,'latest')`） | T3 `[B3A-F2A]` 的 `data-keep` 与终态红 + T2 `resolveKeepIds` 红 |
| F2-c 摘掉 `:truncated-note` | **分层实测**：T2 层 25 例全绿（缺口属实）；但按字面只摘绑定时**池跑不起来** —— `globalSetup` 先 `npm run build`，`vue-tsc` 立刻 `TS6133`。摘干净（binding+computed+import）才走到 T3 `[B3A-F2NOTE]` 红在 `toContainText`。⇒ 证据链写成「T2 缺口 + build 是第二道闸」，不许写成「浏览器层毫无反应」 |
| F2-d 卡片文案回旧字面量 | T2 两条红（整句 `toBe` 与新加的 `toMatch(/本批不处理/)`） |

## 遗留清单（都不在本批做，各有归属）

1. **`frontend/e2e/data/repair-center.spec.ts` 现 591/600 行** ⇒ 批4/批3b 动它之前必须先拆
   `e2e/data/duplicate-keep.spec.ts`（设计稿 §10 已写成硬前置，含拆分时要核的三件事）。
2. **`browse_views.py`（520 行）形状**：4 个内联分支 + 4 个转调兄弟混在一个 `post()` 里；终审建议抽
   `_delete_duplicates(user, action)`。本批不抽 —— 那是形状重构不是修缺陷，且批4 加选项才知道要什么形状。
3. **§10.1 UX-1**：单击已选中 radio 标不出「已改选」，要两击才能表达「就要默认这份」。工效缺口，归批4。
4. **`C:\lqdp-e2e` 下 slot 目录累计约 7.7 GB**，用户明确说先不清。
5. **本机 dev 库 admin 仍有 73 组真实重复**未清理（是用户的实数据，批3a 只给它选了保留的口子，
   没替用户删任何东西）。
6. **另一会话的 `apps/export/*` 未提交改动**还挂在共享工作树上；收口两轮后端全量数
   （2651 → 2662）里含它们那 5 条测试，对账见上表。

# 任务：批3b 两页统一 toolbar（2026-11-15，计划 Task 7 收口）

## 状态：**已收口，未 push**

过程分支 `feature/batch3b-toolbars`，base = `5b3af88`（批3a 收口后的 master）。
**收口时 tip = `8f1db98`**（计划与台账这最后一笔在它之后，别拿 `git rev-parse master` 当本批 tip）。
全程**没有 push**；`origin` 是公开仓库。工作树里另一会话的
`apps/export/*`、`apps/weight/xlsx.py`、`apps/common/sheet_names.py` 等未提交改动本批一律没碰、没 stage。

两份计划（按顺序执行，第一份产出共享壳，第二份消费它）：

1. `docs/superpowers/plans/2026-11-15-batch3b-audit-toolbar.md` —— 共享壳 `AdminPageToolbar.vue` + 操作审计页；
2. `docs/superpowers/plans/2026-11-15-batch3b-user-management-toolbar.md` —— 用户管理页
   （KPI chip / 共用表单对话框 / 工具栏右槽）+ §6.5 死规则收敛 + 主题 T3 + 介绍书 + 收口。

## 收口七档（每档取判据行，不取退出码）

| 档 | 命令 | 实测判据行 |
|---|---|---|
| 后端全量 | `CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test` | `Ran 2674 tests in 571.971s` / `OK (skipped=16)`；`^(FAIL|ERROR):` 0（`tasks/b3b_final_backend.log`） |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | `文件 89 · 加权总量 1061s · 计划 slot 4`；`用例 478 · 墙钟 9.8min · 单价 2.97s/例 · unexpected 0 · flaky 0 · skipped 21 · 结论 MEASURED`（`tasks/b3b_final_pool.log`） |
| 全量 vitest | `npx vitest run` | `Test Files 73 passed (73)` / `Tests 1012 passed (1012)`（`tasks/b3b_final_vitest.log`） |
| e2e 类型 | `npm run lint:e2e` | `error TS` **0** 处（`tasks/b3b_final_lint.log`） |
| 前端构建 | `npm run build`（含 `vue-tsc -b`） | `✓ built in 829ms`，零 TS 诊断（`tasks/b3b_final_build.log`） |
| 行数闸 | `npx vitest run test/unit/lineLimit.spec.ts` | `Tests 15 passed (15)`；**没有给任何文件加豁免**（`tasks/b3b_final_linelimit.log`） |
| affected | `node scripts/e2e_affected.mjs --base master --dry-run` | `decide: 全量 e2e（兜底命中）` 4 档 = lint:e2e / vitest / backend / e2e:全量；`RESULT: PASS · dry-run` ⇒ 上面全量池+后端是它的**超集**（`tasks/b3b_final_affected_dry.log`） |
| 介绍书 | `npm run intro:build` + `node scripts/intro/check.mjs` | `build complete in 2.09s`；`INTRO-CHECK PASS · 截图 8 · 导航 17 · 组件 23 · 源文件 41 · 版本 v0.8.0 同源`（`tasks/b3b_final_intro_*.log`） |

三档测试数现读：**T1 0**（后端零改动；后端全量里的 2674 例是既有套件）/
**T2 新增 20 条**（`adminToolbarWiring.spec.ts` 6 + `adminUserFormWiring.spec.ts` 14；`roleLabelHygiene.spec.ts`
8 条不变、判据 ④ 的目标从 `UserManagement.vue` 迁到 `UserFormDialog.vue`）/
**T3 新增 4 条**（审计页盒宽 1 + 用户管理 KPI/工具栏 1 + 主题 2）；`audit.spec.ts` 两条既有日期流程
加了 `dismissDatePanel()`（点页面标题关面板），断言未削弱。

## 实施期的偏差与判定

- **审计页 1280 换行**：日期面板会盖住右槽「查询」，E2E 用点标题关面板规避（Escape 会清空已输入值）；
  这是真实产品/UX 开口，已记下方「产品开口」，不在批3b 修。
- **B3 评审发现对话框 input/footer 样式够不到 teleport 子组件**：B5 把三条 input 深规则搬进
  `UserFormDialog.vue`、删掉页面死规则，并补了对话框输入框的 light 基线/night 覆写 T3。
- **B5 复审发现第三处死规则** `SettingsPage.vue:313`：写域外，已记下方「产品开口」，归批4/独立小批。
- **B6 复审前扩围**：`data.ts` 的管理功能卡仍写「创建账号 / 四卡」，与实现不符；已补一笔 docs 提交
  `8f1db98` 同步，介绍书 build/check 通过。
- **A4 中间档的一次 backend 红**：默认 affected 只在未提交改动上选例（选到了另一会话的 exports），
  backend 红在 `test_job_cancel` 的负载时序用例；隔离复跑 `Ran 1 test ... OK` ⇒ 负载 flake，不属批3b。
  B7 收口后端全量 `OK`，该 flake 未复发。

## 明确不做（别在收口时顺手扩）

- **决策 D（用户管理左槽搜索/角色筛选）仍归批4**；批3b 左槽留空，`users` 列表过滤逻辑未动。
- 本批**不动** `frontend/e2e/data/repair-center.spec.ts`（591/600）；拆
  `e2e/data/duplicate-keep.spec.ts` 是批4 的硬前置。
- 不 push；并入本地 master 需用户点头（沿用批1/2/3a 的 `--ff-only` 流程）。

## 实现期发现的产品开口（待拍板，不阻塞批内收口）

- **1280 视口下日期面板盖住右槽「查询」**（2026-11-15 审计页 A2 实测）：工具栏左槽在 1280 换行，
  右槽「查询」落到第二行（x1183–1243, y169–201），打开的日期面板（x942–1266, y125–468）正好覆盖它；
  `elementFromPoint(按钮中心)` 命中的是日历表头。真实用户输入日期后直接点「查询」会被面板吃掉一次点击，
  且可能误选日期格。当前 e2e 用「点页面标题关面板」在两条既有日期流程里规避（Escape 实测会清空已输入值），
  没有削弱断言；产品侧修法属壳级（弹层 placement / 单行布局 / 右槽避让），不在批3b 范围。
  **归属：产品/UX 拍板，批4 或单独一批处理。**
- **第三处 `.el-select .el-input__wrapper` 死规则**（2026-11-15 B5 复审现查）：
  `frontend/src/pages/settings/SettingsPage.vue:313` 仍有该规则，且该页模板零 `<el-select>`。
  批3b §6.5 只点了两处（`UserManagement.vue` 与全局主题层），这是写域外的第三处；
  属 settings 页，**归批4 或独立小批**，别在批3b 顺手改。
