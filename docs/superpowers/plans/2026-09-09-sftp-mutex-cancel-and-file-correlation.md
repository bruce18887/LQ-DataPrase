# SFTP 传输互斥/取消 + 文件相关性对比六项改进 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec `docs/superpowers/specs/2026-09-09-sftp-mutex-cancel-and-file-correlation-design.md`（e1205a4）：SFTP 同时只允许一个下载 + 下载取消按钮；文件相关性对比大文件防冻结、`tight_pct` 新规则、ignore 开关默认不勾选、Limit 判定列排序 + Excel limit sheet 筛选。

**Architecture:** 前端互斥（computed 聚合四类传输态）+ 进度卡取消按钮（复用既有 AbortSignal→GeneratorExit 清理链路，新增 1.2s 取消冷却防后端收尾窗口竞态）；相关性后端单点扩展 `_evaluate_diff_rule` 三分支 + Config 新字段，serials 端点免整表拷贝（Series 化）；前端规则文案收敛为共享 map，序列下拉渲染层截断 300。

**Tech Stack:** Django + DRF、pandas、excelize（Go 绑定）、Vue3 + Element Plus 2.14、Playwright。

**命令约定：** 后端命令在仓库根跑（`python manage.py ...`）；e2e/构建命令在 `frontend/` 下跑（`npx playwright test ...` / `npm run build`）。跑 e2e 前按 lessons 检查 8000 端口无残留 runserver（`netstat -ano | grep :8000`），Playwright 自起后端，跑完释放端口。

---

### Task 0: 落账与前置检查

**Files:**
- Modify: `docs/tasks/todo.md`

- [ ] **Step 1: 在 `docs/tasks/todo.md` 顶部新建本批任务条目**

```markdown
# 任务：SFTP 传输互斥/取消 + 文件相关性对比六项改进（2026-09-09）

> spec：docs/superpowers/specs/2026-09-09-sftp-mutex-cancel-and-file-correlation-design.md；
> 计划：docs/superpowers/plans/2026-09-09-sftp-mutex-cancel-and-file-correlation.md。

## 实施清单

- [ ] 后端 tight_pct 规则（TDD）
- [ ] 后端 ignore 开关默认翻转（TDD + 存量测试审计）
- [ ] 后端 serials 端点免整表拷贝（TDD）
- [ ] 后端 Excel Limit对比 sheet auto_filter（TDD）
- [ ] 前端 DiffRule 契约 + 文案 map
- [ ] 前端 规则C UI + ignore 默认翻转
- [ ] 前端 序列下拉渲染截断 300
- [ ] 前端 Limit 判定列排序
- [ ] 前端 SFTP 传输互斥
- [ ] 前端 SFTP 下载取消按钮
- [ ] e2e file-correlation 更新
- [ ] e2e reconnect 互斥+取消用例
- [ ] 全量验证 + Review 落账
```

- [ ] **Step 2: 提交**

```bash
git add docs/tasks/todo.md
git commit -m "docs(tasks): 2026-09-09 SFTP互斥/取消 + 相关性对比六项改进任务清单"
```

---

### Task 1: 后端 `tight_pct` 规则（服务层 TDD）

**Files:**
- Modify: `apps/analysis/services/file_correlation.py`（Config :40-48、`_evaluate_diff_rule` :121-134、模块 docstring 规则块 :7-17）
- Modify: `apps/analysis/views/file_correlation_views.py`（`_parse_fc_config` :191-236）
- Test: `apps/analysis/tests_file_correlation_service.py`、`apps/analysis/tests_file_correlation.py`

- [ ] **Step 1: 写失败的服务层测试**

在 `apps/analysis/tests_file_correlation_service.py` 的 `FileCorrelationServiceTests` 类中（`test_diff_rule_zero_and_wider` 之后）追加：

```python
    def test_diff_rule_tight_pct(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, _ = self._frames()
        meta_a = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        cfg = FileCorrelationConfig(diff_rule='tight_pct', ignore_no_limit=True)

        # B 收紧 20%（LSL 0.5→0.6，USL 2.0→1.6）→ ≤30% 默认容差 → pass
        meta_tol = {'mins': {'ParamA': '0.6'}, 'maxs': {'ParamA': '1.6'}, 'units': {}}
        r = compute_file_correlation(df1, meta_a, df2, meta_tol, cfg)
        self.assertFalse(r['rows'][0]['lsl_fail'])
        self.assertFalse(r['rows'][0]['usl_fail'])

        # USL 收紧 40%（2.0→1.2）超容差 → fail；LSL 20% 仍在容差内 → pass
        meta_over = {'mins': {'ParamA': '0.6'}, 'maxs': {'ParamA': '1.2'}, 'units': {}}
        r2 = compute_file_correlation(df1, meta_a, df2, meta_over, cfg)
        self.assertFalse(r2['rows'][0]['lsl_fail'])
        self.assertTrue(r2['rows'][0]['usl_fail'])

        # B 更宽 → pass（wider 基础语义）
        meta_wide = {'mins': {'ParamA': '0.4'}, 'maxs': {'ParamA': '2.5'}, 'units': {}}
        r3 = compute_file_correlation(df1, meta_a, df2, meta_wide, cfg)
        self.assertFalse(r3['rows'][0]['lsl_fail'])
        self.assertFalse(r3['rows'][0]['usl_fail'])

        # 恰好等于容差（USL 收紧 30%：2.0→1.4）→ pass（≤ 语义）
        meta_edge = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '1.4'}, 'units': {}}
        r4 = compute_file_correlation(df1, meta_a, df2, meta_edge, cfg)
        self.assertFalse(r4['rows'][0]['usl_fail'])

        # A 侧限值为 0（无百分比基准）→ fail
        meta_a0 = {'mins': {'ParamA': '0'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        meta_b0 = {'mins': {'ParamA': '0.1'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        r5 = compute_file_correlation(df1, meta_a0, df2, meta_b0, cfg)
        self.assertTrue(r5['rows'][0]['lsl_fail'])

    def test_diff_rule_tight_pct_custom_tolerance(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, _ = self._frames()
        meta_a = {'mins': {'ParamA': '0.5'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        meta_tol = {'mins': {'ParamA': '0.6'}, 'maxs': {'ParamA': '2.0'}, 'units': {}}
        # x=10：收紧 20% 超容差 → fail
        r = compute_file_correlation(
            df1, meta_a, df2, meta_tol,
            FileCorrelationConfig(diff_rule='tight_pct', tight_pct=10.0,
                                  ignore_no_limit=True))
        self.assertTrue(r['rows'][0]['lsl_fail'])
```

同时把 `test_missing_limit_on_one_side_fails_both_rules` 的规则循环扩到三支（缺 limit 对新规则同样 fail）：

```python
        for rule in ('zero', 'wider', 'tight_pct'):
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.analysis.tests_file_correlation_service -v 1
```
Expected: FAIL/ERROR（`FileCorrelationConfig` 无 `tight_pct` 字段 / `diff_rule='tight_pct'` 走 zero 分支断言失败）

- [ ] **Step 3: 实现**

`apps/analysis/services/file_correlation.py`：

Config（:40-48 区域）改为：

```python
@dataclass
class FileCorrelationConfig:
    """Comparison options; the frontend panel mirrors these one-to-one."""
    threshold: float = 3.0
    diff_rule: str = 'zero'          # 'zero' | 'wider' | 'tight_pct'
    max_serials: int = 30            # fallback cap when ``serials`` is None
    serials: Optional[List[int]] = None  # explicit user selection (优先)
    tight_pct: float = 30.0          # 'tight_pct' 规则的收紧容差（%，相对 A 侧限值）
    ignore_no_limit: bool = True
    ignore_no_data: bool = True
```

`_evaluate_diff_rule`（:121-134）整体替换为：

```python
def _evaluate_diff_rule(lsl_a: Optional[float], usl_a: Optional[float],
                        lsl_b: Optional[float], usl_b: Optional[float],
                        rule: str, tight_pct: float = 30.0) -> Tuple[bool, bool]:
    """→ (lsl_fail, usl_fail).  A missing limit on either side is a fail.

    'tight_pct'：wider 语义 + 收紧容差 —— B 收紧幅度 ≤ tight_pct%（相对 A 侧
    限值，带 1e-9 浮点容差，恰好等于容差判过）时放行；A 侧限值为 0 无百分比
    基准 → fail。
    """
    if rule == 'wider':
        # B 的 limit 不更紧才算 pass（更宽或相等）
        lsl_fail = not (lsl_a is not None and lsl_b is not None and lsl_b <= lsl_a)
        usl_fail = not (usl_a is not None and usl_b is not None and usl_b >= usl_a)
    elif rule == 'tight_pct':
        lsl_fail = not (
            lsl_a is not None and lsl_b is not None
            and (lsl_b <= lsl_a
                 or (lsl_a != 0
                     and (lsl_b - lsl_a) / abs(lsl_a) * 100.0 <= tight_pct + 1e-9)))
        usl_fail = not (
            usl_a is not None and usl_b is not None
            and (usl_b >= usl_a
                 or (usl_a != 0
                     and (usl_a - usl_b) / abs(usl_a) * 100.0 <= tight_pct + 1e-9)))
    else:  # 'zero'（默认）：两侧差值必须恰为 0
        lsl_fail = not (lsl_a is not None and lsl_b is not None
                        and (lsl_b - lsl_a) == 0.0)
        usl_fail = not (usl_a is not None and usl_b is not None
                        and (usl_b - usl_a) == 0.0)
    return lsl_fail, usl_fail
```

调用点（`compute_file_correlation` 内 :226-227）改为：

```python
        lsl_fail, usl_fail = _evaluate_diff_rule(lsl_a, usl_a, lsl_b, usl_b,
                                                 cfg.diff_rule, cfg.tight_pct)
```

模块 docstring 规则块（:9-12 附近）在 `'wider'` 行后补一行：

```
    'tight_pct': pass iff B is no tighter than A, or the tightening is
              within ``tight_pct``% of A's limit (per side).
```

`apps/analysis/views/file_correlation_views.py` 的 `_parse_fc_config`（:191-236）：

```python
    diff_rule = get_param(request, 'diff_rule', 'zero')
    if diff_rule not in ('zero', 'wider', 'tight_pct'):
        diff_rule = 'zero'
    tight_pct = get_param_float(request, 'tight_pct', 30.0)
    if tight_pct is None or tight_pct < 0:
        tight_pct = 30.0
```

末尾 `FileCorrelationConfig(...)` 构造加一行 `tight_pct=float(tight_pct),`。

- [ ] **Step 4: 跑测试确认通过**

```bash
python manage.py test apps.analysis.tests_file_correlation_service -v 1
```
Expected: OK（全部用例含新增 2 个）

- [ ] **Step 5: 写 API 契约测试（透传与回退）**

在 `apps/analysis/tests_file_correlation.py` 的 `FileCorrelationExportTests` 中追加：

```python
    def test_export_diff_rule_tight_pct_and_tolerance_passthrough(self):
        import io
        from openpyxl import load_workbook

        df1 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        df2 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        # B 收紧 20%（0.5→0.6）：默认容差 30 → PASS；容差 10 → FAIL
        meta_tight = {'format': 'CTA8290D',
                      'mins': {'ParamA': '0.6'}, 'maxs': {'ParamA': '2.0'},
                      'units': {'ParamA': 'V'}}
        resp = self._call_export({1: df1, 2: df2}, metas={2: meta_tight},
                                 body={'diff_rule': 'tight_pct'})
        ws = load_workbook(io.BytesIO(self._body(resp)))['Limit对比']
        self.assertEqual(ws['I3'].value, 'PASS')

        resp2 = self._call_export({1: df1, 2: df2}, metas={2: meta_tight},
                                  body={'diff_rule': 'tight_pct', 'tight_pct': 10.0})
        ws2 = load_workbook(io.BytesIO(self._body(resp2)))['Limit对比']
        self.assertEqual(ws2['I3'].value, 'FAIL')

    def test_export_invalid_diff_rule_falls_back_to_zero(self):
        import io
        from openpyxl import load_workbook

        df1 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        df2 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        # B 的 LSL 更宽（0.4 < 0.5）→ 回退 zero 规则：diff ≠ 0 → FAIL
        meta_b = {'format': 'CTA8290D',
                  'mins': {'ParamA': '0.4'}, 'maxs': {'ParamA': '2.0'},
                  'units': {'ParamA': 'V'}}
        resp = self._call_export({1: df1, 2: df2}, metas={2: meta_b},
                                 body={'diff_rule': 'bogus'})
        ws = load_workbook(io.BytesIO(self._body(resp)))['Limit对比']
        self.assertEqual(ws['I3'].value, 'FAIL')
```

- [ ] **Step 6: 跑 API 测试确认通过**

```bash
python manage.py test apps.analysis.tests_file_correlation -v 1
```
Expected: OK

- [ ] **Step 7: 提交**

```bash
git add apps/analysis/services/file_correlation.py apps/analysis/views/file_correlation_views.py apps/analysis/tests_file_correlation_service.py apps/analysis/tests_file_correlation.py
git commit -m "feat(analysis): file correlation 新增 tight_pct 收紧容差规则"
```

---

### Task 2: 后端 ignore 开关默认翻转（TDD + 存量测试审计）

**Files:**
- Modify: `apps/analysis/services/file_correlation.py:47-48`（Config 默认值）、`:180-183`、`:205-207`（注释）
- Modify: `apps/analysis/views/file_correlation_views.py:61-62`、`:194-197`、`:234-235`
- Test: `apps/analysis/tests_file_correlation_service.py`、`apps/analysis/tests_file_correlation.py`

- [ ] **Step 1: 写两个失败测试（服务层默认 + API 默认）**

`tests_file_correlation_service.py` 追加：

```python
    def test_ignore_flags_default_off(self):
        from apps.analysis.services.file_correlation import (
            compute_file_correlation, FileCorrelationConfig)

        df1, df2, meta = self._frames()
        df1['ParamC'] = [0.1, 0.2, 0.3]
        df2['ParamC'] = [0.1, 0.2, 0.3]
        meta['mins']['ParamC'] = '-'
        meta['maxs']['ParamC'] = '-'
        # 默认（不传 ignore_*）：无 limit 的 ParamC 参与对比（2026-09-09 需求 5）
        r = compute_file_correlation(df1, meta, df2, meta, FileCorrelationConfig())
        self.assertEqual(r['params'], ['ParamA', 'ParamB', 'ParamC'])
```

`tests_file_correlation.py` 的 `FileCorrelationExportTests` 追加：

```python
    def test_ignore_flags_default_off_api(self):
        import io
        from openpyxl import load_workbook

        df1 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        df2 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.1]})
        no_limits = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}
        # 不传 ignore_* → 默认不过滤无 limit 的测试项（2026-09-09 需求 5）
        resp = self._call_export({1: df1, 2: df2}, metas={1: no_limits, 2: no_limits})
        ws = load_workbook(io.BytesIO(self._body(resp)))['测试值对比']
        self.assertEqual(ws['A4'].value, 'ParamA')
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.analysis.tests_file_correlation_service.FileCorrelationServiceTests.test_ignore_flags_default_off apps.analysis.tests_file_correlation.FileCorrelationExportTests.test_ignore_flags_default_off_api -v 1
```
Expected: 2 个 FAIL（现默认过滤掉了无 limit 参数）

- [ ] **Step 3: 翻转默认值**

`apps/analysis/services/file_correlation.py`：

```python
    ignore_no_limit: bool = False
    ignore_no_data: bool = False
```

同文件注释更新：`:180-181` 的「（默认勾选）」→「（默认关闭）」；`:205-206` 的「（默认勾选，非 limits-only 时）」→「（默认关闭，非 limits-only 时）」。

`apps/analysis/views/file_correlation_views.py`：

```python
        ignore_no_limit=_bool_param('ignore_no_limit', False),
        ignore_no_data=_bool_param('ignore_no_data', False),
```

docstring 同步：`:61-62` 请求体示例 `"ignore_no_limit": true, "ignore_no_data": true` → `false`；`_parse_fc_config` docstring（:194-197）中「ignore_no_limit / ignore_no_data\n    checked」→「ignore_no_limit / ignore_no_data\n    unchecked（默认不勾选）」。

- [ ] **Step 4: 审计并修正依赖旧默认值的存量测试（恰好 2 处）**

`tests_file_correlation_service.py::test_ignore_no_limit_filters_params_without_limits` 第一段断言显式传参：

```python
        r = compute_file_correlation(df1, meta, df2, meta,
                                     FileCorrelationConfig(ignore_no_limit=True))
```

`tests_file_correlation.py::test_export_ignore_no_data_filters_params` 第一段调用显式传参：

```python
        resp = self._call_export({1: df1, 2: df2}, body={'ignore_no_data': True})
```

（注释「默认 ignore_no_data=True →」同步改为「显式 ignore_no_data=True →」。）

- [ ] **Step 5: 跑两个测试模块确认全绿**

```bash
python manage.py test apps.analysis.tests_file_correlation_service apps.analysis.tests_file_correlation -v 1
```
Expected: OK

- [ ] **Step 6: 提交**

```bash
git add apps/analysis/services/file_correlation.py apps/analysis/views/file_correlation_views.py apps/analysis/tests_file_correlation_service.py apps/analysis/tests_file_correlation.py
git commit -m "feat(analysis): file correlation ignore 开关默认改为不勾选"
```

---

### Task 3: 后端 serials 端点免整表拷贝（TDD）

**Files:**
- Modify: `apps/analysis/services/file_correlation.py:108-118`（`list_common_serials`）
- Modify: `apps/analysis/views/file_correlation_views.py:35-49`（serials 端点）、新增 `_load_fc_serial_series`
- Test: `apps/analysis/tests_file_correlation_service.py`、`apps/analysis/tests_file_correlation.py` 无需改（endpoint mock 测试继续过）

- [ ] **Step 1: 写失败测试（Series 签名）**

`tests_file_correlation_service.py::FileCorrelationServiceTests` 追加：

```python
    def test_list_common_serials_accepts_series(self):
        from apps.analysis.services.file_correlation import list_common_serials

        s1 = pd.to_numeric(pd.Series([3, 1, 2], name='Serial_No'), errors='coerce')
        s2 = pd.to_numeric(pd.Series([2, 1, 99], name='Serial_No'), errors='coerce')
        self.assertEqual(list_common_serials(s1, s2), [1, 2])
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.analysis.tests_file_correlation_service.FileCorrelationServiceTests.test_list_common_serials_accepts_series -v 1
```
Expected: FAIL/ERROR（现实现按 `ate_df['__serial__']` 取列，Series 传入抛 KeyError）

- [ ] **Step 3: 实现**

`apps/analysis/services/file_correlation.py` 的 `list_common_serials` 替换为：

```python
def list_common_serials(ate_ser: pd.Series, bench_ser: pd.Series) -> List[int]:
    """Sorted common serial numbers of the two files (same ``__serial__``
    semantics as :func:`compute_file_correlation`).

    接收已数值化的序列 Series（``pd.to_numeric(..., errors='coerce')`` 的
    产物）——serials 端点只消费序列列，不值得为此整表 copy（大文件下整表
    拷贝是主要开销）。
    """
    return sorted(
        set(ate_ser.dropna().astype(int)) & set(bench_ser.dropna().astype(int)))
```

`apps/analysis/views/file_correlation_views.py`：serials 端点（:36-49）替换为：

```python
    @action(detail=False, methods=['post'])
    def file_correlation_serials(self, request):
        """List the common serial numbers of two files (serial picker data).

        Request body: ``{file1_id, file2_id}``.
        Response: ``{serials: [int, ...], total: int}`` — ascending,
        same ``__serial__`` semantics as the full ``file_correlation``
        computation (交集、数值化), so the picker and the analysis agree.

        只消费序列列：不做整表 copy（大文件下 copy 是主要开销），
        ``pd.to_numeric`` 返回新 Series 不触碰 LRU 缓存原帧。
        """
        sers, err = _load_fc_serial_series(request)
        if err is not None:
            return Response(err[0], status=err[1])

        serials = list_common_serials(sers['ATE'], sers['Bench'])
        return Response({'serials': serials, 'total': len(serials)})
```

在 `_load_file_correlation_pair` 之后新增：

```python
def _load_fc_serial_series(request):
    """Load only the numeric serial Series of two files (serials 端点专用).

    与 ``_load_file_correlation_pair`` 相同的文件解析与错误契约
    （need_two_files / parse_failed / no_serial_column），但不注入
    ``__serial__``、不做整表 copy。Returns ``(sers, err)``，``sers`` 为
    ``{'ATE': Series, 'Bench': Series}``。
    """
    file1_id = request.data.get('file1_id')
    file2_id = request.data.get('file2_id')
    if not file1_id or not file2_id:
        return None, ({'error': 'need_two_files'}, 400)

    sers = {}
    loaded = 0
    for fid, label in [(file1_id, 'ATE'), (file2_id, 'Bench')]:
        df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
        df, metadata, fmt = get_cached_parsed_file(int(fid), request.user.pk, df_obj)
        if df is None:
            continue
        loaded += 1
        serial_col = get_serial_column(df)
        if serial_col:
            # pd.to_numeric 返回新 Series；缓存 DataFrame 只读不变量不受影响
            sers[label] = pd.to_numeric(df[serial_col], errors='coerce')

    if loaded < 2:
        return None, ({'error': 'parse_failed'}, 400)
    if len(sers) < 2:
        return None, ({'error': 'no_serial_column'}, 400)

    return sers, None
```

- [ ] **Step 4: 跑两个测试模块确认全绿（含端点契约回归）**

```bash
python manage.py test apps.analysis.tests_file_correlation_service apps.analysis.tests_file_correlation -v 1
```
Expected: OK（`test_returns_ascending_common_serials` 等 endpoint mock 用例不变即过）

- [ ] **Step 5: 提交**

```bash
git add apps/analysis/services/file_correlation.py apps/analysis/views/file_correlation_views.py apps/analysis/tests_file_correlation_service.py
git commit -m "perf(analysis): serials 端点免整表拷贝，list_common_serials 改收 Series"
```

---

### Task 4: 后端 Excel「Limit对比」sheet auto_filter（TDD）

**Files:**
- Modify: `apps/export/excel_builders.py:237-245`（Limit sheet 数据行循环之后、`set_panes` 之前）
- Test: `apps/analysis/tests_file_correlation.py`（`FileCorrelationExportTests`）

- [ ] **Step 1: 写失败测试**

```python
    def test_export_limit_sheet_has_auto_filter(self):
        import io
        from openpyxl import load_workbook

        df1 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        df2 = pd.DataFrame({'Serial_No': [1], 'ParamA': [1.0]})
        resp = self._call_export({1: df1, 2: df2})
        body = self._body(resp)
        self.assertEqual(resp.status_code, 200, body[:500])
        ws = load_workbook(io.BytesIO(body))['Limit对比']
        # 表头行 2 + 1 行数据（行 3）→ 筛选范围 A2:I3（2026-09-09 需求 6）
        self.assertEqual(ws.auto_filter.ref, 'A2:I3')
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python manage.py test apps.analysis.tests_file_correlation.FileCorrelationExportTests.test_export_limit_sheet_has_auto_filter -v 1
```
Expected: FAIL（`ws.auto_filter.ref` 为 None）

- [ ] **Step 3: 实现**

`apps/export/excel_builders.py` Limit sheet 部分，数据行 for 循环（:211-237）结束后、`limit_widths` 之前插入：

```python
    # 判定列筛选（2026-09-09 需求 6）：表头行 2 到最后一条数据行；仅 Limit对比 sheet
    if row_idx > 3:
        f.auto_filter(sheet_limit, f'A2:I{row_idx - 1}', [])
```

- [ ] **Step 4: 跑测试确认通过 + export 套件回归**

```bash
python manage.py test apps.analysis.tests_file_correlation apps.export -v 1
```
Expected: OK（export 全量无回归；`export_xlsx_optimized` 的既有 auto_filter 用例不受影响）

- [ ] **Step 5: 提交**

```bash
git add apps/export/excel_builders.py apps/analysis/tests_file_correlation.py
git commit -m "feat(export): Limit对比 sheet 增加 auto_filter"
```

---

### Task 5: 前端 DiffRule 契约扩展 + 规则文案 map

**Files:**
- Modify: `frontend/src/types/index.ts:161-162`、`:214-222`
- Modify: `frontend/src/pages/data/composables/useFileCorrelation.ts:69-79`（buildPayload）
- Modify: `frontend/src/pages/data/components/correlation/FileCorrelationSection.vue:115-121`（options 加 tightPct）
- Modify: `frontend/src/pages/data/components/correlation/FileCorrelationTable.vue:12`、`FileCorrelationLimitTable.vue:9`、`FileCorrelationSummary.vue:65-66`（文案换 map）

- [ ] **Step 1: types/index.ts**

```ts
/** 文件相关性对比：LSL/USL Diff 标红规则（A: 差值全为0才pass 默认 / B: B的limit不更紧才pass / C: wider+收紧容差） */
export type DiffRule = 'zero' | 'wider' | 'tight_pct'

/** Limit Diff 规则文案（数据视图 / Limit 视图 / 汇总卡共用） */
export const DIFF_RULE_LABELS: Record<DiffRule, string> = {
  zero: '规则A：Diff 必须为 0',
  wider: '规则B：B 的 Limit 不更紧',
  tight_pct: '规则C：B 收紧 ≤ 容差% 允许',
}
```

`FileCorrelationOptions`（:214-222）加字段：

```ts
export interface FileCorrelationOptions {
  threshold: number
  diffRule: DiffRule
  /** 用户勾选的对比序列（默认前 10 颗；空数组 = 仅对比 Limit） */
  serials: number[]
  /** tight_pct 规则的收紧容差（%），仅 diffRule='tight_pct' 时后端消费 */
  tightPct: number
  ignoreNoLimit: boolean
  ignoreNoData: boolean
}
```

- [ ] **Step 2: buildPayload 透传**

`useFileCorrelation.ts` 的 `buildPayload` 加一行：

```ts
      diff_rule: opts.diffRule,
      tight_pct: opts.tightPct,
```

- [ ] **Step 3: Section options 加默认值（暂无 UI，恒 30）**

`FileCorrelationSection.vue:115-121`：

```ts
const options = ref<FileCorrelationOptions>({
  threshold: 3,
  diffRule: 'zero',
  serials: [],
  tightPct: 30,
  ignoreNoLimit: true,
  ignoreNoData: true,
})
```

- [ ] **Step 4: 三处规则文案换 map**

`FileCorrelationTable.vue:12` 与 `FileCorrelationLimitTable.vue:9` 的插值改为：

```vue
{{ DIFF_RULE_LABELS[diffRule] }}
```

两个组件的 type import 行加 `DIFF_RULE_LABELS`（来源 `../../../../types`）。`FileCorrelationSummary.vue:65-66` 改为：

```ts
import { DIFF_RULE_LABELS } from '../../../../types'

const diffRuleLabel = computed(() => DIFF_RULE_LABELS[props.diffRule])
```

- [ ] **Step 5: 构建验证**

```bash
cd frontend && npm run build
```
Expected: vue-tsc + vite 通过

- [ ] **Step 6: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/pages/data/composables/useFileCorrelation.ts frontend/src/pages/data/components/correlation/FileCorrelationSection.vue frontend/src/pages/data/components/correlation/FileCorrelationTable.vue frontend/src/pages/data/components/correlation/FileCorrelationLimitTable.vue frontend/src/pages/data/components/correlation/FileCorrelationSummary.vue
git commit -m "refactor(data): DiffRule 扩展 tight_pct + 规则文案统一 map"
```

---

### Task 6: 规则C UI（radio + 收紧容差输入）+ ignore 默认翻转

**Files:**
- Modify: `frontend/src/pages/data/components/correlation/FileCorrelationControls.vue`
- Modify: `frontend/src/pages/data/components/correlation/FileCorrelationSection.vue:19-20`、`:115-121`

- [ ] **Step 1: Controls 模板**

规则 radio（:35-45）加第三项 + 条件输入（放在 `.fc-opt` 规则块之后）：

```vue
    <div class="fc-opt">
      <label class="fc-opt-label">Limit Diff 规则</label>
      <el-radio-group
        :model-value="diffRule"
        size="small"
        @update:model-value="(v: string | number | boolean) => emit('update:diffRule', v as DiffRule)"
      >
        <el-radio-button value="zero">A：Diff 必须为 0</el-radio-button>
        <el-radio-button value="wider">B：B 的 Limit 不更紧</el-radio-button>
        <el-radio-button value="tight_pct">C：收紧 ≤ x%</el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="diffRule === 'tight_pct'" class="fc-opt">
      <label class="fc-opt-label">收紧容差 (%)</label>
      <el-input-number
        :model-value="tightPct"
        :min="0"
        :max="100"
        :step="0.1"
        :precision="1"
        size="small"
        style="width: 92px"
        @update:model-value="(v: number | undefined) => emit('update:tightPct', v ?? 30)"
      />
    </div>
```

- [ ] **Step 2: Controls script**

Props 接口加 `tightPct: number`；emits 加：

```ts
  (e: 'update:tightPct', v: number): void
```

- [ ] **Step 3: Section 接线 + 默认翻转**

模板（:17-20 区域）加 `v-model:tight-pct="options.tightPct"`；options 默认值（Task 5 已加 tightPct）把两处翻转：

```ts
  ignoreNoLimit: false,
  ignoreNoData: false,
```

- [ ] **Step 4: 构建验证**

```bash
cd frontend && npm run build
```
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/correlation/FileCorrelationControls.vue frontend/src/pages/data/components/correlation/FileCorrelationSection.vue
git commit -m "feat(data): 规则C 收紧容差 UI + ignore 开关默认不勾选"
```

---

### Task 7: 序列下拉渲染截断 300（大文件防冻结）

**Files:**
- Modify: `frontend/src/pages/data/components/correlation/SerialSelector.vue:25-29`（footer）、`:63-64`（常量）、`:76-77`（filteredItems）

- [ ] **Step 1: 实现**

常量（`MAX_SELECTED` 旁）：

```ts
/** 下拉渲染上限：el-option 是完整组件实例，序列上万时挂载即冻结主线程；
 * 渲染截断，全选/Enter 全选仍作用于完整集合 */
const SERIAL_RENDER_CAP = 300
```

`filteredItems`（:76-77）：

```ts
/** 下拉选项：有关键字显示过滤结果，否则全量；渲染层一律截断到前 N */
const filteredItems = computed(() =>
  (kw.value ? matches.value : props.options).slice(0, SERIAL_RENDER_CAP))
```

footer（:25-29）替换为：

```vue
      <template #footer>
        <div v-if="kw && matches.length > 0" class="match-hint">
          匹配 {{ matches.length }} 项{{ matches.length > SERIAL_RENDER_CAP ? `（显示前 ${SERIAL_RENDER_CAP}）` : '' }}，按 Enter 全选
        </div>
        <div v-else-if="!kw && options.length > SERIAL_RENDER_CAP" class="match-hint">
          仅显示前 {{ SERIAL_RENDER_CAP }} 项，可搜索或直接全选
        </div>
      </template>
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```
Expected: 通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/data/components/correlation/SerialSelector.vue
git commit -m "perf(data): 序列下拉渲染截断 300，防大文件冻结"
```

---

### Task 8: Limit 视图判定列排序

**Files:**
- Modify: `frontend/src/pages/data/components/correlation/FileCorrelationLimitTable.vue:58-64`（判定列）、script（sort 函数）

- [ ] **Step 1: 实现**

判定列（:58）加 sortable 与自定义排序：

```vue
      <el-table-column label="判定" width="92" align="center" sortable :sort-method="verdictSort">
```

script 追加（`rowVerdict` 之后）：

```ts
/** 判定列排序：FAIL rank 0 / PASS rank 1 → 升序 FAIL 在前；同判定保持原 rows 序 */
function verdictSort(a: FileCorrelationRow, b: FileCorrelationRow): number {
  const ra = rowVerdict(a) === 'FAIL' ? 0 : 1
  const rb = rowVerdict(b) === 'FAIL' ? 0 : 1
  return ra - rb
}
```

- [ ] **Step 2: 构建验证**

```bash
cd frontend && npm run build
```
Expected: 通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/data/components/correlation/FileCorrelationLimitTable.vue
git commit -m "feat(data): Limit 视图判定列排序（FAIL 优先）"
```

---

### Task 9: SFTP 传输互斥

**Files:**
- Modify: `frontend/src/pages/sftp/SftpBrowser.vue`（computed + 模板传参）
- Modify: `frontend/src/pages/sftp/components/SftpFileTable.vue`（props + 按钮 disabled）
- Modify: `frontend/src/pages/sftp/components/SftpBatchActions.vue`（props + 按钮 disabled）

- [ ] **Step 1: SftpBrowser 加聚合态并下传**

script（`downloadingRows` 定义附近）：

```ts
/** 传输互斥：后端按用户复用同一条 paramiko 连接（非线程安全），任意两类
 * 传输并发（SSE 单文件/SSE 目录/批量 POST）都会在共享 channel 上打架，
 * 故同时只允许一个下载（2026-09-09 用户拍板）。 */
const transferActive = computed(() =>
  fileDownloading.value || dirDownloading.value ||
  batchDownloading.value || batchParsing.value)
```

模板：`<SftpBatchActions ... :transfer-active="transferActive" ...>`；`<SftpFileTable ... :transfer-active="transferActive" ...>`。

- [ ] **Step 2: SftpFileTable**

Props 加 `transferActive?: boolean`；三个下载类按钮（:49-56 下载、:57-65 解析、:69-77 目录下载）各加 `:disabled="transferActive"`（保留原 `:loading`）。

- [ ] **Step 3: SftpBatchActions**

Props 加 `transferActive?: boolean`；「批量下载」「批量下载解析」两个按钮各加 `:disabled="transferActive"`。

- [ ] **Step 4: 构建验证**

```bash
cd frontend && npm run build
```
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/sftp/SftpBrowser.vue frontend/src/pages/sftp/components/SftpFileTable.vue frontend/src/pages/sftp/components/SftpBatchActions.vue
git commit -m "fix(sftp): 传输互斥——下载进行中禁用所有下载入口"
```

---

### Task 10: SFTP 下载取消按钮 + 取消冷却

**Files:**
- Modify: `frontend/src/pages/sftp/components/SftpDownloadProgress.vue`
- Modify: `frontend/src/pages/sftp/SftpBrowser.vue`（cancel 函数 + cooldown + 模板接 emit）

- [ ] **Step 1: 进度卡加取消按钮**

`SftpDownloadProgress.vue` 模板 `progress-info` 替换为（右侧组：统计 + 取消）：

```vue
    <div class="progress-info">
      <span class="progress-title">
        <el-icon><Download /></el-icon>
        {{ mode === 'file' ? `正在下载 ${progress.currentFile}` : '正在下载目录...' }}
      </span>
      <div class="progress-right">
        <span class="progress-stats" v-if="mode === 'dir'">
          {{ progress.current }}/{{ progress.total }} 文件 ·
          {{ formatBytes(progress.bytes_done) }} / {{ formatBytes(progress.total_bytes) }}
        </span>
        <span class="progress-stats" v-else>{{ formatBytes(progress.bytes_done) }} / {{ formatBytes(progress.total_bytes) }}</span>
        <el-tooltip content="取消下载" placement="top">
          <el-button
            class="dl-cancel-btn"
            :icon="Close"
            size="small"
            circle
            aria-label="取消下载"
            @click="emit('cancel')"
          />
        </el-tooltip>
      </div>
    </div>
```

script：import `Close` 图标（`@element-plus/icons-vue`），defineProps 下加：

```ts
const emit = defineEmits<{ (e: 'cancel'): void }>()
```

style 追加：

```css
.progress-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dl-cancel-btn {
  color: var(--text-2);
  border-color: var(--border-2);
}
.dl-cancel-btn:hover {
  color: var(--error);
  border-color: var(--error);
}
```

- [ ] **Step 2: SftpBrowser 接 cancel + 冷却**

script（download 区域）：

```ts
/** 取消冷却：abort 后后端生成器要到下一个 yield 边界才收到 GeneratorExit
 * 并 invalidate 连接，立即再开新传输会在共享连接上与收尾中的旧传输竞态
 * （本地半秒内收尾，1.2s 足够）。 */
const transferCooldown = ref(false)
let cooldownTimer: ReturnType<typeof setTimeout> | null = null

function startCooldown() {
  transferCooldown.value = true
  if (cooldownTimer) clearTimeout(cooldownTimer)
  cooldownTimer = setTimeout(() => { transferCooldown.value = false; cooldownTimer = null }, 1200)
}

function cancelFileDownload() {
  fileAbortCtrl?.abort()
  // AbortError 被 api 层静默吞掉 → catch 不触发，必须显式复位进度卡
  fileDownloading.value = false
  startCooldown()
}

function cancelDirDownload() {
  dirAbortCtrl?.abort()
  dirDownloading.value = false
  startCooldown()
}
```

`transferActive` computed（Task 9 定义处）追加冷却项（注意：`transferCooldown` 等
ref/函数声明需放在该 computed **之前**，与 Task 9 的定义块合并为一处）：

```ts
const transferActive = computed(() =>
  fileDownloading.value || dirDownloading.value ||
  batchDownloading.value || batchParsing.value || transferCooldown.value)
```

`onBeforeUnmount`（:148-155）加：

```ts
  if (cooldownTimer) { clearTimeout(cooldownTimer); cooldownTimer = null }
```

模板两个进度卡接事件：

```vue
      <SftpDownloadProgress
        v-if="fileDownloading"
        mode="file"
        :progress="fileProgress"
        @cancel="cancelFileDownload"
      />
      <SftpDownloadProgress v-if="dirDownloading" mode="dir" :progress="dlProgress" @cancel="cancelDirDownload" />
```

- [ ] **Step 3: 构建验证**

```bash
cd frontend && npm run build
```
Expected: 通过；`SftpBrowser.vue` 行数 <600（现 504 + ~25）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/sftp/components/SftpDownloadProgress.vue frontend/src/pages/sftp/SftpBrowser.vue
git commit -m "feat(sftp): 下载进度卡取消按钮（abort + 1.2s 收尾冷却）"
```

---

### Task 11: e2e file-correlation.spec.ts（默认值 / 规则C / 判定排序）

**Files:**
- Modify: `frontend/e2e/data/file-correlation.spec.ts:65-67`（默认勾选断言）、第一个用例（规则C 控件）、新增排序用例

种子事实（已核实 `Data/BPD60320_FT.csv` vs `Data/SampleData/Buyoff/BPD60320_QA1.csv` 的 Min/Max 行）：既有相同 limit 列（如 7/13、0/4）也有不同列（如 -50 vs -70）→ 默认 zero 规则下 FAIL 与 PASS 行都必然存在，排序断言确定性成立。

- [ ] **Step 1: 反转默认勾选断言（第一个用例 :65-67）**

```ts
    // ignore no limit / ignore no data 默认不勾选（2026-09-09 需求 5）
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Limit' })).not.toHaveClass(/is-checked/)
    await expect(section.locator('.el-checkbox').filter({ hasText: 'Ignore No Data' })).not.toHaveClass(/is-checked/)
```

- [ ] **Step 2: 第一个用例追加规则C控件断言（判定默认规则断言之后）**

```ts
    // 规则 C：选中后出现「收紧容差」输入（默认 30.0），切回 A 后隐藏
    await ruleGroup.locator('.el-radio-button').filter({ hasText: 'C：收紧' }).click()
    const tol = section.locator('.fc-opt').filter({ hasText: '收紧容差' }).locator('.el-input-number input')
    await expect(tol).toBeVisible()
    await expect(tol).toHaveValue('30.0', { timeout: 5000 })
    await ruleGroup.locator('.el-radio-button').filter({ hasText: 'A：Diff 必须为 0' }).click()
    await expect(tol).toHaveCount(0)
```

- [ ] **Step 3: 新增排序用例（describe 内追加）**

```ts
  test('Limit 视图判定列排序：FAIL 排前 → 反向 PASS 在前', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '文件对比' }).click()

    const section = page.locator('.file-corr-section')
    await expect(section).toBeVisible({ timeout: 10_000 })
    await pickFilePair(section, page)
    await expect(section.locator('.fc-serial-hint')).toContainText(/已选 10 \/ 共 \d+ 颗/, { timeout: 15_000 })

    await section.getByRole('button', { name: '分析', exact: true }).click()
    await expect(section.locator('.fc-table')).toBeVisible({ timeout: 30_000 })

    await section.locator('.el-radio-button').filter({ hasText: 'Limit 对比' }).click()
    const table = section.locator('.fc-table')
    const verdictHeader = table.getByText('判定', { exact: true })
    await expect(verdictHeader).toBeVisible()

    const firstRowVerdict = () =>
      table.locator('.el-table__row').first().locator('.verdict-badge').textContent()

    // 升序（第一次点击）：FAIL rank 0 → 在前（种子对 limit 有同有异，FAIL/PASS 均存在）
    await verdictHeader.click()
    await expect.poll(firstRowVerdict, { timeout: 10_000 }).toBe('FAIL')
    // 降序（第二次点击）：PASS 在前
    await verdictHeader.click()
    await expect.poll(firstRowVerdict, { timeout: 10_000 }).toBe('PASS')
  })
```

- [ ] **Step 4: 跑 e2e**

```bash
cd frontend && npx playwright test data/file-correlation.spec.ts --project=P2
```
Expected: 全绿（存量 5 用例 + 新增 1 用例）

- [ ] **Step 5: 提交**

```bash
git add frontend/e2e/data/file-correlation.spec.ts
git commit -m "test(e2e): file-correlation 默认值/规则C/判定排序用例"
```

---

### Task 12: e2e reconnect.spec.ts（互斥 + 取消）

**Files:**
- Modify: `frontend/e2e/sftp/reconnect.spec.ts`（第二个 describe 追加 1 用例；文件为 serial 模式 + 本地 paramiko 服务器 fixture，root.csv / big.csv / sub1 均由 `helpers/sftpServer.ts` 生成）

- [ ] **Step 1: 新增用例**

```ts
  test('@p1 下载互斥与取消：传输中其它下载入口禁用，取消后恢复并可再下载', async ({ page }) => {
    await gotoApp(page, '/sftp')
    await ensureDisconnected(page)
    await manualConnect(page, server)
    await goRoot(page)

    // 拦住 SSE 请求 3s：进度卡在前端即时渲染（fileDownloading 同步置 true），
    // 后端尚未开始传输 → 断言窗口确定（本地 big.csv 秒传无法人工点击）。
    await page.route('**/sftp/download_file_stream/', async (route) => {
      await new Promise((r) => setTimeout(r, 3000))
      await route.continue().catch(() => {})
    })

    const bigRow = page.locator('.file-table .el-table__row').filter({
      has: page.locator('.file-name', { hasText: 'big.csv' }),
    })
    await bigRow.getByRole('button', { name: '下载' }).click()
    await expect(page.locator('.download-progress-card')).toBeVisible({ timeout: 10_000 })

    // 互斥：其它文件的下载/解析与目录下载全部禁用
    const rootRow = page.locator('.file-table .el-table__row').filter({
      has: page.locator('.file-name', { hasText: 'root.csv' }),
    })
    await expect(rootRow.getByRole('button', { name: '下载' })).toBeDisabled()
    await expect(rootRow.getByRole('button', { name: '解析' })).toBeDisabled()
    const sub1Row = page.locator('.file-table .el-table__row').filter({
      has: page.locator('.file-name', { hasText: 'sub1' }),
    })
    await expect(sub1Row.getByRole('button', { name: '下载' })).toBeDisabled()

    // 取消：进度卡立即消失（AbortError 被前端吞掉 → 显式复位）
    await page.locator('.dl-cancel-btn').click()
    await expect(page.locator('.download-progress-card')).toBeHidden({ timeout: 5_000 })

    // 冷却期（1.2s，等后端生成器收尾）结束后按钮恢复
    await expect(rootRow.getByRole('button', { name: '下载' })).toBeEnabled({ timeout: 10_000 })
    await page.unroute('**/sftp/download_file_stream/')

    // 状态干净：再下载 root.csv 正常完成（证明连接/状态未被取消破坏）
    await rootRow.getByRole('button', { name: '下载' }).click()
    await expect(page.getByText(/已导入: root\.csv/)).toBeVisible({ timeout: 60_000 })

    await disconnect(page)
  })
```

- [ ] **Step 2: 跑 e2e**

```bash
cd frontend && npx playwright test sftp/reconnect.spec.ts --project=P1
```
Expected: 全绿（存量用例 + 新增）

- [ ] **Step 3: 提交**

```bash
git add frontend/e2e/sftp/reconnect.spec.ts
git commit -m "test(e2e): sftp 下载互斥与取消用例"
```

---

### Task 13: 全量验证 + 收尾落账

**Files:**
- Modify: `docs/tasks/todo.md`（勾选 + Review 段）、必要时 `docs/tasks/lessons.md`

- [ ] **Step 1: 后端全量（串行）**

```bash
python manage.py test apps.analysis apps.export
```
Expected: OK（apps.analysis 现基线 173+，apps.export 无回归）

- [ ] **Step 2: 前端构建**

```bash
cd frontend && npm run build
```
Expected: exit 0

- [ ] **Step 3: e2e 定向回归**

```bash
cd frontend && npx playwright test data/file-correlation.spec.ts --project=P2 && npx playwright test sftp/reconnect.spec.ts sftp/sftp.spec.ts --project=P1
```
Expected: 全绿（存量失败按 R2③ 先隔离复跑判定）；跑完确认 8000/3000 端口无监听残留

- [ ] **Step 4: 双主题检查**

新增 UI（取消图标按钮、规则C radio、收紧容差输入）全部走语义 token（`var(--text-2)` / `var(--error)` / `var(--border-2)`），EP 内建组件随全局主题块生效；如条件允许在 dev 环境目测 dark/light 两态。

- [ ] **Step 5: todo.md 勾选全部条目 + 追加 Review 段（验证账目、偏离、遗留），有新教训记 lessons.md**

- [ ] **Step 6: 提交**

```bash
git add docs/tasks/todo.md docs/tasks/lessons.md
git commit -m "docs(tasks): 2026-09-09 批次 Review 落账"
```

---

## 自查记录（writing-plans Self-Review）

- **Spec 覆盖**：需求1→Task 9；需求2→Task 10；需求3→Task 7（渲染）+ Task 3（后端拷贝）；需求4→Task 1（后端）+ Task 5/6（前端）；需求5→Task 2（后端）+ Task 6（前端）+ Task 11（e2e）；需求6→Task 8（排序）+ Task 4（Excel）+ Task 11（e2e）。无缺口。
- **占位符**：无 TBD/TODO；e2e 排序用例的种子前提已用实际 CSV 数据核实（Min/Max 行比对），写进 Task 11 事实块。
- **类型一致性**：`tight_pct`（API/config）↔ `tightPct`（前端 options/props/emit）一处转换点在 `buildPayload`；`transferActive`、`SERIAL_RENDER_CAP`、`.dl-cancel-btn`、`DIFF_RULE_LABELS` 各任务间名称一致；`_evaluate_diff_rule` 新签名（第 6 参 `tight_pct`）与唯一调用点同步。
- **顺序依赖**：Task 5 先于 Task 6（`FileCorrelationOptions.tightPct` 必填，Section 先加默认值保构建绿）；Task 1 先于 Task 5/6（后端白名单先收 `tight_pct`）；Task 2 的默认翻转独立于 Task 1（其测试显式传 `ignore_no_limit=True` 不受影响）。
