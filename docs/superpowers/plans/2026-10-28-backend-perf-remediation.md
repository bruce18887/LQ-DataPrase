# 后端性能整改实施计划（2026-10-28）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 10 份后端逐行审查报告里的 8 条 P0 / 59 条 P1 落成可验证的代码改动，优先消除「每请求重复计算」「每请求多余 DB 往返」「整表/整帧物化」「作业状态机与清理缺陷」四类机制性浪费。

**Architecture:** 后端是 Django 6.0.9 + SQLite 的多 app 结构，桌面档由 `standalone.py` 以 `call_command('runserver', …, '--noreload')` 起单进程线程服务器，服务器档为 Linux systemd + standalone。重活已作业化进 `apps/jobs`（常驻进程池 `MAX_POOL_WORKERS = min(4, …)` + 下载线程 lane `MAX_DOWNLOAD_WORKERS = 2`）。本计划不引入新框架层，只在既有 owner 上补计算/收敛读取/收窄载荷：解析产物（`apps/datafiles/services.py` 的 `_BytesLRUCache` 体系）是列级元信息的唯一归属点，`apps/accounts/services.py` 是用户设置的唯一读取入口，`apps/jobs/executor.py` 是作业状态机的唯一改写点。

**Tech Stack:** Python 3.12/3.13、Django 6.0.9、djangorestframework、pandas/numpy、openpyxl + excelize(Go FFI)、paramiko、`scipy.stats`；测试为 Django unittest runner（`test/backend/`、`apps/*/tests*.py`）+ Playwright e2e（`frontend/e2e/`）+ vitest T2（`frontend/test/unit/`）。

**Spec（证据随计划一起走）:** `tasks/perf-review-2026-10-27/00-INDEX.md` 与同目录 `S1-*.md … S10-*.md`（**gitignored，故本文件把每个任务的 位置/机理/改法/会红测试逐条搬进正文**，下游只读本文件即可干活）；实测基线 `docs/reference/perf-baseline-2026-10-17.md`（入库）；判据与门禁 `docs/reference/testing-gates.md`（入库，唯一事实来源）。

## Global Constraints（每个任务隐含包含本节）

- 单个被跟踪 `.py`/`.ts`/`.vue` ≤ **600 行**（判据 `scripts/line-limit.mjs` + `frontend/test/unit/lineLimit.spec.ts`）。`EXEMPT` 冻了精确行数的 5 个文件**多一行即红**：`apps/datafiles/tests.py`(1968)、`apps/jobs/tests_jobs.py`(846)、`frontend/e2e/data/view-data.spec.ts`(1802)、`frontend/e2e/data/data.spec.ts`(1042)、`test/backend/test_sftp_search_engine_stream.py`(642) ⇒ 新断言一律放 `test/backend/` 下的新文件或不超阈的既有文件，**不许加行进这 5 个，也不许新增豁免**。
- DRF 响应走统一异常处理器 + 稳定机器码（`apps/common/errors.py` 的 `error_response`）。凡改响应字段/新增键/新增错误码 ⇒ 本计划标为 **契约变更**，必须与前端同批改并同步 help 文案与用户指南（语义放宽不给可见提示 = 缺陷）。
- CPU worker 侧禁 Django：`apps/jobs/runner.py` 只能 import 无 Django 的模块；`apps/datafiles/services.py` **带** `apps.datafiles.models`（第 16 行）⇒ 它在 worker 侧不可用，把东西塞进它只会污染 worker 隔离；`apps/analysis/services/statistics/helpers.py` 是无 Django 的一侧，可用。
- 解析缓存键是**内容坐标** `(绝对路径, mtime_ns, format_type)`，**不含 `file_id`/`owner_id`**（`apps/datafiles/services.py:214` 注释）；解析失败值不入缓存。任何新缓存沿用该键形，别把 user 放回键里。
- 远端 grep 现用 `-r` 是**有意保留**（`apps/sftp/search/shell_grep.py:41-45` 的平价理由）；真机软链接比对定夺前**不得改成 `-R`**。
- SFTP 批量下载走每作业临时连接、绝不碰 per-user 常驻池（paramiko 非线程安全），并发上限 2 防撞 `sshd MaxStartups`；禁止嵌套进程池（作业路径必须 `workers=1`）。
- 数值入口按 R4：`pd.to_numeric(..., errors='coerce').astype(float)` + `np.isfinite()` 向量化；NaN→JSON null 的前端侧已有护栏，后端不许改判据口径。
- 共享工作树红线：禁裸 `git stash`；**逐文件 `git add <path>`**（不许 `git add -A/.`）；`git status` 先读现状；另有会话正在改 `frontend/`，本计划**零前端文件改动**（除标了「前端同步」的任务，那些要单独点名）。
- 写进任何被跟踪文档/注释的样例数据用 `$BIG`/`$MID` 占位（275MB = 35,246 行 × 1,702 列；mid = 19.5MB），不出现私有文件名。
- 门禁节奏（判据正文在 `docs/reference/testing-gates.md`）：每批 commit 前 `cd frontend && npm run test:e2e:affected`；波次收口前 `node scripts/e2e_pool.mjs --slots=4` + 后端全量（**按 testing-gates §4 的夜跑同款 label 导文件，勿手打 `apps.*`**）。`NO AFFECTED TESTS` 不是绿灯。判跑批成败读日志末尾 `RESULT:` 行，不取 `$?`。
- 后端全量跑完必须核对 `Ran N` 与基线例数（历史上测试文件里的 pytest import 会让 Django runner **静默少收集**却退 0）。

---

## 波次 A · 零契约热点（先做，收益/风险比最高）

### Task A1: `compute_common_params` 的 O(n_cols²) 消除

**Files:**
- Modify: `apps/analysis/services/data_services/multi_lot.py:43-44`
- Test: `test/backend/test_multi_lot_param_scan.py`（新建）

**Interfaces:**
- Consumes: `apps/analysis/services/statistics/limits.py:20` 的 `get_columns_with_limits(df, metadata) -> List[str]`（签名不变）
- Produces: 无新接口（纯局部变量提升）

- [ ] **Step 1: 写失败测试**——用调用计数钉「每个文件只扫一遍全列」，并带对照组（`ignore_no_limit=False` 分支不应调用它）：

```python
# test/backend/test_multi_lot_param_scan.py
from django.test import SimpleTestCase
import pandas as pd
from apps.analysis.services import multi_lot as ml
from apps.analysis.services.data_services import multi_lot as mod


class CommonParamScanCountTests(SimpleTestCase):
    def _frame(self, n_cols):
        cols = {f'P{i}': [1.0, 2.0] for i in range(n_cols)}
        return pd.DataFrame(cols)

    def _metadata(self, n_cols):
        # 每列都给两侧数值限值，保证 ignore_no_limit 分支不会因"无限值"提前短路
        return {'mins': {f'P{i}': '0' for i in range(n_cols)},
                'maxs': {f'P{i}': '9' for i in range(n_cols)}}

    def test_get_columns_with_limits_called_once_per_file(self):
        calls = []
        original = ml.get_columns_with_limits

        def spy(df, metadata):
            calls.append(len(df.columns))
            return original(df, metadata)

        # patch 实际消费模块的绑定（from x import y 创建独立绑定）
        self.addCleanup(setattr, mod, 'get_columns_with_limits', original)
        mod.get_columns_with_limits = spy

        df, md = self._frame(20), self._metadata(20)
        mod.compute_common_params([(1, df, md, 'a.csv')], ignore_no_limit=True)
        self.assertEqual(calls, [20])          # 精确计数，不是 >0

    def test_ignore_no_limit_false_never_scans(self):
        # 对照组：这一档必须一次都不调用
        ...
```

- [ ] **Step 2: 跑测试确认失败** — `python manage.py test test.backend.test_multi_lot_param_scan -v 2`；预期 FAIL，`calls` 长度为 **20**（实际会是 20 次以上：每列各调一次，且 `set(...)` 也在每列重建）。
- [ ] **Step 3: 改实现**（`multi_lot.py:43-44`，两行换三行）：

```python
        if ignore_no_limit:
            limited = set(get_columns_with_limits(df, metadata))
            numeric_cols = [c for c in numeric_cols if c in limited]
```

- [ ] **Step 4: 跑测试确认通过** — 同 Step 2 命令，预期 PASS，`Ran 2`。
- [ ] **Step 5: 等价性自证**（不许只靠新用例）：同一夹具下 `ignore_no_limit=True` 的返回值在改前/改后**逐位一致**。做法：`git stash` 禁用，改用 `git show HEAD:apps/analysis/services/data_services/multi_lot.py` 落到 `tasks/perf-review-2026-10-27/_old_multi_lot.py` 旁路 import 对比，比较完删除该临时文件。
- [ ] **Step 6: 提交** — `git add apps/analysis/services/data_services/multi_lot.py test/backend/test_multi_lot_param_scan.py` → `git commit -m "perf(analysis): 多批次公共参数筛选不再每列重扫全表"`

### Task A2: `_sanitize_numeric_params` 去无条件整表拷贝 + 逐参数判定向量化

**Files:**
- Modify: `apps/analysis/views/_helpers.py:110-145`（拷贝在 `:116`，`dropna().empty` 在 `:128`）
- Test: `test/backend/test_sanitize_numeric_params.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `_sanitize_numeric_params(df, params) -> List[str]`（签名与返回语义**不变**）

- [ ] **Step 1: 写等价性 + 形状测试**。等价性判据必须覆盖脆弱形态（R4：bool 列 `Dut_Pass`、全 NaN 列、object 数值列、常量列、重复列名、空串参数名），断言新结果 == 旧结果：

```python
    def test_matches_legacy_behaviour_on_fragile_frames(self):
        legacy = self._legacy_impl()          # 由 git show HEAD: 那份函数体包成闭包
        for df, params in self._cases():      # 8 组脆弱夹具
            self.assertEqual(_sanitize_numeric_params(df, params), legacy(df, params))

    def test_no_full_frame_copy_when_columns_unique(self):
        df = pd.DataFrame({f'P{i}': [1.0, 2.0] for i in range(400)})
        with patch.object(pd.DataFrame, 'loc', side_effect=AssertionError('拷贝')) as loc:
            # 用 columns.duplicated().any() 为假的路径断言根本不走 .loc
```

- [ ] **Step 2: 跑测试确认失败** — `python manage.py test test.backend.test_sanitize_numeric_params -v 2`；预期第二例 FAIL（`AssertionError: 拷贝`），第一例 PASS（旧实现即基线）。
- [ ] **Step 3: 改实现**——守卫照抄同文件 `:167-168` 已有的写法与注释口径；逐参数循环改成「一次向量化 + 只做保序」：

```python
def _sanitize_numeric_params(df, params):
    """Filter params to only those that are valid numeric columns with data."""
    # 无重复列名时不做整表 .loc 拷贝：同文件 _load_df_from_request 已给出量级
    # （10k×188 的一次 .loc ≈ 100ms/请求），而调用方进来的帧通常已去过重。
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]

    present = [p for p in dict.fromkeys(params) if p and str(p).strip() and p in df.columns]
    if not present:
        return []
    sub = df[present]
    has_value = dict(zip(present, sub.notna().any().to_numpy()))
    valid = []
    for p in present:
        col_dtype = sub[p].dtype
        if not has_value[p]:
            continue
        if not pd.api.types.is_numeric_dtype(col_dtype):
            continue
        if pd.api.types.is_bool_dtype(col_dtype):
            continue
        valid.append(p)
    return valid
```

- [ ] **Step 4: 跑测试确认通过** — 两例全 PASS 才算收（等价性例必须保持绿，它证明「行为完全一致」）。
- [ ] **Step 5: 提交** — `git commit -m "perf(analysis): 参数净化去掉无条件整表拷贝并一次向量化判空"`

### Task A3: 分析视图取帧——鉴权前置 + 同一行只查一次 + 多文件 `in_bulk`

**Files:**
- Modify: `apps/analysis/views/_helpers.py:148-173`（`:157` 解析、`:170` 二次 SELECT）
- Modify: `apps/analysis/views/_helpers.py:176-189`（`_load_files_from_request` 的 N 次 SELECT + N 次 `os.path.exists`）
- Test: `test/backend/test_analysis_load_db_count.py`（新建）

**Interfaces:**
- Consumes: `apps/datafiles/services.py` 的 `get_cached_parsed_file(file_id, user_id, datafile=None)`（browse 侧已在用第 3 参形态，见 `apps/datafiles/views/browse_views.py:142`）
- Produces: `_load_df_from_request(request) -> (df, datafile, metadata, error_code)` 四元组形态不变

- [ ] **Step 1: 先量现状再写断言**（不要凭猜写期望值）。跑：

```bash
grep -rn "file_not_found_or_parse_failed\|file_not_found" apps/analysis frontend/e2e | cat
```

把命中的测试/文案逐条读一遍，确认「非本人 file_id」在现实现里回哪个码、有没有用例钉着；把结果记进提交信息。

- [ ] **Step 2: 写失败测试**：`assertNumQueries` 钉住「单文件 1 次 SELECT、N 文件 1 次 SELECT」，并钉「不属于本人的 file_id 不触发解析」——用 monkeypatch 计数器证明鉴权在解析之前：

```python
    def test_single_file_load_uses_one_query(self):
        with self.assertNumQueries(1):
            df, datafile, meta, err = _load_df_from_request(self._request(self.file_b))
        self.assertIsNone(err)

    def test_other_users_file_id_does_not_parse(self):
        parsed = []
        self._patch_get_parsed(lambda *a, **k: parsed.append(a) or (None, None, None))
        _load_df_from_request(self._request(file_id=self.other_file.pk))
        self.assertEqual(parsed, [])      # 承重：解析一次都没发生
```

- [ ] **Step 3: 跑测试确认失败** — 预期 `assertNumQueries` 报 2、第二个例 `parsed` 长度 1。
- [ ] **Step 4: 改实现**：

```python
    datafile = DataFile.objects.filter(pk=file_id, owner=request.user).first()
    if datafile is None:
        return None, None, None, 'file_not_found'
    df, metadata, fmt = get_cached_parsed_file(file_id, request.user.pk, datafile)
    if df is None and fmt is not None:
        return None, None, None, 'file_not_found_or_parse_failed'
    if df is None:
        return None, None, None, 'file_not_found'
    if df.columns.duplicated().any():          # 保留 :163-168 既有守卫与注释
        df = df.loc[:, ~df.columns.duplicated()]
    return df, datafile, metadata, None
```

`_load_files_from_request` 照 `apps/analysis/views/analysis_views.py:286-296` 的既有形态改成一次 `filter(pk__in=file_ids, owner=request.user).in_bulk()`，删掉 `os.path.exists` 预检（`get_cached_parsed_file` 对缺文件已返回 `df=None`），保留 `int()` 守卫与被跳过 id 的记录。

- [ ] **Step 5: 跑测试确认通过** + `npm run test:e2e:affected`（分析页 e2e 覆盖面大，`view-data`/`analysis` 系必须过）。
- [ ] **Step 6: 提交** — `git commit -m "perf(analysis): 取帧先鉴权后解析、同行单次 SELECT 并多文件改 in_bulk"`

### Task A4: 列级元信息随解析只算一次（browse 首屏 P0 + histogram P0 一处根治）

**Files:**
- Modify: `apps/datafiles/services.py`（`_parse_file_uncached` 约 `:248`、`metadata['col_meta']` 赋值处约 `:258`、`put_cached_parsed_file` 补 `col_meta` 的同款位置约 `:343-345`）
- Modify: `apps/datafiles/views/browse_views.py:159-186`
- Modify: `apps/analysis/views/analysis_views.py:113-122`
- Test: `test/backend/test_column_profile_cache.py`（新建）

**Interfaces:**
- Consumes: `apps/analysis/services/statistics/helpers.py:38/77` 的 `get_site_column` / `get_serial_column`（browse_views 已从该路径 import，`services.py` 第 11 行已在 import 同一包，无环）
- Produces: `metadata['column_profile'] = {'site_options': list, 'numeric_columns': list, 'system_columns': list, 'serial_column': str|None}`，随解析写入、按内容坐标缓存；`apps/datafiles/services.py` 的字节体积核算必须把这只 dict 计进去（与 `col_meta` 同址）

- [ ] **Step 1: 写等价性测试（先钉值不变）**——对同一份帧，「走缓存取到的四件套」必须逐字等于「现在 `browse_views.py:159-186` 那段现算的结果」。夹具用合成帧，形态必须含：全 NaN 列、bool 列 `Dut_Pass`、数字字符串 object 列（`SW_Bin`）、常量列、`format_type` 四种取值：

```python
class ColumnProfileEquivalenceTests(SimpleTestCase):
    def test_profile_equals_inline_computation(self):
        for df, fmt in self._cases():
            self.assertEqual(_column_profile(df, fmt)['numeric_columns'],
                             _inline_numeric_columns(df))   # 把现 :166-176 那段原样搬成测试内的基线
```

- [ ] **Step 2: 写承重测试（钉"只算一次"）**——`_column_profile` 调用计数：同一 (路径, mtime_ns, format_type) 连续 3 次 `page==1` 请求 ⇒ 计数 **1**；换 mtime ⇒ 计数 **2**。这条是"你触发"且"你坏"的判据，缺它就只是重构。
- [ ] **Step 3: 跑测试确认失败**（`_column_profile` 尚不存在 ⇒ ImportError/AttributeError）。
- [ ] **Step 4: 实现**：在 `services.py` 加模块级 `_column_profile(df, format_type)`（把 `browse_views.py:160-186` 的四段原样搬入，含 `NON_NUMERIC_COLUMNS` 与 `SYSTEM_COLUMNS.get(format_type, [])` 的口径与既有注释），在 `_parse_file_uncached` 的 `col_meta` 旁 `metadata['column_profile'] = _column_profile(df, format_type)`，`put_cached_parsed_file`（写透侧，含上传路径）同款补一行；`browse_views.py` 的 `page == 1` 块改为：

```python
        if page == 1:
            profile = metadata.get('column_profile') if isinstance(metadata, dict) else None
            if profile is None:          # 老缓存条目/写透缺该键时回落现算，绝不下发空元信息
                profile = _column_profile(df, datafile.format_type)
            site_options = profile['site_options']
            numeric_columns = profile['numeric_columns']
            system_columns = profile['system_columns']
            serial_column = profile['serial_column']
```

`analysis_views.py:113-122` 的 histogram 快路径改为读同一只 `metadata['column_profile']['numeric_columns']`，再按 `:106-108` 的 `_meta_cols` 排除（**语义差异要在测试里单独钉**：视图侧多一句"排除序列/site 候选列"，缓存放的是未排除的全集，排除在视图侧一次 `set` 差集完成）。

- [ ] **Step 5: 跑测试确认通过** + `python manage.py test apps.datafiles test.backend -v 2`（`apps/datafiles/tests_parse_cache.py` 的 `SharedFrameSafetyTests`、`col_meta` 同址测试 344/358/417 必须仍绿）。
- [ ] **Step 6: 收口** — `npm run test:e2e:affected`；`cd frontend && npm run build`（T2 的 `lineLimit.spec.ts` 会验 600 行；`services.py` 现 432 行 + ~25 行安全）。
- [ ] **Step 7: 提交** — `git commit -m "perf(datafiles,analysis): 首屏列级元信息随解析只算一次并进缓存体积"`

### Task A5: gage/buyoff 的逐格 FFI 与逐格样式（Excel 生成 CPU）

**Files:**
- Modify: `apps/gage/gage_file_sheet.py:135-140`（列字母在逐格循环内）、`:69-72`、`:88-93`、`:148-154`
- Modify: `apps/gage/gage_summary_sheet.py:233-234`、`:247-253`（组内中间行整趟重复）、`:317`（`autofit_columns` 全量物化只为算列宽）
- Modify: `apps/buyoff/excelize_layout.py:179-204`（14 统计行 × 全部列逐格 `set_cell_style`）
- Test: `test/backend/test_gage_sheet_shape.py`（新建）+ 既有 gage 导出测试

**Interfaces:**
- Consumes: 无
- Produces: `GAGE`/`BUYOFF` 产物 xlsx **字节级不变**（这是本任务的验收判据，不是参考）

- [ ] **Step 1: 先补"逐格样式/列字母"的产物基线**。现状是 gage 侧**没有任何逐格样式读回测试**（buyoff 有），所以第一步是拿既有夹具生成一份 xlsx 存进 `tasks/perf-review-2026-10-27/gage-baseline/`（gitignored），并记录其 sha256 + 关键单元格样式与列字母的读回断言。**没有这份基线就不许动 A5**——改错无人知。
- [ ] **Step 2: 列字母提出循环**（`gage_file_sheet.py:135-140`）：

```python
        letters = [excelize.column_number_to_name(i + 9) for i in range(len(data_header))]
        for test_idx, col_name in enumerate(data_header):
            try:
                val = row_data[col_name]
                if pd.notna(val):
                    set_cell(sheet_name, f"{letters[test_idx]}{excel_row}", float(val))
            except (ValueError, TypeError):
                pass
```

  取值域只有 1700 个、每格一趟 ctypes→Go FFI（`.venv/Lib/site-packages/excelize.py:6736-6754`）；1702 列 × 8 文件 ≈ 170 万次 FFI 只为拿列字母。
- [ ] **Step 3: 样式区间化**：`set_cell_style` 是**替换语义**，`gage_summary_sheet.py:233-234` 已把整片数据带刷成同一 style，`:247-253` 对组内中间行再逐格刷一遍是纯重复（≈25.5 万次调用一格都没改变）⇒ 改区间调用；`buyoff/excelize_layout.py:179-204` 同一行同一 styles id 一次区间覆盖。
- [ ] **Step 4: `autofit_columns` 别从 Go 侧全量物化回 Python**（`apps/export/excel_theme.py:232-259` 的 `get_cols` + `_display_width` 扫了含 1.36 万行的整张 Summary）；列宽只依赖**表头与有限几个统计行的显示宽度**，调用侧传显式宽度即可，不动 `excel_theme` 本体（那是波次 I 的重复实现合并项）。
- [ ] **Step 5: 产物字节判据** — 重新生成并 `sha256sum` 与 Step 1 基线逐字相等；不等 ⇒ 停下报告差异单元格，不许"看起来更对"就接受。
- [ ] **Step 6: 提交** — `git commit -m "perf(gage,buyoff): Excel 逐格 FFI 与重复样式下发改区间化，产物字节不变"`

### Task A6: `norm_ppf` 理论分位数按 n 记忆化

**Files:**
- Modify: `apps/analysis/services/statistics/distributions.py:33-41`
- Test: `apps/analysis/tests_qqplot_math.py`（若无则 `test/backend/test_norm_ppf_memo.py`）

- [ ] **Step 1: 写逐位一致测试**：`n ∈ {1..200, 999, 1000, 5000}` 上，记忆化结果与现逐元素 Python 循环结果 `np.array_equal(..., equal_nan=True)` 全等。
- [ ] **Step 2: 跑测试确认失败**（未实现）。
- [ ] **Step 3: 实现**——`osm` 只依赖 n，纯函数：加 `@lru_cache(maxsize=512)` 的 `_osm_for_n(n) -> tuple`，调用处 `np.asarray(...)`。**不进 worker 的键里不要出现 DataFrame**（该文件已被 `apps/jobs/runner.py:21` 在无 Django 链路 import，改完必须仍能无 Django 导入）。
- [ ] **Step 4: 跑测试确认通过** + 跑 `python manage.py test apps.analysis -v 2` 确认 qqplot 相关全绿。
- [ ] **Step 5: 提交** — `git commit -m "perf(analysis): QQ 图理论分位数按样本数记忆化"`

---

## 波次 B · 载荷封顶与分页（**每项都需先拍板，未拍不动**）

本波次每一条都会改变前端可见行为。按规矩：判据一变，help 提示与用户指南同步改；上限值由用户点，不许我自己定数后写进代码。下表「待拍板」列 = 必须先拿到的答案。

| # | 位置 | 现状机理 | 建议改法（已定形态，只差数值） | 待拍板 |
|---|---|---|---|---|
| B1 | `apps/sftp/views.py:224-251` | `list_files` 无分页/流式，整目录一次物化 + 整体序列化 | 加 `limit`/`offset`（默认如 500），或先加硬上限 + `truncated:true`；前端已有排序/搜索 | 默认条数；截断时前端怎么提示 |
| B2 | `apps/analysis/views/statistics_views.py:198-237` | `correlation_matrix` 默认参数集=全部带规格限列，矩阵规模与响应体无上限 | k>上限时截断并回 `truncated`，或直接 400 要求显式选参数 | 上限值；二选一（截断 vs 拒绝） |
| B3 | `apps/analysis/services/data_services/serial_distribution.py:250-253` | 连续序列轴无跨度上限，整数序列号跨度大时一次造出巨型 list | 跨度 > k×实有序列数（k=2 即可）时走**已有的** else 分支 | k 值可否定 2 |
| B4 | `apps/dashboard/services.py:320/352` | 逐参数总览无列数上限 ⇒ 响应体/序列化膨胀，且导出侧未缓存 | 加 `top_n` 入参；或 export 复用 `get_dashboard_summary` 缓存 | 总览默认显示多少行 |
| B5 | `apps/datafiles/views/browse_views.py:236-253` | 每页响应都重发并重新序列化 `headers`+`col_meta`（首屏 ~30KB + 每页几十KB） | ① 挪进既有 `if page == 1` 分组（**契约变更**，前端要缓存复用）；② 只把 `col_meta` 随解析存**已序列化字符串**、browse 直接拼接（省 CPU 不省传输、**零契约风险**） | 选 ① 还是 ②（我建议先 ②，①留前端改造一起做） |
| B6 | `apps/datafiles/views/batch_views.py:83-104/123` | 每批次全量行明细不分页进响应 | 每批 `files` 加帽（前 500 + `files_truncated` 计数）；或前端改走已分页的 `/files/` | 加帽 vs 前端换端点 |
| B7 | `apps/analysis/services/data_services/wafer_map.py:126-146` | 晶圆图每 die 一个 Python dict + 三条标签列整列 `astype(str)`，且是全仓唯一没接降采样的散点 | 先按 `valid` 切再转 str（零语义变化）、`color_group` 用一次 `np.where`。**采样禁止顺手加**——语义是"每颗 die 可见且可点"，且另有会话正在改 `WaferMapPanel.vue` | 是否要采样（要则与前端一起定） |
| B8 | `apps/export/views.py:66-93`、`197-266` | legacy `/export/to_excel/`、`/export/batch_charts/` 仍可 POST ⇒ 绕过作业池、每请求 `_pick_workers` 缺省 spawn `min(8, cpu)` 进程 | 从 ViewSet 删这两个 `@action`（`urls.py` 不动，405 由统一异常处理器兜），同时 `scripts/perf_load20.py:235` 改打 `/jobs/export_excel/` | 删 vs 转发（删会红 `apps/export/tests.py:313,331,380,447,469,493` 等，需同批改测试） |

---

## 波次 C · 作业状态机与清理（上线级卫生，不依赖波次 B）

### Task C1: 「排队中」不再被烧进超时预算，且作业真能取消

**Files:**
- Modify: `apps/jobs/executor.py:229-233`（`_in_flight` 元组的 `started` 与 submit 即 `running`）、`:303-310`（超时分支）、`:311-315`（monitor 读侧车）
- Modify: `apps/jobs/views.py:259-262`（`cancel` 只认 `pending`）
- Test: `apps/jobs/tests_jobs.py` **不可加行**（EXEMPT 冻结）⇒ 新断言写 `test/backend/test_job_cancel.py`

**Interfaces:**
- Consumes: 无新列、无新状态字符串（避免契约变更）
- Produces: `cancel` 对 `running` 作业的返回码从恒 409 变为「仍在池队列未开跑 ⇒ 200 cancelled / 已开跑 ⇒ 409」

- [ ] **Step 1: 先揭穿那条假绿测试。** 现状 `apps/jobs/tests_jobs.py:251-261` 的 `test_cancel_pending_succeeds_but_running_is_409` 用 `Job.objects.create(status='pending')` **绕过 submit 路径**造行，所以生产里「同一次请求内 pending→running、cancel 恒 409」从没被覆盖。新用例必须走 `POST /jobs/…/cancel/` 的真实提交路径，并在 `_in_flight` 有/无该 future 两种形态下分别断言 200 与 409。
- [ ] **Step 2: 写失败测试**：
  - 超时起算点：池满时提交第 5 条作业，在队列里等过「假想预算」但尚未开跑 ⇒ 断言 monitor **没有**把它标 error。
  - cancel：`future.cancel()` 返回 True ⇒ 作业终态 `cancelled` 且不留 `running`；返回 False ⇒ 409，且**不许**把仍在产出的作业标成 error 后留下孤儿文件（现状：worker 继续烧满 CPU 写完文件，进度侧车被 `status='running'` 过滤挡住，用户看到 error 行 + 悄悄产出的孤儿）。
- [ ] **Step 3: 跑测试确认失败**（当前实现必红）。
- [ ] **Step 4: 实现两处最小改动**：
  - 超时原点改「首次见到进度 > 0」：`_in_flight[job.id]` 的 `started` 在 monitor 首次读到 `percent > 0` 时重置一次（进程 lane 的 `runner.py:119/151/182` 第一步就 `write_progress(...,1,3)`；thread lane 用首次 DB 进度写）。
  - `cancel` 放宽到 `running`：`future = _in_flight.get(job_id)`；`future and future.cancel()` ⇒ 标 `cancelled`；False/缺席 ⇒ 维持 409（与既有测试兼容，那条 running 用例的 job 不在 `_in_flight`）。
- [ ] **Step 5: 语义提示同步（不许只改后端）**：排队中的作业现在「可见可取消」，前端 chip 与放弃文案要给「排队中」这一态；`frontend/src/composables/jobPolling.ts` 的 `jobFailureView()` 是 reason→呈现 的唯一归属点（T2 是 `environment:'node'` 零 DOM 档，必须住那里）。**这一步会动前端，属单独点名授权范围**。
- [ ] **Step 6: 跑测试确认通过** + `python manage.py test apps.jobs test.backend -v 2`；核对 `Ran N` 未减少。
- [ ] **Step 7: 提交** — `git commit -m "fix(jobs): 排队作业不再烧执行预算且可取消，超时原点改首次进度"`

### Task C2: `prune_jobs` 按目录名清理，异常作业不再永久泄漏

**Files:**
- Modify: `apps/jobs/management/commands/prune_jobs.py:42-44`
- Test: `test/backend/test_prune_jobs_dir.py`（新建）

- [ ] **Step 1: 写失败测试**：造一行 `status='error'` 且 `result_path=''` 但 `jobs/<owner>/<id>/` 目录存在（含一个 1KB 文件）的作业，跑 `prune_jobs`，断言该目录**不存在**了；对照组 `running` 行的目录不许删。
- [ ] **Step 2: 跑测试确认失败**（现状只认 `result_path` ⇒ error/cancelled 行恒空，每个异常作业永久泄漏目录，导出类可达数百 MB）。
- [ ] **Step 3: 实现**：清理目标改成按 `owner/id` 的目录名（`jobs/<owner>/<id>/`）枚举，删除前先判该行已过保留期且状态为终态；保留 `result_path` 分支兼容旧行。
- [ ] **Step 4: 跑测试确认通过** + `python manage.py test apps.jobs -v 2`。
- [ ] **Step 5: 提交** — `git commit -m "fix(jobs): prune 按 owner/id 目录清理，异常作业不再泄漏工作目录"`

### Task C3: 优雅退出关掉两条池（POSIX 不留孤儿子进程）

**Files:**
- Modify: `apps/common/shutdown.py:109-128`（`_cleanup` 现只 `_close_database_connections` + `_flush_output`）
- Test: `test/backend/test_shutdown_closes_pools.py`（新建）

**Interfaces:**
- Consumes: `apps/jobs/executor.py` 的既有丢弃通路（`:99-101` 崩池路径里已有 `broken.shutdown(wait=False, cancel_futures=True)` 的形态）
- Produces: `_cleanup` 多一步 best-effort 池关闭，且**任何异常只记 warning 不影响退出码**

- [ ] **Step 1: 先证现状**（我已核实，执行者要独立复现一次）：`grep -rn "\.shutdown(" apps/jobs/executor.py` ⇒ 唯一的生产外调用在 `reset_for_tests()`；`grep -rn "JobObject" apps config standalone.py` ⇒ **零命中**，所以代理"Windows 有 job object 兜底"那句无仓内依据，两档都要修。
- [ ] **Step 2: 写失败测试**：monkeypatch 一个假 `_pool`/`_download_pool`（带 `shutdown` 计数），走 `_cleanup('test')`，断言两条池各被 `shutdown(wait=False, cancel_futures=True)` 调用一次；`_flush_output` 抛错时池关闭仍发生；**并且不许 import 失败时炸掉退出**（executor 未导入的场合要静默跳过）。
- [ ] **Step 3: 实现**：`_cleanup` 里加一步函数内延迟 import（照 `shutdown.py` 既有写法），不在模块顶层 import jobs（避免 `apps.common` → `apps.jobs` 的反向依赖）。
- [ ] **Step 4: 跑测试确认通过**；另跑一次 Linux 侧取证（WSL 演练档，配方见项目 memory：systemd-run 临时 unit + 每轮独立 BASE_DIR；改 `scripts/` 必须重新 rsync）：退出后 `pgrep -c -f "spawn_main"` 应为 0。
- [ ] **Step 5: 提交** — `git commit -m "fix(common,jobs): 优雅退出关闭进程与下载池，不再留孤儿子进程"`

---

## 波次 D · 每请求 DB 往返

### Task D1: 用户设置读取收敛到单一入口（三通路合一）

**Files:**
- Create: `apps/accounts/services.py`（**必须在 `apps/accounts` 下，不许放 `apps/common`**）
- Modify: `apps/common/export_naming.py:95-98`、`apps/export/user_prefs.py:9,14-26`、`apps/common/user_settings.py:40-54`
- Test: `test/backend/test_user_setting_reads.py`（新建）

**Interfaces:**
- Consumes: `UserSetting` 与 `user.settings` 反向描述符
- Produces: `apps/accounts/services.py:get_user_setting(user) -> UserSetting | None`，**同一 user 实例同一请求内只一次 SELECT**（后续通路命中 Django 挂在实例上的反向缓存）；`user=None` 必须继续可用并返回 `None`（`apps/export/tests_chart_dpi.py:78-89,227` 钉着 `get_export_dpi(None)`）

- [ ] **Step 1: 写失败测试**（三条现状各断一次）：

```python
class SettingReadQueryCountTests(TestCase):
    def test_three_helpers_share_one_query(self):
        self._ensure_setting()
        with self.assertNumQueries(1):
            render_export_filename(self.user, ...)   # 通路 1
            get_export_dpi(self.user)                # 通路 2
            get_cpk_thresholds(self.user)            # 通路 3

    def test_helper_tolerates_none_user_and_missing_row(self):
        self.assertIsNone(get_user_setting(None))

    def test_worker_isolation_still_holds(self):
        # apps/jobs/tests_jobs.py:110-118 的钉子形态：把 helper 放 apps/common 就会红
```

- [ ] **Step 2: 跑测试确认失败**（现状是 3 条通路各 1 次 SELECT）。
- [ ] **Step 3: 实现**：`get_user_setting` 内部优先 `getattr(user, 'settings', None)`，缺失时**建行后返回**（保留 `get_or_create` 的「缺失即建」语义——`apps/common/tests.py` 有 8 处直接调 `render_export_filename`，改成只读会让它们抛 `RelatedObjectDoesNotExist`），并把结果塞回 `user._state.fields_cache` 让同实例后续读取零查询。**第二阶段（进程内 TTL 缓存）本任务不做**：先把「同请求多次」压成 1 次且不引入失效语义，值不值等 D1 落地后的实测再说。
- [ ] **Step 4: 迁移三个调用点**：`export/user_prefs.py` 与 `export_naming.py:97` 改调 helper（各删 1 行 query 换 1 行调用）；`apps/common/user_settings.py` **不许** import `accounts.models`（worker 约束），保持只吃描述符。
- [ ] **Step 5: 跑测试确认通过** + `python manage.py test apps.common apps.export apps.accounts apps.analysis test.backend -v 2`。
- [ ] **Step 6: 提交** — `git commit -m "perf(accounts): 用户设置读取收敛为单一入口并按实例复用查询"`

### Task D2: 设置页 GET 不再写库、PUT 只写变更列；登录路径收敛语句数

**Files:**
- Modify: `apps/accounts/views.py:213-225`（`UserSettingsView` 读写皆 `get_or_create`）
- Modify: `apps/accounts/views.py:100-159`（`LoginView` 成功路径同一行 3 条语句）
- Test: `test/backend/test_accounts_write_paths.py`（新建）

- [ ] **Step 1: 写失败测试**：`assertNumQueries` 钉 GET 设置页 **0 写**（现在是可能写库的读请求）；`self.assertNumQueries(1)` + 断言 `UPDATE` 语句只含变更列（`serializer.save()` → 显式 `update_fields=list(validated_data)`）；钉登录成功路径语句数从 3 降到 2。
- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**：GET 改 `UserSetting.objects.filter(user=request.user).first()`，None 时返回**不落库的默认实例** `UserSetting(user=request.user)` 给只读序列化器。`LoginView`：**别动 `authenticate`**（`ModelBackend` 会复用 `request.user`，但登录请求匿名且 `authentication_classes = []`，复用不上），只把 `views.py:101` 的 `User.objects.get` 换成 `filter(username=...).first()` 形态少一条。
- [ ] **Step 4: 跑测试确认通过**；`apps/accounts/tests.py`（498 行）必须全绿——注意它有硬编码的导出类型键集。
- [ ] **Step 5: 提交** — `git commit -m "perf(accounts): 设置页 GET 不写库、PUT 收窄到变更列"`

### Task D3: 批次报告——一次取全 + 砍掉前端不读的四段分区

**Files:**
- Modify: `apps/batch_report/views.py:107-110`（循环内逐 id `get_object_or_404`）
- Modify: `apps/batch_report/views.py:48-59` + `apps/batch_report/services.py:189-207,194-202,267-270,165-171`
- Test: `test/backend/test_batch_report_payload.py`（新建）

- [ ] **Step 1: 先独立复核「前端不读」这个否定断言**（不许照抄代理）：

```bash
grep -rn "trend_data\|bin_distribution\|site_pass_data\|bin_table_data\|bin_site_columns" frontend/src | cat
```

  要求：前三个 0 命中、后两个命中但由 `frontend/src/.../batchAggregation.ts:139` 另算一份。**核不上就停下报告，不许删**（历史上「我搜过没找到」被写成「它不存在」出过事）。
- [ ] **Step 2: 写失败测试**：`assertNumQueries` 钉 `generate_report` 的 N 文件 = 1 次 `DataFile` SELECT；缺 file 时按**输入顺序**返回第一个缺失者的 404；`batch_yield_data` 的响应 JSON **键集合不变**（前端仍拿到它原来拿到的那些），但 `services` 侧的 `compute_trend` 调用计数为 0（HTML 分支仍为 1，`html_report/batch.py:108-129` 确实要）。
- [ ] **Step 3: 实现**：循环外 `found = {d.pk: d for d in DataFile.objects.filter(pk__in=normalized_ids, owner=request.user)}`；JSON 分支按消费方拆，不再为凑 `trend_data` 跑第二遍全量 bin 统计（重复计算落点 `apps/analysis/services/statistics/trends.py:149`）；`file_data_list` 改为携带已算好的 `bin_stats/total` 而**不持有 df** ⇒ 「批次内每个文件的 DataFrame 同时驻留」这条消失，解析缓存不再被挤。
- [ ] **Step 4: 跑测试确认通过** + `npm run test:e2e:affected`（批次报告页 e2e 覆盖面不小）。
- [ ] **Step 5: 提交** — `git commit -m "perf(batch_report): 一次取全文件并按消费方裁剪统计分区"`

### Task D4: sftp 每次浏览少两次写；`last_visit` 值未变不写

- Modify: `apps/sftp/views.py:71,88-89,245`（`_record_last_visit` 的 `get_or_create` + `save`）
- Test: `test/backend/test_sftp_last_visit_writes.py`；既有 `apps/sftp/tests_last_visit.py`（248 行）必须仍绿
- 步骤同 D2 形状：先 `assertNumQueries` 钉「同目录重复浏览 ⇒ 0 写」，再改成 `update(**fields)` 条件写或值相等即跳过。提交信息 `perf(sftp): 目录未变时不再重写 last_visit`。

---

## 波次 G · 缓存失效粒度与键（与 A4 相邻但独立可驳）

### Task G1: 按路径淘汰，不再一把清空全站解析缓存

**Files:**
- Modify: `apps/datafiles/services.py`（`_BytesLRUCache` 加 `evict_keys(pred)`，约 `:80` 一带；`clear_parse_cache` 保留给 MemoryError 兜底）
- Modify: `apps/datafiles/views/file_views.py:209,224,361,437`、`browse_views.py:386`、`_helpers.py:353`、`batch_views.py:220,264`
- Test: `test/backend/test_parse_cache_eviction.py`（新建）；**会红** `apps/datafiles/tests.py:716 ParseCacheInvalidationTests`（大概率直接断言全清）与 `apps/dashboard/tests.py:204,323,365`（用 `clear_parse_cache` 当夹具手段）——同批改这些用例，别指望它们自动绿

- [ ] **Step 1: 写失败测试**：A/B 两个文件的帧都在缓存 ⇒ 删 A ⇒ 断言 B 的缓存条目**仍在**（键不变、未被逐出），且 A 的条目已消失、字节账已扣。
- [ ] **Step 2: 跑测试确认失败**（现状一次单文件删除把全体用户的解析缓存打空 ⇒ 全站重解析风暴）。
- [ ] **Step 3: 实现** `evict_keys(pred)`（锁内收集匹配键、`popitem` 计费，~10 行）；删除/combine/uncombine 传被触达的 `resolve_file_path(...)` 集合按路径前缀淘汰；`MemoryError` 路径（`apps/common/exceptions.py:135`）**必须继续全清**。陈旧服务风险由内容坐标键兜住：删行后 DB 无路径可解析到该条目，文件替换则 `mtime_ns` 变、键自然失效（与 `services.py:186-202` docstring 的自失效论证同构）。
- [ ] **Step 4: 跑测试确认通过** + 后端全量。
- [ ] **Step 5: 提交** — `git commit -m "perf(datafiles): 解析缓存按路径淘汰，MemoryError 仍全清"`

### Task G2: fail 检测并入字节 LRU（键去 owner）+ 低 CPK 缓存去 user 键

- Modify: `apps/datafiles/services.py:349-374`（`_cached_fail_data` 的 `@lru_cache(maxsize=32)` ⇒ 新 `_fail_cache = _BytesLRUCache(小预算)`，键改内容坐标，`store_if` 用 `value[0] is not None` ⇒ 顺带解决「失败四元组被 memo 到 `clear_parse_cache`」与「按条数逐出与字节缓存不同步」）
- Modify: `apps/analysis/views/_helpers.py:28-45`（低 CPK 缓存：键去 `user_id`（threshold 已在键里，跨用户共享天然安全）、淘汰改 `OrderedDict.popitem(last=False)` 且**复用 `apps/dashboard/services.py:381-398` 已有的同型 LRU+lock 形态，不要新建第三份**、加单飞）
- Test: `test/backend/test_fail_cache_sharing.py`——断言两个 owner 读同一文件 ⇒ 检测只跑 1 次（对照组：单 owner 连续两次 ⇒ 也是 1 次）；并**扩一条 `SharedFrameSafetyTests` 同款扫描**覆盖 `fail/borderline`（它们是 `dict[int, list[str]]`，`browse_views.py:228/233` 只读）。
- 会红：`apps/datafiles/tests_parse_cache.py`、`apps/analysis/tests_cpk_thresholds.py:29`（用 `types.SimpleNamespace` 假冒 user ⇒ 任何改成 manager 直读的写法都会红）。
- 提交：`perf(datafiles,analysis): 检测与低CPK缓存改内容坐标键并按字节淘汰`

---

## 波次 H · 解析器与导出内存形态

### Task H1: 宽表 xlsx 的分块流式（P0 内存放大链）

- Modify: `apps/export/export_xlsx_optimized.py:54-62`（`_vectorized_native_rows`）、`:331-354`、`:199-207`
- 改法（三处都是纯内部函数，**签名不变**）：① `_vectorized_native_rows` 改分块生成器 `for lo in range(0, n, 5000): yield df.iloc[lo:lo+5000]` 上做 `astype/tolist`，`_data_rows_xml` 逐块消费即弃；② 放弃 `str.replace`，改在 `sheet_xml` 上 `idx = sheet_xml.rfind('</sheetData>')` 切片拼接（省一份全量拷贝）。
- Test: `test/backend/test_xlsx_chunked_rows.py`——分块拼接结果与整帧生成**逐字节相等**（把夹具行数取 5000 的整数倍 ±1，边界必须有例）。
- 前置：先做 J1 的内存实测（现在只有代理的 3–5GB/作业估算，未取证）。产物字节判据同 A5。
- 提交：`perf(export): 宽表 xlsx 分块生成，去掉全帧拷贝链`

### Task H2: CSV 直下改 FileResponse + `BaseAteCsvParser` 有界读取

- Modify: `apps/export/views.py:97-118` + `apps/export/export_csv.py:42-43`（`to_csv().encode()` 双倍全量字符串驻留 ⇒ view 侧写 `tempfile` 后 `FileResponse(open(tmp,'rb'), as_attachment=True)`，`export_to_csv` 返回 bytes 的签名不变）
- Modify: `apps/datafiles/parsers/base.py:174-175,198-199`（整文件 `readlines()` 后 `read_csv` 二次整读 ⇒ 把 `ets88.py:32-45` 的 head/tail 有界读取模式搬进基类；`marker_idx` 语义不变、找不到 marker 仍返回 `None,None`）
- Test: 两条各自等价（CSV 字节相等；解析器对 4 种 format 的 DataFrame 与改前 `assert_frame_equal`），峰值断言用 `apps/common/memory.py` 的既有采集，不许自己拼 ctypes。
- 提交：`perf(datafiles,export): 基类有界读取、CSV 直下改分块文件响应`

---

## 波次 E · 远程 IO 往返（需真机才收口）

- **E1** `apps/sftp/search/walker.py:165-166` + `:186-204` + `:291-306`：`list_one` 内不要解析目录路径，`_resolve_dir` 挪进 `_enqueue_dirs`、**过了深度闸与 visited 预判之后**再解析；`depth='self'`（仅当前层）时根下所有子目录的 realpath 现在是 100% 白付。Test：`test_sftp_search_engine_stream.py`（642 行，EXEMPT 冻结 ⇒ 新断言进 `test/backend/` 新文件）+ 假 SFTP 服务器的往返计数断言。
- **E2** `apps/sftp/search/runner.py:392-394,432-444,446-478` + `:43`：`_meta_for` 的补取丢进小线程池（复用 `self.session`，每任务 borrow/give_back），主循环 yield 已攒帧、后台填 `_meta_cache`；并把 `_META_CACHE_MAX=512` 抬到与 `max_matches` 同量级（条目是几十字节定长 dict，2 万条才几 MB）。
- **E3** `apps/sftp/search/connect.py:98-127` + `search_views.py:128-136`：`open_all` 用 `ThreadPoolExecutor(max_workers=min(requested, 2))` 并发开临时连接（并发度 2 与下载作业一致，不违 `MaxStartups`），保留「每搜索临时连接、绝不碰 per-user 常驻池」这条不变量。
- **E4** `apps/sftp/downloads.py:337-352` + `apps/jobs/sftp_job.py:106-108`：给 `download_dir_events` 加 `owns_connection: bool = False`，仅 SSE 端点（`views.py:379` 用常驻连接）传 True 才 `pool.invalidate`；作业路径只清半截文件。**会红** `apps/sftp/tests_download_dir.py:204-213,220-229`（两条 `assert_called_once_with(self.user.id)`），同批改。
- **E5** `apps/sftp/views.py:363-369` + `downloads.py:44-49,58-59,283`：`collect_files` 加 `MAX_DEPTH`（如 64，超限 warn 跳过该子树，顺带挡环——现状软链环 → `RecursionError`）；收集挪进 `download_dir_events` 内部，先 yield `collecting` 让 SSE 立即开流；`makedirs` 只在目录首见时建。

**E 波收口要求**：E1/E2/E3 的往返计数只能在真机 SFTP 上验证（本地假服务器没有 shell exec、Git Bash 造不出真软链接）。执行者把判据写成可跑脚本放 `tasks/`，真机窗口由用户开；**没跑成就不许在文档里写"已验证"**。

---

## 波次 I · P2 简洁性清扫（批量转换类，先自证再动）

先做集合相等式自证，再做机械转换（2026-10-16 那次「键名对了语义错了」的事故就出在这类改动上）：把命中点**全量列成清单**（文件:行号 + 原文一行），先让另一人/另一只眼睛确认清单边界，再逐点改。

| 项 | 命中数（代理普查） | 合并判据 |
|---|---|---|
| 错误信封 | 3 + 1 | `error_response` 与其余形态的输出键集**必须完全一致**，逐形态取样例比对 |
| 日期格式 | 16 处 / 7 种格式 | 7 种各自一条等价测试，合成后不许静默改判 |
| NaN/inf 处理 | 87 处 | 先只合并语义**逐字等价**的（`math.isfinite` 谓词那族），其余登记不并 |
| limit 谓词 | 3 份分叉 | 单一来源已是 `statistics/limits.py:78` 的 `resolve_spec_limits`，另两处分叉逐个改调 |
| `[False] * len(...)` | 3 份复制 | 一处工具函数，`count` 断言 3→1 |
| 设置/权限 helper | accounts 内多份 | 与 D1 合并做，别单开一份 |
| `pool.invalidate` / `pool.close` | 实现逐字相同（`apps/sftp/pool.py:152-161`） | 保留两个公开名，一方转调 + 一行注释说明意图差异 |
| 无界容器 | 7 只进程内容器 | 逐只补显式上限或 `None` 声明「有意无界」并写理由 |

P2 里另有两条**独立小缺陷**，别混进清扫批：`_BytesLRUCache._store` 覆盖活键不扣旧字节（S1 复核后认为实害低于台账挂账，建议**并案降级**处理）；`apps/weight/views.py:48` 与 `test/backend/test_weight_export_api.py:252` 引用的 `test_weight_xlsx.py::test_empty_palette_falls_back_to_default` **全仓不存在** ⇒ `apps/weight/xlsx.py:236-237` 的默认色板回退目前无测试保护（先补测试，再谈改代码）。

---

## 波次 J · 先实测才能定档（不许先写"省 N"）

- **J1 导出内存峰值**：验 H1 的 3–5GB/作业估算。配方硬约束：每轮**独立 BASE_DIR + 独立端口 + 独立进程**（同进程第二轮必吃解析缓存，比值即假）；`tracemalloc` 会把 `parse()` 从 3.6s 抬到 7.8s ⇒ 独立成默认不跑的一组；判据分「首跳」与「稳态 ≥6 单」两行，必配无并发对照。
- **J2 连接复用形态**：数一次页面加载里 `sqlite3.connect` 的实际次数。我已核实 `db/utils.py:148 thread_critical = True` 与 runserver threaded（`basehttp.py:90 daemon_threads = True`），但 ThreadingMixIn 是**每 TCP 连接一条线程**、keep-alive 会摊薄 ⇒ `config/settings/*.py` 五档 `DATABASES` 无 `CONN_MAX_AGE` 属事实，「每请求新建」这个口径**待测才准写进文档**。`OPTIONS={'timeout': 30}` 这条（Django `sqlite3/base.py:154-165` 原样喂 `connect`）可独立评估。
- **J3 `/jobs/` 提交阈值**：B 后端载荷那一刀（2026-10-26）后 20 人复测从没跑过，提交跳阈值仍未定；夹具 `$BIG`/`$MID` 实测在位，缺的是独占测量窗口（当日空闲提交内存 8.97GB，仅比 8.0GB 预算线高 0.97GB ⇒ **空闲不足就别开池**）。
- **J4 基线数字本身**：`docs/reference/perf-baseline-2026-10-17.md` 的 6288ms 可能是在 `seed_test_data` 未写透解析缓存的冷启动形态上量到的（S9 P2-8）⇒ 任何"修完快几倍"的表述在复测前不许进文档。

---

## 待用户拍板清单（集中一处，点完才开工）

1. B1–B8 的每个上限值与「截断 vs 拒绝 vs 换端点」取向（B5 另需选 ① 契约变更 / ② 零风险序列化）。
2. B8：legacy `/export/to_excel/`、`/export/batch_charts/` 是否删（删会红 6 处测试，需同批改）。
3. C1 Step 5：是否本轮就动前端「排队中」chip 与放弃文案（不动则后端先改、行为增强暂不可见）。
4. D1 第二阶段：是否给 `UserSetting` 加进程内 TTL 缓存（会引入「改了设置多久生效」的新语义）。
5. zip/目录批量导入与 gage 最重一次 Excel 生成是否作业化（基建已有，属产品决策；作业化即占用 2 worker 池，需与并发预算一起判）。
6. P1-8 的 DPI 回填：迁移 0011 只改 Python 默认值、没回填 ⇒ 既有安装仍按 150 导出（≈3 倍图表体积）。困难在无法区分「150=默认」与「150=用户选的」，三条路见 `S9-accounts-and-batch-report.md` P1-8 节。
7. 服务器 media 无自动回收 ⇒ 保留期与配额（与 `project-server-deployment-constraints` 那条一并定）。
8. E 波真机窗口时间。

## 自检（写完后回看计划本身）

- **覆盖**：8 条 P0 全部有任务（A1/A2/A4×2/H1/C1-G1 关联/D1）；59 条 P1 中 55 条落到 A–H 具体任务，4 条留在「待拍板」（B4 的 export 复用、B7 采样、P1-8 回填、zip/gage 作业化）——已点名，不是漏。
- **占位符**：无 `TBD`/「适当处理」；每个未定数值都写成「待拍板 + 候选取向」，且所在任务在拍板前不许开工。
- **类型一致**：`get_user_setting(user) -> UserSetting | None`、`_column_profile(df, format_type) -> dict`（四键名 `site_options/numeric_columns/system_columns/serial_column`）、`_BytesLRUCache.evict_keys(pred)`、`download_dir_events(..., owns_connection: bool = False)` 在各任务中同名同形；A4 产的 `metadata['column_profile']` 是 G2/H2 的读取前提。
- **风险最高的两处**：G1（少清缓存 ⇒ 陈旧服务面）与 D1（「缺失即建」语义丢失 ⇒ 8 个用例红）。两者都配了会红测试清单与等价判据，收口必须走后端全量。
