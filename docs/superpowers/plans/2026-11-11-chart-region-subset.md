# 图表区域框选 → 子集直方图 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在单文件分析 tab 的直方图/serial 散点图上拖拽框选一批芯片，右键新建会话级子集直方图面板（CPK 锚定原规格限 + 子集 mean/std）。

**Architecture:** 方案 A——`/analysis/histogram/` 加可选 `selection` 字段做行级前置过滤，复用 `compute_histogram_stats`；前端 zrender 指针事件 + DOM 高亮浮层实现框选，子集面板独立于 ChartDock（不进账号记忆）。

**Tech Stack:** Django/DRF + pandas（后端）；Vue 3 + ECharts（全量包，`import * as echarts`）+ Pinia + Element Plus（前端）；pytest 风格 SimpleTestCase（T1）/ vitest（T2）/ Playwright（T3）。

**Spec:** `docs/superpowers/specs/2026-11-11-chart-region-subset-design.md`（含 D1–D6 决策；D6 兜底柱无界语义与 §5.3 zrender 机制是计划阶段修订，已回写 spec）。

---

## 关键现状事实（动手前必读，均已实测核对）

- 后端视图 `apps/analysis/views/analysis_views.py:63` `histogram()`：`_load_df_from_request` → 过滤链（`filter_bin1_rows`/`filter_test_items`）→ `guard_all_missing`（:190）→ per-param `compute_histogram_stats`（:197）。选区过滤插在 guard 之后、循环之前。
- `compute_histogram_stats`（`apps/analysis/services/data_services/histogram.py:82`）：**CPK 恒锚 RDL 规格限，不随 range_type 变**（:96-97 docstring、:131-134）；`range_type='DR'` = 按子集自身值域分箱（`resolve_bin_range` :219）。响应键：`total_count/mean/std/cpk/cpk_level/cpk_color/lower_limit/upper_limit/bin_centers/bin_percentages/bin_counts/site_histograms/outlier_info/unit`（:301-355）。
- `get_serial_column(df, preferred=None)` 从 `apps.analysis.services.statistics` 导出（`__init__.py:19,91`；实现 `statistics/helpers.py:77`，preferred 不在列里会静默回退——所以非法 serial_col 要在调用前显式守卫）。
- `get_param(request,'selection')` 读 JSON body（`apps/common/params.py:9`）。`error_response(code, detail, **extra)` → `{code,message,detail}`（`apps/common/errors.py:14`）。
- 视图测试范式：`test/backend/test_histogram_candidates_fastpath.py`——`APIRequestFactory().post(...,format='json')` + `force_authenticate(request, user=_fake_user())`（`_fake_user` 带 `settings=None`，:113）+ `apps.analysis.test_support.patch_df_loader(df, datafile, metadata)`（返回 restore）+ `fake_datafile()`。**用 SimpleTestCase 类**（manage.py test 只收集 unittest.TestCase，不收 plain pytest 函数）。
- 前端 `useChart`（`frontend/src/composables/useChart.ts:28`）返回 `{ chartRef, chartInstance }`；每次渲染 `setOption(notMerge:true)`（:132）——这是不用 ECharts brush 组件的原因（areas/光标态会被清）。`chartInstance` 上可 `getZr()`、`convertFromPixel`、`getModel()`。
- `HistogramChart.vue`（315 行）props.result 即后端单参数结果；`SerialChart.vue`（329 行）props.data.series_data 每点 `[serial,value,is_fail,anchor]`，buildOption 内 `toPoint` 产出 `{value:[xIdx,yDisp,...],realY,realSerial}`（:104-120），`siteData`（:124-129）是各 lane 绘制点集。
- `SingleParamTab.vue` **578 行**（600 上限）：只允许 ~6 行新增。right-panel 模板里 `ChartDock v-if` 与 `el-empty v-else-if`（:241-245）是 if/else 链——`<SubsetPanelArea/>` 必须放在该 el-empty **之后**，不能插中间。
- store `useSingleTabStore`（`stores/analysisTabs.ts:81`）：fileId/selectedParam/chartConfig/rangeType/barWidthPercent/barOverlapPercent/customLow/customHigh + 过滤开关（ignoreNoLimit/ignoreNoTestValue/dataOnlyBin1/onlyFailTestItem/onlyLowCpk/outlierHandling/iqrMultiplier）。setup store 返回值在实例上**已解包**（取布尔/数值直接 `store.x`，要 ref 用 storeToRefs）。
- auth 复位：`stores/auth.ts:22` `resetUserSettingsCaches()` 内调 `resetChartDockMemoryState()`（:25）——子集面板复位挂同一处。
- `StatsSummary.vue` props `statCards:{label,value,color?}[]`，按固定顺序排（N/Mean/STD/CPK 在内，未知 label 追加末尾）；类名 `.stats-summary/.stat-item` 是 e2e 契约。
- `ErrorBanner.vue` props `message/title?/showRetry?`，emit `retry`。
- e2e 范式：`frontend/e2e/analysis/serial-fail-count.spec.ts`（合成 CTA8280F CSV + `uploadFile`）；DB 清理 `deleteFilesByNameQuiet(page, prefix)`（`helpers/cleanup.ts:102`，afterAll 用 browser fixture 新建 page + `loginAs`，见 `serial-no-column.spec.ts:107-129`）。helpers：`gotoApp`/`selectAnalysisFile`/`selectParam`/`listParams`/`expectChartRendered`/`waitLoadingGone`/`loginAs`。
- 门禁（`docs/reference/testing-gates.md`）：批内 `cd frontend && npm run test:e2e:affected`；提交前 `npx vitest run` + `npm run lint:e2e` + `npm run build`；收口 `node scripts/e2e_pool.mjs --slots=4` + 后端全量。判绿取日志末尾 `RESULT:`/`OK`，不取 `$?`。

---

## Task 1: 后端 selection 解析/过滤模块 + T1

**Files:**
- Create: `apps/analysis/services/data_services/subset_selection.py`
- Test: `test/backend/test_histogram_selection.py`

- [ ] **Step 1: 写失败测试（service 层）**

创建 `test/backend/test_histogram_selection.py`：

```python
"""T1：histogram 选区（子集直方图）解析与行级过滤 + 视图接线契约。

判据分层（testing-gates §2）：守卫全组合/过滤正确性/CPK 口径都在这一档；
浏览器只留接线证明（e2e/analysis/subset-drilldown.spec.ts）。
用 SimpleTestCase：manage.py test 只收集 unittest.TestCase。
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

import pandas as pd  # noqa: E402
from django.test import SimpleTestCase  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

from apps.analysis import test_support  # noqa: E402
from apps.analysis.services.data_services.subset_selection import (  # noqa: E402
    parse_selection, filter_df_by_selection,
)
from apps.analysis.test_support import fake_datafile  # noqa: E402
from apps.analysis.views import AnalysisViewSet  # noqa: E402

PARAM = 'P1'


def _frame():
    return pd.DataFrame({
        'Serial_No': [1, 2, 3, 4, 5, 6],
        'Site_No': ['1', '1', '1', '2', '2', '2'],
        'P1': [1.0, 2.0, 3.0, 10.0, 11.0, 12.0],
    })


def _md():
    return {'format': 'CTA8290D', 'units': {PARAM: 'V'},
            'mins': {PARAM: '0'}, 'maxs': {PARAM: '5'}}


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False, settings=None,
    )


class ParseSelectionTests(SimpleTestCase):
    def test_none_means_no_selection(self):
        sel, err = parse_selection(None)
        self.assertIsNone(sel)
        self.assertIsNone(err)

    def test_value_range_finite(self):
        sel, err = parse_selection({'kind': 'value_range', 'lo': 1.0, 'hi': 2.0})
        self.assertIsNone(err)
        self.assertEqual(sel, {'kind': 'value_range', 'lo': 1.0, 'hi': 2.0})

    def test_value_range_null_hi_is_unbounded(self):
        sel, err = parse_selection({'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertIsNone(sel['hi'])

    def test_value_range_both_null_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': None, 'hi': None})
        self.assertEqual(err.status_code, 400)
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_lo_gt_hi_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': 3.0, 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_nan_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': float('nan'), 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_value_range_bool_rejected(self):
        _, err = parse_selection({'kind': 'value_range', 'lo': True, 'hi': 1.0})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_ok(self):
        sel, err = parse_selection({'kind': 'serials', 'serials': [1, 2], 'serial_col': 'Serial_No'})
        self.assertIsNone(err)
        self.assertEqual(sel['serials'], [1, 2])
        self.assertEqual(sel['serial_col'], 'Serial_No')

    def test_serials_empty_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': []})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_not_list_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': '1,2'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_bool_element_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [True]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_nan_element_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [float('nan')]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serials_over_cap_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': list(range(100001))})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_serial_col_non_string_rejected(self):
        _, err = parse_selection({'kind': 'serials', 'serials': [1], 'serial_col': 5})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_unknown_kind_rejected(self):
        _, err = parse_selection({'kind': 'magic'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_non_dict_rejected(self):
        _, err = parse_selection([1, 2])
        self.assertEqual(err.data['code'], 'invalid_selection')


class FilterDfTests(SimpleTestCase):
    def test_value_range_filters_rows(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': 11.5})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [10.0, 11.0])

    def test_value_range_unbounded_hi(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [10.0, 11.0, 12.0])

    def test_value_range_coerces_string_column(self):
        df = _frame()
        df[PARAM] = df[PARAM].astype(str)
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'value_range', 'lo': 9.0, 'hi': None})
        self.assertIsNone(err)
        self.assertEqual(len(out), 3)

    def test_serials_numeric_column(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [2, 4, 6]})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [2.0, 10.0, 12.0])

    def test_serials_string_column(self):
        df = _frame()
        df['Serial_No'] = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6']
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': ['S2', 'S5']})
        self.assertIsNone(err)
        self.assertEqual(sorted(out[PARAM].tolist()), [2.0, 11.0])

    def test_serials_numeric_wanted_string_column_coerces(self):
        df = _frame()
        df['Serial_No'] = df['Serial_No'].astype(str)
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [3]})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [3.0])

    def test_serial_col_override(self):
        df = _frame()
        df['Dut_No'] = [101, 102, 103, 104, 105, 106]
        out, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [104], 'serial_col': 'Dut_No'})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [10.0])

    def test_invalid_serial_col_rejected(self):
        _, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [1], 'serial_col': 'NOPE'})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_no_serial_column_rejected(self):
        df = _frame().drop(columns=['Serial_No'])
        _, err = filter_df_by_selection(df, PARAM, {'kind': 'serials', 'serials': [1]})
        self.assertEqual(err.data['code'], 'invalid_selection')

    def test_unmatched_serials_ignored(self):
        out, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'serials', 'serials': [2, 999]})
        self.assertIsNone(err)
        self.assertEqual(out[PARAM].tolist(), [2.0])

    def test_empty_subset_rejected(self):
        _, err = filter_df_by_selection(_frame(), PARAM, {'kind': 'value_range', 'lo': 100.0, 'hi': 200.0})
        self.assertEqual(err.data['code'], 'empty_selection')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_histogram_selection -v 1`
Expected: FAIL/ERROR —— `ModuleNotFoundError: No module named 'apps.analysis.services.data_services.subset_selection'`

- [ ] **Step 3: 实现模块**

创建 `apps/analysis/services/data_services/subset_selection.py`：

```python
"""histogram 选区（子集直方图）：解析 + 行级过滤。

选区是现有统计管线的前置过滤步骤：视图在既有过滤链（Bin1 / 测试项开关）之后、
compute_histogram_stats 之前调用 filter_df_by_selection。分箱强制 DR（子集自身
值域）由视图覆盖；CPK 锚定原规格限是 compute_histogram_stats 的既有口径。

守卫纪律（lessons R3/R4）：非法形态在解析层就 400，绝不放进计算层；数值入口
一律 pd.to_numeric(errors='coerce')，bool 不算数值。
"""
import math

import pandas as pd

from apps.analysis.services.statistics import get_serial_column
from apps.common.errors import error_response

MAX_SERIALS = 100_000


def _is_finite_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_selection(raw):
    """request.data['selection'] → (selection | None, 400 响应 | None)。

    None/缺省 = 无选区（旧口径逐字不变）。value_range 的 lo/hi 各为有限数或
    null（null = 该侧无界，D6 兜底柱语义），至少一个非 null。
    """
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, error_response('invalid_selection', 'selection 必须是对象')
    kind = raw.get('kind')
    if kind == 'value_range':
        lo, hi = raw.get('lo'), raw.get('hi')
        for v in (lo, hi):
            if v is not None and not _is_finite_number(v):
                return None, error_response('invalid_selection', 'value_range 边界必须是有限数或 null')
        if lo is None and hi is None:
            return None, error_response('invalid_selection', 'value_range 至少一侧有界')
        if lo is not None and hi is not None and lo > hi:
            return None, error_response('invalid_selection', 'value_range 下限不能大于上限')
        return {'kind': 'value_range',
                'lo': float(lo) if lo is not None else None,
                'hi': float(hi) if hi is not None else None}, None
    if kind == 'serials':
        serials = raw.get('serials')
        if not isinstance(serials, list) or not serials or len(serials) > MAX_SERIALS:
            return None, error_response('invalid_selection', f'serials 需要 1..{MAX_SERIALS} 个元素的数组')
        for s in serials:
            if isinstance(s, bool) or not isinstance(s, (int, float, str)):
                return None, error_response('invalid_selection', 'serials 元素只能是数值或字符串')
            if isinstance(s, float) and not math.isfinite(s):
                return None, error_response('invalid_selection', 'serials 不允许 NaN/inf')
        serial_col = raw.get('serial_col')
        if serial_col is not None and not isinstance(serial_col, str):
            return None, error_response('invalid_selection', 'serial_col 必须是字符串')
        out = {'kind': 'serials', 'serials': serials}
        if serial_col:
            out['serial_col'] = serial_col
        return out, None
    return None, error_response('invalid_selection', 'selection.kind 只能是 value_range 或 serials')


def filter_df_by_selection(df, param, selection):
    """按选区过滤行 → (df, 400 响应 | None)。param 已由 guard_all_missing 保证在列里。"""
    if selection['kind'] == 'value_range':
        values = pd.to_numeric(df[param], errors='coerce')
        # pandas 3.x 的 between(None, …) 全 False（None 不是无界），用 ±inf 表达无界侧；
        # NaN 与 ±inf 比较仍为 False，脏值行自动落选。
        lo = selection['lo'] if selection['lo'] is not None else -math.inf
        hi = selection['hi'] if selection['hi'] is not None else math.inf
        out = df[values.between(lo, hi)]
    else:
        preferred = selection.get('serial_col')
        if preferred and preferred not in df.columns:
            return df, error_response('invalid_selection', 'serial_col 不在该文件的列中')
        serial_col = get_serial_column(df, preferred=preferred)
        if not serial_col:
            return df, error_response('invalid_selection', '该文件没有可用的序列列')
        col = df[serial_col]
        wanted = selection['serials']
        if pd.api.types.is_numeric_dtype(col):
            col_nums = pd.to_numeric(col, errors='coerce')
            wanted_nums = pd.to_numeric(pd.Series(wanted), errors='coerce').dropna()
            out = df[col_nums.isin(wanted_nums)]
        else:
            out = df[col.astype(str).isin([str(s) for s in wanted])]
    if len(out) == 0:
        return out, error_response('empty_selection', '选区内没有数据行')
    return out, None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_histogram_selection -v 1`
Expected: `Ran 27 tests ... OK`（ParseSelection 16 + FilterDf 11；视图测试在 Task 2 追加）

- [ ] **Step 5: Commit**

```bash
git add apps/analysis/services/data_services/subset_selection.py test/backend/test_histogram_selection.py
git commit -m "feat(analysis): histogram 选区解析/行级过滤模块（value_range 无界边界 + serials）"
```

---

## Task 2: histogram 视图接线 + T1 视图契约

**Files:**
- Modify: `apps/analysis/views/analysis_views.py`（import 区 :28-37；histogram :190-212）
- Test: `test/backend/test_histogram_selection.py`（追加视图测试类）

- [ ] **Step 1: 追加失败的视图测试**

在 `test/backend/test_histogram_selection.py` 末尾追加：

```python
class HistogramViewSelectionTests(SimpleTestCase):
    def _post(self, payload, df=None, metadata=None):
        df = df if df is not None else _frame()
        metadata = metadata if metadata is not None else _md()
        restore = test_support.patch_df_loader(df, fake_datafile(), metadata)
        try:
            request = APIRequestFactory().post(
                '/api/v1/analysis/histogram/', dict(payload), format='json')
            force_authenticate(request, user=_fake_user())
            response = AnalysisViewSet.as_view({'post': 'histogram'})(request)
            response.render()
            return response
        finally:
            restore()

    def _base(self, **extra):
        return dict({'file_id': 1, 'params': [PARAM]}, **extra)

    def test_value_range_subset_count_and_limits(self):
        r = self._post(self._base(selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}))
        self.assertEqual(r.status_code, 200, r.content)
        res = r.data['results'][PARAM]
        self.assertEqual(res['total_count'], 3)
        # 规格限仍是原参数（D1/D2）：CPK 锚 RDL，不随子集变
        self.assertEqual(res['lower_limit'], 0.0)
        self.assertEqual(res['upper_limit'], 5.0)
        # 子集 mean=11 → CPK 为负（USL=5 远小于 mean）
        self.assertLess(res['cpk'], 0)

    def test_selection_forces_dr_binning(self):
        # 客户端故意传 RDL：后端必须强制 DR，子集 {10,11,12} 的 bin 跨度 hugs 自身值域
        r = self._post(self._base(range_type='RDL',
                                  selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}))
        self.assertEqual(r.status_code, 200, r.content)
        centers = r.data['results'][PARAM]['bin_centers']
        self.assertGreater(centers[0], 5.0)   # 不跨原规格限 [0,5]
        self.assertLess(centers[-1], 15.0)

    def test_serials_subset(self):
        r = self._post(self._base(selection={'kind': 'serials', 'serials': [2, 4, 6]}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'][PARAM]['total_count'], 3)

    def test_empty_selection_400(self):
        r = self._post(self._base(selection={'kind': 'value_range', 'lo': 100.0, 'hi': 200.0}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'empty_selection')

    def test_selection_requires_single_param(self):
        r = self._post(self._base(params=[PARAM, 'Site_No'],
                                  selection={'kind': 'value_range', 'lo': 0.0, 'hi': 5.0}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'invalid_selection')

    def test_invalid_kind_400(self):
        r = self._post(self._base(selection={'kind': 'magic'}))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'invalid_selection')

    def test_fast_path_ignores_selection(self):
        r = self._post(self._base(params=[], selection={'kind': 'magic'}))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn(PARAM, r.data['results'])

    def test_bin1_context_applies_before_selection(self):
        df = _frame()
        df['SW_Bin'] = ['1', '1', '1', '5', '5', '5']
        md = _md()
        md['units']['SW_Bin'] = ''
        md['mins']['SW_Bin'] = ''
        md['maxs']['SW_Bin'] = ''
        # Bin1 只剩 {1,2,3}；选区 lo=9 在 Bin1 行里无匹配 → empty_selection
        r = self._post(self._base(data_only_bin1=True,
                                  selection={'kind': 'value_range', 'lo': 9.0, 'hi': None}),
                       df=df, metadata=md)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'empty_selection')

    def test_no_selection_keeps_old_behavior(self):
        r = self._post(self._base())
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['results'][PARAM]['total_count'], 6)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_histogram_selection.HistogramViewSelectionTests -v 1`
Expected: FAIL —— 选区被忽略（`test_value_range_subset_count_and_limits` 得 6 而非 3；`test_empty_selection_400` 得 200）

- [ ] **Step 3: 视图接线**

在 `apps/analysis/views/analysis_views.py` import 区（`from apps.common.errors import error_response` 之后）加：

```python
from apps.analysis.services.data_services.subset_selection import (
    parse_selection,
    filter_df_by_selection,
)
```

在 `histogram()` 的 guard 块之后、`skipped_params = []` 之前（现 :190-193）插入：

```python
        params, all_missing = guard_all_missing(df, params)
        if all_missing is not None:
            return all_missing
        # 选区（子集直方图）：既有过滤链之后做行级过滤；分箱强制 DR（子集自身
        # 值域，spec D1），CPK 仍锚定原规格限（compute_histogram_stats 不随 range_type 变）。
        selection, sel_err = parse_selection(get_param(request, 'selection'))
        if sel_err is not None:
            return sel_err
        if selection is not None:
            if len(params) != 1:
                return error_response('invalid_selection', '选区只支持单参数请求')
            df, sel_err = filter_df_by_selection(df, params[0], selection)
            if sel_err is not None:
                return sel_err
            range_type = 'DR'
            custom_low = custom_high = None
        skipped_params = []
```

把循环后的 `if not results:` 块（现 :209-212）改为：

```python
        if not results:
            if selection is not None:
                return error_response('empty_selection', '选区内无有效数值数据')
            return error_response(
                'no_valid_params', '请求的参数均无有效数值数据',
                requested=params, skipped=skipped_params)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_histogram_selection -v 1`
Expected: `Ran 36 tests ... OK`

- [ ] **Step 5: 回归既有 histogram 契约**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_histogram_range_type test.backend.test_histogram_kde test.backend.test_histogram_candidates_fastpath apps.analysis -v 1`
Expected: OK（无选区路径逐字不变）

- [ ] **Step 6: Commit**

```bash
git add apps/analysis/views/analysis_views.py test/backend/test_histogram_selection.py
git commit -m "feat(analysis): histogram 端点接 selection 行级过滤（强制 DR 分箱，CPK 锚原规格限）"
```

---

## Task 3: 前端选区纯函数 + T2

**Files:**
- Create: `frontend/src/pages/analysis/composables/selectionGeometry.ts`
- Test: `frontend/test/unit/selectionGeometry.spec.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/test/unit/selectionGeometry.spec.ts`：

```typescript
import { describe, it, expect } from 'vitest'
import {
  normalizeRect, intersectRects, normalizeRange, pickSerials, mergeSerials,
  valueRangeWithOverflow, subsetPanelTitle, buildSubsetRequest,
  type DataPoint,
} from '../../src/pages/analysis/composables/selectionGeometry'

describe('normalizeRect', () => {
  it(' sorts corners', () => {
    expect(normalizeRect({ x: 10, y: 20 }, { x: 2, y: 5 }))
      .toEqual({ x0: 2, y0: 5, x1: 10, y1: 20 })
  })
})

describe('intersectRects', () => {
  const a = { x0: 0, y0: 0, x1: 10, y1: 10 }
  it('returns overlap', () => {
    expect(intersectRects(a, { x0: 5, y0: 5, x1: 15, y1: 15 }))
      .toEqual({ x0: 5, y0: 5, x1: 10, y1: 10 })
  })
  it('returns null when disjoint', () => {
    expect(intersectRects(a, { x0: 20, y0: 20, x1: 30, y1: 30 })).toBeNull()
  })
  it('returns null for edge-only touch', () => {
    expect(intersectRects(a, { x0: 10, y0: 0, x1: 20, y1: 10 })).toBeNull()
  })
})

describe('normalizeRange', () => {
  it('orders ascending', () => {
    expect(normalizeRange(5, 2)).toEqual([2, 5])
    expect(normalizeRange(2, 5)).toEqual([2, 5])
  })
})

describe('pickSerials', () => {
  const pts: DataPoint[] = [
    { x: 0, y: 1.0, serial: 1 },
    { x: 1, y: 2.0, serial: 2 },
    { x: 2, y: 3.0, serial: 3 },
    { x: 3, y: NaN, serial: 4 },
  ]
  it('inclusive bounds on both axes', () => {
    expect(pickSerials(pts, [1, 2], [2.0, 3.0])).toEqual([2, 3])
  })
  it('skips non-finite y', () => {
    expect(pickSerials(pts, [0, 3], [0, 10])).toEqual([1, 2, 3])
  })
  it('empty when out of range', () => {
    expect(pickSerials(pts, [10, 20], [0, 10])).toEqual([])
  })
})

describe('mergeSerials', () => {
  it('dedupes preserving first-seen order', () => {
    expect(mergeSerials([[3, 1], [1, 2], [3]])).toEqual([3, 1, 2])
  })
})

describe('valueRangeWithOverflow (D6)', () => {
  const centers = [-0.1, 0.5, 1.0, 1.5, 2.1] // [0]=underflow, [-1]=overflow
  it('normal range unchanged', () => {
    expect(valueRangeWithOverflow(0.4, 1.2, centers)).toEqual({ lo: 0.4, hi: 1.2 })
  })
  it('hi reaching overflow center → null', () => {
    expect(valueRangeWithOverflow(0.4, 2.1, centers)).toEqual({ lo: 0.4, hi: null })
  })
  it('lo reaching underflow center → null', () => {
    expect(valueRangeWithOverflow(-0.1, 1.2, centers)).toEqual({ lo: null, hi: 1.2 })
  })
  it('both edges → both null', () => {
    expect(valueRangeWithOverflow(-0.1, 2.1, centers)).toEqual({ lo: null, hi: null })
  })
  it('short centers array leaves range unchanged', () => {
    expect(valueRangeWithOverflow(0.4, 2.1, [1.0])).toEqual({ lo: 0.4, hi: 2.1 })
  })
})

describe('subsetPanelTitle', () => {
  it('value_range with unbounded hi', () => {
    expect(subsetPanelTitle('P1', { kind: 'value_range', lo: 9, hi: null }, 3))
      .toBe('P1 子集 · n=3 · [9, +∞]')
  })
  it('serials count', () => {
    expect(subsetPanelTitle('P1', { kind: 'serials', serials: [1, 2, 3] }, 3))
      .toBe('P1 子集 · n=3 · 3 颗序列')
  })
  it('null n while loading', () => {
    expect(subsetPanelTitle('P1', { kind: 'value_range', lo: 0, hi: 1 }, null))
      .toBe('P1 子集 · [0, 1]')
  })
})

describe('buildSubsetRequest', () => {
  const ctx = {
    fileId: 7, ignoreNoLimit: false, ignoreNoTestValue: false, dataOnlyBin1: true,
    onlyFailTestItem: false, onlyLowCpk: false, iqrMultiplier: 2.0,
    chartConfig: ['limit', 'kde', 'kde_full'],
  }
  it('forces DR + null custom limits + carries selection', () => {
    const sel = { kind: 'value_range' as const, lo: 9, hi: null }
    const body = buildSubsetRequest(ctx, 'P1', sel)
    expect(body.file_id).toBe(7)
    expect(body.params).toEqual(['P1'])
    expect(body.range_type).toBe('DR')
    expect(body.custom_low).toBeNull()
    expect(body.custom_high).toBeNull()
    expect(body.data_only_bin1).toBe(true)
    expect(body.iqr_multiplier).toBe(2.0)
    expect(body.selection).toEqual(sel)
  })
  it('kde_variant all when kde_full checked', () => {
    const body = buildSubsetRequest(ctx, 'P1', { kind: 'value_range', lo: 0, hi: 1 })
    expect(body.include_kde).toBe(true)
    expect(body.kde_variant).toBe('all')
  })
  it('kde off when not configured', () => {
    const body = buildSubsetRequest({ ...ctx, chartConfig: ['limit'] }, 'P1',
      { kind: 'value_range', lo: 0, hi: 1 })
    expect(body.include_kde).toBe(false)
    expect(body.kde_variant).toBeNull()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run test/unit/selectionGeometry.spec.ts`
Expected: FAIL —— 模块不存在

- [ ] **Step 3: 实现纯函数模块**

创建 `frontend/src/pages/analysis/composables/selectionGeometry.ts`：

```typescript
/**
 * 框选选区的纯几何/payload 函数（T2 承载，无 DOM 无网络）。
 * 图表 glue（convertFromPixel/grid 矩形/zrender 事件）在 useChartBrushSelect.ts。
 */

export interface PxRect { x0: number; y0: number; x1: number; y1: number }
/** x = 轴下标（category 映射后）；y = 绘制值（含 jitter/锚定，D5 WYSIWYG） */
export interface DataPoint { x: number; y: number; serial: number | string }

export type ChartSelection =
  | { kind: 'value_range'; lo: number | null; hi: number | null }
  | { kind: 'serials'; serials: (number | string)[]; serial_col?: string }

export function normalizeRect(a: { x: number; y: number }, b: { x: number; y: number }): PxRect {
  return {
    x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y),
    x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y),
  }
}

export function intersectRects(a: PxRect, b: PxRect): PxRect | null {
  const x0 = Math.max(a.x0, b.x0)
  const y0 = Math.max(a.y0, b.y0)
  const x1 = Math.min(a.x1, b.x1)
  const y1 = Math.min(a.y1, b.y1)
  return x1 > x0 && y1 > y0 ? { x0, y0, x1, y1 } : null
}

export function normalizeRange(a: number, b: number): [number, number] {
  return a <= b ? [a, b] : [b, a]
}

export function pickSerials(
  points: DataPoint[], xRange: [number, number], yRange: [number, number],
): (number | string)[] {
  const out: (number | string)[] = []
  for (const p of points) {
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue
    if (p.x >= xRange[0] && p.x <= xRange[1] && p.y >= yRange[0] && p.y <= yRange[1]) {
      out.push(p.serial)
    }
  }
  return out
}

export function mergeSerials(groups: (number | string)[][]): (number | string)[] {
  const seen = new Set<number | string>()
  const out: (number | string)[] = []
  for (const g of groups) {
    for (const s of g) {
      if (!seen.has(s)) { seen.add(s); out.push(s) }
    }
  }
  return out
}

/** D6：框选触达 underflow/overflow 兜底柱中心 → 该侧无界（null）。 */
export function valueRangeWithOverflow(
  lo: number, hi: number, binCenters: number[],
): { lo: number | null; hi: number | null } {
  let L: number | null = lo
  let H: number | null = hi
  if (binCenters.length >= 2) {
    if (lo <= binCenters[0]) L = null
    if (hi >= binCenters[binCenters.length - 1]) H = null
  }
  return { lo: L, hi: H }
}

export function subsetPanelTitle(param: string, sel: ChartSelection, n: number | null): string {
  const base = n != null ? `${param} 子集 · n=${n}` : `${param} 子集`
  if (sel.kind === 'value_range') {
    const lo = sel.lo != null ? String(sel.lo) : '-∞'
    const hi = sel.hi != null ? String(sel.hi) : '+∞'
    return `${base} · [${lo}, ${hi}]`
  }
  return `${base} · ${sel.serials.length} 颗序列`
}

export interface SubsetRequestCtx {
  fileId: number
  ignoreNoLimit: boolean
  ignoreNoTestValue: boolean
  dataOnlyBin1: boolean
  onlyFailTestItem: boolean
  onlyLowCpk: boolean
  iqrMultiplier: number
  chartConfig: string[]
}

/** 子集请求体：强制 DR 分箱（D1）、custom 限置空、KDE 跟随图表配置（与 useHistogram 同口径）。 */
export function buildSubsetRequest(ctx: SubsetRequestCtx, param: string, selection: ChartSelection) {
  const showKde = ctx.chartConfig.includes('kde')
  return {
    file_id: ctx.fileId,
    params: [param],
    ignore_no_limit: ctx.ignoreNoLimit,
    range_type: 'DR',
    custom_low: null,
    custom_high: null,
    iqr_multiplier: ctx.iqrMultiplier,
    ignore_no_test_value: ctx.ignoreNoTestValue,
    data_only_bin1: ctx.dataOnlyBin1,
    only_fail_test_item: ctx.onlyFailTestItem,
    only_low_cpk: ctx.onlyLowCpk,
    include_kde: showKde,
    kde_variant: showKde ? (ctx.chartConfig.includes('kde_full') ? 'all' : 'filtered') : null,
    selection,
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/selectionGeometry.spec.ts`
Expected: PASS（20 例）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/analysis/composables/selectionGeometry.ts frontend/test/unit/selectionGeometry.spec.ts
git commit -m "feat(analysis): 框选选区纯函数（几何/命中/D6 无界/子集请求体）+ T2"
```

---

## Task 4: 框选 composable + 右键菜单 + 两图接线

**Files:**
- Create: `frontend/src/pages/analysis/composables/useChartBrushSelect.ts`
- Create: `frontend/src/pages/analysis/components/ChartContextMenu.vue`
- Modify: `frontend/src/pages/analysis/components/HistogramChart.vue`
- Modify: `frontend/src/pages/analysis/components/SerialChart.vue`

本任务无独立单测（DOM/zrender 交互属 T3 五类「真实渲染」）；验证靠 `npm run build`（vue-tsc）+ Task 6 的 e2e 接线证明。几何判据已在 Task 3 的 T2 钉住。

- [ ] **Step 1: 实现 useChartBrushSelect.ts**

创建 `frontend/src/pages/analysis/composables/useChartBrushSelect.ts`：

```typescript
/**
 * 图表框选（zrender 指针事件 + DOM 高亮浮层，spec §5.3）。
 * 不用 ECharts brush 组件：useChart 每次 setOption(notMerge) 会清掉 brush areas
 * 与光标态；自有选区状态 + DOM 浮层可在重渲染后按数据坐标重定位，large 模式确定。
 *
 * value-range 模式（直方图）：只取 X 分量，浮层占满 grid 全高，D6 兜底柱无界。
 * rect 模式（散点）：逐 lane 与 grid 矩形求交 → convertFromPixel → 点集命中取 serial。
 */
import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import type * as echarts from 'echarts'
import {
  normalizeRect, intersectRects, normalizeRange, pickSerials, mergeSerials,
  valueRangeWithOverflow, type PxRect, type DataPoint, type ChartSelection,
} from './selectionGeometry'

export type { ChartSelection } from './selectionGeometry'

export interface BrushMenu { visible: boolean; x: number; y: number }
interface GridRect { x: number; y: number; width: number; height: number }
interface RectLane { lane: number; xRange: [number, number]; yRange: [number, number] }

const MIN_DRAG_PX = 3

export function useChartBrushSelect(opts: {
  mode: 'value-range' | 'rect'
  chartInstance: Ref<echarts.ECharts | null>
  container: Ref<HTMLElement | null>
  enabled: () => boolean
  getLanes?: () => { points: DataPoint[] }[]
  getBinCenters?: () => number[]
  serialCol?: () => string | undefined
  onCreate: (sel: ChartSelection) => void
}) {
  const menu = ref<BrushMenu>({ visible: false, x: 0, y: 0 })
  const selection = ref<ChartSelection | null>(null)
  let rectLanes: RectLane[] = []
  let overlays: HTMLDivElement[] = []
  let drag: { start: { x: number; y: number }; cur: { x: number; y: number } } | null = null
  let bound: echarts.ECharts | null = null

  function gridRects(chart: echarts.ECharts): GridRect[] {
    const out: GridRect[] = []
    const model = chart.getModel() as any
    for (let i = 0; ; i++) {
      const g = model.getComponent('grid', i)
      if (!g) break
      const cs = g.coordinateSystem
      if (cs?.getRect) out.push(cs.getRect() as GridRect)
    }
    return out
  }

  function clearOverlays() {
    for (const el of overlays) el.remove()
    overlays = []
  }

  function makeOverlay(rect: PxRect) {
    const el = opts.container.value
    if (!el) return
    const div = document.createElement('div')
    div.className = 'chart-brush-overlay'
    div.style.cssText = `position:absolute;pointer-events:none;z-index:5;`
      + `left:${rect.x0}px;top:${rect.y0}px;width:${rect.x1 - rect.x0}px;height:${rect.y1 - rect.y0}px;`
      + `background:color-mix(in srgb, var(--brand) 15%, transparent);`
      + `border:1px solid color-mix(in srgb, var(--brand) 60%, transparent);`
    el.appendChild(div)
    overlays.push(div)
  }

  /** 按当前数据坐标重画浮层（重渲染/resize 后调用）。 */
  function drawOverlays() {
    clearOverlays()
    const chart = opts.chartInstance.value
    const sel = selection.value
    if (!chart || !sel) return
    const grids = gridRects(chart)
    if (sel.kind === 'value_range') {
      const g = grids[0]
      if (!g) return
      const x0 = sel.lo != null ? (chart.convertToPixel({ xAxisIndex: 0 }, sel.lo) as number) : g.x
      const x1 = sel.hi != null ? (chart.convertToPixel({ xAxisIndex: 0 }, sel.hi) as number) : g.x + g.width
      makeOverlay({ x0: Math.min(x0, x1), y0: g.y, x1: Math.max(x0, x1), y1: g.y + g.height })
      return
    }
    for (const rl of rectLanes) {
      const g = grids[rl.lane]
      if (!g) continue
      const px0 = chart.convertToPixel({ xAxisIndex: rl.lane }, rl.xRange[0]) as number
      const px1 = chart.convertToPixel({ xAxisIndex: rl.lane }, rl.xRange[1]) as number
      const py0 = chart.convertToPixel({ yAxisIndex: rl.lane }, rl.yRange[1]) as number
      const py1 = chart.convertToPixel({ yAxisIndex: rl.lane }, rl.yRange[0]) as number
      const inter = intersectRects(normalizeRect({ x: px0, y: py0 }, { x: px1, y: py1 }),
        { x0: g.x, y0: g.y, x1: g.x + g.width, y1: g.y + g.height })
      if (inter) makeOverlay(inter)
    }
  }

  function localPoint(ev: MouseEvent) {
    const r = opts.container.value!.getBoundingClientRect()
    return { x: ev.clientX - r.left, y: ev.clientY - r.top }
  }

  function onZrMouseDown(e: any) {
    const ev = e.event as MouseEvent
    if (ev.button !== 0 || !opts.enabled()) return
    if (!opts.chartInstance.value || !opts.container.value) return
    clearOverlays()
    selection.value = null
    rectLanes = []
    drag = { start: { x: e.offsetX, y: e.offsetY }, cur: { x: e.offsetX, y: e.offsetY } }
    window.addEventListener('mousemove', onWinMove)
    window.addEventListener('mouseup', onWinUp)
  }

  function onWinMove(ev: MouseEvent) {
    if (!drag) return
    drag.cur = localPoint(ev)
    const chart = opts.chartInstance.value
    if (!chart) return
    clearOverlays()
    const r = normalizeRect(drag.start, drag.cur)
    if (opts.mode === 'value-range') {
      const g = gridRects(chart)[0]
      if (g) makeOverlay({ x0: r.x0, y0: g.y, x1: r.x1, y1: g.y + g.height })
    } else {
      makeOverlay(r)
    }
  }

  function onWinUp(ev: MouseEvent) {
    window.removeEventListener('mousemove', onWinMove)
    window.removeEventListener('mouseup', onWinUp)
    if (!drag) return
    drag.cur = localPoint(ev)
    const r = normalizeRect(drag.start, drag.cur)
    drag = null
    if (r.x1 - r.x0 < MIN_DRAG_PX && r.y1 - r.y0 < MIN_DRAG_PX) { clearOverlays(); return }
    const chart = opts.chartInstance.value
    if (!chart) { clearOverlays(); return }
    const grids = gridRects(chart)
    if (opts.mode === 'value-range') {
      const g = grids[0]
      if (!g) { clearOverlays(); return }
      const cx0 = Math.max(r.x0, g.x)
      const cx1 = Math.min(r.x1, g.x + g.width)
      if (cx1 <= cx0) { clearOverlays(); return }
      const v0 = chart.convertFromPixel({ xAxisIndex: 0 }, cx0) as number
      const v1 = chart.convertFromPixel({ xAxisIndex: 0 }, cx1) as number
      const [lo, hi] = normalizeRange(v0, v1)
      const bounded = valueRangeWithOverflow(lo, hi, opts.getBinCenters?.() ?? [])
      if (bounded.lo == null && bounded.hi == null) { clearOverlays(); return }
      selection.value = { kind: 'value_range', lo: bounded.lo, hi: bounded.hi }
      drawOverlays()
      return
    }
    const lanes = opts.getLanes?.() ?? []
    const groups: (number | string)[][] = []
    rectLanes = []
    grids.forEach((g, i) => {
      const inter = intersectRects(r, { x0: g.x, y0: g.y, x1: g.x + g.width, y1: g.y + g.height })
      if (!inter || !lanes[i]) return
      const xRange = normalizeRange(
        chart.convertFromPixel({ xAxisIndex: i }, inter.x0) as number,
        chart.convertFromPixel({ xAxisIndex: i }, inter.x1) as number)
      const yRange = normalizeRange(
        chart.convertFromPixel({ yAxisIndex: i }, inter.y0) as number,
        chart.convertFromPixel({ yAxisIndex: i }, inter.y1) as number)
      const picked = pickSerials(lanes[i].points, xRange, yRange)
      if (picked.length) {
        rectLanes.push({ lane: i, xRange, yRange })
        groups.push(picked)
      }
    })
    const serials = mergeSerials(groups)
    if (!serials.length) { clearOverlays(); rectLanes = []; return }
    selection.value = { kind: 'serials', serials, serial_col: opts.serialCol?.() }
    drawOverlays()
  }

  function onRendered() { if (selection.value) drawOverlays() }

  function onContextMenu(ev: MouseEvent) {
    if (!opts.enabled() || !selection.value) return
    ev.preventDefault()
    menu.value = { visible: true, x: ev.clientX, y: ev.clientY }
  }

  function bind(chart: echarts.ECharts) {
    const el = opts.container.value
    if (el) {
      el.style.position = 'relative'
      el.addEventListener('contextmenu', onContextMenu)
    }
    chart.getZr().on('mousedown', onZrMouseDown)
    chart.on('rendered', onRendered)
    bound = chart
  }

  function unbind() {
    if (bound) {
      bound.getZr().off('mousedown', onZrMouseDown)
      bound.off('rendered', onRendered)
      bound = null
    }
    opts.container.value?.removeEventListener('contextmenu', onContextMenu)
    window.removeEventListener('mousemove', onWinMove)
    window.removeEventListener('mouseup', onWinUp)
    clearOverlays()
  }

  function clearSelection() {
    selection.value = null
    rectLanes = []
    clearOverlays()
    menu.value.visible = false
  }
  function closeMenu() { menu.value.visible = false }
  function createAndClose() {
    if (selection.value) opts.onCreate(selection.value)
    menu.value.visible = false
  }

  watch(opts.chartInstance, (chart) => {
    unbind()
    clearSelection()
    if (chart) bind(chart)
  }, { immediate: true })

  onBeforeUnmount(() => { unbind(); clearSelection() })

  return { menu, selection, clearSelection, closeMenu, createAndClose }
}
```

- [ ] **Step 2: 实现 ChartContextMenu.vue**

创建 `frontend/src/pages/analysis/components/ChartContextMenu.vue`：

```vue
<template>
  <Teleport to="body">
    <div
      v-if="menu.visible"
      class="chart-ctx-menu"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      data-chart-context-menu
      role="menu"
      @contextmenu.prevent
    >
      <button type="button" role="menuitem" data-menu-create-subset @click="emit('create')">新建子集直方图</button>
      <button type="button" role="menuitem" data-menu-clear-selection @click="emit('clear')">清除选择</button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { watch, onBeforeUnmount } from 'vue'
import type { BrushMenu } from '../composables/useChartBrushSelect'

const props = defineProps<{ menu: BrushMenu }>()
const emit = defineEmits<{ create: []; clear: []; close: [] }>()

function onWindowDown(ev: MouseEvent) {
  const inside = (ev.target as HTMLElement)?.closest?.('[data-chart-context-menu]')
  if (!inside) emit('close')
}
function onKey(ev: KeyboardEvent) { if (ev.key === 'Escape') emit('close') }

watch(() => props.menu.visible, (visible) => {
  if (visible) {
    window.addEventListener('mousedown', onWindowDown, true)
    window.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('mousedown', onWindowDown, true)
    window.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('mousedown', onWindowDown, true)
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.chart-ctx-menu {
  position: fixed;
  z-index: 3000;
  min-width: 160px;
  padding: 4px;
  background: var(--bg-2, #fff);
  border: 1px solid var(--border-2, #e4e7ed);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
}
.chart-ctx-menu button {
  display: block;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: var(--p-fs-dense);
  color: var(--text);
  cursor: pointer;
}
.chart-ctx-menu button:hover {
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
}
</style>
```

- [ ] **Step 3: HistogramChart 接线**

`frontend/src/pages/analysis/components/HistogramChart.vue`：

模板——在 `<OutlierHintBar ... />` 之后、`</div>`（wrapper 闭合）之前加：

```vue
    <ChartContextMenu
      :menu="brush.menu"
      @create="brush.createAndClose"
      @clear="brush.clearSelection"
      @close="brush.closeMenu"
    />
```

script——import 区加：

```typescript
import { useChartBrushSelect, type ChartSelection } from '../composables/useChartBrushSelect'
import ChartContextMenu from './ChartContextMenu.vue'
```

props 类型加一个字段（在 `outlierHandling?: 'clip' | 'exclude' | 'off'` 后）：

```typescript
  enableSelection?: boolean
```

`withDefaults` 默认值对象加 `enableSelection: false,`。

在 `const { colors, isDark } = useEChartsTheme()` 之后加 emit 与 brush（注意 `useChart` 解构要补 `chartInstance`，见下）：

```typescript
const emit = defineEmits<{ 'create-subset': [sel: ChartSelection] }>()
```

把文件末尾的 `const { chartRef } = useChart(buildOption, [...])` 改为 `const { chartRef, chartInstance } = useChart(buildOption, [...])`（依赖数组原样不动），并在其后加：

```typescript
const brush = useChartBrushSelect({
  mode: 'value-range',
  chartInstance,
  container: chartRef,
  enabled: () => props.enableSelection,
  getBinCenters: () => props.result?.bin_centers ?? [],
  onCreate: (sel) => emit('create-subset', sel),
})
```

（`void chartRef` 那行保留。）

- [ ] **Step 4: SerialChart 接线**

`frontend/src/pages/analysis/components/SerialChart.vue`：

模板——在 `<OutlierHintBar ... />` 之后、wrapper `</div>` 之前加（与 HistogramChart 相同的 ChartContextMenu 块）：

```vue
    <ChartContextMenu
      :menu="brush.menu"
      @create="brush.createAndClose"
      @clear="brush.clearSelection"
      @close="brush.closeMenu"
    />
```

script——先把 vue 导入补上 `ref`（该文件原本只导入 `computed`）：

```typescript
import { computed, ref } from 'vue'
```

import 区再加：

```typescript
import { useChartBrushSelect, type ChartSelection } from '../composables/useChartBrushSelect'
import type { DataPoint } from '../composables/selectionGeometry'
import ChartContextMenu from './ChartContextMenu.vue'
```

props 类型加 `enableSelection?: boolean`，默认值加 `enableSelection: false,`。

在 `const { colors, isDark } = useEChartsTheme()` 之后加：

```typescript
const emit = defineEmits<{ 'create-subset': [sel: ChartSelection] }>()
// 各 lane 绘制点集（x=轴下标, y=绘制值含 jitter/锚定, serial=真实序列号）。
// 只在 buildOption 里同步写出、只在框选 mouseup 时读——不 watch，避免渲染循环。
const displayLanes = ref<{ points: DataPoint[] }[]>([])
```

buildOption 开头 `if (!props.data) return {}` 改为：

```typescript
  if (!props.data) { displayLanes.value = []; return {} }
```

在 `siteData` 计算块（`const siteData: any[][] = siteSeriesRaw.map(...)` 结束）之后加：

```typescript
  displayLanes.value = siteData.map((arr) => ({
    points: arr.map((pt: any) => ({
      x: typeof pt.value[0] === 'number' ? pt.value[0] : continuousSerials.indexOf(pt.realSerial),
      y: pt.value[1] as number,
      serial: pt.realSerial as number | string,
    })),
  }))
```

把末尾 `const { chartRef } = useChart(...)` 改为 `const { chartRef, chartInstance } = useChart(...)`（其余参数不动），并在其后加：

```typescript
const brush = useChartBrushSelect({
  mode: 'rect',
  chartInstance,
  container: chartRef,
  enabled: () => props.enableSelection,
  getLanes: () => displayLanes.value,
  serialCol: () => props.data?.serial_col,
  onCreate: (sel) => emit('create-subset', sel),
})
```

- [ ] **Step 5: 类型与单测验证**

Run: `cd frontend && npm run build`
Expected: vue-tsc -b + vite build 成功（无 TS 错误）

Run: `cd frontend && npx vitest run`
Expected: 全绿（含 Task 3 的 20 例）

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/analysis/composables/useChartBrushSelect.ts frontend/src/pages/analysis/components/ChartContextMenu.vue frontend/src/pages/analysis/components/HistogramChart.vue frontend/src/pages/analysis/components/SerialChart.vue
git commit -m "feat(analysis): 直方图/散点图框选（zrender+DOM 浮层）与右键菜单"
```

---

## Task 5: 子集面板状态/区域 + 页面接线 + T2

**Files:**
- Create: `frontend/src/pages/analysis/composables/useSubsetPanels.ts`
- Create: `frontend/src/pages/analysis/components/SubsetPanelArea.vue`
- Modify: `frontend/src/pages/analysis/components/SingleParamTab.vue`（~6 行）
- Modify: `frontend/src/stores/auth.ts`（2 行）

- [ ] **Step 1: 实现 useSubsetPanels.ts**

创建 `frontend/src/pages/analysis/composables/useSubsetPanels.ts`：

```typescript
/**
 * 会话级子集面板（spec D4：独立于 ChartDock，不进账号记忆）。
 * 模块单例仿 useChartDock；切文件/切参数清空（R5），换账号由 auth 复位调
 * resetSubsetPanels()。请求体构造是纯函数 buildSubsetRequest（T2 承载）。
 */
import { ref, reactive, watch } from 'vue'
import api from '../../../api'
import { formatError } from '../../../utils/error'
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { buildSubsetRequest, type ChartSelection } from './selectionGeometry'

export interface SubsetPanel {
  id: number
  param: string
  selection: ChartSelection
  result: any | null
  loading: boolean
  error: string | null
}

function create() {
  const panels = ref<SubsetPanel[]>([])
  let nextId = 1
  const store = useSingleTabStore()

  async function load(panel: SubsetPanel) {
    panel.loading = true
    panel.error = null
    try {
      const ctx = {
        fileId: store.fileId as number,
        ignoreNoLimit: store.ignoreNoLimit,
        ignoreNoTestValue: store.ignoreNoTestValue,
        dataOnlyBin1: store.dataOnlyBin1,
        onlyFailTestItem: store.onlyFailTestItem,
        onlyLowCpk: store.onlyLowCpk,
        iqrMultiplier: store.iqrMultiplier,
        chartConfig: store.chartConfig,
      }
      const resp = await api.post(
        '/analysis/histogram/',
        buildSubsetRequest(ctx, panel.param, panel.selection),
        { silent: true },
      )
      panel.result = resp?.results?.[panel.param] ?? null
      if (!panel.result) panel.error = '选区内无有效数值数据'
    } catch (e) {
      panel.error = formatError(e, '子集数据加载失败')
    } finally {
      panel.loading = false
    }
  }

  function createPanel(selection: ChartSelection) {
    if (!store.fileId || !store.selectedParam) return
    // reactive：load 里就地改 loading/result/error 必须经响应式代理才触发 UI
    const panel = reactive<SubsetPanel>({
      id: nextId++, param: store.selectedParam, selection,
      result: null, loading: true, error: null,
    })
    panels.value = [...panels.value, panel]
    void load(panel)
  }

  function remove(id: number) { panels.value = panels.value.filter((p) => p.id !== id) }
  function clearAll() { panels.value = [] }
  function retry(id: number) {
    const p = panels.value.find((x) => x.id === id)
    if (p) void load(p)
  }

  watch([() => store.fileId, () => store.selectedParam], clearAll)

  return { panels, create: createPanel, remove, clearAll, retry }
}

let singleton: ReturnType<typeof create> | null = null

export function useSubsetPanels() {
  if (!singleton) singleton = create()
  return singleton
}

/** 登出/登入（stores/auth.ts）调用：不赌 fileId 一定变，显式清空。 */
export function resetSubsetPanels() { singleton?.clearAll() }
```

- [ ] **Step 2: 实现 SubsetPanelArea.vue**

创建 `frontend/src/pages/analysis/components/SubsetPanelArea.vue`：

```vue
<template>
  <div v-if="panels.length" class="subset-area" data-subset-area>
    <div
      v-for="panel in panels"
      :key="panel.id"
      class="subset-panel"
      data-subset-panel
      :data-subset-id="panel.id"
      :data-subset-n="panel.result?.total_count ?? ''"
    >
      <div class="subset-panel__h">
        <span class="subset-panel__title">{{ titleOf(panel) }}</span>
        <span class="subset-panel__grow" />
        <button
          type="button"
          class="subset-panel__btn"
          title="关闭"
          aria-label="关闭子集面板"
          @click="remove(panel.id)"
        >×</button>
      </div>
      <StatsSummary v-if="panel.result" :stat-cards="cardsOf(panel)" />
      <div class="subset-panel__b">
        <el-skeleton v-if="panel.loading" :rows="5" animated />
        <ErrorBanner
          v-else-if="panel.error"
          :message="panel.error"
          title="子集数据加载失败"
          @retry="retry(panel.id)"
        />
        <HistogramChart
          v-else-if="panel.result"
          :result="panel.result"
          :chart-config="store.chartConfig"
          range-type="DR"
          :bar-width-percent="store.barWidthPercent"
          :bar-overlap-percent="store.barOverlapPercent"
          :selected-param="panel.param"
          outlier-handling="off"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { subsetPanelTitle } from '../composables/selectionGeometry'
import { useSubsetPanels, type SubsetPanel } from '../composables/useSubsetPanels'
import HistogramChart from './HistogramChart.vue'
import StatsSummary from './StatsSummary.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'

const store = useSingleTabStore()
const { panels, remove, retry } = useSubsetPanels()
const { isDark } = useEChartsTheme()

function titleOf(panel: SubsetPanel) {
  return subsetPanelTitle(panel.param, panel.selection, panel.result?.total_count ?? null)
}

// CPK 色板与 useHistogram 的 clrs 同值（dark/light 双主题）；那边是 composable
// 内部常量，这里只取 5 色映射，不重复其统计逻辑。
function cpkColor(name?: string) {
  if (!name) return undefined
  const light: Record<string, string> = { green: '#047857', orange: '#7c3aed', darkorange: '#a21caf', red: '#b91c1c', gray: '#475569' }
  const dark: Record<string, string> = { green: '#14b8a6', orange: '#fcd34d', darkorange: '#a78bfa', red: '#fb7185', gray: '#e2e8f0' }
  return (isDark.value ? dark : light)[name]
}

function cardsOf(panel: SubsetPanel) {
  const r = panel.result
  if (!r) return []
  const cpk = r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level})` : '-'
  const limits = r.lower_limit != null && r.upper_limit != null
    ? `[${r.lower_limit}, ${r.upper_limit}]` : '-'
  return [
    { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
    { label: 'Mean', value: r.mean?.toFixed(4) ?? '-' },
    { label: 'STD', value: r.std?.toFixed(4) ?? '-' },
    { label: 'CPK', value: cpk, color: cpkColor(r.cpk_color) },
    { label: '规格限', value: limits },
  ]
}
</script>

<style scoped>
.subset-area {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
@media (max-width: 900px) {
  .subset-area { grid-template-columns: minmax(0, 1fr); }
}
.subset-panel {
  height: 420px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-2, #fff);
  border: 1px solid var(--border-2, #e4e7ed);
  border-radius: 6px;
  overflow: hidden;
}
.subset-panel__h {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 8px;
  background: var(--bg-3, #f8f9fa);
  border-bottom: 1px solid var(--border-2, #e4e7ed);
  font-size: var(--p-fs-dense);
  font-weight: 600;
  color: var(--text);
  flex: 0 0 auto;
}
.subset-panel__title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.subset-panel__grow { flex: 1; }
.subset-panel__btn {
  border: 0; background: transparent; cursor: pointer;
  color: var(--text-3, #9ca3af); font-size: var(--p-fs-base); line-height: 1;
  padding: 2px 6px; border-radius: 3px;
}
.subset-panel__btn:hover { color: var(--brand); background: color-mix(in srgb, var(--brand) 10%, transparent); }
.subset-panel__b {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  overflow: hidden;
  padding: 4px;
}
</style>
```

- [ ] **Step 3: SingleParamTab 接线（≤6 行）**

`frontend/src/pages/analysis/components/SingleParamTab.vue`：

import 区（`import ChartDock from './ChartDock.vue'` 之后）加：

```typescript
import SubsetPanelArea from './SubsetPanelArea.vue'
import { useSubsetPanels } from '../composables/useSubsetPanels'
```

在 `const site3dResetEpoch = ref(0)` 之后加：

```typescript
const subsetPanels = useSubsetPanels()
```

`<HistogramChart ... />` 标签加两个属性：`enable-selection` 与 `@create-subset="subsetPanels.create"`。
`<SerialChart ... />` 标签同样加这两个属性。

在 right-panel 模板的 `<el-empty v-else-if="!anyChartVisible" ... />` 块**之后**（不能插在 ChartDock 与该 el-empty 之间，会断 v-if/v-else-if 链）加：

```vue
      <SubsetPanelArea />
```

- [ ] **Step 4: auth 复位接线**

`frontend/src/stores/auth.ts`：

import 区（`import { resetChartDockMemoryState } ...` 之后）加：

```typescript
import { resetSubsetPanels } from '../pages/analysis/composables/useSubsetPanels'
```

`resetUserSettingsCaches()` 内 `resetChartDockMemoryState()` 之后加：

```typescript
  resetSubsetPanels()
```

- [ ] **Step 5: 验证**

Run: `cd frontend && npm run build`
Expected: 成功；并确认 SingleParamTab.vue 行数 ≤600：`wc -l src/pages/analysis/components/SingleParamTab.vue`（应 ≈584）

Run: `cd frontend && npx vitest run && npm run lint:e2e`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/analysis/composables/useSubsetPanels.ts frontend/src/pages/analysis/components/SubsetPanelArea.vue frontend/src/pages/analysis/components/SingleParamTab.vue frontend/src/stores/auth.ts
git commit -m "feat(analysis): 会话级子集直方图面板区（独立于 dock，切上下文/换账号清空）"
```

---

## Task 6: T3 接线证明 + 门禁收口

**Files:**
- Test: `frontend/e2e/analysis/subset-drilldown.spec.ts`

合成夹具：6 颗 die，KELVIN_VIN = [1.0, 1.5, 0.5, 10.0, 11.0, 12.0]，限值 [0, 2]
→ 3 颗在限内、3 颗远超限（直方图落 overflow 兜底柱、散点锚定轴顶）。第二参数 VCC 供切参数清空用例。

- [ ] **Step 1: 写 e2e**

创建 `frontend/e2e/analysis/subset-drilldown.spec.ts`：

```typescript
import { test, expect } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import fs from 'node:fs'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'
import { loginAs } from '../helpers/auth'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { selectAnalysisFile, selectParam } from '../helpers/params'

/**
 * 框选 → 右键 → 子集直方图面板（接线证明，组合判据在 T1）。
 * 夹具 6 颗 die：KELVIN_VIN [1,1.5,0.5,10,11,12]，限值 [0,2]。
 *  - 直方图右缘框选（触达 overflow 兜底柱）→ hi=null → 子集 {10,11,12} n=3；
 *  - 散点右上框选（锚定轴顶的超界点，D5 WYSIWYG）→ serials {4,5,6} n=3；
 *  - 切参数 → 面板清空（R5）。
 * 上传型用例：afterAll 删 DataFile 行（lessons R2③，deleteFilesByNameQuiet）。
 */

const SINGLE = '.single-param-tab'
const PREFIX = 'e2e_subset_'

const CSV = [
  'CTA8280F,',
  'Device Name,TEST_DEVICE,',
  '[Data]',
  'Index_No,Dut_No,Serial_No,Site_No,Dut_Pass,SW_Bin,X_COORD,Y_COORD,QR_Code,Test_Time,Data_Num,KELVIN_VIN,VCC,',
  'Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,Unit,ohm,V,',
  'Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,Min,0,3,',
  'Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,Max,2,3.6,',
  '1,1,1,1,TRUE,1,0,0,None,4.1,10,1.0,3.3,',
  '2,1,2,1,TRUE,1,0,0,None,4.1,10,1.5,3.2,',
  '3,1,3,2,TRUE,1,0,0,None,4.1,10,0.5,3.4,',
  '4,1,4,2,TRUE,1,0,0,None,4.2,10,10.0,3.3,',
  '5,1,5,2,TRUE,1,0,0,None,4.2,10,11.0,3.2,',
  '6,1,6,2,TRUE,1,0,0,None,4.2,10,12.0,3.3,',
  '',
].join('\n')

let filename = ''
let csvPath = ''

test.describe('框选子集直方图', { tag: ['@p1', '@analysis'] }, () => {
  test.beforeAll(async ({ browser }) => {
    filename = `${PREFIX}${Date.now()}.csv`
    csvPath = path.join(os.tmpdir(), filename)
    fs.writeFileSync(csvPath, CSV, 'utf-8')
    const page = await browser.newPage()
    await gotoApp(page, '/data')
    await page.locator('button').filter({ hasText: '上传文件' }).click()
    await uploadFile(page, csvPath)
    await expect(page.getByText(/上传成功/).first()).toBeVisible({ timeout: 60_000 })
    await page.close()
  })

  test.afterAll(async ({ browser }) => {
    cleanupQuiet(csvPath)
    const page = await browser.newPage()
    await loginAs(page, 'admin')
    await deleteFilesByNameQuiet(page, PREFIX)
    await page.close()
  })

  async function openAnalysis(page: import('@playwright/test').Page) {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, filename)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await selectParam(page, 'KELVIN_VIN')
    await waitLoadingGone(page.locator(SINGLE))
  }

  /** 在容器盒内按分数坐标拖拽（起点可在标题留白，spec §5.3）。 */
  async function drag(page: import('@playwright/test').Page, sel: string,
                      fx0: number, fy0: number, fx1: number, fy1: number) {
    const box = await page.locator(sel).boundingBox()
    expect(box).not.toBeNull()
    const b = box!
    const x0 = b.x + b.width * fx0
    const y0 = b.y + b.height * fy0
    const x1 = b.x + b.width * fx1
    const y1 = b.y + b.height * fy1
    await page.mouse.move(x0, y0)
    await page.mouse.down()
    await page.mouse.move(x1, y1, { steps: 8 })
    await page.mouse.up()
    return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 }
  }

  test('直方图框选 → 右键新建子集面板（n=3，CPK 非空）', async ({ page }) => {
    await openAnalysis(page)
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"value_range"') === true
        && r.status() < 500,
      { timeout: 20_000 },
    )
    // 右缘 82%→97%：触达 overflow 兜底柱 → hi=null；lo≈1.7+ 排除限内点
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    await expect(page.locator('[data-chart-context-menu]')).toBeVisible()
    await page.locator('[data-menu-create-subset]').click()
    const resp = await respPromise
    expect(resp.request().postData()).toContain('"hi":null')

    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
    await expect(panel.locator('.stat-item', { hasText: 'CPK' })).toBeVisible()
  })

  test('散点矩形框选 → 右键新建子集面板（serials，n=3）', async ({ page }) => {
    await openAnalysis(page)
    const cb = page.getByRole('checkbox', { name: '显示序列分布' })
    if (!(await cb.isChecked())) await cb.check()
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="serial"]`))

    const respPromise = page.waitForResponse(
      (r) => r.url().includes('/analysis/histogram/')
        && r.request().method() === 'POST'
        && r.request().postData()?.includes('"kind":"serials"') === true
        && r.status() < 500,
      { timeout: 20_000 },
    )
    // 右上矩形：x 55%→98% 覆盖 serial 4/5/6；y 从标题留白到 grid 40% 覆盖轴顶锚定点
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="serial"] .chart-b`, 0.55, 0.06, 0.98, 0.45)
    await page.mouse.click(cx, cy, { button: 'right' })
    await expect(page.locator('[data-chart-context-menu]')).toBeVisible()
    await page.locator('[data-menu-create-subset]').click()
    const resp = await respPromise
    const body = resp.request().postData() ?? ''
    expect(body).toContain('"kind":"serials"')

    const panel = page.locator('[data-subset-panel]')
    await expect(panel).toHaveCount(1)
    await expect(panel).toHaveAttribute('data-subset-n', '3', { timeout: 15_000 })
  })

  test('切参数 → 子集面板清空', async ({ page }) => {
    await openAnalysis(page)
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    await page.locator('[data-menu-create-subset]').click()
    await expect(page.locator('[data-subset-panel]')).toHaveCount(1)

    await selectParam(page, 'VCC')
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator('[data-subset-panel]')).toHaveCount(0)
  })

  test('夜间主题：右键菜单可见可读', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await openAnalysis(page)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    await expectChartRendered(page.locator(`${SINGLE} [data-chart-key="hist"]`))
    const { cx, cy } = await drag(page, `${SINGLE} [data-chart-key="hist"] .chart-b`, 0.82, 0.5, 0.97, 0.5)
    await page.mouse.click(cx, cy, { button: 'right' })
    const menu = page.locator('[data-chart-context-menu]')
    await expect(menu).toBeVisible()
    const item = menu.locator('[data-menu-create-subset]')
    await expect(item).toBeVisible()
    // night 下菜单文字不得是纯黑（var(--text) 应提亮），否则深底不可读
    const color = await item.evaluate((el) => getComputedStyle(el).color)
    expect(color).not.toBe('rgb(0, 0, 0)')
  })
})
```

- [ ] **Step 2: 跑新 spec（独占端口，先 netstat 确认 8000/3000 空闲）**

Run: `cd frontend && npx playwright test e2e/analysis/subset-drilldown.spec.ts --project=P1`
Expected: 4 passed。若 serial 用例框选颗数不符，先截图核对锚定点像素位置再调分数坐标（勿改判据迁就）。

- [ ] **Step 3: 双主题菜单可见性（第 4 例已覆盖 dark）**

Run: `cd frontend && npx playwright test e2e/analysis/subset-drilldown.spec.ts --project=P1 -g "夜间主题"`
Expected: 1 passed（菜单在 dark 下可见、文字非纯黑）。light 由前三例默认主题覆盖。

- [ ] **Step 4: 批内门禁**

Run: `cd frontend && npm run test:e2e:affected`
Expected: 末行 `RESULT: PASS`（analysis 档；取 RESULT 行不取 `$?`）

- [ ] **Step 5: 提交前检查集**

Run: `cd frontend && npx vitest run && npm run lint:e2e && npm run build`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/analysis/subset-drilldown.spec.ts
git commit -m "test(analysis): 框选子集直方图 e2e 接线证明（hist/serial/切参数清空）"
```

- [ ] **Step 7: 功能收口（FF 并入本地 master 前）**

Run（仓库根）: `node scripts/e2e_pool.mjs --slots=4`
Expected: 末行 `RESULT: PASS`；崩池 `VOID (infra)` 则重跑才是结论。

后端全量（枚举 apps/*，与夜跑同源；判绿取末尾 OK/FAILED，不取 `$?`）：

```bash
APPS=$(for d in apps/*/; do echo "apps.$(basename "$d")"; done | tr '\n' ' ')
.venv/Scripts/python.exe manage.py test test.backend $APPS 2>&1 | tee tasks/subset-backend-full.log
```

Expected: `Ran N tests ... OK`。跑完释放端口。

---

## 自审记录（计划作者已核对）

- **Spec 覆盖**：D1 强制 DR（Task 2 视图 + Task 3 buildSubsetRequest + T1 `test_selection_forces_dr_binning`）；D2 不再 IQR 剔除（面板 outlier-handling='off'，Task 5）；D3 限线轴内才画（markLine 超轴自动裁剪 + 统计卡常显限值，Task 5 cardsOf）；D4 独立面板区（Task 5）；D5 WYSIWYG（Task 4 displayLanes 用绘制值 + T2 pickSerials）；D6 兜底柱无界（Task 1 parse/filter + Task 3 valueRangeWithOverflow + T1/T2）。会话级多面板/切上下文清空（Task 5 watch + auth reset + T3 第三例）。双主题（CSS 变量 + Task 6 Step 3）。
- **占位扫描**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致**：`ChartSelection`/`DataPoint`/`PxRect`/`SubsetRequestCtx` 定义于 selectionGeometry.ts，useChartBrushSelect re-export ChartSelection；`BrushMenu`/`SubsetPanel` 各定义一处；`create/remove/retry/clearAll` 与模板引用一致；后端 `parse_selection/filter_df_by_selection` 签名前后一致。
- **已知执行风险**：① serial 用例锚定点像素坐标依赖 grid 几何（top 48），分数坐标已留余量，失败先截图核对再调；② `getModel().getComponent('grid', i)` 取 lane 数——拆分模式 N 个 grid 与 series_data N 个 lane 对齐（SerialChart split 分支 grids 按 siteSeriesRaw 建）；③ SingleParamTab 行数务必 ≤600（Step 5 有 wc 判据）。