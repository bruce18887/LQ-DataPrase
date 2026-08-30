# LQ-DataPrase UI 设计指南（Design Tokens）

**日期**: 2026-08-29 · **状态**: 生效（含组件篇 §10 四批定稿 + 仪表板页面篇 §11 定稿，§11 已含 2026-08-30 落地修正）
**视觉基准**: `docs/plans/dashboard-rebuild-preview.html`、`docs/plans/design-system-preview.html` 与组件审阅页 `docs/plans/component-review-1..4-*.html`
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
        ↓ 组件按需引用（不新增组件级 token）
③ Component（组件设计规范，见 §10）
   徽标/按钮/表单/卡片/表格/浮层/反馈的统一规格，样式直接取用语义层
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

## 10. 组件篇（四批定稿 · 2026-08-29）

> 定稿过程与弃选方案留档：`docs/specs/2026-08-29-component-redesign-review-design.md`；
> 可视化对照：`docs/plans/component-review-1..4-*.html`（可双击打开，双主题）。
> 总基调：**A 延续渐变**（按钮/激活页签/Logo 保留品牌渐变）；旧「工业风/霓虹」发光效果一律移除。
> 组件层不新增 token：以下规格全部直接取用语义层 + `color-mix()` 派生。

### 10.1 徽标 Badges（主变体 = V1 柔和底）

| 项 | 规格 |
|---|---|
| 基础样式 | 彩底 `color-mix(in srgb, <语义色> 13%, transparent)` + 同色文字，无边框；11.5px/700，圆角 6，`tabular-nums`；大号 12.5px（顶部条/关键位） |
| 良率族 | ≥95 优 = `--success` ▲ / ≥90 警 = `--warn` ◆ / <90 差 = `--error` ▼ |
| CPK 族 | A✓ 绿（--success）/ B● 品牌色（--brand）/ C◆ 琥珀（--warn）/ D▼ 红（--error，底色加深到 22%） |
| Bin 族 | 并入徽标变体：pass（Bin 1）= good，普通 = neutral，高失 = bad |
| 中性/趋势 | 中性 = `--text-2` 12% 底；趋势 chip 胶囊形：▲ 绿 / ▼ 红 / — 中性 |
| 区分原则 | **色相 + 形状双编码**（night 下 --brand 与 --warn 同为金黄，B/C 靠 ●◆ 区分）；禁用纯色实心变体于多行表格 |

### 10.2 按钮 Buttons

| 型 | 规格 |
|---|---|
| primary | 品牌渐变 `--grad-brand` + `--on-brand` 文字，`--shadow-sm` |
| ghost | `--card` 底 + `--border-2` 边框 + `--text-2`；悬停转品牌色 |
| danger | **纯红实心** `var(--error)`（弃用红色渐变） |
| text | 无边框、品牌色，链接式 |
| 尺寸 | 默认 13px/600，内边距 8·15，圆角 8；小 12px，5·11，圆角 7 |
| 悬停 | **X 抬升**：全部上移 1px + 阴影加深（0.12s） |
| 禁用/焦点 | 禁用 45% 透明去阴影；`--focus-ring` 2px 焦点环（outline-offset 2px） |

### 10.3 表单

- 输入/下拉/日期：高 34，圆角 8，底 `--bg`（与卡面形成层次），边框 `--border-2`；
  焦点 = 品牌边框 + 3px `--focus-ring`；禁用 50% 透明 + `--bg-2` 底。
- 错误态：`--error` 边框 + 25% 红色光环 + 11px 错误提示文字。
- 开关：开 = 品牌渐变，关 = `--bg-3` + `--border-2`；滑杆 15px。
- 复选/单选：`accent-color: var(--brand)`，随 `color-scheme` 双主题自适配。
- 分段控件（视角切换）：`--bg-2` 底容器 + 激活项 `--card` 底/品牌字/`--shadow-sm`。

### 10.4 卡片

- 卡片底 `--card`（night 为半透明白），边框 `--border`，圆角 12，`--shadow-sm`；内边距 16。
- Section 卡：卡头 = **浅底带**（`color-mix(--bg-2 60%, --card)`）+ 底分隔线；
  标题 14/700（可带 emoji 图标）+ `--text-3` 说明 + 右侧操作区。
- KPI Card 不在组件范围（批次报表已删除该组件）。
- 禁止：neon 发光、2px 粗边框、`:root.theme-*` 页面级覆盖（教训 R7）。

### 10.5 表格（T2 纯分隔线）

- 无斑马纹；行分隔 `--border`；行悬停品牌色 10% 淡染；表头 `--bg-3` 底 + `--text-2` 600。
- 字号 12.5，行内边距 7–10；数字列右对齐 + `tabular-nums`；行链接品牌色悬停下划线。
- Fail 列 **>0 一律红字加粗**（`--error`）；热力格按 `color-mix(--error, n%)` 深浅染色。
- Level 徽标按 §10.1 CPK 族双编码。
- 斑马纹（T1）已弃选；EP el-table 场景经主题覆写向本规格对齐。

### 10.6 Tabs 与页签（两形态）

- **下划线 Tabs**（页内功能页签）：激活 = 品牌色文字 + 2px 品牌下划线；默认 `--text-2`。
- **胶囊 Tabs**（顶层视图切换）：激活 = `--grad-brand` 实底 + `--on-brand` 文字；默认卡底描边。
- 分段控件见 §10.3（视角切换用，不属于 Tabs）。

### 10.7 浮层（对话框 / 抽屉 / Toast）

| 组件 | 规格 |
|---|---|
| 对话框 | 居中，`--card-glass` + blur 14，圆角 12，`--shadow-lg`；标题 14/700 + 图标；正文 13/`--text-2`；底部按钮右对齐（危险动作用纯红按钮）；0.18s 缩放动效 |
| 抽屉 | 右侧 560px（max 92vw），同毛玻璃规格；头/体分隔，体可滚动；0.25s 滑入 |
| 遮罩 | `--overlay`，点击关闭；浮层 z-41 / 遮罩 z-40 / Toast z-60 |
| Toast | **顶部居中**（与 EP message 习惯一致）；毛玻璃卡 + 左侧 3px 语义色条 + 语义色文字；2.2s 自动消失 |
| EP 对齐 | el-dialog / el-drawer / el-message 经 `element-plus-theme.css` 覆写向本规格对齐 |

### 10.8 反馈（横幅 / 空状态 / 骨架 / 分页 / Tooltip）

- 告警横幅（四色）：底 `color-mix(<语义色> 10%)` + 边框 40%，圆角 12；标题语义色 13/700 + 图标；
  正文 `--text-2` 12；可展开明细（仪表板现有交互保留）。
- 空状态：图标（34 半透明）+ 说明（13/600 `--text-2`）+ 主动作（primary 小按钮）。
- 加载骨架：`--bg-2 → --bg-3` 流光，圆角 6；尊重 `prefers-reduced-motion`。
- 分页：28×28 圆角 6，激活 = `--grad-brand` + `--on-brand`；悬停品牌描边。
- Tooltip：`--text` 底 + `--bg` 字（反色），11，圆角 6，`--shadow-md`，悬停 0.15s 淡入。
- 双主题规则：以上全部只取语义层，禁止页面级 night 覆盖（教训 R7）。

### 10.9 落地边界（另行排期）

1. `components/common/*` 改造：旧霓虹/发光样式清理；Button/Card/Badge/Loading/Empty 按本篇规格与 API 对齐；
   `:root.theme-*` 页面级覆盖清除。
2. 新增业务徽标组件（YieldBadge / CpkBadge / BinTag）替换各页面手写 span。
3. EP 覆写对齐（§10.7）与 e2e 选择器同步维护（教训 R2）。

## 11. 页面篇：仪表板（单文件 / 批次，定稿 2026-08-30）

> 详细设计与全部确认记录：`docs/specs/2026-08-29-dashboard-content-redesign-design.md`（单文件）、
> `docs/specs/2026-08-30-batch-dashboard-redesign-design.md`（批次）；可视化审阅页：
> `docs/plans/dashboard-redesign-review.html`、`docs/plans/batch-redesign-review.html`（双主题可交互）。
> 本章只定**信息架构与组合方式**，区块内部组件全部按 §10 定稿规格。
> 目标：提升信息集中度——去 KPI 大卡/Site GAP gauge/重复图表，整页纵向约减 45%。

### 11.1 页面级共用组件（两 Tab 同规格）

- **总览条（信息记录中枢）**：一行 label+value；数值大号 18/700、文本型小号 13.5；
  Pass 绿 / Fail>0 红 / 良率色阶；窄视口可换行；带 `data-testid`（`overview-strip`）。
- **告警/QA 横幅**：单行汇总（级别取最高）+ 点击展开明细，无告警零占位（§10.8 四色横幅）。
- **Bin 构成 = Pareto 横向条**（降序、pass 绿/fail 红、条内「数量 · 占比%」），取代饼图+占比表。
- **Site 良率 = 柱线组合**（柱色阶 + `--info` 良率折线 + 卡头 3 pills 最高/最低/Δ）；gauge 删除。
- **Bin×Site = 同卡「表格 / 热力图」页签**：表格热力格等宽居中 `数量(行内占比%)`、
  合计列 `数量 (占总记录%)`；**Bin 列纯文字不用徽标**（避免勾形误解，两表同）；
  热力图仅 Fail Bin、色深 = 行内集中度，**必须配 `visualMap`（show:false）**，
  插值色为具体 rgba（`var()`/`color-mix` 不参与 visualMap 插值，由 token hex 转换），
  数值标签用具体色值保双主题可读；无 Fail Bin 时空态提示。
- **百分比显示统一 `formatPercent`**：自适应精度、**最多 3 位小数**、极小非零显示 `<0.001`、去尾零；
  适用热力格、测试项总览 Fail 列与 chip、Site 柱顶标签、批次趋势线标签、YieldBadge 数值等全部百分比场景。
- **UPH 紧凑明细行**：平均测试时间/总耗时/并行站点数/各站点独立小格/来源标签/警告/公式（? 悬停）；
  `UphDetail` 为渲染函数组件，scoped 样式需 `:deep()`，teleported tooltip 用内联样式。
- **Section 卡浅底带卡头 + T2 表格**（§10.4/10.5）；表格样式统一走全局 `element-plus-theme.css`，
  禁止页面级 `:deep(.el-table)` 局部覆写；文本/时间列用 `min-width` 弹性撑满容器。

### 11.2 单文件分析 Tab 结构（自上而下）

1. 页头仅保留主标题（**20px**，图标 21px，左对齐；居中大标题/工具条行删除）；
   **文件选择器下沉到单文件 Tab 内首行**（与批次页头同一行式：选择器 + 更新元信息）。
2. 总览条：程序/总记录/Pass/Fail/Yield/UPH/测试时长/测试开始 + 格式 chip。
3. 告警单横幅。
4. 图表双列：Bin Pareto + Site 柱线组合（<900px 堆叠）。
5. Bin×Site 交叉表（表格/热力图页签）。
6. 测试项总览：CPK 堆叠比例条（**短段 `min-width:10px` 保底；占比 <10% 隐藏段内文字；
   条下方设图例行（色点 + 图标 + 等级 · 计数 (占比)）承载全量读数**）+ 11 列表格（Fail 列 `数量 (占比%)`，
   表头全列排序，卡头双复选框「忽略无 Limit/忽略无测试值」默认勾选，行点击跳转数据分析）+ Top 10 Fail 信息 chip 行。
7. UPH 紧凑明细行（页面最底部）→ 导出页脚。

### 11.3 批次良率 Tab 结构（自上而下）

1. 页头一行：标题 + 批次下拉 + 文件数/更新时间 + 加载/导出按钮。
2. 阶段胶囊过滤条（激活品牌渐变，点选全局收窄，再点取消）。
3. QA 数量校验横幅（仅全部/FT 阶段可见）。
4. 阶段汇总卡：总览条（投入/Pass/Fail/良率，随胶囊联动）+ 树形表（阶段聚合→版本明细）+
   良率趋势图（柱=总数、线=良率）同卡合并。
5. 阶段明细表：保留阶段/版本/程序/总数/通过/失败/良率/开始/结束等核心列，
   **删除操作员/工站/Device/Tester 列**（11 项元数据保留在展开 drill-down 行）；
   文本/时间列 `min-width` 弹性撑满；样式统一走全局 EP 主题（无局部覆写）。
6. Site 良率矩阵：每 Site **合并单列**（良率徽章 + Pass/Total 小字）+ All Site 列。
7. Bin 分布卡（单阶段口径，阶段下拉在卡头）：Pareto + Site 柱线双列 + Bin×Site 页签 + UPH 紧凑行。
   UPH 不上总览条（用户确认保持现状）。

### 11.4 落地现状与工程约定（2026-08-30 落地完成）

- **已落地**：批 1 单文件（e2aba14）/ 批 2 批次（fec0ff9）+ 三轮用户反馈修正（详见 §11.5）；
  `KpiCards`/`DataQualityOverview`/`QualityAlerts`/`OverviewCharts`/`BatchSelectorBar` 已删除；
  新增 `OverviewStrip`（`data-testid=overview-strip`，测试开始取 `/files/:id/` 的 `metadata.start_time`）/
  `AlertBanner`/`UphDetail`；`CollapsibleSection` 增 `header-extra` 槽。
- **不动**：后端接口与聚合、导出链路、阶段过滤联动、单阶段现算口径、行点击跳转/排序逻辑。
- **图表生命周期工程约定（防图表消失/空白）**：容器级 `observeContainerResize`
  （ResizeObserver + rAF 防抖，替代 window resize，避免隐藏 Tab `display:none` 时锁 0 尺寸）；
  `initEchartsWhenReady` 超时不 disconnect、容器后拿尺寸时自愈 init；`v-if` 容器重建时按元素身份
  dispose 旧实例再 init。
- **e2e**：`dashboard.spec`（总览条/柱线/页签/11 列/批次区块）、`batch-phase.spec`、
  `night-visibility` 已同步；新组件带 `data-testid`。

### 11.5 落地修正记录（与设计稿的差异，均为用户确认）

1. 热力图必须配 `visualMap`（否则 ECharts 拒渲整系列），插值用具体 rgba（见 §11.1）。
2. CPK 比例条短段保底/隐文/图例行（见 §11.2.6）。
3. 百分比统一最多 3 位小数（`formatPercent`，见 §11.1）。
4. UPH 各站小格排版修正（`:deep()` + 内联 tooltip，见 §11.1）。
5. Bin×Site 两表 Bin 列改纯文字（去徽标勾）。
6. 页头仅留 20px 主标题，文件选择器下沉入单文件 Tab（见 §11.2.1）。
7. 阶段明细表删 4 列，元数据入展开行（见 §11.3.5）。
8. 表格弹性列宽 + 全局 EP 主题统一（禁局部 `:deep(.el-table)` 覆写）。

## 12. 参考

- 视觉基准 / token 展示：`docs/plans/design-system-preview.html`（零依赖可运行）
- 仪表板重建原型：`docs/plans/dashboard-rebuild-preview.html`
- 组件审阅页（四批定稿）：`docs/plans/component-review-1..4-*.html`
- 仪表板重设计审阅页：`docs/plans/dashboard-redesign-review.html`（单文件）、`docs/plans/batch-redesign-review.html`（批次）
- 仪表板设计文档：`docs/specs/2026-08-29-dashboard-content-redesign-design.md`、`docs/specs/2026-08-30-batch-dashboard-redesign-design.md`
- 历史理念（已被本指南取代，仅作背景）：`frontend/LIGHT_THEME_STYLE_GUIDE.md`、`frontend/NIGHT_THEME_STYLE_GUIDE.md`
- 相关教训：`docs/tasks/lessons.md` R7（主题与图表）
