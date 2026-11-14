# test/backend/test_storage_usage_scan.py
"""批2 磁盘占用的口径测试（T1）。

判据分层：这里只钉「同一个目录树该报几个字节/几个文件/怎么分桶」。
端点契约在 test_files_usage_api.py，两本账与恒等式在本文件后半段（Task 3）。
"""
import os
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.datafiles import storage_usage


def _write(path, size):
    """写一个恰好 size 字节的文件（内容全 'a'，体积可预测）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'a' * size)
    return path


class ScanTreeTests(SimpleTestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, 'data', 'tester')

    def test_空目录返回全零而不是抛错(self):
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['unique_bytes'], 0)
        self.assertEqual(result['file_count'], 0)
        self.assertEqual(result['by_type'], {})

    def test_嵌套目录逐文件加总并计数(self):
        _write(os.path.join(self.root, 'single', 'a.csv'), 1024)
        _write(os.path.join(self.root, 'batch', 'B1', 'sub', 'b.csv'), 1536)
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 2560)
        self.assertEqual(result['file_count'], 2)

    def test_by_type_按根下第一段目录分桶_散文件归入空串(self):
        _write(os.path.join(self.root, 'loose.csv'), 10)
        _write(os.path.join(self.root, 'single', 'a.csv'), 100)
        _write(os.path.join(self.root, 'single', 'nested', 'b.csv'), 200)
        _write(os.path.join(self.root, 'batch', 'B1', 'c.csv'), 1000)
        by = storage_usage._scan_tree(self.root)['by_type']
        self.assertEqual(by['single'], {'bytes': 300, 'count': 2})
        self.assertEqual(by['batch'], {'bytes': 1000, 'count': 1})
        self.assertEqual(by[''], {'bytes': 10, 'count': 1})
        # 分桶必须自洽：各桶之和 == 总量，否则浮层与 chip 会互相打脸
        self.assertEqual(sum(v['bytes'] for v in by.values()), 1310)
        self.assertEqual(sum(v['count'] for v in by.values()), 4)

    def test_口径交叉核对_用rglob独立加总必须相等(self):
        """判据异源（规格 §4.2）：实现走 os.scandir + os.lstat，这里用第二种机制
        pathlib.rglob + Path.stat 自己加总一遍。两个机制给的数必须逐字节相同。
        本用例的树里不放符号链接（rglob 会把它计成文件、而实现按口径跳过它），
        跳过符号链接由下面那条单独的用例钉。"""
        _write(os.path.join(self.root, 'single', 'a.csv'), 700)
        _write(os.path.join(self.root, 'batch', 'B1', 'b.csv'), 322)
        result = storage_usage._scan_tree(self.root)
        files = [p for p in Path(self.root).rglob('*') if p.is_file()]
        self.assertEqual(result['bytes'], sum(p.stat().st_size for p in files))
        self.assertEqual(result['file_count'], len(files))

    def test_硬链接按inode只计一次(self):
        """规格 §4.2 的硬要求：表观口径与唯一口径必须分开，去重靠 (st_dev, st_ino)。
        本机实测 os.lstat 会填 inode（Python 3.13.12 / Windows，见计划头部），
        而 os.DirEntry.stat() 的 st_dev/st_ino 恒为 0 —— 所以实现只能用 lstat。"""
        src = _write(os.path.join(self.root, 'single', 'a.csv'), 4096)
        try:
            os.link(src, os.path.join(self.root, 'single', 'b_hard.csv'))
        except OSError as exc:  # 跨卷/权限做不到就跳过这条判据（同 test_test_data_gc.py:157）
            self.skipTest('本机建不了硬链接：%s' % type(exc).__name__)
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 8192)              # 表观：两个目录项各算一次
        self.assertEqual(result['unique_bytes'], 4096)        # 唯一：同一个 inode
        self.assertEqual(result['file_count'], 2)             # 目录项确实是 2 个

    def test_符号链接不计入(self):
        target = _write(os.path.join(self.base, 'outside.csv'), 5000)
        try:
            os.makedirs(os.path.join(self.root, 'single'), exist_ok=True)
            os.symlink(target, os.path.join(self.root, 'single', 'via_link.csv'))
        except OSError as exc:
            self.skipTest('本机建不了符号链接：%s' % type(exc).__name__)
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['file_count'], 0)

    def test_目录内不可读条目被跳过而不是整体失败(self):
        """一个坏条目不该让整次统计消失（chip 宁缺勿谎，但也不能整体 500）。"""
        good = _write(os.path.join(self.root, 'single', 'a.csv'), 100)
        blocked = os.path.join(self.root, 'single', 'locked')
        os.makedirs(blocked, exist_ok=True)
        os.chmod(good, 0o000)
        self.addCleanup(os.chmod, good, 0o644)
        try:
            result = storage_usage._scan_tree(self.root)
        except OSError as exc:
            self.fail('_scan_tree 不该把单个条目的权限错误抛出去：%s' % exc)
        # Windows 上 chmod 不真正拒读，所以这里只钉「不抛错 + 桶数不多于 1」
        self.assertLessEqual(result['file_count'], 1)
