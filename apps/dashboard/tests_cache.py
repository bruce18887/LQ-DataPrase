"""仪表板汇总缓存层测试（get_dashboard_summary / clear_dashboard_summary_cache）。

缓存是进程级共享状态，每条用例前后都要清空，否则跨用例串味。
真实 DataFile 行 + 临时 MEDIA_ROOT 下的 CSV，走 resolve_file_path 的正式路径。
"""

import os
import shutil
import tempfile
from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.common.user_settings import CpkThresholds
from apps.dashboard import services
from apps.dashboard.services import (
    clear_dashboard_summary_cache,
    get_dashboard_summary,
)
from apps.datafiles.models import DataFile

User = get_user_model()

HEADER = 'P1,P2,Site,Bin\n'
ROWS_A = '1.0,10.0,S1,1\n2.0,11.0,S1,2\n3.0,12.0,S2,1\n4.0,12.0,S2,1\n'
ROWS_B = '1.0,10.0,S1,1\n2.0,11.0,S1,1\n3.0,12.0,S2,1\n4.0,12.0,S2,2\n5.0,10.5,S2,1\n6.0,11.5,S1,1\n'


class DashboardSummaryCacheTests(TestCase):
    """同 key 命中缓存；阈值/mtime 变化必须重算。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.override = override_settings(MEDIA_ROOT=os.path.join(self.tmp, 'media'))
        self.override.enable()
        self.addCleanup(self.override.disable)

        clear_dashboard_summary_cache()
        self.addCleanup(clear_dashboard_summary_cache)

        self.user = User.objects.create_user(username='cacheuser', password='pw')
        data_dir = os.path.join(self.tmp, 'media', 'data')
        os.makedirs(data_dir, exist_ok=True)
        self.csv_path = os.path.join(data_dir, 'cache.csv')
        self._write_csv(HEADER + ROWS_A)

        self.datafile = self._make_datafile()
        self.metadata = {
            'format': 'ETS88',
            'units': {'P1': 'V'},
            'mins': {'P1': '0.5', 'P2': '9.0'},
            'maxs': {'P1': '5.0', 'P2': '13.0'},
        }
        self.fmt = 'ETS88'

    def _write_csv(self, content):
        with open(self.csv_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)

    def _make_datafile(self):
        return DataFile.objects.create(
            owner=self.user,
            filename='cache.csv',
            file_path='data/cache.csv',
            file_size=os.path.getsize(self.csv_path),
            format_type='ETS88',
            status='ready',
            program_name='cache.pts',
        )

    def _df(self):
        return pd.read_csv(self.csv_path)

    def test_second_call_same_key_does_not_recompute(self):
        """同文件 + 同阈值 + 同 mtime：第二次直接命中缓存，不重算。"""
        real = services.compute_dashboard_summary
        with mock.patch.object(
                services, 'compute_dashboard_summary', side_effect=real) as mocked:
            first = get_dashboard_summary(
                self.datafile, self._df(), self.fmt, self.metadata)
            second = get_dashboard_summary(
                self.datafile, self._df(), self.fmt, self.metadata)

        self.assertEqual(mocked.call_count, 1)
        self.assertIs(first, second)  # 命中返回的是同一个共享对象
        self.assertEqual(first['metrics']['total_rows'], 4)

    def test_threshold_change_recomputes(self):
        """同一文件、不同 cpk_b：key 不同，必须重算且结果对象不同。"""
        real = services.compute_dashboard_summary
        with mock.patch.object(
                services, 'compute_dashboard_summary', side_effect=real) as mocked:
            first = get_dashboard_summary(
                self.datafile, self._df(), self.fmt, self.metadata,
                thresholds=CpkThresholds(1.67, 1.33, 1.0))
            second = get_dashboard_summary(
                self.datafile, self._df(), self.fmt, self.metadata,
                thresholds=CpkThresholds(1.67, 1.5, 1.0))

        self.assertEqual(mocked.call_count, 2)
        self.assertIsNot(first, second)

    def test_mtime_change_recomputes(self):
        """文件内容/mtime 变了：不能返回旧数字。"""
        first = get_dashboard_summary(
            self.datafile, self._df(), self.fmt, self.metadata)
        self.assertEqual(first['metrics']['total_rows'], 4)

        self._write_csv(HEADER + ROWS_B)
        old_ns = os.stat(self.csv_path).st_mtime_ns
        os.utime(self.csv_path, ns=(old_ns + 10 ** 9, old_ns + 10 ** 9))

        real = services.compute_dashboard_summary
        with mock.patch.object(
                services, 'compute_dashboard_summary', side_effect=real) as mocked:
            second = get_dashboard_summary(
                self.datafile, self._df(), self.fmt, self.metadata)

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(second['metrics']['total_rows'], 6)

    def test_clear_cache_forces_recompute(self):
        """清空缓存后同一 key 也会重新计算。"""
        get_dashboard_summary(self.datafile, self._df(), self.fmt, self.metadata)
        clear_dashboard_summary_cache()

        real = services.compute_dashboard_summary
        with mock.patch.object(
                services, 'compute_dashboard_summary', side_effect=real) as mocked:
            get_dashboard_summary(self.datafile, self._df(), self.fmt, self.metadata)

        self.assertEqual(mocked.call_count, 1)
