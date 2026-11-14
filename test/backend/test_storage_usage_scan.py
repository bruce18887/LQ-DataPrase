# test/backend/test_storage_usage_scan.py
"""批2 磁盘占用的口径测试（T1）。

判据分层：这里只钉「同一个目录树该报几个字节/几个文件/怎么分桶」。
端点契约在 test_files_usage_api.py，两本账与恒等式在本文件后半段（Task 3）。

关于「注入故障」的那几条：本机的 ``os.chmod(0o000)`` **不真的拒读**（实测 lstat 照样成功），
所以想钉「一个坏条目不许拖垮整次扫描」这两条 except OSError 分支，只有注入一条路。
注入用的 wrapper 对其他路径一律委托给真实现，所以窗口内不会波及 Django 自己的调用。
每条注入用例都配了变异判据：把对应的 ``continue`` 改成 ``raise``，用例必须红。
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

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

    def test_根不存在时返回全零而不是抛错(self):
        # 新装机/新用户根本没建过目录，这是最常见的空态。
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['unique_bytes'], 0)
        self.assertEqual(result['file_count'], 0)
        self.assertEqual(result['by_type'], {})

    def test_空目录同样返回全零(self):
        # 与上一条分开：目录存在但为空 与 目录不存在 走的是不同的返回路径
        # （_iter_files 的 isdir 早退 vs 扫描到零条目），混在一条里就只钉住了前者。
        os.makedirs(self.root)
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['file_count'], 0)
        self.assertEqual(result['by_type'], {})

    def test_根是文件而不是目录时返回全零(self):
        path = _write(os.path.join(self.base, 'afile.csv'), 100)
        result = storage_usage._scan_tree(path)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['file_count'], 0)

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
        result = storage_usage._scan_tree(self.root)
        by = result['by_type']
        self.assertEqual(by['single'], {'bytes': 300, 'count': 2})
        self.assertEqual(by['batch'], {'bytes': 1000, 'count': 1})
        self.assertEqual(by[''], {'bytes': 10, 'count': 1})
        # 自洽性对着 result 自己比，不写死 1310/4：写死的话「总量与分桶一起算错」就查不出来，
        # 而那正是浮层与 chip 互相打脸的形状。
        self.assertEqual(sum(v['bytes'] for v in by.values()), result['bytes'])
        self.assertEqual(sum(v['count'] for v in by.values()), result['file_count'])

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
        # 第三颗必须是「不是硬链接、体积也不同」的独立文件，这条用例才有判别力：
        # 只放硬链对时，把取 inode 改成 os.DirEntry.stat()（本机填不出 inode ⇒ 所有
        # 条目都塌到同一个 (0, 0) 键）算出来的 unique_bytes 与正确实现**一模一样**，
        # 2026-11-14 按变异实测过：那样 7 例全绿。有了这颗不同体积的独立文件，坏实现
        # 会把三颗全压成 1 个 inode，unique 直接少算。
        _write(os.path.join(self.root, 'single', 'c_own.csv'), 1000)
        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 4096 * 2 + 1000)      # 表观：三个目录项各算一次
        self.assertEqual(result['unique_bytes'], 4096 + 1000)    # 唯一：两个 inode
        self.assertEqual(result['file_count'], 3)                # 目录项确实是 3 个

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

    def test_单个文件读不到时其余照常计入且不抛错(self):
        """注入版（2026-11-14 订正）：本机 chmod(0o000) 之后 os.lstat 实测**仍然成功**，
        所以靠权限造不出这个分支，那条写法判不出任何东西。改成只对一个路径抛 OSError。
        变异判据：把 _iter_files 条目分支的 continue 改成 raise ⇒ 本条必须红。"""
        _write(os.path.join(self.root, 'single', 'a.csv'), 100)
        bad = _write(os.path.join(self.root, 'single', 'b.csv'), 200)
        good = _write(os.path.join(self.root, 'single', 'c.csv'), 300)
        real_lstat = os.lstat
        target = os.path.normcase(bad)

        def fake_lstat(path, *args, **kwargs):
            if os.path.normcase(path) == target:
                raise OSError('simulated unreadable')
            return real_lstat(path, *args, **kwargs)

        with mock.patch.object(storage_usage.os, 'lstat', fake_lstat):
            result = storage_usage._scan_tree(self.root)
        self.assertEqual(os.path.getsize(good), 300)             # 前置：好的那颗确实在盘上
        self.assertEqual(result['bytes'], 400)                   # 少了坏的那一颗
        self.assertEqual(result['file_count'], 2)
        self.assertEqual(result['by_type']['single'], {'bytes': 400, 'count': 2})

    def test_单个子目录读不到时其余照常计入且不抛错(self):
        """目录分支（_iter_files 的外层 except OSError）单独钉一条：它和条目分支
        是两处不同的 continue，任何一处被改成 raise 都会让整次扫描消失。
        变异判据：外层 continue 改成 raise ⇒ 本条必须红。"""
        _write(os.path.join(self.root, 'single', 'a.csv'), 100)
        _write(os.path.join(self.root, 'broken', 'b.csv'), 900)
        real_scandir = os.scandir
        broken = os.path.normcase(os.path.join(self.root, 'broken'))

        def fake_scandir(path, *args, **kwargs):
            if os.path.normcase(path) == broken:
                raise OSError('simulated unreadable dir')
            return real_scandir(path, *args, **kwargs)

        with mock.patch.object(storage_usage.os, 'scandir', fake_scandir):
            result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 100)
        self.assertEqual(result['file_count'], 1)
        self.assertEqual(result['by_type'], {'single': {'bytes': 100, 'count': 1}})

    def test_目录联接junction不进树(self):
        """Windows 的 junction 是**本条而不是符号链接那条**才钉住的：实测
        ``mklink /J`` 造出来的条目 ``is_symlink() == False``、
        ``is_dir(follow_symlinks=False) == True`` —— 只判 is_symlink 的旧写法会走进去，
        把别人目录的体积算到这个用户头上（自引用 junction 还能递归到 MAX_PATH）。
        变异判据：``_iter_files`` 里去掉 ``or entry.is_junction()`` ⇒ 本条必须红。"""
        target = os.path.join(self.base, 'elsewhere')
        _write(os.path.join(target, 'big.bin'), 500000)
        link = os.path.join(self.root, 'single', 'via_junction')
        os.makedirs(os.path.dirname(link), exist_ok=True)
        try:
            done = subprocess.run(
                ['cmd', '/c', 'mklink', '/J', link, target],
                capture_output=True,
            )
            if done.returncode != 0 or not os.path.isdir(link):
                self.skipTest('本机造不出 junction（rc=%s）' % done.returncode)
        except OSError as exc:
            self.skipTest('本机造不出 junction：%s' % type(exc).__name__)
        self.addCleanup(shutil.rmtree, link, True)

        result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 0)
        self.assertEqual(result['file_count'], 0)
        self.assertEqual(result['by_type'], {})


class InodeFallbackTests(SimpleTestCase):
    """``st_ino`` 一律为 0 的文件系统（网络盘、部分虚拟盘）不许把整棵树塌成一份。

    塌掉的后果是 unique_bytes 只剩一颗文件的体积 —— 与 lessons 2026-10-24 那次
    「5.0GB 报成 0.07MB」同一个形状，只是成因不同。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-ino-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = os.path.join(self.base, 'data', 'tester')
        _write(os.path.join(self.root, 'single', 'a.csv'), 100)
        _write(os.path.join(self.root, 'single', 'b.csv'), 200)

    def test_ino为0时不去重_宁可高估(self):
        real_lstat = os.lstat

        def zeroed_lstat(path, *args, **kwargs):
            st = real_lstat(path, *args, **kwargs)
            return SimpleNamespace(st_dev=st.st_dev, st_ino=0, st_size=st.st_size)

        with mock.patch.object(storage_usage.os, 'lstat', zeroed_lstat):
            result = storage_usage._scan_tree(self.root)
        self.assertEqual(result['bytes'], 300)
        self.assertEqual(result['unique_bytes'], 300)   # 不去重，而不是塌成 100 或 200


class ScanRootGuardTests(SimpleTestCase):
    def test_带registered时root必须是绝对路径(self):
        """相对 root ⇒ entry.path 也是相对 ⇒ 与 map 的键永不命中 ⇒ 交集恒空、
        差值恒 0（假绿）。宁可当场报错，不交出一个看起来正常的 0。"""
        with self.assertRaises(ValueError):
            storage_usage._scan_tree('relative/root', registered={'whatever': 1})

    def test_不带registered时相对root仍然可用(self):
        # 纯总量扫描不需要键命中，别把它一起禁掉（Task 2 的既有测试都用绝对路径，
        # 这条只是把守卫的边界画清楚）。
        result = storage_usage._scan_tree('definitely/not/here')
        self.assertEqual(result['bytes'], 0)


class UserDataRootTests(SimpleTestCase):
    """用户名会拼进扫描路径，所以 '.'/'..' 这类写法必须挡（实测默认 validator 接受 '..'）。"""

    def test_正常用户名拼出MEDIA_ROOT下的目录(self):
        with self.settings(MEDIA_ROOT=os.path.join('C:', 'x', 'media')):
            self.assertEqual(
                os.path.normpath(storage_usage._user_data_root('admin')),
                os.path.normpath(os.path.join('C:', 'x', 'media', 'data', 'admin')),
            )

    def test_点点点之类的用户名直接报错(self):
        """``MEDIA_ROOT/data/..`` 归一化就是 MEDIA_ROOT ⇒ 这一个用户会看到所有人的量。
        顺带说明为什么不用 os.path.basename 防：basename('..') 实测还是 '..'。"""
        with self.settings(MEDIA_ROOT=os.path.join('C:', 'x', 'media')):
            for bad in ('..', '.', '', 'a' + os.sep + 'b'):
                with self.assertRaises(ValueError, msg=bad):
                    storage_usage._user_data_root(bad)
