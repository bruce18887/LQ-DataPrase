# 任务：良率批次报表 UI 优化（2026-08-29）✅

用户 7 项反馈：删顶部 KPI 卡片 / 趋势 X 轴对齐 / QA 校验紧凑化 / 明细表更多行 /
Site 矩阵表头撑满 / Bin×Site·Site 良率·GAP·UPH 随阶段切换 / GAP 不以大面板展示。

## 实施清单

- [x] `utils/batchAggregation.ts`（新）：纯 TS 聚合 `aggregateSiteYield` /
  `aggregateBinSiteTable` / `aggregateUph`，算法与后端 `apps/batch_report/aggregation.py`
  逐行对齐 → 阶段过滤时前端从 `phases[]` 现算，后端零改动
- [x] `BatchYieldTab.vue`：删除 `batch/KpiCards.vue`（658→452 行，拆出 `BatchBinSection.vue`）；
  阶段过滤态 Site/Bin×Site/UPH/整体良率全部改为前端聚合；阶段明细表 max-height 350→560；
  Site 良率矩阵 width→min-width 弹性撑满
- [x] `PhaseSummaryTree.vue`：新增「总览条」（投入/Pass/Fail/良率，Fail 红、良率阈值色），
  随阶段胶囊联动（阶段过滤时显示该阶段汇总值）
- [x] `QaValidationBar.vue`（新）：QA 校验单行条（✅/⚠️ + 期望/实际），替代原整卡表格
- [x] `YieldTrendChart.vue`：X 轴唯一标签（phase-Wxx）+ `interval: 0` + 标签多时 45° 旋转
  （修复 ECharts 自动跳签导致的「坐标与柱子对不上」）
- [x] `SiteYieldAnalysis.vue`：`compact` 模式（批次页）：去右侧 gauge+统计大面板，
  改为单面板全宽柱图 + 头部 3 个 GAP pills（最高/最低/差异）；单文件仪表板保持原样
- [x] e2e：`batch-phase.spec.ts` 追加总览条/QA 门控/pills/UPH/Bin×Site Total×阶段 4 倍断言；
  `batch.spec.ts` 陈旧 4 用例显式 skip（旧 /batch 页面已下线，此前已被 todo 2026-08-28
  标记为遗留清理项）+ 阶段明细表用例改为新导航 + KPI 测试改为总览条断言

## Review（2026-08-29）

- 阶段联动的数据完备性：`batch_yield_data` 每 phase 已带 site_total/site_pass/bin_info
  （含 per-site）/uph → 前端聚合可行，且 e2e 实测「全部阶段 Bin×Site Total = UIS 阶段 ×4」
  精确认证了前端聚合与后端批次级数据一致（4 个相同样件文件）
- 构建/验证：`npm run build`（vue-tsc + vite）通过；`batch-phase.spec.ts` 3/3 绿；
  `batch.spec.ts` 总览条/阶段明细表在有批次数据时通过、无批次时优雅 skip
- ⚠️ 遗留（非本次改动引入）：fresh-seed 环境下 DashboardPage 单文件 pane 存在既有
  render 崩溃——`/summary/` 返回缺 `metrics` 时 `metrics.value = d.metrics` 赋 undefined，
  模板 `metrics.yield_pct` 抛 TypeError（DashboardPage.vue:196/207），导致该环境下
  dashboard.spec 三个批次良率用例的 tab 切换全挂；已用 `git stash` 对比原代码复现
  （改动前后行为一致），建议后续在 DashboardPage 对 `d.metrics` 做兜底默认值
- ⚠️ 环境注意：e2e 必须用 Playwright 自起后端（`LQDP_SYSTEM_CONFIG_FILE` 指向项目根）；
  复用本机 dev 后端时其 `system_config.json` data_dir=用户主目录，`/batch-dirs/import/`
  会对项目根下的测试目录返回 404（排查耗时点）

---

# 任务：SFTP 目录/批次下载进度改为按总字节实时显示（2026-08-30）✅

> ⚠️ **同日重做记录**：用户误还原代码（工作区回到 HEAD，代码改动全部丢失）。
> 已按本任务原方案**完整重放**并重新验证：后端 72 项、vue-tsc+build、e2e
> reconnect 8/8 全绿（后端日志确认 download_dir 200/344B SSE 流畅结束）。
> 重放期间顺带修复两个既有 e2e 缺陷：
> ① 单文件下载用例最终轮询仍搜 `?search=big.csv`——`icontains` 匹配不到
> `big_<ts>.csv`（重名时间戳后缀），改为 `search=big` + 文件名前缀过滤；
> ② 确认「串行文件内前一用例失败 → 后续用例 did not run」的排障盲区。

> 用户反馈：单文件下载进度改版后，**目录（批次）下载的进度条像卡死一样一直停在
> 1%**；要求改为**根据下载的总大小来显示百分比**。

## 根因（实测代码定位，非猜测）

- 旧 `download_dir` 的 SSE 进度：`sftp.get()` **阻塞式整文件下载**，进度事件只在
  **每个文件整体下载完成后**才发一次（percent = 已整文件字节 / 总字节）。
  第一个事件甚至要等第一个文件下载完才出现 → 大文件传输期间进度条停在 0%/1%，
  看起来像卡死。前端 `dlProgress` 也把 `bytes_done/total_bytes` 清零未透传。

## 实施清单

- [x] 后端 `apps/sftp/downloads.py`：抽出 `iter_remote_chunks`（256KB 分块读取，
  单文件/目录共用）；`download_file_events` 改为其上层；新增
  `download_dir_events` —— **分块到达即按「累计下载字节/远端总字节」发进度**
  （0.1s 节流 + 每文件至少一次补偿事件），单文件失败清理半截后继续，
  整体超时/断开清理半截 + invalidate（与单文件同语义）
- [x] `views.py`：`download_dir` 内联生成器移除，改用 `download_dir_events`
- [x] 前端 `SftpBrowser.vue`：目录下载透传 `bytes_done/total_bytes`；
  `SftpDownloadProgress.vue` 目录模式展示「N/M 文件 · 已 xx / 总 yy」；
  `api/sftp.ts` `SseProgressData` 补可选字节字段
- [x] 后端测试 `apps/sftp/tests_download_dir.py`（6 项：按总字节单调进度 /
  大文件中间事件 / 单文件失败续传+清理 / 超时中止 / GeneratorExit / API 契约）
- [x] e2e `reconnect.spec.ts` 新增「目录下载进度卡片按总字节显示并完成导入」
- [x] 验证：sftp 后端 72 项全过、vue-tsc + vite build 通过、e2e 8/8 全绿、
  端口释放后恢复用户 dev 服务

### Review（2026-08-30）

- 目录下载进度与单文件下载完全同构：percent = 实际累计下载字节 / 远端总字节，
  **分块到达即更新**（0.1s 节流，每文件至少一次补偿事件），大文件传输期间
  百分比平滑前进，不再「卡在 1%」；失败/超时/断开的半截文件清理与 invalidate
  语义与单文件一致（顺带修掉旧实现「单文件失败不清理残片」的隐患）。
- 兼容性：`download_dir` 端点与事件契约不变（progress 增补
  `bytes_done/total_bytes` 字段），旧前端照常工作；前端目录卡片新增
  「N/M 文件 · 已 xx / 总 yy」字节展示。
- 真实验证（首次实现时）：用户真实 SFTP `/te/Test_Data/JTSC/FT/BPD80590`
  目录下载 5 分钟 SSE 流畅跑通（~10 事件/秒，200/774KB），非 env-gated e2e
  无法覆盖真实服务器，但本地 paramiko 服务器 e2e 全绿。

---

# 任务：两个仪表板完全重建（主题 token 化 + 五层 IA）（2026-08-28）✅

> 设计文档：docs/plans/2026-08-31-dashboard-rebuild-design.md；用户确认"按推荐执行"。

- [x] P0 设计系统地基：token 扩充/浅色 EP 对称块/useChartTheme 语义色/全组件去字面 hex/删 47 条全局 night 覆盖/删 8 个孤儿组件/Card-Button-Badge 指南对齐
- [x] P1 共享组件库（PageHeader/ContextBar/KpiStrip/SectionCard/StatGrid/YieldBadge/CpkBadge/ChartPanel/QualityBanner/DrilldownDrawer）
- [x] P2 单文件分析仪表板重建（五层 IA；UPH 并入 KPI；告警横幅；Bin 三视角；测试项总览保留）
- [x] P3 批次良率看板重建（ContextBar+阶段胶囊→KPI 六卡→趋势/阶段汇总→明细→Site 矩阵→Bin 抽屉；删与单文件页重复三小节；BatchYieldTab ≤600 行拆分）
- [x] P4 分析页单文件 Tab 对齐（StatGrid；表头 token 化；死代码清理）
- [x] e2e 维护：dashboard/batch-phase/axis-label-precision/night-visibility 更新；批注 batch.spec.ts（/batch 已下线）陈旧待清理
- [x] vue-tsc -b + vite build 通过；dashboard(15 pass/2 env-skip)/theme/batch-phase 定向 e2e 全绿；全量回归见 lessons flake 说明

### Review（2026-08-28）
- 视觉一致性：三层颜色体系归一为"CSS token + useChartTheme 语义色"两源；浅色 EP 主色从出厂 #409eff 修正为品牌 #2563eb；night 图表首色 #fdd835→#f9a825。
- 重复消除：Yield/Fail/CPK/Bin/Site/UPH 各保留"一个主呈现+视角切换"；批次页与单文件页重复三小节删除并改为阶段下钻抽屉；分析页统计卡统一 StatGrid。
- 信息架构：两看板均为 ContextBar→KPI(6)→主网格(8/4)→明细表→下钻抽屉 五层。
- 遗留（建议后续）：batch.spec.ts 陈旧用例清理；DataBrowserAgGrid/UserManagement 等页面的浅蓝残留（本轮范围外）；MultiFileChart 正态曲线按 lot 色（有意保留）。

---

# 任务：项目 UI 设计指南（三层 Design Tokens）静态 Demo（2026-08-29）✅

> 设计文档：docs/specs/2026-08-29-design-system-tokens-demo-design.md；用户已确认
> （展示页 + 仪表板/分析页代表页 · 三层 token · 先只交 demo · light 蓝/night 金）。

## 实施清单

- [x] `docs/plans/design-system-preview.html`（新，单文件自包含，约 1300 行）：
  Primitive(--p-*) / Semantic(双主题) / Component 三层 token + 色板/排版/间距/组件画廊/图表色板双主题对照 + 仪表板 + 分析页代表页（纯 SVG 静态图表）
- [x] 浏览器验证：双主题切换 / 3 视图渲染 / 无控制台报错 / 截图留档（6 张）
- [ ] 用户确认风格后：产出 Markdown 指南 + 可落地 tokens.css（下一轮）

### Review（2026-08-29）

- 交付物：`docs/plans/design-system-preview.html`（零依赖，双击即开）。三层 token：
  Primitive 6 色族（--p-*，从现有 light/night 配色提炼）→ Semantic（--bg/--text/--brand/--chart-1..8/--spc-* 等，
  :root[data-theme] + .force-light/.force-night 双选择器）→ Component（表格/徽标/KPI accent 等 color-mix 派生）。
- 验收：Browser 子代理两轮实测（首轮发现脚本初始化顺序缺陷：applyTheme 早于 semTokens 赋值
  导致整段脚本中断，修复后复验全绿）：双主题切换实时生效、三视图全部渲染、
  对话框/抽屉/Toast 交互正常、控制台 0 报错；除 token 定义块外无字面 hex（新增 --on-brand 收敛品牌底上的前景色）。
- 截图：test/screenshots_night/ds_step*.png（light token 页 / night token 页 / 单文件仪表板 /
  批次看板 / 分析页直方图 / 序列图）。
- 后续：用户确认风格 → 出 Markdown 指南 + tokens.css 落地方案（含 variables.css 迁移映射）。

---

# 任务：按设计指南完成 UI Token 迁移（四批）（2026-08-29）✅

> 设计文档：docs/specs/2026-08-29-ui-token-migration-design.md（本地，不入仓库）；
> 用户已确认：四批一次到位 / CVD 过则切序列色 / 直接采新值 / 分批硬替换。

## 实施清单（指南 §9.2 顺序）

- [x] 批 1：main.ts 接入 design-tokens.css（variables.css 之后）；非颜色旧变量搬入新文件；
      pages/dashboard/** + components/common/* + components/layout/* 按映射表替换；
      build + theme/dashboard e2e → commit（0b03b77，顺带修 DashboardPage metrics 兜底存量崩溃）
- [x] 批 2：pages/analysis/** + pages/data/** 替换；build + 相关 e2e → commit（122f96e）
- [x] 批 3：其余页面清零旧引用；element-plus-theme.css 按指南 §6.3 对齐（新增完整 light 块、
      night warning→#ffd54f、双块对称）；typography.ts 字体栈核对；删 variables.css 与 import；
      build + theme/fonts e2e + 双主题截图留档 → commit（f939765 / 3b59b35）
- [x] 批 4：echarts-theme.ts 轴系/文本/tooltip 按 §6.2 对齐；CVD 复验（tasks/cvd_verify.mjs）
      新色板未过（light 灰/青绿 deutan ΔE=7.6、night 浅蓝/粉红 deutan ΔE=13.6）→ 按口径维持现序列色；
      build + 图表相关 e2e → commit（4ae5800）
- [x] 收尾：全量 e2e 回归（存量失败按 R2 判定）；释放端口；双主题截图留档；Review 追加

### Review（2026-08-29）

- 终态达成：design-tokens.css 为唯一 token 事实来源；variables.css 已删；全库 scoped 样式
  只引用语义层（grep 清零）；EP 双主题块对称（light 新增完整块，出厂蓝 #409eff 回潮风险消除）。
- CVD 复验结论：现行序列色基线 PASS（脚本口径与历史注释一致）；指南 §3.5 目标色板双主题
  均未过相邻色 ΔE≥15 → 按用户确认口径维持现序列色，仅轴系/文本/tooltip 对齐（指南 §6.2 允许）。
- 值差异点实装：--text-3 #9ca3af / --warn light #92400e / night 边框 0.10/0.18 均取新值，
  双主题截图（test/screenshots_night/token_batch3_*.png）目测无失色区块。
- 顺带修复两个存量问题（均经 baseline/DB 取证非本次引入）：
  ① DashboardPage /summary/ 缺 metrics 崩溃（2026-08-29 todo 已建议）→ 兜底默认值；
  ② e2e DB 残留污染：big_*.csv error 行 + BPD60320 重复种子行（legend-color 前缀匹配 4≠2）→ 清理。
- 新教训（见 lessons.md 2026-08-29 追加）：PowerShell -File 传数组参数被外层 shell 吞（改 -Command）；
  CSS 自定义属性多行书写会保留换行空白（fonts.spec 字面断言失败）→ token 字体栈单行书写。

---

# 任务：UI 设计指南 + tokens.css 落地（除组件层）（2026-08-29）✅

> 用户确认 demo 后指示：除组件画廊外其它先给出，组件维持现状。

## 实施清单

- [x] `docs/reference/ui-design-guide.md`（新）：三层架构总览 + Primitive 全清单 +
  Semantic 双主题对照表（表面/文本/边框/品牌/状态/图表/阴影/chrome）+ 排版/间距/圆角规范 +
  图表规范（SPC/Bin/ECharts JS 映射 + CVD 复验警告）+ 主题机制 + DO/DON'T +
  variables.css/EP 迁移映射表；组件层标注暂缓（§10）
- [x] `frontend/src/styles/design-tokens.css`（新，未 import）：Primitive + Semantic 两层落地版，
  与 variables.css 并存；接入顺序见指南 §9.2（新代码先行 → 按 app 分批替换 → EP 对齐后删旧）

### Review（2026-08-29）

- 关键风险已在指南中显式标注：现有 echarts-theme.ts seriesColors 是 CVD 色盲验证过的
  替换色（#d97706/#86198f 等），新 --chart-1..8 正式切换前必须重跑同样验证；验证前
  ECharts 序列色维持现状，仅轴系/tooltip 对齐。
- 值差异点已在映射表备注：--text-tertiary #717880→#9ca3af（preview 基准）、
  --color-warning #b45309→#92400e（与 EP 统一时一并对齐）、--brand-secondary 退场。
- design-tokens.css 未被任何入口 import，对现有构建零影响。

---

# 任务：组件重设计（四批分批预览迭代）定稿 + 指南组件篇（2026-08-29）✅

> 设计文档：docs/specs/2026-08-29-component-redesign-review-design.md（含全部定稿与弃选记录）；
> 审阅页：docs/plans/component-review-1..4-*.html（均可双击打开、双主题、定稿版）。
> 用户确认方式：分批预览迭代 · 基调见实物再定。

## 四批定稿摘要（详见指南 §10 组件篇）

- 批 1 徽标：主变体 **V1 柔和底**（彩底 13% + 彩字）；整体基调 **A 延续渐变**；Bin 并入变体；KPI Card 移出范围（批次报表已删）
- 批 2 按钮表单：悬停 **X 抬升**（全型上移 1px + 阴影加深）；danger **纯红实心**（弃红渐变）；
  输入框底 --bg / 3px 焦点环 / 错误态红框红环 / 开关渐变 / 分段控件确认
- 批 3 卡片表格：Section 卡头 **浅底带**；表格 **T2 纯分隔线**（弃斑马纹，悬停品牌 10%）；
  Tabs 两形态（下划线/胶囊）；Fail >0 红字加粗；Level **方案 1 双重编码**
  （A✓ 绿/B● 品牌色/C◆ 琥珀/D▼ 红，D 底色 22%；night 下 B/C 同为金黄靠形状区分）；
  B 级误用灰色已修正为品牌蓝；“热度”列仅演示数据非落地概念（用户问，已澄清）
- 批 4 浮层反馈：Toast **顶部居中**；对话框/抽屉毛玻璃规格（--card-glass + blur14 + 圆角 12 + --shadow-lg）；
  横幅四色 / 空状态 / 骨架流光 / 分页渐变激活 / Tooltip 深底反色确认；z-index 层级浮层 41/遮罩 40/Toast 60

## 交付与验证

- [x] 四张审阅页全部浏览器实测（每批含双主题渲染/交互/控制台 0 报错）；中途修复：脚本初始化顺序、
      强制主题面板文字继承、窄视口并排、B 级灰误用等（均已留档于 spec）
- [x] 定稿回写 `docs/reference/ui-design-guide.md` §10 组件篇（10.1–10.9），§1.2 架构图同步转正；
      组件层不新增 token，规格全部直接取语义层 + color-mix
- [x] 落地改造（2026-08-29 当日完成，见下条任务）：components/common/* 旧霓虹清理与 API 对齐 / YieldBadge·CpkBadge·BinTag
      组件化替换手写 span / EP 浮层覆写对齐 + e2e 维护

---

# 任务：指南 §10 组件篇落地（三批改造）（2026-08-29）✅

> 依据：ui-design-guide.md §10（四批定稿转正）；用户确认：§10.9 三项全做 + LoginPage 霓虹一并清理；
> 定稿留档：docs/specs/2026-08-29-component-redesign-review-design.md。

## 实施清单

- [x] 批 A（97c0e40）：Button/Card/Badge/Loading/Empty 按 §10 重做（V1 柔和底/渐变 primary/纯红 danger/X 抬升/浅底带卡头）；
      LoginPage 霓虹→login-input/login-button（e2e 同步）；UserManagement kpi-card 去夜块；全库 `.theme-*` 页面级覆盖清零（grep 0）；
      两主题 css 删 87+7 处并联选择器；4 页删非 scoped 夜块；多处字面 hex→token
- [x] 批 B（2b83891）：新增 YieldBadge（≥95▲/≥90◆/<90▼，compact 表格变体）、CpkBadge（A✓绿/B●品牌/C◆琥珀/D▼红底 22%）、
      BinTag（pass✓good/普通—neutral/高失▼bad，占比≥10% 判高失）三组件；替换 6 处手写 span / el-tag：
      StageFilterBar/DataQualityBar（阈值 90/80→95/90 对齐）/BatchYieldTab（3 处）/TestItemOverviewSection（弃后端 cpk_color 内联色）/
      BinDistribution/BinSiteCrossTable；顺带清 TestItemOverviewSection 漏网 hex（#f3f4f6/#fafbfc→浅底带）
- [x] 批 C（64875cf）：element-plus-theme.css 追加 §10.7/§10.8 双主题通用段（只取语义 token 不写 night 分支）：
      el-dialog/el-drawer/el-message-box/el-message = --card-glass + blur14 + r12 + --shadow-lg；Toast 左 3px 语义色条 + 语义色文字；
      分页 28×28 r6 激活 --grad-brand；遮罩 →--overlay；同步把旧 night !important 块（dialog/message/drawer/pager）改为同 token 值防双主题割裂
- [x] 收尾：全量回归 + 分组隔离复跑判定；DB 污染清理（error 行 + e2e_large_qqplot 残留）；todo/lessons 回写；双主题截图留档；端口释放

---

# 任务：仪表板内容重设计（单文件 + 批次）定稿 + 指南页面篇（2026-08-29~30）✅

> 设计文档：docs/specs/2026-08-29-dashboard-content-redesign-design.md（单文件）、
> 2026-08-30-batch-dashboard-redesign-design.md（批次）；审阅页：docs/plans/dashboard-redesign-review.html、
> batch-redesign-review.html（均双主题可交互、浏览器实测通过）。
> 目标：去 KPI 卡 / Site GAP，提升信息集中度；批次大部分参考单文件，差异点逐个沟通确认。

## 单文件定稿摘要（指南 §11.2）

- 页头一行（文件选择器并入）；总览条 = 程序/总记录/Pass/Fail/Yield/UPH/测试时长/测试开始 + 格式 chip（UPH 带 ? 公式）
- 警报单横幅可展开；Bin Pareto + Site 柱线组合双列；Bin×Site 同卡表格/热力图页签（热力格等宽居中
  `数量(行内占比%)`，合计列 `数量(占总记录%)`）
- 测试项总览：CPK 堆叠比例条 + 11 列表格（Fail 合并 `数量(占比%)`、表头全列排序、卡头双复选框默认勾选、
  行点击跳转）+ Top 10 Fail 信息 chip；UPH 紧凑明细行置底（字段全保留含公式/来源/警告/各站小格）
- 删除：KpiCards / DataQualityOverview / gauge / Bin 饼图表 / CPK 饼图 / Top10 柱状 / 工具条行；整页纵向约减 45%
- 多轮迭代修正留档：热力格混排错位（统一等宽格）、B 级灰误用、副行/筛选口误澄清（实为表头排序）、
  UPH 信息补全、Top10 字体降级、合计列百分比口径（与 Pareto 一致）

## 批次定稿摘要（指南 §11.3，六差异点逐个确认）

- 批次选择器并入页头；阶段胶囊条保留；趋势图并入阶段汇总卡；Site 矩阵合并单列（徽章+比值）；
  Bin 卡全套对齐单文件；UPH 保持现状（只在 Bin 卡内，不上总览条）

## 交付与验证

- [x] 两张审阅页浏览器实测（双主题/交互/窄视口/控制台 0 报错）；截图存档 test/screenshots_night/dashboard_redesign_*、batch_redesign_*
- [x] 定稿回写 ui-design-guide.md §11 页面篇（参考顺延 §12，状态行更新）
- [x] 落地改造（2026-08-30 完成，两批）：
      - 批 1（e2aba14）单文件 Tab：页头一行 / OverviewStrip 总览条（data-testid=overview-strip，
        测试开始走 /files/:id/ 详情取 metadata.start_time）/ AlertBanner 单横幅 / Bin Pareto（纯 CSS）/
        Site 柱线组合（删 gauge）/ Bin×Site 表格-热力图页签（热力格等宽 `数量(行内占比%)`、合计列占总记录%）/
        测试项总览 11 列 + 双复选框 + CPK 比例条 + Top10 chip / UPH 紧凑明细行；
        删 KpiCards/DataQualityOverview/QualityAlerts/OverviewCharts 四组件
      - 批 2（fec0ff9）批次 Tab：页头一行（批次下拉+元信息+加载/导出）/ QA 四色横幅 /
        阶段汇总卡合并趋势图 / Site 矩阵合并单列 / Bin 卡全套对齐单文件（Pareto+柱线+页签+UPH）/
        胶囊激活渐变实底；删 BatchSelectorBar；CollapsibleSection 增 header-extra 槽
      - e2e 同步：dashboard.spec（总览条/柱线/页签/11 列/批次区块断言）、batch-phase.spec、
        night-visibility（ready 选择器）；build ×4 绿；定向回归全绿（batch 条件 skip 为基线）；
        双主题截图留档 dash_batch1_*（4 张）/ dash_batch2_*（2 张）

## 用户反馈修正轮（2026-08-30 晚）✅

用户 8 项反馈（编号 1-6、8、9），全部修正并验证：

- [x] 1 热力图无数值：根因 = 笛卡尔热力图未配 visualMap，ECharts 抛 “Heatmap must use with visualMap”
      整系列不渲染（截图只见 splitArea）。修：visualMap show:false 按行内集中度（dimension 3）具体 rgba
      插值着色 + 数值标签具体色值（BinSiteCrossTable）
- [x] 2 CPK 比例条短段压缩至几乎不可见：min-width 10px 保底 + 占比 <10% 隐藏条内文字，
      新增图例行承载全量 计数/占比（TestItemOverviewSection）
- [x] 3/5 百分比位数限最多 3 位：formatPercent 上限 6→3（极小非零 “<0.001”）；测试项总览 Fail 列/chip、
      Site 柱顶标签、批次趋势图线标签、YieldBadge 数字值统一走该格式化
- [x] 4 UPH 各站点明细挤作一团：根因 = UphDetail 为 plain script defineComponent + h() 渲染，
      scoped 选择器命中不到内部节点；统一 :deep() + tooltip（teleported）改内联样式，排版对齐静态审阅页
- [x] 6 Bin×Site 交叉表 Bin 值去徽标勾改纯文字（两张表）
- [x] 8 文件下拉移入单文件 Tab（同批次页头行式），页头主标题放大 20px
- [x] 9 阶段明细表删 操作员/工站/Device/Tester 列（展开 drill-down 行保留）
- [x] 验证：vue-tsc 绿；定向回归 19 passed/8 基线 skip；含截图轮 22 passed/0 failed；
      截图留档 fix_*（single/heatmap/uph/overview/crosstable × light/night + batch）；手动 dev server 已清理

## 用户反馈修正轮 2（2026-08-30 夜）✅

- [x] 1 阶段明细表不撑满容器 + 表格风格与主题不一致：文本/时间列改 min-width 弹性擑满（明细表 +
      树形表数值列均衡分布）；删 BatchYieldTab 局部 `:deep(.el-table)` 灰头/hover 覆写，
      统一走全局 element-plus-theme.css（与单文件表同款）
- [x] 2 滚动缩放后切 Tab 良率趋势空白 / Site 良率挤压：根因 = 隐藏 Tab display:none 时
      window resize 触发 chart.resize() 锁 0 尺寸；新增 `observeContainerResize`（echarts-init，RO + rAF 防抖），
      YieldTrendChart/SiteYieldAnalysis/BinSiteCrossTable 三组件迁移（v-if 容器按元素身份挂载）
- [x] 验证：vue-tsc 绿；临时 resize 用例（隐藏期视口两连变→切回，svg 宽 ≥ 0.8×容器）通过；
      定向回归 19 passed/8 基线 skip；截图 fix2_batch_after_switch / fix2_detail_table

## 用户反馈修正轮 3（2026-08-30 夜）✅

- [x] 图表「经常消失」补漏：① initEchartsWhenReady 5s 超时不再 disconnect ResizeObserver
      （容器后拿尺寸时自愈 init）；② SiteYieldAnalysis v-if 容器重建时 dispose 旧实例再 init
      （元素身份守卫），修「卡头有数、图区空白」
- [x] 验证：vue-tsc 绿；定向回归 19 passed/8 基线 skip

---

# 任务：分析页审计修复三批（2026-09-02）

来源：/analysis 页全栈审计（前端 pages/analysis 6004 行 + apps/analysis 7548 行）。
基线：`manage.py test apps.analysis` = 127 tests OK / 4.5s。

## 批次 1 — P0 正确性与错误暴露 ✅

- [x] `statistics/site_stats`：补 `param not in df.columns` → 400 `param_not_found`（对齐
      serial:469 / qqplot:546，R3①）；`no_site_column` 由 200+body.error 改 400 且不再回传
      `available_columns` 全量列名
- [x] `_load_df_from_request`：`int(file_id)` 非数字 → 400 `file_id_invalid` 而非 500
- [x] 新增 `/statistics/zonal_yield/`（落 StatisticsViewSet：`analysis_views.py` 已 798 行
      不允许再增长，且该端点返回聚合统计与 site_stats/bin_stats 同类）：三分区良率，
      几何抽 `compute_wafer_geometry` 与晶圆图同源；`WaferMapPanel` 去掉空 catch
- [x] 删死端点关联代码：孤儿组件 `dashboard/components/YieldTrendChart.vue`（真正在用的是
      `batch/YieldTrendChart.vue`）+ `api/analysis.ts getYieldTrend`
- [x] 前端失败不再伪装空态：useHistogram/useBoxPlot/useQQPlot/useCorrelation/useMultiFile
      透出 `error`，各 Tab/图表位渲染 ErrorBanner + 重试；`zonal_yield` 失败同样可见；
      未发请求的提前返回分支统一清错误态（防旧横幅跨上下文残留）
- [x] 验证：`manage.py test apps.analysis` 141 项全绿（新增 14：守卫/分区服务/分区端点）；
      `npm run build`（vue-tsc -b + vite）通过；e2e `chart-error-state.spec.ts` 2 用例
      （500 → 横幅 → 重试恢复 / 切文件横幅不残留）通过

## 批次 2 — P1 性能 ✅

- [x] `wafer_map.py` 逐行 `df.loc` 改列级向量化：坐标 `pd.to_numeric` 整列取一次 +
      `np.flatnonzero(isfinite)` 掩码，serial/bin/site 标签改 `_str_column` 整列 `astype(str)`
      （保持历史 `str(df.loc…)` 口径含 NaN→`'nan'`）。真实文件实测 14174 点位
      **0.65s → 0.019s（≈35×）**；`apps/analysis/tests_wafer_map_points.py` 断言改造前后
      points/stats/wafer **逐字段等价**，另含 5 万行 < 2s 用例
- [x] 前端晶圆图走 canvas/large：≥5000 点时 `large:true` + `animation:false` +
      renderer 强制 canvas（`useChart` 第 4 参，切换时 dispose 重建），小晶圆图行为零变更；
      `wafermap-model-not-found` 大文件用例改为渲染器无关（canvas 走 `dispatchAction` 切图例）
- [x] 三个 `el-tab-pane` 加 `lazy`（晶圆图 / 多文件 / 相关性）：未访问的 tab 不挂载、
      不发请求、不再在零尺寸容器里 init ECharts；`CorrelationToolsTab` 加 `active` 门控
      （隐藏期间共享开关变化只记欠账，切回补算一次）；AnalysisPage 6 开关 watcher 250ms 合并
- [x] `datafiles/services.py` 解析缓存：`lru_cache(maxsize=64)` → `_BytesLRUCache`
      按**字节预算** LRU（默认 1536MB，`LQDP_PARSE_CACHE_MB` 覆盖，`memory_usage(deep=True)`
      估算）+ per-key 单飞锁（并发 miss 只解析一次，失败不卡 pending，超预算单值不缓存）。
      `apps/datafiles/tests_parse_cache.py` 12 项覆盖命中/按字节淘汰/超限/clear/并发单飞
- [x] 验证：`manage.py test apps.datafiles apps.analysis` = **286 项全绿**；`npm run build`
      （vue-tsc -b + vite）通过；e2e 新增 `tab-request-fanout.spec.ts` 3 用例 × 3 轮全绿，
      晶圆图相关 `wafermap-model-not-found` / `wafermap-hidden-tab-init` / `analysis.spec.ts`
      共 5 用例全绿

### 与审计原结论的偏差（如实记录）

- `bin1 改布尔掩码`：**过时发现**。`filters.py:38 get_bin1_mask` 早已是
  `unique → isin` 掩码（`dba2fda` 引入），本轮未改动。
- `wafer_map 接入 statistics/downsample`：**有意不做**。抽样会改变逐 die tooltip /
  Pass-Fail 统计口径，14k die 载荷实测 1.21MB（85B/点），改由 canvas+large 承接渲染成本。
  载荷仍是剩余限制，与 `useChart` resize 全量重绘、请求无 AbortController 一并留待后续。

## 批次 3 — P2 合规

- [x] 删零引用死组件树：`components/correlation/*Section.vue` + `CorrelationPanel`/
      `CorrelationMatrixPanel`/`BatchExportPanel`（6 文件 491 行，只互相引用、无页面挂载）。
      **审计更正**：原计划「把未挂载的批量导出面板接入分析页」不成立——批量导出早已
      上线在 数据管理 → 导出工具（`pages/data/ExportToolsTab.vue` 是 `useExport.ts` 的
      现存消费方），再挂一份是重复功能。`useExport.ts` 因此保留。
- [x] 600 行上限：`analysis_views.py` 798→591（file_correlation 三端点外移为
      `views/file_correlation_views.py` 的 `FileCorrelationActions` mixin——DRF
      `get_extra_actions()` 用 `inspect.getmembers` 沿 MRO 收集，路由前缀一字不变，
      存量测试 URL 未改即全绿即为证据）；`tests.py` 2468→7 个主题模块
      （`tests_param_guards`/`tests_chart_config`/`tests_histogram_kde`/
      `tests_serial_column`/`tests_file_correlation`/`tests_file_correlation_service`/
      `tests_cpk_trend`，最大 520 行）。搬迁等价性：拆分前后唯一用例 ID 集合
      151 == 151、diff 为空、套件 OK。踩到的坑：类之间互相复用 fixture
      （`StaleParamAcrossFileSwitchTests._patched_view` 被 4 个模块用、
      `ChartConfigFilterTests.METADATA/_frame` 被 2 个用），必须显式跨模块 import；
      实测跨模块 import 不会被重复收集（Python 3.13 loader 按定义模块过滤）。
- [x] 双主题：`OutlierHintBar` 夜块 + 硬编码色 → `color-mix(--warn|--error|--success)`
      三态；`SiteStatsTable`/`RangeComparisonTable` 全局 `!important` 块 → scoped
      `:deep(td.el-table__cell)`（EP 把行底色画在 td 上，只命中 tr 会被盖掉）；
      两表头 `#f5f5f5`/`#4a90d9` → `var(--bg-3)`，与同页 `QQPlotStatsTable`/
      `BoxPlotStatsTable` 既有写法一致。
- [x] R5：`SingleParamTab` 14 个 store 快照 + 15 条回写 watch → `storeToRefs`，
      `AnalysisPage` 页头两控件同改。**修掉一个真缺陷**：改「敏感度 (IQR 倍数)」后
      直方图仍用挂载时快照的 1.5 发请求——e2e 实测 RED 报 `Expected: 3 / Received: 1.5`，
      即界面显示宽松 3.0x、后端按严格 1.5x 算异常值边界。断言必须按请求体
      `params:[选中参数]` 精确挑出「单参数直方图」：页面级参数列表请求直读 store
      本来就带新值，只匹配 `iqr_multiplier` 会误判成已修好。
      `store.reset()` 仍无调用方（无重置 UI），改造后它已能正确传播，留作后续。
- [x] 相关性矩阵默认选择加 12 项上限：CTA8280F 实测 **180 个参数默认全选 = 32400 个
      带文字标签的 heatmap 单元**。r 统一 4 位（格内 2 位为空间例外并注明），
      p-value < 1e-4 改科学计数法——原 `toFixed(6)` 会把最强显著性显示成 `0.000000`。
      矩阵 option 构建外移 `composables/matrix-option.ts`，`CorrelationToolsTab.vue`
      601→553 行。
- [x] 修两个与现状脱节的陈旧 e2e 断言（都是测试假设过期，非产品缺陷）：
      ① `large-data-qqplot` 断言 `content-encoding: gzip`，但 GZipMiddleware 已在
      `45f741e`（2026-08-12，距 HEAD 39 个 commit）按实测理由移除 → 改为断言当前契约
      （不压缩）+ 响应体 <300KB（性能护栏交给降采样，实测 34808 字节）；
      ② `file-select` show-meta 把断言锚在 `meta.first()` 上，本地库残留的 2 行 88B
      测试上传 `program_name` 为空 → metaText 只渲染 4 段，五段正则必失败 →
      改为先过滤到种子文件 `BPD60320_FT.csv` 再测该行。
- [x] 双主题可验证化：新增 `e2e/helpers/colors.ts`（rgba()/`color(srgb …)`/hex 三格式
      解析 + 祖先 alpha 合成 + 对比度），`@theme` 加一条分析页用例。借此**发现并修掉一个
      真实缺陷**：`styles/element-plus-theme.css` 夜模式对 `td.el-table__cell` 硬压
      `background-color:#16213e !important`，把组件在单元格上做的语义行着色（当前范围行/
      失败 Site 行/告警行）整片盖掉——夜模式下这些高亮一直不可见。基础行色本来已由
      `--el-table-tr-bg-color` 经 EP 自带 `.el-table tr{...}` 生效，故删掉这条 td 底色，
      实测 tint 由 `rgb(22,33,62)`（被盖）变回 `color(srgb .976 .659 .145 / .12)`。

## Review（2026-09-02）

- 验证（全部实测，串行）：`npm run build`（vue-tsc + vite）✓ built；
  `manage.py test apps.analysis` **151 项 OK**（拆分前后唯一用例 ID 集合一致）；
  全量后端 **605 项 / 1 error**（`test/backend/test_outliers.py` 缺 `pytest`，
  遗留目录，与本批无关）；分析页 e2e `--project=P1` **97 passed / 0 failed（8.7m，
  workers=1）**；`@theme` **7 passed**（含本批新增的分析页着色用例）。
- 本批真实修掉的缺陷：①页头「敏感度」改档后单参数直方图仍按挂载时快照 1.5 发请求
  （界面显示宽松 3.0x、后端按 1.5x 算边界，全程无报错）；②相关性矩阵无上限默认全选
  （180 参数 → 32400 个带标签 heatmap 单元）；③夜模式 `td.el-table__cell` 的
  `background-color !important` 把所有表格语义行着色整片抹掉（当前范围行 tint 实测从
  被盖成 `rgb(22,33,62)` 恢复为 `color(srgb .976 .659 .145 / .12)`）。
- 遗留（下次接手的入口）：
  ① `store.reset()` 仍无调用方（无「重置」UI），storeToRefs 改造后它已能正确传播；
  ② p-value 科学计数法修正无自动覆盖（要 p<1e-4 的真实相关性数据才看得见）；
  ③ 晶圆图 payload 1.21 MB（批次 2 已减请求数，未做服务端降采样）；
  ④ `useChart` resize 走整图重渲染；无 AbortController，切参数时旧请求不取消；
  ⑤ 夜模式 hover 仍由 `element-plus-theme.css` 的 `!important` 决定，鼠标悬停时
  语义行 tint 会被 hover 底色盖掉（只影响悬停瞬时态，未改）；
  ⑥ 分析页未纳入整页对比度扫描的常备页面清单（本批用定向用例覆盖，路由级扫描仍只有
  仪表板/数据管理/设置/SFTP）。
- 踩坑与通则已并入 `lessons.md` 2026-09-02 批次 3 段（storeToRefs 快照、同名端点按
  请求体挑请求、拆测试先量跨类 fixture、陈旧断言反查、行断言勿锚 first()、
  e2e 与后端套件勿并跑、夜模式 !important 盖 td、`color-mix` 计算值是 `color(srgb …)`）。

---

# 任务：全量代码评审修复（2026-09-03）

来源：full review = 4 个只读子代理（后端业务 / 统计算法 / 前端 / 安全构建）+ 自跑门禁。
门禁基线：`npm run build` exit=0（vue-tsc -b + vite，零类型错误）；
`manage.py test test.backend apps` = **605 项 / 1 error / 7 skipped**（211s，串行）。
注：`--parallel 4` 会因 `cannot pickle 'traceback' object` 崩溃并掩盖真实失败，本任务全程串行跑。

## 用户口径决策（2026-09-03 确认，勿自行推翻）

1. **Gage R&R 只修明确代码缺陷**，不动 AIAG 公式口径（不补 σ_AV 修正 / %Study Var / ndc）；
   tolerance 缺失时输出 `N/A`，不再静默换成 `r_r/|global_mean|` 这种另一种量纲。
2. **删掉 pp/ppk 字段**（后端不再输出，前端与导出去掉展示）——消除「两个名字报同一个数」。
3. **良率控制限保持 X̄-chart 近似**（mean ± 3·std），补 `ucl = min(ucl, 100.0)` 钳位 + 精度对齐 6 位。
4. **本轮不做结构重构**：`gage_legacy_builder.py`(857)、`DataBrowserAgGrid.vue`(625) 的 600 行拆分、
   `apps/*/tests.py` → `test/backend/` 迁移、4 个超大测试文件拆分，全部留待下一轮。

## 批次 A — 测试基建（安全网先行）✅

- [ ] `test/backend/test_outliers.py`：`import pytest` + 12 处 `pytest.approx` + 裸 `class TestDetectOutliersIqr`
      → 改 `SimpleTestCase` + `assertAlmostEqual(places=6)`。**只删 import 不够**：裸 class 不被 unittest
      收集，会变成「零错误、零覆盖」的静默失效（比现在报错更危险）
- [ ] 验证：`manage.py test test.backend.test_outliers` 计数 = 20 且全绿；全量 error 归零

## 批次 B — 安全 ✅

- [ ] `apps/accounts/serializers.py:10-14`：`role`/`is_active` 加入 `read_only_fields`
      （堵 `PUT /api/v1/auth/profile/ {"role":"administrator"}` 自助提权；FeaturePermission 每请求读 DB role，提权即时生效）
- [ ] `apps/datafiles/views/batch_views.py`：`BatchDirImportView`(:130 请求体 dir_name，可跨用户 os.walk)、
      `BatchDirDeleteView`(:180)、`SubBatchDeleteView`(:209) 三端点复用 `file_views.py:264` 的
      `re.search(r'[<>:"/\\|?*]', ...)` 黑名单 + 拒 `.`/`..` + realpath 归属校验
- [ ] `standalone.py:142`：`--host` 默认 `0.0.0.0` → `127.0.0.1`；`:90-96` 去掉硬编码 `admin/admin123`
- [ ] `electron/backend.ts`：显式传 `--host 127.0.0.1`
- [ ] `frontend/src/pages/auth/LoginPage.vue:88`：清空预填 `admin`/`admin123`
- [ ] `config/settings/base.py`：补 `DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]` 兜底（现缺失→DRF 回退 AllowAny）；
      `SPECTACULAR_SETTINGS.SERVE_PERMISSIONS=[IsAdminUser]`；`DEBUG` 默认改 False
- [ ] `frontend/src/router/index.ts:53`：`admin/users` 加 `requiresAdmin` 守卫（后端已有 FeaturePermission 兜底，属纵深防御）
- [ ] `config/settings/__init__.py`：遗留 settings（硬编码 `django-insecure-` + `DEBUG=True`）清空为包标识；
      `scripts/update_sub_batch.py:13` 改指向 `config.settings.development`
- [ ] 验证 + 提交

## 批次 C — 数值正确性（部分完成，见 Review）⚠️

- [ ] `limits.py:38-50 parse_limit_string`：缺失/`n/a`/空串 → 返回 `None`（不再 `default_min=0.0`）；
      `'min'/'max'` 关键字 → 视为「无规格限」返回 `None`（不再把数据自身极值当 LSL/USL）。
      **单点根因，扩散 5 条路径**：CPK 变 `−|μ|/(3σ)`、outlier 低侧栅栏被 `min(lb,0.0)` 钳死、
      PPT 导出直方图捕获 0 点全空白、buyoff 负 CPK、gage 魔法哨兵
- [ ] 同步全部调用点：`computations.py:287`、`histogram.py:80`、`cpk_table.py:24`、`serial_distribution.py:151`、
      `site_yield.py:171,181`、`trends.py:266`（可移除局部 `_has_real_limit` 绕过）、`buyoff/services.py:23-29`、
      `gage_legacy_builder.py:307,369,416`、`rr_analysis.py:64,82`（后四处同时删 `0`/`4` 魔法默认与 `!=0/!=4` 哨兵）
- [ ] `helpers.py:156,169`：`filter_finite`/`ensure_numeric` 补 `.astype(float)`；同修 `outliers.py:56`、`computations.py:334`
      （bool 列 `Dut_Pass` 在 `.quantile()` 抛 `TypeError: numpy boolean subtract` → histogram 500）
- [ ] `abs(s) < float('inf')` → `filter_finite`：`analysis_views.py:320,376`、`multi_lot.py:140,157`、`filters.py:70,141`
      （str 列抛 `ArrowNotImplementedError`，既非 TypeError 也非 ValueError，现有 except 捕不到 → 500）
- [ ] dtype 白名单 `('int64','float64')` → `is_numeric_dtype(s) and not is_bool_dtype(s)`：
      `site_yield.py:178`、`analysis_views.py:113`、`export/views.py:199`、`excel_builders.py:77`、
      `export_xlsx_optimized.py:239`、`buyoff/views.py:35,80`；`views/_helpers.py:130` 另补 `nunique()>1`
- [ ] `trends.py:78`：`bin_name == 'Bin1' or bin_name == '1'` → `is_pass_bin(bin_name)`
      （int64 bin 键使良率恒 0.0，与同 app `compute_yield_trend` 矛盾）
- [ ] `iqr_multiplier` 贯穿四端点：correlation(`analysis_views.py:452`)、serial_distribution、qqplot(`:562`)、
      boxplot(`computations.py:240`)；`compute_boxplot_stats` 补 `spec_limits` 参数
- [ ] 筛选开关对称：抽 `_apply_common_filters`，让 cpk/qqplot/boxplot/serial_distribution 与 histogram/correlation 同口径
- [ ] `computations.py:152,164`：相关矩阵样本不足不再伪造 `r=1.0`；NaN→`None`；`np.fill_diagonal(matrix,1.0)`
- [ ] `computations.py:77,87`：删 `pp`/`ppk`（决策 2），同步 `cpk_table.py:32`、`histogram.py:254`、前端与导出
- [ ] `export_xlsx_optimized.py:259`：`std()` → `std(ddof=0)` 对齐屏幕；`:264` 用未舍入原值算 CPK
- [ ] `trends.py:172-177`：补 `ucl=min(ucl,100.0)` + round 6 位（决策 3）
- [ ] `serial_distribution.py:150`：统计量与 plotted 数据同源（`serial_grouped[param]`）
- [ ] `histogram.py:144-149`：site 统计改用已 coerce 的 `data_series`，分母对齐
- [ ] gage 明确缺陷（决策 1 范围）：`np.empty`→`np.full(nan)`+`nanstd`(:336-351)、`fs` 先初始化(:348)、
      Min/Max CPK 分别取 per-file min/max(:458)、R&R% 与 Fail Level 同源(:473-476)、
      V/W 列不再混装量纲 + Average 不回读单元格(:469,485,510)、`ignore_no_limit` 恒先剔 SYSTEM_COLUMNS(:276)
- [ ] buyoff：`views.py:88` 补空 `datasets` 守卫（对齐 `:39`）；`views.py:78`/`gage/views.py:42` 的 `bin_numeric==1`
      → `filter_bin1_rows`；`excelize_layout.py:275,300` 补 FT KeyError 守卫；`:278` 除零守卫改 N/A
- [ ] `batch_report/views.py:328`：`objects.get` → `get_object_or_404`；`sftp/views.py:251,292` 补 `path` 真值守卫；
      `sftp/views.py:267,399,458,491` 异常路径清理半截文件；`:495` 裸 `except:` → `except Exception:`
- [ ] `uph.py:58-64,89`：site 全 NaN 时 fallback `nunique()` + warning；`astype(int)` 前校验整数；unit 空值告警
- [ ] `site_yield.py:31,46`：`total==0` 返回 None 而非 100%；`:124` 裸 except 对齐 `:141`
- [ ] 百分比精度统一 6 位（`site_yield.py:190`、`multi_lot.py:273`、`export/views.py:158`、`buyoff/excelize_layout.py:281,306`）
- [ ] `charts.py:65`：x_labels 由 bins 直接推导（现错开 0.5·gap）；`:37-39` 与 `histogram.py:180-205` 网格统一
- [ ] `export/views.py:207`：pptx 分支补齐 show_limit/sigma/kde 开关透传；`:112` `sigma` 补 int() 与范围校验；
      `:148` html_report 补 `filter_bin1_rows`；`:85` 删死代码 `keep_header`
- [ ] `file_views.py:286-306,350-372`：`shutil.move`/删目录移出 `transaction.atomic()`；`filename` 设 read_only 或 basename 校验
- [ ] `statistics_views.py:350`：bin 列改 `get_bin_column_name(format_type)`，不再「第一个列名含 bin」
- [ ] 死代码：`export/views.py:85 keep_header`、`gage/services/rr_analysis.py` + `gage_summary_builder.py`（标注或删）
- [ ] 补测试：gage/buyoff 数值级断言（构造已知均值/方差→读回单元格到 1e-4）、`compute_bin_trend` int64 键良率、
      `detect_outliers_iqr`/`filter_finite` 的 bool 与 str dtype 用例、limit 缺失应为 None/N/A
- [ ] 验证 + 提交

## 批次 D — 前端（部分完成，见 Review）⚠️

- [ ] `SiteYieldAnalysis.vue:84,123,124` + `batch/YieldTrendChart.vue:80,86`：ECharts option 里的
      `var(--success|--error|--warn|--info)` / `color-mix(...)` → `useChartTheme()` JS 语义色
      （zrender 不解析 CSS；`YieldTrendChart.vue:25` 注释正好写着这条，代码却违反）
- [ ] `var(--color-danger)` 4 处（`OrphanedDbCard.vue:31`、`FileListTable.vue:283`、`DuplicateFilesCard.vue:43`、
      `BatchFilesTable.vue:143`）→ `var(--error)`（全项目从未定义 `--color-danger`，红色警示实际失效）
- [ ] null 守卫：`UphCard.vue:69,70`、`OutlierHintBar.vue:88,91`（后端 NaN→JSON null，`toFixed` 抛 TypeError 致 render 崩溃）
- [ ] SSE 可取消：`api/sftp.ts:197` `postSse()` 加 `signal`；`SftpBrowser.vue` 加 AbortController + `onBeforeUnmount`；
      `:315,363` 的 setTimeout 保存引用并清理
- [ ] 定时器清理：`DataBrowserAgGrid.vue:372` `siteFilterTimer`、`MultiFileTab.vue:312` `fileDebounce`
- [ ] localStorage 统一 `safeGetItem`/`safeSetItem`（`stores/auth.ts`、`stores/theme.ts`、`api/sftp.ts:202`、`useZoom.ts:89`）
- [ ] `DashboardPage.vue:194 onFileChange` 加请求序号守卫（竞态：旧响应覆盖新数据）
- [ ] `styles/common-components-theme.css:12-44`：删全局非 scoped `[class*="toolbar"]` 通配 + night-only `!important`（R7①）
- [ ] `Sidebar.vue:36`：管理员菜单 `hidden` class → `v-if`
- [ ] `SiteYieldAnalysis.vue:49-51`：`_tc()` 每次 getComputedStyle → buildOption 顶部缓存一次
- [ ] e2e：为改到的图表颜色/删除警示色/null 守卫补或维护用例；跑完释放端口
- [ ] 验证（build + 定向 e2e + 双主题截图）+ 提交

## 收尾

- [ ] 全量回归：`npm run build` + `manage.py test test.backend apps`（串行）+ 定向 e2e
- [ ] `docs/tasks/lessons.md` 追加本轮教训
- [ ] Review 段回写本文件

## Review（2026-09-03 阶段性，未完成）

### 已验证的门禁（实测）

- 后端全量：`Found 857 test(s)` / `Ran 857 tests in 252.586s` / **OK (skipped=7)**
  —— 基线是 `605 / 1 error / 7 skipped`，即 **+252 个用例真的在跑 + error 归零**。
- 前端：`npm run build`（`vue-tsc -b && vite build`）**exit=0、零类型错误**。
- Electron：`npm run electron:build:ts`（tsc -p electron/tsconfig.json）**通过**。
- 留底：`tasks/_review_batchABCD.patch`（808KB，R1 认可的 `git diff` 留底方式）。
  **本轮未 commit**（提交需用户明确授权）。

### 已完成

- **批次 A**：`test/backend/test_outliers.py` 转 `SimpleTestCase` + `assertAlmostEqual(places=6)`，
  `Found 20 test(s) / Ran 20 / OK`——这 20 个用例从「一个都没跑」变成真的在跑。
  教训已写入长期记忆（裸 class 不被 unittest 收集 → 只删 import 会变成零错误零覆盖）。
- **批次 B（全部）**：
  - 提权：新增 `UserProfileSerializer`（role/is_active/username 只读），`UserProfileView.put` 改用它。
    **不能**直接把 `UserSerializer.role` 设只读——`UserManagementViewSet` 复用它，会让管理员改不了角色。
    `updateProfile` 在前端零调用方、无测试/e2e 打该端点，收窄可写字段安全。
  - 路径穿越：`_helpers.py` 新增 `_safe_batch_dir`（沿用 `_safe_extract_zip` 的 realpath+commonpath 范式），
    接入 import/delete/sub-delete 三端点。**RED-GREEN 已实测**：旧逻辑下
    `../../victim/batch/LOT-SECRET` → `isdir=True` 且 walk 到 `secret.csv`；`..` → 解析为整个用户上传根。
  - `standalone.py`：`--host` 默认 `127.0.0.1`；bootstrap 口令改 `LQDP_BOOTSTRAP_ADMIN_PASSWORD` 可覆盖；
    **加硬互锁**：非回环绑定 + 默认口令 → `SystemExit` 拒绝启动。
  - `electron/backend.ts` 两处 args 显式传 `--host 127.0.0.1`；`LoginPage.vue:88` 预填改 `import.meta.env.DEV` 分支。
  - `config/settings/base.py`：补 `DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]`（实测 23 个 DRF 视图类
    **全部**已显式声明 permission_classes，故为纯 fail-closed，不改变现有行为）。
  - Swagger：改用 `API_DOCS_ENABLED` 开关（development=True / standalone=False）而非 `SERVE_PERMISSIONS`。
    **原因**：`playwright.config.ts:124` 用 `/api/schema/` 当后端健康检查，直接锁权限会让整套 e2e 起不来。
  - `config/settings/__init__.py` 遗留 settings 清空为包标识（它硬编码 `django-insecure-` + `DEBUG=True`，
    且 `INSTALLED_APPS` 只有 2 个 app，缺 analysis/export/sftp/gage 等 8 个）；`scripts/update_sub_batch.py` 改指 development。
  - `config/urls.py:62` 静态文件防穿越 `str.startswith` → `Path.is_relative_to`。
  - `router/index.ts` `/admin/users` 加 `requiresAdmin` 守卫。
- **批次 C（部分）**：
  - **幻影规格限根因已修**：`limits.py` 新增 `resolve_spec_limit`/`resolve_spec_limits`（缺失/占位/字面
    `'Min'`/`'Max'` → `None`），`parse_limit_string` 降为委派它的兼容壳（解析逻辑只有一份）。
    已迁移调用点：`computations.compute_range_statistics`、`site_yield`、`trends`（顺带删掉
    `_has_real_limit` 局部绕过）、`multi_lot`、`histogram`、`dashboard/views`。
    **实测证据**：真实 `gage_m_S1.csv` 有 **13 个列**（Serial_No/Part_No/Dut_No/Site_No/Dut_Pass/
    SW_Bin/X_COORD/Y_COORD/QR_Code/Start_T/Test_Time/Alarm）的限值字段是字面 `'Min'`/`'Max'`——
    该格式里这就是「无规格限」的占位，旧实现把数据极值当 LSL/USL，于是这 13 列全部算出
    Cpk ≤ 0.5 判 D 级红。
  - `helpers.filter_finite`/`ensure_numeric` 补 `.astype(float)`；`outliers.py`、`computations.compute_qqplot`、
    `filters.py`×2、`multi_lot.py`×2、`analysis_views.py`×2 的裸 `to_numeric`/`abs()<inf` 统一改走 `filter_finite`。
    **RED-GREEN 已实测**：`to_numeric(bool).dtype == bool`，旧 `.quantile(0.25)` 抛
    `TypeError: numpy boolean subtract`；新写法返回 0.75。真实数据 `Dut_Pass`=bool、`Start_T`=str。
  - `trends.py:78` 改 `is_pass_bin`（int64 bin 键使良率恒 0.0）；`bins_sorted` 改数值感知排序
    （旧 key 对 int 键排不出 Bin1 优先，且 int/str 混用时 `sorted` 直接 TypeError）。
  - 良率 SPC 控制限补 `ucl=min(ucl,100)` + 精度 6 位（决策 3）。
  - **删 pp/ppk**（决策 2）：`compute_cpk` + `histogram.py` + `cpk_table.py` + `tests_cpk_trend.py` 断言。
    实测前端与 apps/export 对 pp/ppk **零引用**，故无下游破坏。
  - 相关矩阵：样本不足不再伪造全 1.0（改全 `None` + `insufficient_data` 标记）；`np.fill_diagonal(1.0)`；
    非对角 NaN → `None` 而非 0.0。前端 `matrix-option.ts:50` 已有 `?? 0` 兜底，不会崩。
  - `site_yield`：单边限不再让缺失侧以幻影 0.0 参与比较（新增 `_limit_fail_mask`）；`total==0` 返回
    `None`/`'N/A(0)'` 而非 100%；裸 `except:` → `except (ValueError, TypeError)`；dtype 白名单改
    `is_numeric_dtype and not is_bool_dtype`；`yield_pct` 统一 6 位。
  - `histogram.py`：site 统计改用已 coerce 的 `data_series` + 索引对齐（与 `site_histograms` 同源）；
    `lower_limit`/`upper_limit` 缺失时输出 `None`（不再画幻影限值线）。
  - `serial_distribution.py:150`：统计量改与 plotted 数据同源（`serial_grouped[param]`）。
  - 子代理完成：`apps/gage`（np.empty→nan、fs 未赋值串味、Min/Max CPK 同值、R&R% 与 Fail Level 同源、
    V/W 量纲混装、魔法哨兵 0/4、ignore_no_limit 恒先剔系统列、临时文件 try/finally、死代码标注）；
    `apps/buyoff`+`apps/batch_report`+`apps/sftp`（空 datasets 守卫、filter_bin1_rows、limit→N/A、
    FT KeyError 守卫、get_object_or_404、path 真值守卫、半截文件清理、裸 except、SFTP 主机密钥 TOFU）；
    `apps/export`（ddof=0、二次舍入、网格与屏幕同源 + ±inf 兜底、pptx 开关透传、sigma int()+400、
    html_report 补 bin1、删 keep_header、inf 不进单元格、dtype 白名单）；
    `apps/datafiles`+`apps/dashboard`+`apps/common`（combine/uncombine 三阶段化使事务内无文件 I/O、
    filename 设 read_only、分页容错钳位、静默 except 补日志、500 detail 仅 DEBUG 下发、file_id int 容错）。
  - **新增测试 252 个**，其中我写的：`test_profile_privilege`(8)、`test_batch_dir_traversal`(15)、
    `test_numeric_dtype_guards`(12)、`test_bin_trend_yield`(13)、`test_spec_limits_and_correlation`(18)。

### 两个测试本身钉住了 bug，已按正确语义改写（不是「改测试让它过」）

- `apps/dashboard/tests.py::test_overview_row_schema`：原断言 `assertIsInstance(row['cpk'], float)`。
  上面那 13 个 `'Min'/'Max'` 占位列因此**必须**有 float cpk —— 即断言钉住了「系统列被报成工艺能力不足」。
  改为逐侧判定（真有限值→float，无→None），并额外钉住 `Serial_No`/`Test_Time` 确实落入 None 分支、
  占位列 ≥10 个，防止 None 分支永不执行导致测试退化。
- `apps/export/tests.py::test_batch_charts_site_stats_string_failcount`：原 metadata 是
  `{'limits': {'Vth': (1.4, 1.6)}}`，而 `compute_range_statistics` 读的是 `mins`/`maxs`，export 侧
  根本不消费 `limits` 键 → rdl 退化成幻影 `(0.0, 0.0)` → 「所有 Vth > 0」全判 fail → 红底断言碰巧通过。
  改为真实的 `{'mins': {'Vth': '1.4'}, 'maxs': {'Vth': '1.6'}, 'units': {...}}`，越限变成真越限。

### 子代理对我原评审结论的实测纠正（已采纳）

1. **str 列 `abs()` 抛的不是 `ArrowNotImplementedError`**：实测真实 `Start_T`（pandas 3.0 str dtype）抛
   `TypeError: bad operand type for abs(): 'str'`，**可被 `except (TypeError, ValueError)` 捕获**。
   缺陷成立（一个非数值列就能打断整个多文件请求），但严重度低于我原来的「不可捕获→必 500」。
   我已把自己写进代码注释与测试 docstring 的同一错误说法一并更正。
2. **buyoff 文本 bin 的症状不是 `no_common_items` 400**：实测空表仍保留列与 dtype，`common_items` 非空；
   且 `'1'` 字面量仍会被 `to_numeric` 转成 1。真实症状是**静默丢行**（4 行只剩 1 行）却返回 200——比 400 更危险。
3. **gage 文本 bin 的症状不是 `need_at_least_2_files`**：df 被清空后 `file_datasets` 长度仍是 2，
   真实症状是汇总表无数据（`O12` 空白）。
4. **`charts.py` x 轴并没有错开 0.5·gap**：`low - 2*gap` 恰好等于第一个 bin 的**中心**，旧 `x_labels`
   本来就与 bin 中心一致。我原来是拿「中心」与「边界」相比才得出错标结论——**这条判断是错的**。
   真缺陷是网格相对屏幕平移 + 无 ±inf 兜底（已修，且改为由 bins 推导 x_labels 作单一来源）。
5. **`download_file_stream` 本来就有半截清理**（走 `downloads.download_file_events`）；真正缺清理的是
   `download`/`download_batch`/`_single_download_parse`/`_batch_download_parse` 四个直落盘端点。另多找到
   一处同族 `download_dir` 的 `remote_path` 可为 None（我漏了）。
6. **bool 列在旧 export 白名单下本来就被排除**（`dtype in ('int64','float64')` 不含 `'bool'`）；
   真缺陷是窄 dtype 漏列（int32/float32/UInt8）+ pandas 3.0 下 `== object` 对字符串列恒 False。
   且反向风险成立：换成 `is_numeric_dtype` 后 bool **会被纳入**，必须显式 `and not is_bool_dtype`。

### 刻意未做（附理由）

- **`config/settings/base.py` 的 `DEBUG` 默认值不改**：base.py 是被 development/standalone `import *` 的
  **mixin**，而它的 SECRET_KEY 守卫在 import 期执行。默认改 False 会让
  `from config.settings.base import *` 在 development.py 来得及设 `DEBUG=True` 之前就抛
  `ImproperlyConfigured`，**直接打断所有没设 SECRET_KEY 环境变量的 `manage.py` 调用**。
  出货用 standalone（硬编码 `DEBUG=False`），无实际暴露面。已在代码里写明理由。
- **`CORS_ALLOW_ALL_ORIGINS` 不改**：生产 Electron 用 `win.loadFile()`（`file://`，Origin 为 `null`）
  访问 `http://localhost:<port>`，**每个生产请求都是跨源**，收窄会直接打断打包版。dev 态 vite 是 proxy
  `/api`，本来也不需要 CORS。正解是让 Django 用 http:// 同源提供 SPA 再彻底关掉 CORS，但那要改打包版
  加载方式、必须拿真实安装包验证，本轮不做。已用「绑 127.0.0.1 + bootstrap 硬互锁」收敛主要暴露面，
  并在 base.py 写明残留风险。
- **登录用户名枚举 / 按账号锁定可被定向锁死 admin**：`LOGIN_ERROR_CODES` 上方注释明写
  「Never rename — 前端 LoginPage.vue 按这些字符串分支」，改文案会破坏前端契约；绑定回环后风险大幅下降。
  列为后续。
- **`trends.py` 的 `cpk_val = 0.0`（不可计算 vs 极差混同）**：改 `None` 需前端断线渲染配合，属展示语义变更，
  且原评审标注为「需业务确认」。列为后续。
- **Gage R&R 的 AIAG 公式口径**（σ_AV 修正 / %Study Var / ndc）：用户决策 1 明确本轮不动。
  子代理据此**移除**了 V/W 列里的方差贡献分数而非另开新列（避免改 27 列布局），已记录。
- **`build_histogram_bins` 保留为弃用 shim**：`apps/export/tests.py` 的 `BuildHistogramBinsTests` 把旧几何
  pin 死了，而测试迁移是下一轮的事。生产路径（charts/export_ppt/export_batch_charts_xlsx）已全部改走
  新的 `build_histogram_grid`，shim 只服务那个旧测试。
- **结构重构全部延后**（用户决策 4）：600 行拆分、`apps/*/tests.py` → `test/backend/` 迁移、超大测试文件拆分。
  注：`apps/gage/gage_legacy_builder.py` 因本轮修缺陷从 857 → 901 行，下一轮拆分时一并处理。

### 未完成（下一轮入口）

**批次 C 残留**
- [ ] `iqr_multiplier` 贯穿 correlation / serial_distribution / qqplot / boxplot 四端点
      （`compute_serial_distribution_data` 连 `parse_filter_flags` 都没调；`compute_boxplot_stats` 硬编码 `1.5*iqr`）
- [ ] `compute_boxplot_stats` 补 `spec_limits` 参数（`outliers.py` 已修好，boxplot 没跟上）
- [ ] 筛选开关对称：抽 `_apply_common_filters`，让 cpk/qqplot/boxplot/serial_distribution 与 histogram/correlation 同口径
- [ ] `statistics_views.py` boxplot 的 by_bin 分组改 `get_bin_column_name(format_type)`，不再「第一个列名含 bin」
- [ ] `uph.py`：site 全 NaN 时 fallback `nunique()` + warning；`astype(int)` 前校验整数；unit 空值告警
- [ ] `views/_helpers.py` `_sanitize_numeric_params`：补 `not is_bool_dtype` + `nunique() > 1`（常量列使相关矩阵对角线曾为 0）
- [ ] `analysis_views.py` 参数候选的 dtype 白名单同改
- [ ] `cpk_table` 复用 `filters._display_cpk`（现与直方图卡片的 filtered CPK 口径不一致）
- [ ] `multi_lot.py` `bin_centers` 补 round 6 位；百分比精度统一；`range_type` 用正则 `^S(\d+)$` 解析任意 N
- [ ] `correlation.py` / `serial_distribution.py` 的 `sorted(key=str)` → `site_sort_key`（Site10 排在 Site2 前）
- [ ] `serial_distribution.py` serial 展开的内存护栏（稀疏大整数会构造千万级 list）+ 字符串 serial 的 ValueError
- [ ] `charts.py` 与屏幕侧残留差异：导出无 `range_type` 概念（恒用 RDL）、多 site 归一分母不同（per-site vs 全样本）
- [ ] gage/buyoff 的 AIAG 口径与 `rr_analysis.py` 死代码删除（决策 1 范围外）

**批次 D 残留**
- [ ] null 守卫：`UphCard.vue`（`avg_test_time.toFixed`）、`OutlierHintBar.vue`（`lower_bound.toFixed`）
      —— 注意后端 `lower_limit`/`upper_limit` 现在**会**返回 null 了，这条从「防御性」升级为「必需」
- [ ] SSE 可取消：`api/sftp.ts` `postSse()` 加 `signal`；`SftpBrowser.vue` 加 AbortController + `onBeforeUnmount`
- [ ] 定时器清理：`DataBrowserAgGrid.vue` `siteFilterTimer`、`MultiFileTab.vue` `fileDebounce`、`SftpBrowser.vue` 两处 setTimeout
- [ ] localStorage 统一 `safeGetItem`/`safeSetItem`（`stores/auth.ts`、`stores/theme.ts`、`api/sftp.ts`、`useZoom.ts`）
- [ ] `DashboardPage.vue onFileChange` 竞态守卫（注：`useAsyncData` 已内置请求序号守卫，先确认该页是否走它）
- [ ] `styles/common-components-theme.css` 全局非 scoped `[class*="toolbar"]` 通配 + night-only `!important`（R7①）
- [ ] `Sidebar.vue` 管理员菜单 `hidden` class → `v-if`
- [ ] `SiteYieldAnalysis.vue` 的 `_tc()` 仍走 `getComputedStyle`（可用，但每次 buildOption 多次调用触发样式重算；
      改 `colors.value.textColor` 会顺带把轴标签从 --text 统一到 --text-2，与另两个仪表板图表一致——属视觉决策，本轮未动）
- [ ] `element-plus-theme.css` night 覆盖区的硬编码 hex → 语义 token

**e2e（本轮完全没跑 —— 合并前必须补）**
- [ ] 阻塞原因：端口 8000 被 PID 35224 占用，且存在 **2 个残留 runserver 进程**。
      `playwright.config.ts` 的 `reuseExistingServer: !CI` 会静默复用**旧代码**进程，
      e2e 结果无效（lessons 2026-08-29 的同款坑）。未擅自杀用户的 dev 服务。
- [ ] 跑前必须：沿 `ParentProcessId` 杀整棵 runserver 进程树 → 验证无 `CommandLine like '%runserver%'`
      残留 → 再跑；跑完释放端口并恢复用户 dev 服务。
- [ ] 本轮前端改动的 e2e 风险点（需重点验）：① `LoginPage` 预填清空——`helpers/auth.ts` 用 `fill()`
      覆盖式输入、`auth.spec.ts:26-27` 显式 `fill('')`，理论不受影响，但要实跑确认；
      ② `router` 新增 `requiresAdmin` 重定向——可能影响 `admin.spec` 的角色用例；
      ③ 两个仪表板图表改 JS 语义色 + `--color-danger`→`--error`——`@theme` 套件的颜色断言可能命中；
      ④ 后端 `lower_limit`/`upper_limit` 现在会返回 null、pp/ppk 字段消失、相关矩阵出现 null 与
      `insufficient_data`——分析页/导出相关 e2e 断言需复核。
- [ ] 双主题截图留档（本轮改了图表颜色与删除警示色，属可见变更）

---

# 分析页「每个 tab 独立选文件」与异常值处理归位（2026-09-05）

> 需求：删掉数据分析页最上方的「选择数据文件」，改为每个 tab 有自己独立的文件
> 选择；「异常值处理」放进「数据筛选」。确认口径：文件选择**完全独立**，数据筛选
> 与异常值处理也**随 tab 独立**。设计见
> `docs/specs/2026-09-05-analysis-per-tab-file-selection-design.md`。

## 实施清单

- [x] 批次 1｜选择器契约先行（不改行为）：`data-file-picker="single|wafer|correlation|multi"`
      与 `data-filter="outlier-handling|iqr-multiplier|…"` 挂到现有控件；`helpers/params.ts`
      新增 `filePicker/filterControl/pickTabFile/pickOutlierMode/pickSensitivity`，8 个 spec
      的文案与顺序定位器迁到契约属性
- [x] 批次 2｜`stores/analysisTabs.ts`：单文件/晶圆图/相关性/多文件四个子 store（工厂 +
      不分叉的 `reset()`）；`stores/analysis.ts` 只剩 `activeTab`；`useBoxPlot/useQQPlot/
      useSerialDistribution` 改为接收传入的 `iqrMultiplier` Ref；`ExportToolsTab`、
      `TestItemOverviewSection` 改指单文件子 store
- [x] 批次 3｜`useTabFileParams`（防抖/过期响应守卫/预设参数自愈/空白列/文件失效回落）+
      `AnalysisFilePicker` + `DataFilterSection`；四个 tab 接线；`ChartConfigPanel` 退为纯
      显示配置卡；`AnalysisPage` 395 → 106 行；晶圆图加载下放；多文件补传 `iqr_multiplier`；
      敏感度可见条件改为 `outlier!=off || onlyLowCpk`；删除相关性重复 switch 与镜像 ref；
      不再透传后端从不读的 `global_judgment`
- [x] 批次 4｜e2e：存量用例改为「在目标 tab 内选文件」（wafermap-×2、相关性×3、分析页
      晶圆图用例）；`tab-request-fanout` 第 2 条按新语义重写（不重发也不补发）；新增
      `tab-independent-files.spec.ts` 6 条独立性契约
- [x] 批次 5｜设计归档 + 09-02 spec 取代标注 + 用户指南（`04-analysis.md`、
      `01-quickstart.md`）+ `e2e/README.md` 选择器契约章节

## Review

- 验证：`npm run build`（vue-tsc -b + vite）绿；分析页 + `@theme` 套件全量（workers=1
  retries=0）结果见下方账目；浏览器双主题烟测 7 项全绿（页头已无全局控件、每个 tab
  各一个选择器、单文件选 A / 晶圆图选 B 互不覆盖、相关性提示条按自己的档位、多文件
  只有敏感度没有裁剪）
- 踩坑（已记 lessons）：端口 8000 上残留一个**未钉 `LQDP_SYSTEM_CONFIG_FILE` 的旧
  runserver**，`reuseExistingServer: !CI` 静默复用它 → e2e 后端连到用户目录库 → 文件
  id 存在但磁盘无对应文件 → 38 条用例 `file_not_found_or_parse_failed`。一开始被当成
  代码回归，实际是 todo 2026-09-02 条目已经预警过的同一个坑。
- [ ] 待确认：本轮 e2e 全量账目（清理端口后重跑）——失败项必须回到已知的 5 条存量
      （boxplot-bool-params×2、file-switch-param-reset、wafermap-×2 负载 flake）以内
