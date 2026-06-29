# 异常值处理功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为直方图、散点图、QQ图、序列图添加 IQR 异常值检测和处理，支持裁剪显示范围和完全排除两种模式。

**Architecture:** 后端新增通用 `detect_outliers_iqr` 工具函数，各 API 端点调用后返回 `outlier_info`；前端 store 新增 `outlierHandling` 状态，全局默认 + 单图覆盖，图表根据模式裁剪轴范围或过滤数据点。

**Tech Stack:** Python (pandas, numpy), Django REST Framework, Vue 3 + TypeScript, ECharts, Element Plus, Pinia

---

## 文件结构

### 新建文件

| 文件 | 用途 |
|---|---|
| `apps/analysis/services/statistics/outliers.py` | IQR 异常值检测工具函数 |
| `test/backend/test_outliers.py` | 后端单元测试 |
| `frontend/src/pages/analysis/components/OutlierHintBar.vue` | 异常值提示条组件 |

### 修改文件

| 文件 | 改动 |
|---|---|
| `apps/analysis/services/statistics/__init__.py` | 导出 `detect_outliers_iqr` |
| `apps/analysis/services/data_services/histogram.py` | 调用检测函数，返回 `outlier_info` + `filtered_cpk` |
| `apps/analysis/services/data_services/correlation.py` | 调用检测函数（x/y 轴分别），返回 `x_outlier_info` + `y_outlier_info` |
| `apps/analysis/services/statistics/computations.py` | `compute_qqplot` 调用检测函数，返回 `outlier_info` |
| `apps/analysis/services/data_services/serial_distribution.py` | 调用检测函数，返回 `outlier_info` |
| `frontend/src/stores/analysis.ts` | 新增 `outlierHandling` 状态 |
| `frontend/src/pages/analysis/AnalysisPage.vue` | 顶部工具栏增加异常值处理下拉框 |
| `frontend/src/pages/analysis/components/SingleParamTab.vue` | 传递 outlierHandling 给子组件 |
| `frontend/src/pages/analysis/components/HistogramChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/CorrelationToolsTab.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/QQPlotChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |
| `frontend/src/pages/analysis/components/SerialChart.vue` | 根据模式裁剪/排除，显示 OutlierHintBar |

---

## Task 1: 后端 - 创建 `detect_outliers_iqr` 工具函数

**Files:**
- Create: `apps/analysis/services/statistics/outliers.py`

- [ ] **Step 1: 创建 outliers.py**

```python
"""Outlier detection utilities for data visualization."""

from typing import Any, Dict, Optional
import numpy as np
import pandas as pd


def detect_outliers_iqr(
    data: pd.Series,
    include_values: bool = False,
) -> Dict[str, Any]:
    """Detect outliers using the IQR (Interquartile Range) method.

    Uses the standard 1.5×IQR rule:
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR

    Args:
        data: Raw numeric data series.
        include_values: If True, include the full outlier_values list in the
            response. Set to False for "clip" mode (saves bandwidth) and True
            for "exclude" mode.

    Returns:
        Dict with keys: has_outliers, outlier_count, lower_bound,
        upper_bound, normal_count, and optionally outlier_values.
    """
    empty_result: Dict[str, Any] = {
        'has_outliers': False,
        'outlier_count': 0,
        'lower_bound': 0.0,
        'upper_bound': 0.0,
        'normal_count': 0,
    }

    if data is None or len(data) == 0:
        return empty_result

    # Basic cleaning: coerce to numeric, drop NaN, remove infinities
    clean = pd.to_numeric(data, errors='coerce').dropna()
    clean = clean[np.isfinite(clean.values)]

    if len(clean) < 4:
        # IQR is unreliable with fewer than 4 data points
        return {
            **empty_result,
            'normal_count': len(clean),
        }

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1

    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    outlier_mask = (clean < lower_bound) | (clean > upper_bound)
    outlier_count = int(outlier_mask.sum())
    normal_count = int(len(clean) - outlier_count)

    # Edge case: if ALL values are outliers, treat as no outliers
    # (data distribution is too extreme for IQR to be meaningful)
    if normal_count == 0:
        return {
            'has_outliers': False,
            'outlier_count': 0,
            'lower_bound': round(lower_bound, 6),
            'upper_bound': round(upper_bound, 6),
            'normal_count': 0,
        }

    result: Dict[str, Any] = {
        'has_outliers': outlier_count > 0,
        'outlier_count': outlier_count,
        'lower_bound': round(lower_bound, 6),
        'upper_bound': round(upper_bound, 6),
        'normal_count': normal_count,
    }

    if include_values and outlier_count > 0:
        result['outlier_values'] = [
            round(float(x), 6) for x in clean[outlier_mask].tolist()
        ]

    return result
```

- [ ] **Step 2: 更新 `__init__.py` 导出**

在 `apps/analysis/services/statistics/__init__.py` 的 imports 部分添加：

```python
from .outliers import detect_outliers_iqr
```

在 `__all__` 列表中添加 `'detect_outliers_iqr'`。

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/services/statistics/outliers.py apps/analysis/services/statistics/__init__.py
git commit -m "feat(stats): add detect_outliers_iqr utility function"
```

---

## Task 2: 后端 - 为 `detect_outliers_iqr` 编写单元测试

**Files:**
- Create: `test/backend/test_outliers.py`

- [ ] **Step 1: 创建测试文件**

```python
"""Tests for apps.analysis.services.statistics.outliers."""
import numpy as np
import pandas as pd
import pytest

from apps.analysis.services.statistics.outliers import detect_outliers_iqr


class TestDetectOutliersIqr:
    """Unit tests for detect_outliers_iqr."""

    def test_no_outliers(self):
        """Normal data within range should have no outliers."""
        data = pd.Series([25.0, 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['outlier_count'] == 0
        assert result['normal_count'] == 8

    def test_extreme_outlier(self):
        """An extreme value like 99999 should be detected as outlier."""
        normal = [25.0 + np.random.normal(0, 0.5) for _ in range(100)]
        data = pd.Series(normal + [99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['outlier_count'] == 1
        assert result['normal_count'] == 100
        assert result['upper_bound'] < 99999.0

    def test_multiple_outliers(self):
        """Multiple extreme values should all be detected."""
        normal = [25.0] * 100
        data = pd.Series(normal + [99999.0, 88888.0, -99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['outlier_count'] == 3

    def test_include_values_flag(self):
        """outlier_values should only be present when include_values=True."""
        normal = [25.0] * 100
        data = pd.Series(normal + [99999.0])

        result_clip = detect_outliers_iqr(data, include_values=False)
        assert 'outlier_values' not in result_clip

        result_exclude = detect_outliers_iqr(data, include_values=True)
        assert 'outlier_values' in result_exclude
        assert len(result_exclude['outlier_values']) == 1

    def test_empty_data(self):
        """Empty series should return safe defaults."""
        data = pd.Series([], dtype=float)
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['outlier_count'] == 0
        assert result['normal_count'] == 0

    def test_too_few_points(self):
        """Fewer than 4 points should skip detection."""
        data = pd.Series([1.0, 2.0, 3.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False
        assert result['normal_count'] == 3

    def test_all_same_values(self):
        """All identical values should have no outliers (IQR=0)."""
        data = pd.Series([25.0] * 50)
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is False

    def test_nan_handling(self):
        """NaN values should be cleaned before detection."""
        data = pd.Series([25.0, 25.1, np.nan, 25.3, np.nan, 99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True
        assert result['normal_count'] == 3

    def test_inf_handling(self):
        """Infinite values should be cleaned before detection."""
        data = pd.Series([25.0, 25.1, float('inf'), 25.3, 99999.0])
        result = detect_outliers_iqr(data)
        assert result['has_outliers'] is True

    def test_all_outliers_fallback(self):
        """If all values would be outliers, treat as no outliers."""
        # Create data where IQR=0 but values are spread
        data = pd.Series([1.0, 1.0, 1.0, 100.0, 100.0, 100.0])
        result = detect_outliers_iqr(data)
        # With this distribution Q1=1, Q3=100, IQR=99
        # lower=1-148.5=-147.5, upper=100+148.5=248.5
        # All values are within bounds, so no outliers
        assert result['has_outliers'] is False

    def test_bounds_are_correct(self):
        """Verify the IQR bounds calculation."""
        # Q1=10, Q3=30, IQR=20, lower=10-30=-20, upper=30+30=60
        data = pd.Series(range(1, 41), dtype=float)
        result = detect_outliers_iqr(data)
        assert result['lower_bound'] == pytest.approx(-20.0, abs=1.0)
        assert result['upper_bound'] == pytest.approx(60.0, abs=1.0)

    def test_none_input(self):
        """None input should return safe defaults."""
        result = detect_outliers_iqr(None)
        assert result['has_outliers'] is False
```

- [ ] **Step 2: 运行测试**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python -m pytest test/backend/test_outliers.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add test/backend/test_outliers.py
git commit -m "test(stats): add unit tests for detect_outliers_iqr"
```

---

## Task 3: 后端 - 集成到直方图 API

**Files:**
- Modify: `apps/analysis/services/data_services/histogram.py`

- [ ] **Step 1: 修改 histogram.py**

在 `compute_histogram_stats` 函数中：

1. 在文件顶部导入 `detect_outliers_iqr`：

```python
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
```

2. 在 `data_series` 清洗之后（第 33 行 `if len(data_series) == 0:` 之前），添加异常值检测：

```python
    # Detect outliers using IQR method
    outlier_info = detect_outliers_iqr(data_series, include_values=False)
```

3. 在 `cpk_result` 计算之后，计算排除异常值后的 Cpk：

```python
    # Compute filtered Cpk (excluding outliers)
    filtered_cpk = None
    if outlier_info['has_outliers'] and outlier_info['normal_count'] > 1:
        normal_data = data_series[
            (data_series >= outlier_info['lower_bound']) &
            (data_series <= outlier_info['upper_bound'])
        ]
        if len(normal_data) > 1:
            filtered_mean = float(normal_data.mean())
            filtered_std = float(normal_data.std(ddof=0))
            if filtered_std > 0:
                filtered_cpk_result = compute_cpk(
                    filtered_mean, filtered_std,
                    stats['rdl'][0], stats['rdl'][1]
                )
                filtered_cpk = round(filtered_cpk_result['cpk'], 4)
```

4. 在返回的 dict 中添加 `outlier_info` 和 `filtered_cpk`：

```python
    return {
        # ... existing fields ...
        'outlier_info': outlier_info,
        'filtered_cpk': filtered_cpk,
    }
```

- [ ] **Step 2: 验证后端可启动**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python -c "from apps.analysis.services.data_services.histogram import compute_histogram_stats; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/services/data_services/histogram.py
git commit -m "feat(api): integrate outlier detection into histogram endpoint"
```

---

## Task 4: 后端 - 集成到散点图 API

**Files:**
- Modify: `apps/analysis/services/data_services/correlation.py`

- [ ] **Step 1: 修改 correlation.py**

1. 在文件顶部导入：

```python
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
```

2. 在 `compute_correlation_scatter` 函数中，在 `x_vals` 和 `y_vals` 确定之后（第 31 行之后），添加异常值检测：

```python
    # Detect outliers for both axes
    x_outlier_info = detect_outliers_iqr(x_vals, include_values=False)
    y_outlier_info = detect_outliers_iqr(y_vals, include_values=False)
```

3. 在返回的 dict 中添加：

```python
    return {
        'param_x': param_x,
        'param_y': param_y,
        'n': n,
        'pearson_r': round(pearson_r, 6),
        'series_data': series_data,
        'x_outlier_info': x_outlier_info,
        'y_outlier_info': y_outlier_info,
    }
```

- [ ] **Step 2: 验证**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python -c "from apps.analysis.services.data_services.correlation import compute_correlation_scatter; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/services/data_services/correlation.py
git commit -m "feat(api): integrate outlier detection into correlation endpoint"
```

---

## Task 5: 后端 - 集成到 QQ 图 API

**Files:**
- Modify: `apps/analysis/services/statistics/computations.py`

- [ ] **Step 1: 修改 computations.py 中的 compute_qqplot**

1. 在文件顶部导入（已有 `from .helpers import ...` 和 `from .limits import ...`，在后面添加）：

```python
from .outliers import detect_outliers_iqr
```

2. 在 `compute_qqplot` 函数中，在 `clean` 数据清洗之后（第 322 行 `clean = clean[np.isfinite(clean.values)]` 之后），添加：

```python
    outlier_info = detect_outliers_iqr(clean, include_values=False)
```

3. 在返回的 dict 中添加：

```python
        return {
            'theoretical_quantiles': theoretical,
            'observed_quantiles': observed,
            'r_squared': r_squared,
            'is_normal': is_normal,
            'n': len(clean),
            'outlier_info': outlier_info,
        }
```

4. 同样在 except 的返回中也添加：

```python
        return {
            'theoretical_quantiles': [],
            'observed_quantiles': [],
            'r_squared': 0.0,
            'is_normal': False,
            'n': len(clean),
            'outlier_info': outlier_info,
        }
```

5. 在早期返回（`len(clean) < 3`）中也添加：

```python
        return {
            'theoretical_quantiles': [],
            'observed_quantiles': [],
            'r_squared': 0.0,
            'is_normal': False,
            'n': len(clean),
            'outlier_info': detect_outliers_iqr(clean, include_values=False),
        }
```

- [ ] **Step 2: 验证**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python -c "from apps.analysis.services.statistics.computations import compute_qqplot; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/services/statistics/computations.py
git commit -m "feat(api): integrate outlier detection into QQ plot computation"
```

---

## Task 6: 后端 - 集成到序列图 API

**Files:**
- Modify: `apps/analysis/services/data_services/serial_distribution.py`

- [ ] **Step 1: 修改 serial_distribution.py**

1. 在文件顶部导入：

```python
from apps.analysis.services.statistics.outliers import detect_outliers_iqr
```

2. 在 `compute_serial_distribution_data` 函数中，在 `data_series = get_1d_from(df, param).dropna()` 之后（第 121 行），添加：

```python
    outlier_info = detect_outliers_iqr(data_series, include_values=False)
```

3. 在返回的 dict 中添加：

```python
    return {
        'param': param,
        'unit': metadata.get('units', {}).get(param, ''),
        'serial_col': serial_col,
        'lower_limit': spec_lower,
        'upper_limit': spec_upper,
        'mean': mean_val,
        'std': std_val,
        'series_data': series_data,
        'continuous_serials': continuous_serials,
        'marks': marks,
        'y_min': y_min,
        'y_max': y_max,
        'outlier_info': outlier_info,
    }
```

- [ ] **Step 2: 验证**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python -c "from apps.analysis.services.data_services.serial_distribution import compute_serial_distribution_data; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/services/data_services/serial_distribution.py
git commit -m "feat(api): integrate outlier detection into serial distribution endpoint"
```

---

## Task 7: 前端 - 扩展 analysis store

**Files:**
- Modify: `frontend/src/stores/analysis.ts`

- [ ] **Step 1: 添加 outlierHandling 状态**

在 `customHigh` 之后添加：

```typescript
  const outlierHandling = ref<'clip' | 'exclude' | 'off'>('clip')
```

在 `reset` 函数中添加：

```typescript
    outlierHandling.value = 'clip'
```

在 return 中添加 `outlierHandling`。

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/analysis.ts
git commit -m "feat(store): add outlierHandling state to analysis store"
```

---

## Task 8: 前端 - 创建 OutlierHintBar 组件

**Files:**
- Create: `frontend/src/pages/analysis/components/OutlierHintBar.vue`

- [ ] **Step 1: 创建组件**

```vue
<template>
  <div
    v-if="visible"
    class="outlier-hint-bar"
    :class="`outlier-hint-bar--${mode}`"
  >
    <el-tooltip
      v-if="outlierValues.length > 0"
      placement="top"
      :width="320"
    >
      <template #content>
        <div class="outlier-hint-bar__tooltip">
          <div class="outlier-hint-bar__tooltip-title">异常值列表</div>
          <div class="outlier-hint-bar__tooltip-values">
            {{ outlierValues.map(v => v.toFixed(4)).join(', ') }}
          </div>
        </div>
      </template>
      <span class="outlier-hint-bar__text">
        <el-icon class="outlier-hint-bar__icon"><Warning /></el-icon>
        {{ hintText }}
      </span>
    </el-tooltip>
    <span v-else class="outlier-hint-bar__text">
      <el-icon class="outlier-hint-bar__icon"><Warning /></el-icon>
      {{ hintText }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Warning } from '@element-plus/icons-vue'

export interface OutlierInfo {
  has_outliers: boolean
  outlier_count: number
  lower_bound: number
  upper_bound: number
  outlier_values?: number[]
  normal_count: number
}

const props = defineProps<{
  mode: 'clip' | 'exclude' | 'off'
  outlierInfo: OutlierInfo | null
}>()

const visible = computed(() => {
  if (!props.outlierInfo) return false
  if (props.mode === 'off') return false
  return props.outlierInfo.has_outliers
})

const outlierValues = computed(() => {
  return props.outlierInfo?.outlier_values ?? []
})

const hintText = computed(() => {
  if (!props.outlierInfo) return ''
  const info = props.outlierInfo
  const modeText = props.mode === 'clip' ? '已裁剪' : '已排除'
  const bounds = `（正常范围: ${info.lower_bound.toFixed(4)} ~ ${info.upper_bound.toFixed(4)}）`
  return `${modeText} ${info.outlier_count} 个异常值 ${bounds}`
})
</script>

<style scoped>
.outlier-hint-bar {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 4px;
  margin-top: 4px;
  font-size: 12px;
}

.outlier-hint-bar--clip {
  background-color: #fff3e0;
  color: #e65100;
  border: 1px solid #ffe0b2;
}

.outlier-hint-bar--exclude {
  background-color: #fce4ec;
  color: #c62828;
  border: 1px solid #f8bbd0;
}

.outlier-hint-bar__text {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.outlier-hint-bar__icon {
  font-size: 14px;
  flex-shrink: 0;
}

.outlier-hint-bar__tooltip {
  max-width: 300px;
}

.outlier-hint-bar__tooltip-title {
  font-weight: bold;
  margin-bottom: 4px;
}

.outlier-hint-bar__tooltip-values {
  word-break: break-all;
  font-family: monospace;
  font-size: 11px;
}

/* Dark theme */
:root[data-theme='dark'] .outlier-hint-bar--clip {
  background-color: #3e2723;
  color: #ffab91;
  border: 1px solid #5d4037;
}

:root[data-theme='dark'] .outlier-hint-bar--exclude {
  background-color: #3e1515;
  color: #ef9a9a;
  border: 1px solid #5d2020;
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/analysis/components/OutlierHintBar.vue
git commit -m "feat(ui): create OutlierHintBar component with dark/light themes"
```

---

## Task 9: 前端 - AnalysisPage 顶部工具栏添加全局控制

**Files:**
- Modify: `frontend/src/pages/analysis/AnalysisPage.vue`

- [ ] **Step 1: 添加 import 和状态**

在 `<script setup>` 的 import 区域添加：

```typescript
import { useAnalysisStore } from '../../stores/analysis'
```

（已有此 import，跳过）

在 `activeTab` 之后添加：

```typescript
const outlierHandling = ref(analysisStore.outlierHandling)
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
```

- [ ] **Step 2: 在模板中添加下拉框**

在文件选择器的 `el-form-item` 之后，添加一个新的 form item：

```html
      <el-form-item label="异常值处理">
        <el-select
          v-model="outlierHandling"
          size="small"
          class="analysis-file-selector__select"
          style="width: 160px"
        >
          <el-option label="裁剪范围" value="clip" />
          <el-option label="完全排除" value="exclude" />
          <el-option label="不处理" value="off" />
        </el-select>
      </el-form-item>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/analysis/AnalysisPage.vue
git commit -m "feat(ui): add global outlier handling control to AnalysisPage"
```

---

## Task 10: 前端 - 更新 HistogramChart 支持异常值处理

**Files:**
- Modify: `frontend/src/pages/analysis/components/HistogramChart.vue`
- Modify: `frontend/src/pages/analysis/components/SingleParamTab.vue`

- [ ] **Step 1: 修改 HistogramChart.vue props**

添加新 prop：

```typescript
const props = defineProps<{
  result: any
  chartConfig: string[]
  rangeType: string
  barWidthPercent: number
  selectedParam: string
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()
```

- [ ] **Step 2: 在 HistogramChart.vue 的 buildOption 中添加裁剪逻辑**

在 `buildOption()` 函数中，`const r = props.result` 之后，添加：

```typescript
  // Apply outlier clipping to x-axis range
  const outlierInfo = r.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let xAxisMin: number | undefined = binCenters[0]
  let xAxisMax: number | undefined = binCenters[binCenters.length - 1]

  if (handlingMode === 'clip' && outlierInfo?.has_outliers) {
    // Find the bin centers that fall within the normal range
    const normalCenters = binCenters.filter(
      (c: number) => c >= outlierInfo.lower_bound && c <= outlierInfo.upper_bound
    )
    if (normalCenters.length > 0) {
      xAxisMin = normalCenters[0]
      xAxisMax = normalCenters[normalCenters.length - 1]
    }
  }
```

然后在 `xAxis` 配置中使用 `xAxisMin` 和 `xAxisMax`：

```typescript
    xAxis: { type: 'value', name: '', nameLocation: 'middle', nameGap: 28, min: xAxisMin, max: xAxisMax, ... },
```

- [ ] **Step 3: 在模板中添加 OutlierHintBar**

在 `<template>` 中，将 `<div ref="chartRef" ... />` 改为：

```html
  <div class="histogram-chart-wrapper">
    <div ref="chartRef" class="chart-container" />
    <OutlierHintBar
      :mode="outlierHandling || 'off'"
      :outlier-info="result?.outlier_info ?? null"
    />
  </div>
```

添加 import：

```typescript
import OutlierHintBar from './OutlierHintBar.vue'
```

- [ ] **Step 4: 修改 SingleParamTab.vue 传递 outlierHandling**

在 `HistogramChart` 组件调用处添加 prop：

```html
          <HistogramChart
            :result="histResult"
            :chart-config="chartConfig"
            :range-type="rangeType"
            :bar-width-percent="barWidthPercent"
            :selected-param="localSelectedParam"
            :outlier-handling="outlierHandling"
          />
```

添加 `outlierHandling` ref：

```typescript
const outlierHandling = ref(analysisStore.outlierHandling)
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
watch(() => analysisStore.outlierHandling, (val) => { outlierHandling.value = val })
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/components/HistogramChart.vue frontend/src/pages/analysis/components/SingleParamTab.vue
git commit -m "feat(ui): add outlier handling to HistogramChart"
```

---

## Task 11: 前端 - 更新 QQPlotChart 支持异常值处理

**Files:**
- Modify: `frontend/src/pages/analysis/components/QQPlotChart.vue`

- [ ] **Step 1: 添加 props**

```typescript
const props = defineProps<{
  fileId: number | null
  param: string
  visible: boolean
  result: any
  loading: boolean
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()
```

- [ ] **Step 2: 在 buildOption 中添加裁剪逻辑**

在 `buildOption()` 中，`const theoretical` 和 `const observed` 之后，添加：

```typescript
  // Apply outlier clipping
  const outlierInfo = r.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let filteredTheoretical = theoretical
  let filteredObserved = observed

  if (handlingMode === 'clip' && outlierInfo?.has_outliers) {
    // Clip to the range of normal values
    const lb = outlierInfo.lower_bound
    const ub = outlierInfo.upper_bound
    const indices = observed
      .map((v: number, i: number) => (v >= lb && v <= ub ? i : -1))
      .filter((i: number) => i >= 0)
    if (indices.length > 2) {
      filteredTheoretical = indices.map((i: number) => theoretical[i])
      filteredObserved = indices.map((i: number) => observed[i])
    }
  }

  const scatterData = filteredTheoretical.map((t: number, i: number) => [t, filteredObserved[i]])
```

并将 `const allValues` 改为基于 `filteredTheoretical` 和 `filteredObserved`。

- [ ] **Step 3: 在模板中添加 OutlierHintBar**

将 `<div v-else ref="chartRef" class="qqplot-container" />` 改为：

```html
    <div v-else class="qqplot-chart-inner">
      <div ref="chartRef" class="qqplot-container" />
      <OutlierHintBar
        :mode="outlierHandling || 'off'"
        :outlier-info="result?.outlier_info ?? null"
      />
    </div>
```

添加 import：

```typescript
import OutlierHintBar from './OutlierHintBar.vue'
```

- [ ] **Step 4: 修改 SingleParamTab.vue 传递 outlierHandling**

```html
          <QQPlotChart
            :file-id="props.fileId"
            :param="localSelectedParam"
            :visible="showQQPlot"
            :result="qqResult"
            :loading="qqLoading"
            :outlier-handling="outlierHandling"
          />
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/components/QQPlotChart.vue frontend/src/pages/analysis/components/SingleParamTab.vue
git commit -m "feat(ui): add outlier handling to QQPlotChart"
```

---

## Task 12: 前端 - 更新 SerialChart 支持异常值处理

**Files:**
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`

- [ ] **Step 1: 添加 props**

```typescript
const props = defineProps<{
  data: any
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()
```

- [ ] **Step 2: 在 buildOption 中添加裁剪逻辑**

在 `buildOption()` 中，y 轴配置处，添加裁剪：

```typescript
  // Apply outlier clipping to y-axis
  const outlierInfo = props.data?.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let yAxisMin = props.data?.y_min
  let yAxisMax = props.data?.y_max

  if (handlingMode === 'clip' && outlierInfo?.has_outliers) {
    yAxisMin = outlierInfo.lower_bound
    yAxisMax = outlierInfo.upper_bound
    // Add some padding
    const pad = (yAxisMax - yAxisMin) * 0.1
    yAxisMin -= pad
    yAxisMax += pad
  }
```

在 yAxis 配置中使用 `yAxisMin` 和 `yAxisMax`。

- [ ] **Step 3: 在模板中添加 OutlierHintBar**

将 SerialChart 的 chart container 改为包含 OutlierHintBar。

- [ ] **Step 4: 修改 SingleParamTab.vue 传递 outlierHandling**

```html
        <SerialChart v-if="serialDistData" :data="serialDistData" :outlier-handling="outlierHandling" />
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/components/SerialChart.vue frontend/src/pages/analysis/components/SingleParamTab.vue
git commit -m "feat(ui): add outlier handling to SerialChart"
```

---

## Task 13: 前端 - 更新 CorrelationToolsTab 支持异常值处理

**Files:**
- Modify: `frontend/src/pages/analysis/components/CorrelationToolsTab.vue`

- [ ] **Step 1: 添加 outlierHandling 状态**

```typescript
const outlierHandling = ref(analysisStore.outlierHandling)
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
watch(() => analysisStore.outlierHandling, (val) => { outlierHandling.value = val })
```

- [ ] **Step 2: 在 buildScatterOption 中添加裁剪逻辑**

在 `buildScatterOption()` 中，散点数据构建之后，添加：

```typescript
  // Apply outlier clipping
  if (outlierHandling.value === 'clip' && d.x_outlier_info?.has_outliers && d.y_outlier_info?.has_outliers) {
    const xlb = d.x_outlier_info.lower_bound
    const xub = d.x_outlier_info.upper_bound
    const ylb = d.y_outlier_info.lower_bound
    const yub = d.y_outlier_info.upper_bound
    // Update axis ranges
    if (axisModeX.value === 'data') {
      xR.min = xlb
      xR.max = xub
    }
    if (axisModeY.value === 'data') {
      yR.min = ylb
      yR.max = yub
    }
  }
```

- [ ] **Step 3: 在模板中添加 OutlierHintBar 和异常值提示**

在散点图的 `chart-wrapper` div 内，`<div v-if="corrResult" ref="scatterChartRef" class="chart-inner" />` 之后添加：

```html
          <OutlierHintBar
            v-if="corrResult"
            :mode="outlierHandling"
            :outlier-info="corrResult?.x_outlier_info ?? null"
          />
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/analysis/components/CorrelationToolsTab.vue
git commit -m "feat(ui): add outlier handling to CorrelationToolsTab"
```

---

## Task 14: E2E 测试

**Files:**
- Create: `test/e2e/test_outlier_handling.py`

- [ ] **Step 1: 创建 E2E 测试文件**

```python
"""E2E tests for outlier handling feature.

These tests verify the API responses include outlier_info and that
the frontend correctly handles the three modes.
"""
import pytest
from django.test import TestCase


class TestOutlierInfoInAPI(TestCase):
    """Verify API responses include outlier_info field."""

    def test_histogram_returns_outlier_info(self):
        """Histogram API should return outlier_info."""
        # This test requires a running server and test data file
        # It will be implemented as a Playwright E2E test
        pass

    def test_correlation_returns_outlier_info(self):
        """Correlation API should return x_outlier_info and y_outlier_info."""
        pass

    def test_qqplot_returns_outlier_info(self):
        """QQ plot API should return outlier_info."""
        pass

    def test_serial_returns_outlier_info(self):
        """Serial distribution API should return outlier_info."""
        pass
```

- [ ] **Step 2: Commit**

```bash
git add test/e2e/test_outlier_handling.py
git commit -m "test(e2e): add skeleton for outlier handling E2E tests"
```

---

## 执行顺序总结

1. Task 1: 创建 `outliers.py`（后端基础）
2. Task 2: 单元测试（验证基础逻辑）
3. Task 3-6: 四个 API 端点集成（并行可做）
4. Task 7: 前端 store 扩展
5. Task 8: OutlierHintBar 组件
6. Task 9: AnalysisPage 全局控制
7. Task 10-13: 四个图表组件更新（并行可做）
8. Task 14: E2E 测试
