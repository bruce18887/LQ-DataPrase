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
① `_resolve_keep_selection` 的白名单（Task 2）；② 真删的三种保留结果（Task 3）；
③ 经 HTTP 的响应形状、400 家族与 51 组切片（Task 4）。
"""

import os
import shutil
import tempfile

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
    """白名单：`keep_ids ⊆ 已展示切片的成员 id`，越界一律抛，且**抛在任何删除之前**。"""

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
