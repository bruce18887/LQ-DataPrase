# 相关性对比页同屏布局改造 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把相关性对比 Tab 从「散点/矩阵二选一切换」改为矩阵卡+散点卡同屏常驻（对齐保守重设计原型），左栏参数选择改搜索框+chips，顺带修掉后端 p 值 round(6) 抹零的真 bug。

**Architecture:** 数据流（useCorrelation / useCorrelationMatrix / corrFlags / trimMatrixParams / store）零改动；只重构 CorrelationToolsTab.vue 模板与联动分支，新增 MatrixParamPicker.vue 子组件，matrix-option/scatter-option 两个 option 构建器各做一处小改，后端 correlation.py / computations.py 删 round。p 值精度与回归式标签修复先行（批次 3 逻辑前置为 Task 1，因为它是独立可验证的后端改动）。

**Tech Stack:** Vue 3 + Element Plus + ECharts（前端）、Django/DRF（后端）、Playwright（e2e）、unittest（后端测试）。

**Spec:** `docs/specs/2026-09-07-correlation-inline-layout-design.md`（已批准）

**硬约束（项目规则）:**
- 单文件 ≤600 行（CorrelationToolsTab.vue 现 555 行，删大于增，预计降到 ~500）
- 任何前端改动维护 dark+light 双主题（全部走 design-tokens.css 语义 token）
- `npm run build` = vue-tsc -b + vite build，是唯一有效类型门禁（R8）
- e2e 前清未钉 `LQDP_SYSTEM_CONFIG_FILE` 的残留 runserver；跑后释放 8000 端口，3000（用户 dev vite）不动
- 提交需用户授权——本计划每批次 commit 前先向用户确认

**运行环境注意:**
- 后端测试：`python manage.py test test.backend.test_xxx`（项目唯一 runner 是 unittest，禁止 pytest 风格）
- e2e 在 `frontend/` 下跑 `npx playwright test e2e/analysis/<spec> --project=P1`（workers=1 串行）

---

## Task 1: 后端 p 值精度修复（round 抹零 bug）

**Files:**
- Modify: `apps/analysis/services/data_services/correlation.py:121`（删 `round(p_value, 6)`）
- Modify: `apps/analysis/services/statistics/computations.py:183`（删 `round(val, 6)`）
- Test: `test/backend/test_correlation_scatter_pvalue.py`（追加用例）
- Test: `test/backend/test_spec_limits_and_correlation.py`（CorrelationMatrixTests 追加用例）

- [ ] **Step 1.1: 写失败测试（散点侧）**

在 `test/backend/test_correlation_scatter_pvalue.py` 的 `CorrelationPValueTests` 类末尾追加：

```python
    def test_p_not_rounded_to_zero_for_large_n(self):
        """round(p, 6) 会把大 n 的强相关 p（~1e-40）抹成 0.0——
        前端 formatPValue 的科学计数法分支永远吃不到真值，「p=0」语义错误。
        响应必须保留完整双精度（非 0、非 1、量级 <1e-10）。"""
        out = compute_correlation_scatter(self._df_xy(), 'X', 'Y')
        self.assertIsNotNone(out['p_value'])
        self.assertGreater(out['p_value'], 0.0)
        self.assertLess(out['p_value'], 1e-10)
```

（`_df_xy` 默认 n=200、noise=0.1 → r≈0.995 → p≈1e-40 数量级，round(6) 后必为 0.0，此测试在旧代码下必失败。）

- [ ] **Step 1.2: 写失败测试（矩阵侧）**

在 `test/backend/test_spec_limits_and_correlation.py` 的 `CorrelationMatrixTests` 类末尾追加：

```python
    def test_p_values_not_rounded_to_zero_for_large_n(self):
        """矩阵 p_values 同样曾被 round(6) 抹零：大 n 强相关对的真实 p
        远小于 1e-6。修后应保留完整双精度。"""
        rng = np.random.RandomState(3)
        x = rng.normal(0, 1, 200)
        df = pd.DataFrame({'A': x, 'B': x * 2 + rng.normal(0, 0.1, 200)})
        result = compute_correlation_matrix(df, ['A', 'B'])
        p01 = result['p_values'][0][1]
        self.assertIsNotNone(p01)
        self.assertGreater(p01, 0.0)
        self.assertLess(p01, 1e-10)
```

- [ ] **Step 1.3: 跑测试确认失败**

```bash
python manage.py test test.backend.test_correlation_scatter_pvalue test.backend.test_spec_limits_and_correlation
```

预期：`test_p_not_rounded_to_zero_for_large_n` 与 `test_p_values_not_rounded_to_zero_for_large_n` FAIL（`0.0 not greater than 0.0` 或 assertLess 失败），其余用例 PASS。

- [ ] **Step 1.4: 最小实现**

`correlation.py` 返回 dict 中：

```python
        # p 值保留完整双精度：round(_, 6) 会把大 n 的强相关 p（~1e-40）抹成
        # 0.0，前端 formatPValue 的科学计数法分支吃不到真值。
        'p_value': p_value if p_value is not None else None,
```

`computations.py:183` 整行替换为：

```python
    # p 值保留完整双精度（理由同 correlation.py 散点侧）：round(6) 抹零。
    p_matrix_list = [[float(val) for val in row] for row in p_values.tolist()]
```

- [ ] **Step 1.5: 跑测试确认通过**

```bash
python manage.py test test.backend.test_correlation_scatter_pvalue test.backend.test_spec_limits_and_correlation
```

预期：全部 PASS（原 5 + 新 1 = 6 项、CorrelationMatrixTests 5 项含新 1 项）。

- [ ] **Step 1.6: 全量后端回归（串行）**

```bash
python manage.py test apps.analysis
```

预期：全绿（当前基线 173+ 项）。若有失败，grep 本任务改的两个文件确认非既有失败（对照 lessons R2③/R8②）。

- [ ] **Step 1.7: Commit（先向用户确认）**

```bash
git add apps/analysis/services/data_services/correlation.py apps/analysis/services/statistics/computations.py test/backend/test_correlation_scatter_pvalue.py test/backend/test_spec_limits_and_correlation.py
git commit -m "fix(analysis): 相关性 p 值去 round(6)——大 n 强相关 p 被抹成 0.0"
```

---

## Task 2: matrix-option.ts —— visualMap 去滑块 + tooltip 回归式标签随 method

**Files:**
- Modify: `frontend/src/pages/analysis/composables/matrix-option.ts`

- [ ] **Step 2.1: visualMap.show: false**

`buildCorrelationMatrixOption` 返回对象中 `visualMap` 改为：

```ts
    visualMap: {
      min: -1, max: 1, calculable: false, orient: 'horizontal', left: 'center', bottom: '0%',
      // 对齐原型紧凑卡形态：色阶滑块藏掉（show:false），映射与色带不变
      show: false,
      inRange: { color: ramp },
    },
```

- [ ] **Step 2.2: tooltip 标签随 method**

函数体开头（`const params: string[] = ...` 之前）加：

```ts
  // Pearson r / Spearman ρ / Kendall τ：tooltip 与 series.name 不能硬编码
  // Pearson——切方法后文案就错了（method 由后端响应体回传）
  const SYMBOLS: Record<string, string> = { pearson: 'Pearson r', spearman: 'Spearman ρ', kendall: 'Kendall τ' }
  const rLabel = SYMBOLS[data.method] ?? 'r'
```

tooltip formatter 与 series name 中两处 `Pearson r` 改用 `rLabel`：

```ts
        return `${params[pi]} vs ${params[pj]}<br/>${rLabel}: ${formatR(r)}${getSignificanceStars(pv)}<br/>p-value: ${formatPValue(pv)}`
```

```ts
      name: rLabel, type: 'heatmap', data: heatmapData,
```

- [ ] **Step 2.3: 类型检查 + 构建**

```bash
cd frontend && npm run build
```

预期：exit=0（vue-tsc -b + vite build）。此文件无直接单测（纯 option 构建，行为由 e2e 覆盖）。

- [ ] **Step 2.4: Commit（先向用户确认）**

```bash
git add frontend/src/pages/analysis/composables/matrix-option.ts
git commit -m "feat(analysis): 矩阵热力图去色阶滑块 + tooltip 标签随方法"
```

---

## Task 3: MatrixParamPicker.vue 新组件

**Files:**
- Create: `frontend/src/pages/analysis/components/MatrixParamPicker.vue`

- [ ] **Step 3.1: 创建组件（完整代码）**

```vue
<!-- frontend/src/pages/analysis/components/MatrixParamPicker.vue -->
<template>
  <el-card shadow="hover" :body-style="{ padding: '12px' }" data-matrix-param-picker>
    <div class="matrix-param-header">
      <label class="section-label">选择参数（已选 {{ selected.length }}/{{ params.length }}）</label>
      <div class="matrix-param-actions">
        <el-button link type="primary" size="small" :disabled="visibleParams.length === 0" @click="selectAllVisible">全选</el-button>
        <el-button link type="primary" size="small" :disabled="selected.length === 0" @click="emit('update:selected', [])">清空</el-button>
      </div>
    </div>
    <el-input
      v-model="keyword"
      placeholder="搜索参数"
      clearable
      size="small"
      data-matrix-search
    />
    <div class="chips-box">
      <button
        v-for="p in visibleParams"
        :key="p"
        type="button"
        class="chip"
        :class="{ on: selected.includes(p) }"
        :title="p"
        @click="toggle(p)"
      >{{ p }}</button>
      <div v-if="visibleParams.length === 0" class="chips-empty">无匹配参数</div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  /** 全量候选参数（本 tab 文件的带 Limit 参数列表） */
  params: string[]
  /** 已选参数集合（v-model:selected，父组件持有真值） */
  selected: string[]
}>()

const emit = defineEmits<{
  (e: 'update:selected', value: string[]): void
}>()

const keyword = ref('')

/** 搜索只影响可见性，不改已选集合；大小写不敏感包含匹配 */
const visibleParams = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return props.params
  return props.params.filter((p) => p.toLowerCase().includes(k))
})

function toggle(p: string) {
  const next = props.selected.includes(p)
    ? props.selected.filter((x) => x !== p)
    : [...props.selected, p]
  emit('update:selected', next)
}

/** 全选 = 清空后选中当前可见全部（搜索状态下只加可见项） */
function selectAllVisible() {
  const set = new Set(props.selected)
  for (const p of visibleParams.value) set.add(p)
  emit('update:selected', [...set])
}
</script>

<style scoped>
.matrix-param-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.matrix-param-header .section-label {
  margin-bottom: 0;
}

.matrix-param-actions {
  display: flex;
  gap: 4px;
}

.section-label {
  font-size: 11px;
  color: var(--text-2);
  font-weight: 500;
  display: block;
}

.chips-box {
  margin-top: 8px;
  max-height: 180px;
  overflow-y: auto;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.chip {
  font: inherit;
  font-size: 11px;
  line-height: 1.4;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 12px;
  padding: 1px 9px;
  cursor: pointer;
  border: 1px solid var(--border-2);
  background: var(--card);
  color: var(--text-2);
}

.chip.on {
  border-color: var(--brand);
  background: var(--active-bg);
  color: var(--brand);
  font-weight: 600;
}

.chips-empty {
  font-size: 11px;
  color: var(--text-3);
  padding: 6px 2px;
}
</style>
```

设计要点（对照 spec）：
- 全部颜色走语义 token（`--text-2`/`--border-2`/`--card`/`--brand`/`--active-bg`/`--text-3`），双主题自动生效（R7①）
- 无下拉面板 → 无 popper-class 需求；e2e 锚点 `data-matrix-param-picker` + `data-matrix-search`
- 「已选 N/M」沿用现状文案格式（`已选 \d+/\d+`），`correlation-matrix-default-cap.spec.ts` 的正则解析不用改

- [ ] **Step 3.2: 类型检查**

```bash
cd frontend && npm run build
```

预期：exit=0（组件尚未被引用，属「新增未消费」，vue-tsc 不报错）。

---

## Task 4: CorrelationToolsTab.vue 同屏重构

**Files:**
- Modify: `frontend/src/pages/analysis/components/CorrelationToolsTab.vue`（模板 + script 大改，现 555 行）

- [ ] **Step 4.1: 模板重写**

整个 `<template>` 块替换为（结构：工具栏只剩文件选择器；左栏筛选+X/Y+回归线+轴卡+矩阵参数选择+方法+计算按钮；右栏矩阵卡+散点卡常驻）：

```vue
<template>
  <AnalysisTabLayout :loading="corrLoading || matrixLoading">
    <!-- 工具栏：文件选择（viewMode radio 删除） -->
    <template #toolbar>
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="correlation"
        :loading="listLoading"
      />
    </template>

    <!-- 左侧面板 -->
    <template #left-panel>
      <DataFilterSection
        scope="correlation"
        v-model:ignore-no-limit="ignoreNoLimit"
        v-model:ignore-no-test-value="ignoreNoTestValue"
        v-model:data-only-bin1="dataOnlyBin1"
        v-model:only-fail-test-item="onlyFailTestItem"
        v-model:only-low-cpk="onlyLowCpk"
        v-model:outlier-handling="outlierHandling"
        v-model:iqr-multiplier="iqrMultiplier"
      />

      <!-- 散点对选择（双入口之一，保留） -->
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">X 轴测试项</label>
        <el-select v-model="localX" placeholder="选择 X 轴参数" filterable style="width: 100%">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
        <label class="section-label" style="margin-top: 10px">Y 轴测试项</label>
        <el-select v-model="localY" placeholder="选择 Y 轴参数" filterable style="width: 100%">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
        <div style="margin-top: 10px">
          <el-switch v-model="showRegression" size="small" active-text="显示回归线" />
        </div>
      </el-card>

      <!-- 坐标轴范围设置 -->
      <CorrelationScatterAxisCard
        :show="!!corrResult"
        v-model:axis-mode-x="axisModeX"
        v-model:axis-mode-y="axisModeY"
        v-model:sigma-x="sigmaX"
        v-model:sigma-y="sigmaY"
        v-model:custom-min-x="customMinX"
        v-model:custom-min-y="customMinY"
        v-model:custom-max-x="customMaxX"
        v-model:custom-max-y="customMaxY"
      />

      <!-- 矩阵参数选择（新组件）+ 方法 + 计算按钮（按钮留左栏原位） -->
      <MatrixParamPicker :params="params" v-model:selected="selectedMatrixParams" />
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">相关系数方法</label>
        <!-- data-corr-method：e2e 契约选择器（同 data-file-picker/data-filter 惯例） -->
        <el-select v-model="method" data-corr-method style="width: 100%">
          <el-option label="Pearson（线性）" value="pearson" />
          <el-option label="Spearman（秩相关）" value="spearman" />
          <el-option label="Kendall（秩相关）" value="kendall" />
        </el-select>
      </el-card>
      <el-button
        type="primary"
        size="small"
        :loading="matrixLoading"
        :disabled="selectedMatrixParams.length < 2"
        style="width: 100%"
        @click="onCalculateMatrix"
      >
        计算相关性矩阵（{{ selectedMatrixParams.length }} 项）
      </el-button>
    </template>

    <!-- 右侧面板：矩阵卡 + 散点卡同屏常驻 -->
    <template #right-panel>
      <!-- 矩阵卡 -->
      <div class="inline-card">
        <div class="inline-card-h">
          <span>相关系数矩阵</span>
          <span class="grow"></span>
          <span v-if="matrixData" class="matrix-meta-inline">{{ matrixMeta }}</span>
        </div>
        <div class="inline-card-b">
          <div v-if="matrixData" ref="matrixChartRef" class="matrix-chart-inner" />
          <el-empty
            v-else
            description="选择参数后点击左栏「计算相关性矩阵」按钮"
            :image-size="72"
          />
        </div>
      </div>

      <!-- 散点卡 -->
      <div class="inline-card">
        <div class="inline-card-h">
          <span>散点明细<template v-if="corrResult"> · {{ corrResult.param_x }} × {{ corrResult.param_y }}</template></span>
          <span class="grow"></span>
          <template v-if="corrResult">
            <span class="head-metric" :class="rColorClass">r={{ (corrResult.pearson_r ?? 0).toFixed(4) }}<span v-if="scatterPStars" class="p-stars">{{ scatterPStars }}</span></span>
            <span class="head-metric">p={{ scatterPText }}</span>
            <span class="head-metric">n={{ (corrResult.n ?? 0).toLocaleString() }}</span>
            <span v-if="regressionInfo" class="head-metric head-eq">{{ regressionInfo.equation }}</span>
          </template>
        </div>
        <div class="inline-card-b">
          <div v-if="corrResult" ref="scatterChartRef" class="scatter-chart-inner" />
          <ErrorBanner
            v-else-if="corrError"
            :message="corrError"
            title="相关性数据加载失败"
            @retry="reloadCorrelation"
          />
          <el-empty v-else description="选择 X/Y 轴参数或点击矩阵格以分析相关性" :image-size="72" />
        </div>
        <div v-if="sampledText" class="sample-note">{{ sampledText }}</div>
      </div>

      <OutlierHintBar
        v-if="corrResult"
        :mode="outlierHandling"
        :outlier-info="corrResult?.x_outlier_info ?? null"
      />
      <OutlierHintBar
        v-if="corrResult"
        :mode="outlierHandling"
        :outlier-info="corrResult?.y_outlier_info ?? null"
      />
    </template>
  </AnalysisTabLayout>
</template>
```

- [ ] **Step 4.2: script 调整**

按序在 `<script setup>` 中做以下修改（其余逻辑——corrFlags/useTabFileParams/watch 群/trimMatrixParams/MATRIX_DEFAULT_MAX/watch(fileId) 清空——全部保留不动）：

a) import 区新增 / 删除：

```ts
import MatrixParamPicker from './MatrixParamPicker.vue'
```

（`useEChartsTheme`、`getChartRenderer`、`minMax`、`getSiteColors8`、`buildCorrelationMatrixOption`、`formatPValue`、`getSignificanceStars`、`buildCorrelationScatterOption`、`linearRegression`、`CorrelationScatterAxisCard`、`ErrorBanner`、`useChart`、`useCorrelation`、`useCorrelationMatrix`、`useTabFileParams`、`OutlierHintBar` 全部保留。）

b) 删除 `viewMode` 相关：

```ts
// 删除：const viewMode = ref<'scatter' | 'matrix'>('scatter')
```

c) 散点卡头指标 computed（放 `scatterPText` 定义之后）：

```ts
// 抽样注记：后端 n 是降采样前全量口径（correlation.py n = len(common_idx)），
// 已画点数 = 各 series data 长度和；N < M 才显示「抽样 N/M 点」
const sampledText = computed(() => {
  if (!corrResult.value) return ''
  const drawn = (corrResult.value.series_data || []).reduce(
    (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0)
  const total = corrResult.value.n ?? 0
  return drawn < total ? `抽样 ${drawn.toLocaleString()}/${total.toLocaleString()} 点` : ''
})
```

d) 矩阵联动 click 回调：删掉 `viewMode.value = 'scatter'` 一行，注释同步改：

```ts
watch(matrixChartInstance, (chart) => {
  if (!chart) return
  chart.off('click')
  chart.on('click', (p: any) => {
    if (p?.componentType !== 'series') return
    const [i, j, r] = (p.value ?? []) as [number, number, number | null]
    if (i === j || r == null) return
    const list: string[] = matrixData.value?.params || []
    const x = list[i]
    const y = list[j]
    if (!x || !y) return
    localX.value = x
    localY.value = y
  })
})
```

e) `matrixMeta` 保留不动（文案已对齐原型）。

f) `buildMatrixOption` 保留不动（Task 2 已在 matrix-option.ts 内改）。

- [ ] **Step 4.3: style 块替换**

`<style scoped>` 整块替换为（KPI 卡样式全删，新增两张同屏卡样式；全部语义 token）：

```css
<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-2);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

/* 同屏双卡（对齐原型 .chart/.chart-h/.chart-b 结构） */
.inline-card {
  background: var(--card);
  border: 1px solid var(--border-2);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.inline-card-h {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  background: var(--bg-3);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.inline-card-h .grow { flex: 1; }

.inline-card-b {
  padding: 6px;
  min-height: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.matrix-chart-inner,
.scatter-chart-inner {
  width: 100%;
  height: 480px;
}

/* 卡头一行指标（badge/note 规格） */
.head-metric {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
  color: var(--text);
  white-space: nowrap;
}

.head-metric.r-strong { color: var(--success); }
.head-metric.r-medium { color: var(--warn); }
.head-metric.r-weak { color: var(--text-2); }

.p-stars {
  color: var(--warn);
  font-size: 11px;
  margin-left: 1px;
}

.head-eq {
  font-weight: 500;
  color: var(--text-2);
}

.matrix-meta-inline {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sample-note {
  padding: 2px 10px 6px;
  font-size: 11px;
  color: var(--text-3);
}
</style>
```

- [ ] **Step 4.4: 行数自检（硬约束 600 行）**

```bash
grep -c "" frontend/src/pages/analysis/components/CorrelationToolsTab.vue
```

预期：< 600。若超：把「X/Y 下拉 + 回归线开关」卡拆为 `CorrelationPairPicker.vue` 子组件（模板 ~30 行 + 无逻辑），再复检。

- [ ] **Step 4.5: 构建**

```bash
cd frontend && npm run build
```

预期：exit=0。常见失败点：漏删的 `viewMode` 引用（vue-tsc 会报 TS2304）。

---

## Task 5: e2e 迁移与新增

**Files:**
- Modify: `frontend/e2e/analysis/correlation-matrix-linkage.spec.ts`（重写为同屏断言）
- Modify: `frontend/e2e/analysis/correlation-matrix-default-cap.spec.ts`（选择器迁移）
- Modify: `frontend/e2e/analysis/correlation-file-switch-reset.spec.ts`（metric-card → 卡头指标）
- Create: `frontend/e2e/analysis/correlation-inline.spec.ts`（新组件/卡头/抽样注记用例）

前置（lessons 2026-09-05/09-03）：检查并清掉未钉 `LQDP_SYSTEM_CONFIG_FILE` 的残留 runserver 进程树再跑。

- [ ] **Step 5.1: 重写 correlation-matrix-linkage.spec.ts**

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 同屏布局下的矩阵格 → 散点轻联动 + 方法下拉（2026-09-07 同屏改造）。
 *
 * 1. 矩阵卡与散点卡同屏常驻（无 radio 切换）；
 * 2. 点非对角格 → 散点卡就地更新（不发视图切换，散点请求 X/Y == 所点格）；
 * 3. 对角格（恒 1）点击不响应；
 * 4. 方法下拉切 Spearman 重算 → meta 行显示方法名。
 */

const MATRIX_CARD = '.inline-card:has(.matrix-chart-inner)'
const SCATTER_CARD = '.inline-card:has(.scatter-chart-inner)'
const MATRIX_CONTAINER = `${MATRIX_CARD} div[_echarts_instance_]`

test.describe('@p2 相关性同屏点格联动', { tag: ['@p2', '@analysis'] }, () => {
  test('同屏常驻；点非对角格就地更新散点；对角格不响应；方法下拉生效', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    await waitLoadingGone(page)

    // 同屏：两卡都在（无 radio）
    await expect(page.locator(MATRIX_CARD)).toBeVisible({ timeout: 20_000 })
    await expect(page.locator(SCATTER_CARD)).toBeVisible()
    await expect(page.locator('.el-radio-button')).toHaveCount(0)

    const container = page.locator(MATRIX_CONTAINER).first()
    await expect(container).toBeVisible({ timeout: 20_000 })

    // 从实例读格心像素（convertToPixel 对类目轴吃类目名）
    const info = await container.evaluate((el: any) => {
      const inst = el.__echartsInstance__
      const params: string[] = inst.getOption().xAxis[0].data
      return {
        params,
        diagPx: inst.convertToPixel({ seriesIndex: 0 }, [params[0], params[0]]),
        pairPx: inst.convertToPixel({ seriesIndex: 0 }, [params[0], params[1]]),
      }
    })
    const [xName, yName] = [info.params[0], info.params[1]]
    expect(xName, '矩阵应至少有 2 个参数').toBeTruthy()
    expect(yName).toBeTruthy()
    const box = await container.boundingBox()
    expect(box, '矩阵容器应有布局尺寸').not.toBeNull()

    // 1) 对角格 [0,0] 不响应：散点卡头无指标
    await page.mouse.click(box!.x + info.diagPx[0], box!.y + info.diagPx[1])
    await expect(page.locator(`${SCATTER_CARD} .head-metric`)).toHaveCount(0)

    // 2) 非对角格 [0,1] → 散点就地加载该对（同屏，无视图切换）
    const corrP = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.mouse.click(box!.x + info.pairPx[0], box!.y + info.pairPx[1])
    const resp = await corrP
    const body = resp.request().postDataJSON()
    expect(body.param_x, '散点请求 X 应等于所点格行参数').toBe(xName)
    expect(body.param_y, '散点请求 Y 应等于所点格列参数').toBe(yName)

    const layout = page.locator('.analysis-tab-layout:visible')
    await expect(layout.locator(`${SCATTER_CARD} .head-metric`).first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator(SCATTER_CARD)).toContainText(`n=`)
    // X/Y select 显示该对参数
    await expect(layout.locator('.el-select').filter({ hasText: xName }).first()).toBeVisible()
    await expect(layout.locator('.el-select').filter({ hasText: yName }).first()).toBeVisible()

    // 3) 方法下拉：切 Spearman 重算 → meta 行显示方法（请求体也带 method）
    await page.locator('[data-corr-method]').click()
    await page.locator('.el-select-dropdown__item:visible').filter({ hasText: 'Spearman' }).first().click()
    const matrixP = page.waitForResponse(
      (r) => r.url().includes('/statistics/correlation_matrix/') && r.request().method() === 'POST',
      { timeout: 25_000 },
    )
    await page.getByRole('button', { name: /计算相关性矩阵/ }).click()
    const mResp = await matrixP
    expect((mResp.request().postDataJSON() as Record<string, unknown>).method).toBe('spearman')
    await waitLoadingGone(page)
    await expect(page.locator('.matrix-meta-inline')).toContainText('spearman')
  })
})
```

注意与旧版的差异：无 `MATRIX_RADIO`；对角格断言从「停留矩阵视图」改为「散点卡头无指标」；`data-corr-method` 不再需要 `.el-tab-pane:visible` 前缀限定（不再有二分模板，全页仅此一个实例）。

- [ ] **Step 5.2: 迁移 correlation-matrix-default-cap.spec.ts**

两处：① 删掉 `.el-radio-button` 切换行（radio 已不存在，左栏矩阵参数卡常驻）；② `HEADER` 定位器改 `.matrix-param-header .section-label`（新组件里类名保留，无需变）但限定容器 `[data-matrix-param-picker]` 防跨组件同名：

```ts
const HEADER = '[data-matrix-param-picker] .matrix-param-header .section-label'
```

删除行：

```ts
    await page.locator('.el-radio-button').filter({ hasText: '相关性矩阵' }).first().click()
```

- [ ] **Step 5.3: 迁移 correlation-file-switch-reset.spec.ts**

`.metric-card` 断言全部改卡头指标（`.head-metric`），空态描述改新文案：

```ts
    // 旧文件结果已展示
    await expect(layout.locator('.head-metric').first()).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator('.scatter-chart-inner')).toBeVisible()
```

```ts
    // 指标与散点清空，回到空态提示
    await expect(layout.locator('.head-metric')).toHaveCount(0)
    await expect(layout.locator('.scatter-chart-inner')).toHaveCount(0)
    await expect(
      layout.locator('.el-empty').filter({ hasText: '选择 X/Y 轴参数或点击矩阵格以分析相关性' }),
    ).toBeVisible()
```

- [ ] **Step 5.4: 新建 correlation-inline.spec.ts（新组件 + 卡头 + 抽样注记）**

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 同屏改造新增能力（2026-09-07）：
 * 1. MatrixParamPicker：搜索过滤 chips / 点选取消 / 全选作用可见项 / 默认 12；
 * 2. 散点卡头一行指标：r 值星标 + p + n + 回归式；
 * 3. 抽样注记：仅当已画点数 < n 时出现「抽样 N/M 点」。
 */

const PICKER = '[data-matrix-param-picker]'
const SCATTER_CARD = '.inline-card:has(.scatter-chart-inner)'

test.describe('@p2 相关性同屏新增能力', { tag: ['@p2', '@analysis'] }, () => {
  test('参数搜索/chips 选择 + 散点卡头指标行', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)

    const picker = page.locator(PICKER)
    await expect(picker).toBeVisible({ timeout: 15_000 })

    // 1) chips 渲染且默认前 12 选中（与 correlation-matrix-default-cap 同语义，
    //    该文件参数 >12 时可断言恰好 12；不足 12 个文件本用例 skip 由 cap spec 覆盖）
    const chips = picker.locator('.chip')
    const chipCount = await chips.count()
    expect(chipCount, 'chips 应渲染当前文件参数列表').toBeGreaterThan(0)
    const onCount = await picker.locator('.chip.on').count()
    expect(onCount, '默认选中数 = min(12, 参数总数)').toBe(Math.min(12, chipCount))

    // 2) 搜索过滤：输入必中前缀（推荐文件首个参数）→ chips 收缩；点一个未选 chip → 已选 +1
    const firstParam = (await chips.first().textContent())!.trim()
    await picker.locator('[data-matrix-search]').fill(firstParam)
    await expect(picker.locator('.chip')).toHaveCount(1)
    const before = await picker.locator('.chip.on').count()
    await picker.locator('.chip').first().click()
    await expect(picker.locator('.chip.on')).toHaveCount(before + 1)

    // 3) 清空按钮作用于真实选择（计数回 0，计算按钮 disabled）
    await picker.getByRole('button', { name: '清空' }).click()
    await expect(picker.locator('.chip.on')).toHaveCount(0)
    await expect(page.getByRole('button', { name: /计算相关性矩阵/ })).toBeDisabled()

    // 4) 搜索空态
    await picker.locator('[data-matrix-search]').fill('___no_such_param___')
    await expect(picker.locator('.chips-empty')).toBeVisible()
    await picker.locator('[data-matrix-search]').fill('')

    // 5) 散点卡头指标行：选 X/Y（helpers/elplus.pickOption 走占位文本）
    const layout = page.locator('.analysis-tab-layout:visible')
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await page.locator('.el-select').filter({ hasText: '选择 X 轴参数' }).click()
    await page.locator('.el-select-dropdown__item:visible').first().click()
    await page.waitForTimeout(600)
    await page.locator('.el-select').filter({ hasText: '选择 Y 轴参数' }).click()
    await page.locator('.el-select-dropdown__item:visible').nth(1).click()
    await respPromise

    const head = layout.locator(`${SCATTER_CARD} .inline-card-h`)
    await expect(head.locator('.head-metric').filter({ hasText: 'r=' })).toBeVisible({ timeout: 15_000 })
    await expect(head.locator('.head-metric').filter({ hasText: 'p=' })).toBeVisible()
    await expect(head.locator('.head-metric').filter({ hasText: /^n=/ })).toBeVisible()
    // 回归线默认开 → 回归式（y=…）出现
    await expect(head.locator('.head-eq')).toBeVisible()
    // 卡头出现「散点明细 · X × Y」
    await expect(head).toContainText(/散点明细 · .+ × .+/)
  })

  test('抽样注记：已画点数 < n 时显示「抽样 N/M 点」', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await page.getByRole('tab', { name: /相关性对比/ }).click()
    // 大数据文件才触发降采样（DOWN_SAMPLE_THRESHOLD 之后才裁点）；无大文件时 skip
    await pickTabFile(page, 'correlation', RECOMMENDED.analysis)
    const layout = page.locator('.analysis-tab-layout:visible')
    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/correlation/') && r.request().method() === 'POST' && r.status() < 500,
      { timeout: 25_000 },
    )
    await page.locator('.el-select').filter({ hasText: '选择 X 轴参数' }).click()
    await page.locator('.el-select-dropdown__item:visible').first().click()
    await page.waitForTimeout(600)
    await page.locator('.el-select').filter({ hasText: '选择 Y 轴参数' }).click()
    await page.locator('.el-select-dropdown__item:visible').nth(1).click()
    const resp = (await respPromise).json()
    const n = resp.n as number
    const drawn = (resp.series_data as { data: unknown[] }[]).reduce((s, sd) => s + sd.data.length, 0)
    test.skip(drawn >= n, `该文件未触发降采样（drawn=${drawn}, n=${n}），抽样注记用例不适用`)

    await expect(layout.locator(`${SCATTER_CARD} .sample-note`)).toBeVisible({ timeout: 15_000 })
    await expect(layout.locator(`${SCATTER_CARD} .sample-note`)).toContainText('抽样')
  })
})
```

- [ ] **Step 5.5: 跑相关性 e2e 子集**

```bash
cd frontend
npx playwright test e2e/analysis/correlation-matrix-linkage.spec.ts e2e/analysis/correlation-matrix-default-cap.spec.ts e2e/analysis/correlation-file-switch-reset.spec.ts e2e/analysis/correlation-inline.spec.ts --project=P1 --workers=1
```

预期：全绿（抽样注记用例在无降采样文件环境 skip 属正常）。失败先按 R2③ 分辨 4xx 数据层 vs UI 层。

- [ ] **Step 5.6: 存量引用复查**

```bash
grep -rn "metric-card\|el-radio-button\|viewMode" frontend/e2e/analysis/correlation-*.spec.ts
grep -rn "metric-card" frontend/src/pages/analysis
```

预期：第一组无匹配（相关性三个 spec 已迁完）；第二组无匹配（KPI 卡删净）。`viewMode` 在全前端 src 的残留引用一并 grep 确认为 0。

---

## Task 6: 全量验证 + 双主题截图 + 收尾

**Files:**
- 无新改动；纯验证批次（问题回修在所属 Task 内完成后再回到本任务）

- [ ] **Step 6.1: 后端全量（串行）**

```bash
python manage.py test test.backend apps
```

预期：OK（基线 857+1 新增；skip 数与基线一致）。

- [ ] **Step 6.2: 分析页 e2e 定向回归**

```bash
cd frontend
npx playwright test e2e/analysis --project=P1 --workers=1
```

预期：除基线存量失败（lessons 2026-09-05 记录组：boxplot-bool-params×2、file-switch-param-reset 超时类）外全绿；新增/迁移用例全绿。若 `tab-request-fanout`/`tab-independent-files` 受 radio 删除影响，按新语义修正断言后复跑。

- [ ] **Step 6.3: 浏览器双主题实测**

用 browser-use MCP（或手动 dev）走查 `/analysis` → 相关性对比 Tab：
1. light/night 两主题下：矩阵卡/散点卡/chips/卡头指标对比度与配色正常（chip 选中态 `--active-bg` 两主题可见）；
2. 点矩阵格 → 下方散点更新；X/Y 下拉选择 → 散点更新（双入口）；
3. 切 Spearman 重算 → meta 行与 tooltip 前缀变化；
4. 截图留档 `test/screenshots_night/corr_inline_{light,night}.png`。

- [ ] **Step 6.4: 端口释放确认**

```bash
netstat -ano | findstr :8000
```

预期：无 LISTENING（e2e 自起后端已退出）；3000（用户 dev vite）保持不动。

- [ ] **Step 6.5: 收尾提交 + 文档回写（先向用户确认提交）**

- `docs/tasks/todo.md` 追加本任务段（实施清单 + Review：验证账目、踩坑、遗留）
- `docs/tasks/lessons.md` 若有新踩坑则追加（无则不动）
- 最终 commit（含 todo 回写）：

```bash
git add docs/tasks/todo.md
git commit -m "docs(tasks): 相关性同屏改造任务记录与验证账目"
```

---

## 计划自审（writing-plans Self-Review）

1. **Spec 覆盖**：决策 1 同屏→Task 4；决策 2 双入口→Task 4.1 模板 + Task 5.1 断言；决策 3 卡头一行→Task 4.1/4.3；决策 4 搜索+chips→Task 3；决策 5 去滑块→Task 2.1；决策 6 手动按钮→Task 4.1（按钮留左栏）；决策 7 抽样注记→Task 4.2c + Task 5.4；决策 8 直接落地→本计划即执行序。spec「批次 3」p 值精度→Task 1。回归式标签随 method 是 spec 批次 3 的组成部分→Task 2.2。✅
2. **占位符**：所有代码块完整；无 TBD/「适当处理」。✅
3. **类型一致性**：`selectedMatrixParams`（父持有）/ `v-model:selected`（子 emit `update:selected`）签名一致；`matrixMeta`/`scatterPText`/`scatterPStars`/`rColorClass`/`regressionInfo`/`sampledText` 与模板引用一致；e2e 契约属性 `data-matrix-param-picker`/`data-matrix-search`/`data-corr-method` 前后一致。✅

一处刻意偏离 writing-plans 默认：计划文件放 `docs/superpowers/plans/`（skill 默认），项目 specs 在 `docs/specs/`——两处并存不冲突，plan 生命周期短不入库。
