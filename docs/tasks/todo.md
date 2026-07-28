# 任务：前端 UI/UX 全面修复（2026-07-28）✅ 完成

> **36 文件修改 + 2 新文件 = 38 文件**，570+ 行增，417- 行删
> 46 项问题全部修复

---

## ✅ 已完成的 46 项修复

### 主题颜色系统（Phase 1）
- [x] 7 通用组件：Card, Button, Badge, Loading, Empty, GridBackground, CircularProgress → CSS 变量
- [x] 5 图表组件：BoxPlotChart, ParameterTrendChart, ParetoChart, CorrelationPanel, CorrelationToolsTab → echarts theme
- [x] useHistogram.ts CPK 颜色 → echarts theme
- [x] 4 页面：LoginPage, UserManagement, AnalysisPage, SftpBrowser, SftpFileTable, SftpConnectionPanel
- [x] variables.css 6 项 WCAG 对比度修复 + --brand-primary-rgb
- [x] echarts-theme.ts 配色同步新值
- [x] utilities.css shadow → var(--shadow-*)
- [x] style.css focus → --brand-primary
- [x] FOUC 防护脚本
- [x] colors.ts 死代码删除

### 可访问性（Phase 2）
- [x] index.html: lang=zh-CN, meta desc, noscript
- [x] Sidebar: h1+router-link, nav aria-label, aria-current, dynamic aria-expanded
- [x] Topbar: dynamic aria-expanded
- [x] MainLayout: skip-link, id="main-content", tabindex=-1
- [x] CircularProgress: role=progressbar + ARIA + onBeforeUnmount
- [x] Loading: role=status + aria-live
- [x] LoginPage: visible labels + name 属性
- [x] QQPlotChart: role=img + aria-label
- [x] SettingsPage: CPK aria-describedby

### 表单验证与错误（Phase 3）
- [x] SftpConnectionPanel: 空值 validation
- [x] SettingsPage: CPK 变更 ElMessage.warning
- [x] ExportFooter: ElMessage.error
- [x] Dashboard: 部分数据降级渲染

### 组件架构与性能（Phase 4）
- [x] CircularProgress 内存泄漏修复
- [x] Wildcard * transition 移除
- [x] keep-alive :max="10"
- [x] Barrel: CircularProgress, GridBackground 导出
- [x] 6 组件 + 2 layout reduced-motion

### 响应式（Phase 5）
- [x] 100vh → 100dvh (MainLayout + Sidebar)
- [x] Sidebar z-index: 100 + ≤768px 自动折叠
- [x] Topbar 搜索 disabled + 个人资料 no-op
- [x] SftpFileTable Action fixed="right"

### 路由与打磨（Phase 6）
- [x] document.title 更新（afterEach）
- [x] Focus 管理 → #main-content
- [x] 404 页面（NotFoundPage.vue）
- [x] print.css 打印样式
- [x] theme-color meta 动态更新（已有）

---

## ⬜ 剩余待处理

### 组件拆分（13 文件 >300 行）
- BatchYieldTab(601), FileListTab(572), FileManager(551), CorrelationToolsTab(540),
  DashboardPage(497), BuyoffForm(485), DataBrowserAgGrid(464), BatchManagement(462),
  UserManagement(434), SettingsPage(426), DataManagement(416), GageSummary(403),
  ExportToolsTab(384)

### 图表可访问性
- [ ] SiteYieldAnalysis gauge 数值文本替代
- [ ] 图表 → 配套数据表关联

### E2E 测试
- [ ] 主题切换回归
- [ ] night 模式渲染验证

---

## 🔑 关键技术决策

| 决策 | 原因 |
|------|------|
| `--brand-primary-rgb` 变量 | 支持 `rgba()` 用于 shadow/glow |
| `color-mix(in srgb, var(--x) N%, transparent)` | 用于低透明度背景/Badge/边框 |
| `var(--shadow-*)` 统一阴影 | 自动适配双主题 |
| `replace_all: true` 全局替换 | LoginPage/SftpConnection 多处 rgba→rgba(var) |
