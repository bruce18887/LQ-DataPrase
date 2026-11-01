"""B5：browse 的 ``col_meta`` 随解析预序列化，每页不再重新 ``json.dumps``。

口径（用户 2026-11-01 拍板选 ②）：只省 CPU、不省传输，**响应键集与字节一字不改**。
``col_meta`` 字典仍留在 metadata 里（``detect_fail`` 等消费方按 dict 读），另存一份
``col_meta_json`` 供 browse 直接拼接 —— 两个挂载点（解析侧 / 写透侧）都要挂。

判据分三层：① 缓存里确有这份串且与 dict 同值；② 响应体里出现的就是这份串（原样拼接，
不是重新序列化）；③ 体积账把串按真实长度计（否则 1702 列那档会被估成 64 字节）。

runner: ``python -X utf8 manage.py test test.backend.test_browse_col_meta_prestd``
"""
import json
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import services as datafile_services
from apps.datafiles.models import DataFile
from apps.datafiles.parse_cache_sizing import _parse_value_bytes
from apps.datafiles.parsers import get_parser

CSV = (
    'CTA8280F\nDevice Name,TEST_DEVICE\nTestFileName,C:\\x\\prog.dll\n'
    '[Data]\n'
    'Site_No,SW_Bin,KELVIN_VIN,\n'
    'Unit,Unit,ohm,\n'
    'Min,Min,0,\n'
    'Max,Max,2,\n'
    '1,1,0.5,\n'
    '1,1,1.0,\n'
    '2,1,1.5,\n'
)


class ColMetaPreSerializedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmpdir = tempfile.mkdtemp(prefix='browse_colmeta_')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        datafile_services._parse_cache.clear()
        self.addCleanup(datafile_services._parse_cache.clear)
        self.user = User.objects.create_user('colmeta', password='pw')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.path = os.path.join(self.tmpdir, f'{self._testMethodName}.csv')
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(CSV)
        self.datafile = DataFile.objects.create(
            owner=self.user, filename=os.path.basename(self.path),
            file_path=self.path, file_size=os.path.getsize(self.path),
            format_type='CTA8280F', status='ready')

    def _loaded(self):
        return datafile_services.get_cached_parsed_file(
            self.datafile.id, self.user.pk, self.datafile)

    def test_cached_metadata_carries_the_serialized_string(self):
        _df, metadata, _fmt = self._loaded()
        self.assertIn('col_meta', metadata, '前提：解析侧仍产 col_meta 字典')
        self.assertIn('col_meta_json', metadata, '解析侧没挂预序列化串')
        self.assertEqual(metadata['col_meta_json'],
                         json.dumps(metadata['col_meta'], ensure_ascii=False))

    def test_response_splices_the_stored_string_verbatim(self):
        body = self.client.get('/api/v1/browse/', {
            'datafile_id': self.datafile.id, 'page_size': 10}).content
        _df, metadata, _fmt = self._loaded()
        fragment = b'"col_meta":' + metadata['col_meta_json'].encode('utf-8')
        self.assertIn(fragment, body, '响应里的 col_meta 不是缓存里那份串（被重新序列化了）')
        self.assertEqual(json.loads(body)['col_meta'], metadata['col_meta'])

    def test_browse_prefers_the_pre_serialized_string(self):
        """判别力：把缓存串换成标记值，响应必须原样带出标记 —— 没重算 dict。"""
        _df, metadata, fmt = self._loaded()
        marker = '{"__MARKER__":1}'
        poisoned = dict(metadata)
        poisoned['col_meta_json'] = marker
        with mock.patch.object(datafile_services, 'get_cached_parsed_file',
                               return_value=(_df, poisoned, fmt)):
            from apps.datafiles.views import browse_views
            with mock.patch.object(browse_views, 'get_cached_parsed_file',
                                   return_value=(_df, poisoned, fmt)):
                body = self.client.get('/api/v1/browse/', {
                    'datafile_id': self.datafile.id, 'page_size': 10}).content
        self.assertIn(b'"col_meta":' + marker.encode('utf-8'), body,
                      'browse 没用预序列化串（标记没带出来）')

    def test_sizing_counts_the_string_by_its_real_length(self):
        col_meta = {'KELVIN_VIN': {'unit': 'ohm', 'min': '0', 'max': '2'}}
        base = {'col_meta': col_meta}
        with_json = dict(base, col_meta_json=json.dumps(col_meta, ensure_ascii=False))
        delta = _parse_value_bytes((None, with_json, 'X')) - _parse_value_bytes(
            (None, base, 'X'))
        self.assertEqual(delta, len(with_json['col_meta_json']),
                         '预序列化串只按 64 字节估 ⇒ 体积预算失真')

    def test_write_through_attaches_the_string(self):
        """写透侧（上传/导入主路径）也必须挂串，否则主路径的首屏每页都要重算。"""
        path = os.path.join(self.tmpdir, 'wt.csv')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(CSV)
        datafile = DataFile.objects.create(
            owner=self.user, filename='wt.csv', file_path=path,
            file_size=os.path.getsize(path), format_type='CTA8280F', status='ready')
        from apps.analysis.services.statistics import build_col_meta
        from apps.datafiles.column_profile import build_column_profile
        df, metadata = get_parser('CTA8280F').parse(path)
        metadata = dict(metadata)
        # 真实形状：旧缓存条目 / 上游已挂好 col_meta 与 column_profile，只缺预序列化串
        metadata['col_meta'] = build_col_meta(df, metadata)
        metadata['column_profile'] = build_column_profile(df, 'CTA8280F')
        metadata['__MARKER__'] = 'wt'
        datafile_services.put_cached_parsed_file(
            datafile.id, self.user.pk, datafile, df, metadata, 'CTA8280F')
        _df, got, _fmt = datafile_services.get_cached_parsed_file(
            datafile.id, self.user.pk, datafile)
        self.assertEqual(got.get('__MARKER__'), 'wt', '写透没命中缓存（条目没写进去）')
        self.assertIn('col_meta_json', got, '写透侧没挂预序列化串')
        self.assertEqual(got['col_meta_json'],
                         json.dumps(got['col_meta'], ensure_ascii=False))
