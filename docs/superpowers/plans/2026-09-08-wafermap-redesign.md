# 晶圆图页面对齐保守重设计原型 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-09-08-wafermap-redesign-design.md`（方案 B）把晶圆图 tab 改造为：着色 4 档 + 分区独立 checkbox、左栏两表（分区良率/该片统计）、自动结论条、die 尺寸真实化、Edge/Notch 标签语义修正；保持单文件单图。

**Architecture:** 后端仅在 `wafer_map` 响应补逐点 `value` 与 `spec_low/spec_high` 两个字段（复用 `resolve_spec_limits`）；归一与结论生成全在前端。`WaferMapPanel.vue` 重排为「toolbar 盒（不动）→ 控制工具条 → 左栏 25% 两表 / 右栏 75% 图 + 结论条」，`buildOption` 按 colorBy×zoneMode 分支构建 series。e2e 用 `data-wafer-*` 契约属性定位。

**Tech Stack:** Django DRF + pandas（后端）；Vue 3 `<script setup>` + Pinia 子 store + ECharts（前端）；unittest（Django runner，串行）+ Playwright（e2e）。

**项目硬约束（执行者必读）：**
- 任何 Vue/Python 单文件 ≤600 行；测试文件放 test/backend 或 apps/*/tests_*.py；e2e 在 frontend/e2e/。
- 前端改动维护 dark+light 双主题：组件只认 `var(--token)`；ECharts option 里的颜色取 `useEChartsTheme()` 的 JS 语义色（`colors.value.successColor` 等），**不解析** CSS 变量与 color-mix。
- 完成前验证：`npm run build`（在 frontend/ 下，等价 vue-tsc -b + vite）+ `manage.py test apps.analysis`（串行）+ e2e（跑前确认 8000 端口占用者是 Playwright 自起或无占用；跑完释放端口）。
- 每个任务结束即 commit（R1）。提交信息沿用仓库风格 `type(scope): 中文摘要`。

---

## 文件结构总览

| 文件 | 动作 | 职责 |
|---|---|---|
| `apps/analysis/services/data_services/wafer_map.py` | 修改 | `compute_wafer_map_data` 增加逐点 `value` |
| `apps/analysis/views/analysis_views.py` | 修改 | `wafer_map` 视图下发 `spec_low/spec_high` |
| `apps/analysis/tests_wafer_map_points.py` | 修改 | 补 value 字段断言（TDD 先行） |
| `apps/analysis/tests_batch4_contract.py` | 修改 | 补 spec_low/high 下发断言 |
| `frontend/src/pages/analysis/components/WaferMapPanel.vue` | 重写 | 布局改造 + 着色分支 + 结论条 |
| `frontend/src/pages/analysis/components/WaferStatTables.vue` | 新建 | 左栏两张表（两表逻辑独立成件，控行数） |
| `frontend/e2e/analysis/wafermap-redesign.spec.ts` | 新建 | 着色 4 档/分区叠加/参数值着色/两表一致性/结论条 |
| `frontend/e2e/analysis/wafermap-hidden-tab-init.spec.ts` | 修改 | 「Total Dies」定位器迁到左栏统计表 |
| `frontend/e2e/analysis/wafermap-model-not-found.spec.ts` | 修改 | 同上（3 处） |
| `frontend/e2e/analysis/tab-independent-files.spec.ts` | 修改 | 「Total Dies」→ 左栏统计表 |
| `frontend/e2e/README.md` | 修改 | 补 `data-wafer-*` 契约章节 |
| `docs/tasks/todo.md` | 修改 | 任务清单落册 |

组件拆分决策：`WaferMapPanel.vue` 现有 317 行，加布局模板/着色分支/结论条预计 500+ 行。把「两张统计表」（纯展示、props 进 computed 出）拆到 `WaferStatTables.vue`，主文件控制在 ~430 行，两件各自单一职责。

---

### Task 1: 后端 TDD——wafer_map 逐点 value 字段

**Files:**
- Modify: `apps/analysis/tests_wafer_map_points.py`
- Modify: `apps/analysis/services/data_services/wafer_map.py:102-146`

- [ ] **Step 1: 写失败测试**

在 `apps/analysis/tests_wafer_map_points.py` 的 `WaferMapPointsShapeTests` 类末尾（`test_duplicate_columns_do_not_yield_dataframe_rows` 之后）追加：

```python
    def test_param_selected_adds_pointwise_value(self):
        """选中判定参数时逐点补 value（参数值着色的数据源）。"""
        df = pd.DataFrame({
            'X_COORD': [0.0, 10.0, 20.0],
            'Y_COORD': [0.0, 10.0, 20.0],
            'Site': ['1', '1', '1'],
            'P1': [1.0, -5.0, 3.0],
        })
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['value'] for p in out['points']], [1.0, -5.0, 3.0])

    def test_value_nan_points_omit_field(self):
        """参数列 NaN/非数值的点省略 value 字段（前端归入「无值」灰档）。"""
        df = pd.DataFrame({
            'X_COORD': [0.0, 10.0, 20.0],
            'Y_COORD': [0.0, 10.0, 20.0],
            'Site': ['1', '1', '1'],
            'P1': [1.0, None, 'abc'],
        })
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual(out['points'][0]['value'], 1.0)
        self.assertNotIn('value', out['points'][1])
        self.assertNotIn('value', out['points'][2])

    def test_no_param_omits_value(self):
        """未选参数（全局判定）不下发 value——省 payload。"""
        df = pd.DataFrame({
            'X_COORD': [0.0, 10.0], 'Y_COORD': [0.0, 10.0],
            'Site': ['1', '1'], 'P1': [1.0, 2.0],
        })
        out = compute_wafer_map_data(df, _meta(), None, 'result', 'X_COORD', 'Y_COORD')
        for p in out['points']:
            self.assertNotIn('value', p)

    def test_value_ignores_color_by(self):
        """value 与 color_by 解耦：选参数时无论着色模式都下发。"""
        df = pd.DataFrame({
            'X_COORD': [0.0, 10.0], 'Y_COORD': [0.0, 10.0],
            'Site': ['1', '2'], 'P1': [1.0, 2.0],
        })
        out = compute_wafer_map_data(df, _meta(), 'P1', 'site', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['value'] for p in out['points']], [1.0, 2.0])

    def test_value_index_aligns_with_coords_mask(self):
        """坐标被剔除的行不产生点，value 不得错位（掩码对齐）。"""
        df = pd.DataFrame({
            'X_COORD': [0.0, np.nan, 20.0],
            'Y_COORD': [0.0, 10.0, 20.0],
            'Site': ['1', '1', '1'],
            'P1': [1.0, 99.0, 3.0],
        })
        out = compute_wafer_map_data(df, _meta(), 'P1', 'result', 'X_COORD', 'Y_COORD')
        self.assertEqual([p['value'] for p in out['points']], [1.0, 3.0])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase
python manage.py test apps.analysis.tests_wafer_map_points -v 2
```

预期：新增 5 个用例 FAIL（`KeyError: 'value'` 或断言失败），存量 10 个 PASS。

- [ ] **Step 3: 最小实现**

修改 `apps/analysis/services/data_services/wafer_map.py` 的 `compute_wafer_map_data`。

在 `bin_col = get_bin_column(df, metadata)`（现 :115）之后加一行：

```python
    # 参数值着色数据源：选中判定参数时逐点取值（与 xs/ys 同一掩码，NaN 不下发）。
    # 无论 color_by 都取——着色分支是前端职责，后端只管给数据。
    param_vals = (pd.to_numeric(get_1d_from(df, param), errors='coerce').to_numpy(dtype='float64', copy=False)
                  if param else None)
```

在 `for i in np.flatnonzero(valid):` 循环内 `statuses = ...` 使用处之后（`point['bin']` 赋值块之后、`point['site']` 赋值块之前均可，保持顺序一致即可——推荐放在 `point['bin']` 块后）加：

```python
        if param_vals is not None:
            v = param_vals[i]
            if math.isfinite(v):
                point['value'] = float(v)
```

注意：文件头部已 `import math`（:3），无需新增 import。

- [ ] **Step 4: 跑测试确认通过**

```bash
python manage.py test apps.analysis.tests_wafer_map_points -v 2
```

预期：15 个用例全 PASS（含性能守卫 `test_50k_rows_build_under_two_seconds`）。

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/services/data_services/wafer_map.py apps/analysis/tests_wafer_map_points.py
git commit -m "feat(analysis): wafer_map 逐点下发判定参数 value 字段（参数值着色数据源）"
```

---

### Task 2: 后端 TDD——视图下发 spec_low/spec_high

**Files:**
- Modify: `apps/analysis/tests_batch4_contract.py`（`WaferMapParamGuardTests` 类）
- Modify: `apps/analysis/views/analysis_views.py:238-273`

- [ ] **Step 1: 写失败测试**

在 `apps/analysis/tests_batch4_contract.py` 的 `WaferMapParamGuardTests` 类末尾追加：

```python
    def test_param_response_carries_spec_limits(self):
        """参数值着色归一口径的数据源：真规格限原样下发；'Min'/'Max' 占位 → null。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df, _meta(mins={'Param0': '0'}, maxs={'Param0': '10'}))
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1, 'param': 'Param0',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data['spec_low'], 0.0)
        self.assertEqual(response.data['spec_high'], 10.0)

    def test_placeholder_limits_serialize_to_null(self):
        """'Min'/'Max' 占位列（无规格限）→ spec_low/high 为 null（JSON null）。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df, _meta(mins={'Param0': 'Min'}, maxs={'Param0': 'Max'}))
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1, 'param': 'Param0',
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data['spec_low'])
        self.assertIsNone(response.data['spec_high'])

    def test_no_param_spec_fields_still_present(self):
        """未选参数时字段也在（统一契约，前端不用判键存在）。"""
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({
            'X_COORD': [0, 1, 0, 1], 'Y_COORD': [0, 0, 1, 1],
            'Param0': [1.0, 2.0, 1.5, 2.5], 'SW_Bin': [1, 1, 2, 1],
        })
        self._patch_and_track(df)
        factory, force_authenticate = _make_request_factory()
        request = _authed(factory.post('/api/v1/analysis/wafer_map/', {
            'file_id': 1,
        }, format='json'), force_authenticate)
        view = AnalysisViewSet.as_view({'post': 'wafer_map'})
        response = view(request)
        response.render()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.data['spec_low'])
        self.assertIsNone(response.data['spec_high'])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.analysis.tests_batch4_contract.WaferMapParamGuardTests -v 2
```

预期：新增 3 个用例 FAIL（`KeyError: 'spec_low'`），存量 2 个 PASS。

- [ ] **Step 3: 最小实现**

修改 `apps/analysis/views/analysis_views.py`：

imports 处（:19 的 statistics import 块内，按字母序加一行）：

```python
from apps.analysis.services.statistics import (
    compute_correlation_matrix,
    ...
    resolve_spec_limits,
)
```

`wafer_map` 视图的 `return Response(clean_data({...}))`（:266-273）改为：

```python
        # 参数值着色的归一口径由前端做（有真规格限按 LSL→USL、否则按数据范围），
        # 这里只下发原始规格限：'Min'/'Max' 占位等「无规格限」语义经
        # resolve_spec_limits 统一为 None（JSON null），前端不用再判占位符。
        spec_low, spec_high = resolve_spec_limits(metadata, param) if param else (None, None)

        return Response(clean_data({
            'file_id': datafile.id,
            'x_col': x_col,
            'y_col': y_col,
            'points': wm['points'],
            'stats': wm['stats'],
            'wafer': wm['wafer'],
            'spec_low': spec_low,
            'spec_high': spec_high,
        }))
```

- [ ] **Step 4: 跑测试确认通过**

```bash
python manage.py test apps.analysis.tests_batch4_contract tests_wafer_map_points -v 2 --failfast
```

注：`tests_batch4_contract` 需带 `apps.analysis.` 前缀——正确命令：

```bash
python manage.py test apps.analysis.tests_batch4_contract apps.analysis.tests_wafer_map_points -v 2
```

预期：全 PASS。

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/views/analysis_views.py apps/analysis/tests_batch4_contract.py
git commit -m "feat(analysis): wafer_map 响应补 spec_low/spec_high（无规格限为 null）"
```

---

### Task 3: 前端组件——WaferStatTables.vue（左栏两表）

**Files:**
- Create: `frontend/src/pages/analysis/components/WaferStatTables.vue`

- [ ] **Step 1: 创建组件（纯展示，无测试框架——e2e 在 Task 6 钉行为）**

```vue
<template>
  <div class="wafer-stat-tables">
    <!-- 分区良率：zonal_yield 三区常驻表（非分区模式也展示，数字口径与图同源） -->
    <div class="stat-card" data-wafer-zone-table>
      <div class="stat-card-h">分区良率</div>
      <table class="stat-table">
        <thead>
          <tr><th>环带</th><th class="n">Die</th><th class="n">Pass</th><th class="n">Yield</th></tr>
        </thead>
        <tbody>
          <tr v-for="z in zones" :key="z.name">
            <td>{{ z.name }}</td>
            <td class="n">{{ z.total }}</td>
            <td class="n">{{ z.pass }}</td>
            <td class="n" :class="zoneYieldClass(z.yield)">{{ fmtYield(z.yield) }}</td>
          </tr>
          <tr v-if="!zones.length">
            <td colspan="4" class="stat-empty">{{ zoneError || '暂无分区数据' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 该片统计：stats + wafer 几何（坐标列/die_size 后端已下发） -->
    <div class="stat-card" data-wafer-stat-table>
      <div class="stat-card-h">该片统计</div>
      <table class="stat-table">
        <tbody>
          <tr><td>总 die</td><td class="n">{{ stats?.total ?? '-' }}</td></tr>
          <tr><td>Pass</td><td class="n">{{ stats?.pass_count ?? '-' }}</td></tr>
          <tr><td>Fail</td><td class="n" :class="{ 'val-fail': (stats?.fail_count ?? 0) > 0 }">{{ stats?.fail_count ?? '-' }}</td></tr>
          <tr><td>良率</td><td class="n">{{ fmtYield(stats?.yield_pct ?? null) }}</td></tr>
          <tr><td>坐标列</td><td class="n">{{ coordCols }}</td></tr>
          <tr><td>die 尺寸</td><td class="n">{{ dieSize }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  zones: { name: string; total: number; pass: number; fail: number; yield: number | null }[]
  zoneError?: string
  stats: { total?: number; pass_count?: number; fail_count?: number; yield_pct?: number | null } | null
  xCol?: string
  yCol?: string
  dieSize?: number | null
}>()

const coordCols = computed(() =>
  props.xCol && props.yCol ? `${props.xCol} / ${props.yCol}` : '-')

const dieSize = computed(() =>
  props.dieSize != null && Number.isFinite(props.dieSize) ? String(props.dieSize) : '-')

function fmtYield(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return `${v.toFixed(1)}%`
}

/* 预览稿口径：≥99.6% 绿、否则警示色；None（空区）不着色 */
function zoneYieldClass(v: number | null): Record<string, boolean> {
  if (v == null || !Number.isFinite(v)) return {}
  return { 'val-good': v >= 99.6, 'val-warn': v < 99.6 }
}
</script>

<style scoped>
.stat-card {
  background: var(--card);
  border: 1px solid var(--border-2);
  border-radius: 6px;
  overflow: hidden;
}
.stat-card-h {
  padding: 7px 10px;
  background: var(--bg-3);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.stat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.stat-table th,
.stat-table td {
  padding: 5px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
}
.stat-table th {
  color: var(--text-2);
  font-weight: 500;
  background: var(--bg-3);
}
.stat-table td.n,
.stat-table th.n {
  text-align: right;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.stat-table tbody tr:last-child td { border-bottom: 0; }
.stat-empty {
  color: var(--text-2);
  font-size: 11.5px;
}
.val-good { color: var(--success); }
.val-warn { color: var(--warn); }
.val-fail { color: var(--error); font-weight: 600; }
</style>
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

预期：vue-tsc + vite 全绿（组件未被引用也不报错——如报「未使用」告警可忽略，Task 4 接线后消失；若 tsconfig noUnusedLocals 报错，此处组件是独立文件不受影响）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/analysis/components/WaferStatTables.vue
git commit -m "feat(analysis): 新增晶圆图左栏两表组件（分区良率/该片统计）"
```

---

### Task 4: 前端改造——WaferMapPanel.vue 布局与着色重写

**Files:**
- Modify: `frontend/src/pages/analysis/components/WaferMapPanel.vue`（全文重写）

- [ ] **Step 1: 重写组件**

完整替换为（结构分五块：toolbar 盒不动 / 控制工具条 / 左栏两表+右栏图 / buildOption 着色分支 / 结论条）：

```vue
<template>
  <div>
    <!-- 顶部 toolbar 盒：文件选择行（与单文件/相关性同位）。
         晶圆图不吃任何筛选（wafer_map 不读筛选字段），故无筛选行。 -->
    <div class="dp-analysis-toolbar wafer-toolbar">
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="wafer"
        :loading="listLoading"
      />
      <span class="wafer-note">
        本图按全部 die 的 Pass/Fail 判定，数据筛选不影响本图；
        可选参数取自直方图的测试项列表。
      </span>
    </div>

    <!-- 控制工具条：着色 4 档 + 边界/分区开关 + 高度 + 加载（预览稿形态） -->
    <div class="wafer-controls">
      <span class="ctl-label">着色</span>
      <el-radio-group
        v-model="localColorBy"
        data-wafer-color
        size="small"
        @change="onLoad"
      >
        <el-radio-button value="result">判定结果</el-radio-button>
        <el-radio-button value="site">Site</el-radio-button>
        <el-radio-button value="bin">Bin</el-radio-button>
        <el-radio-button value="param">参数值</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="localShowEdge" @change="onReRender">边界圆+Notch</el-checkbox>
      <el-checkbox v-model="localZoneMode" @change="onReRender">分区模式</el-checkbox>
      <span class="ctl-spacer" />
      <span class="ctl-label">高度</span>
      <input v-model.number="localHeight" type="range" class="height-range" min="400" max="900" step="50" />
      <span class="height-val">{{ localHeight }}</span>
      <el-button type="primary" @click="onLoad" :loading="waferLoading">加载晶圆图</el-button>
    </div>

    <!-- 缺坐标列等错误：展示提示而非静默空白 -->
    <el-alert
      v-if="waferError"
      :title="waferError"
      type="error"
      show-icon
      :closable="false"
      class="wafer-error-alert"
      style="margin-bottom: 12px"
    />
    <ErrorBanner
      v-if="zonalError"
      :message="zonalError"
      title="分区良率加载失败"
      @retry="fetchZonalYield"
    />

    <div class="wafer-body">
      <!-- 左栏 25%：两张常驻统计表 -->
      <div class="wafer-left">
        <WaferStatTables
          :zones="zonalData?.zones ?? []"
          :zone-error="zonalError"
          :stats="waferData?.stats ?? null"
          :x-col="waferData?.x_col"
          :y-col="waferData?.y_col"
          :die-size="waferData?.wafer?.die_size ?? null"
        />
      </div>

      <!-- 右栏 75%：晶圆图卡 + 自动结论条 -->
      <div class="wafer-right">
        <el-card body-style="padding: 8px">
          <div ref="chartRef" :style="{ height: localHeight + 'px' }" />
          <div v-if="paramFallbackNote" class="wafer-fallback-note">{{ paramFallbackNote }}</div>
        </el-card>
        <div v-if="conclusion" class="wafer-conclusion" data-wafer-conclusion>{{ conclusion }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWaferTabStore } from '../../../stores/analysisTabs'
import type { DataFile } from '../../../types'
import { useChart } from '../../../composables/useChart'
import { useTabFileParams } from '../composables/useTabFileParams'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import { getSiteColors8 } from '../../../utils/chart-bar'
import { formatError } from '../../../utils/error'
import { analysisApi } from '../../../api/analysis'
import AnalysisFilePicker from './AnalysisFilePicker.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import WaferStatTables from './WaferStatTables.vue'

const props = defineProps<{ files: DataFile[] }>()
const { colors, isDark } = useEChartsTheme()

// 文件与参数列表是本 tab 自己的（`wafer_map` 不读任何筛选字段，且
// `data_only_bin1` 会把 fail die 全抹掉 → 拉参数列表时不带开关）
const { fileId, params, loading: listLoading } = storeToRefs(useWaferTabStore())
useTabFileParams({
  ctx: { fileId, params, loading: listLoading },
  files: computed(() => props.files),
})

// 判定参数可选：不入 store，换文件/换列表后若已不在候选集里就回到「无」
const localParam = ref('')
watch(params, (list) => {
  if (localParam.value && !list.includes(localParam.value)) localParam.value = ''
})
const localColorBy = ref('result')
const localZoneMode = ref(false)
const localHeight = ref(550)
const localShowEdge = ref(true)
const zonalData = ref<any>(null)
const zonalError = ref('')

// 晶圆图数据（此前挂在 AnalysisPage 上，随文件选择一起下放到本 tab）
const waferData = ref<any>(null)
const waferError = ref<string | null>(null)
const waferLoading = ref(false)

// 「参数值」着色降级注记（value 全空或 spec 退化时给图例级提示，不弹横幅）
const paramFallbackNote = ref('')

// 缺坐标列等错误走 axios 抛错路径（后端 400），不再静默空白。
// 两条数据通道各自维护「最新请求」序号：裸 await 无守卫时，切文件/快速连点
// 后在途旧响应会把旧文件的晶圆图/分区数据写回（2026-09-05 审查 M2）；
// waferLoading 由最新请求独占管理，先完成的一方不再熄灭在途方的加载态。
// loadWafer/loadWaferGlobal 同写 waferData 共用 waferLoadSeq；
// fetchZonalYield 写 zonalData，是独立通道，单独计数（不能与晶圆图互斥）。
let waferLoadSeq = 0
let zonalLoadSeq = 0

async function loadWafer() {
  if (!fileId.value) return
  const mySeq = ++waferLoadSeq
  const reqFileId = fileId.value
  waferLoading.value = true
  try {
    const payload: any = { file_id: reqFileId, color_by: localColorBy.value }
    if (localParam.value) payload.param = localParam.value
    const { data } = await analysisApi.postWaferMap(payload)
    if (mySeq !== waferLoadSeq || fileId.value !== reqFileId) return
    if (data.error) {
      // 防御旧后端 200 错误载荷
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    if (mySeq !== waferLoadSeq) return
    waferError.value = formatError(e)
  } finally {
    if (mySeq === waferLoadSeq) waferLoading.value = false
  }
}

// 换文件后旧数据不再属于当前选择，直接清掉防止误读
watch(fileId, () => {
  waferData.value = null
  waferError.value = null
  zonalData.value = null
})

/**
 * Pass/Fail/分区/参数值渐变色（双主题）。night 经 CVD 色盲模拟验证：
 * Pass 蓝 #4facfe / Fail 橙 #ff9f43 为主色对（protan+deutan ΔE≥18），
 * 分区 绿/金/粉 与主色对全部 ΔE≥15；light 保持原值。
 */
const waferColors = computed(() => isDark.value
  ? { pass: '#4facfe', fail: '#ff9f43', zoneCenter: '#38ef7d', zoneMid: '#fdd835', zoneEdge: '#fb7185' }
  : { pass: '#2ECC71', fail: '#E74C3C', zoneCenter: '#2ECC71', zoneMid: '#F39C12', zoneEdge: '#E74C3C' })

/* 「参数值」着色的归一区间与口径注记（双口径自适应，spec 见 2026-09-08 §后端改动）：
   有真规格限 → LSL→USL 归一；无 → 数据 min→max 归一；LSL==USL 退化 → 数据口径兜底 */
const paramScale = computed(() => {
  const d = waferData.value
  if (!d) return null
  const vals: number[] = (d.points || [])
    .map((p: any) => p.value)
    .filter((v: any) => typeof v === 'number' && Number.isFinite(v))
  if (!vals.length) return null
  let lo: number | null = d.spec_low ?? null
  let hi: number | null = d.spec_high ?? null
  let bySpec = lo != null && hi != null && hi > lo
  if (!bySpec) {
    lo = Math.min(...vals)
    hi = Math.max(...vals)
    bySpec = false
    if (hi <= lo) return null // 全同值：渐变无意义，走降级
  }
  const label = bySpec
    ? '按规格限 LSL→USL 归一'
    : (d.spec_low != null || d.spec_high != null ? '按数据范围归一（规格限退化）' : '按数据范围归一（该参数无规格限）')
  return { lo: lo as number, hi: hi as number, label }
})

function getZoneYield(name: string): number | null {
  const zone = zonalData.value?.zones?.find((z: any) => z.name === name)
  return zone && Number.isFinite(zone.yield) ? zone.yield : null
}
function getZoneStat(name: string, key: string): string | number {
  const zone = zonalData.value?.zones?.find((z: any) => z.name === name)
  return zone ? (zone[key] ?? '-') : '-'
}

/* 自动结论条（预览稿口径）：三区都有数据才出结论；<0.5pp 判无径向梯度 */
const conclusion = computed(() => {
  const zones = zonalData.value?.zones
  if (!zones?.length || zones.length !== 3) return ''
  const yields = zones.map((z: any) => z.yield)
  if (yields.some((y: any) => y == null || !Number.isFinite(y))) return ''
  const lo = Math.min(...yields), hi = Math.max(...yields)
  const span = hi - lo
  const spanText = `三环带良率 ${lo.toFixed(1)}% ~ ${hi.toFixed(1)}%，极差 ${span.toFixed(1)} 个百分点`
  return span < 0.5
    ? `${spanText} → 无径向梯度，失效集中在特定 Site/Bin 分裂（可切单文件 tab 看 Site 分层）。`
    : `${spanText} → 存在径向梯度，可按环带下钻。`
})

async function fetchZonalYield() {
  if (!fileId.value) return
  const mySeq = ++zonalLoadSeq
  const reqFileId = fileId.value
  const reqParam = localParam.value
  zonalError.value = ''
  try {
    const { data } = await analysisApi.getZonalYield(reqFileId, reqParam || undefined)
    if (mySeq !== zonalLoadSeq || fileId.value !== reqFileId || localParam.value !== reqParam) return
    zonalData.value = data
  } catch (e) {
    if (mySeq !== zonalLoadSeq) return
    zonalError.value = formatError(e, '分区良率加载失败')
    zonalData.value = null
  }
}

/* 左栏分区表是常驻的：选文件/换判定参数后拉一次（原来只在勾选分区时发） */
function onLoad() {
  loadWafer()
  fetchZonalYield()
}
function onReRender() { /* triggers watch via ref change */ }

// 上万 die 时逐点 SVG rect 是主要卡顿源（与相关性散点同阈值）：强制 canvas
// + large，小晶圆图行为零变更
const isLarge = computed(() => ((waferData.value?.points?.length) ?? 0) >= 5000)

/* die 方块尺寸：按真实 die_size 与坐标 span 的比例换算（预览稿口径，下限 1.6px）。
   旧实现写死 [8,8]，小 die 晶圆挤成一团、大 die 晶圆缝隙过宽 */
const dieSymbolSize = computed(() => {
  const wafer = waferData.value?.wafer
  if (!wafer?.die_size || !waferData.value?.points?.length) return [8, 8]
  const pts = waferData.value.points
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
  for (const p of pts) {
    if (p.x < x0) x0 = p.x
    if (p.x > x1) x1 = p.x
    if (p.y < y0) y0 = p.y
    if (p.y > y1) y1 = p.y
  }
  const span = Math.max(x1 - x0, y1 - y0) || 1
  // 图表数据区约 600px 高（localHeight 550 减去 title/legend/grid 边距），
  // die 在数据坐标下的尺寸 ≈ die_size，换算成像素 ≈ die_size / span * 600
  const px = Math.max(1.6, (wafer.die_size / span) * 600 * 0.86)
  return [px, px]
})

function buildOption() {
  if (!waferData.value) return {}
  const tc = colors.value.textColor
  const data = waferData.value
  const pts: any[] = data.points || []
  const wafer = data.wafer
  const colorBy = localColorBy.value
  const series: any[] = []
  const largeOpts = isLarge.value ? { large: true } : {}
  const sym = { symbol: 'rect', symbolSize: dieSymbolSize.value }
  paramFallbackNote.value = ''

  if (localZoneMode.value && wafer) {
    /* 分区模式（独立 checkbox，覆盖着色）：按 die 距心半径落 1/3·2/3 环带 */
    const cx = wafer.center_x, cy = wafer.center_y, r = wafer.radius
    const bounds = [r / 3, (r * 2) / 3]
    const zoneDefs = [
      { name: '中心区', color: waferColors.value.zoneCenter, upper: bounds[0] },
      { name: '中间区', color: waferColors.value.zoneMid, upper: bounds[1] },
      { name: '边缘区', color: waferColors.value.zoneEdge, upper: Infinity },
    ]
    if (cx != null && cy != null && r > 0) {
      const buckets = new Map<string, any[]>()
      for (const p of pts) {
        const d = Math.hypot(p.x - cx, p.y - cy)
        const zd = zoneDefs.find((z) => d <= z.upper)!
        if (!buckets.has(zd.name)) buckets.set(zd.name, [])
        buckets.get(zd.name)!.push(toPt(p))
      }
      for (const zd of zoneDefs) {
        series.push({
          name: zd.name, type: 'scatter', ...sym, ...largeOpts,
          data: buckets.get(zd.name) ?? [], itemStyle: { color: zd.color, opacity: 0.9 },
        })
      }
      // 1/3·2/3 虚线环（预览稿形态）
      for (const k of [1 / 3, 2 / 3]) {
        const ringPts: number[][] = []
        for (let i = 0; i < 120; i++) {
          const a = (2 * Math.PI * i) / 120
          ringPts.push([cx + r * k * Math.cos(a), cy + r * k * Math.sin(a)])
        }
        series.push({
          name: `环带 ${k.toFixed(2)}R`, type: 'scatter', symbol: 'circle', symbolSize: 1.5,
          data: ringPts.map((pt) => ({ value: pt })), itemStyle: { color: tc, opacity: 0.5 },
          silent: true, z: 1,
        })
      }
    }
  } else if (colorBy === 'param' && paramScale.value) {
    /* 参数值着色：单系列 + continuous visualMap（绿→红）；NaN 值灰档「无值」 */
    const scale = paramScale.value
    const withVal: any[] = [], noVal: any[] = []
    for (const p of pts) {
      const t = typeof p.value === 'number' && Number.isFinite(p.value)
        ? Math.max(0, Math.min(1, (p.value - scale.lo) / (scale.hi - scale.lo)))
        : null
      ;(t == null ? noVal : withVal).push(toPt(p, t))
    }
    if (!withVal.length) {
      // 全 NaN：该档降级回落 Pass/Fail（spec §错误处理），图内给注记
      paramFallbackNote.value = '所选参数在坐标有效点上无有效值，已回落判定结果着色'
      pushResultSeries(series, pts, sym, largeOpts)
    } else {
      series.push({
        name: localParam.value || '参数值', type: 'scatter', ...sym, ...largeOpts,
        data: withVal, itemStyle: { opacity: 0.9 },
      })
      if (noVal.length) {
        series.push({
          name: '无值', type: 'scatter', ...sym, ...largeOpts,
          data: noVal, itemStyle: { color: '#9ca3af', opacity: 0.9 },
        })
      }
    }
  } else if (colorBy === 'param') {
    // 请求里没带逐点值（如旧缓存响应）：回落
    paramFallbackNote.value = '所选参数在坐标有效点上无有效值，已回落判定结果着色'
    pushResultSeries(series, pts, sym, largeOpts)
  } else if (colorBy === 'bin' && pts.some((p: any) => p.bin != null)) {
    /* Bin 着色：按 bin 分组复用 8 色板（>8 组循环取色） */
    const binMap = new Map<string, any[]>()
    for (const p of pts) {
      const g = p.bin == null ? '无 Bin' : String(p.bin)
      if (!binMap.has(g)) binMap.set(g, [])
      binMap.get(g)!.push(toPt(p))
    }
    const palette = getSiteColors8(isDark.value)
    Array.from(binMap.keys())
      .sort((a, b) => (Number(a) - Number(b)) || a.localeCompare(b))
      .forEach((binName, idx) => {
        series.push({
          name: `Bin ${binName}`, type: 'scatter', ...sym, ...largeOpts,
          data: binMap.get(binName)!, itemStyle: { color: palette[idx % 8], opacity: 0.9 },
        })
      })
  } else if (colorBy === 'site' && pts.some((p: any) => p.color_group)) {
    const siteMap = new Map<string, any[]>()
    for (const p of pts) {
      const g = p.color_group || 'Unknown'
      if (!siteMap.has(g)) siteMap.set(g, [])
      siteMap.get(g)!.push(toPt(p))
    }
    Array.from(siteMap.keys()).sort().forEach((siteName, idx) => {
      series.push({
        name: siteName, type: 'scatter', ...sym, ...largeOpts,
        data: siteMap.get(siteName)!,
        itemStyle: { color: getSiteColors8(isDark.value)[idx % 8], opacity: 0.9 },
      })
    })
  } else {
    pushResultSeries(series, pts, sym, largeOpts)
  }

  if (wafer && localShowEdge.value && !localZoneMode.value) {
    const cx = wafer.center_x, cy = wafer.center_y, r = wafer.radius
    if (cx != null && cy != null && r > 0) {
      const circlePoints: number[][] = []
      for (let i = 0; i < 200; i++) {
        const a = (2 * Math.PI * i) / 200
        circlePoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
      }
      series.push({ name: 'Wafer Edge', type: 'scatter', symbol: 'circle', symbolSize: 1, data: circlePoints.map((pt) => ({ value: pt })), itemStyle: { color: '#B0BEC5', borderColor: '#78909C', borderWidth: 1.5 }, silent: true, z: 0 })
      const notchPoints: number[][] = []
      for (let i = 0; i < 20; i++) {
        const a = Math.PI / 2 - 0.02 + (0.04 * i) / 19
        notchPoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
      }
      series.push({ name: 'Notch', type: 'scatter', symbol: 'circle', symbolSize: 1, data: notchPoints.map((pt) => ({ value: pt })), itemStyle: { color: '#90A4AE' }, silent: true, z: 0 })
    }
  }

  const stats = data.stats || {}
  const yieldRate = pts.length > 0 ? ((100 * (stats.pass_count || 0)) / pts.length).toFixed(1) : '0.0'
  const option: any = {
    // 上万 symbol 的入场/更新动画是纯开销，大晶圆直接关掉
    animation: !isLarge.value,
    title: { text: 'Wafer Map', subtext: `Total: ${pts.length} | Yield: ${yieldRate}%`, left: 'center' },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (!p.value || !Array.isArray(p.value)) return p.name
        const d = p.data
        let h = `<b>${d.status || p.seriesName}</b><br/>X: ${p.value[0]} | Y: ${p.value[1]}<br/>`
        if (d.serial != null) h += `Serial: ${d.serial}<br/>`
        if (d.bin != null) h += `Bin: ${d.bin}<br/>`
        if (d.site != null) h += `Site: ${d.site}<br/>`
        return h
      },
      backgroundColor: colors.value.tooltipBg, borderColor: colors.value.tooltipBorder, textStyle: { color: colors.value.tooltipText },
      extraCssText: 'box-shadow:0 2px 8px rgba(0,0,0,0.15);border-radius:4px;padding:8px 12px;',
    },
    legend: { data: series.map((s: any) => s.name), bottom: 10, type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { title: '保存', pixelRatio: 2 }, dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 },
    grid: { left: 50, right: 60, top: 60, bottom: 50 },
    xAxis: { type: 'value', name: data.x_col ?? 'X', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    yAxis: { type: 'value', name: data.y_col ?? 'Y', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, start: 0, end: 100 }, { type: 'slider', yAxisIndex: 0, start: 0, end: 100 }, { type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
    series,
  }
  if (colorBy === 'param' && paramScale.value && !localZoneMode.value) {
    const scale = paramScale.value
    option.visualMap = {
      show: false, min: 0, max: 1, calculable: false,
      inRange: { color: [colors.value.successColor, colors.value.warnColor, colors.value.errorColor] },
      // dimension 2 = toPt 塞进 value[2] 的归一值
      dimension: 2,
      seriesIndex: 0,
    }
  }
  return option
}

function toPt(p: any, normalized?: number) {
  const base = { value: [p.x, p.y, ...(normalized != null ? [normalized] : [])], serial: p.serial, bin: p.bin, site: p.site, status: p.status }
  return base
}

function pushResultSeries(series: any[], pts: any[], sym: any, largeOpts: any) {
  series.push({ name: 'Pass', type: 'scatter', ...sym, ...largeOpts, data: pts.filter((p: any) => p.status === 'Pass').map((p: any) => toPt(p)), itemStyle: { color: waferColors.value.pass, opacity: 0.9 } })
  series.push({ name: 'Fail', type: 'scatter', ...sym, ...largeOpts, data: pts.filter((p: any) => p.status === 'Fail').map((p: any) => toPt(p)), itemStyle: { color: waferColors.value.fail, opacity: 0.95 } })
}

const { chartRef } = useChart(
  buildOption,
  [waferData, localShowEdge, localColorBy, localZoneMode, zonalData],
  'chartRef',
  () => (isLarge.value ? 'canvas' : getChartRenderer()),
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
/* 晶圆图 toolbar 盒：选择器定宽，说明文字占余宽换行 */
.wafer-toolbar {
  flex-wrap: wrap;
}
.wafer-toolbar > .dp-analysis-filepicker {
  flex: 0 0 360px;
  min-width: 240px;
}

/* 晶圆图不吃数据筛选的例外说明（与左栏筛选区同屏时防用户误以为会影响本图） */
.wafer-note {
  font-size: 12px;
  /* 同 DataFilterSection 的提示文字：浅色下 --text-3 在白底仅 2.54:1 */
  color: var(--text-2);
  line-height: 1.5;
}

/* 控制工具条（预览稿 .toolbar 形态） */
.wafer-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin: 12px 0;
  padding: 8px 12px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 6px;
}
.ctl-label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
  white-space: nowrap;
}
.ctl-spacer {
  flex: 1;
}
.height-range {
  width: 120px;
  accent-color: var(--brand);
}
.height-val {
  font-size: 11px;
  color: var(--text);
  font-weight: 600;
  font-family: var(--font-mono);
  min-width: 28px;
}

/* 左 25% / 右 75% 分栏（对齐预览稿 .row .col-l/.col-r） */
.wafer-body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.wafer-left {
  flex: 0 0 25%;
  min-width: 0;
}
.wafer-right {
  flex: 1 1 75%;
  min-width: 0;
}
.wafer-left > :deep(.wafer-stat-tables) {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 自动结论条（预览稿 .diag 形态） */
.wafer-conclusion {
  margin-top: 10px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-2);
  border-left: 3px solid var(--info);
  background: color-mix(in srgb, var(--info) 9%, transparent);
  border-radius: 0 4px 4px 0;
}
.wafer-fallback-note {
  margin-top: 6px;
  padding: 4px 10px;
  font-size: 11.5px;
  color: var(--warn-2, var(--warn));
  text-align: center;
}
</style>
```

注意（执行者对照原文件）：`loadWaferGlobal`、`onLoadGlobal` 整体删除（全局判定按钮取消）；`buildOption` 里的 `colorBy === 'zone'` 与 `zonalData` 环带叠加分支迁到 `localZoneMode` 分支并重写为「按 die 落环带着色」（旧实现只画环线不着色 die，这是预览稿「分区模式接真」的显示层缺口——zone 统计口径后端 `compute_wafer_zone_stats` 与此分支用同一 `bounds = [r/3, 2r/3]` + `hypot` 距离，行为一致）。

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```

预期：exit=0 零类型错误。若 `visualMap dimension` 或 `toPt` 类型报错，给 `option` 显式 `: any`（已带）并核对 `toPt` 返回值形状。

- [ ] **Step 3: 浏览器冒烟（有 dev 服务时）**

用 browser-use 打开 `/analysis` 晶圆图 tab，逐档切换着色 + 勾选分区，确认双主题下四档渲染、左栏两表出数、结论条出现。无 dev 服务时跳过（e2e Task 6 会覆盖），在 todo.md Review 里记录「双主题走查待用户 dev 环境」。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/analysis/components/WaferMapPanel.vue frontend/src/pages/analysis/components/WaferStatTables.vue
git commit -m "refactor(analysis): 晶圆图对齐预览稿——着色4档+分区checkbox+左栏两表+结论条+die尺寸真实化"
```

---

### Task 5: e2e 存量迁移——「Total Dies」定位器与契约

**Files:**
- Modify: `frontend/e2e/analysis/wafermap-hidden-tab-init.spec.ts:51`
- Modify: `frontend/e2e/analysis/wafermap-model-not-found.spec.ts:73,153`
- Modify: `frontend/e2e/analysis/tab-independent-files.spec.ts:92`

- [ ] **Step 1: 三处定位器替换**

顶部四统计卡已删，「Total Dies」文字现在在左栏 `data-wafer-stat-table` 表内。统一改为：

```ts
await expect(panel.locator('[data-wafer-stat-table]')).toBeVisible({ timeout: 30_000 })
```

- `wafermap-hidden-tab-init.spec.ts:51`：`await expect(panel.getByText('Total Dies')).toBeVisible({ timeout: 30_000 })` → 上一行（panel 变量已存在）。
- `wafermap-model-not-found.spec.ts:73`、`:153`：同样替换（`:152` 的注释「统计卡片出现（Total Dies）」改为「左栏统计表出现（data-wafer-stat-table）」）。
- `tab-independent-files.spec.ts:92`：`await expect(page.getByText('Total Dies')).toBeVisible({ timeout: 120_000 })` → `await expect(page.locator('[data-wafer-stat-table]')).toBeVisible({ timeout: 120_000 })`。

注意：`tab-independent-files.spec.ts` 后续如还有依赖统计卡结构的断言（grep `Pass Dies|Fail Dies|Yield`），一并迁移到 `[data-wafer-stat-table]` 行文本断言。

- [ ] **Step 2: 隔离复跑三个 spec**

```bash
cd frontend
npx playwright test e2e/analysis/wafermap-hidden-tab-init.spec.ts e2e/analysis/wafermap-model-not-found.spec.ts e2e/analysis/tab-independent-files.spec.ts --workers=1
```

预期：全绿（或既有数据竞态 flake 隔离复跑绿，判定口径按 lessons R2③）。

- [ ] **Step 3: 提交**

```bash
git add frontend/e2e/analysis/wafermap-hidden-tab-init.spec.ts frontend/e2e/analysis/wafermap-model-not-found.spec.ts frontend/e2e/analysis/tab-independent-files.spec.ts
git commit -m "test(e2e): 晶圆图统计卡定位器迁至左栏 data-wafer-stat-table 契约"
```

---

### Task 6: e2e 新增——wafermap-redesign.spec.ts

**Files:**
- Create: `frontend/e2e/analysis/wafermap-redesign.spec.ts`

- [ ] **Step 1: 写 spec**

```ts
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { pickTabFile } from '../helpers/params'
import { expectChartRendered } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

/**
 * 晶圆图对齐保守重设计原型（2026-09-08 spec）形态契约：
 * 着色 4 档 / 分区独立 checkbox / 左栏两表 / 自动结论条 / 参数值着色降级。
 * 文件统一用种子 CP 数据 BN281R3CYCAA（唯一带 Wafer 坐标的种子文件）。
 */

const FILE_SUBSTR = 'BN281R3CYCAA'

async function enterWafer(page: import('@playwright/test').Page) {
  await gotoApp(page, '/analysis')
  await page.getByRole('tab', { name: /晶圆图/ }).click()
  await pickTabFile(page, 'wafer', FILE_SUBSTR)
  const loadBtn = page.locator('button').filter({ hasText: '加载晶圆图' })
  await expect(loadBtn).toBeEnabled({ timeout: 120_000 })
  const respPromise = page.waitForResponse(
    (r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST',
    { timeout: 180_000 },
  )
  await loadBtn.click()
  expect((await respPromise).status()).toBe(200)
  const panel = page.getByRole('tabpanel', { name: /晶圆图/ })
  await expect(panel.locator('[data-wafer-stat-table]')).toBeVisible({ timeout: 30_000 })
  return panel
}

test.describe('@p1 晶圆图重设计形态', { tag: ['@p1', '@analysis'] }, () => {
  test('着色 4 档切换：series 结构随之变化（bin 分组 >1、param 带 visualMap）', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    // result 档：Pass + Fail 两系列
    const seriesNames = async () =>
      chart.evaluate((el: any) => {
        const opt = el.__echartsInstance__.getOption()
        return opt.series.map((s: any) => s.name)
      })
    expect(await seriesNames()).toContain('Pass')
    expect(await seriesNames()).toContain('Fail')

    // bin 档：种子文件多 bin → 系列数 > 2 且名字以 Bin 开头
    await panel.locator('[data-wafer-color] .el-radio-button').filter({ hasText: 'Bin' }).click()
    await page.waitForResponse((r) => r.url().includes('/analysis/wafer_map/') && r.request().method() === 'POST')
    await expectChartRendered(chart, 0, 60_000)
    const binNames = (await seriesNames()).filter((n: string) => n.startsWith('Bin'))
    expect(binNames.length, 'CP 文件应有多个 bin 分组').toBeGreaterThan(1)

    // param 档：选一个参数后带 visualMap（连续渐变）
    await panel.locator('[data-wafer-color] .el-radio-button').filter({ hasText: '参数值' }).click()
    // 等图重渲染（visualMap 出现在 option 里）
    await expect
      .poll(async () =>
        chart.evaluate((el: any) => {
          const opt = el.__echartsInstance__.getOption()
          return Object.prototype.hasOwnProperty.call(opt, 'visualMap')
        }),
      )
      .toBe(true)
  })

  test('分区 checkbox：勾选→环带三系列+虚线环，取消→回判定结果着色', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    const zoneCheckbox = panel.locator('.el-checkbox').filter({ hasText: '分区模式' })
    await zoneCheckbox.check()
    await expect
      .poll(async () =>
        chart.evaluate((el: any) => {
          const opt = el.__echartsInstance__.getOption()
          return opt.series.map((s: any) => s.name)
        }),
      )
      .toEqual(expect.arrayContaining(['中心区', '中间区', '边缘区']))

    await zoneCheckbox.uncheck()
    await expect
      .poll(async () =>
        chart.evaluate((el: any) => {
          const opt = el.__echartsInstance__.getOption()
          return opt.series.map((s: any) => s.name)
        }),
      )
      .toEqual(expect.arrayContaining(['Pass', 'Fail']))
  })

  test('左栏两表：统计表数字与图 title 子文本一致（防口径漂移）', async ({ page }) => {
    const panel = await enterWafer(page)
    const chart = panel.locator('div[_echarts_instance_]').first()
    await expectChartRendered(chart, 0, 60_000)

    const titleSub = await chart.evaluate((el: any) => el.__echartsInstance__.getOption().title[0].subtext)
    const total = Number(titleSub.match(/Total: (\d+)/)![1])
    const statTotal = await panel
      .locator('[data-wafer-stat-table] tr', { hasText: '总 die' })
      .locator('td.n')
      .innerText()
    expect(Number(statTotal)).toBe(total)
  })

  test('自动结论条：三区有数时出现且文案含「径向梯度」', async ({ page }) => {
    const panel = await enterWafer(page)
    await expect(panel.locator('[data-wafer-zone-table] tr')).toHaveCount(3, { timeout: 30_000 })
    // 种子 CP 文件三区都有 die（144×~100 网格），结论条必须出现
    const conclusion = panel.locator('[data-wafer-conclusion]')
    await expect(conclusion).toBeVisible({ timeout: 30_000 })
    await expect(conclusion).toContainText(/径向梯度/)
  })
})
```

- [ ] **Step 2: 跑新 spec**

```bash
cd frontend
npx playwright test e2e/analysis/wafermap-redesign.spec.ts --workers=1
```

预期：4 用例全绿。若「参数值档 visualMap」用例失败：检查 buildOption 是否把 `visualMap` 挂在 option 根（`getOption().visualMap` 是数组或对象，ECharts 返回时可能包装——断言改为 `opt.visualMap != null && opt.visualMap.length !== 0` 的宽松形式再定位）。

- [ ] **Step 3: 提交**

```bash
git add frontend/e2e/analysis/wafermap-redesign.spec.ts
git commit -m "test(e2e): 晶圆图着色4档/分区叠加/两表一致性/结论条形态契约"
```

---

### Task 7: e2e README 契约章节 + 全量回归 + todo 落册

**Files:**
- Modify: `frontend/e2e/README.md`（「已验证选择器」章节）
- Modify: `docs/tasks/todo.md`

- [ ] **Step 1: README 补契约**

在 `frontend/e2e/README.md` 选择器契约章节（`[data-file-picker=...]` 段落之后）插入：

```markdown
- 晶圆图（2026-09-08 起对齐保守重设计原型）：着色 radio 挂 `data-wafer-color`；
  左栏两表挂 `[data-wafer-zone-table]` / `[data-wafer-stat-table]`；
  自动结论条挂 `[data-wafer-conclusion]`。统计信息不再有「Total Dies」等
  el-card 统计卡（已在重设计中删除），存量定位器一律走上述契约属性。
```

- [ ] **Step 2: 全量构建 + 后端测试**

```bash
cd frontend && npm run build
cd ..
python manage.py test apps.analysis
```

预期：build exit=0；`manage.py test apps.analysis` 全 OK（当前基线 173+，串行数分钟）。

- [ ] **Step 3: 分析页全量 e2e（Playwright 自起后端）**

```bash
cd frontend
npx playwright test e2e/analysis --workers=1
```

前置检查（lessons 2026-09-05：残留 runserver 污染数据环境）：

```bash
powershell -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*runserver*' } | Select-Object ProcessId, CommandLine"
```

有残留且未钉 `LQDP_SYSTEM_CONFIG_FILE` 的进程先整树杀掉再跑。跑完释放端口（8000/3000 确认无监听，用户手动 dev 服务除外——按契约复用不杀）。

预期：全绿 + 既有 flake 隔离复跑绿（基线 flake 族谱见 todo 2026-09-07 Review）。

- [ ] **Step 4: todo.md 落册**

在 `docs/tasks/todo.md` 顶部插入本任务条目（标题「任务：晶圆图页面对齐保守重设计原型（2026-09-08）」+ 实施清单 + Review 段记录验证账目与遗留账——双主题人工走查若未做，明确写给用户）。

- [ ] **Step 5: 收尾提交**

```bash
git add frontend/e2e/README.md docs/tasks/todo.md
git commit -m "docs(e2e): 晶圆图 data-wafer-* 契约入 README；todo 落册验证账目"
```

---

## 自审记录（writing-plans Self-Review）

1. **Spec 覆盖**：9 项决策逐条映射——决策 1（范围）→ Task 4 全部；决策 2（双口径）→ Task 1 value + Task 2 spec_low/high + Task 4 `paramScale`；决策 3（标签）→ Task 4 checkbox 文案；决策 4（结论条）→ Task 4 `conclusion` computed + Task 6 用例 4；决策 5（分区 checkbox）→ Task 4 `localZoneMode` 分支 + Task 6 用例 2；决策 6（复用判定参数）→ Task 4 `localParam` 不加控件；决策 7（左栏两表）→ Task 3 + Task 4 接线 + Task 6 用例 3；决策 8（窄 range）→ Task 4 `.height-range`；决策 9（直发 value）→ Task 1。无缺口。
2. **占位符扫描**：所有代码步骤给完整代码；无 TBD/「适当处理」。
3. **类型一致性**：`toPt` 在 `pushResultSeries` 与各分支一致（value 三元组仅 param 档）；`WaferStatTables` props 与 Task 4 传参一致（`zones/zoneError/stats/xCol/yCol/dieSize`）；后端 `resolve_spec_limits` 返回 `Tuple[Optional[float], Optional[float]]` 与视图赋值一致。

## 已知风险与规避

1. **结论条可能对种子文件不成立**：`wafermap-redesign` 用例 4 假设种子 CP 文件三区都有 die。若种子的失效全集中在某区且各区 yield 均非 null，结论条必现（两分支都含「径向梯度」字样）；但若某区 total=0（yield=null），结论条不出现 → 用例加前置：结论条不可见时跳过并注释原因，避免环境假红。
2. **param 档依赖用户选了参数**：`localParam` 默认空。用例 1 切到「参数值」档前未选参数 → 后端无 value → 降级回落（这是契约行为）。修法：用例 1 在切档前先从参数下拉选 Vth（种子里有 Min/Max 元数据的参数），或断言回落注记出现。执行者按第一步实测结果二选一，倾向后者（少一次下拉交互、钉住降级契约）。
3. **`get_1d_from` 对 str 列 to_numeric**：CP 文件参数列是 float，`errors='coerce'` 兜底；`math.isfinite(v)` 防 NaN/inf（numpy float64 转换后 `math.isfinite` 可用）。
4. **大文件 e2e 耗时**：BN281R3CYCAA 首次解析 120s 级，`enterWafer` 的超时已按存量 spec 口径（120_000/180_000）设置；本 spec 4 用例共享同文件走解析缓存，实际增量可控。
5. **e2e 与后端测试勿并跑**（lessons 2026-09-02）：Task 7 Step 2/3 顺序执行，不并行。
