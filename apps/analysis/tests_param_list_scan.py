"""参数列表快路径的向量化改写必须与旧的逐列判定**逐列同结果**（2026-10-17 第二批）。

旧写法对每一列做 `df[c].dropna().empty`，实测那只 1,702 列的 ETS88 文件要 205ms
（每列都新建一次 dropna 的 Series）；改成一次 `df[cols].notna().any()` 是 91ms。
这类改写的风险不是慢，而是**语义悄悄变了**：空列判断、列序、bool/字符串列的归属，
任一变了都会让分析页的参数下拉少几项或多几项，而界面看不出来。

所以这里的判据是「用旧公式在测试里现算一遍期望值，与新实现的实际值比」，
而不是「断言有 3 列」——期望值来自被测代码的**旧口径**，属运行时对照组。
"""
import types

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.test_support import fake_datafile, patch_df_loader

_META = {'format': 'CTA8290D',
         'mins': {f'P{i}': '1.0' for i in range(1, 9)},
         'maxs': {f'P{i}': '9.0' for i in range(1, 9)},
         'units': {f'P{i}': 'V' for i in range(1, 9)}}


def _frame():
    """覆盖快路径判据会碰到的每一类列。"""
    return pd.DataFrame({
        'Serial_No': list(range(1, 7)),          # 序列列：元数据，不是参数
        'Site': [1, 2, 1, 2, 1, 2],              # Site 列：同上
        'P1': [2.0, 3.0, 4.0, 5.0, 6.0, 7.0],    # 正常数值列
        'P2': [np.nan] * 6,                       # 整列空 → 必须被剔掉
        'P3': [np.nan, np.nan, 4.5, np.nan, np.nan, np.nan],  # 稀疏但有一个值 → 必须保留
        'P4': np.array([True, False, True, False, True, False]),   # bool 标志 → 排除
        'P5': ['a', 'b', 'c', 'd', 'e', 'f'],     # 字符串列（pandas 3.0 是 str dtype）→ 排除
        'P6': [np.inf, 2.0, 3.0, 4.0, 5.0, 6.0],  # 含 inf：dropna/notna 都算有值 → 保留
        'P7': np.array([1, 2, 3, 4, 5, 6], dtype='int32'),   # 窄整型：白名单写法会漏
        'P8': np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], dtype='float32'),
    })


def _expected_old_formula(df, meta_cols):
    """旧实现的判定式，逐字照抄（int64/float64 白名单已在前一批改掉，这里用 is_numeric_dtype）。"""
    return [c for c in df.columns
            if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c])
            and not df[c].dropna().empty
            and c not in meta_cols]


class ParamListVectorizedScanTests(SimpleTestCase):
    def _fast_path_params(self, df):
        from apps.analysis.views import AnalysisViewSet
        restore = patch_df_loader(df, fake_datafile(format_type='CTA8290D'), _META)
        self.addCleanup(restore)
        from rest_framework.test import APIRequestFactory, force_authenticate
        request = APIRequestFactory().post('/api/v1/analysis/histogram/',
                                          {'file_id': 1}, format='json')
        force_authenticate(request, user=types.SimpleNamespace(
            pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
            is_staff=False, is_superuser=False,
        ))
        resp = AnalysisViewSet.as_view({'post': 'histogram'})(request)
        resp.render()
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data['results']

    def test_param_list_matches_old_formula_exactly(self):
        """含列序：向量化改写不许改变顺序（前端下拉按它排序）。"""
        df = _frame()
        from apps.analysis.services.statistics.helpers import get_serial_candidates, get_site_column
        meta_cols = set(get_serial_candidates(df))
        sc = get_site_column(df)
        if sc:
            meta_cols.add(sc)

        results = self._fast_path_params(df)
        expected = _expected_old_formula(df, meta_cols)
        self.assertEqual(list(results.keys()), expected)
        # 点名关键列，防止两边同时因为同一个 bug 得到同一个「错但相等」的结果
        self.assertIn('P1', results)
        self.assertIn('P3', results, '整列只有一个值也算有数据（旧口径如此）')
        self.assertIn('P6', results, 'inf 不是 NaN，旧口径保留')
        self.assertIn('P7', results, 'int32 不能像旧的 dtype 白名单那样被漏掉')
        self.assertIn('P8', results, 'float32 同上')
        for dropped in ('P2', 'P4', 'P5', 'Site', 'Serial_No'):
            self.assertNotIn(dropped, results, f'{dropped} 不该进参数列表')

    def test_all_nan_frame_still_returns_empty_not_error(self):
        """全空帧：新写法对空列集合取子集会走 `if numeric_cols` 早路，不能抛。"""
        df = pd.DataFrame({'Site': [1, 2], 'P1': [np.nan, np.nan]})
        results = self._fast_path_params(df)
        self.assertEqual(list(results.keys()), [])
