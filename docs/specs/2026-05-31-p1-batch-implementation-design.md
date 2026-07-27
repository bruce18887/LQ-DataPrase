# P1 批次实现设计方案

## 概述

本文档描述 ATE 数据分析平台 Roadmap P1 优先级（中优先级）7 个任务的批次实现方案。采用"统一设计 → 按层并行实现"的策略：Phase 1 全后端并行，Phase 2 全前端并行，Phase 3 收尾。

## P1 任务清单

| 编号 | 任务名称 | 类型 | 依赖 |
|------|---------|------|------|
| TODO-07 | Yield Trend 良率趋势后端 | 后端 | 无 |
| TODO-08 | YieldTrendChart 仪表板组件 | 前端 | TODO-07 |
| TODO-09 | Yield By Zone 分区良率 | 后端 | 无 |
| TODO-10 | Wafer Map 分区高亮 | 前端 | TODO-09 |
| TODO-11 | QQ Plot 正态性检验 | 后端+前端 | 无 |
| TODO-12 | 多 Lot 良率对比扩展 | 后端+前端 | 无 |
| TODO-13 | UPH 单位小时产量计算 | 后端 | 无 |

## 架构总览

```
Backend                                Frontend
┌──────────────────────┐             ┌──────────────────────────┐
│ yield_trend API       │◄──────┬───►│ YieldTrendChart          │
│ (+SPC UCL/LCL)       │       │    │ (DashboardPage 卡片)     │
├──────────────────────┤       │    ├──────────────────────────┤
│ compute_zonal_yield()│◄──────┼───►│ WaferMapPanel 分区模式    │
│ (statistics.py)      │       │    │ (+ZoneStatsCard)         │
├──────────────────────┤       │    ├──────────────────────────┤
│ qqplot API            │◄──────┼───►│ QQPlotChart             │
│ (scipy.stats.probplot)│       │    │ (SingleParamTab 补充)    │
├──────────────────────┤       │    ├──────────────────────────┤
│ multi_lot (扩展)      │◄──────┼───►│ MultiLotPanel 良率标签    │
│ mode='yield' 模式     │       │    │                          │
├──────────────────────┤       │    └──────────────────────────┘
│ efficiency.py         │◄──────┘
│ compute_uph()         │
└──────────────────────┘
```

## 后端设计

### 1. TODO-07: Yield Trend 良率趋势

**端点**: `POST /analysis/yield_trend/`

**请求**:
```json
{ "file_ids": [123, 124, 125] }
```

**响应**:
```json
{
  "files": [{ "file_id": 123, "filename": "lot1", "timestamp": "2026-05-30" }],
  "trend_data": [
    { "file_index": 0, "yield_pct": 95.2, "pass_count": 952, "total_count": 1000 }
  ],
  "spc_limits": { "ucl": 98.5, "cl": 95.0, "lcl": 91.5 },
  "anomalies": [{ "file_index": 2, "yield_pct": 88.3, "reason": "below_lcl" }]
}
```

**逻辑** (`statistics.py` 新增 `compute_yield_trend()`):
- 复用 `calculate_fail_bin_statistics()` 获取每个文件的良率
- 按时间序列计算整体均值 → UCL/CL/LCL
- 标记超出控制限的异常点

**文件**: `apps/analysis/views.py` + `apps/analysis/services/statistics.py`

### 2. TODO-09: Yield By Zone 分区良率

**函数**: `statistics.py` 新增 `compute_zonal_yield()`

```
Zones: 中心区 (radius ≤ 0.33R)
       中间区 (0.33R < radius ≤ 0.66R)
       边缘区 (radius > 0.66R)
```

**返回**:
```json
{
  "zones": [
    { "name": "中心区", "total": 300, "pass": 285, "fail": 15, "yield": 95.0 }
  ],
  "wafer_radius": 100,
  "zone_boundaries": [0.33, 0.66]
}
```

**逻辑**: 复用已有 X/Y 坐标列，计算每个 die 到中心距离，按半径比例分区，统计各区域 Pass/Fail。

**文件**: `apps/analysis/services/statistics.py`

### 3. TODO-11: QQ Plot 正态性检验

**端点**: `POST /analysis/qqplot/`

**请求**: `{ "file_id": 123, "param": "VCC" }`

**响应**:
```json
{
  "param": "VCC", "n": 1000,
  "theoretical": [-3.0, -2.5, ..., 2.5, 3.0],
  "observed": [2.1, 2.2, ..., 2.5, 2.6],
  "r_squared": 0.985,
  "is_normal": true
}
```

**逻辑**: 使用 `scipy.stats.probplot` 计算。R² > 0.95 判定为正态分布。

**文件**: `apps/analysis/views.py` + `apps/analysis/services/statistics.py`

### 4. TODO-12: 多 Lot 良率对比扩展

在现有 `POST /analysis/multi_lot/` 端点新增 `mode: "yield"` 参数。

**请求**: `{ "file_ids": [1,2,3], "mode": "yield" }`

**响应**:
```json
{
  "mode": "yield",
  "yield_data": [
    { "file_id": 1, "filename": "lot1", "yield": 95.2, "pass": 952, "total": 1000 }
  ],
  "chi_square": { "statistic": 3.2, "p_value": 0.20, "significant": false },
  "outliers": [],
  "global_stats": { "mean_yield": 94.5, "std_yield": 1.8 }
}
```

**增强逻辑**:
- 当 `mode === 'yield'` 时走新分支：计算每个文件的良率，不做参数分布对比
- 添加卡方检验和异常批次识别

**文件**: `apps/analysis/views.py`

### 5. TODO-13: UPH 计算

**新文件**: `apps/analysis/services/efficiency.py`

**函数**: `compute_uph(df, test_time_col=None)`

**返回**:
```json
{
  "uph": 1250,
  "avg_test_time": 2.88,
  "total_tested": 10000,
  "total_time_seconds": 28800,
  "by_site": [{ "site": "1", "tested": 2500, "uph": 1250 }],
  "source": "column",
  "warnings": []
}
```

**数据源优先级**:
1. 自动检测 Test Time 列（`test_time`/`cycle_time`/`testtime`）
2. 从文件元数据估算
3. 支持手动传入测试时间参数

## 前端设计

### 1. TODO-08: YieldTrendChart 仪表板卡片

**新文件**: `frontend/src/pages/dashboard/components/YieldTrendChart.vue`

**集成位置**: `DashboardPage.vue` — Fail 测试项分析 与 数据质量概览 之间

**UI 布局**:
- ECharts 折线图展示 trend_data
- UCL/LCL markLine 作为控制限参考线
- 异常点 markPoint 红色高亮
- dataZoom 滑块支持时间范围选择
- 文件选择器允许用户选择文件列表

**Props**:
```typescript
interface Props {
  fileId: number | null
}
```

### 2. TODO-10: Wafer Map 分区高亮

**文件**: `frontend/src/pages/analysis/components/WaferMapPanel.vue`（修改）

**新增功能**:
- 工具栏添加「分区模式」切换按钮（普通模式 | 分区模式）
- 分区模式下调用 `compute_zonal_yield()` 获取数据
- 晶圆图上绘制三个半透明扇形区域（中心/中间/边缘）
- 右侧新增分区统计卡片 ZoneStatsCard

**数据流**: 分区模式 → 调用 API(zonal_yield) → 更新图表叠加层 → 更新统计卡片

### 3. TODO-11: QQPlotChart 组件

**新文件**: `frontend/src/pages/analysis/components/QQPlotChart.vue`

**集成位置**: `SingleParamTab.vue` — 数值分布模式下，新增"显示QQ图"复选框

**UI 布局**:
- ECharts 散点图（observed vs theoretical quantiles）
- 对角线 y=x 参考线
- StatsSummary 区域显示 R² 和正态性判断（tooltip/标签）

**Props**:
```typescript
interface Props {
  fileId: number | null
  param: string
  visible: boolean
}
```

### 4. TODO-12: MultiLotPanel 良率标签

**文件**: `frontend/src/pages/analysis/components/MultiLotPanel.vue`（修改）

**新增功能**:
- 新增「良率对比」子标签页（当前为「分布对比」）
- 良率对比模式下：无需选择参数，直接调用 `multi_lot?mode=yield`
- ECharts 柱状图：每批次一根柱子，标注良率值
- 表格：批次名/测试数/Pass数/良率/异常标记
- 统计摘要：均值/标准差/最高/最低良率

## 执行计划

### Phase 1: 后端（并行子代理）

| 子代理 | 任务 | 文件 | 依赖 |
|--------|------|------|------|
| Agent A | `compute_yield_trend()` + yield_trend 端点 | statistics.py + views.py | 无 |
| Agent B | `compute_zonal_yield()` | statistics.py | 无 |
| Agent C | `compute_qqplot()` + qqplot 端点 | statistics.py + views.py | 无 |
| Agent D | multi_lot yield 扩展 | views.py | 无 |
| Agent E | efficiency.py + compute_uph() | 新文件 efficiency.py | 无 |

### Phase 2: 前端（并行子代理）

| 子代理 | 任务 | 文件 | 依赖 |
|--------|------|------|------|
| Agent F | YieldTrendChart + DashboardPage 集成 | 新建 + 修改 | Agent A |
| Agent G | WaferMap 分区模式 | WaferMapPanel.vue | Agent B |
| Agent H | QQPlotChart + SingleParamTab 集成 | 新建 + 修改 | Agent C |
| Agent I | MultiLotPanel 良率标签 | MultiLotPanel.vue | Agent D |

### Phase 3: 收尾

| 子代理 | 任务 | 文件 |
|--------|------|------|
| Agent J | 更新 RoadmapPage.vue P1 状态 | RoadmapPage.vue |
| Agent K | 验证 + 清理测试用文件 | — |

## 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| YieldTrend 定位 | 仪表板卡片 | 良率趋势是全局监控指标，适合放在 Dashboard |
| QQ Plot 定位 | SingleParamTab 补充 | 分布诊断的辅助工具，与直方图配合使用 |
| 多 Lot 良率对比 | MultiLotPanel 子标签页 | 复用现有文件选择逻辑，UI 操作流程一致 |
| UPH 数据源 | 列优先→元数据→手动 | 灵活应对不同格式的 ATE 数据 |
| 执行策略 | 按层并行(C) | 后端同一层、前端同一层，并行度最佳 |
