"""批量导入的事务边界测试（性能修复：全量解析移出写事务）。

SQLite 的写事务是全局单写锁（busy_timeout=30000）。原实现把「循环内逐文件
_register_file」整体包在一个 transaction.atomic() 里，而 _register_file 会做
全量解析（275MB 文件实测 3.2s），于是导入 9 只文件时写锁被持有十几秒，其他
用户的任何写请求（上传登记、登录 last_update）都在排队。

这里用确定性断言钉住新边界：解析时不在事务内、每个文件各自一个短事务、
单个文件失败不影响后续文件。

用 TransactionTestCase 而非 TestCase：后者会把每个用例包进一个外层
atomic，connection.in_atomic_block 恒为 True，就测不出「解析发生在事务外」。
"""
import io
import os
import shutil
import tempfile
import zipfile

import pandas as pd
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase, override_settings

from apps.datafiles import services
from apps.datafiles.models import DataFile
from apps.datafiles.views import _helpers


def _frame():
    return pd.DataFrame({'P1': [1.0, 2.0], 'P2': [3.0, 4.0]})


class _AtomicProbeParser:
    """假解析器：每次 parse 记录当时是否处于事务内。"""

    def __init__(self):
        self.in_atomic_block = []
        self.calls = 0

    def parse(self, path):
        self.calls += 1
        self.in_atomic_block.append(connection.in_atomic_block)
        return _frame(), {'program_name': 'PTS'}


def _csv_bytes(name='a.csv'):
    # 头部带 cta8290d，BaseATEParser.identify_format 才会认出格式
    return f'CTA8290D,{name}\nA,B\n1,2\n'.encode('utf-8')


def _build_zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name in names:
            zf.writestr(name, _csv_bytes(name))
    buf.seek(0)
    return buf


class ImportTransactionBoundaryTests(TransactionTestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        # 模块级解析缓存是进程共享的，换掉以免被其它用例污染
        self.original_cache = services._parse_cache
        self.addCleanup(setattr, services, '_parse_cache', self.original_cache)
        services._parse_cache = services._BytesLRUCache(
            services.PARSE_CACHE_BUDGET_BYTES)

        self.user = get_user_model().objects.create_user(
            username='tx_user', password='x')

    def _patch_parser(self):
        parser = _AtomicProbeParser()
        original = _helpers.get_parser
        _helpers.get_parser = lambda fmt: parser
        self.addCleanup(setattr, _helpers, 'get_parser', original)
        return parser

    def test_parse_happens_outside_atomic_block(self):
        parser = self._patch_parser()
        zip_file = _build_zip(['a.csv', 'b.csv'])

        created, error = _helpers._register_zip_batch(
            self.user, zip_file, 'batch1.zip')

        self.assertIsNone(error)
        self.assertEqual(len(created), 2)
        self.assertEqual(parser.calls, 2)
        self.assertEqual(
            parser.in_atomic_block, [False, False],
            f'解析发生在事务内：{parser.in_atomic_block}（写锁会被长时间持有）',
        )

    def test_each_file_gets_its_own_transaction(self):
        parser = self._patch_parser()
        original = _helpers._register_file
        calls = []

        def counting_register(*args, **kwargs):
            calls.append(kwargs.get('parsed'))
            return original(*args, **kwargs)

        _helpers._register_file = counting_register
        self.addCleanup(setattr, _helpers, '_register_file', original)

        created, error = _helpers._register_zip_batch(
            self.user, _build_zip(['a.csv', 'b.csv']), 'batch2.zip')

        self.assertIsNone(error)
        self.assertEqual(len(calls), 2, '每个文件各调一次 _register_file')
        self.assertEqual(len(created), 2)
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 2)
        # 逐文件短事务：解析结果由事务外算好后传入，解析本身不在事务内
        self.assertTrue(all(p is not None for p in calls))
        self.assertEqual(parser.in_atomic_block, [False, False])

    def test_import_keeps_going_after_one_failure(self):
        self._patch_parser()
        original = _helpers._register_file

        def fail_on_second(user, file_path, *args, **kwargs):
            if os.path.basename(file_path) == 'b.csv':
                raise RuntimeError('落库失败')
            return original(user, file_path, *args, **kwargs)

        _helpers._register_file = fail_on_second
        self.addCleanup(setattr, _helpers, '_register_file', original)

        created, error = _helpers._register_zip_batch(
            self.user, _build_zip(['a.csv', 'b.csv']), 'batch3.zip')

        skipped_count = 2 - len(created)
        self.assertIsNone(error)
        self.assertEqual(len(created), 1, '第一个文件仍须落库')
        self.assertEqual(skipped_count, 1, '失败的那个文件计入跳过')
        self.assertEqual(
            list(DataFile.objects.filter(owner=self.user).values_list('filename', flat=True)),
            ['a.csv'],
        )
