"""批量图表作业的图形参数贯穿（B8 从已删的同步端点测试迁来）。

``/export/batch_charts/`` 删除后，#6 的「pptx 与 xlsx 两分支收到同一组图形配置」
与 #11 的「默认参数白名单」只剩作业 runner 这一处兑现，判据跟到这里：

* 同一 task（6 个开关 + dpi + cpk_thresholds）走两种 ``chart_format``，
  两个 builder 拿到的图形配置必须逐项相同；
* ``params`` 为空时由 runner 算默认列表：窄 dtype 数值列在内，bool / 文本 /
  系统记录列（SW_Bin）在外（白名单口径本体的判据在
  ``test_export_stats_consistency``，这里只钉 runner 确实用了它）。
"""
import os
import shutil
import tempfile
from unittest import mock

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.jobs import runner

SWITCHES = ('show_limit', 'show_3sigma', 'show_4sigma',
            'show_6sigma', 'show_normal', 'show_kde')
GRAPH_KEYS = set(SWITCHES) | {'dpi', 'cpk_thresholds'}


class JobChartParamsTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='jobs-chart-params-')
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _df(self):
        return pd.DataFrame({
            'SW_Bin': [1, 1, 1, 1],
            'F32': np.array([1.0, 2.0, 3.0, 4.0], dtype='float32'),
            'I32': np.array([1, 2, 3, 4], dtype='int32'),
            'Flag': [True, False, True, True],
            'Text': pd.Series(['a', 'b', 'c', 'd'], dtype='str'),
        })

    def _task(self, **overrides):
        task = {
            'abs_path': 'unused',
            'fmt': 'CTA8290D',
            'out_path': os.path.join(self.tmpdir, 'charts.bin'),
            'params': ['F32'],
            'filters': {},
            'data_only_bin1': False,
            'show_limit': True,
            'show_3sigma': False,
            'show_4sigma': False,
            'show_6sigma': True,
            'show_normal': False,
            'show_kde': False,
            'dpi': 150,
            'cpk_thresholds': (1.67, 1.33, 1.0),
            'chart_format': 'xlsx',
        }
        task.update(overrides)
        return task

    def _capture(self, **overrides):
        captured = {}

        def fake(*args, **kwargs):
            captured['args'] = args
            captured['kwargs'] = kwargs
            return b'payload'

        metadata = {'format': 'CTA8290D', 'units': {}, 'mins': {}, 'maxs': {}}
        patches = [
            mock.patch.object(
                runner, '_parse_and_filter',
                lambda task: (self._df(), metadata)),
            mock.patch.object(runner, 'build_batch_charts_pptx', fake),
            mock.patch.object(
                runner, 'build_batch_charts_xlsx_with_charts', fake),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        runner.run_export_batch_charts(self._task(**overrides))
        return captured

    @staticmethod
    def _graph_config(kwargs):
        return {k: v for k, v in kwargs.items() if k in GRAPH_KEYS}

    def test_pptx_and_xlsx_receive_the_same_graph_config(self):
        overrides = {'show_limit': False, 'show_3sigma': True,
                     'show_4sigma': False, 'show_6sigma': False,
                     'show_normal': True, 'show_kde': True}
        pptx = self._graph_config(
            self._capture(chart_format='pptx', **overrides)['kwargs'])
        xlsx = self._graph_config(
            self._capture(chart_format='xlsx', **overrides)['kwargs'])

        self.assertEqual(pptx, xlsx, '两分支的图形配置必须逐项一致')
        self.assertEqual(set(pptx), GRAPH_KEYS)
        self.assertEqual(pptx['dpi'], 150)
        self.assertEqual(tuple(pptx['cpk_thresholds']), (1.67, 1.33, 1.0))
        for name in SWITCHES:
            self.assertEqual(pptx[name], overrides[name], name)

    def test_empty_params_use_the_narrow_dtype_whitelist(self):
        captured = self._capture(params=[])
        params = list(captured['args'][2])
        self.assertEqual(params, ['F32', 'I32'],
                         'F32/I32 必须在内；bool、文本、SW_Bin 必须在外')
