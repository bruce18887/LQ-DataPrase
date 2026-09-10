# 多文件分析 Tab 增强设计

> 日期：2026-09-10
> 方案：C（混合方案）—— 布局升级 + 统计对比增强 + 图表类型扩展 + 阶段智能标签
> 状态：待审核

## 1. 背景与动机

多文件分析 tab 当前仅提供单张柱状图 + 基础统计表（Mean/STD/N/Yield），相比单文件 tab 的完整能力（CPK/箱线图/QQ 图/KDE/ChartDock）差距明显。典型使用场景是**同产品多阶段对比**（FT1→QA1→QA2→RT1→RT2），用户需要快速识别阶段间的均值漂移、分布变化和过程能力变化。

### 当前能力边界

| 已有 | 相比单文件 tab 缺少 |
|------|-------------------|
| 多文件柱状图 + per-file 规格限线 | CPK/CP 过程能力指标 |
| 正态分布曲线叠加 | KDE 非参数密度曲线 |
| 范围类型切换（RDL/DR/S3/S4/S6） | 箱线图分布对比 |
| 统计表（Mean/STD/N/Yield） | Median/Min/Max + 阶段间 Delta |
| 自定义图例名 | 阶段标识智能提取 |
| 5 个数据筛选开关 | — |
| 自动差异标签提取 | — |

## 2. 设计目标

1. **统计对比增强**：统计表扩展到 CPK/CP/Median/Min/Max，CPK 按质量等级着色
2. **图表类型扩展**：新增 KDE 曲线叠加 + 多文件箱线图
3. **布局升级**：从手工 el-row/el-col 迁移到 AnalysisTabLayout（与其余 3 个 tab 结构统一）
4. **阶段智能标签**：从文件名自动提取阶段标识（FT1/QA1/RT1 等）

## 3. 架构与布局

### 3.1 MultiFileTab.vue 迁移到 AnalysisTabLayout

```
AnalysisTabLayout
├── #toolbar
│   ├── Line 1: AnalysisFilePicker (multiple) + 图表类型勾选
│   │   └── el-checkbox "显示箱线图" | el-checkbox "显示KDE"
│   └── Line 2: DataFilterSection (variant="bar", scope="multi")
├── #left-panel (span 6)
│   ├── 自定义图例名卡（保留现有逻辑）
│   ├── ChartConfigPanel (variant="multi-file")
│   ├── 范围类型卡（保留现有 el-select）
│   └── 统计对比表（enriched，见 §4）
└── #right-panel (span 18)
    ├── 顶部: ParamSelector + 共有项提示 + CircularProgress
    ├── 主图表: MultiFileChart（柱状图 + 可选 KDE 叠加）
    └── 可折叠箱线图卡（"显示箱线图" checkbox 控制显隐）
```

### 3.2 关键改变

- toolbar 第一行右侧新增图表类型勾选（与单文件 tab 的「显示序列分布/显示QQ图/显示箱线图」对齐）
- 右面板从单张图表扩展为「主图表 + 可折叠箱线图」
- 左面板结构不变，统计表内容增强

### 3.3 Store 扩展

`createMultiState`（`analysisTabs.ts`）新增字段：

```typescript
showBoxPlot: ref(false),    // 箱线图显示开关
showKde: ref(false),        // KDE 曲线显示开关
```

## 4. 统计对比增强

### 4.1 后端改动（multi_lot.py）

在 `compute_multi_lot_distribution` 的 per-file 循环中追加字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| `cpk` | `compute_cpk(mean, std, lower_limit, upper_limit)` | 实际能力指数 |
| `cp` | 同上 | 潜在能力指数（单边规格时为 null） |
| `cpk_level` | `compute_cpk` 返回 | A/B/C/D 质量等级 |
| `cpk_color` | `compute_cpk` 返回 | 绿/橙/深橙/红 hex |
| `median` | `float(series.median())` | 中位数 |

每个文件使用自己的 `lower_limit/upper_limit` 计算 CPK（与 `trends.py` 同一口径）。

### 4.2 前端统计表

el-table 从 4 列扩展到 9 列，支持横向滚动：

| 文件/阶段 | Mean | STD | Median | CPK | N | Yield% | Min | Max |

- CPK 列按 `cpk_color` 着色（绿≥1.67/橙≥1.33/深橙≥1.0/红<1.0），与单文件 tab 的 CPK 显示一致
- 表底部可选 **Δ 行**：前端基于相邻文件（按 fileIds 选择顺序）的 mean/cpk 差值本地计算
  - 格式：`Δmean: +0.023  Δcpk: −0.15`
  - 仅当文件数 ≥ 2 时显示

## 5. 图表类型扩展

### 5.1 KDE 曲线叠加

**后端**：在 `compute_multi_lot_distribution` 中为每个 lot 调用现有的 `compute_kde_curve`（来自 `histogram.py`），追加 `kde_curve` 字段到每个 `lot_data` 项。

**前端**（MultiFileChart.vue）：
- `chartConfig` 含 `'kde'` 时，在每个文件的柱状图上叠加该文件的 KDE 曲线
- 颜色使用与该文件柱状图相同的 `lotThemeColor`，实线（区别于正态分布的 dotted）
- Y 轴复用正态分布的右侧概率密度轴（yAxisIndex: 1）
- 图例追加 `{dn} KDE`

**ChartConfigPanel**（variant="multi-file"）：
- 新增 `KDE 曲线` checkbox（与 `normal` 正态分布并列）

### 5.2 多文件箱线图

新建 `MultiFileBoxPlot.vue`：

**后端**：`multi_lot` 响应中每个 `lot_data[i]` 追加：

| 字段 | 来源 | 说明 |
|------|------|------|
| `q1` | `float(series.quantile(0.25))` | 第一四分位数 |
| `q3` | `float(series.quantile(0.75))` | 第三四分位数 |
| `median` | 已在 §4 追加 | 中位数 |
| `min_v` | 已有 | 最小值 |
| `max_v` | 已有 | 最大值 |

不单独计算 whisker/outlier——箱线图使用 min/max 作为须端（与单文件箱线图的简化模式一致）。

**前端**：
- ECharts 水平箱线图（`type: 'boxplot'`）
- 每个文件一条箱线，颜色与柱状图一致
- X 轴与柱状图共享范围（方便对比分布形态）
- 仅当 toolbar 的「显示箱线图」开启时渲染
- 折叠/展开不触发新的 API 请求（数据随 multi_lot 响应一起返回）

### 5.3 不做的事

- **不引入 ChartDock**：多文件场景用「主图表 + 折叠箱线」够用，不需要拖拽拼格
- **不加 QQ 图**：多文件 QQ 图叠加可读性差，如需单文件 QQ 请在单文件 tab 查看
- **不实现批量参数扫览**：后续迭代
- **不实现 Pp/Ppk**：后端文档明确说明当前只有 overall sigma，无法正确区分组内/组间波动

## 6. 阶段智能标签

### 6.1 改进 `autoExtractLabel`（前端纯函数）

在现有公共前后缀裁剪逻辑前增加预处理：

1. **时间戳剥离**：文件名末尾的 `_YYYYMMDD_HHMMSS` 或 `_YYYYMMDD_HHMMSS.csv` 模式在裁剪前先剥离
2. **阶段关键字识别**：在提取差异段后，尝试匹配常见阶段模式（正则 `(?:FT|QA|RT|CP|UIS|EQC)\d*`），如果所有文件都匹配到阶段标识，则用阶段名作为默认图例
3. **回退不变**：如果阶段识别失败，仍用当前的公共前后缀裁剪逻辑

### 6.2 示例

输入文件名：
```
DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv
DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_RT1_20260421_035306.csv
DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_RT2_20260421_054945.csv
```

当前提取结果（差异段含时间戳噪音）→ 改进后：`FT`、`RT1`、`RT2`

## 7. API 响应变更汇总

### POST /analysis/multi_lot/ 响应（lot_data 字段）

现有字段不变，每个 `lot_data[i]` 追加：

```json
{
  "cpk": 1.45,
  "cp": 1.52,
  "cpk_level": "B",
  "cpk_color": "#FF8C00",
  "median": 2.345,
  "q1": 2.100,
  "q3": 2.590,
  "kde_curve": [[x1, y1], [x2, y2], ...]
}
```

`kde_curve` 仅当 chartConfig 需要 KDE 时后端才计算——通过请求参数 `include_kde: true` 控制，避免无用的计算开销。

## 8. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `apps/analysis/services/data_services/multi_lot.py` | 修改 | lot_data 追加 cpk/cp/median/q1/q3/kde_curve |
| `frontend/.../MultiFileTab.vue` | 重构 | 迁移到 AnalysisTabLayout + toolbar 图表勾选 + 箱线图折叠区 |
| `frontend/.../MultiFileChart.vue` | 修改 | 新增 KDE 曲线渲染 |
| `frontend/.../MultiFileBoxPlot.vue` | 新建 | 多文件水平箱线图组件 |
| `frontend/.../ChartConfigPanel.vue` | 修改 | variant="multi-file" 新增 KDE 选项 |
| `frontend/.../useMultiFile.ts` | 微调 | 类型定义扩展新字段 |
| `frontend/.../analysisTabs.ts` | 微调 | createMultiState 新增 showBoxPlot/showKde |
| `frontend/e2e/analysis/multi-file.spec.ts` | 扩展 | 新增 CPK 列可见、箱线图显隐、KDE 切换等用例 |
| `apps/analysis/tests_param_guards.py` | 扩展 | MultiFileAnalysisTests 追加 CPK/median 测试 |

## 9. 测试计划

### 后端

- `tests_param_guards.py::MultiFileAnalysisTests`：
  - 新增 CPK/CP 字段验证（已知均值/标准差/规格限 → 期望 CPK）
  - 新增 median 字段验证
  - 新增 q1/q3 字段验证
  - KDE 曲线字段验证（include_kde=true 时有数据，false 时为 null）

### E2E

- 统计对比表列数断言（≥ 7 列可见）
- CPK 列着色断言（检查 background-color 或 color 非默认）
- 箱线图 checkbox 显隐断言（勾选后 boxplot 区域可见，取消后隐藏）
- KDE checkbox 断言（勾选后 KDE 曲线系列出现在图表中）
- 阶段智能标签断言（选择已知命名模式的文件后，图例名显示为阶段标识）

## 10. 不做的事（显式排除）

- 不引入 ChartDock 停靠系统
- 不增加多文件 QQ 图
- 不实现批量参数扫览（后续迭代候选）
- 不实现 Pp/Ppk（当前整体 sigma 无法正确计算）
- 不改变后端 API 端点路径或新增端点
- 不改变现有的数据筛选开关行为
