# 数据分析页面 Tab 布局统一改造设计

**日期**: 2026-06-13
**状态**: 待审批
**范围**: 前端 AnalysisPage 及其子组件的布局重构 + bug 修复

---

## 1. 需求概述

| # | 需求 | 类型 |
|---|---|---|
| 1 | 箱线图 tab：模式和布局完全复刻 SingleParamTab 三层布局 | 布局重构 |
| 2 | 箱线图 tab：修复无法展示的 bug | Bug 修复 |
| 3 | 相关性工具 tab：更名为"相关性对比"，模式和布局完全复刻 SingleParamTab 三层布局 | 布局重构 + 改名 |
| 4 | 单参数分析 tab：更名为"单文件分析" | 改名 |
| 5 | 多文件分析 tab：选择文件后立即开始加载计时 | 功能增强 |
| 6 | 数据分析页面顶部文件选择框：修改 label 文案 | 文案优化 |

---

## 2. 架构方案：共享布局组件

### 2.1 提取 `AnalysisTabLayout` 组件

从 SingleParamTab 中提取三层布局为共享组件，所有分析 tab 统一使用。

**组件结构**:
```
AnalysisTabLayout.vue
├── slot: toolbar          — 顶部工具栏（模式切换、可选操作）
├── el-row (gutter=12)
│   ├── el-col (span=leftPanelWidth)  — 左侧面板
│   │   └── slot: left-panel
│   └── el-col (span=rightPanelWidth) — 右侧面板
│       └── slot: right-panel
```

**Props**:
| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `loading` | `boolean` | `false` | 右侧面板 v-loading 状态 |
| `leftPanelSpan` | `number` | `6` | 左面板栅格宽度 (1-23) |
| `rightPanelSpan` | `number` | `18` | 右面板栅格宽度 (1-23) |

**样式**: 继承 SingleParamTab 的现有样式 — toolbar 灰色背景 (#f8f9fa)、12px padding、6px border-radius、1px border，左右面板 10px gap。

### 2.2 为什么选方案 A

- 三个 tab（单文件分析、箱线图、相关性对比）使用同一套布局
- 布局调整只需改一处
- 新增分析 tab 时可直接复用

---

## 3. 详细设计

### 3.1 箱线图改造（需求 1 + 2）

**当前状态**: BoxPlotSection.vue 是扁平布局 — 参数多选 + 分组下拉 + 生成按钮 + 图表列表。无工具栏、无左右面板。

**改造后布局**:
```
┌─────────────────────────────────────────────────────┐
│  Toolbar                                             │
│  ┌─────────────────────────────────────────────────┐ │
│  │ [不分组] [按 Site 分组] [按 Bin 分组]            │ │
│  └─────────────────────────────────────────────────┘ │
├────────────────┬────────────────────────────────────┤
│ Left Panel     │  Right Panel                        │
│ (span=6)       │  (span=18)                          │
│                │                                      │
│  参数多选器     │  Top Bar: 参数选择器 + 五数概括统计  │
│  (el-select    │                                      │
│   multiple)    │  Chart Area                          │
│                │  ┌──────────────────────────────────┐│
│  箱线图概念说明 │  │  BoxPlotChart (min-height: 480px)││
│  (info alert)  │  └──────────────────────────────────┘│
└────────────────┴────────────────────────────────────┘
```

**工具栏**: `<el-radio-group v-model="groupBy" size="small">` 三个选项：不分组 / 按 Site 分组 / 按 Bin 分组。

**左面板**:
- 参数多选器（el-select multiple）— 选择要展示的参数
- 箱线图概念说明（当前的 info alert，可折叠）

**右面板**:
- 顶部栏：当前选中参数的五数概括（min/Q1/median/Q3/max）+ 异常值数量
- 图表区：BoxPlotChart 组件，min-height 480px
- 当选择多个参数时，图表区域支持纵向滚动展示多个箱线图

**数据流**:
- 工具栏 `groupBy` 变化 → 触发 `useBoxPlot.loadBoxPlot()`
- 左面板参数选择变化 → 更新 `selectedParams` → 触发重新加载
- 右面板 loading 状态由 `useBoxPlot.loading` 驱动

**Bug 修复（需求 2）**:

后端 `apps/analysis/views.py` ~line 535:
```python
# 修复前
data_series = get_1d_from(df, param)
# 修复后
data_series = ensure_numeric(df, param)
```

前端 `BoxPlotChart.vue` tooltip formatter 索引修复:

ECharts 6 boxplot 数据格式：
- `boxData` 数组元素为 `[min, Q1, median, Q3, max]`（5 个元素，索引 0-4）
- 顶层 tooltip `params.value`：ECharts 内部会 prepend category index → `[catIdx, min, Q1, median, Q3, max]`（6 个元素，索引 0-5），所以 `d[1]`~`d[5]` 是正确的
- Series tooltip `p.data`：原始数据 `[min, Q1, median, Q3, max]`（5 个元素，索引 0-4），`p.data[5]` 越界为 `undefined`

修复方案 — 仅修改 series tooltip（line 70-71）:
```typescript
// 修复前（索引越界，p.data[5] 为 undefined，hover 会崩溃）
fmt(p.data[5]), fmt(p.data[4]), fmt(p.data[3]), fmt(p.data[2]), fmt(p.data[1])
// 修复后
fmt(p.data[4]), fmt(p.data[3]), fmt(p.data[2]), fmt(p.data[1]), fmt(p.data[0])
```

顶层 tooltip（line 55）保持不变，因为 `params.value` 含 category index，`d[1]`~`d[5]` 正确。

---

### 3.2 相关性对比改造（需求 3）

**当前状态**: CorrelationToolsTab.vue 是极薄的 wrapper，内部只有 CorrelationPanel（散点图 + X/Y 参数选择 + 轴范围设置）。

**改造后布局**:
```
┌─────────────────────────────────────────────────────┐
│  Toolbar                                             │
│  ┌─────────────────────────────────────────────────┐ │
│  │ [散点图] [相关性矩阵]                           │ │
│  └─────────────────────────────────────────────────┘ │
├────────────────┬────────────────────────────────────┤
│ Left Panel     │  Right Panel                        │
│ (span=6)       │  (span=18)                          │
│                │                                      │
│  散点图模式:    │  Top Bar: Pearson r 值 + 数据点数    │
│   X 轴参数选择  │                                      │
│   Y 轴参数选择  │  Chart Area                          │
│   轴范围设置    │  ┌──────────────────────────────────┐│
│   分析按钮      │  │  ScatterChart / MatrixHeatmap    ││
│                │  │  (min-height: 480px)              ││
│  矩阵模式:     │  └──────────────────────────────────┘│
│   参数多选器    │                                      │
│   方法选择      │                                      │
│   (pearson/    │                                      │
│    spearman/   │                                      │
│    kendall)    │                                      │
└────────────────┴────────────────────────────────────┘
```

**工具栏**: `<el-radio-group>` 切换散点图 / 相关性矩阵两种模式。

**左面板 — 散点图模式**:
- X 轴参数选择器
- Y 轴参数选择器
- 轴范围设置（sigma/custom/data range，当前 CorrelationPanel 的折叠面板）
- "分析相关性" 按钮

**左面板 — 矩阵模式**:
- 参数多选器（选择参与矩阵的参数）
- 相关性方法选择（pearson/spearman/kendall）
- "生成矩阵" 按钮

**右面板 — 散点图模式**:
- 顶部栏：Pearson r 值 + 数据点数 + 显著性标记
- 图表区：散点图（ECharts scatter）

**右面板 — 矩阵模式**:
- 顶部栏：矩阵尺寸 + 方法名
- 图表区：相关性矩阵热力图（ECharts heatmap）

**数据流**:
- 散点图：`useCorrelation.loadCorrelation(xParam, yParam)`
- 矩阵：`useCorrelationMatrix.loadMatrix(params, method)`
- 工具栏模式切换时，左面板内容动态切换，右面板图表类型随之变化

---

### 3.3 单文件分析 tab 调整（需求 4）

**改动**: `AnalysisPage.vue` line 23 label 从 `"单参数分析"` 改为 `"单文件分析"`。

**注意事项**:
- Pinia store `analysisStore.activeTab` 的值 `"single-param"` 保持不变（内部标识符，用户不可见）
- 路由和 API 无影响

---

### 3.4 多文件分析加载计时（需求 5）

**当前状态**: MultiFileTab 内部使用 `v-loading` 遮罩，无独立计时器。

**改造**: 在 MultiFileTab 右面板顶部添加 `CircularProgress` 组件，绑定到 `useMultiFile` composable 的 `loading` 状态。

**触发时机**:
1. 用户在 MultiFileTab 内选择文件（checkbox 勾选）
2. 点击"开始分析"按钮
3. 立即启动 `CircularProgress` 计时
4. 数据加载完成后计时结束

**实现**:
- 复用现有 `CircularProgress` 组件
- 在 MultiFileTab 的右面板顶部（图表区上方）添加
- 绑定 `loading` prop 到 `useMultiFile.loading`

---

### 3.5 文件选择框 label 优化（需求 6）

**当前 label**: `"数据文件 (选择后自动加载参数列表)"`
**新 label**: `"选择数据文件"` + 下方灰色辅助文字 `"选择后自动加载参数列表，各 tab 中可选择参数进行分析"`

**实现**: 使用 `<el-form-item>` 的 `#label` slot 或在 form-item 下方添加 `<div class="hint">` 元素。

---

## 4. 涉及文件清单

### 新建文件
| 文件 | 说明 |
|------|------|
| `frontend/src/pages/analysis/components/AnalysisTabLayout.vue` | 共享布局组件 |

### 修改文件
| 文件 | 改动 |
|------|------|
| `frontend/src/pages/analysis/AnalysisPage.vue` | tab label 改名 (需求 3,4)、label 文案 (需求 6) |
| `frontend/src/pages/analysis/components/SingleParamTab.vue` | 引入 AnalysisTabLayout 替换内联布局 |
| `frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue` | 重构为三层布局 + 使用 AnalysisTabLayout |
| `frontend/src/pages/analysis/components/BoxPlotChart.vue` | 修复 tooltip 索引 (需求 2) |
| `frontend/src/pages/analysis/components/CorrelationToolsTab.vue` | 重构为三层布局 + 使用 AnalysisTabLayout + 改名 |
| `frontend/src/pages/analysis/components/MultiFileTab.vue` | 添加 CircularProgress (需求 5) |
| `apps/analysis/views.py` | boxplot 端点添加 ensure_numeric (需求 2) |

### 可能涉及的文件
| 文件 | 说明 |
|------|------|
| `frontend/src/stores/analysis.ts` | 如果需要新增 store 字段 |
| `frontend/src/pages/analysis/composables/useBoxPlot.ts` | 如果需要调整 composable 接口 |

---

## 5. E2E 测试计划

| 测试场景 | 优先级 |
|----------|--------|
| 箱线图 tab 选择参数后正常展示图表 | P0 |
| 箱线图切换分组模式（不分组/Site/Bin）图表更新 | P0 |
| 箱线图 tooltip hover 显示正确的五数概括 | P1 |
| 相关性对比 tab 散点图正常展示 | P0 |
| 相关性对比 tab 矩阵模式正常展示 | P1 |
| 单文件分析 tab label 显示为"单文件分析" | P1 |
| 相关性对比 tab label 显示为"相关性对比" | P1 |
| 多文件分析选择文件后 CircularProgress 启动 | P1 |
| 文件选择框 label 和辅助文字正确显示 | P2 |
| Dark/Light 主题下布局和样式正确 | P1 |

---

## 6. 风险与注意事项

1. **AnalysisTabLayout 灵活性**: 三个 tab 的左面板内容差异较大（配置面板 vs 参数选择 vs 轴范围设置），slot 设计需要足够灵活，避免过度约束。
2. **BoxPlotChart tooltip 索引**: 需要实际运行验证 ECharts 6 中 boxplot 的 `params.value` 和 `p.data` 的确切格式。
3. **相关性矩阵模式**: 当前 `CorrelationMatrixSection` 已存在但未在 CorrelationToolsTab 中使用，需要确认是否可以直接引入。
4. **SingleParamTab 重构风险**: 将现有布局替换为 AnalysisTabLayout 时需要保持所有功能不变（QQ 图、站点统计、范围对比等）。
5. **主题兼容**: 所有新增样式必须同时适配 dark 和 light 主题。
