# Debug: Param selector returns 400 (qqplot, boxplot) and 500 (histogram) on selection

**Status**: `[RESOLVED]` — root cause identified, fixed at two layers, regression tests added
**Date opened**: 2026-06-13
**Date closed**: 2026-06-13
**Session ID**: `param-select-400-500`

## TL;DR

The three errors were **all symptoms of one root cause**: the persisted Pinia store
value of `analysisStore.selectedParam` leaked across a file switch. After the user
selected `R_Kelvin_AGND` on `gage_m_S4.csv` and then switched the file dropdown to
`BPD93204_FT1_ETS163550_12252024.csv` (an ETS88 file that has no such column), the
analysis APIs were called with a column that does not exist in the new file:

| Endpoint | Status | Why |
|----------|--------|-----|
| `POST /api/v1/analysis/qqplot/` | **400** `param_not_found` | had `if param not in df.columns` guard |
| `GET  /api/v1/statistics/boxplot/?params=R_Kelvin_AGND&group_by=site` | **400** `no_valid_params` | post-`_sanitize_numeric_params` was empty |
| `POST /api/v1/analysis/histogram/` | **500** `KeyError: 'R_Kelvin_AGND'` | had **no** `df.columns` guard before `df[param]` |

The 500 on histogram is the loudest error and is the only one that survives the
narrow view of the original error log. The 400s on qqplot / boxplot are
*expected* behaviour once you accept the param is stale.

## Resolution

### 1. Frontend — primary fix (`AnalysisPage.onFileChange`)

Clear the selected param **before** reloading params. Without this, the user's
previous selection rides the file change and the next chart load fires the
stale value at the API.

```ts
// frontend/src/pages/analysis/AnalysisPage.vue
async function onFileChange() {
  if (!selectedFileId.value) return
  loading.value = true
  // Reset stale state so the previous file's params (which may not exist
  // in the new file) don't linger.
  params.value = []
  selectedParam.value = ''
  // Also clear the persisted store value so a remount of the page
  // (e.g. navigating away and back) does not restore the stale param.
  analysisStore.selectedParam = ''
  // ... load new file's params ...
}
```

### 2. Frontend — defence in depth (`SingleParamTab.vue`)

Watch the fileId prop and reset the local selected param. If a parent path ever
forgets to reset the v-model binding, this stops the leak.

```ts
watch(() => props.fileId, () => {
  localSelectedParam.value = ''
  if (showQQPlot.value) {
    loadQQPlot()
  }
})
```

### 3. Backend — defence in depth (`apps/analysis/views.py`)

Three views had inconsistent guards. **All three** now validate that every
requested param exists in the current DataFrame and return a structured
400 with `requested` / `missing` payload instead of 500.

```python
# histogram (was crashing with KeyError)
valid_params = [p for p in params if p in df.columns]
missing_params = [p for p in params if p not in df.columns]
if not valid_params:
    return Response({
        'error': 'no_valid_params',
        'detail': '请求的参数均不在该文件中，请重新选择文件或参数',
        'requested': params,
        'missing': missing_params,
    }, status=400)
params = valid_params  # partial params still compute

# boxplot
requested_params = list(params)
params = _sanitize_numeric_params(df, params)
if not params:
    missing = [p for p in requested_params if p and str(p).strip() and p not in df.columns]
    return Response({...}, status=400)
```

## User-reported symptoms (browser console)

Three failures fire from a single user action (selecting a parameter from the dropdown at
`useSelect.mjs:339 selectOptionClick`):

1. `SingleParamTab.vue:221` — `POST /api/v1/analysis/qqplot/ 400 (Bad Request)`
   - Triggered by `loadQQPlot()` after the user picks a parameter
2. `analysis.ts:34` — `GET /api/v1/statistics/boxplot/?file_id=14514&params=R_Kelvin_AGND&group_by=site 400 (Bad Request)`
   - For the specific param `R_Kelvin_AGND`
3. `useHistogram.ts:21` — `POST /api/v1/analysis/histogram/ 500 (Internal Server Error)`
   - Server-side crash

## Reproduction steps (as reported by user)

1. Open analysis page with a file that contains `R_Kelvin_AGND` (file_id=14514)
2. Click the param-selector dropdown
3. Select any parameter
4. Observe three XHR errors in DevTools console

## Hypotheses (falsifiable, evidence-pending)

| # | Hypothesis | Confirmation source | Result |
|---|------------|---------------------|--------|
| H1 | **Param-list vs API list divergence** — the param-selector is populated by `/analysis/histogram/` (no params) which uses `df[c].dtype in ('int64', 'float64')` strict filter, but `/analysis/boxplot/` uses `_sanitize_numeric_params` which uses `is_numeric_dtype` (lenient — bool passes). A bool/object column that gets *into* the selector could be rejected by boxplot's stricter filter. | Add instrumentation: log `df[p].dtype` and `is_numeric_dtype` for every param the user picks. | **Refuted** — the param is a real numeric column that exists in the previous file but not the new one. |
| H2 | **Histogram 500 is an unhandled exception in `compute_histogram_stats`** for the specific `R_Kelvin_AGND` data shape. The view lacks a try/except around the per-param loop. | Add instrumentation: wrap `compute_histogram_stats` in try/except and log the exception + param dtype + first/last 5 values. | **Refuted** — the 500 is `KeyError: 'R_Kelvin_AGND'` raised at `df[param]`, not inside the stats function. |
| H3 | **The qqplot 400 is `'param_no_valid_data'`** because `data_series.dropna().empty` — but this is logged in the view as a 400 return, not a crash. | Add instrumentation: log which error code qqplot returns and the row count. | **Refuted** — qqplot 400 is `param_not_found` (column missing from df). |
| H4 | **Site-grouping boxplot blows up** because `get_site_column(df)` returns None, or the column is missing/empty for this file. The 400 then comes from the empty `_sanitize_numeric_params` result. | Add instrumentation: log site_col detection and the size of the post-sanitize list. | **Confirmed partially** — the boxplot 400 IS due to empty post-sanitize list, but the *root cause* is the param not existing, not site_col detection. |
| H5 | **The three errors are all symptoms of ONE bug** — a stale param carried over from the previous file in the Pinia store. | Compare selectedParam in store vs params list in new file. | **Confirmed** — `analysisStore.selectedParam = 'R_Kelvin_AGND'` survives the file switch and the analysis APIs are called with that stale value. |

## Instrumentation plan (added during investigation)

All instrumentation went to the existing debug-server on port 7777. None of the
changes below modified business logic; they only added `_log(...)` calls.

1. `apps/analysis/views.py:histogram` — wrapped the per-param loop body in try/except,
   log the param name + dtype + exception + first 3 values.
2. `apps/analysis/views.py:qqplot` — logged which early-return code path is taken
   (param_required / param_not_found / param_no_valid_data / qqplot_failed) and
   the size of the post-dropna series.
3. `apps/analysis/views.py:boxplot` — logged the post-`_sanitize_numeric_params` list,
   the dtype of each param, and whether site_col is detected.

## Progress

- [x] Debug server started on `http://127.0.0.1:7777` (session `param-select-400-500`, idle 30 min)
- [x] `_dbg()` helper added at top of `apps/analysis/views.py` (reads `.env` file, never raises)
- [x] Instrumented `qqplot` view (Hypothesis B): entry / load-err / param-missing / dtype / empty / failed / ok
- [x] Instrumented `boxplot` view (Hypothesis C): entry / pre-sanitize / post-sanitize / no-valid
- [x] Instrumented `histogram` view (Hypothesis D): entry / pre-loop / per-param try/except with full exception context
- [x] Syntax check OK (`ast.parse` passes)
- [x] **Root cause identified**: stale `analysisStore.selectedParam` from previous file
- [x] **Front-end fix**: `AnalysisPage.onFileChange` resets `selectedParam` + store value
- [x] **Front-end fallback**: `SingleParamTab` watches `props.fileId` and clears `localSelectedParam`
- [x] **Back-end fix**: `histogram` / `boxplot` / `qqplot` views validate `param in df.columns` and return 400
- [x] **Unit tests added** (`apps/analysis/tests.py:StaleParamAcrossFileSwitchTests`, 4 cases)
- [x] **E2E test added** (`frontend/e2e/analysis/file-switch-param-reset.spec.ts`)
- [x] **Lessons documented** in `tasks/lessons.md`

## Verification

### Unit tests
```
$ python manage.py test apps.analysis.tests.StaleParamAcrossFileSwitchTests -v 2
test_boxplot_view_returns_400_for_unknown_param ... ok
test_histogram_view_drops_partial_unknown_params ... ok
test_histogram_view_returns_400_for_unknown_param ... ok
test_qqplot_view_returns_param_not_found_for_unknown_param ... ok
Ran 4 tests in 0.007s — OK
```

Full suite: 19 tests in `apps.analysis.tests` pass.

### E2E test
`frontend/e2e/analysis/file-switch-param-reset.spec.ts` — covers:
- selecting a param on `gage_m_S4`, enabling QQ+Box, switching to `BPD93204_FT1_ETS163550_12252024.csv`,
  asserting the new file's first param differs and no 4xx/5xx fires on the analysis APIs
- the placeholder-rendering edge case when QQ+Box are enabled before any param is picked

### Manual reproduction
After applying the fix, repeating the original reproduction steps:
1. Select `R_Kelvin_AGND` on `gage_m_S4.csv` → qqplot 200, boxplot 200, histogram 200
2. Switch to `BPD93204_FT1_ETS163550_12252024.csv` → param selector is cleared, first
   param of new file is auto-selected, no 4xx/5xx in DevTools
3. (Defence in depth) Manually `analysisStore.selectedParam = 'BOGUS'` in DevTools and
   call `/api/v1/analysis/histogram/` → 400 `no_valid_params` with `missing: ['BOGUS']`
   (no longer 500)

## Files changed

- `apps/analysis/views.py` — `histogram` / `boxplot` / `qqplot` views add `valid_params` validation, return 400 with `requested` / `missing` payload
- `apps/analysis/tests.py` — new `StaleParamAcrossFileSwitchTests` (4 cases, all pass)
- `frontend/src/pages/analysis/AnalysisPage.vue` — `onFileChange` resets `selectedParam` + store value before async load
- `frontend/src/pages/analysis/components/SingleParamTab.vue` — `watch(() => props.fileId)` clears `localSelectedParam` as defence in depth
- `frontend/e2e/analysis/file-switch-param-reset.spec.ts` — new e2e regression test
- `tasks/lessons.md` — new "Pinia store 持久化导致 stale selectedParam 跨文件泄漏" section with 5 rules
