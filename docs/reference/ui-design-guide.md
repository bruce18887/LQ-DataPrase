# LQ-DataPrase UI 设计指南（Design Tokens）

**日期**: 2026-08-29 · **状态**: 生效（组件层暂缓，见 §10）
**视觉基准**: `docs/plans/dashboard-rebuild-preview.html` 与 `docs/plans/design-system-preview.html`（可双击打开的 token 展示页）
**配套文件**: `frontend/src/styles/design-tokens.css`（本指南的可落地 CSS，Primitive + Semantic 两层）

---

## 1. 总览

### 1.1 设计哲学

- **Light · 日间工作室**：温暖米白底（非纯白）+ 专业蓝品牌色，高对比文本，适合日间长时间工作。
- **Night · 深夜工作室**：深蓝灰底（非纯黑）+ 金黄品牌色（与 `element-plus-theme.css` 的 `--el-color-primary` 同源），半透明卡片 + 毛玻璃浮层，低刺激沉浸。

### 1.2 三层架构

```
① Primitive（--p-*，主题无关）
   原始素材：色阶 / 间距 / 圆角 / 字号 / 字重 / 字体
        ↓ 只被语义层引用
② Semantic（随 data-theme 切换）★ 页面唯一取色入口
   --bg/--text/--border/--brand/--success…/--chart-1..8/--shadow-*
        ↓ 组件按需引用
③ Component（暂缓，见 §10）
   组件级派生 token；当前组件维持现状，直接用②即可
```

### 1.3 适用范围

- 所有新写样式 **只允许取用语义层**（`var(--text-2)`），禁止字面 hex / 直接取 `--p-*`。
- ECharts 不认 CSS 变量：JS 侧颜色按下表取语义值（见 §6.3），不在 option 里写 `var()`。
- 现存代码按 §9 映射表渐进迁移，不做一次性大爆炸替换。

---

## 2. ① Primitive 层（主题无关）

### 2.1 色阶（从现有 light/night 两套配色提炼，禁止新增随意色）

| 色族 | 色阶 | 主要用途 |
|---|---|---|
| `--p-blue-50..900` | `50 #eff6ff · 100 #dbeafe · 200 #bfdbfe · 300 #93c5fd · 400 #60a5fa · 500 #3b82f6 · 600 #2563eb · 700 #1d4ed8 · 800 #1e40af · 900 #1e3a8a` | light 品牌 |
| `--p-amber-100..800` | `100 #fef3c7 · 200 #fde68a · 300 #ffd54f · 400 #fbc02d · 500 #f9a825 · 600 #f59e0b · 700 #c17900 · 800 #92400e` | night 品牌 / warn |
| `--p-teal-100..800` | `100 #d1fae5 · 200 #a7f3d0 · 300 #6ee7b7 · 400 #38ef7d · 500 #10b981 · 600 #11998e · 700 #047857 · 800 #065f46` | success |
| `--p-red-100..800` | `100 #fee2e2 · 200 #fecaca · 300 #fca5a5 · 400 #f87171 · 500 #f5576c · 600 #dc2626 · 700 #b91c1c · 800 #991b1b` | error |
| `--p-sky-100..800` | `100 #e0f2fe · 200 #bae6fd · 300 #7dd3fc · 400 #00f2fe · 500 #0ea5e9 · 600 #4facfe · 700 #0369a1 · 800 #075985` | info |
| `--p-slate-50..950` | `50 #fafbfc · 100 #f3f4f6 · 200 #e5e7eb · 300 #d1d5db · 400 #9ca3af · 500 #6b7280 · 600 #4b5563 · 700 #374151 · 800 #1f2937 · 850 #1a1a2e · 900 #16213e · 950 #131327` | 中性：背景/文本/边框 |

### 2.2 尺寸

| 类别 | token | 值 |
|---|---|---|
| 间距 | `--p-space-1..12/16` | 4px 基数：1=4 · 2=8 · 3=12 · 4=16 · 5=20 · 6=24 · 8=32 · 10=40 · 12=48 · 16=64 |
| 圆角 | `--p-radius-xs/sm/md/lg/xl/full` | 4 / 6 / 8 / 12 / 16 / 999px（卡片默认 `lg`=12，控件 `md`=8，胶囊 `full`） |
| 字号 | `--p-fs-xs/sm/md/base/lg/xl/2xl/3xl/4xl` | 11 / 12 / 12.5 / 14 / 16 / 18 / 22 / 26 / 36 |
| 字重 | `--p-fw-regular/medium/semibold/bold/extrabold` | 400 / 500 / 600 / 700 / 800 |
| 字体 | `--font-sans` / `--font-mono` | 与 `variables.css` 同源（拉丁在前 + CJK 回退）；`typography.ts` / `echarts-theme.ts` 必须同步 |

---

## 3. ② Semantic 层（双主题对照）

★ 页面与组件的唯一取色入口。选择器：`:root`/`:root[data-theme="light"]`/`.force-light` 与 `:root[data-theme="night"]`/`.force-night`。

### 3.1 表面

| token | light | night | 用途 |
|---|---|---|---|
| `--bg` | `#fafbfc` | `#1a1a2e` | 页面主背景 |
| `--bg-2` | `#f3f4f6` | `#16213e` | 次级背景（分段控件底/芯片底） |
| `--bg-3` | `#e5e7eb` | `rgba(255,255,255,.05)` | 三级背景（表头底） |
| `--card` | `#ffffff` | `rgba(255,255,255,.055)` | 卡片/区块 |
| `--card-glass` | `rgba(255,255,255,.92)` | `rgba(19,19,39,.88)` | 毛玻璃浮层（抽屉/对话框） |
| `--overlay` | `rgba(15,23,42,.45)` | `rgba(5,8,20,.60)` | 遮罩 |

### 3.2 文本 / 边框

| token | light | night | 用途 |
|---|---|---|---|
| `--text` | `#1f2937` | `#ffffff` | 主文本 |
| `--text-2` | `#6b7280` | `rgba(255,255,255,.76)` | 次级文本 |
| `--text-3` | `#9ca3af` | `rgba(255,255,255,.55)` | 辅助/图注/轴标签 |
| `--text-disabled` | `#d1d5db` | `rgba(255,255,255,.32)` | 禁用 |
| `--text-inverse` | `#ffffff` | `#1a1a2e` | 反色（深底白字 / 亮底深字） |
| `--border` | `#e5e7eb` | `rgba(255,255,255,.10)` | 常规分隔线 |
| `--border-2` | `#d1d5db` | `rgba(255,255,255,.18)` | 控件边框/强调分隔 |

### 3.3 品牌

| token | light | night | 说明 |
|---|---|---|---|
| `--brand` | `#2563eb`（blue-600） | `#f9a825`（amber-500） | 主品牌；night 与 EP `--el-color-primary` 同源 |
| `--brand-2` | `#1d4ed8` | `#ffd54f` | 品牌渐变终点/悬停 |
| `--grad-brand` | `135deg(#1d4ed8→#2563eb)` | `135deg(#c17900→#f9a825 55%→#ffd54f)` | 主按钮/标题渐变/Logo |
| `--on-brand` | `#ffffff` | `#ffffff` | 品牌底上的前景色 |
| `--active-bg` | brand 10% | brand 12% | 选中菜单/激活态底（color-mix） |
| `--focus-ring` | brand 35% | brand 40% | 键盘焦点环 |

### 3.4 状态

| 语义 | light（主 / 亮） | night（主 / 亮） | 典型用途 |
|---|---|---|---|
| `--success / -2` | `#047857 / #10b981` | `#11998e / #38ef7d` | Pass、良率达标、成功横幅 |
| `--warn / -2` | `#92400e / #f59e0b` | `#f9a825 / #ffd54f` | 告警横幅、良率临界、趋势线 |
| `--error / -2` | `#b91c1c / #dc2626` | `#f5576c / #f77889` | Fail、LCL、危险操作 |
| `--info / -2` | `#0369a1 / #0ea5e9` | `#4facfe / #00f2fe` | 信息、总数柱 |
| `--grad-success/warn/error/info` | 135deg 双色渐变（night 为三段金绿/金/粉红渐变） | | 危险按钮、渐变强调 |

派生背景统一用 `color-mix(in srgb, var(--success) 14%, transparent)` 形式，**不再**为每个派生色建 token。

### 3.5 图表

| token | light | night | 用途 |
|---|---|---|---|
| `--chart-1..8` | `#2563eb · #10b981 · #f59e0b · #dc2626 · #0ea5e9 · #6b7280 · #11998e · #60a5fa` | `#f9a825 · #38ef7d · #ffd54f · #f5576c · #4facfe · #00f2fe · #f093fb · rgba(255,255,255,.62)` | 多序列色板（多文件对比/图例） |
| `--bin-pass` | `#10b981` | `#38ef7d` | Bin 1 良品 |
| `--spc-ucl / --spc-cl / --spc-lcl` | `#10b981 / #9ca3af / #b91c1c` | `#38ef7d / rgba(255,255,255,.5) / #f5576c` | SPC 控制线 |
| 热力格基色 | `--error` + `color-mix` 透明度 | 同左 | Bin×Site 交叉表热度 |
| 图表网格 | `--bar-grid`（`#eef0f3` / `rgba(255,255,255,.04)`） | | 柱图底网格 |

### 3.6 阴影 / chrome

| token | light | night |
|---|---|---|
| `--shadow-sm` | `0 1px 3px rgba(15,23,42,.06),0 1px 2px rgba(15,23,42,.04)` | `0 2px 8px rgba(0,0,0,.35)` |
| `--shadow-md` | `0 4px 12px rgba(15,23,42,.10),0 2px 6px rgba(15,23,42,.06)` | `0 8px 24px rgba(0,0,0,.45)` |
| `--shadow-lg` | `0 8px 24px rgba(15,23,42,.14),0 4px 12px rgba(15,23,42,.08)` | `0 16px 48px rgba(0,0,0,.55)` |
| `--sidebar-bg` | `#ffffff` | `#131327` |
| `--topbar-bg` | `rgba(255,255,255,.92)` | `rgba(19,19,39,.92)` |
| `--row-stripe` | `rgba(15,23,42,.015)` | `rgba(255,255,255,.025)` |

用法：卡片常态 `sm`；悬停/小浮层 `md`；抽屉/对话框 `lg`。

---

## 4. 排版规范

| 字阶 | 规格 | 使用场景 |
|---|---|---|
| 4xl | 36 / 800 | 仅营销性大标题（极少用） |
| 3xl | 26 / 800 | 页面主标题（渐变文字 `--grad-brand` 裁切） |
| 2xl | 22 / 800 | KPI 数值（`tabular-nums`） |
| lg | 16 / 700 | 弹窗/抽屉标题 |
| base | 14 / 500 | 正文、菜单、按钮（按钮 13px/600） |
| md | 12.5 / 400 | 表格内容 |
| sm | 12 / 600 | 次级数值、图例行（数值一律 `tabular-nums`） |
| xs | 11 / 500 | 辅助说明、单位、图注（配 `--text-3`） |
| mono | `--font-mono` | CPK/统计值等等宽读数场景 |

规则：**所有数字使用 `font-variant-numeric: tabular-nums`** 保证列对齐；字重只取 400/500/600/700/800 五档。

## 5. 间距 / 圆角 / 阴影规则

- 卡片内边距 16（`--p-space-4`）；区块间垂直节奏 16；页面左右 24–28。
- 控件高 30–34；按钮内边距 `8px 14px`（小按钮 `5px 10px`）。
- 圆角：卡片/横幅 12（`--p-radius-lg`）；按钮/输入/表格单元 8/6；胶囊（阶段芯片/分页/头像）`full`。
- 主题切换全局过渡：`transition: background .25s, color .25s`（body 级），禁止给阴影加大范围过渡造成闪动。

---

## 6. 图表规范

### 6.1 通用

- 轴线/网格弱化（`--border` / `--bar-grid`），轴标签 `--text-3`，数值标签 `--text-2`。
- Pass/Fail 永远用 `--success*` / `--error*` 语义对，不得随意换色；限外数据统一 `--error-2` 高亮。
- SPC 三线固定 `--spc-ucl/--spc-cl/--spc-lcl`，虚线样式：UCL `4 6`、CL `6 4`、LCL `4 6`。

### 6.2 ECharts JS 侧取色（不认 CSS 变量）

`utils/echarts-theme.ts` 的 `useEChartsTheme()` 是 JS 语义色单一来源，目标映射：

| echarts-theme 字段 | 对应语义 | light 目标 | night 目标 |
|---|---|---|---|
| `titleColor` | `--text` | `#1f2937` | `#ffffff` |
| `textColor` / `legendTextColor` / `axisLabelColor` | `--text-2` | `#6b7280` | `rgba(255,255,255,.76)` |
| `subtextColor` | `--text-3` | `#9ca3af` | `rgba(255,255,255,.55)` |
| `axisLineColor` / `borderColor` / `splitLineColor` | `--border`/`--bar-grid` | `#e5e7eb` / `#eef0f3` | `rgba(255,255,255,.10)` / `rgba(255,255,255,.04)` |
| `tooltipBg` / `tooltipText` | `--card-glass` / `--text` | 白玻璃 / `#1f2937` | 深色玻璃 / `#ffffff` |
| `seriesColors[0..7]` | `--chart-1..8` | 见 §3.5 | 见 §3.5 |

> ⚠️ 迁移注意：当前 `seriesColors` 已通过 CVD 色盲模拟验证（protan/deutan ΔE≥15，
> 注释见 `echarts-theme.ts:69`），其中 `#d97706/#86198f/#475569/#b45309/#ff9f43` 等
> 是为色盲可分辨**特意替换过的**。§3.5 的目标色板在正式切换前必须重跑同样的
> CVD 验证；验证通过前，**ECharts 序列色维持现状**，仅轴系/文本/tooltip 颜色按上表对齐。

### 6.3 与 Element Plus 的同源关系

| EP 变量 | 语义 token | 说明 |
|---|---|---|
| `--el-color-primary` | `--brand` | light `#2563eb` / night `#f9a825`，双块必须对称（教训 R7） |
| `--el-color-success` | `--success` | light `#047857` / night `#11998e` |
| `--el-color-warning` | `--warn` | light 用深琥珀 `#92400e` 系（EP 现为 `#b45309`，迁移时统一） |
| `--el-color-danger` | `--error` | light `#b91c1c` / night `#f5576c` |
| `--el-color-info` | `--info` | light `#0369a1` / night `#4facfe` |
| `--el-color-*-light-9` | `color-mix(--x 12-15%)` | 派生浅底统一用 color-mix 表达 |

---

## 7. 主题机制

- 挂载点：`<html data-theme="light|night">`；Pinia theme store 是唯一写入方。
- 初始值跟随 `prefers-color-scheme`，用户显式切换后持久化。
- 局部强制主题：容器加 `.force-light` / `.force-night`（语义选择器已并列挂载），用于双主题对照、预览卡等场景；**禁止**用它做页面级覆盖（教训 R7：组件只认 token）。
- `color-scheme: light/dark` 随主题声明，保证原生控件（滚动条/日期输入）跟随。
- 禁止任何形式的「页面级全局 night 覆盖块」；scoped 样式内只写 `var(--xxx)`。

## 8. DO / DON'T

**DO**
- ✅ 样式只引用语义层：`color: var(--text-2)`、`background: var(--card)`。
- ✅ 派生透明色用 `color-mix(in srgb, var(--error) 14%, transparent)`。
- ✅ 数值一律 `tabular-nums`；图表走 `useEChartsTheme()` + `initEchartsWhenReady`（教训 R7）。
- ✅ 改任何前端组件时双主题都看一眼（项目硬约束）。

**DON'T**
- ❌ 组件/页面样式里写字面 hex 或 `rgb()`（token 定义文件除外）。
- ❌ 直接引用 `--p-*`（那是语义层的原料）。
- ❌ 为单个页面新造颜色；确需新色，先并入 Primitive 色阶再走语义层。
- ❌ ECharts option 里写 `var(--xxx)`（canvas 不解析）。
- ❌ 只维护单主题、或 EP 主题块 light/night 不对称。

---

## 9. 迁移映射（现有 → 新）

### 9.1 `variables.css`

| 现有 | 新 token | 备注 |
|---|---|---|
| `--bg-primary` | `--bg` | 值相同 |
| `--bg-secondary` | `--bg-2` | 值相同 |
| `--bg-tertiary` | `--bg-3` | 值相同 |
| `--border-default` | `--border-2` | `#d1d5db`（新体系中它是"控件边框"） |
| `--border-muted` | `--border` | `#e5e7eb` |
| `--border-emphasis` | `var(--p-slate-400)` 或 `--text-3` | 语义层未保留该档 |
| `--text-primary/secondary` | `--text/--text-2` | 值相同 |
| `--text-tertiary` | `--text-3` | 值微调 `#717880`→`#9ca3af`（preview 基准，更轻盈） |
| `--text-inverse` | `--text-inverse` | 值相同 |
| `--brand-primary` | `--brand` | 值相同 |
| `--brand-primary-hover` | `--brand-2` | 值相同 |
| `--brand-secondary` | 无直接对应 | light 橙 `#ea580c` 退场；强调用 `--warn`，night 青绿已由 `--success` 覆盖 |
| `--brand-primary-rgb` | 删除 | `rgba()` 场景一律改 `color-mix()` |
| `--color-success(-emphasis)` | `--success(-2)` | emphasis 语义并入 `-2` 亮档 |
| `--color-warning` | `--warn` | `#b45309`→`#92400e`（略深，与 EP 统一时一并对齐） |
| `--color-error` | `--error` | 值相同 |
| `--color-info` | `--info` | 值相同 |
| `--color-fail-bg/-text` | `color-mix(var(--error) 22-55%, transparent)` / `--error` | 相关性对比标红格 |
| `--shadow-sm..xl` | `--shadow-sm/md/lg` | xl→lg 合并 |
| `--font-*`/`--text-*`/`--spacing-*` | 保留，逐步替换为 `--p-*` 命名 | 低优先 |

### 9.2 迁移顺序建议

1. `design-tokens.css` 先与 `variables.css` **并存**（不删旧文件），新代码用新 token；
2. 按 app 分批替换（dashboard → analysis → 其余），每批跑 theme/dashboard e2e；
3. `element-plus-theme.css` 双块按 §6.3 对齐后，再删 `variables.css`；
4. ECharts `seriesColors` 单独一批（先做 CVD 复验，见 §6.2 警告）。

---

## 10. 组件层（暂缓）

组件级 token（`--table-head-bg` / `--badge-*-bg` / `--kpi-accent-*` 等）已在
`design-system-preview.html` 中原型化，但**本轮不落地**：现有组件（`components/common/*`、
共享卡片组件等）维持现状，直接用语义层即可。待本轮 Semantic 层迁移稳定后，
再单独评审组件层命名与接入方案。

## 11. 参考

- 视觉基准 / token 展示：`docs/plans/design-system-preview.html`（零依赖可运行）
- 仪表板重建原型：`docs/plans/dashboard-rebuild-preview.html`
- 历史理念（已被本指南取代，仅作背景）：`frontend/LIGHT_THEME_STYLE_GUIDE.md`、`frontend/NIGHT_THEME_STYLE_GUIDE.md`
- 相关教训：`docs/tasks/lessons.md` R7（主题与图表）
