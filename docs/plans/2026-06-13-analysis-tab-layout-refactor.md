# 数据分析页面 Tab 布局统一改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the layout of boxplot and correlation tabs to match SingleParamTab's three-layer pattern, fix the boxplot display bug, rename tabs, and add loading indicators.

**Architecture:** Extract a shared `AnalysisTabLayout` component with toolbar/left-panel/right-panel slots. Refactor SingleParamTab, BoxPlotSection, and CorrelationToolsTab to use it. Fix backend `ensure_numeric` call and frontend tooltip index for boxplot.

**Tech Stack:** Vue 3.5 (Composition API), TypeScript, Element Plus, ECharts 6, Django REST Framework

---

## File Structure

### New Files
| File | Responsibility |
|------|----------------|
| `frontend/src/pages/analysis/components/AnalysisTabLayout.vue` | Shared three-layer layout (toolbar + left-panel + right-panel slots) |

### Modified Files
| File | Changes |
|------|---------|
| `apps/analysis/views.py:535` | Fix boxplot: `get_1d_from` → `ensure_numeric` |
| `frontend/src/pages/analysis/components/BoxPlotChart.vue:70-71` | Fix series tooltip index |
| `frontend/src/pages/analysis/components/SingleParamTab.vue` | Replace inline layout with `AnalysisTabLayout` |
| `frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue` | Full rewrite: three-layer layout with `AnalysisTabLayout` |
| `frontend/src/pages/analysis/components/CorrelationToolsTab.vue` | Full rewrite: three-layer layout with `AnalysisTabLayout`, rename to "相关性对比" |
| `frontend/src/pages/analysis/components/MultiFileTab.vue` | Add `CircularProgress` to right panel |
| `frontend/src/pages/analysis/AnalysisPage.vue` | Tab renames + label optimization |
| `frontend/e2e/analysis/analysis.spec.ts` | Update e2e tests for new tab names and boxplot |

---

### Task 1: Fix Boxplot Bug (Backend + Frontend)

**Files:**
- Modify: `apps/analysis/views.py:535`
- Modify: `frontend/src/pages/analysis/components/BoxPlotChart.vue:70-71`

- [ ] **Step 1: Fix backend — add `ensure_numeric` to boxplot endpoint**

In `apps/analysis/views.py`, line 535, change `get_1d_from` to `ensure_numeric`:

```python
# Line 535 — BEFORE:
data_series = get_1d_from(df, param)

# AFTER:
data_series = ensure_numeric(df, param)
```

Also verify the import at the top of the file. Add `ensure_numeric` to the import from helpers if not already present:

```python
# Around line 10-15, ensure this import exists:
from apps.analysis.services.statistics.helpers import get_1d_from, get_site_column, ensure_numeric
```

- [ ] **Step 2: Fix frontend — boxplot series tooltip index**

In `frontend/src/pages/analysis/components/BoxPlotChart.vue`, lines 70-71, fix the series tooltip formatter:

```typescript
// BEFORE (line 70-71):
formatter: (p: any) =>
  `<strong>${p.name}</strong><br/>Max: ${fmt(p.data[5])}<br/>Q3: ${fmt(p.data[4])}<br/>Median: ${fmt(p.data[3])}<br/>Q1: ${fmt(p.data[2])}<br/>Min: ${fmt(p.data[1])}`,

// AFTER:
formatter: (p: any) =>
  `<strong>${p.name}</strong><br/>Max: ${fmt(p.data[4])}<br/>Q3: ${fmt(p.data[3])}<br/>Median: ${fmt(p.data[2])}<br/>Q1: ${fmt(p.data[1])}<br/>Min: ${fmt(p.data[0])}`,
```

Note: The top-level tooltip (line 52-56) stays unchanged because `params.value` includes the category index prepended by ECharts, making `d[1]`~`d[5]` correct.

- [ ] **Step 3: Verify the backend fix**

Run the Django development server and test the boxplot endpoint:

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
python manage.py test apps.analysis.tests -k boxplot --verbosity=2
```

If no specific boxplot tests exist, verify manually by starting the server and checking the boxplot tab in the browser.

- [ ] **Step 4: Commit**

```bash
git add apps/analysis/views.py frontend/src/pages/analysis/components/BoxPlotChart.vue
git commit -m "fix(analysis): fix boxplot display bug — add ensure_numeric and fix tooltip index

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create AnalysisTabLayout Shared Component

**Files:**
- Create: `frontend/src/pages/analysis/components/AnalysisTabLayout.vue`

- [ ] **Step 1: Create the AnalysisTabLayout component**

```vue
<!-- frontend/src/pages/analysis/components/AnalysisTabLayout.vue -->
<template>
  <div class="analysis-tab-layout">
    <!-- 顶部工具栏 -->
    <div v-if="$slots.toolbar" class="toolbar">
      <slot name="toolbar" />
    </div>

    <!-- 主内容区：左侧配置面板 + 右侧图表 -->
    <el-row :gutter="12" class="main-row">
      <!-- 左侧面板 -->
      <el-col :span="leftPanelSpan" class="left-panel">
        <slot name="left-panel" />
      </el-col>

      <!-- 右侧面板 -->
      <el-col
        :span="rightPanelSpan"
        class="right-panel"
        v-loading="loading"
        element-loading-text="正在分析数据..."
      >
        <slot name="right-panel" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  loading?: boolean
  leftPanelSpan?: number
  rightPanelSpan?: number
}>(), {
  loading: false,
  leftPanelSpan: 6,
  rightPanelSpan: 18,
})
</script>

<style scoped>
.analysis-tab-layout {
  padding: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--bg-tertiary, #f8f9fa);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
}

.main-row {
  margin-bottom: 16px;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.right-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
```

- [ ] **Step 2: Verify the component compiles**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

Expected: No errors related to `AnalysisTabLayout`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/analysis/components/AnalysisTabLayout.vue
git commit -m "feat(analysis): add shared AnalysisTabLayout component

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Refactor SingleParamTab to Use AnalysisTabLayout

**Files:**
- Modify: `frontend/src/pages/analysis/components/SingleParamTab.vue`

This task replaces the inline layout (toolbar + el-row + el-col) with `AnalysisTabLayout`, keeping all logic identical.

- [ ] **Step 1: Update template to use AnalysisTabLayout**

Replace the entire `<template>` section of `SingleParamTab.vue`:

```vue
<template>
  <AnalysisTabLayout :loading="histLoading">
    <!-- 工具栏 -->
    <template #toolbar>
      <el-radio-group v-model="chartMode" size="small">
        <el-radio-button value="distribution">数值分布</el-radio-button>
        <el-radio-button value="serial">序列分布</el-radio-button>
      </el-radio-group>
      <el-checkbox
        v-if="chartMode === 'distribution'"
        v-model="showQQPlot"
        size="small"
        style="margin-left: 12px;"
      >
        显示QQ图
      </el-checkbox>
    </template>

    <!-- 左侧配置面板 -->
    <template #left-panel>
      <ChartConfigPanel
        v-model:chart-config="chartConfig"
        v-model:range-type="rangeType"
        v-model:bar-width-percent="barWidthPercent"
        v-model:ignore-no-limit="ignoreNoLimit"
        v-model:custom-low="customLow"
        v-model:custom-high="customHigh"
      />
      <RangeComparisonTable :range-table-data="rangeTableData" :range-type="rangeType" />
      <SiteStatsTable :site-stats="siteStats" :site-stats-error="siteStatsError" />
    </template>

    <!-- 右侧图表区 -->
    <template #right-panel>
      <!-- 参数选择 + 统计摘要 -->
      <div class="top-bar">
        <ParamSelector
          :params="params"
          v-model:selected-param="localSelectedParam"
          @prev="prevParam"
          @next="nextParam"
        />
        <div class="top-bar-right">
          <StatsSummary :stat-cards="statCards" />
          <el-tag
            v-if="qqResult && showQQPlot"
            :type="qqResult.is_normal ? 'success' : 'danger'"
            size="small"
            class="normality-tag"
          >
            {{ qqResult.is_normal ? '正态' : '非正态' }}
          </el-tag>
        </div>
      </div>

      <!-- 图表：QQ图激活时上下布局 -->
      <div
        v-if="showQQPlot && chartMode === 'distribution' && histResult"
        class="chart-vertical-layout"
      >
        <div class="chart-wrapper chart-wrapper--top">
          <HistogramChart
            :result="histResult"
            :chart-config="chartConfig"
            :range-type="rangeType"
            :bar-width-percent="barWidthPercent"
            :selected-param="localSelectedParam"
          />
        </div>
        <div class="chart-wrapper chart-wrapper--bottom">
          <QQPlotChart
            :file-id="props.fileId"
            :param="localSelectedParam"
            :visible="showQQPlot"
            :result="qqResult"
            :loading="qqLoading"
          />
        </div>
      </div>
      <!-- 图表：默认全宽布局 -->
      <div v-else class="chart-wrapper">
        <HistogramChart
          v-if="histResult && chartMode === 'distribution'"
          :result="histResult"
          :chart-config="chartConfig"
          :range-type="rangeType"
          :bar-width-percent="barWidthPercent"
          :selected-param="localSelectedParam"
        />
        <SerialChart
          v-if="chartMode === 'serial'"
          :data="serialDistData"
        />
      </div>
    </template>
  </AnalysisTabLayout>
</template>
```

- [ ] **Step 2: Add import for AnalysisTabLayout**

In the `<script setup>` section, add the import (after existing imports):

```typescript
import AnalysisTabLayout from './AnalysisTabLayout.vue'
```

- [ ] **Step 3: Remove the now-unused inline layout styles**

Remove the following CSS rules from the `<style scoped>` section (they are now in `AnalysisTabLayout`):
- `.toolbar`
- `.main-row`
- `.left-panel`
- `.right-panel`

Keep the following styles (they are specific to SingleParamTab):
- `.single-param-tab`
- `.top-bar`, `.top-bar-right`, `.top-bar > *:first-child`, `.top-bar > *:last-child`
- `.normality-tag`
- `.chart-wrapper`, `.chart-wrapper > *`, `.chart-wrapper--bottom`
- `.chart-vertical-layout`

- [ ] **Step 4: Verify the page renders correctly**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

Start dev server and verify the SingleParamTab renders identically to before.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/components/SingleParamTab.vue
git commit -m "refactor(analysis): SingleParamTab uses shared AnalysisTabLayout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Refactor BoxPlotSection to Three-Layer Layout

**Files:**
- Modify: `frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue`

- [ ] **Step 1: Rewrite BoxPlotSection template**

Replace the entire content of `BoxPlotSection.vue`:

```vue
<!-- frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue -->
<template>
  <AnalysisTabLayout :loading="loading">
    <!-- 工具栏：分组模式切换 -->
    <template #toolbar>
      <el-radio-group v-model="groupBy" size="small">
        <el-radio-button value="">不分组</el-radio-button>
        <el-radio-button value="site">按 Site 分组</el-radio-button>
        <el-radio-button value="bin">按 Bin 分组</el-radio-button>
      </el-radio-group>
      <el-button
        type="primary"
        size="small"
        :loading="loading"
        :disabled="selectedParams.length === 0"
        @click="loadData"
      >
        生成箱线图
      </el-button>
    </template>

    <!-- 左侧面板：参数选择 + 说明 -->
    <template #left-panel>
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">选择参数（可多选）</label>
        <el-select
          v-model="selectedParams"
          multiple
          filterable
          placeholder="选择要分析的参数"
          style="width: 100%"
          :disabled="loading"
        >
          <el-option
            v-for="param in availableParams"
            :key="param"
            :label="param"
            :value="param"
          />
        </el-select>
      </el-card>

      <el-collapse>
        <el-collapse-item title="箱线图说明" name="info">
          <ul class="info-list">
            <li>箱体表示数据的四分位数范围（Q1-Q3）</li>
            <li>箱体中的线表示中位数</li>
            <li>须（whiskers）延伸到 1.5×IQR 范围内的最大/最小值</li>
            <li>红色点表示异常值（outliers）</li>
          </ul>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- 右侧面板：图表 -->
    <template #right-panel>
      <!-- 无数据时的空状态 -->
      <el-empty
        v-if="!loading && !boxPlotData"
        description="请选择参数并点击生成箱线图"
      />

      <!-- 图表列表 -->
      <div v-if="boxPlotData && !loading" class="boxplot-list">
        <div
          v-for="param in Object.keys(boxPlotData)"
          :key="param"
          class="boxplot-item"
        >
          <div class="boxplot-item__header">
            <strong>{{ param }}</strong>
            <span v-if="boxPlotData[param]?.overall" class="boxplot-stats">
              Min: {{ boxPlotData[param].overall.min?.toFixed(4) }}
              | Q1: {{ boxPlotData[param].overall.q1?.toFixed(4) }}
              | Median: {{ boxPlotData[param].overall.median?.toFixed(4) }}
              | Q3: {{ boxPlotData[param].overall.q3?.toFixed(4) }}
              | Max: {{ boxPlotData[param].overall.max?.toFixed(4) }}
              | Outliers: {{ boxPlotData[param].overall.outliers?.length ?? 0 }}
            </span>
          </div>
          <div class="chart-wrapper">
            <BoxPlotChart :data="{ param, ...boxPlotData[param] }" :title="`Box Plot - ${param}`" />
          </div>
        </div>
      </div>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import AnalysisTabLayout from '../AnalysisTabLayout.vue'
import BoxPlotChart from '../BoxPlotChart.vue'
import { useBoxPlot } from '../../composables/useBoxPlot'

const props = defineProps<{
  fileId: number | null
  availableParams: string[]
}>()

const selectedParams = ref<string[]>([])
const groupBy = ref<string>('')

const { loading, boxPlotData, loadBoxPlot } = useBoxPlot(
  () => props.fileId,
  selectedParams,
  groupBy
)

function loadData() {
  loadBoxPlot()
}

// Auto-select first param when params change
watch(() => props.availableParams, (newParams) => {
  if (newParams.length > 0 && selectedParams.value.length === 0) {
    selectedParams.value = [newParams[0]]
  }
}, { immediate: true })

// Reset when file changes
watch(() => props.fileId, () => {
  boxPlotData.value = null
  selectedParams.value = []
})
</script>

<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

.info-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.boxplot-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.boxplot-item__header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}

.boxplot-item__header strong {
  font-size: 14px;
  color: var(--text-primary);
}

.boxplot-stats {
  font-size: 12px;
  color: var(--text-secondary);
}

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-secondary, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}
</style>
```

- [ ] **Step 2: Verify compilation**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue
git commit -m "refactor(analysis): BoxPlotSection uses three-layer AnalysisTabLayout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Refactor CorrelationToolsTab to Three-Layer Layout

**Files:**
- Modify: `frontend/src/pages/analysis/components/CorrelationToolsTab.vue`
- Modify: `frontend/src/pages/analysis/components/CorrelationPanel.vue` (remove card wrapper)
- Modify: `frontend/src/pages/analysis/components/correlation/ParameterCorrelationSection.vue` (simplify)

- [ ] **Step 1: Rewrite CorrelationToolsTab template**

Replace the entire content of `CorrelationToolsTab.vue`:

```vue
<!-- frontend/src/pages/analysis/components/CorrelationToolsTab.vue -->
<template>
  <AnalysisTabLayout :loading="corrLoading">
    <!-- 工具栏 -->
    <template #toolbar>
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button value="scatter">散点图</el-radio-button>
        <el-radio-button value="matrix">相关性矩阵</el-radio-button>
      </el-radio-group>
      <el-button
        v-if="viewMode === 'scatter'"
        type="primary"
        size="small"
        :loading="corrLoading"
        :disabled="!localX || !localY"
        @click="onAnalyze"
      >
        分析相关性
      </el-button>
      <el-button
        v-if="viewMode === 'matrix'"
        type="primary"
        size="small"
        :loading="matrixLoading"
        @click="onCalculateMatrix"
      >
        计算相关性矩阵
      </el-button>
    </template>

    <!-- 左侧面板 -->
    <template #left-panel>
      <!-- 散点图模式 -->
      <template v-if="viewMode === 'scatter'">
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label">X 轴测试项</label>
          <el-select v-model="localX" placeholder="选择 X 轴参数" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-card>
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label">Y 轴测试项</label>
          <el-select v-model="localY" placeholder="选择 Y 轴参数" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-card>

        <!-- 坐标轴范围设置 -->
        <el-card v-if="corrResult" shadow="hover" :body-style="{ padding: '12px' }">
          <el-collapse v-model="axisCollapse" style="border: none">
            <el-collapse-item title="坐标轴范围设置" name="axis">
              <div class="axis-body">
                <div class="axis-item">
                  <label class="axis-label">X轴</label>
                  <el-select v-model="axisModeX" size="small" style="width: 95px">
                    <el-option label="数据分布" value="data" />
                    <el-option label="西格玛" value="sigma" />
                    <el-option label="自定义" value="custom" />
                  </el-select>
                  <el-select v-if="axisModeX === 'sigma'" v-model="sigmaX" size="small" style="width: 65px; margin-left: 6px">
                    <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
                  </el-select>
                  <template v-if="axisModeX === 'custom'">
                    <el-input-number v-model="customMinX" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                    <span style="margin: 0 3px">~</span>
                    <el-input-number v-model="customMaxX" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                  </template>
                </div>
                <div class="axis-item">
                  <label class="axis-label">Y轴</label>
                  <el-select v-model="axisModeY" size="small" style="width: 95px">
                    <el-option label="数据分布" value="data" />
                    <el-option label="西格玛" value="sigma" />
                    <el-option label="自定义" value="custom" />
                  </el-select>
                  <el-select v-if="axisModeY === 'sigma'" v-model="sigmaY" size="small" style="width: 65px; margin-left: 6px">
                    <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
                  </el-select>
                  <template v-if="axisModeY === 'custom'">
                    <el-input-number v-model="customMinY" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                    <span style="margin: 0 3px">~</span>
                    <el-input-number v-model="customMaxY" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                  </template>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <p class="hint-text">计算所有含 Limit 测试项的 Pearson 相关系数矩阵</p>
        </el-card>
      </template>
    </template>

    <!-- 右侧面板 -->
    <template #right-panel>
      <!-- 散点图模式 -->
      <template v-if="viewMode === 'scatter'">
        <div v-if="corrResult" class="top-bar">
          <div class="metric-card">
            <div class="metric-label">Pearson r</div>
            <div class="metric-value" :class="rColorClass">{{ (corrResult?.pearson_r ?? 0).toFixed(4) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">数据点数</div>
            <div class="metric-value">{{ (corrResult?.n ?? 0).toLocaleString() }}</div>
          </div>
        </div>
        <div class="chart-wrapper">
          <div v-if="corrResult" ref="scatterChartRef" class="chart-inner" />
          <el-empty v-else description="选择 X/Y 轴参数后点击分析相关性" />
        </div>
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <div class="chart-wrapper">
          <div v-if="matrixData" ref="matrixChartRef" class="chart-inner" />
          <el-empty v-else description="点击按钮计算所有有 Limit 测试项的 Pearson 相关系数矩阵" />
        </div>
      </template>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import AnalysisTabLayout from './AnalysisTabLayout.vue'
import { useCorrelation } from '../composables/useCorrelation'
import { useCorrelationMatrix } from '../composables/useCorrelationMatrix'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const { colors } = useEChartsTheme()

// View mode
const viewMode = ref<'scatter' | 'matrix'>('scatter')

// ===== Scatter mode =====
const localX = ref('')
const localY = ref('')
const axisCollapse = ref<string[]>([])
const axisModeX = ref<'data' | 'sigma' | 'custom'>('data')
const axisModeY = ref<'data' | 'sigma' | 'custom'>('data')
const sigmaX = ref(3); const sigmaY = ref(3)
const customMinX = ref(0); const customMaxX = ref(0)
const customMinY = ref(0); const customMaxY = ref(0)

const { corrLoading, corrResult, loadCorrelation } = useCorrelation(() => props.fileId)

const SITE_COLORS = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0']

const rColorClass = computed(() => {
  const r = Math.abs(corrResult.value?.pearson_r ?? 0)
  if (r > 0.7) return 'r-strong'
  if (r > 0.4) return 'r-medium'
  return 'r-weak'
})

function onAnalyze() {
  if (localX.value && localY.value) loadCorrelation(localX.value, localY.value)
}

function computeRange(mode: string, sigma: number, cMin: number, cMax: number, vals: number[]) {
  if (mode === 'custom') return { min: cMin, max: cMax }
  if (mode === 'sigma') {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length
    const s = Math.sqrt(vals.reduce((sum, v) => sum + (v - m) ** 2, 0) / vals.length)
    return { min: m - sigma * s, max: m + sigma * s }
  }
  const dMin = Math.min(...vals), dMax = Math.max(...vals)
  const rng = dMax > dMin ? dMax - dMin : 1
  return { min: dMin - rng / 2, max: dMax + rng / 2 }
}

function buildScatterOption() {
  if (!corrResult.value) return {}
  const tc = colors.value.textColor
  const d = corrResult.value
  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][] }, idx: number) => ({
      name: sd.name, type: 'scatter', data: sd.data, symbolSize: 6,
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length], opacity: 0.6 },
    }),
  )
  const allX: number[] = [], allY: number[] = []
  for (const sd of d.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const xR = allX.length > 0 ? computeRange(axisModeX.value, sigmaX.value, customMinX.value, customMaxX.value, allX) : { min: undefined, max: undefined }
  const yR = allY.length > 0 ? computeRange(axisModeY.value, sigmaY.value, customMinY.value, customMaxY.value, allY) : { min: undefined, max: undefined }

  return {
    title: { text: `${d.param_x} vs ${d.param_y}`, subtext: `Pearson r = ${d.pearson_r?.toFixed(4) ?? '-'}`, left: 'center', textStyle: { color: tc, fontSize: 14 }, subtextStyle: { color: tc, fontSize: 12 } },
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.seriesName}<br/>${d.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${d.param_y}: ${Number(p.value[1]).toFixed(4)}` },
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    xAxis: { type: 'value', name: d.param_x, nameLocation: 'center', nameGap: 30, min: xR.min, max: xR.max, axisLabel: { color: tc }, nameTextStyle: { color: tc } },
    yAxis: { type: 'value', name: d.param_y, nameLocation: 'center', nameGap: 40, min: yR.min, max: yR.max, axisLabel: { color: tc }, nameTextStyle: { color: tc } },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  }
}

const { chartRef: scatterChartRef } = useChart(buildScatterOption, [
  () => corrResult.value,
  () => axisModeX.value, () => axisModeY.value,
  () => sigmaX.value, () => sigmaY.value,
  () => customMinX.value, () => customMaxX.value,
  () => customMinY.value, () => customMaxY.value,
])

watch(() => corrResult.value, (data) => {
  if (!data) return
  const allX: number[] = [], allY: number[] = []
  for (const sd of data.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const r4 = (v: number) => Math.round(v * 1e4) / 1e4
  if (allX.length > 0) { customMinX.value = r4(Math.min(...allX)); customMaxX.value = r4(Math.max(...allX)) }
  if (allY.length > 0) { customMinY.value = r4(Math.min(...allY)); customMaxY.value = r4(Math.max(...allY)) }
})

// ===== Matrix mode =====
const { loading: matrixLoading, matrixData, loadCorrelationMatrix } = useCorrelationMatrix(() => props.fileId)

function onCalculateMatrix() {
  loadCorrelationMatrix()
}

function buildMatrixOption() {
  if (!matrixData.value) return {}
  const tc = colors.value.textColor
  const data = matrixData.value
  const params: string[] = data.params || []
  const matrix: number[][] = data.matrix || []

  const heatmapData: [number, number, number][] = []
  for (let i = 0; i < params.length; i++) {
    for (let j = 0; j < params.length; j++) {
      heatmapData.push([i, j, matrix[i]?.[j] ?? 0])
    }
  }

  return {
    tooltip: {
      position: 'top',
      formatter: (p: any) => `${params[p.value[0]]} vs ${params[p.value[1]]}<br/>Pearson r: ${p.value[2].toFixed(4)}`,
    },
    grid: { left: '15%', right: '10%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { rotate: 45, fontSize: 10, color: tc } },
    yAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { fontSize: 10, color: tc } },
    visualMap: {
      min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: '0%',
      inRange: { color: ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#e6f598', '#abdda4', '#66c2a5', '#3288bd'] },
    },
    series: [{
      name: 'Pearson r', type: 'heatmap', data: heatmapData,
      label: { show: true, fontSize: 9, formatter: (p: any) => p.value[2].toFixed(2) },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
    }],
  }
}

const { chartRef: matrixChartRef } = useChart(buildMatrixOption, [() => matrixData.value])
</script>

<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

.hint-text {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.top-bar {
  display: flex;
  gap: 16px;
}

.metric-card {
  background: var(--bg-tertiary, #f5f7fa);
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.metric-label {
  font-size: 12px;
  color: var(--text-secondary, #909399);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary, #303133);
}

.metric-value.r-strong { color: #059669; }
.metric-value.r-medium { color: #d97706; }
.metric-value.r-weak { color: var(--text-primary, #303133); }

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-secondary, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chart-inner {
  width: 100%;
  height: 100%;
  min-height: 480px;
}

.axis-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.axis-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.axis-label {
  font-size: 13px;
  color: var(--text-secondary, #909399);
  white-space: nowrap;
  min-width: 30px;
}

:deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--text-secondary, #909399);
  border: none;
  padding: 4px 0;
}

:deep(.el-collapse-item__wrap) {
  border: none;
}

:deep(.el-collapse-item__content) {
  padding: 8px 0 0 0;
}
</style>
```

- [ ] **Step 2: Update ParameterCorrelationSection (no longer needed)**

The `ParameterCorrelationSection.vue` and `CorrelationPanel.vue` are no longer used by `CorrelationToolsTab`. They can be kept for potential reuse but are no longer imported. No changes needed to these files — they just become unused.

- [ ] **Step 3: Verify compilation**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/analysis/components/CorrelationToolsTab.vue
git commit -m "refactor(analysis): CorrelationToolsTab uses three-layer AnalysisTabLayout

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Tab Renames + Label Optimization in AnalysisPage

**Files:**
- Modify: `frontend/src/pages/analysis/AnalysisPage.vue`

- [ ] **Step 1: Rename tabs and update label**

In `AnalysisPage.vue`, make these changes:

```vue
<!-- Line 6 — BEFORE: -->
<el-form-item label="数据文件 (选择后自动加载参数列表)">

<!-- AFTER: -->
<el-form-item>
  <template #label>
    <span>选择数据文件</span>
    <span class="file-hint">选择后自动加载参数列表，各 tab 中可选择参数进行分析</span>
  </template>
```

```vue
<!-- Line 23 — BEFORE: -->
<el-tab-pane label="📊 单参数分析" name="single-param">

<!-- AFTER: -->
<el-tab-pane label="📊 单文件分析" name="single-param">
```

```vue
<!-- Line 58 — BEFORE: -->
<el-tab-pane label="🔗 相关性工具" name="correlation-tools">

<!-- AFTER: -->
<el-tab-pane label="🔗 相关性对比" name="correlation-tools">
```

- [ ] **Step 2: Add CSS for the hint text**

Add to the `<style scoped>` section:

```css
.file-hint {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 400;
  margin-left: 8px;
}
```

- [ ] **Step 3: Verify compilation**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/analysis/AnalysisPage.vue
git commit -m "feat(analysis): rename tabs and optimize file selector label

- 单参数分析 → 单文件分析
- 相关性工具 → 相关性对比
- File selector label: add hint text

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Add CircularProgress to MultiFileTab

**Files:**
- Modify: `frontend/src/pages/analysis/components/MultiFileTab.vue`

- [ ] **Step 1: Add CircularProgress to the right panel top bar**

In `MultiFileTab.vue`, add the import and component:

Add import in `<script setup>`:
```typescript
import CircularProgress from '../../../components/common/CircularProgress.vue'
```

In the template, modify the right panel top bar (around line 87-93):

```vue
<!-- BEFORE (lines 87-93): -->
<div class="top-bar">
  <ParamSelector
    :params="commonParams"
    v-model:selected-param="selectedParam"
  />
  <div class="common-hint">共有测试项：{{ commonParams.length }} 项</div>
</div>

<!-- AFTER: -->
<div class="top-bar">
  <ParamSelector
    :params="commonParams"
    v-model:selected-param="selectedParam"
  />
  <div class="common-hint">共有测试项：{{ commonParams.length }} 项</div>
  <CircularProgress :loading="loading" />
</div>
```

- [ ] **Step 2: Verify compilation**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | head -20
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/analysis/components/MultiFileTab.vue
git commit -m "feat(analysis): add CircularProgress loading indicator to MultiFileTab

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Update E2E Tests

**Files:**
- Modify: `frontend/e2e/analysis/analysis.spec.ts`

- [ ] **Step 1: Update tab name references**

In `analysis.spec.ts`, update the tab name references:

```typescript
// Line 26 — BEFORE:
await expect(page.getByRole('tab', { name: /单参数分析/ })).toBeVisible({ timeout: 20_000 })

// AFTER:
await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
```

```typescript
// Line 165 — BEFORE:
const TABS = ['晶圆图', '箱线图', '多文件分析', '相关性工具']

// AFTER:
const TABS = ['晶圆图', '箱线图', '多文件分析', '相关性对比']
```

```typescript
// Line 204 — BEFORE:
await page.getByRole('tab', { name: /相关性工具/ }).click()

// AFTER:
await page.getByRole('tab', { name: /相关性对比/ }).click()
```

```typescript
// Line 248 — BEFORE:
await page.getByRole('tab', { name: /相关性工具/ }).click()

// AFTER:
await page.getByRole('tab', { name: /相关性对比/ }).click()
```

```typescript
// Line 290 — BEFORE:
await page.getByRole('tab', { name: /相关性工具/ }).click()

// AFTER:
await page.getByRole('tab', { name: /相关性对比/ }).click()
```

- [ ] **Step 2: Add boxplot e2e test**

Add a new test section for boxplot after the wafer map tests:

```typescript
test.describe('@p1 箱线图', { tag: ['@p1', '@analysis'] }, () => {
  test('箱线图选择参数后正常展示图表', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /箱线图/ }).click()

    // 箱线图 tab 应可见
    const panel = page.locator('.el-tabs__content .el-tab-pane').filter({ visible: true }).first()
    await expect(panel).toBeVisible()

    // 等待参数列表加载
    await page.waitForTimeout(1000)

    // 点击生成箱线图按钮
    const genBtn = panel.getByRole('button', { name: /生成箱线图/ })
    if (await genBtn.isVisible().catch(() => false)) {
      const resp = page.waitForResponse(
        (r) => r.url().includes('/analysis/boxplot/') && r.status() < 500,
        { timeout: 20_000 },
      )
      await genBtn.click()
      const r = await resp
      expect(r.status(), 'boxplot API 应返回 200').toBe(200)

      // 图表应渲染
      await expect
        .poll(() => panel.locator('svg').count(), { timeout: 15_000 })
        .toBeGreaterThanOrEqual(1)
    }
  })

  test('箱线图切换分组模式', async ({ page }) => {
    await enterAnalysis(page, RECOMMENDED.analysis)
    await page.getByRole('tab', { name: /箱线图/ }).click()

    const panel = page.locator('.el-tabs__content .el-tab-pane').filter({ visible: true }).first()
    await expect(panel).toBeVisible()

    // 工具栏应有分组模式 radio
    const toolbar = panel.locator('.toolbar')
    await expect(toolbar).toBeVisible()

    // 应有三个模式按钮
    const buttons = toolbar.locator('.el-radio-button')
    await expect(buttons).toHaveCount(3)
  })
})
```

- [ ] **Step 3: Update the `enterAnalysis` function to use new tab name**

```typescript
// Line 26 — update the function:
async function enterAnalysis(page: import('@playwright/test').Page, filename?: string) {
  await gotoApp(page, '/analysis')
  await selectAnalysisFile(page, filename)
  await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
}
```

- [ ] **Step 4: Run e2e tests to verify**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx playwright test e2e/analysis/analysis.spec.ts --reporter=list 2>&1 | tail -30
```

Expected: All tests pass with the updated tab names.

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/analysis/analysis.spec.ts
git commit -m "test(analysis): update e2e tests for renamed tabs and boxplot

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run TypeScript type check**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx vue-tsc --noEmit --pretty 2>&1 | tail -20
```

Expected: No type errors.

- [ ] **Step 2: Run e2e tests**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase/frontend"
npx playwright test e2e/analysis/ --reporter=list 2>&1 | tail -30
```

Expected: All analysis e2e tests pass.

- [ ] **Step 3: Visual verification in browser**

Start the dev server and verify:
1. 单文件分析 tab — layout unchanged, all features work
2. 箱线图 tab — three-layer layout, generate boxplot works, tooltip hover works
3. 相关性对比 tab — three-layer layout, scatter mode works, matrix mode works
4. 多文件分析 tab — CircularProgress visible during loading
5. 文件选择框 — new label with hint text
6. Dark/Light theme — all new elements styled correctly

- [ ] **Step 4: Final commit if needed**

```bash
git add -A
git commit -m "chore(analysis): final adjustments for tab layout refactor

Co-Authored-By: Claude <noreply@anthropic.com>"
```
