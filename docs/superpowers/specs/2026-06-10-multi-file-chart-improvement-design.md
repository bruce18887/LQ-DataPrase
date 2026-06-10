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
