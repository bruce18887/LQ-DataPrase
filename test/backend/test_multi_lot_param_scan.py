from unittest.mock import patch

import pandas as pd
from django.test import SimpleTestCase

from apps.analysis.services.data_services import multi_lot


class MultiLotParamScanTests(SimpleTestCase):
    def setUp(self):
        self.columns = [f'P{i}' for i in range(20)]
        self.df = pd.DataFrame({col: [1, 2] for col in self.columns})
        self.metadata = {
            'mins': {col: '0' for col in self.columns},
            'maxs': {col: '9' for col in self.columns},
        }
        self.loaded = [
            (1, self.df, self.metadata, 'first.csv'),
            (2, self.df[self.columns[::-1]].copy(), self.metadata, 'second.csv'),
        ]

    def test_ignore_no_limit_scans_once_per_file(self):
        real_scan = multi_lot.get_columns_with_limits
        for file_count in (1, 2):
            with self.subTest(file_count=file_count):
                calls = []

                def record_scan(df, metadata):
                    calls.append(len(df.columns))
                    return real_scan(df, metadata)

                with patch(
                    'apps.analysis.services.data_services.multi_lot.get_columns_with_limits',
                    side_effect=record_scan,
                ) as scan:
                    result = multi_lot.compute_common_params(
                        self.loaded[:file_count], ignore_no_limit=True,
                    )

                self.assertEqual(result, self.columns)
                self.assertEqual(calls, [20] * file_count)
                for call, loaded in zip(scan.call_args_list, self.loaded[:file_count]):
                    self.assertIs(call.args[0], loaded[1])
                    self.assertIs(call.args[1], loaded[2])

    def test_include_no_limit_never_scans_and_preserves_order(self):
        loaded = [(fid, df, {}, name) for fid, df, _, name in self.loaded]
        for file_count in (1, 2):
            with self.subTest(file_count=file_count):
                with patch(
                    'apps.analysis.services.data_services.multi_lot.get_columns_with_limits',
                    side_effect=AssertionError('Unexpected specification scan'),
                ) as scan:
                    result = multi_lot.compute_common_params(
                        loaded[:file_count], ignore_no_limit=False,
                    )

                scan.assert_not_called()
                self.assertEqual(result, self.columns)
