"""T1：重复文件的保留选择契约（批3a · 第 3 项）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection

为什么另起一份而不写进 ``apps/datafiles/tests.py``：那份已 1959 行、冻在 600 行闸的 EXEMPT
登记值上（``scripts/line-limit.mjs:36``），多一行就 ``kind:'grew'`` 报红。既有那五条重复文件用例
（tests.py:1218 403 / :1241 同名不同大小 / :1255 保留最早 / :1277 只删批次内文件 / :1299 计数）
**逐字不动** —— 它们是「向后兼容」的证据，不是本批的靶子。

造树与 test_files_usage_api.py 同一种：临时 MEDIA_ROOT + ``self.settings``。⚠ 这里必须真的
把 MEDIA_ROOT 指到临时根：``_delete_datafile_file_only`` 删完文件会**向上递归摘空目录**，
一直走到 ``settings.MEDIA_ROOT`` 才停（``_helpers.py:232-242``）—— 不设就等于让它去删系统
临时区里的空目录。

三类形状各占一段：
① `_resolve_keep_selection` 的**双向**闸门（Task 2 的正向白名单 + 终审修复轮的反向覆盖）；
② 真删的三种保留结果 + 覆盖漏组 + 被占用文件的计数（Task 3）；
③ 经 HTTP 的响应形状、400 家族与 51 组切片（Task 4）。

终审修复轮（2026-11-15）为什么补这几条：只有正向白名单时，「载荷非空但漏了某个已展示组」
会走到 `_delete_duplicate_files` 那句默认回落（`files[0]`），于是一组**用户从未见过**的文件
被静默删光 —— GET 与 POST 之间列表一变（多导入一条、或某组塌成一行让第 51 组滑进来）就会发生，
正好是本批要消灭的「服务端替用户决定」。所以新增的两条承重断言是：
漏一组 ⇒ 抛错且**磁盘与 DB 都原样**；空数组 ⇒ 仍走 legacy（向后兼容不许被这道新闸打死）。
另有一条钉 §5.2 那句「`deleted_count` 是这条不可撤销路径上唯一的闸」：`os.remove` 失败时
计数不许把没删掉的字节算进去（DB 行照删，遗留文件下次检查以孤立磁盘文件露面）。
"""

import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.datafiles.views._duplicate_files import (
    DUPLICATE_DISPLAY_LIMIT,
    InvalidKeepSelection,
    _group_duplicates,
    _resolve_keep_selection,
)


def _group(filename, ids, size=500):
    """造一个 `_group_duplicates` 形状的检查组（files 按 id 升序，与真函数一致）。"""
    return {
        'filename': filename,
        'file_size': size,
        'files': [
            {
                'id': i,
                'filename': filename,
                'file_size': size,
                'file_type': 'single',
                'batch_name': '',
                'sub_batch': '',
                'created_at': '2026-01-0%dT00:00:00+00:00' % (n % 9 + 1),
            }
            for n, i in enumerate(ids)
        ],
    }


class ResolveKeepSelectionTests(TestCase):
    """`keep_ids` 与已展示切片**双向**对齐：每枚 id 都必须在切片里（白名单），
    且非空载荷必须覆盖切片里每一组。越界与漏组一律抛，且**抛在任何删除之前**。"""

    def setUp(self):
        self.groups = [
            _group('a.csv', [10, 11]),
            _group('b.csv', [20, 21, 22]),
        ]

    def _resolve(self, keep_ids, groups=None, limit=None):
        return _resolve_keep_selection(
            groups if groups is not None else self.groups,
            keep_ids,
            limit if limit is not None else DUPLICATE_DISPLAY_LIMIT,
        )

    def test_空keep_ids返回空映射并交出整个切片(self):
        displayed, keep_by_key = self._resolve([])
        self.assertEqual([g['filename'] for g in displayed], ['a.csv', 'b.csv'])
        self.assertEqual(keep_by_key, {}, '没指定就什么都别钉，由调用方回落默认最小 id')

    def test_合法保留项按分组键落位(self):
        _, keep_by_key = self._resolve([11, 20])
        self.assertEqual(keep_by_key, {('a.csv', 500): 11, ('b.csv', 500): 20},
                         '跨两组各选一枚是**正常载荷**（旧设计那句「指向别的组→400」不成立）')

    def test_不存在的id被拒(self):
        with self.assertRaises(InvalidKeepSelection):
            self._resolve([999])

    def test_未进入切片的组的id被拒(self):
        tail = _group('zz.csv', [900, 901])
        groups = [_group('g%02d.csv', [i * 2 + 10, i * 2 + 11]) for i in range(50)] + [tail]
        with self.assertRaises(InvalidKeepSelection):
            self._resolve([900], groups=groups, limit=50)

    def test_同组两枚被拒(self):
        with self.assertRaises(InvalidKeepSelection):
            self._resolve([10, 11])

    def test_非整数被拒(self):
        for bad in (['10'], [10.0], [None]):
            with self.assertRaises(InvalidKeepSelection, msg=repr(bad)):
                self._resolve(bad)

    def test_布尔被拒且拒在类型闸门(self):
        """`True` 必须撞「必须是整数数组」那道闸门，而不是撞白名单那道。

        为什么单独一条、还钉消息（2026-11-14 变异 M3 实测逼出来的）：fixture 的 id 空间
        不含 1，而 `hash(True) == hash(1)` —— 只断异常类型时，删掉 bool 闸门后
        `allowed.get(True)` 返回 None，改由**白名单**那条抛出，同一个异常类型把两条防线
        的存在性混成一条，变异当场跑成全绿。探针实证删闸门后含 pk=1 的组 + `[True]`
        会被**静默接受**并按「留 id 1」执行 —— 那就是本项要修的「替用户决定」。
        """
        with self.assertRaisesRegex(InvalidKeepSelection, '整数数组'):
            self._resolve([True])

    def test_切片外的组不参与校验(self):
        """limit 之内没被选中的组，keep_by_key 里不该出现它的键。"""
        _, keep_by_key = self._resolve([11], limit=1)
        self.assertEqual(keep_by_key, {('a.csv', 500): 11})

    def test_非空载荷漏掉一个已展示组被拒(self):
        """反向闸门（终审修复轮 Fix 1）：`[11]` 只覆盖 a 组，b 组没被提到。

        放行它 == 让调用方对 b 组回落到默认 `files[0]` 去删，而 b 组完全可能在 GET 之后
        才是「用户没见过的那一组」。消息必须让人知道下一步是**重新检查**，不是重试。
        """
        with self.assertRaisesRegex(InvalidKeepSelection, '覆盖'):
            self._resolve([11])

    def test_非空载荷覆盖全部已展示组时通过(self):
        """反向闸门的正例：每组恰一枚 ⇒ 正常落位，不误伤自己的客户端。"""
        displayed, keep_by_key = self._resolve([11, 22])
        self.assertEqual(len(displayed), 2)
        self.assertEqual(keep_by_key, {('a.csv', 500): 11, ('b.csv', 500): 22})

    def test_空载荷不做覆盖校验(self):
        """legacy 分支（§5.3 第 2 条）：空数组 == 什么都没送 ⇒ 每组按默认，不抛。

        这条是 F-1b 变异的靶子：把反向闸门写成「不区分空载荷」，两处 legacy 用例
        （本条 + 删除层的空数组例 + HTTP 层的空数组例）当场红。
        """
        for empty in ([], ()):
            displayed, keep_by_key = self._resolve(empty)
            self.assertEqual(len(displayed), 2, '切片照常交出')
            self.assertEqual(keep_by_key, {}, '空载荷恒等于「没钉任何保留项」')

    def test_切片为空且载荷为空时不抛(self):
        """没有重复组 + 没有载荷 ⇒ 两边都空，覆盖检查不该凭空报错。"""
        displayed, keep_by_key = self._resolve([], groups=[], limit=50)
        self.assertEqual(displayed, [])
        self.assertEqual(keep_by_key, {})


class DeleteByKeepSelectionTests(TestCase):
    """真删的三种结果：默认最早 / 指定最新 / 跨两组各留被选那份。

    这一类**不经 HTTP**：视图接线归 Task 4，这里只钉「函数拿到 keep_ids 之后删对了谁」。
    每条都要同时断磁盘（真删，不是只删 DB 行）与 DB 行。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-dup-fn-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('dup_fn_a', 'da@localhost', 'x-pass-12345678')

    def _pair(self, filename, tag, size=10):
        """同名同大小两行，落在两个目录（同目录会同名覆盖成一只物理文件）。"""
        rows = []
        for letter in ('p', 'q'):
            directory = os.path.join(self.base, '%s_%s' % (tag, letter))
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, filename)
            with open(path, 'wb') as fh:
                fh.write(b'\0' * size)
            rows.append(DataFile.objects.create(
                owner=self.user, filename=filename, file_path=path, file_size=size,
                format_type='CTA8290D',
            ))
        return rows

    def _delete(self, keep_ids=()):
        from apps.datafiles.views._duplicate_files import _delete_duplicate_files
        with self.settings(MEDIA_ROOT=self.base):
            return _delete_duplicate_files(self.user, keep_ids)

    def test_不带keep_ids时保留最早并且磁盘文件真删(self):
        first, second = self._pair('a.csv', 'def')
        deleted, remaining = self._delete()
        self.assertEqual((deleted, remaining), (1, 0))
        self.assertTrue(DataFile.objects.filter(pk=first.id).exists(), '默认留 id 最小那条')
        self.assertFalse(DataFile.objects.filter(pk=second.id).exists())
        self.assertTrue(os.path.exists(first.file_path))
        self.assertFalse(os.path.exists(second.file_path), '只删 DB 行不算删干净')

    def test_指定保留最新时删掉最早那条(self):
        first, second = self._pair('b.csv', 'latest')
        deleted, remaining = self._delete([second.id])
        self.assertEqual((deleted, remaining), (1, 0))
        self.assertFalse(DataFile.objects.filter(pk=first.id).exists())
        self.assertTrue(DataFile.objects.filter(pk=second.id).exists())
        self.assertFalse(os.path.exists(first.file_path))
        self.assertTrue(os.path.exists(second.file_path))

    def test_跨两组各选一枚各自留被选那份(self):
        a1, a2 = self._pair('c.csv', 'c')
        b1, b2 = self._pair('d.csv', 'd')
        deleted, remaining = self._delete([a2.id, b1.id])
        self.assertEqual((deleted, remaining), (2, 0))
        alive = set(DataFile.objects.filter(owner=self.user).values_list('id', flat=True))
        self.assertEqual(alive, {a2.id, b1.id},
                         '两枚保留项互不干扰：证明 keep 是**逐组**裁决而不是全局一枚')

    def test_校验失败时一行都不删(self):
        first, second = self._pair('e.csv', 'e')
        with self.assertRaises(InvalidKeepSelection):
            self._delete([999999])
        alive = DataFile.objects.filter(owner=self.user).count()
        self.assertEqual(alive, 2, '抛在删除之前 ⇒ 这条才是「不静默删一半」的证据')
        self.assertTrue(os.path.exists(first.file_path) and os.path.exists(second.file_path))

    def test_非空载荷漏一组时抛错且磁盘与DB都原样(self):
        """Fix 1 的主判据：两组夹具、只覆盖 a 组 ⇒ 抛 `InvalidKeepSelection`，
        而 b 组**一行都不能少**（DB 与磁盘同时核）。

        为什么不能只断言抛错：删一半再抛也是抛。b 组那两只文件是本条唯一的承重，
        「用户没见过的组被默认策略删光」正是它要拦的形状。
        """
        a1, a2 = self._pair('k1.csv', 'k1')
        b1, b2 = self._pair('k2.csv', 'k2')
        with self.assertRaisesRegex(InvalidKeepSelection, '覆盖'):
            self._delete([a2.id])
        self.assertEqual(set(DataFile.objects.filter(owner=self.user).values_list('id', flat=True)),
                         {a1.id, a2.id, b1.id, b2.id}, '四行一行不少')
        for row in (a1, a2, b1, b2):
            self.assertTrue(os.path.exists(row.file_path), '%s 还在盘上' % row.file_path)

    def test_非空载荷全量覆盖时正常删除(self):
        """反向闸门的正例（走真删）：两组各送一枚 ⇒ 两组各删其余，且磁盘真的没了。

        与 `test_跨两组各选一枚各自留被选那份` 的分工：那条只核 DB 里活着的是谁，
        本条额外核**磁盘**（`_pair` 造的物理文件）—— 覆盖校验放行正常载荷时不能顺手把
        文件留在盘上、也不能反过来只删 DB 行。
        """
        a1, a2 = self._pair('m1.csv', 'm1')
        b1, b2 = self._pair('m2.csv', 'm2')
        deleted, remaining = self._delete([a2.id, b2.id])
        self.assertEqual((deleted, remaining), (2, 0))
        alive = set(DataFile.objects.filter(owner=self.user).values_list('id', flat=True))
        self.assertEqual(alive, {a2.id, b2.id})
        for doomed in (a1, b1):
            self.assertFalse(os.path.exists(doomed.file_path), '被删那份的字节必须真的没了')
        for kept in (a2, b2):
            self.assertTrue(os.path.exists(kept.file_path))

    def test_空数组载荷在多组夹具上仍走默认留最早(self):
        """§5.3 第 2 条的 legacy 分支：`keep_ids=[]` 与「不带该键」同义 ⇒ 每组留 id 最小。

        F-1b 的靶子：把反向闸门写成不区分空载荷，本条红在 `(2, 0)` 之前先抛
        `InvalidKeepSelection`（老客户端与脚本的通路被新闸打死）。
        """
        a1, a2 = self._pair('n1.csv', 'n1')
        b1, b2 = self._pair('n2.csv', 'n2')
        deleted, remaining = self._delete([])
        self.assertEqual((deleted, remaining), (2, 0), '空载荷照样删两组，各留最早')
        alive = set(DataFile.objects.filter(owner=self.user).values_list('id', flat=True))
        self.assertEqual(alive, {a1.id, b1.id})
        self.assertFalse(os.path.exists(a2.file_path))
        self.assertFalse(os.path.exists(b2.file_path))

    def test_文件被占用删不掉时计数不含它_行照删字节成孤立磁盘文件(self):
        """§5.2 的兑现：用户已否掉 `.trash` ⇒ `deleted_count` 是这条不可撤销路径上唯一的闸，
        它只能统计**字节真的不在盘上了**的那些。

        形状：两组各两条，只把 k 组该删的那只对 `os.remove` 抛 `OSError`（模拟 Windows 占用），
        另一组正常。三件同时成立才算修好：
        ① 计数 1 而不是 2（前端按钮那句「（X MB）」读的就是这个数）；
        ② 被占用那行的 **DB 行仍然删掉** —— 这是本调用点选的口径：
           `_delete_datafile_file_only` 的返回值契约由 4 个调用点共用
           （`test_parse_cache_invariant_scan.py` 的 `EXPECTED_SITES` 按文件钉着），
           为「已经不在盘上」与「remove() 失败」给同一个返回值而改它，代价是另外三处；
        ③ 那只文件还在盘上 ⇒ 它下一次一致性检查会以**孤立磁盘文件**露面，
           由 `delete_orphaned_disk` 那条通路清理。不计数是「如实报告」，不是补救手段。
        """
        a_keep, a_doomed = self._pair('k1.csv', 'k1')
        b_keep, b_doomed = self._pair('k2.csv', 'k2')
        real_remove = os.remove
        locked = os.path.normcase(a_doomed.file_path)

        def locked_remove(path):
            if os.path.normcase(path) == locked:
                raise OSError(13, '另一个程序正在使用此文件，进程无法访问该文件')
            return real_remove(path)

        with mock.patch('os.remove', side_effect=locked_remove):
            deleted, remaining = self._delete([a_keep.id, b_keep.id])
        self.assertEqual(deleted, 1, '被占用那只不算进计数：它还在盘上')
        self.assertEqual(remaining, 0, '两组各塌成 1 行 ⇒ 剩余组数与计数是两件事')
        self.assertFalse(DataFile.objects.filter(pk=a_doomed.id).exists(),
                         '本调用点口径：注册行照删（见 docstring ②）')
        self.assertTrue(DataFile.objects.filter(pk=a_keep.id).exists())
        self.assertTrue(os.path.exists(a_doomed.file_path),
                        '字节还在盘上 ⇒ 下次检查报孤立磁盘文件（见 docstring ③）')
        self.assertFalse(os.path.exists(b_doomed.file_path), '没被占用的那组照常真删')

    def test_本来就没有文件时仍按删除计数(self):
        """把「已经不在盘上」与「remove() 失败」分开：前者计数，后者不计数。

        注册行指向一只不存在的文件（DB 有、盘上没有，正是 `delete_orphaned_db` 那条通路
        要清的形状），删掉它没有字节可留 ⇒ 计数照加。没有本条时，把判据写成
        `if unlinked is None: continue` 也能让上一条占用例绿 —— 那是另一种说谎。
        """
        directory = os.path.join(self.base, 'ghost_p')
        os.makedirs(directory, exist_ok=True)
        gone = os.path.join(directory, 'gone.csv')
        live_dir = os.path.join(self.base, 'ghost_q')
        os.makedirs(live_dir, exist_ok=True)
        live = os.path.join(live_dir, 'gone.csv')
        with open(live, 'wb') as fh:
            fh.write(b'\0' * 10)
        ghost = DataFile.objects.create(
            owner=self.user, filename='gone.csv', file_path=gone, file_size=10,
            format_type='CTA8290D')
        real = DataFile.objects.create(
            owner=self.user, filename='gone.csv', file_path=live, file_size=10,
            format_type='CTA8290D')
        self.assertFalse(os.path.exists(gone), '前置：ghost 的字节本来就不在盘上')
        deleted, remaining = self._delete([real.id])
        self.assertEqual((deleted, remaining), (1, 0),
                         '本来就没有文件 ⇒ 没有字节可留，计数照加（这才是如实报告）')
        self.assertFalse(DataFile.objects.filter(pk=ghost.id).exists(), 'ghost 的注册行被删')
        self.assertTrue(DataFile.objects.filter(pk=real.id).exists(), '保留项是 real')
        self.assertTrue(os.path.exists(live))

    def test_每组files按id升序_前端默认保留项直接取首条的前提(self):
        """前端 `defaultKeepId` 取的是 `files[0].id`，`strategyKeepId` 的并列裁决也落在首条。

        两边都不重排序 —— 所以「后端给的 files 是 id 升序」这条契约一旦变，前端两处会
        一起静默选错，而 TS 与 e2e 都不会报（形状完全一样，错的只是哪一条在前）。

        ⚠ 计划原文这条的函数名带全角括号，Python 里 U+FF08 不是合法标识符字符
        （`SyntaxError: invalid character '（'`，实测）⇒ 名字改成下划线连接，判据不变。
        """
        first, second = self._pair('h.csv', 'h')
        groups = _group_duplicates(self.user)
        self.assertEqual(len(groups), 1)
        ids = [f['id'] for f in groups[0]['files']]
        self.assertEqual(ids, sorted(ids), 'files 必须 id 升序')
        self.assertEqual(ids, [first.id, second.id])

    def test_remaining_groups是删完重算的实测值(self):
        """两组、塌掉一组后只处理 f ⇒ 剩 0，钉的是「删完重算」这条口径的实现。

        ⚠ 计划原文预测本条能抓住 `len(groups) - len(displayed)` 的算术写法（M5），
        **实测没抓住**（变异跑完 42 例全绿，2026-11-14 本批记录）。算术在那种写法下是
        `1 - 1 == 0`：g 组是在**进函数之前**就塌掉的（本条先删了 g 的一行），所以两组形状
        里 `len(groups) == len(displayed)`；而 51 组形状里第 51 组原样留着，算术也是 1。
        ⇒ 现有形状分不出这两种写法（要分出来得让**已展示**的组在删除过程中活下来，
        单线程夹具做不到，需注入并发/失败）。保留实测写法是因为它对并发与半途中止更稳，
        不要因为本条绿着就以为算术版被挡住了。
        """
        self._pair('f.csv', 'f')
        self._pair('g.csv', 'g')
        self.assertEqual(len(_group_duplicates(self.user)), 2)
        DataFile.objects.filter(filename='g.csv').first().delete()  # g 组塌成 1 行
        deleted, remaining = self._delete()
        self.assertEqual(deleted, 1, 'f 组删一条')
        self.assertEqual(remaining, 0, '删完重算：g 组早就不是重复组了')


from rest_framework.test import APIClient  # noqa: E402  与下方 HTTP 契约类同段，见计划 Task 4

CHECK_URL = '/api/v1/consistency-check/'


class DeleteDuplicatesHttpContractTests(TestCase):
    """端点形状：keep_ids 上行、`invalid_keep_id` 下行、切片语义、以及 GET 没被改动。

    与 Task 3 的分工：Task 3 钉「函数删对谁」，本类钉「载荷形状与响应字段」。
    400 家族在这里重跑一遍**带 HTTP 状态码与 code 字段**的形状，是因为
    前端 toast 读的是 `{code, message}` 那层 —— 函数层的异常名对界面不可观察。
    """

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-dup-api-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('dup_api_a', 'da@localhost', 'x-pass-12345678')
        self.user.role = 'administrator'
        self.user.save()
        self.other = User.objects.create_user('dup_api_b', 'db@localhost', 'x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _pair(self, filename, owner=None, tag=None, size=10):
        owner = owner or self.user
        rows = []
        for letter in ('p', 'q'):
            directory = os.path.join(self.base, '%s%s' % (tag or filename[:-4], letter))
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, filename)
            with open(path, 'wb') as fh:
                fh.write(b'\0' * size)
            rows.append(DataFile.objects.create(
                owner=owner, filename=filename, file_path=path, file_size=size,
                format_type='CTA8290D',
            ))
        return rows

    def _post(self, extra=None):
        payload = {'action': 'delete_duplicates'}
        payload.update(extra or {})
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.post(CHECK_URL, payload, format='json')

    def _get(self):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.get(CHECK_URL)

    def test_不带keep_ids时响应仍是旧形状加一个新字段(self):
        self._pair('a.csv', tag='a')
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['action'], 'delete_duplicates')
        self.assertEqual(resp.data['deleted_count'], 1)
        self.assertEqual(resp.data['remaining_groups'], 0, '新字段必须在，且是实测值')

    def test_keep_ids不是数组时400(self):
        self._pair('b.csv', tag='b')
        resp = self._post({'keep_ids': 123})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'invalid_keep_id')
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 2)

    def test_五态非法keep_ids全部400且一行都没删(self):
        first, second = self._pair('c.csv', tag='c')
        stranger = self._pair('s.csv', owner=self.other, tag='s')
        lone = DataFile.objects.create(
            owner=self.user, filename='lone.csv', file_path=os.path.join(self.base, 'lone.csv'),
            file_size=999, format_type='CTA8290D',
        )
        bad_payloads = {
            '不存在的 id': [999999],
            '他人的 id': [stranger[0].id],
            '非重复文件的 id': [lone.id],
            '同组两枚': [first.id, second.id],
            '非整数': ['%d' % first.id],
        }
        for label, keep_ids in bad_payloads.items():
            resp = self._post({'keep_ids': keep_ids})
            self.assertEqual(resp.status_code, 400, label)
            self.assertEqual(resp.data['code'], 'invalid_keep_id', label)
            self.assertTrue(resp.data['message'], 'detail 必须带中文，前端才不用再加 ERROR_CODE_MAP 条目')
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 3,
                         '五条 400 之后：本用户 3 行（重复组 2 + lone 1）一行都没少')
        self.assertTrue(os.path.exists(first.file_path), '磁盘上也一行没动')

    def test_指定保留最新经端点也生效(self):
        first, second = self._pair('d.csv', tag='d')
        resp = self._post({'keep_ids': [second.id]})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 1)
        alive = DataFile.objects.filter(owner=self.user, filename='d.csv')
        self.assertEqual([r.id for r in alive], [second.id])

    def test_51组时只处理前50组第51组仍在(self):
        """本批语义反转的那一条。旧行为没有任何用例钉住（五例逐条核过），
        所以这里既是新契约也是「旧契约不许回来」的绊线。"""
        for i in range(1, 52):
            self._pair('dup%02d.csv' % i, tag='g%02d' % i)
        checked = self._get()
        self.assertEqual(checked.status_code, 200)
        self.assertEqual(checked.data['duplicate_group_count'], 51)
        self.assertEqual(len(checked.data['duplicate_groups']), DUPLICATE_DISPLAY_LIMIT,
                         'GET 的展示切片仍是 50，本批没动它')

        resp = self._post()
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 50, '前 50 组各删一条')
        self.assertEqual(resp.data['remaining_groups'], 1)
        tail = DataFile.objects.filter(owner=self.user, filename='dup51.csv')
        self.assertEqual(tail.count(), 2, '第 51 组一行都没被删（用户没见过它）')

        again = self._get()
        self.assertEqual(again.data['duplicate_group_count'], 1,
                         '重新检查后它就成了下一批的已展示组 —— 循环是有出口的')

    def test_切片外组的保留项被拒(self):
        for i in range(1, 52):
            self._pair('dup%02d.csv' % i, tag='h%02d' % i)
        tail = DataFile.objects.filter(owner=self.user, filename='dup51.csv').order_by('id')
        resp = self._post({'keep_ids': [tail[1].id]})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['code'], 'invalid_keep_id')
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 102)

    def test_非空keep_ids漏一组时400且一行都没删(self):
        """Fix 1 经 HTTP 的形状：前端 `resolveKeepIds` 恒送「每组一枚」，所以漏一组只在
        GET 与 POST 之间列表变过时出现 —— 那一刻用户手里的选择已经不作数了，
        必须 400 + 中文「请重新检查」，不能按默认删掉他没提过的那组。"""
        a1, a2 = self._pair('p1.csv', tag='p1')
        b1, b2 = self._pair('p2.csv', tag='p2')
        resp = self._post({'keep_ids': [a2.id]})
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertEqual(resp.data['code'], 'invalid_keep_id')
        self.assertIn('覆盖', resp.data['message'], '文案要指向「重新检查」，不是重试')
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 4, '四行一行不少')
        for row in (a1, a2, b1, b2):
            self.assertTrue(os.path.exists(row.file_path), '磁盘同样原样（b 组没被默认策略删光）')

    def test_空数组keep_ids经端点仍走legacy默认留最早(self):
        """`keep_ids: []` == 老客户端/脚本（§5.3 第 2 条）⇒ 200 且每组留 id 最小。

        反向覆盖闸门若写成「不区分空载荷」，本条与函数层那条同批红 ——
        向后兼容不是顺带绿出来的，是有两条靶子盯着的。
        """
        a1, a2 = self._pair('q1.csv', tag='q1')
        b1, b2 = self._pair('q2.csv', tag='q2')
        resp = self._post({'keep_ids': []})
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['deleted_count'], 2)
        self.assertEqual(resp.data['remaining_groups'], 0)
        alive = set(DataFile.objects.filter(owner=self.user).values_list('id', flat=True))
        self.assertEqual(alive, {a1.id, b1.id}, '两组都按历史默认留最早')
