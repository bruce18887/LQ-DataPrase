from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.views._helpers import _sanitize_numeric_params


# Frozen from git show HEAD:apps/analysis/views/_helpers.py at 0ae0251 (A1).
# Only the function name differs; tests never invoke git or load external data.
def _legacy_sanitize_numeric_params(df, params):
    """Filter params to only those that are valid numeric columns with data.

    Removes: blank names, all-NaN columns, non-numeric columns, duplicate names.
    """
    # Deduplicate columns first
    df = df.loc[:, ~df.columns.duplicated()]
    valid = []
    for p in params:
        if not p or not str(p).strip():
            continue
        if p not in df.columns:
            continue
        col = df[p]
        # If duplicate columns were collapsed, get_1d_from style extraction
        if isinstance(col, pd.DataFrame):
            col = col.iloc[:, 0]
        # Skip all-NaN columns
        if col.dropna().empty:
            continue
        # Skip non-numeric
        if not pd.api.types.is_numeric_dtype(col):
            continue
        # Skip bool columns (real data has ``Dut_Pass``): ``is_numeric_dtype``
        # returns True for bool, but a pass/fail flag is not a measurable
        # parameter — a boxplot / correlation row for it is meaningless, and
        # before ``ensure_numeric`` gained ``.astype(float)`` it also crashed
        # ``.quantile()`` with "numpy boolean subtract".
        # 常量列（nunique()==1）**不排除**：全一致的列（如整文件 pass 的
        # SW_Bin、数字 trim code）画箱线图是合法的，而相关矩阵的对角线/
        # NaN 已在 compute_correlation_matrix 里从根上修好（fill_diagonal(1.0)
        # + 非对角 NaN → None），不需要在这里靠剔列规避。
        if pd.api.types.is_bool_dtype(col):
            continue
        valid.append(p)
    return valid


class SanitizeNumericParamsTests(SimpleTestCase):
    def test_matches_legacy_without_mutating_inputs(self):
        numeric_dtypes = [
            'Int8', 'Int16', 'Int32', 'Int64',
            'UInt8', 'UInt16', 'UInt32', 'UInt64', 'Float32', 'Float64',
        ]
        nullable = pd.DataFrame({
            dtype: pd.Series([pd.NA, 1, 1], dtype=dtype)
            for dtype in numeric_dtypes
        })
        nullable['all_na'] = pd.Series([pd.NA] * 3, dtype='Float64')
        nullable['Dut_Pass'] = pd.Series([True, pd.NA, False], dtype='boolean')
        nullable['text'] = pd.Series(['1', pd.NA, '2'], dtype='string')
        cases = [
            (
                'bool_nan_object_and_constant',
                pd.DataFrame({
                    'Dut_Pass': [True, False, True],
                    'all_nan': [float('nan')] * 3,
                    'object_numbers': pd.Series(['1', '2', None], dtype=object),
                    'SW_Bin': [1, 1, 1],
                    'voltage': [1.2, None, 1.4],
                }),
                ['Dut_Pass', 'all_nan', 'object_numbers', 'SW_Bin', 'voltage'],
                ['SW_Bin', 'voltage'],
            ),
            (
                'duplicate_first_nan',
                pd.DataFrame([[float('nan'), 2.0], [float('nan'), 3.0]], columns=['P', 'P']),
                ['P', 'P'], [],
            ),
            (
                'duplicate_first_numeric',
                pd.DataFrame([[2.0, float('nan')], [3.0, float('nan')]], columns=['P', 'P']),
                ['P', 'P'], ['P', 'P'],
            ),
            (
                'duplicate_first_bool',
                pd.DataFrame([[True, 2.0], [False, 3.0]], columns=['P', 'P']),
                ['P'], [],
            ),
            (
                'duplicate_second_bool',
                pd.DataFrame([[2.0, True], [3.0, False]], columns=['P', 'P']),
                ['P'], ['P'],
            ),
            (
                'blank_and_missing_names',
                pd.DataFrame({'': [1], ' ': [2], '\t\n': [3], None: [4], ' P ': [5]}),
                ['', ' ', '\t\n', None, False, 0, 'missing', ' P '], [' P '],
            ),
            (
                'request_order_and_repeats',
                pd.DataFrame({'A': [1, 2], 'B': [3, 4]}),
                ['B', 'unknown', 'A', 'B', 'A', 'A'], ['B', 'A', 'B', 'A', 'A'],
            ),
            ('empty_frame', pd.DataFrame(), ['P', '', None], []),
            (
                'zero_rows_with_numeric_dtypes',
                pd.DataFrame({
                    'P': pd.Series(dtype='float64'),
                    'N': pd.Series(dtype='Int64'),
                }),
                ['N', 'P', 'N'], [],
            ),
            ('no_requests', pd.DataFrame({'P': [1.0]}), [], []),
            (
                'nullable_numeric_and_boolean', nullable,
                ['Dut_Pass', 'all_na', *numeric_dtypes, 'text', 'Int64'],
                [*numeric_dtypes, 'Int64'],
            ),
            (
                'numeric_nonfinite_and_complex',
                pd.DataFrame({
                    'inf': [float('inf'), -float('inf')],
                    'complex': [1 + 2j, complex('nan')],
                    'zero': [0.0, 0.0],
                }),
                ['zero', 'complex', 'inf'], ['zero', 'complex', 'inf'],
            ),
            (
                'category_datetime_and_object_scalars',
                pd.DataFrame({
                    'category': pd.Categorical([1, 2]),
                    'datetime': pd.to_datetime(['2026-10-28', None]),
                    'object': pd.Series([1, 2], dtype=object),
                    'P': [1, 2],
                }),
                ['category', 'datetime', 'object', 'P'], ['P'],
            ),
            (
                'duplicate_row_index',
                pd.DataFrame({'P': [None, 1.0], 'Q': [2.0, None]}, index=['x', 'x']),
                ['Q', 'P', 'Q'], ['Q', 'P', 'Q'],
            ),
            (
                'bool_column_label_two_rows',
                pd.DataFrame({True: [1.0, 2.0]}),
                [True], [True],
            ),
            (
                'bool_column_label_one_row',
                pd.DataFrame({True: [1.0]}),
                [True], [True],
            ),
            (
                'mixed_column_labels_request_order_and_repeats',
                pd.DataFrame({True: [None, 2.0], 'A': [3.0, 4.0], 2: [5.0, 6.0], False: [7.0, 8.0]}),
                [2, True, 'A', True, 2, False, 'missing', 'A'],
                [2, True, 'A', True, 2, 'A'],
            ),
        ]
        for name, df, params, expected in cases:
            with self.subTest(case=name):
                before = df.copy(deep=True)
                params_before = params.copy()
                legacy = _legacy_sanitize_numeric_params(df, params)
                self.assertEqual(legacy, expected)
                pd.testing.assert_frame_equal(df, before)
                self.assertEqual(params, params_before)
                self.assertEqual(_sanitize_numeric_params(df, params), legacy)
                pd.testing.assert_frame_equal(df, before)
                self.assertEqual(params, params_before)

    def test_unique_wide_frame_avoids_loc_and_scans_candidates_once(self):
        columns = [f'P{i:03}' for i in range(400)]
        df = pd.DataFrame({
            p: [None, None] if i % 17 == 0 else [None, float(i)]
            for i, p in enumerate(columns)
        })
        before = df.copy(deep=True)
        real_loc = pd.DataFrame.loc
        real_notna = pd.DataFrame.notna
        real_any = pd.DataFrame.any
        real_dropna = pd.Series.dropna

        def record_loc(frame):
            loc_shapes.append(frame.shape)
            return real_loc.__get__(frame, type(frame))

        def record_notna(frame, *args, **kwargs):
            notna_columns.append(list(frame.columns))
            return real_notna(frame, *args, **kwargs)

        def record_any(frame, *args, **kwargs):
            any_columns.append(list(frame.columns))
            return real_any(frame, *args, **kwargs)

        def record_dropna(series, *args, **kwargs):
            dropna_columns.append(series.name)
            return real_dropna(series, *args, **kwargs)

        for count in (4, 400):
            requested = columns[-count:][::-1]
            params = [*requested, 'unknown', '', None, requested[0]]
            expected = [p for p in requested if int(p[1:]) % 17] + [requested[0]]
            for name, sanitize in (
                ('legacy_spy_control', _legacy_sanitize_numeric_params),
                ('optimized', _sanitize_numeric_params),
            ):
                with self.subTest(count=count, implementation=name):
                    loc_shapes, notna_columns, any_columns, dropna_columns = [], [], [], []
                    with (
                        patch.object(pd.DataFrame, 'loc', new=property(record_loc)),
                        patch.object(pd.DataFrame, 'notna', new=record_notna),
                        patch.object(pd.DataFrame, 'any', new=record_any),
                        patch.object(pd.Series, 'dropna', new=record_dropna),
                    ):
                        result = sanitize(df, params)
                    self.assertEqual(result, expected)
                    pd.testing.assert_frame_equal(df, before)
                    if name == 'legacy_spy_control':
                        self.assertTrue(loc_shapes)
                        self.assertTrue(all(shape == df.shape for shape in loc_shapes))
                        self.assertEqual(dropna_columns, [*requested, requested[0]])
                        self.assertEqual(notna_columns, [])
                        self.assertEqual(any_columns, [])
                    else:
                        self.assertEqual(
                            loc_shapes, [],
                            'Unique columns must not trigger the full-frame .loc copy',
                        )
                        self.assertEqual(notna_columns, [requested])
                        self.assertEqual(any_columns, [requested])
                        self.assertEqual(dropna_columns, [])
