# BoxPlot Integration into SingleFileAnalysis

## Summary

Remove the standalone BoxPlot tab from AnalysisPage. Integrate the boxplot chart into SingleParamTab as a toggle-able chart below the QQ plot, sharing the same parameter selection and configuration.

## Motivation

- BoxPlot currently lives in a separate tab with its own ParamSelector, forcing users to switch tabs and re-select parameters.
- In SingleFileAnalysis, the user already selects a parameter and configures ignoreNoLimit. The boxplot should share this context.
- Placing the boxplot below the QQ plot creates a natural analytical flow: histogram (distribution shape) → QQ plot (normality check) → boxplot (site-level spread).

## Design

### Toolbar Changes (SingleParamTab)

Add two checkboxes in the toolbar, after the existing "显示QQ图" checkbox:

```
[数值分布] [序列分布]  ☑ 显示QQ图  ☑ 显示箱线图  ☑ Jitter散点
```

- "显示箱线图" (`showBoxPlot`): only visible when `chartMode === 'distribution'`
- "Jitter散点" (`showJitter`): only visible when `showBoxPlot` is true

### Chart Area Layout

The chart area renders up to 3 charts vertically stacked when in distribution mode:

```
┌─ HistogramChart (always, min-height: 480px) ────────┐
├─ QQPlotChart (if showQQPlot, min-height: 400px) ────┤
├─ BoxPlotChart (if showBoxPlot, min-height: 400px) ──┤
└──────────────────────────────────────────────────────┘
```

When `chartMode === 'serial'`, only SerialChart is shown (boxplot and QQ are hidden).

### Shared State

| State | Source | How BoxPlot uses it |
|---|---|---|
| `localSelectedParam` | SingleParamTab (defineModel) | Passed to `useBoxPlot` composable |
| `ignoreNoLimit` | SingleParamTab (from analysisStore) | Already synced to store; `useBoxPlot` reads from API |
| `fileId` | SingleParamTab props | Passed to `useBoxPlot` composable |
| `groupBy` | Hardcoded `ref('site')` | Fixed, no UI toggle |

### Composable Integration

Add `useBoxPlot` composable to SingleParamTab:

```ts
const groupBy = ref('site')
const { loading: boxPlotLoading, boxPlotData, stats: boxPlotStats } = useBoxPlot(
  () => props.fileId,
  localSelectedParam,
  groupBy
)
```

The composable auto-loads on param/fileId/groupBy changes. No manual trigger needed.

### Files to Modify

| File | Change |
|---|---|
| `SingleParamTab.vue` | Add showBoxPlot/showJitter toggles, integrate useBoxPlot, add BoxPlotChart to template |
| `AnalysisPage.vue` | Remove BoxPlot tab pane and BoxPlotSection import |
| `BoxPlotSection.vue` | Delete file (functionality merged into SingleParamTab) |

### BoxPlotChart Props

```ts
defineProps<{
  data: any           // raw boxPlotData from useBoxPlot
  selectedParam: string
  groupBy: string     // always 'site'
  showJitter: boolean
}>()
```

The chart receives the full `boxPlotData` and extracts the selected param's series internally (same as current behavior).

## Non-Goals

- No groupBy UI toggle (fixed to 'site')
- No BoxPlotStatsTable in left panel (stats visible in chart and top StatsSummary)
- No changes to the boxplot backend API
- No changes to BoxPlotChart.vue internals (reuse as-is)

## Validation

1. Open SingleFileAnalysis tab → toolbar shows "显示箱线图" checkbox
2. Check "显示箱线图" → boxplot appears below QQ plot (or below histogram if QQ hidden)
3. Switch parameter via ParamSelector → boxplot updates automatically
4. Toggle ignoreNoLimit → boxplot reloads
5. Switch to serial mode → boxplot and QQ both hidden
6. BoxPlot tab no longer exists in AnalysisPage
