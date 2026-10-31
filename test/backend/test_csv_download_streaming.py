"""to_csv 端点「写临时文件 + FileResponse 直读」的等价与峰值判据（H2）。

旧实现 ``df.to_csv(...)`` 先返回整串，``.encode('utf-8-sig')`` 再复制一份
bytes，随后 ``FileResponse(io.BytesIO(...))`` 又复制一份——三份全量 CSV
同时驻留。新实现把 CSV 写进 ``tempfile.TemporaryFile``，``FileResponse``
直接读盘；Windows 上该句柄以 O_TEMPORARY 打开，响应关闭 → 句柄关闭 →
OS 删除文件，既没有「先关句柄再 unlink」的竞态，也不需要路径记账。

峰值口径（与计划正文的偏差及理由）：计划写「用 ``apps/common/memory.py``
的既有采集」，但该模块只有时点采样（``process_private_bytes`` /
``system_memory_snapshot`` / ``memory_snapshot``），**没有峰值收集器**；
单测里断言进程 RSS 差值只会是机器负载噪音。这里改用标准库
``tracemalloc`` 量 Python 分配峰值（确定性、无 ctypes、不碰进程 RSS）。
"""

import gc
import glob
import os
import tempfile
import tracemalloc
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.export import views as export_views
from apps.export.export_csv import CSV_WRITE_CHUNK_ROWS, export_to_csv
from apps.export.views import CSV_TEMP_PREFIX

User = get_user_model()

CSV_URL = '/api/v1/export/to_csv/'


class _ToCsvBase(APITestCase):
    """真实 User + DRF 鉴权，文件加载 patch 成合成数据（不依赖样例 CSV）。"""

    def build_df(self):
        return pd.DataFrame({
            'Serial_No': [1, 2, 3],
            'Part_No': ['P1', 'P2', None],
            'Value': [1.25, np.nan, -0.5],
            'Flag': [True, False, True],
            'Note': ['甲', '', 'b,c'],
        })

    def build_metadata(self):
        return {
            'units': {'Value': 'V'}, 'mins': {'Value': '0'},
            'maxs': {'Value': '2'}, 'format': 'CTA8290D',
        }

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='csvstreamer', password='pw')
        self.client.force_authenticate(self.user)
        self.df = self.build_df()
        self.metadata = self.build_metadata()
        self.datafile = SimpleNamespace(
            id=1, filename='probe.csv', format_type='CTA8290D',
        )
        original = export_views.load_user_file
        export_views.load_user_file = (
            lambda request, file_id=None, **kw: (self.df, self.datafile, self.metadata)
        )
        self.addCleanup(setattr, export_views, 'load_user_file', original)


class ToCsvByteEqualityTests(_ToCsvBase):
    """直读临时文件后，响应体与 ``export_to_csv`` 逐字节相等。"""

    def test_streaming_body_equals_export_to_csv(self):
        expected = export_to_csv(self.df, self.metadata)
        resp = self.client.post(CSV_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('probe_data.csv', resp['Content-Disposition'])
        self.assertEqual(resp['Content-Length'], str(len(expected)),
                         '临时文件句柄仍须让 FileResponse 算出 Content-Length')
        body = b''.join(resp.streaming_content)
        resp.close()
        self.assertEqual(body, expected)
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'), 'utf-8-sig BOM 必须保留')


class ToCsvChunkBoundaryTests(_ToCsvBase):
    """跨分块边界与零行帧也必须与 ``export_to_csv`` 逐字节相等。

    ``export_to_csv_file`` 按 ``CSV_WRITE_CHUNK_ROWS`` 行分块写盘；单块夹具
    （3 行）证明不了「BOM 只写一次、块边界不多一个换行」，所以补两个端点：
    2,500 行（两次跨过 1,000 行边界）与零行（只有表头一行）。
    """

    ROWS = 2_500

    def build_df(self):
        n = self.ROWS
        return pd.DataFrame({
            'Serial_No': np.arange(n, dtype='int64'),
            'V1': np.linspace(0.5, 2.5, n),
            'Note': [f'行{i}' for i in range(n)],
        })

    def test_multi_chunk_frame_matches_byte_oracle(self):
        self.assertGreater(self.ROWS, 2 * CSV_WRITE_CHUNK_ROWS,
                           '夹具必须跨过 1,000 行分块边界两次')
        expected = export_to_csv(self.df, self.metadata)
        resp = self.client.post(CSV_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        body = b''.join(resp.streaming_content)
        resp.close()
        self.assertEqual(body, expected,
                         '多分块的临时文件内容必须与字节判据逐字节相同')
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'), 'BOM 只在开头写一次')

    def test_empty_frame_streams_header_only(self):
        # 零行帧：临时文件里只有 BOM + 表头一行，分块写盘不得多写字。
        self.df = pd.DataFrame({'Value': pd.Series(dtype='float64')})
        expected = export_to_csv(self.df, self.metadata)
        resp = self.client.post(CSV_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Length'], str(len(expected)))
        body = b''.join(resp.streaming_content)
        resp.close()
        self.assertEqual(body, expected)
        self.assertTrue(body.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(body.count(b'\n'), 1, '零行帧只输出表头一行')


class ToCsvTempFileCleanupTests(_ToCsvBase):
    """临时文件生命周期：请求内存在、响应关闭后由 OS 删除、写失败也不残留。"""

    @staticmethod
    def _leftover_exports():
        pattern = os.path.join(tempfile.gettempdir(), CSV_TEMP_PREFIX + '*.csv')
        return sorted(glob.glob(pattern))

    def _record_handles(self):
        """记录视图经 ``tempfile.TemporaryFile`` 创建的句柄。

        ``export_views.tempfile`` 就是标准库 ``tempfile`` 模块本身，替换模块
        属性即可拦到视图里的调用；用完必须还原并关掉所有残留句柄。
        """
        handles = []
        real = tempfile.TemporaryFile

        def fake(*args, **kwargs):
            handle = real(*args, **kwargs)
            handles.append(handle)
            return handle

        export_views.tempfile.TemporaryFile = fake
        self.addCleanup(setattr, export_views.tempfile, 'TemporaryFile', real)
        self.addCleanup(self._close_all, handles)
        return handles

    @staticmethod
    def _close_all(handles):
        for handle in handles:
            if not handle.closed:
                handle.close()

    def _view_response(self):
        """直接调用视图动作拿响应。

        Django 测试客户端会把 ``response.streaming_content`` 换成
        ``closing_iterator_wrapper``，这一赋值会重新走 setter 并把
        ``file_to_stream`` 重置为 ``None``；只有直接调用视图才能看到真正
        交给 WSGI 服务器的那个响应/句柄。
        """
        view = export_views.ExportViewSet()
        request = SimpleNamespace(user=self.user, data={'file_id': 1})
        return view.to_csv(request)

    def test_temp_file_is_removed_after_response_close(self):
        handles = self._record_handles()
        before = self._leftover_exports()
        expected = export_to_csv(self.df, self.metadata)
        resp = self._view_response()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Length'], str(len(expected)))
        self.assertEqual(len(handles), 1, '下载路径应恰好创建一个临时文件')
        handle = handles[0]
        self.assertIs(resp.file_to_stream, handle,
                      'FileResponse 必须直读本次创建的临时句柄')
        path = handle.name
        self.assertTrue(os.path.exists(path), '流式响应期间临时文件必须仍存在')
        self.assertEqual(os.path.getsize(path), len(expected),
                         '返回响应前应已写完整个 CSV')
        body = b''.join(resp.streaming_content)
        resp.close()
        self.assertTrue(handle.closed, '响应关闭必须关闭临时句柄')
        self.assertFalse(os.path.exists(path),
                         'Windows 上句柄一关即由 OS 删除临时文件')
        self.assertEqual(self._leftover_exports(), before,
                         '不得留下本次请求的临时 CSV')
        self.assertEqual(body, expected)

    def test_failed_write_closes_handle_and_reraises(self):
        handles = self._record_handles()
        before = self._leftover_exports()
        original = export_views.export_to_csv_file

        def boom(*args, **kwargs):
            raise RuntimeError('disk full')

        export_views.export_to_csv_file = boom
        self.addCleanup(setattr, export_views, 'export_to_csv_file', original)
        resp = self.client.post(CSV_URL, {'file_id': 1}, format='json')
        self.assertEqual(resp.status_code, 500,
                         '写 CSV 失败必须冒泡成 500，而不是返回残缺文件')
        self.assertEqual(len(handles), 1)
        handle = handles[0]
        path = handle.name
        self.assertTrue(handle.closed, '写失败时必须关闭临时句柄')
        self.assertFalse(os.path.exists(path), '写失败不得留下临时文件')
        self.assertEqual(self._leftover_exports(), before,
                         '写失败不得留下本次请求的临时 CSV')


class ToCsvAllocationPeakTests(_ToCsvBase):
    """大 CSV 下载的 Python 分配峰值必须远低于输出体积。

    判据取「视图峰值 - apply_export_filters 基线 < 输出字节数 / 4」：视图
    一开始就要 ``df.copy()`` 出一份与数据同大的独立帧（约 0.5× 输出体积），
    这份与本次改动无关，也消不掉。旧实现在此之上还要整串 + 整份 bytes +
    BytesIO 三份驻留（本机实测总峰值 ≈3× 输出体积）；新实现按
    CSV_WRITE_CHUNK_ROWS 分块写盘，增量约 0.1×。这里直接调用视图动作而
    不是走 APIClient —— 后者的请求/鉴权/中间件开销会盖过被测的导出路径。
    """

    ROWS = 120_000

    def build_df(self):
        n = self.ROWS
        return pd.DataFrame({
            'Serial_No': np.arange(n, dtype='int64'),
            'V1': np.linspace(0.125, 100.0, n),
            'V2': np.linspace(-50.0, 50.0, n),
            'V3': np.linspace(1.0, 2.0, n),
            'V4': np.arange(n, dtype='float64') / 7.0,
        })

    def _download(self):
        view = export_views.ExportViewSet()
        request = SimpleNamespace(user=self.user, data={'file_id': 1})
        return view.to_csv(request)

    def _download_into(self, sink):
        """走完流写进预分配的 sink、按 WSGI 方式关闭响应，返回收到字节数。

        sink 在 ``tracemalloc.start()`` 之前分配，切片赋值只是就地 memmove，
        不会为整份 CSV 再分配一块被测内存——测量范围仍是「视图 + 流式读盘」，
        与旧判据同口径，峰值不被响应体本身抬高。
        """
        resp = self._download()
        try:
            pos = 0
            for chunk in resp.streaming_content:
                sink[pos:pos + len(chunk)] = chunk
                pos += len(chunk)
            return pos
        finally:
            resp.close()

    @staticmethod
    def _measure(fn):
        gc.collect()
        tracemalloc.start()
        try:
            result = fn()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        return result, peak

    def test_peak_far_below_output_size(self):
        warm = self._download()
        for _ in warm.streaming_content:
            pass
        warm.close()
        expected = export_to_csv(self.df, self.metadata)
        output_size = len(expected)
        self.assertGreater(output_size, 8 * 1024 * 1024,
                           '夹具应产出 8MB 量级 CSV')
        export_views.apply_export_filters(  # warm up the frame copy
            self.df, self.metadata, {'file_id': 1})
        baseline_df, baseline = self._measure(
            lambda: export_views.apply_export_filters(
                self.df, self.metadata, {'file_id': 1}))
        del baseline_df
        sink = bytearray(output_size)  # 测量前预分配：不计入峰值
        written, peak = self._measure(lambda: self._download_into(sink))
        self.assertEqual(written, output_size)
        self.assertEqual(bytes(sink), expected,
                         '120k 行（多分块）输出必须与字节判据逐字节相等')
        extra = peak - baseline
        self.assertLess(
            extra, output_size // 4,
            f'view peak {peak} - filtered-frame baseline {baseline} = '
            f'{extra} bytes / output {output_size} bytes '
            f'(不得再出现整串/整份 bytes 的多副本驻留)',
        )


if __name__ == '__main__':
    unittest.main()
