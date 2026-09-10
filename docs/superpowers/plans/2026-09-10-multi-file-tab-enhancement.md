# Multi-File Tab Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增强多文件分析 tab：布局升级、统计对比（CPK/Median）、图表扩展（KDE/箱线图）、阶段智能标签

**Architecture:** 后端在现有 `compute_multi_lot_distribution` 中追加统计字段（CPK/median/quartiles/KDE），不新增端点；前端 MultiFileTab 迁移到 AnalysisTabLayout 统一结构，新增箱线图组件和 KDE 叠加渲染

**Tech Stack:** Django/Python (numpy, pandas) + Vue 3/TypeScript + ECharts + Element Plus + Playwright (E2E)

**Spec:** `docs/superpowers/specs/2026-09-10-multi-file-tab-enhancement-design.md`

---

### Task 1: 后端 lot_data 统计字段增强

**Files:**
- Modify: `apps/analysis/services/data_services/multi_lot.py`
- Test: `apps/analysis/tests_param_guards.py`

- [ ] **Step 1: 写失败测试**

在 `tests_param_guards.py` 的 `MultiFileAnalysisTests` 类末尾追加：

```python
def test_lot_data_includes_cpk_median_quartiles(self):
    """每个 lot_data 项包含 cpk/cp/median/q1/q3 字段。"""
    from apps.analysis.services.data_services import compute_multi_lot_distribution

    s1 = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    s2 = pd.Series([2.0, 3.0, 4.0, 5.0, 6.0])
    datasets = {
        '1': {'df': pd.DataFrame({'A': s1}),
              'metadata': {'mins': {'A': '0'}, 'maxs': {'A': '6'}},
              'series': s1, 'name': 'f1', 'file_id': 1},
        '2': {'df': pd.DataFrame({'A': s2}),
              'metadata': {'mins': {'A': '0'}, 'maxs': {'A': '6'}},
              'series': s2, 'name': 'f2', 'file_id': 2},
    }
    out = compute_multi_lot_distribution(datasets, [s1, s2], 'A')
    for lot in out['lot_data']:
        self.assertIn('cpk', lot)
        self.assertIn('cp', lot)
        self.assertIn('cpk_level', lot)
        self.assertIn('cpk_color', lot)
        self.assertIn('median', lot)
        self.assertIn('q1', lot)
        self.assertIn('q3', lot)
        self.assertIsInstance(lot['median'], float)
        self.assertIsInstance(lot['q1'], float)

def test_lot_data_kde_included_when_requested(self):
    """include_kde=True 时每个 lot 包含 kde_curve，默认不含。"""
    from apps.analysis.services.data_services import compute_multi_lot_distribution

    s1 = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0] * 20)
    s2 = pd.Series([2.0, 3.0, 4.0, 5.0, 6.0] * 20)
    datasets = {
        '1': {'df': pd.DataFrame({'A': s1}),
              'metadata': {'mins': {'A': '0'}, 'maxs': {'A': '7'}},
              'series': s1, 'name': 'f1', 'file_id': 1},
        '2': {'df': pd.DataFrame({'A': s2}),
              'metadata': {'mins': {'A': '0'}, 'maxs': {'A': '7'}},
              'series': s2, 'name': 'f2', 'file_id': 2},
    }
    # Default: no kde
    out = compute_multi_lot_distribution(datasets, [s1, s2], 'A')
    for lot in out['lot_data']:
        self.assertIsNone(lot.get('kde_curve'))
    # With include_kde
    out2 = compute_multi_lot_distribution(datasets, [s1, s2], 'A', include_kde=True)
    for lot in out2['lot_data']:
        self.assertIsNotNone(lot['kde_curve'])
        self.assertIsInstance(lot['kde_curve'], list)
        self.assertGreater(len(lot['kde_curve']), 0)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python manage.py test apps.analysis.tests_param_guards.MultiFileAnalysisTests.test_lot_data_includes_cpk_median_quartiles apps.analysis.tests_param_guards.MultiFileAnalysisTests.test_lot_data_kde_included_when_requested -v 2`
Expected: FAIL (fields missing)

- [ ] **Step 3: 实现后端改动**

在 `multi_lot.py` 顶部 import 区追加：

```python
from apps.analysis.services.statistics import compute_cpk
from apps.analysis.services.data_services.histogram import compute_kde_curve
```

修改 `compute_multi_lot_distribution` 函数签名，追加 `include_kde=False` 参数：

```python
def compute_multi_lot_distribution(datasets, all_series, param,
                                    range_type='S4', custom_low=None,
                                    custom_high=None, include_kde=False):
```

在 Second pass 循环内（`for pre in lot_data_pre:` 块），`lot_data.append(...)` 之前追加计算：

```python
        # CPK/CP: 用每个文件自己的规格限（与 trends.py 同口径）
        cpk_result = compute_cpk(pre['mean_v'], pre['std_v'], lower_limit, upper_limit)
        # Median + quartiles
        median_v = round(float(series.median()), 6)
        q1_v = round(float(series.quantile(0.25)), 6)
        q3_v = round(float(series.quantile(0.75)), 6)
        # KDE curve (optional)
        kde = None
        if include_kde and len(series) >= 3:
            kde = compute_kde_curve(series, bin_min, bin_max)
```

在 `lot_data.append({...})` 字典中追加字段：

```python
            'cpk': round(cpk_result['cpk'], 4),
            'cp': round(cpk_result['cp'], 4) if cpk_result['cp'] is not None else None,
            'cpk_level': cpk_result['cpk_level'],
            'cpk_color': cpk_result['cpk_color'],
            'median': median_v,
            'q1': q1_v,
            'q3': q3_v,
            'kde_curve': kde,
```

- [ ] **Step 4: 在 view 层传递 include_kde**

在 `analysis_views.py` 的 `multi_lot` action 中，两处调用 `compute_multi_lot_distribution` 时追加 `include_kde` 参数：

合并请求分支（~line 376）：
```python
                    include_kde = get_bool_param(request, 'include_kde')
                    dist = compute_multi_lot_distribution(
                        datasets, all_series, first, range_type,
                        custom_low, custom_high, include_kde=include_kde)
```

带 param 分支（~line 447）：
```python
        include_kde = get_bool_param(request, 'include_kde')
        result = compute_multi_lot_distribution(
            datasets, all_series, param,
            range_type=range_type, custom_low=custom_low, custom_high=custom_high,
            include_kde=include_kde,
        )
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python manage.py test apps.analysis.tests_param_guards.MultiFileAnalysisTests -v 2`
Expected: 全部 PASS

- [ ] **Step 6: 运行全量后端测试确认无回归**

Run: `python manage.py test apps.analysis -v 1`
Expected: OK

- [ ] **Step 7: Commit**

```
git add apps/analysis/services/data_services/multi_lot.py apps/analysis/views/analysis_views.py apps/analysis/tests_param_guards.py
git commit -m "feat(multi-lot): lot_data 追加 cpk/cp/median/q1/q3/kde_curve 字段"
```

---

### Task 2: 前端 Store 扩展

**Files:**
- Modify: `frontend/src/stores/analysisTabs.ts`

- [ ] **Step 1: 在 createMultiState 中追加新字段**

在 `createMultiState` 函数中，`...createFilterStateWithoutOutlier()` 之前追加：

```typescript
    showBoxPlot: ref(false),
    showKde: ref(false),
```

- [ ] **Step 2: 运行 vue-tsc 确认无类型错误**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```
git add frontend/src/stores/analysisTabs.ts
git commit -m "feat(multi-tab-store): 追加 showBoxPlot/showKde 开关字段"
```

---

### Task 3: MultiFileTab 迁移到 AnalysisTabLayout

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue`

- [ ] **Step 1: 替换 template 为 AnalysisTabLayout 结构**

将现有 `<div class="multi-file-tab">` 内的手工 `el-row/el-col` 替换为：

```vue
<template>
  <AnalysisTabLayout :loading="loading" class="multi-file-tab">
    <template #toolbar>
      <div class="control-panel">
        <div class="control-panel__main">
          <AnalysisFilePicker
            v-model="fileIds"
            :files="files"
            scope="multi"
            multiple
            label="数据文件 (最少 2 个)"
          />
          <div class="chart-toggles">
            <el-checkbox v-model="showBoxPlot" size="small">显示箱线图</el-checkbox>
            <el-checkbox v-model="showKde" size="small">显示KDE</el-checkbox>
          </div>
        </div>
        <div class="control-panel__filters">
          <DataFilterSection
            variant="bar"
            scope="multi"
            v-model:ignore-no-limit="ignoreNoLimit"
            v-model:ignore-no-test-value="ignoreNoTestValue"
            v-model:data-only-bin1="dataOnlyBin1"
            v-model:only-fail-test-item="onlyFailTestItem"
            v-model:only-low-cpk="onlyLowCpk"
            v-model:iqr-multiplier="iqrMultiplier"
            :show-outlier="false"
          />
        </div>
      </div>
    </template>

    <template #left-panel>
      <!-- 自定义图例名（保留现有逻辑） -->
      <el-card v-if="selectedFileObjs.length" shadow="hover" :body-style="{ padding: '12px' }">
        <div class="section-label">自定义图例名</div>
        <div v-for="f in selectedFileObjs" :key="f.id" class="name-row">
          <span class="name-dot" :style="{ background: colorOf(f.id) }" />
          <label :for="`file-name-${f.id}`" class="sr-only">{{ f.filename }} 图例名</label>
          <el-input :id="`file-name-${f.id}`" v-model="fileNames[f.id]" :placeholder="f.filename" size="small" clearable />
        </div>
      </el-card>

      <ChartConfigPanel variant="multi-file" v-model:chart-config="chartConfig" v-model:bar-width-percent="barWidthPercent" :bar-width-max="barWidthMax" :range-type="'RDL'" />

      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label" for="multi-range-type">范围类型</label>
        <el-select id="multi-range-type" v-model="rangeType" size="small" style="width: 100%">
          <el-option label="Spec Limits (RDL)" value="RDL" />
          <el-option label="Data Range (DR)" value="DR" />
          <el-option label="3 Sigma (S3)" value="S3" />
          <el-option label="4 Sigma (S4)" value="S4" />
          <el-option label="6 Sigma (S6)" value="S6" />
        </el-select>
      </el-card>

      <!-- 统计对比表（Task 4 增强） -->
      <el-card v-if="lotStats.length" shadow="hover" :body-style="{ padding: '8px' }">
        <div class="section-label">各文件统计</div>
        <el-table :data="lotStats" size="small" stripe max-height="260">
          <el-table-column prop="name" label="文件" min-width="90" show-overflow-tooltip />
          <el-table-column prop="mean" label="Mean" width="78" />
          <el-table-column prop="std" label="STD" width="70" />
          <el-table-column prop="count" label="N" width="56" />
          <el-table-column label="Yield" width="68">
            <template #default="{ row }">{{ row.yield_pct }}%</template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <template #right-panel>
      <el-empty v-if="fileIds.length < 2" description="请至少选择 2 个数据文件" />
      <ErrorBanner v-else-if="paramsError" :message="paramsError" title="共有测试项加载失败" @retry="reloadParams" />
      <el-empty v-else-if="commonParams.length === 0 && !paramsLoading" description="所选文件没有共有测试项" />
      <template v-else>
        <div class="top-bar">
          <ParamSelector :params="commonParams" v-model:selected-param="selectedParam" popper-class="dp-param-popper-multi" />
          <div class="common-hint">共有测试项：{{ commonParams.length }} 项</div>
          <CircularProgress :loading="loading" />
        </div>
        <div class="chart-wrapper">
          <MultiFileChart v-if="lotData && lotData.lot_data && lotData.lot_data.length > 0"
            :lot-data="lotData" :chart-config="chartConfig" :bar-width-percent="barWidthPercent"
            :file-names="resolvedNames" :selected-param="selectedParam" />
          <ErrorBanner v-else-if="distError" :message="distError" title="多文件分布加载失败"
            @retry="loadDistribution(fileIds, selectedParam, rangeType, multiFilters)" />
          <el-empty v-else-if="lotData && selectedParam"
            :description="`${selectedParam} 暂无有效数据`"
            style="height: 100%; display: flex; align-items: center; justify-content: center;" />
        </div>
        <!-- 可折叠箱线图（Task 6 实现组件） -->
        <el-card v-if="showBoxPlot && lotData?.lot_data?.length" shadow="never"
          :body-style="{ padding: '8px' }" class="boxplot-card">
          <div class="section-label">箱线图对比</div>
          <div style="height: 240px">
            <MultiFileBoxPlot v-if="lotData" :lot-data="lotData" :file-names="resolvedNames" />
          </div>
        </el-card>
      </template>
    </template>
  </AnalysisTabLayout>
</template>
```

- [ ] **Step 2: 更新 script setup**

追加 import：

```typescript
import AnalysisTabLayout from './AnalysisTabLayout.vue'
import MultiFileBoxPlot from './MultiFileBoxPlot.vue'
```

从 store 追加解构：

```typescript
const { ..., showBoxPlot, showKde } = storeToRefs(multiStore)
```

- [ ] **Step 3: 更新 style scoped**

追加与单文件 tab 对齐的样式（可复用）：

```css
.control-panel { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.control-panel__main { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.control-panel__main > .dp-analysis-filepicker { flex: 1; min-width: 240px; }
.chart-toggles { display: flex; align-items: center; gap: 12px; margin-left: auto; }
.control-panel__filters { border-top: 1px dashed var(--border-2, #e4e7ed); padding-top: 8px; }
.boxplot-card { flex-shrink: 0; }
```

移除旧的手工布局样式（`.multi-toolbar`, `.main-row`, `.left-panel`, `.right-panel` 等）。

- [ ] **Step 4: 运行 vue-tsc 确认编译通过**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors（MultiFileBoxPlot 暂用占位组件，Task 6 实现）

- [ ] **Step 5: 创建 MultiFileBoxPlot 占位组件**

新建 `frontend/src/pages/analysis/components/MultiFileBoxPlot.vue`（最小占位，Task 6 实现完整版）：

```vue
<template>
  <div ref="chartRef" class="chart-container" />
</template>
<script setup lang="ts">
const props = defineProps<{ lotData: any; fileNames: Record<number, string> }>()
</script>
<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 200px; }
</style>
```

- [ ] **Step 6: 运行 vue-tsc + 确认页面可用**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 7: Commit**

```
git add frontend/src/pages/analysis/components/MultiFileTab.vue frontend/src/pages/analysis/components/MultiFileBoxPlot.vue frontend/src/stores/analysisTabs.ts
git commit -m "refactor(multi-file-tab): 迁移到 AnalysisTabLayout + toolbar 图表勾选"
```

---

### Task 4: 统计对比表增强

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue`

- [ ] **Step 1: 扩展 lotStats computed 属性**

在 `MultiFileTab.vue` 中，将 `lotStats` computed 从 4 列扩展到 9 列 + CPK 着色：

```typescript
const lotStats = computed(() => {
  const lots = lotData.value?.lot_data || []
  return lots.map((lot: any) => ({
    name: resolvedNames.value[lot.file_id] || lot.name,
    mean: lot.mean,
    std: lot.std,
    median: lot.median,
    cpk: lot.cpk,
    cpk_level: lot.cpk_level,
    cpk_color: lot.cpk_color,
    count: lot.count,
    yield_pct: lot.yield_pct,
    min_v: lot.min_v,
    max_v: lot.max_v,
  }))
})
```

- [ ] **Step 2: 更新统计表 template**

替换 `<el-table>` 内容为 9 列：

```vue
<el-table :data="lotStats" size="small" stripe max-height="300">
  <el-table-column prop="name" label="文件" min-width="80" show-overflow-tooltip fixed />
  <el-table-column prop="mean" label="Mean" width="75" />
  <el-table-column prop="std" label="STD" width="70" />
  <el-table-column prop="median" label="Median" width="75" />
  <el-table-column label="CPK" width="65">
    <template #default="{ row }">
      <span :style="{ color: row.cpk_color === 'gray' ? undefined : `var(--cpk-${row.cpk_color}, inherit)`, fontWeight: row.cpk_color !== 'gray' ? 600 : 400 }">
        {{ row.cpk != null ? row.cpk.toFixed(2) : '—' }}
      </span>
    </template>
  </el-table-column>
  <el-table-column prop="count" label="N" width="55" />
  <el-table-column label="Yield" width="65">
    <template #default="{ row }">{{ row.yield_pct }}%</template>
  </el-table-column>
  <el-table-column prop="min_v" label="Min" width="70" />
  <el-table-column prop="max_v" label="Max" width="70" />
</el-table>
```

- [ ] **Step 3: 追加 CPK 颜色 CSS 变量**

在 `<style scoped>` 中追加（对齐现有 design-tokens）：

```css
/* CPK 着色：与单文件 tab 的 cpk-badge 同源色 */
:deep(.cpk-green) { color: #22c55e; }
:deep(.cpk-orange) { color: #f59e0b; }
:deep(.cpk-darkorange) { color: #ea580c; }
:deep(.cpk-red) { color: #ef4444; }
```

- [ ] **Step 4: 运行 vue-tsc**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 5: Commit**

```
git add frontend/src/pages/analysis/components/MultiFileTab.vue
git commit -m "feat(multi-file-tab): 统计表扩展到 CPK/Median/Min/Max + 着色"
```

---

### Task 5: ChartConfigPanel 新增 KDE 选项

**Files:**
- Modify: `frontend/src/pages/analysis/components/ChartConfigPanel.vue`

- [ ] **Step 1: 在 multi-file variant 中追加 KDE checkbox**

在 `ChartConfigPanel.vue` 的 `<el-checkbox-group>` 中，`normal` 之后追加：

```vue
<el-checkbox v-if="variant === 'multi-file'" value="kde">KDE曲线</el-checkbox>
```

- [ ] **Step 2: 运行 vue-tsc**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/analysis/components/ChartConfigPanel.vue
git commit -m "feat(chart-config): multi-file variant 新增 KDE 曲线选项"
```

---

### Task 6: MultiFileChart KDE 曲线渲染

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileChart.vue`
- Modify: `frontend/src/pages/analysis/composables/useMultiFile.ts`

- [ ] **Step 1: 在 useMultiFile 请求中传递 include_kde**

在 `useMultiFile.ts` 的 `loadCommonParams` 和 `loadDistribution` 函数中，请求体追加 `include_kde`：

```typescript
async function loadCommonParams(fileIds: number[], ignoreNoLimit: boolean,
                                rangeType: string = 'RDL',
                                filters: MultiFilterFlags = {},
                                includeKde: boolean = false) {
  // ...
  const result = await runParams(() => api.post('/analysis/multi_lot/', {
    file_ids: fileIds,
    ignore_no_limit: ignoreNoLimit,
    range_type: rangeType,
    include_kde: includeKde,
    ...filters,
  }))
```

```typescript
async function loadDistribution(fileIds: number[], param: string,
                                rangeType: string = 'S4',
                                filters: MultiFilterFlags = {},
                                includeKde: boolean = false) {
  // ...
  await runDist(() => api.post('/analysis/multi_lot/', {
    file_ids: fileIds,
    param,
    range_type: rangeType,
    include_kde: includeKde,
    ...filters,
  }))
```

- [ ] **Step 2: MultiFileTab 传递 showKde 到 composable**

在 `MultiFileTab.vue` 中，watch 和调用处追加 `showKde.value`：

```typescript
// reloadParams 调用处
await loadCommonParams(fileIds.value, ignoreNoLimit.value, rangeType.value, multiFilters.value, showKde.value)
// loadDistribution 调用处
loadDistribution(fileIds.value, selectedParam.value, rangeType.value, multiFilters.value, showKde.value)
```

追加 watch：
```typescript
watch(showKde, () => { reloadParams() })
```

- [ ] **Step 3: MultiFileChart 渲染 KDE 曲线**

在 `MultiFileChart.vue` 的 `buildOption` 中，正态分布块之后追加 KDE 渲染：

```typescript
  // KDE 曲线：每个文件独立颜色
  const showKde = props.chartConfig.includes('kde')
  if (showKde) {
    for (const lot of lots) {
      const dn = displayName(lot)
      const lc = lotThemeColor(lot)
      if (lot.kde_curve && lot.kde_curve.length > 0) {
        series.push({
          name: `${dn} KDE`,
          type: 'line',
          data: lot.kde_curve,
          smooth: true,
          lineStyle: { color: lc, width: 2.5 },
          itemStyle: { color: lc },
          symbol: 'none',
          yAxisIndex: 1,
          z: 10,
        })
        legendData.push(`${dn} KDE`)
      }
    }
  }
```

确保 `yAxisConfig` 在 `showNormal || showKde` 时都包含右侧密度轴：

```typescript
  if (showNormal || showKde) {
    yAxisConfig.push({
      type: 'value',
      name: '概率密度',
      // ...（现有代码不变）
    })
  }
```

- [ ] **Step 4: 运行 vue-tsc**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 5: Commit**

```
git add frontend/src/pages/analysis/composables/useMultiFile.ts frontend/src/pages/analysis/components/MultiFileChart.vue frontend/src/pages/analysis/components/MultiFileTab.vue
git commit -m "feat(multi-file-chart): KDE 曲线叠加渲染 + include_kde 请求参数"
```

---

### Task 7: MultiFileBoxPlot 箱线图组件

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileBoxPlot.vue`

- [ ] **Step 1: 实现完整箱线图组件**

替换 Task 3 的占位内容为：

```vue
<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { mapLotColorToTheme } from '../../../utils/chart-bar'

const props = defineProps<{
  lotData: any
  fileNames: Record<number, string>
}>()

const { colors, isDark } = useEChartsTheme()

function lotThemeColor(lot: any): string {
  return mapLotColorToTheme(lot.color, isDark.value)
}

function displayName(lot: any): string {
  return props.fileNames[lot.file_id] || lot.name || `File ${lot.file_id}`
}

function buildOption() {
  const r = props.lotData
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}
  const tc = colors.value.textColor
  const lots = r.lot_data

  // boxplot data: [min, Q1, median, Q3, max] per file
  const boxData = lots.map((lot: any) => [
    lot.min_v ?? 0, lot.q1 ?? 0, lot.median ?? 0, lot.q3 ?? 0, lot.max_v ?? 0,
  ])
  const categories = lots.map((lot: any) => displayName(lot))

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
    },
    grid: { top: 20, bottom: 40, left: 80, right: 30 },
    xAxis: {
      type: 'value',
      axisLabel: { color: tc, fontSize: 10 },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: tc, fontSize: 11 },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
    },
    series: [{
      type: 'boxplot',
      data: boxData.map((d: number[], i: number) => ({
        value: d,
        itemStyle: {
          color: lotThemeColor(lots[i]) + '33',
          borderColor: lotThemeColor(lots[i]),
        },
      })),
      boxWidth: [12, 24],
    }],
  }
}

const { chartRef } = useChart(buildOption, [
  () => props.lotData,
  () => props.fileNames,
])
void chartRef
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 200px; }
</style>
```

- [ ] **Step 2: 运行 vue-tsc**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/analysis/components/MultiFileBoxPlot.vue
git commit -m "feat(multi-file-boxplot): 多文件水平箱线图组件"
```

---

### Task 8: 阶段智能标签

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue`

- [ ] **Step 1: 增强 autoExtractLabel 函数**

替换现有的 `autoExtractLabel` 为带阶段识别的增强版：

```typescript
/**
 * 从多个文件名中自动提取差异部分作为图例名。
 * 增强版：先剥离时间戳后缀，再尝试匹配阶段关键字（FT/QA/RT/CP/UIS/EQC），
 * 最后回退到公共前后缀裁剪。
 */
function autoExtractLabel(filenames: string[]): string[] {
  if (filenames.length <= 1) return filenames

  // Phase 0: 剥离扩展名和时间戳后缀
  const stripped = filenames.map(f =>
    f.replace(/\.(csv|txt|xlsx)$/i, '')
     .replace(/[_\-.]\d{8}[_\-]?\d{6}$/, '')
     .replace(/[_\-.]\d{8}$/, '')
  )

  // Phase 1: 尝试阶段关键字识别
  const STAGE_RE = /(?:FT|QA|RT|CP|UIS|EQC)\d*/gi
  const stages = stripped.map(f => {
    const m = f.match(STAGE_RE)
    return m ? m[m.length - 1] : null
  })
  if (stages.every(s => s !== null)) {
    // 去重：相同阶段名追加序号
    const seen = new Map<string, number>()
    return stages.map(s => {
      const count = seen.get(s!) ?? 0
      seen.set(s!, count + 1)
      return count > 0 ? `${s} (${count + 1})` : s!
    })
  }

  // Phase 2: 回退到公共前后缀裁剪（现有逻辑）
  let prefix = stripped[0]
  for (let i = 1; i < stripped.length; i++) {
    while (prefix.length > 0 && !stripped[i].startsWith(prefix)) prefix = prefix.slice(0, -1)
  }
  let suffix = stripped[0]
  for (let i = 1; i < stripped.length; i++) {
    while (suffix.length > 0 && !stripped[i].endsWith(suffix)) suffix = suffix.slice(1)
  }

  return stripped.map(f => {
    let mid = f.slice(prefix.length)
    if (suffix.length) mid = mid.slice(0, -suffix.length)
    mid = mid.replace(/^[_\-. ]+|[_\-. ]+$/g, '')
    if (mid.length > 30) {
      const sep = mid.search(/[_\-].{8,}/)
      if (sep > 0) mid = mid.slice(0, sep)
    }
    return mid || f
  })
}
```

- [ ] **Step 2: 运行 vue-tsc**

Run: `cd frontend; npx vue-tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/analysis/components/MultiFileTab.vue
git commit -m "feat(multi-file-tab): 阶段智能标签（时间戳剥离 + FT/QA/RT 模式识别）"
```

---

### Task 9: 前端构建验证 + E2E 测试

**Files:**
- Modify: `frontend/e2e/analysis/multi-file.spec.ts`

- [ ] **Step 1: 运行前端构建确认零错误**

Run: `cd frontend; npm run build`
Expected: 0 TS errors, build success

- [ ] **Step 2: 在 multi-file.spec.ts 追加增强功能的 E2E 用例**

在现有 `test.describe` 块内追加：

```typescript
  test('统计对比表包含 CPK 和 Median 列', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    // 等待分布数据返回
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    // 统计表应包含 Median 和 CPK 列头
    const statsTable = page.locator(`${TAB} .left-panel .el-table`)
    await expect(statsTable).toBeVisible({ timeout: 10_000 })
    const headers = await statsTable.locator('th').allTextContents()
    expect(headers.join(',')).toContain('Median')
    expect(headers.join(',')).toContain('CPK')
  })

  test('箱线图 checkbox 控制折叠区显隐', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    // 默认不显示箱线图
    const boxCard = page.locator(`${TAB} .boxplot-card`)
    await expect(boxCard).toHaveCount(0)
    // 勾选后出现
    await page.getByRole('checkbox', { name: '显示箱线图' }).check()
    await expect(boxCard).toBeVisible({ timeout: 5_000 })
    // 取消后消失
    await page.getByRole('checkbox', { name: '显示箱线图' }).uncheck()
    await expect(boxCard).toHaveCount(0)
  })

  test('KDE checkbox 触发 include_kde 请求', async ({ page }) => {
    test.slow()
    await enterMultiFile(page)
    // 收集请求体
    const bodies: string[] = []
    page.on('request', (req) => {
      if (req.method() === 'POST' && req.url().includes('/analysis/multi_lot/')) {
        bodies.push(req.postData() || '')
      }
    })
    await pickFiles(page, [RECOMMENDED.buyoff[0], RECOMMENDED.buyoff[1]])
    await page.waitForResponse(
      (r) => r.url().includes('/analysis/multi_lot/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    // 默认不含 include_kde=true
    expect(bodies.some(b => b.includes('"include_kde":true'))).toBe(false)
    // 勾选后触发新请求带 include_kde=true
    await page.getByRole('checkbox', { name: '显示KDE' }).check()
    await expect.poll(
      () => bodies.some(b => b.includes('"include_kde":true')),
      { timeout: 15_000 },
    ).toBe(true)
  })
```

- [ ] **Step 3: 运行现有 E2E 确认无回归**

Run: `cd frontend; npx playwright test e2e/analysis/multi-file.spec.ts --reporter=list`
Expected: 全部 PASS（含新增用例）

- [ ] **Step 4: Commit**

```
git add frontend/e2e/analysis/multi-file.spec.ts
git commit -m "test(multi-file): E2E 用例覆盖 CPK 列/箱线图显隐/KDE 请求"
```
