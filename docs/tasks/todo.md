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
