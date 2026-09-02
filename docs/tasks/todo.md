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

- [ ] 删零引用死组件树（`components/correlation/*Section.vue` + `CorrelationPanel`/
      `CorrelationMatrixPanel`）；把未挂载的批量导出面板接入分析页
- [ ] `analysis_views.py` 798→<600（file_correlation 三端点外移）；`tests.py` 2468 行拆 `tests/` 包
- [ ] 双主题：`OutlierHintBar` 页面级 `:root[data-theme='night']` 覆盖块与硬编码色改 token；
      `SiteStatsTable`/`RangeComparisonTable` 非 scoped 全局 `!important` 改 scoped
- [ ] R5：`iqrMultiplier` 等 store 值统一 `storeToRefs` 双向；相关性矩阵默认选择加 12 项上限；
      数字格式统一
- [ ] 验证：`npm run build` + 双主题截图 + 后端测试全绿

## Review（2026-09-02）

（实施后填写）
