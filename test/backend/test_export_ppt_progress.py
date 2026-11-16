"""pptx 导出的逐参数进度回调（builder 侧判据）。

runner 侧只钉「回调被传进来」；这里钉回调的**次数与时机**：
每真实产出一张 slide 调一次。两条跳过路径都不许虚报——
参数不在 df 里（缺列），以及在 df 里但整列没有有限值（全 NaN）。
"""
import io
from types import SimpleNamespace

import pandas as pd
from django.test import SimpleTestCase
from pptx import Presentation

from apps.export.export_ppt import build_batch_charts_pptx


class PptxProgressCallbackTests(SimpleTestCase):
    def test_callback_fires_once_per_rendered_param(self):
        calls = []
        df = pd.DataFrame({
            'A': [1.0, 2.0, 3.0, 4.0],
            'B': [1.0, 2.0, 3.0, 4.0],
            'C': [float('nan')] * 4,
        })
        metadata = {'units': {'A': 'V', 'B': 'V', 'C': 'V'},
                    'mins': {'A': '1', 'B': '1', 'C': '1'},
                    'maxs': {'A': '4', 'B': '4', 'C': '4'},
                    'format': 'CTA8290D'}
        datafile = SimpleNamespace(filename='p.csv', format_type='CTA8290D',
                                   program_name='P')

        blob = build_batch_charts_pptx(
            datafile, df, metadata, ['A', 'MISSING', 'C', 'B'],
            progress_cb=calls.append)

        self.assertGreater(len(blob), 0, 'PPTX 不得为空')
        self.assertEqual(calls, [1, 2],
                         '只对真实渲染出的参数回调，跳过的参数不虚报')
        self.assertEqual(len(Presentation(io.BytesIO(blob)).slides), 2,
                         '回调次数必须与真实 slide 数一致')
