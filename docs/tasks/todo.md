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
- [ ] 落地改造（另行确认排期）：components/common/* 旧霓虹清理与 API 对齐 / YieldBadge·CpkBadge·BinTag
      组件化替换手写 span / EP 浮层覆写对齐 + e2e 维护
