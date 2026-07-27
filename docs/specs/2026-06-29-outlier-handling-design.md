# 异常值处理设计方案

## 背景

半导体测试数据中经常出现极端异常值（如正常值 ~25，异常值 99999），导致数据可视化图表的坐标轴被严重拉伸，正常数据分布无法观察。当前项目中仅箱线图有 IQR 异常值检测（标红点），直方图、散点图、QQ 图、序列图均无异常值处理。

## 目标

为以下四种图表类型提供异常值检测和处理能力：

- **直方图 (HistogramChart)**
- **散点图 (CorrelationToolsTab / CorrelationPanel)**
- **QQ 图 (QQPlotChart)**
- **序列图 (SerialChart)**

## 设计决策

| 决策项 | 选择 | 理由 |
|---|---|---|
| 检测方法 | IQR（Q1 - 1.5×IQR ~ Q3 + 1.5×IQR） | 箱线图已使用，保持一致性；对极端值鲁棒，不假设正态分布 |
| 处理方式 | 裁剪显示范围（默认）+ 可切换完全排除 | 裁剪不丢数据，排除可重算统计值 |
| 架构方案 | 后端统一检测 + 前端只管渲染 | 逻辑集中，统计数据准确，前端改动小 |
| 配置粒度 | 全局默认 + 单图覆盖 | 平衡灵活性和简洁性 |

## 架构设计

### 1. 后端异常值检测层

#### 新增通用工具函数

**文件**：`apps/analysis/services/statistics/outliers.py`（新建）

```python
def detect_outliers_iqr(data: pd.Series) -> dict:
    """
    使用 IQR 方法检测异常值。

    Returns:
        {
            "has_outliers": bool,
            "outlier_count": int,
            "lower_bound": float,    # Q1 - 1.5 * IQR
            "upper_bound": float,    # Q3 + 1.5 * IQR
            "outlier_values": list,  # 异常值列表（仅 exclude 模式需要）
            "normal_count": int      # 正常值数量
        }
    """
```

**工作流程**：

1. 基本清洗：`pd.to_numeric(errors='coerce')` → `dropna()` → `np.isfinite()` 过滤
2. 若数据量 < 4，跳过检测，返回 `has_outliers: false`（IQR 不可靠）
3. 计算 Q1、Q3、IQR = Q3 - Q1
4. lower_bound = Q1 - 1.5 × IQR，upper_bound = Q3 + 1.5 × IQR
5. 分离异常值和正常值
6. 返回结构化结果

#### 改造现有 API 端点

每个端点在计算完统计数据后，额外调用 `detect_outliers_iqr`，在响应中增加 `outlier_info` 字段。

| API 端点 | 改动内容 |
|---|---|
| `GET /analysis/histogram/` | 返回 `outlier_info` + `filtered_cpk`（排除异常值后的 Cpk） |
| `GET /analysis/correlation/` | 返回 `outlier_info`（x 和 y 轴分别检测，返回 `x_outlier_info` 和 `y_outlier_info`） |
| `GET /analysis/qqplot/` | 返回 `outlier_info` |
| `GET /analysis/serial_distribution/` | 返回 `outlier_info` |

**API 响应示例**（以直方图为例）：

```json
{
    "bins": [...],
    "cpk": 1.5,
    "mean": 25.3,
    "std": 1.2,
    "outlier_info": {
        "has_outliers": true,
        "outlier_count": 3,
        "lower_bound": 20.5,
        "upper_bound": 29.3,
        "outlier_values": [99999, 88888, 77777],
        "normal_count": 997
    },
    "filtered_cpk": 2.1
}
```

**性能优化**：

- 裁剪模式下不传输 `outlier_values` 列表（减少 payload）
- 仅排除模式传输完整列表

### 2. 前端配置与交互

#### 全局配置：扩展 analysis store

**文件**：`frontend/src/stores/analysis.ts`

新增状态：

```typescript
outlierHandling: 'clip' | 'exclude' | 'off'  // 默认 'clip'
```

- `'clip'`：裁剪显示范围（默认，不丢数据）
- `'exclude'`：完全排除异常值（后端重新计算）
- `'off'`：不过滤，显示原始数据

#### 全局控制：AnalysisPage 顶部工具栏

在分析页面顶部（文件选择器旁边）增加异常值处理下拉框：

```
┌──────────────────────────────────────────────────────────────┐
│  [文件选择器]  [参数搜索]  [图表模式]  [异常值处理: ▼ 裁剪范围] │
└──────────────────────────────────────────────────────────────┘
```

选项：
- 裁剪范围（默认）
- 完全排除
- 不处理

#### 单图覆盖：图表组件局部控制

每个图表的工具栏区域增加切换按钮，默认跟随全局设置，用户可覆盖：

```
┌──────────────────────────────────┐
│  直方图               [✂ 裁剪]  │  ← 点击切换
│                                  │
│  ┌────────────────────────────┐  │
│  │                            │  │
│  │       图表区域             │  │
│  │                            │  │
│  └────────────────────────────┘  │
│  ⚠ 已裁剪 3 个异常值 (范围: 20~30) │  ← OutlierHintBar
└──────────────────────────────────┘
```

### 3. 各图表渲染逻辑

#### 直方图 (HistogramChart)

**裁剪模式**：

- x 轴范围设置为 `[lower_bound, upper_bound]`
- 超出范围的数据点不参与分桶计算
- Cpk 等统计指标仍用原始值（数据没真正丢弃）

**排除模式**：

- 后端用正常值重新计算分桶和 Cpk
- 前端直接渲染过滤后的数据
- Cpk 使用 `filtered_cpk`

#### 散点图 (CorrelationToolsTab)

**裁剪模式**：

- x 轴和 y 轴分别用各自的 IQR 边界裁剪
- 超出范围的点不渲染
- 回归线、Pearson r 基于完整数据

**排除模式**：

- 后端返回过滤后的散点数据
- 回归线、Pearson r、R² 基于过滤后数据重新计算

#### QQ 图 (QQPlotChart)

**裁剪模式**：

- 理论分位数轴和样本分位数轴都裁剪到合理范围
- 异常值点不渲染

**排除模式**：

- 后端用正常值重新计算分位数
- R² 和正态性判断基于过滤后数据

#### 序列图 (SerialChart)

**裁剪模式**：

- y 轴范围设置为 `[lower_bound, upper_bound]`
- 超出范围的点不渲染

**排除模式**：

- 后端返回过滤后的序列数据

### 4. 异常值提示条组件

**文件**：`frontend/src/pages/analysis/components/OutlierHintBar.vue`（新建）

复用于所有支持异常值处理的图表底部，显示：

```
⚠ 已裁剪 3 个异常值，范围外值: [99999, 88888, 77777]（正常范围: 20.5 ~ 29.3）
```

**Props**：

```typescript
interface OutlierHintBarProps {
    mode: 'clip' | 'exclude' | 'off'
    outlierInfo: {
        has_outliers: boolean
        outlier_count: number
        lower_bound: number
        upper_bound: number
        outlier_values?: number[]  // 仅 exclude 模式
    }
}
```

**行为**：

- `has_outliers = false` 时不显示
- hover 可查看具体异常值列表
- 支持 dark/light 两套主题

### 5. 数据流

```
用户选择参数 → API 请求
       ↓
后端计算统计数据 (compute_histogram_stats, ...)
       ↓
后端调用 detect_outliers_iqr(data) → outlier_info
       ↓
API 返回 { ...原始统计, outlier_info, filtered_stats? }
       ↓
前端 store.outlierHandling 决定渲染模式
       ↓
裁剪模式 → 设置轴范围，不丢数据
排除模式 → 过滤数据点，用 filtered_stats
关闭模式 → 原样渲染
       ↓
OutlierHintBar 显示提示
```

### 6. 边界情况

| 情况 | 处理方式 |
|---|---|
| 没有异常值 | `has_outliers = false`，不显示提示条，图表正常渲染 |
| 全是异常值 | 保持原始数据，提示"数据分布异常，无法裁剪" |
| 数据量 < 4 个点 | IQR 不可靠，跳过检测，直接渲染原始数据 |
| 单图覆盖全局设置 | 组件本地 ref 覆盖 store 值，useChart 的 watchSources 包含模式变量 |
| 用户切换模式 | 触发 chart rebuild |
| 双轴散点图 | x 和 y 分别检测，提示条显示两轴各自的异常值信息 |

## 文件变更清单

### 新建文件

| 文件 | 用途 |
|---|---|
| `apps/analysis/services/statistics/outliers.py` | IQR 异常值检测工具函数 |
| `frontend/src/pages/analysis/components/OutlierHintBar.vue` | 异常值提示条组件 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `apps/analysis/services/data_services/histogram.py` | 调用 `detect_outliers_iqr`，返回 `outlier_info` + `filtered_cpk` |
| `apps/analysis/services/data_services/correlation.py` | 调用 `detect_outliers_iqr`（x/y 轴分别），返回 `x_outlier_info` + `y_outlier_info` |
| `apps/analysis/services/statistics/computations.py` | `compute_qqplot` 调用 `detect_outliers_iqr`，返回 `outlier_info` |
| `apps/analysis/services/data_services/serial_distribution.py` | 调用 `detect_outliers_iqr`，返回 `outlier_info` |
| `frontend/src/stores/analysis.ts` | 新增 `outlierHandling` 状态 |
| `frontend/src/pages/analysis/AnalysisPage.vue` | 顶部工具栏增加异常值处理下拉框 |
| `frontend/src/pages/analysis/components/HistogramChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/CorrelationToolsTab.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/QQPlotChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/SerialChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |

## 主题兼容

- `OutlierHintBar.vue` 需支持 dark/light 两套主题
- 顶部工具栏的下拉框使用 Element Plus 组件，自动适配主题
- 图表内的裁剪模式通过 ECharts axis min/max 实现，主题由 `useChart` 统一处理

## 测试计划

- 后端单元测试：`outliers.py` 的各种边界情况（空数据、全相同值、极端异常值、正常数据无异常值）
- 前端 E2E 测试：切换三种模式后图表正确响应，提示条正确显示
