# Multi-File Analysis Chart Improvement Design

**Date:** 2026-06-10
**Status:** Draft

## Problem Statement

The multi-file analysis chart has several visualization issues that make it difficult to compare distributions across files:

1. **X-axis range too wide** — raw data min/max is used (e.g., 0.04~999.36) while data clusters in a narrow range (170~180), causing bars to appear as thin lines
2. **Legend names too long** — full filenames with timestamps and serial numbers clutter the chart bottom
3. **Limit line labels too verbose** — markLine labels show full filename + "USL", overlapping with chart elements
4. **X-axis labels have unnecessary decimals** — `50.0000` instead of `50`
5. **X-axis labels too dense** — 24 split intervals cause label overlap
6. **Missing Range Type selector** — single-file analysis has RDL/DR/S3/S4/S6/CL options, multi-file has none

## Solution Design

### 1. Range Type Support

**Backend: `apps/analysis/services/data_services.py` — `compute_multi_lot_distribution()`**

Add parameters: `range_type: str = 'S4'`, `custom_low: float | None = None`, `custom_high: float | None = None`

Range computation logic (after computing `global_mean`, `global_std`, `combined`):

```python
def _resolve_multi_range(range_type, combined, global_mean, global_std, all_metadata, param):
    """Resolve bin range for multi-file chart."""
    if range_type == 'CL' and custom_low is not None and custom_high is not None:
        return float(custom_low), float(custom_high)

    if range_type == 'DR':
        return float(combined.min()), float(combined.max())

    # RDL: use spec limits from metadata (union across files)
    if range_type == 'RDL':
        lowers, uppers = [], []
        for meta in all_metadata:
            lo, hi = _resolve_param_limits(None, meta, param, combined)
            if lo is not None: lowers.append(lo)
            if hi is not None: uppers.append(hi)
        if lowers or uppers:
            return (min(lowers) if lowers else float(combined.min())),
                   (max(uppers) if uppers else float(combined.max()))

    # S3/S4/S6: mean ± N*std
    n = int(range_type[1])  # 3, 4, or 6
    return global_mean - n * global_std, global_mean + n * global_std
```

Fallback chain: selected range → RDL → DR (raw min/max).

Bin edges: use `bin_min`/`bin_max` from resolved range instead of `combined.min()`/`max()`.

**Backend: `apps/analysis/views.py` — `multi_lot()` action**

Pass `range_type` from `request.data` to `compute_multi_lot_distribution`.

**Frontend: `stores/analysis.ts`**

Add `multiRangeType: ref('S4')` to the store (with persistence).

**Frontend: `MultiFileTab.vue`**

Add Range Type selector in left panel (between ChartConfigPanel and stats table):
```html
<el-select v-model="rangeType" size="small" style="width: 100%">
  <el-option label="Spec Limits (RDL)" value="RDL" />
  <el-option label="Data Range (DR)" value="DR" />
  <el-option label="3 Sigma (S3)" value="S3" />
  <el-option label="4 Sigma (S4)" value="S4" />
  <el-option label="6 Sigma (S6)" value="S6" />
</el-select>
```

Pass `rangeType` to `loadDistribution()`.

**Frontend: `composables/useMultiFile.ts`**

Add `rangeType` parameter to `loadDistribution()` request body.

### 2. Auto-Extract Legend Labels

**Frontend: `MultiFileTab.vue`**

New utility function:

```typescript
function autoExtractLabel(filenames: string[]): string[] {
  if (filenames.length <= 1) return filenames

  // Find common prefix
  let prefix = filenames[0]
  for (let i = 1; i < filenames.length; i++) {
    while (!filenames[i].startsWith(prefix)) {
      prefix = prefix.slice(0, -1)
    }
  }

  // Find common suffix
  let suffix = filenames[0]
  for (let i = 1; i < filenames.length; i++) {
    while (!filenames[i].endsWith(suffix)) {
      suffix = suffix.slice(1)
    }
  }

  return filenames.map(f => {
    let mid = f.slice(prefix.length)
    if (suffix.length) mid = mid.slice(0, -suffix.length)
    // Trim leading/trailing separators
    mid = mid.replace(/^[_\-. ]+|[_\-. ]+$/g, '')
    // Truncate at meaningful separator if too long
    if (mid.length > 30) {
      const sep = mid.search(/[_\-].{8,}/)
      if (sep > 0) mid = mid.slice(0, sep)
    }
    return mid || f  // fallback to full name if empty
  })
}
```

Integration in `resolvedNames`:
```typescript
const resolvedNames = computed(() => {
  const map: Record<number, string> = {}
  const customExists = selectedFileObjs.value.some(f => (fileNames.value[f.id] || '').trim())
  if (!customExists) {
    // Auto-extract: use differentiating parts as defaults
    const names = selectedFileObjs.value.map(f => f.filename)
    const labels = autoExtractLabel(names)
    selectedFileObjs.value.forEach((f, i) => { map[f.id] = labels[i] })
  } else {
    for (const f of selectedFileObjs.value) {
      const custom = (fileNames.value[f.id] || '').trim()
      map[f.id] = custom || f.filename
    }
  }
  return map
})
```

### 3. Simplify Limit Line Labels

**Frontend: `MultiFileChart.vue` — `buildOption()`**

Change markLine label formatter:
```typescript
// Before: `${displayName(lot)} USL`
// After:
const limitValue = lot.upper_limit.toFixed(2)
label: {
  show: true,
  formatter: lots.length > 1 ? `USL=${limitValue}` : `${displayName(lot)} USL=${limitValue}`,
  position: 'end',
  color: lot.color,
  fontSize: 10,
}
```

For LSL:
```typescript
formatter: lots.length > 1 ? `LSL=${lot.lower_limit.toFixed(2)}` : `${displayName(lot)} LSL=${lot.lower_limit.toFixed(2)}`
```

Merge identical limit lines: group lots by their limit values, draw one line per unique value.

Implementation detail — merge logic in `buildOption()`:
```typescript
// Collect all unique limit values across files
const limitMap = new Map<number, { type: 'USL'|'LSL', lots: any[] }>()
for (const lot of lots) {
  if (lot.upper_limit != null) {
    const key = lot.upper_limit
    const entry = limitMap.get(key) || { type: 'USL', lots: [] }
    entry.lots.push(lot)
    limitMap.set(key, entry)
  }
  // Same for lower_limit...
}
// One markLine per unique value
for (const [value, { type, lots: limitLots }] of limitMap) {
  mk.push({
    xAxis: value,
    lineStyle: { color: limitLots[0].color, width: 2, type: 'dashed' },
    label: { show: true, formatter: `${type}=${value.toFixed(2)}`, position: 'end', color: limitLots[0].color, fontSize: 10 },
  })
}
```

### 4. X-Axis Label Smart Formatting

**Frontend: `MultiFileChart.vue` — `buildOption()` xAxis**

```typescript
axisLabel: {
  rotate: 0,           // Remove 45° rotation (with smart range, labels fit horizontally)
  show: true,
  interval: 'auto',    // Let ECharts decide which labels to show
  fontSize: 10,
  formatter: (v: number) => {
    if (Number.isInteger(v)) return v.toString()
    // Dynamic decimal places: max 2, trim trailing zeros
    const s = v.toFixed(2)
    return s.replace(/\.?0+$/, '')
  },
  color: tc,
},
splitNumber: 10,       // Reduced from 24
```

Note: With Range Type defaulting to S4, the X-axis range will be much narrower (e.g., 160~194 instead of 0~1000), so horizontal labels fit naturally. If the user selects DR (full data range), ECharts' `interval: 'auto'` will skip labels to prevent overlap.

### 5. Grid Layout Adjustment

Adjust `grid` to give more room for rotated labels if needed:
```typescript
grid: { top: 50, bottom: 50, left: 55, right: 40 }
```

## Files to Modify

| File | Changes |
|------|---------|
| `apps/analysis/services/data_services.py` | Add range_type param to `compute_multi_lot_distribution`, add `_resolve_multi_range` |
| `apps/analysis/views.py` | Pass range_type from request to service |
| `frontend/src/stores/analysis.ts` | Add `multiRangeType` state |
| `frontend/src/pages/analysis/components/MultiFileTab.vue` | Add Range Type selector, add `autoExtractLabel` |
| `frontend/src/pages/analysis/components/MultiFileChart.vue` | Fix limit labels, X-axis formatting, grid |
| `frontend/src/pages/analysis/composables/useMultiFile.ts` | Pass range_type in API request |

## Testing

- E2E: Select 2 FT1 files from `media/data/admin/batch/BE01-2605260001`, verify X-axis range is data-focused, legend shows short names, limit labels show values only
- Visual: Compare before/after screenshots for both light and dark themes
- Edge case: Files with no spec limits (RDL fallback to DR)
- Edge case: Files with identical filenames (autoExtractLabel fallback)

## 2026-06-11 Enhancement: Per-File Limit Lines, Limit-Based X-Axis, and Normal Distribution Curves

### New Requirements

1. **Per-file limit lines** — Each file displays its own limit lines (even if values are identical), with labels showing file name, limit value, and fail count
2. **Limit-based X-axis** — X-axis range is determined by limit values: 20 bins inside the limit range (min LSL to max USL), 4 bins outside (2 on each side), total 24 bins
3. **Normal distribution curves** — Each file has its own normal distribution curve, controlled by a checkbox, using an independent probability density Y-axis

### Implementation Details

#### 1. Backend Changes (`apps/analysis/services/data_services.py`)

**Modified function: `compute_multi_lot_distribution()`**

```python
# New logic: collect all file limits first
global_lsl = None  # Minimum LSL across all files
global_usl = None  # Maximum USL across all files

for fid, ds in datasets.items():
    lower_limit, upper_limit = _resolve_param_limits(...)
    if lower_limit is not None:
        global_lsl = min(global_lsl, lower_limit) if global_lsl is not None else lower_limit
    if upper_limit is not None:
        global_usl = max(global_usl, upper_limit) if global_usl is not None else upper_limit

# Limit-based X-axis: 20 inside + 4 outside
if global_lsl is not None and global_usl is not None and global_lsl < global_usl:
    limit_range = global_usl - global_lsl
    bin_width_inside = limit_range / 20
    bin_min = global_lsl - 2 * bin_width_inside  # 2 bins outside left
    bin_max = global_usl + 2 * bin_width_inside  # 2 bins outside right
    bin_count = 24
else:
    # Fallback to range_type-based resolution
    bin_count = 25

# Return values include global_lsl and global_usl
return {
    ...
    'global_lsl': round(float(global_lsl), 6) if global_lsl is not None else None,
    'global_usl': round(float(global_usl), 6) if global_usl is not None else None,
}
```

#### 2. Frontend Changes (`MultiFileChart.vue`)

**Limit lines: no longer merge identical values**

```typescript
// Each file displays its own limit lines
for (const lot of lots) {
  const dn = displayName(lot)
  if (lot.upper_limit != null) {
    const label = `${dn} USL=${formatAxisValue(lot.upper_limit)} (失效: ${lot.fail})`
    mk.push({
      xAxis: lot.upper_limit,
      lineStyle: { color: lot.color, width: 2, type: 'dashed' },
      label: {
        show: true,
        formatter: label,
        position: 'end',
        color: lot.color,
        fontSize: 10,
        backgroundColor: 'rgba(255,255,255,0.8)',
        padding: [2, 4],
        borderRadius: 2,
      },
    })
  }
  // Same for lower_limit...
}
```

**Normal distribution curves**

```typescript
if (showNormal) {
  for (const lot of lots) {
    const dn = displayName(lot)
    if (lot.std > 0 && binCenters.length > 0) {
      const xMin = binCenters[0]
      const xMax = binCenters[binCenters.length - 1]
      const step = (xMax - xMin) / 100
      const normalData: [number, number][] = []
      for (let x = xMin; x <= xMax; x += step) {
        normalData.push([x, normalPDF(x, lot.mean, lot.std)])
      }
      series.push({
        name: `${dn} 正态分布`,
        type: 'line',
        data: normalData,
        smooth: true,
        lineStyle: { color: lot.color, width: 2, type: 'dashed' },
        symbol: 'none',
        yAxisIndex: 1,  // Independent probability density Y-axis
        z: 10,
      })
    }
  }
}
```

**Dual Y-axis configuration**

```typescript
const yAxisConfig: any[] = [
  {
    type: 'value',
    name: '百分比 (%)',
    min: 0,
    nameTextStyle: { color: tc },
    axisLabel: { formatter: '{value}%', color: tc },
  },
]

if (showNormal) {
  yAxisConfig.push({
    type: 'value',
    name: '概率密度',
    nameTextStyle: { color: tc },
    axisLabel: { color: tc },
    splitLine: { show: false },
  })
}
```

#### 3. ChartConfigPanel Changes

Added "正态分布" checkbox for `variant='multi-file'`:

```html
<el-checkbox-group :model-value="chartConfig" @change="onChartConfigChange" class="config-checkboxes">
  <el-checkbox value="limit">Limit</el-checkbox>
  <template v-if="variant === 'full'">
    <el-checkbox value="s3">3σ线</el-checkbox>
    <el-checkbox value="s4">4σ线</el-checkbox>
    <el-checkbox value="s6">6σ线</el-checkbox>
  </template>
  <el-checkbox value="normal">正态分布</el-checkbox>  <!-- Now available for both variants -->
</el-checkbox-group>
```

### Testing Results

**E2E Tests Added:**
- ✅ 每个文件显示独立的 limit 线（含失效个数）
- ✅ 正态分布曲线复选框控制显示/隐藏
- ✅ 正态分布曲线显示独立的概率密度 Y 轴
- ✅ X 轴基于 limit 值分配（24份）

**All 13 multi-file analysis tests passed.**

### Files Modified

| File | Changes |
|------|---------|
| `apps/analysis/services/data_services.py` | Limit-based X-axis algorithm, global_lsl/global_usl return values |
| `frontend/src/pages/analysis/components/MultiFileChart.vue` | Per-file limit lines, normal distribution curves, dual Y-axis |
| `frontend/src/pages/analysis/components/ChartConfigPanel.vue` | Normal distribution checkbox for multi-file variant |
| `frontend/e2e/analysis/multi-file.spec.ts` | 4 new test cases for new features |

## 2026-06-11 Enhancement v2: Align with Single-File Analysis Style

### New Requirements (User Feedback)

1. **Limit labels** - Simplify to LSL/USL (same as single-file analysis), remove fail count from labels
2. **Limit lines visibility** - Ensure all files' limit lines are fully visible (expand X-axis range)
3. **X-axis fixed 24 coordinates** - Always use 24 bins
4. **Bar chart style** - Add percentage labels on top (same as single-file analysis All Site style)

### Implementation Details

#### 1. Backend Changes (`apps/analysis/services/data_services.py`)

**X-axis range expansion to include all limit lines:**

```python
# Resolve bin range using range_type
bin_min, bin_max = _resolve_multi_range(...)

# Expand range to include all limit lines
if global_lsl is not None:
    bin_min = min(bin_min, global_lsl)
if global_usl is not None:
    bin_max = max(bin_max, global_usl)

# Add 5% margin to ensure limit lines are not at the edge
margin = (bin_max - bin_min) * 0.05
bin_min -= margin
bin_max += margin

# Fixed 24 bins
bin_count = 24
bins = np.linspace(bin_min, bin_max, bin_count + 1)
bin_centers = [float((bins[i] + bins[i + 1]) / 2) for i in range(bin_count)]
```

#### 2. Frontend Changes (`MultiFileChart.vue`)

**Simplified limit labels (same as single-file analysis):**

```typescript
if (lot.upper_limit != null) {
  mk.push({
    xAxis: lot.upper_limit,
    lineStyle: { color: '#C62828', width: 3, type: 'dashed' },
    label: {
      show: true,
      formatter: 'USL',  // Simplified label
      position: 'end',
      color: '#C62828',
      fontSize: 12,
      fontWeight: 'bold',
    },
  })
}
```

**Bar chart with percentage labels:**

```typescript
series.push({
  name: dn,
  type: 'bar',
  data: lot.bar_data,
  itemStyle: { color: lot.color },
  barWidth: `${props.barWidthPercent}%`,
  barGap: '10%',
  label: {
    show: true,
    position: 'top',
    formatter: (params: any) => {
      const value = params.data?.[1]
      return value > 0 ? `${value.toFixed(2)}%` : ''
    },
    fontSize: 10,
    color: lot.color,
    fontWeight: 'bold',
  },
})
```

**X-axis configuration (same as single-file analysis):**

```typescript
xAxis: {
  type: 'value',
  min: binCenters.length > 0 ? binCenters[0] : r.chart_min,
  max: binCenters.length > 0 ? binCenters[binCenters.length - 1] : r.chart_max,
  axisLabel: {
    rotate: 45,
    show: true,
    interval: 0,
    fontSize: 9,
    formatter: formatAxisValue,
    color: tc,
  },
  splitNumber: 24,  // Fixed 24 coordinates
}
```

### Testing Results

**All 13 multi-file analysis E2E tests passed.**

### Alignment with Single-File Analysis

| Feature | Single-File Analysis | Multi-File Analysis (v2) |
|---------|---------------------|-------------------------|
| Limit labels | LSL/USL | LSL/USL ✅ |
| X-axis coordinates | 24 | 24 ✅ |
| Bar labels | Percentage values | Percentage values ✅ |
| Y-axis config | Left percentage | Left percentage ✅ |
| Normal distribution | Independent Y-axis | Independent Y-axis ✅ |
