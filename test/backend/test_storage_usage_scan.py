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

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile


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


class DbMapTests(TestCase):
    """DB 侧两本账（订正②）：只有「resolve 后落在根目录内」的记录才可与磁盘比。

    两套计数各有用途，别混：``in_rows`` / ``in_bytes`` 是**行**口径（进返回体的 db_*），
    ``in_files`` 与 map 是**文件**口径（交集差值用它 —— 磁盘上只有那颗）。

    这里**没有** ``file_size is None`` 的用例，实现里也没有 ``or 0`` 兜底：
    ``file_size`` 是 ``BigIntegerField(null=False)``（``0001_initial.py:23``），实测
    ``update(file_size=None)`` 直接 ``sqlite3.IntegrityError`` —— 那个状态在真库里不存在，
    为它写用例就得 mock 掉整个 ORM，只会让下一个人以为这种数据存在过。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-db-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('inroot', 'ir@localhost', 'x-pass-12345678')

    def _row(self, file_path, file_size):
        return DataFile.objects.create(
            owner=self.user, filename=os.path.basename(file_path),
            file_path=file_path, file_size=file_size,
            format_type='CTA8290D', status='ready',
        )

    def _map(self):
        """造行不需要 MEDIA_ROOT，只有算根目录需要 —— 所以 override 只裹住这一次。"""
        with self.settings(MEDIA_ROOT=self.base):
            return storage_usage._db_map(
                self.user, storage_usage._user_data_root('inroot'))

    def test_相对路径进map_绝对路径落在根外单独记账(self):
        self._row('data/inroot/single/a.csv', 100)
        self._row('data/inroot/batch/B1/b.csv', 250)
        self._row(os.path.join(self.base, 'elsewhere', 'c.csv'), 999)   # 遗留绝对路径
        self._row(r'C:\SampleData\d.csv', 7)                            # 根外/跨盘
        db = self._map()
        self.assertEqual(db['in_rows'], 2)
        self.assertEqual(db['in_bytes'], 350)
        self.assertEqual(db['out_count'], 2)
        self.assertEqual(db['out_bytes'], 1006)

    def test_同一路径两条不同大小的注册行_按id最大那条定胜负(self):
        """不加 order_by 的话 map 里的胜者取决于 values_list 的返回顺序 ⇒ 同一份数据
        两次请求可以给出不同的差值，还在 30s TTL 里冻住一个。定死成 id 最大的那条
        （与 _helpers.py:309 _group_duplicates 的 order_by('id') 同一条纪律）。"""
        self._row('data/inroot/single/a.csv', 100)
        self._row('data/inroot/single/a.csv', 250)
        db = self._map()
        self.assertEqual(db['in_rows'], 2)          # 行口径：两条都算
        self.assertEqual(db['in_files'], 1)         # 文件口径：去重后只剩一颗
        self.assertEqual(db['in_bytes'], 350)       # 行口径的合计
        self.assertEqual(list(db['map'].values()), [250])   # 交集用 id 最大那条

    def test_map的键是normcase后的绝对路径(self):
        """交集靠这个键匹配。键的形态必须与 _scan_tree 查表时用的同一种，
        否则「匹配不上」的方向是 reg_db 与 reg_disk 一起不加 ⇒ 差值恒为 0 ⇒
        该报的不报（假绿），而不是冒出一条虚高差值。所以下面 joined 那批用例断言
        registered_count 非 0 才是真正的护栏，别指望差值行替这条路把关。"""
        self._row('data/inroot/single/a.csv', 100)
        db = self._map()
        key = next(iter(db['map']))
        self.assertEqual(key, os.path.normcase(os.path.normpath(
            os.path.join(self.base, 'data', 'inroot', 'single', 'a.csv'))))
        self.assertEqual(db['map'][key], 100)

    def test_大小写不同的路径也能匹配上(self):
        """Windows 路径大小写不敏感：DB 里写 data/INROOT/... 而磁盘上是 data/inroot/。
        不做 normcase 的话这一条会在交集里凭空消失。"""
        self._row('data/INROOT/single/a.csv', 100)     # 只有大小写不同
        db = self._map()
        self.assertEqual(db['in_rows'], 1)
        self.assertEqual(db['in_files'], 1)

    def test_空表返回全零而不是报错(self):
        db = self._map()
        self.assertEqual(
            db,
            {'map': {}, 'in_rows': 0, 'in_files': 0, 'in_bytes': 0,
             'out_count': 0, 'out_bytes': 0},
        )


class JoinedScanTests(TestCase):
    """订正⑤ 的核心：差值只比「注册行 ∩ 文件确实在盘上」这一交集。

    这四条复刻 Task 1 探针在本机 dev 库实测到的形状（112 条在盘 + 73 条已删 + 漂移 0 B），
    也就是旧口径 ratio=0.1775 / 新口径 ratio=0.0000 那个差。

    ⚠ 根目录必须在 ``self.settings(MEDIA_ROOT=self.base)`` **里面**再算：
    ``_user_data_root`` 读的是 ``settings.MEDIA_ROOT``，在 setUp 里算好会在 override 生效之前
    拿到真实 dev 目录 ⇒ 磁盘侧扫 A 树、DB 侧指向 B 树，交集恒空。用例照样会红，
    但红的原因跟它声称判的东西无关（计划初稿就是这么埋的，2026-11-14 复审时拆出来）。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-join-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('joiner', 'j@localhost', 'x-pass-12345678')

    def _row(self, rel, file_size):
        return DataFile.objects.create(
            owner=self.user, filename=os.path.basename(rel),
            file_path='data/joiner/' + rel, file_size=file_size,
            format_type='CTA8290D', status='ready',
        )

    def _write_own(self, rel, size):
        """在「当前 settings 的 MEDIA_ROOT」下写文件 —— 必须在 override 里调。"""
        path = os.path.join(storage_usage._user_data_root('joiner'), *rel.split('/'))
        return _write(path, size)

    def _joined(self):
        root = storage_usage._user_data_root('joiner')
        db = storage_usage._db_map(self.user, root)
        return storage_usage._scan_tree(root, registered=db['map'])

    def test_文件已不在盘上时不报不一致(self):
        """记录还在、文件早没了 —— 那是孤立记录卡的活；再用 MB 说一遍会让人以为有两个毛病。

        本条钉的是「已删的行不许进交集」：实测把 ``_scan_tree`` 的清单侧换成
        ``sum(registered.values())``（清单全量）红在这里 —— ``5243880 != 1000``。
        它**看不见** ``_mismatch`` 内部退回旧口径（磁盘总量比清单量）：本条三个入参
        按构造全是 1000，任何两个相减都是 0。那一半归 ``test_磁盘孤儿不进差值`` 和
        ``MismatchTests.test_分母是磁盘总量_空目录用1防除零``，两处都做过变异实测。
        """
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._row('single/a.csv', 1000)
            self._row('single/deleted.csv', 5 * 1024 * 1024)
            scan = self._joined()
            flag, diff = storage_usage._mismatch(
                scan['bytes'], scan['registered_disk_bytes'], scan['registered_db_bytes'])
        self.assertEqual(scan['registered_count'], 1)          # 交集只有 a.csv
        self.assertEqual(scan['registered_db_bytes'], 1000)
        self.assertEqual(scan['registered_disk_bytes'], 1000)
        self.assertEqual(scan['bytes'], 1000)
        self.assertFalse(flag)
        self.assertEqual(diff, 0)

    def test_同一条记录的size漂移才报不一致(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)              # 实际 1000
            self._row('single/a.csv', 100)                     # 清单还写着 100
            scan = self._joined()
            flag, diff = storage_usage._mismatch(
                scan['bytes'], scan['registered_disk_bytes'], scan['registered_db_bytes'])
        self.assertEqual(scan['registered_count'], 1)   # 键匹配真的匹配上了（防假绿）
        self.assertTrue(flag)
        self.assertEqual(diff, 900)

    def test_磁盘孤儿不进差值(self):
        """盘上有、清单里没有的那颗（孤立磁盘文件）也不许混进差值。"""
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._write_own('batch/B1/orphan.csv', 4000)       # 没有注册行
            self._row('single/a.csv', 1000)
            scan = self._joined()
        self.assertEqual(scan['bytes'], 5000)        # chip 显示的是全部占用
        self.assertEqual(scan['registered_disk_bytes'], 1000)   # 差值只看交集
        self.assertFalse(storage_usage._mismatch(
            scan['bytes'], scan['registered_disk_bytes'],
            scan['registered_db_bytes'])[0])

    def test_不传registered时只回四个总量键(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 10)
            scan = storage_usage._scan_tree(storage_usage._user_data_root('joiner'))
        self.assertEqual(
            set(scan), {'bytes', 'unique_bytes', 'file_count', 'by_type'})


class MismatchTests(SimpleTestCase):
    """恒等式本身（规格 §4.6 + 订正⑤）：纯算术，不碰文件系统。"""

    def test_阈值是严格大于_恰好5pct不算不一致(self):
        flag, diff = storage_usage._mismatch(1000, 1000, 950)
        self.assertFalse(flag)
        self.assertEqual(diff, 50)

    def test_略超5pct报不一致(self):
        flag, diff = storage_usage._mismatch(1000, 1000, 949)
        self.assertTrue(flag)
        self.assertEqual(diff, 51)

    def test_分母是磁盘总量_空目录用1防除零(self):
        """bytes_total=0 时 max(...,1) 防除零。别顺手把分母改成 registered_disk_bytes ——
        分母选「用户看得见的那个数」才能让 5% 读成「chip 显示的量的 5%」。"""
        self.assertEqual(storage_usage._mismatch(0, 0, 0), (False, 0))
        flag, diff = storage_usage._mismatch(0, 10, 30)
        self.assertTrue(flag)
        self.assertEqual(diff, 20)
        # 上面两句**钉不住**分母的选择（2026-11-14 变异实测：把分母换成
        # registered_disk_bytes 后这三句全绿 —— 这几笔数里 bytes_total 与
        # registered_disk_bytes 要么相等、要么两侧都远越过阈值）。下面这一笔才是判据：
        # 交集里漂 51 B，而用户看得见的是 100000 B ⇒ 真口径 0.051% 不报；
        # 分母一旦换成 registered_disk_bytes 就变成 5.1% ⇒ 冒出一条假的不一致。
        # 同一笔数也把「旧口径（拿磁盘总量当差值的一侧）」杀成 True（51 ⇒ 98,949）。
        self.assertEqual(storage_usage._mismatch(100000, 1000, 1051), (False, 51))

    def test_清单大还是磁盘大都算(self):
        self.assertTrue(storage_usage._mismatch(10000, 1000, 2000)[0])
        self.assertTrue(storage_usage._mismatch(10000, 2000, 1000)[0])


class ComputeUsageTests(TestCase):
    """装配层（`_compute_usage`）必须有自己的判据。

    前面所有用例都直接打 `_scan_tree` / `_db_map` / `_mismatch`，于是「把哪个数喂给
    恒等式」这件事在那些用例里完全看不见：把 `_compute_usage` 里的
    ``scan['registered_db_bytes']`` 换成行口径的 ``db['in_bytes']``，29 条全绿
    （2026-11-14 变异实测，`tasks/mutate_b2_task3.py` 追加的那一档）。下面几条就是堵这个洞的。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-asm-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('assembler', 'a@localhost', 'x-pass-12345678')

    def _row(self, rel, file_size):
        return DataFile.objects.create(
            owner=self.user, filename=os.path.basename(rel),
            file_path='data/assembler/' + rel, file_size=file_size,
            format_type='CTA8290D', status='ready',
        )

    def _write_own(self, rel, size):
        root = storage_usage._user_data_root('assembler')
        return _write(os.path.join(root, *rel.split('/')), size)

    def _usage(self):
        """必须在 ``self.settings(MEDIA_ROOT=self.base)`` **里面**调。

        `manage.py test` 跑的是 ``config.settings.unit``，它的 MEDIA_ROOT 是
        ``test/unit-data/media``（不是 tempdir！）⇒ 漏了 override 时 _write_own 会把文件
        写进那份**跨用例共享**的沙箱，扫描侧却在 tempdir：表现为 usage['bytes'] == 0，
        还在沙箱里留下一堆别人也会读到的残留。2026-11-14 这条初稿就踩上了。
        """
        return storage_usage._compute_usage(self.user)

    def test_磁盘与清单一致时各字段各自成话(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._row('single/a.csv', 1000)
            usage = self._usage()
        self.assertEqual(usage['bytes'], 1000)
        self.assertEqual(usage['unique_bytes'], 1000)
        self.assertEqual(usage['file_count'], 1)
        self.assertEqual(usage['by_type'], {'single': {'bytes': 1000, 'count': 1}})
        self.assertEqual(usage['db_count'], 1)
        self.assertEqual(usage['db_bytes'], 1000)
        self.assertFalse(usage['mismatch_over_threshold'])
        self.assertEqual(usage['mismatch_diff_bytes'], 0)
        self.assertTrue(usage['scanned_at'])
        # 期望值按 self.base 自己拼，别再调一次 _user_data_root：那次调用落在
        # override 外面，读到的会是 unit 档的 MEDIA_ROOT（test/unit-data/media），
        # 与被测值（tempdir）根本不同源 —— 等于用两个不同口径去比口径。
        self.assertEqual(
            os.path.normcase(os.path.normpath(usage['data_dir'])),
            os.path.normcase(os.path.join(self.base, 'data', 'assembler')))

    def test_记录还在文件已删_恒等式必须吃交集而不是行口径(self):
        """订正⑤ 在装配层的判据，也是本机 dev 库的真实形状（112 颗在盘 + 73 条已删）。
        变异判据：喂 `db['in_bytes']` 给 `_mismatch` ⇒ 本条必须红（True is not false）。"""
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._row('single/a.csv', 1000)
            self._row('single/deleted.csv', 5 * 1024 * 1024)
            usage = self._usage()
        self.assertEqual(usage['bytes'], 1000)                   # 磁盘上只剩一颗
        self.assertEqual(usage['db_count'], 2)                   # 行口径照旧两条
        self.assertEqual(usage['db_bytes'], 1000 + 5 * 1024 * 1024)
        self.assertFalse(usage['mismatch_over_threshold'])       # ← 不许吃行口径
        self.assertEqual(usage['mismatch_diff_bytes'], 0)

    def test_size漂移在装配层也要冒出来(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._row('single/a.csv', 100)
            usage = self._usage()
        self.assertTrue(usage['mismatch_over_threshold'])
        self.assertEqual(usage['mismatch_diff_bytes'], 900)

    def test_磁盘孤儿只进磁盘总量不进差值(self):
        """装配层的另一侧：磁盘上多一颗没注册的文件 ⇒ chip 的 bytes 要含它（那就是占用的量），
        而差值不许含它（磁盘孤儿有自己的孤立磁盘卡）。
        变异判据：把 `_mismatch` 的磁盘侧换成 `scan['bytes']` ⇒ 本条必须红。"""
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 1000)
            self._write_own('batch/B1/orphan.csv', 4000)
            self._row('single/a.csv', 1000)
            usage = self._usage()
        self.assertEqual(usage['bytes'], 5000)
        self.assertEqual(usage['file_count'], 2)
        self.assertEqual(usage['db_count'], 1)
        self.assertFalse(usage['mismatch_over_threshold'])
        self.assertEqual(usage['mismatch_diff_bytes'], 0)

    def test_交集的三个内部量不许进返回体(self):
        """规格 §4.6 否掉的就是「没人看得懂的二阶数字」：内部量留在模块里，
        判据打在 `_scan_tree` 与 `_mismatch` 上，不摆到端点去。"""
        with self.settings(MEDIA_ROOT=self.base):
            self._write_own('single/a.csv', 10)
            usage = self._usage()
        for leaked in ('registered_count', 'registered_db_bytes', 'registered_disk_bytes'):
            self.assertNotIn(leaked, usage)


class CacheBehaviourTests(TestCase):
    """缓存的**行为**判据：扫几次、什么时候必须重扫。

    判据打在「计算次数」而不是「返回内容」上 —— 内容与口径的等价性由前面的用例钉，
    这里只钉缓存有没有改变实际发生的扫描数（异源）。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-cache-')
        self.addCleanup(shutil.rmtree, self.base, True)
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('cacheuser', 'c@localhost', 'x-pass-12345678')

    def tearDown(self):
        storage_usage.clear_usage_cache()

    def _counting_compute(self, sink):
        def compute(user):
            sink.append(user.username)
            return {'bytes': len(sink) * 10, 'scanned_at': ''}
        return compute

    def test_同一bucket内第二次调用不再算(self):
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            # 三次调用都要钉住同一个 bucket：不锁 monotonic 的话，落在 30s 桶边界上
            # 的第二次就会重算 —— 那是每 30 秒一次的定时 flaky，CI 上迟早自己冒出来。
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                first = storage_usage.get_user_usage(self.user)
                second = storage_usage.get_user_usage(self.user)
        self.assertEqual(first['bytes'], 10)
        self.assertEqual(second['bytes'], 10)
        self.assertEqual(sink, ['cacheuser'])          # 只算了一次

    def test_fresh为True时强制重算(self):
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                storage_usage.get_user_usage(self.user)
                third = storage_usage.get_user_usage(self.user, fresh=True)
        self.assertEqual(sink, ['cacheuser', 'cacheuser'])
        self.assertEqual(third['bytes'], 20)

    def test_不同用户不共享缓存(self):
        other = User.objects.create_user('otheruser', 'o@localhost', 'x-pass-12345678')
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0), \
                    mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                storage_usage.get_user_usage(self.user)
                storage_usage.get_user_usage(other)
        self.assertEqual(sink, ['cacheuser', 'otheruser'])

    def test_bucket随TTL变化_用假时钟证明换桶必重算(self):
        """钉的是「过期机制 = 换 key」这条形状，不是真的等 30 秒。"""
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                with mock.patch.object(storage_usage.time, 'monotonic', return_value=0.0):
                    storage_usage.get_user_usage(self.user)
                with mock.patch.object(storage_usage.time, 'monotonic',
                                       return_value=float(storage_usage.USAGE_CACHE_TTL_SECONDS)):
                    storage_usage.get_user_usage(self.user)
        self.assertEqual(len(sink), 2)
