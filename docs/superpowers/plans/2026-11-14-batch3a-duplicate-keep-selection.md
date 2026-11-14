# 批3a · 重复项选保留 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让数据修复中心的重复文件卡「每组可选保留哪一份」，并把删除作用范围从「作用于全部」反转成「只作用于已展示的前 50 组」。

**Architecture:** 后端把重复文件的三件事（分组 / 保留解析 / 删除）从 `_helpers.py` 搬进新模块
`apps/datafiles/views/_duplicate_files.py`，`POST {action:'delete_duplicates'}` 收 `keep_ids` 并按
白名单校验（非法即 400，且一行都不删）；前端把卡片里的只读 tag 换成 radio 行 + 两颗策略按钮，
派生文案与选择逻辑全在 `utils/dupKeep.ts`（T2 钉），组件只做渲染。

**Tech Stack:** Django 5 + DRF（`error_response` 家族）、Vue 3 + Element Plus 2.14.0、
vitest（T2，node 环境、**不装 jsdom、不用 `@vue/test-utils`**）、Playwright（T3，`@p2 @data`）。

**规格来源：** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §5
（含 2026-11-14 按本计划探针写回的四条订正）。判据分层与门禁节奏看
`docs/reference/testing-gates.md`，本文件不重复。

---

## 0. 开工前必读的六条事实（都是现量，不是推测）

1. **行数闸**：`apps/datafiles/tests.py` = **1959 行**且冻在 `EXEMPT` 的 1959（`scripts/line-limit.mjs:36-42`）
   ⇒ 本批**一行都不许往它里加**，新 T1 另起文件。`apps/datafiles/views/_helpers.py` = **552/600**，
   本批要加的保留解析放不下 ⇒ Task 1 先做纯搬迁。判据：`npx vitest run test/unit/lineLimit.spec.ts`。
2. **调用点结构判据**：`test/backend/test_parse_cache_invariant_scan.py:87-93` 的 `EXPECTED_SITES`
   按**文件**钉 `evict_parse_cache_for_paths` 的调用点数与归属。搬迁会把它的一处调用点从
   `_helpers.py` 挪到新模块 ⇒ 登记表必须同步改，否则那条扫描先红（Task 1 Step 4）。
3. **探针实测**（`tasks/probe_b3a_dup_shapes.py`，只读、不写库、不发 HTTP，2026-11-14）：
   - 本机 `admin` 有 **73 组**重复、每组恰好 2 个文件、`DataFile` 总行数 185；
   - 组内 distinct `file_size` 全是 **1** ⇒「体积最大」策略不可能有区分度（设计稿已作废那颗）；
   - 组内 distinct `created_at` 全是 **2** ⇒「最早 / 最新导入」真有区分度（样本差两个月）；
   - `_group_duplicates` 两次调用逐字相同 ⇒ 排序是全序，**GET 的切片与 POST 的切片必然同一批**；
   - 73 > 50 ⇒「只删已展示的组」在这台机器上是**每次都会走到**的路径，不是假想边界。
4. **`el-radio` 在 EP 2.14 用 `value` 不是 `label`**（仓内先例 `pages/auth/ConnectPage.vue:24`，
   且它就在 `<el-radio>` 上挂了 `data-test`）。
5. **单文件 e2e 走池，不走裸 playwright**：`node scripts/e2e_pool.mjs --slots=1 -- e2e/data/repair-center.spec.ts`
   （`testing-gates.md` §5：那是小集合的唯一入口；裸跑会自己抢 8000/3000 端口）。
6. **新的 `frontend/src/utils/dupKeep.ts` 会命中全局清单**（`affected-rules.mjs:182` 那条目录级
   `frontend/src/utils/` → GLOBAL）⇒ `npm run test:e2e:affected` 会升全量池。**不给它开放行规则**
   （它的行为最终由浏览器承载，放行等于削门禁）。批内只在 Task 8、Task 9 各跑一次 affected，
   收口档（全量池 + 后端全套）只在 Task 10 跑。

## 1. 文件地图

| 文件 | 责任 | 动作 |
|---|---|---|
| `apps/datafiles/views/_duplicate_files.py` | 重复文件的**唯一口径**：分组、保留解析、删除、切片同源 | 新建（Task 1 搬入 + Task 2/3 新增） |
| `apps/datafiles/views/_helpers.py` | 其它视图私有助手 | 只减不增（Task 1 搬走 3 个函数） |
| `apps/datafiles/views/browse_views.py` | 一致性检查 GET/POST | 改 import、改 `delete_duplicates` 分支、订正 post docstring |
| `test/backend/test_parse_cache_invariant_scan.py` | 调用点结构判据 | `EXPECTED_SITES` 同步 |
| `test/backend/test_duplicate_keep_selection.py` | 本批 T1 契约 | 新建 |
| `frontend/src/utils/dupKeep.ts` | 选择状态、策略、汇总与全部文案（纯函数） | 新建 |
| `frontend/test/unit/dupKeep.spec.ts` | 上面那份的 T2 | 新建 |
| `frontend/src/pages/data/components/DuplicateFilesCard.vue` | 卡片渲染 + 交互 | 重写 tag 行为 radio |
| `frontend/src/pages/data/components/ConsistencyCheckDialog.vue` | keep_ids 上行、remaining_groups 下行 | 改两处 |
| `frontend/src/api/datafiles.ts` | 请求体与响应类型 | 改两处 |
| `frontend/test/unit/dupKeepWiring.spec.ts` | 源侧接线绊线（装配层自有判据） | 新建 |
| `frontend/e2e/data/repair-center.spec.ts` | 本批 T3 | 改造那条 + 新增一条 |
| `docs/intro/.vitepress/theme/components/FileListMock.vue`、`theme/data.ts` | 介绍书复刻与文案 | 各改一行 |

不动的：`apps/datafiles/tests.py`（向后兼容证据所在，逐字不动）、`_helpers.py` 里
`_delete_datafile_file_only` 与 `_user_upload_dir`（后者是批4 FIX-2 的靶子，本批不碰）。

---

## Task 1: 后端纯搬迁（无行为变化）+ 结构判据同步

**Files:**
- Create: `apps/datafiles/views/_duplicate_files.py`
- Modify: `apps/datafiles/views/_helpers.py`（删 300-369 行那一块）
- Modify: `apps/datafiles/views/browse_views.py:38-45`
- Modify: `test/backend/test_parse_cache_invariant_scan.py:87-93`

- [ ] **Step 1: 先取基线（搬迁前后要逐字对得上）**

```bash
cd frontend && npx vitest run test/unit/lineLimit.spec.ts 2>&1
cd .. && .venv/Scripts/python.exe -X utf8 manage.py test \
  test.backend.test_parse_cache_scoped_invalidation test.backend.test_parse_cache_invariant_scan 2>&1
```
把两份输出的 `Tests 15 passed` / `Ran N tests ... OK` 记进 `tasks/b3a_task1_baseline.txt`（gitignore 区内）。
⚠ 判绿取末尾 `OK` / `Tests N passed` 行，**不取 `$?`**。
⚠ 本步原写的 label `test.backend.apps_datafiles_deletion` **不存在**（实测 `ModuleNotFoundError`
+ `FAILED (errors=1)`，Task 1 复审核过）⇒ 已从两处命令里删掉。别为它改用例，更别把它读成回归。

- [ ] **Step 2: 新建模块并搬入三个函数（逐字搬，不改一行逻辑）**

创建 `apps/datafiles/views/_duplicate_files.py`：

```python
"""重复文件的分组、保留选择与删除（批3a · 第 3 项）。

从 ``_helpers.py`` 搬出来的理由是**行数闸**，不是口味：那份 552/600（判据
``scripts/line-limit.mjs``，无豁免），而本模块要加的「keep_ids 白名单校验」带注释放不下。
搬动本身不改一行语义；``test_parse_cache_invariant_scan.py`` 按文件钉
``evict_parse_cache_for_paths`` 的调用点归属，所以那份登记表跟着搬（见那个 Task）。

三条口径只在这里写一次，视图与前端都只引用它：

1. **分组** = ``(filename, file_size)`` 精确相等 + ``owner=user``。后者是越权防线，
   不是冗余条件（``_group_duplicates`` 的 docstring 与 :355 原注释同义）。
2. **展示切片 == 处理切片**：GET 与 POST 都取 ``_group_duplicates(user)[:50]``。
   ``groups.sort`` 的键就是分组键本身 ⇒ 全序，两边切到的必然是同一批 50 组。
   这是「只删已展示的组」的**实现**，不靠两个 limit 常数互相对齐 —— 对齐写法总有一天会漂。
3. **每组恰一枚保留 id**；未指定 = 该组 id 最小（``files`` 按 id 升序，见下面
   ``_group_duplicates`` 里的 ``order_by('id')``），即历史行为。
"""

from django.db import transaction

from apps.datafiles.models import DataFile
from apps.datafiles.services import evict_parse_cache_for_paths

from ._helpers import _delete_datafile_file_only

# GET 的展示切片与 POST 的处理切片共用这一个常数（口径 2）。
DUPLICATE_DISPLAY_LIMIT = 50


def _group_duplicates(user):
    """Group the user's files by exact (filename, file_size) match.

    Returns a list of groups, each ``{'filename', 'file_size', 'files': [...]}``
    where ``files`` is ordered by id ascending (the first entry is the
    canonical file kept when duplicates are cleaned). Groups with fewer than
    two files are dropped. Works across single and batch files.
    """
    grouped = {}
    rows = DataFile.objects.filter(owner=user).order_by('id').values(
        'id', 'filename', 'file_size', 'file_type', 'batch_name', 'sub_batch',
        'created_at',
    )
    for r in rows:
        key = (r['filename'], r['file_size'])
        group = grouped.setdefault(key, {
            'filename': r['filename'],
            'file_size': r['file_size'],
            'files': [],
        })
        group['files'].append({
            'id': r['id'],
            'filename': r['filename'],
            'file_size': r['file_size'],
            'file_type': r['file_type'],
            'batch_name': r['batch_name'] or '',
            'sub_batch': r['sub_batch'] or '',
            'created_at': r['created_at'].isoformat() if r['created_at'] else '',
        })
    groups = [g for g in grouped.values() if len(g['files']) >= 2]
    groups.sort(key=lambda g: (g['filename'].lower(), g['file_size']))
    return groups


def _find_duplicate_groups(user, limit=DUPLICATE_DISPLAY_LIMIT):
    """Duplicate groups for the repair center: ``(groups, total_group_count)``.

    ``groups`` is capped at ``limit`` for display; the count reflects all.
    """
    groups = _group_duplicates(user)
    return groups[:limit], len(groups)


def _delete_duplicate_files(user):
    """Delete duplicate files (same filename+size), keeping the lowest id per
    group (the earliest registered). Returns the number of deleted rows.

    Per-file transaction so a mid-way failure never rolls back completed
    deletions; the action is idempotent. Only the duplicate file is removed —
    an existing batch directory and its remaining files are untouched.
    """
    deleted_count = 0
    deleted_paths = []
    groups = _group_duplicates(user)
    # 一次取回全部待删行：曾是「每个重复文件一次 SELECT」，几十组重复时就是几十次
    # 往返。owner=user 与 _group_duplicates 同源，是越权防线，不是冗余条件。
    pending = [item['id'] for group in groups for item in group['files'][1:]]
    rows = DataFile.objects.filter(owner=user, pk__in=pending).in_bulk()
    for group in groups:
        for item in group['files'][1:]:
            df = rows.get(item['id'])
            if df is None:
                continue
            with transaction.atomic():
                unlinked = _delete_datafile_file_only(df)
                df.delete()
            deleted_paths.append(unlinked)
            deleted_count += 1
    evict_parse_cache_for_paths(deleted_paths)
    return deleted_count
```

- [ ] **Step 3: 从 `_helpers.py` 删掉那三个函数**

删除 `apps/datafiles/views/_helpers.py` 的 300-369 行（`_group_duplicates` /
`_find_duplicate_groups` / `_delete_duplicate_files` 三个 def 与其间空行）。
`_helpers.py` 里 `transaction`、`evict_parse_cache_for_paths`、`DataFile` 都还有别的消费者
（`_delete_datafile_file_only` 等），**import 行不动**。

- [ ] **Step 4: 改引用与结构判据**

`browse_views.py:38-45` 的 import 拆成两条：

```python
from ._helpers import (
    _register_file,
    _resolve_product_code,
    _scan_orphaned_disk,
    _user_upload_dir,
)
from ._duplicate_files import (
    _find_duplicate_groups,
    _delete_duplicate_files,
)
```

`test/backend/test_parse_cache_invariant_scan.py:87-93` 的 `EXPECTED_SITES` 把那一条改名：

```python
    EXPECTED_SITES = {
        'apps/datafiles/views/_duplicate_files.py': 1,  # _delete_duplicate_files
        'apps/datafiles/views/file_views.py': 4,     # destroy / bulk_delete / combine / uncombine
        'apps/datafiles/views/browse_views.py': 1,   # _delete_orphaned_db
        'apps/datafiles/views/batch_views.py': 2,    # 批次目录 / 子批目录
    }
```
（`TOTAL = 8` 不动 —— 调用点总数没变，只是换了归属文件。）

- [ ] **Step 5: 跑基线三档，必须与 Step 1 逐字相同**

```bash
cd frontend && npx vitest run test/unit/lineLimit.spec.ts 2>&1
cd .. && .venv/Scripts/python.exe -X utf8 manage.py test \
  test.backend.test_parse_cache_scoped_invalidation test.backend.test_parse_cache_invariant_scan 2>&1
.venv/Scripts/python.exe -X utf8 manage.py test apps.datafiles 2>&1
```
Expected: 前两条与 Step 1 输出一致；第三条 `OK`（既有重复文件那五条用例是本步的承重判据，
它们**不许被改动**）。行数**落地实测**（`b736237`）：`_helpers.py` 552→**480**、新模块 **99**、
`browse_views.py` 495→497，都 < 600。本步原写 482/103 是计划自己算错的估计值，已按实数订正；
删块时把其后 2 个分隔空行一并带走才对（留下就是 4 连空行）。

- [ ] **Step 6: 提交**

```bash
git add apps/datafiles/views/_duplicate_files.py apps/datafiles/views/_helpers.py \
        apps/datafiles/views/browse_views.py test/backend/test_parse_cache_invariant_scan.py
git commit -m "refactor(datafiles): 重复文件三函数搬出 _helpers（600 行闸留位），调用点登记表同步"
```

---

## Task 2: 保留项白名单校验（纯函数层，T1 直调）

**Files:**
- Modify: `apps/datafiles/views/_duplicate_files.py`
- Test: `test/backend/test_duplicate_keep_selection.py`

- [ ] **Step 1: 写失败测试（只测解析函数，不经 HTTP）**

创建 `test/backend/test_duplicate_keep_selection.py`：

```python
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
```

- [ ] **Step 2: 跑到失败**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
```
Expected: `ImportError: cannot import name 'InvalidKeepSelection'`（收集期就错）。
**实测原文**（2026-11-14 落地）：`Found 1 test(s) ... Ran 1 test in 0.000s / FAILED (errors=1)` ——
不是 `Ran 0 tests`：unittest loader 把收集期的 ImportError 包成一条合成的 `_FailedTest`，
所以计数记 1。本处原写 `Ran 0 tests` 是计划自己的事实错，已订正。
**这一条必须真红过**才往下写实现。

- [ ] **Step 3: 实现 `_resolve_keep_selection`**

在 `_duplicate_files.py` 的 `DUPLICATE_DISPLAY_LIMIT` 之后、`_group_duplicates` 之前插入：

```python
class InvalidKeepSelection(ValueError):
    """`keep_ids` 与本次可处理的重复组对不上（四态之一，见 `_resolve_keep_selection`）。

    继承 `ValueError` 只为让视图一句 `except` 就能翻成 400，不必再往 `browse_views`
    引一个新异常名。
    """


def _group_key(group):
    """分组键本身（`(filename, file_size)`，全库唯一 ⇒ 可当 dict 键）。"""
    return (group['filename'], group['file_size'])


def _resolve_keep_selection(groups, keep_ids, limit=DUPLICATE_DISPLAY_LIMIT):
    """把 `keep_ids` 落成「每组一枚保留 id」，返回 ``(displayed, keep_by_key)``。

    判据是**白名单**：每一枚 id 必须出现在已展示切片（前 ``limit`` 组）的成员里。
    四态越界即抛，且抛在任何删除动作之前 —— 顺序就是「一行都不许删」那句的实现：

    * 不存在的 id / 他人的文件 / 非重复文件：压根进不了 ``allowed``；
    * **切片之外的组**：用户以为改了它，服务端根本不碰。静默接受等于按默认
      删掉用户以为改选过的那份，正是本项要修的缺陷的变体；
    * 同一组两枚：radio 的不变量是「一组恰一枚」，出现两枚说明载荷与界面状态不一致，
      此时删谁都是替用户决定。

    非整数（含 `bool`：`isinstance(True, int)` 在 Python 里是真的，不挡就会拿 `True`
    当 id 1 去查表）同样拒 —— 这是 HTTP 入口，不是内部调用。
    """
    displayed = groups[:limit]
    allowed = {}
    for group in displayed:
        for item in group['files']:
            allowed[item['id']] = _group_key(group)
    keep_by_key = {}
    for raw in keep_ids:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise InvalidKeepSelection('keep_ids 必须是整数数组')
        key = allowed.get(raw)
        if key is None:
            raise InvalidKeepSelection('保留项不属于本次可处理的重复组（已失效或不在本批 50 组内）')
        if key in keep_by_key:
            raise InvalidKeepSelection('同一组只能有一枚保留项')
        keep_by_key[key] = raw
    return displayed, keep_by_key
```

- [ ] **Step 4: 跑到全绿**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
```
Expected: `Ran 8 tests ... OK`（落地实测原文）。

- [ ] **Step 5: 变异反证（每条判据都要咬得住）**

```bash
# M1：把「切片外的 id 也放行」——allowed 换成全量 groups
# M2：删掉同组两枚那条 raise
# M3：把 isinstance(raw, bool) 那道判断去掉
```
逐个手工改、跑、改回（**禁 `git checkout --` / `git restore`**，改回用 Edit 反着写）。
Expected: M1 → `test_未进入切片的组的id被拒` 红；M2 → `test_同组两枚被拒` 红；
M3 → **第一版跑成了全绿**（本批第一次「反证没咬住」，落地实测）。根因不是变异等价，而是
fixture 的 id 空间 `10/11/20/21/22` 不含 `1`，而 `hash(True) == hash(1)` ⇒ 删掉 bool 闸门后
`[True]` 改由白名单那条抛出，异常类型撞对、用例照绿 —— **只断异常类型时，两条重叠防线互相掩盖**。
处置：把那条用例拆成 `test_非整数被拒` + `test_布尔被拒且拒在类型闸门`（后者用
`assertRaisesRegex(..., '整数数组')` 钉**是哪道闸门生效**），拆完重跑 M3 → `FAILED (failures=1)`
且只红新那条（已实测）。三个变异各记一行结果到台账。

- [ ] **Step 6: 提交**

```bash
git add apps/datafiles/views/_duplicate_files.py test/backend/test_duplicate_keep_selection.py
git commit -m "feat(datafiles): keep_ids 白名单校验（切片外/同组两枚/非整数一律拒）+ T1"
```

---

## Task 3: 删除侧按保留选择执行 + `remaining_groups` 实测

> **落地订正（2026-11-14，`6e2d664`）**：Task 3 与 Task 4 **合成一批实现、一笔提交**。
> 分开写会留下一笔必然红的中间提交 —— Task 3 把返回值改成元组之后、Task 4 接线之前，
> `browse_views.py` 仍把元组当整数塞进 `deleted_count`，`apps.datafiles` 那五条重复文件用例
> 当场红（实测形状 `AssertionError: (1, 0) != 1`）。「每一笔提交都全绿」优先于「按计划一步一提交」。
> 下面两个 Task 的正文照原样读，只是提交合成一笔。

**Files:**
- Modify: `apps/datafiles/views/_duplicate_files.py:50-103`
- Test: `test/backend/test_duplicate_keep_selection.py`

- [ ] **Step 1: 写失败测试（追加一个 TestCase 类）**

在同文件末尾追加：

```python
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

    def test_每组files按id升序_前端默认保留项直接取首条的前提(self):
        # ⚠ 落地订正：原计划这条用例名里带全角括号 `（…）`，实测 SyntaxError
        # （全角括号不是合法标识符字符）。中文标识符本身合法，括号不合法 ⇒ 换成下划线。
        """前端 `defaultKeepId` 取的是 `files[0].id`，`strategyKeepId` 的并列裁决也落在首条。

        两边都不重排序 —— 所以「后端给的 files 是 id 升序」这条契约一旦变，前端两处会
        一起静默选错，而 TS 与 e2e 都不会报（形状完全一样，错的只是哪一条在前）。
        """
        first, second = self._pair('h.csv', 'h')
        groups = _group_duplicates(self.user)
        self.assertEqual(len(groups), 1)
        ids = [f['id'] for f in groups[0]['files']]
        self.assertEqual(ids, sorted(ids), 'files 必须 id 升序')
        self.assertEqual(ids, [first.id, second.id])

    def test_remaining_groups是删完重算的实测值(self):
        """两组、只处理其中一枚保留项 ⇒ 剩 0；若写 `总数-已处理` 的算术，
        「某行已不在 DB 所以那组当场塌掉」那种形状会报成非 0 的假数。"""
        self._pair('f.csv', 'f')
        self._pair('g.csv', 'g')
        self.assertEqual(len(_group_duplicates(self.user)), 2)
        DataFile.objects.filter(filename='g.csv').first().delete()  # g 组塌成 1 行
        deleted, remaining = self._delete()
        self.assertEqual(deleted, 1, 'f 组删一条')
        self.assertEqual(remaining, 0, '删完重算：g 组早就不是重复组了')
```

- [ ] **Step 2: 跑到失败**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
```
Expected: 新增 6 条里 **5 条红**，形状是 `TypeError: _delete_duplicate_files() takes 1 positional argument`；
`test_每组files按id升序` 这一条**一开始就是绿的** —— 它钉的是后端既有契约（前端两处都依赖它），
不是本批新增行为，所以没有「先红」这一步可期待。把它写成红会是在造假 TDD。

- [ ] **Step 3: 改写 `_delete_duplicate_files`**

把 Task 1 搬进来的那个 def 整个换成：

```python
def _delete_duplicate_files(user, keep_ids=()):
    """按保留选择删除重复文件，返回 ``(deleted_count, remaining_groups)``。

    * ``keep_ids`` 为空 ⇒ 每组留 id 最小（== 搬迁前的历史行为，向后兼容由
      ``apps/datafiles/tests.py:1255`` 与本文件的默认例共同钉住）；
    * 校验先于删除（`_resolve_keep_selection` 抛出来时一行都没动）；
    * 逐文件 ``transaction.atomic()`` 照旧：中途失败不回滚已删的，动作幂等；
    * **只处理已展示切片**（口径 2）—— 第 51 组之后的东西用户根本没看见，
      不该替他删（设计 §5.4 的语义反转，2026-11-14 用户拍板）。

    ``remaining_groups`` 是删完再跑一遍 `_group_duplicates` 的**实测**长度，不是
    ``总数 - len(displayed)`` 的算术：某行已不在 DB 时那组当场塌掉，算术会虚报。
    """
    groups = _group_duplicates(user)
    displayed, keep_by_key = _resolve_keep_selection(groups, keep_ids)
    pending = []
    for group in displayed:
        keep = keep_by_key.get(_group_key(group), group['files'][0]['id'])
        pending.extend(item['id'] for item in group['files'] if item['id'] != keep)
    deleted_count = 0
    deleted_paths = []
    # 一次取回全部待删行（批2 之前的写法是每个重复文件一次 SELECT）。
    # owner=user 与 _group_duplicates 同源，是越权防线，不是冗余条件。
    rows = DataFile.objects.filter(owner=user, pk__in=pending).in_bulk()
    for group in displayed:
        keep = keep_by_key.get(_group_key(group), group['files'][0]['id'])
        for item in group['files']:
            if item['id'] == keep:
                continue
            df = rows.get(item['id'])
            if df is None:
                continue
            with transaction.atomic():
                unlinked = _delete_datafile_file_only(df)
                df.delete()
            deleted_paths.append(unlinked)
            deleted_count += 1
    evict_parse_cache_for_paths(deleted_paths)
    return deleted_count, len(_group_duplicates(user))
```

- [ ] **Step 4: 跑到全绿**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
.venv/Scripts/python.exe -X utf8 manage.py test apps.datafiles 2>&1
```
Expected: 新增类全绿；`apps.datafiles` 仍 `OK` ⇒ **默认分支的向后兼容没被改坏**。
⚠ 若 `apps/datafiles` 里 `test_delete_duplicates_keeps_earliest` 红，一定是 Step 3 的默认回落写错了
（`group['files'][0]['id']` 不是 `group['files'][1]` 那种切片写法），改实现而不是改用例。

- [ ] **Step 5: 变异反证**

* M4：把默认回落从 `group['files'][0]['id']` 换成 `group['files'][-1]['id']` ⇒
  `test_不带keep_ids时保留最早…` 与 `apps.datafiles` 那条**同时**红（后者是既有承重判据，红了就说明变异被接住）。
* M5：把 `remaining_groups` 换成 `len(groups) - len(displayed)` ⇒ **实测全绿（判据洞，计划预测错）**。
  计划原话「算术在塌组形状下报 1 而非 0」算错了：那条用例里 g 组是在**进函数之前**就塌的，
  于是 `len(groups) == len(displayed) == 1`，算术也得 0；51 组形状下两种写法同样恒等。
  根因是结构性的：**每个已展示组跑完必塌成 1 行**（每组删掉 `len-1` 条），所以
  「实测剩余组数」与「总数 − 已处理数」在当下所有可达形状里相等，任何不注入失败的夹具都分不开它们。
  ⇒ 处置：代码保持实测（它不依赖那个前提），docstring 与用例说明改成实话；这条记进 lessons
  （判据抓不到的第二种原因：两种写法在可达状态空间上恒等，不是等价变异而是**无可观察差异的边界**）。
* M6：把校验挪到删除循环之后（先删再校验）⇒ `test_校验失败时一行都不删` 红。

- [ ] **Step 6: 提交**

```bash
git add apps/datafiles/views/_duplicate_files.py test/backend/test_duplicate_keep_selection.py
git commit -m "feat(datafiles): 重复文件按 keep_ids 删除，remaining_groups 取删后实测"
```

---

## Task 4: 视图接线 + 400 家族与 51 组切片的 HTTP 契约

**Files:**
- Modify: `apps/datafiles/views/browse_views.py:38-45,336-363`
- Test: `test/backend/test_duplicate_keep_selection.py`

- [ ] **Step 1: 写失败测试（HTTP 段）**

追加：

```python
from rest_framework.test import APIClient

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
```

- [ ] **Step 2: 跑到失败**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
```
Expected: HTTP 类里 `KeyError: 'remaining_groups'` / `400 != 200` 等（视图还在调一参数版函数）。

- [ ] **Step 3: 改 `browse_views.py`**

import 段加上新名字（Task 1 拆出来的那条）：

```python
from ._duplicate_files import (
    _find_duplicate_groups,
    _delete_duplicate_files,
    InvalidKeepSelection,
)
```

`post()` 的 docstring（:337-338 那句现在**是假的**，必须订正）：

```python
    def post(self, request):
        """Fix consistency issues.

        ``delete_orphaned_db`` / ``delete_orphaned_disk`` / ``import_orphaned_disk``
        / ``fix_product_codes`` still recompute the full affected set server-side.

        ``delete_duplicates`` deliberately does **not**: it acts on the same first
        ``DUPLICATE_DISPLAY_LIMIT`` groups the GET handed to the UI, because a file
        the user never saw is a file they cannot be asked to consent about
        (spec §5.4, 2026-11-14 用户拍板「只删已展示的组」). Both sides read the
        slice out of one function, so no constant pair can drift apart.
        """
```

分支替换（原 :355-360）：

```python
        elif action == 'delete_duplicates':
            keep_ids = request.data.get('keep_ids') or []
            if not isinstance(keep_ids, list):
                # 数组形状在这里挡：进 `_resolve_keep_selection` 之前它是别的类型，
                # 里面只逐条判元素，不判容器。
                return error_response('invalid_keep_id', 'keep_ids 必须是数组')
            try:
                deleted_count, remaining_groups = _delete_duplicate_files(user, keep_ids)
            except InvalidKeepSelection as exc:
                # detail 是中文 ⇒ apps/common/errors.py:29 会把它复制进 message，
                # 前端 pickMessage 优先读 message，所以不需要给 ERROR_CODE_MAP 加条目
                # （先例见 test/backend/test_login_throttle.py:68）。
                return error_response('invalid_keep_id', str(exc))
            return Response({
                'status': 'ok',
                'action': action,
                'deleted_count': deleted_count,
                'remaining_groups': remaining_groups,
            })
```

- [ ] **Step 4: 跑到全绿**

```bash
.venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_duplicate_keep_selection 2>&1
.venv/Scripts/python.exe -X utf8 manage.py test test.backend apps.datafiles 2>&1
```
Expected: 本文件全绿（**落地实测 20 例**：Task 2 拆完 bool 闸门那条是 8 + Task 3 的 6 + Task 4 的 6）；`test.backend apps.datafiles` `OK`
（⚠ 这一档**不是**后端全量，实测约 1988 例，别写成「全量」）。

- [ ] **Step 5: 变异反证**

* M7：把 `keep_ids = request.data.get('keep_ids') or []` 改成整个传 `request.data.get('keep_ids')`
  （即 `None` 直接进函数）⇒ `for raw in None` 抛 `TypeError` ⇒ 500，HTTP 类红。
* M8：把 `except InvalidKeepSelection` 换成 `except ValueError` ⇒ 本类仍全绿（它是子类），
  **但** `test_keep_ids不是数组时400` 里的 `isinstance` 那道挡不住时也一样红 —— 记录这个
  「等价变异」为**已知不可区分**，别声称这条判据抓得住它（判据可达性纪律）。
* M9：把 POST 的切片改回全量（`_delete_duplicate_files` 里 `displayed = groups`）⇒
  `test_51组时只处理前50组第51组仍在` 与 `test_切片外组的保留项被拒` 双红。

- [ ] **Step 6: 提交**

```bash
git add apps/datafiles/views/browse_views.py test/backend/test_duplicate_keep_selection.py
git commit -m "feat(api): delete_duplicates 收 keep_ids、越界 400 不删、响应带 remaining_groups"
```

---

## Task 5: `utils/dupKeep.ts` + T2

**Files:**
- Create: `frontend/src/utils/dupKeep.ts`
- Test: `frontend/test/unit/dupKeep.spec.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/test/unit/dupKeep.spec.ts`（期望值一律写**字面量**，不重跑同一段代码）：

```ts
/**
 * T2：重复项保留选择的纯函数层（批3a · 第 3 项）。
 *
 * 跑：cd frontend && npx vitest run test/unit/dupKeep.spec.ts
 *
 * 判据异源：所有期望值都是手写字面量（组数、字节数、id、整句文案）。
 * 拿实现去算期望值等于让同一段代码给自己盖章 —— 档/取整/键拼法错了会一起错。
 *
 * 组件层不在这里：卡片渲染由 T3（repair-center.spec.ts）钉，接线形状由
 * dupKeepWiring.spec.ts 的源侧绊线钉。本层不起组件（本仓无 jsdom）。
 */
import { describe, expect, it } from 'vitest'
import {
  STRATEGY_LABELS,
  applyStrategyToUntouched,
  deleteSummary,
  deleteSummaryText,
  groupKey,
  keepIdForGroup,
  resolveKeepIds,
  remainingGroupsNote,
  strategyKeepId,
  truncatedNoteText,
  dupImportText,
} from '../../src/utils/dupKeep'
import type { DuplicateGroup } from '../../src/api/datafiles'

function files(...pairs: Array<[number, string, number?]>) {
  // [id, created_at, file_size?] —— file_size 默认 500，与所属组一致（分组键含它）
  return pairs.map(([id, created_at, file_size]) => ({
    id,
    filename: 'x.csv',
    file_size: file_size ?? 500,
    file_type: 'single' as const,
    batch_name: '',
    sub_batch: '',
    created_at,
  }))
}

function group(filename: string, members: ReturnType<typeof files>, size = 500): DuplicateGroup {
  return { filename, file_size: size, files: members }
}

describe('groupKey', () => {
  it('同名同大小同组，任一维不同就换组', () => {
    expect(groupKey(group('a.csv', files([1, 't'])))).toBe('a.csv|500')
    expect(groupKey(group('a.csv', files([1, 't']), 600))).toBe('a.csv|600')
    expect(groupKey(group('A.CSV', files([1, 't'])))).toBe('A.CSV|500')
    expect(groupKey(group('a.csv', files([1, 't'])))).toBe(groupKey(group('a.csv', files([2, 't']))))
    expect(groupKey(group('a.csv', files([1, 't'])))).not.toBe(groupKey(group('b.csv', files([1, 't']))))
  })
  it('文件名里带竖线也不与别的组撞键', () => {
    // 'a|500' 大小 1000 与 'a' 大小 5001000… 之类的拼法歧义：右段恒为数字，
    // 想撞必须让左段吃掉一个 '|' 后右段仍是同一个数 —— 构造不出来，钉两条实测值。
    expect(groupKey(group('a|500', files([1, 't']), 1000))).toBe('a|500|1000')
    expect(groupKey(group('a', files([1, 't']), 500))).toBe('a|500')
    expect(groupKey(group('a|500', files([1, 't']), 1000))).not.toBe(groupKey(group('a', files([1, 't']), 500)))
  })
})

describe('保留项裁决', () => {
  const g = group('a.csv', files([10, '2026-01-02T00:00:00+00:00', 11, '2026-01-01T00:00:00+00:00']))
  it('未改选时用默认保留项 = files[0] = id 最小', () => {
    expect(keepIdForGroup(g, new Map())).toBe(10)
  })
  it('改选过的组用改选值', () => {
    expect(keepIdForGroup(g, new Map([['a.csv|500', 11]]))).toBe(11)
  })
  it('策略「最早/最新」比 created_at，与 id 大小无关', () => {
    // 两条是「后端会给的样子」：id 升序，但时间与 id 倒挂（id 大的那条反而更早导入）
    expect(strategyKeepId(g, 'earliest')).toBe(11)
    expect(strategyKeepId(g, 'latest')).toBe(10)
  })
  it('created_at 相同时裁决落在 id 最小（靠 files 已升序，不靠额外比 id）', () => {
    const same = '2026-01-01T00:00:00+00:00'
    const tie = group('t.csv', files([29, same, 30, same]))
    expect(strategyKeepId(tie, 'earliest')).toBe(29)
    expect(strategyKeepId(tie, 'latest')).toBe(29)
    expect(keepIdForGroup(tie, new Map())).toBe(29)
    // 反向探针：数组顺序反过来就不是这个形状了（Task 3 有一条 T1 钉后端不会给这种输入）
    const flipped = group('t.csv', files([30, same, 29, same]))
    expect(strategyKeepId(flipped, 'earliest')).toBe(30)
  })
  it('只有两颗策略：体积最大是谎话控件，已作废', () => {
    // 重复判定口径是 (filename, file_size) 精确相等 ⇒ 组内 file_size 恒等（实测 73/73 组），
    // 「体积最大」在数学上永远等于「按 id 最小」。谁加回来这条就红。
    expect(Object.keys(STRATEGY_LABELS).sort()).toEqual(['earliest', 'latest'])
  })
})

describe('applyStrategyToUntouched', () => {
  const a = group('a.csv', files([10, '2026-01-01T00:00:00+00:00', 11, '2026-01-02T00:00:00+00:00']))
  const b = group('b.csv', files([20, '2026-01-01T00:00:00+00:00', 21, '2026-01-02T00:00:00+00:00']))
  it('只覆盖未改选的组，改选过的原样保留', () => {
    const before = new Map<string, number>([['b.csv|500', 20]])
    const after = applyStrategyToUntouched([a, b], before, 'latest')
    expect(after.get('a.csv|500')).toBe(11)
    expect(after.get('b.csv|500')).toBe(20, '用户手选过的那组不许被一键策略覆盖')
    expect(before.get('a.csv|500'), '原 Map 必须不被就地改').toBeUndefined()
  })
})

describe('resolveKeepIds', () => {
  it('每组一枚、按 groups 顺序、含未改选的默认值', () => {
    const a = group('a.csv', files([10, 't1', 11, 't2']))
    const b = group('b.csv', files([21, 't1', 20, 't2']))
    expect(resolveKeepIds([a, b], new Map([['b.csv|500', 20]]))).toEqual([10, 20])
    expect(resolveKeepIds([a, b], new Map())).toEqual([10, 21])
    expect(resolveKeepIds([], new Map())).toEqual([])
  })
})

describe('汇总与文案', () => {
  const g2 = group('a.csv', files([1, 't', 2, 't']), 500)
  const g3 = group('b.csv', files([3, 't', 4, 't', 5, 't']), 1024)
  it('deleteSummary 只数已展示组：每组删 (len-1) 个', () => {
    expect(deleteSummary([g2, g3])).toEqual({ count: 3, bytes: 500 + 2 * 1024 })
  })
  it('按钮文案把数字来自当前选择，不写死「全部」', () => {
    expect(deleteSummaryText([g2, g3])).toBe('按选择删除 3 个（2.5 KB）')
    expect(deleteSummaryText([g2])).toBe('按选择删除 1 个（500 B）')
  })
  it('truncatedNote：超过切片才说话，且说的是本批处理多少', () => {
    expect(truncatedNoteText(73, 50)).toBe(
      '共 73 组重复，本批处理前 50 组，另有 23 组未处理 —— 重新检查后可继续。',
    )
    expect(truncatedNoteText(50, 50)).toBe('')
    expect(truncatedNoteText(1, 1)).toBe('')
  })
  it('旧的「删除操作将作用于全部」这句必须消失', () => {
    expect(truncatedNoteText(73, 50)).not.toMatch(/作用于全部|仅显示/)
  })
  it('remainingGroupsNote：0 组不啰嗦', () => {
    expect(remainingGroupsNote(0)).toBe('')
    expect(remainingGroupsNote(23)).toBe('，另有 23 组未处理')
  })
  it('dupImportText 带年份（跨月的两份要分得出先后，短形态会跨年读错）', () => {
    expect(dupImportText('2026-08-10T14:09:42.332806+00:00')).toMatch(/2026/)
    expect(dupImportText('2026-08-10T14:09:42.332806+00:00')).not.toMatch(/[上下]午/)
    expect(dupImportText('')).toBe('--')
    expect(dupImportText('not-a-date')).toBe('--')
  })
})
```

- [ ] **Step 2: 跑到失败**

```bash
cd frontend && npx vitest run test/unit/dupKeep.spec.ts 2>&1
```
Expected: `Failed to load ... dupKeep` 之类（文件还不存在），**不是**断言红。

- [ ] **Step 3: 实现**

创建 `frontend/src/utils/dupKeep.ts`：

```ts
/**
 * 重复项保留选择的全部派生逻辑与文案（批3a · 第 3 项）。
 *
 * 与批2 的 `utils/diskUsage.ts` 同一条分工理由：会被用户读成**承诺**的句子
 * （「本批处理前 50 组」「按选择删除 3 个」）必须在 T2 钉住，组件只做渲染。
 * 这条卡片上的承诺尤其贵 —— 它后面是不可撤销的物理删除（设计 §5.5 已否掉 `.trash`）。
 *
 * 三件事在这里，不在组件里：
 * 1. 每组保留谁的裁决（改选值 / 默认 id 最小 / 策略 + 并列裁决 id 最小）；
 * 2. 「应用到未改选的 N 组」只碰未改选的那些；
 * 3. 上行载荷 `keep_ids` == 已展示每组的保留项，与服务端白名单同源那条边界。
 */
import type { DuplicateGroup } from '../api/datafiles'
import { usageBytesText } from './diskUsage'

export type KeepStrategy = 'earliest' | 'latest'

/** 两颗策略，不多写第三颗：组内 `file_size` 恒等（分组键含它），「体积最大」永远选不出别的东西。 */
export const STRATEGY_LABELS: Record<KeepStrategy, string> = {
  earliest: '最早导入',
  latest: '最新导入',
}

/**
 * 与后端 `_group_key` 同形状（`(filename, file_size)`），但必须是字符串：前端只拿 GET 的
 * `duplicate_groups`，没有别的可用身份。`|` 分隔不引入碰撞 —— 右段恒为数字，
 * 两个不同的 (filename, size) 拼出同一串需要文件名里吃掉一个 `|` 且大小仍是同一个数。
 */
export function groupKey(group: DuplicateGroup): string {
  return `${group.filename}|${group.file_size}`
}

/** 默认保留项 = `files[0].id`：后端 `files` 按 id 升序（`_group_duplicates` 的 order_by('id')）。 */
export function defaultKeepId(group: DuplicateGroup): number {
  return group.files[0].id
}

/**
 * 策略裁决。并列裁决**天然落在 id 最小**，不需要额外分支：`files` 按 id 升序是后端契约
 * （`_group_duplicates` 的 `order_by('id')`，Task 3 有一条 T1 钉住它），reduce 从 `files[0]`
 * 起步、只在**严格**更早/更晚时换人 ⇒ `created_at` 相同的组里首条就是 id 最小的那条。
 * 「相同 created_at 时再比一次 id」那种写法是给已经排好序的数组重复排序，
 * 而且会误导下一个人以为顺序不可靠。
 */
export function strategyKeepId(group: DuplicateGroup, strategy: KeepStrategy): number {
  let best = group.files[0]
  for (const f of group.files) {
    const better = strategy === 'earliest'
      ? f.created_at < best.created_at
      : f.created_at > best.created_at
    if (better) best = f
  }
  return best.id
}

export function keepIdForGroup(group: DuplicateGroup, choice: Map<string, number>): number {
  const chosen = choice.get(groupKey(group))
  return chosen === undefined ? defaultKeepId(group) : chosen
}

/** 返回**新** Map（调用方直接赋给 ref，Vue 侧不依赖 Map 的深改追踪）。 */
export function applyStrategyToUntouched(
  groups: DuplicateGroup[],
  choice: Map<string, number>,
  strategy: KeepStrategy,
): Map<string, number> {
  const next = new Map(choice)
  for (const group of groups) {
    const key = groupKey(group)
    if (!next.has(key)) next.set(key, strategyKeepId(group, strategy))
  }
  return next
}

/** 已展示每组的保留项全量上行（含未改选的默认值）。服务端据此逐组裁决，见 `_resolve_keep_selection`。 */
export function resolveKeepIds(groups: DuplicateGroup[], choice: Map<string, number>): number[] {
  return groups.map((group) => keepIdForGroup(group, choice))
}

/**
 * 汇总只算已展示组 —— 与按钮要删的东西严格同范围，否则数字就是在骗人。
 * 形参里没有 `choice`，不是漏了：每组恒删 `len - 1` 个，**改选保留谁不改变删除数量**，
 * 只改变删走的那一份（那一份由 `resolveKeepIds` 承重）。加一个不参与计算的参数
 * 只会让下一个人以为它参与。
 */
export function deleteSummary(groups: DuplicateGroup[]): { count: number; bytes: number } {
  let count = 0
  let bytes = 0
  for (const group of groups) {
    const doomed = group.files.length - 1
    count += doomed
    bytes += doomed * group.file_size
  }
  return { count, bytes }
}

export function deleteSummaryText(groups: DuplicateGroup[]): string {
  const { count, bytes } = deleteSummary(groups)
  return `按选择删除 ${count} 个（${usageBytesText(bytes)}）`
}

/** 超过切片才出这句话（MaintenanceCard 的空串即不渲染）。 */
export function truncatedNoteText(totalCount: number, displayedCount: number): string {
  if (totalCount <= displayedCount) return ''
  return `共 ${totalCount} 组重复，本批处理前 ${displayedCount} 组，`
    + `另有 ${totalCount - displayedCount} 组未处理 —— 重新检查后可继续。`
}

/** 删除回执的尾巴。0 时说空话比说「另有 0 组」好读。 */
export function remainingGroupsNote(remaining: number | undefined): string {
  if (!remaining || remaining <= 0) return ''
  return `，另有 ${remaining} 组未处理`
}

/**
 * 故意不复用 `utils/format.ts` 的 `formatTime`：那是 MM-DD HH:mm 短形态，
 * 实测 `formatTime('2026-11-14T23:07:08+00:00')` = `'11/15 07:07'` —— 没有年份，
 * 而这张卡要分「两次导入」的先后，样本实测差两个月、跨年时短形态会读反。
 * 同一条理由的第二份实现见 `diskUsage.ts:usageScannedText`（那边还带 `hour12:false` 的
 * 等价变异说明）；第三份出现时把它们并起来。
 */
export function dupImportText(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString('zh-CN', { hour12: false })
}
```

- [ ] **Step 4: 跑到全绿**

```bash
cd frontend && npx vitest run test/unit/dupKeep.spec.ts 2>&1
npx vitest run test/unit/diskUsage.spec.ts 2>&1
```
Expected: 两份全绿。`dupKeep` 依赖 `diskUsage` 的 `usageBytesText`，所以第二次跑的是**被依赖方**的既有判据
（它若有回归，本批的字节文案就是错的；批2 那 16 条不许因为「本批没改它」而省掉）。

- [ ] **Step 5: 变异反证**

* M10：把 `keepIdForGroup` 的回落从 `defaultKeepId(group)` 改成 `group.files.at(-1)!.id` ⇒
  `未改选时用默认保留项` 红。
* M11：把 `applyStrategyToUntouched` 的 `if (!next.has(key))` 挡掉 ⇒ `只覆盖未改选的组` 红。
* M12：把 `truncatedNoteText` 的第一句改回「删除操作将作用于全部」⇒ 两条红
  （整句比对 + 「必须消失」那条）。
* M13：把 `strategy === 'earliest' ? f.created_at < best.created_at : ...` 的两个比较符互换 ⇒
  `策略「最早/最新」比 created_at，与 id 大小无关` 红（两颗按钮互换是这条判据唯一要抓的形状）。
* M14：往 `STRATEGY_LABELS` 加 `largest: '体积最大'` ⇒ `只有两颗策略` 红（谎话控件绊线）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/utils/dupKeep.ts frontend/test/unit/dupKeep.spec.ts
git commit -m "feat(data): 重复项保留选择纯函数层 + T2（两颗策略、切片文案、汇总）"
```

---

## Task 6: 卡片改造成 radio 行（结构钩子 + 源侧绊线）

**Files:**
- Modify: `frontend/src/pages/data/components/DuplicateFilesCard.vue`
- Test: `frontend/test/unit/dupKeepWiring.spec.ts`

- [ ] **Step 1: 重写组件**

整个文件替换为（关键：`data-testid="dup-group"` / `dup-keep-row` + `data-keep` 是给 T3 的
**结构**钩子，按文案筛的定位器抓不到「选中态画错行」这种回归 —— 批2 G1 实测过同形状）：

```vue
<template>
  <MaintenanceCard
    test-id="duplicate-files-card"
    :visible="groups.length > 0"
    title="重复文件"
    tag-text="文件名与大小完全相同"
    tag-type="danger"
    :alert="{
      title: '以下文件按「文件名 + 大小」判定重复。每组保留一项、删除其余；未改选的组默认保留最早导入的那条。',
      type: 'warning',
    }"
    :truncated-note="truncatedNote"
  >
    <div class="dup-strategy">
      <span class="dup-strategy-label">未改选的组默认保留</span>
      <el-radio-group v-model="strategy" size="small" :disabled="!canDelete">
        <el-radio value="earliest">最早导入</el-radio>
        <el-radio value="latest">最新导入</el-radio>
      </el-radio-group>
      <el-button
        size="small"
        :disabled="!canDelete || untouched.length < 1"
        data-testid="dup-apply-strategy"
        @click="applyStrategy"
      >
        应用到未改选的 {{ untouched.length }} 组
      </el-button>
    </div>

    <div
      v-for="group in groups"
      :key="groupKey(group)"
      class="dup-group"
      data-testid="dup-group"
    >
      <div class="dup-group-header">
        <span class="dup-group-key mono">{{ group.filename }}</span>
        <span class="dup-group-size mono">{{ formatSize(group.file_size) }}</span>
        <span class="dup-group-count">{{ group.files.length }} 个</span>
      </div>
      <el-radio-group
        class="dup-keep-rows"
        :model-value="keepFor(group)"
        :disabled="!canDelete"
        @update:model-value="(id: number) => pick(group, id)"
      >
        <div
          v-for="f in group.files"
          :key="f.id"
          class="dup-file-row"
          data-testid="dup-keep-row"
          :data-keep="f.id === keepFor(group) ? 'keep' : 'delete'"
        >
          <el-radio :value="f.id">
            <span class="dup-file-state">{{ f.id === keepFor(group) ? '保留' : '将删除' }}</span>
            <span class="dup-file-loc mono">{{ f.file_type === 'batch' ? `[${f.batch_name}]` : '[单文件]' }}</span>
            <span class="dup-file-id mono">#{{ f.id }}</span>
            <span class="dup-file-time">{{ dupImportText(f.created_at) }}</span>
            <span class="dup-file-size mono">{{ formatSize(f.file_size) }}</span>
          </el-radio>
        </div>
      </el-radio-group>
    </div>

    <template #footer-left>
      <el-checkbox v-model="deleteConfirmed" :disabled="!canDelete">
        <span :style="{ color: canDelete ? 'var(--error)' : 'var(--text-3)', fontWeight: 600 }">
          {{ canDelete ? '我已确认按以上选择删除' : '仅管理员可删除重复文件' }}
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <el-button
        type="danger"
        plain
        :disabled="!deleteConfirmed || !canDelete"
        :loading="fixing"
        @click="submit"
      >
        <el-icon><Delete /></el-icon> {{ summaryText }}
      </el-button>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { DuplicateGroup, DuplicateGroupFile } from '../../../api/datafiles'
import { formatSize } from '../../../utils/format'
import {
  applyStrategyToUntouched,
  deleteSummaryText,
  groupKey,
  keepIdForGroup,
  resolveKeepIds,
  truncatedNoteText,
  dupImportText,
  type KeepStrategy,
} from '../../../utils/dupKeep'
import MaintenanceCard from './MaintenanceCard.vue'

/**
 * 重复文件卡（批3a）。这里原来的两支「✓ 保留 / 删除」是**只读 `el-tag`**，
 * 没有 `@click`：文案把后端既定策略渲染成用户的承诺，而用户什么都选不了。
 *
 * 选择状态只有一份 `choice`（Map）。曾经考虑过再加一个 `touched` 集合，那是两份事实：
 * `choice.has(key)` 就是「用户改选过」，删掉集合后「一键策略只碰未改选组」这条
 * 由 `applyStrategyToUntouched` 自己判，不需要调用方再维护一个影子。
 */
const props = defineProps<{
  groups: DuplicateGroup[]
  /** 总组数（groups 只是展示切片） */
  totalCount: number
  fixing: boolean
  /** 当前用户是否有删除权限（管理员） */
  canDelete: boolean
}>()

const emit = defineEmits<{
  fix: [keepIds: number[]]
}>()

const deleteConfirmed = ref(false)
const choice = ref(new Map<string, number>())
const strategy = ref<KeepStrategy>('earliest')

// 检查结果刷新后：确认态与选择态一起清零。留着旧选择等于拿上一批 id 去删这一批 ——
// 服务端会按白名单拒（400），但那只是兜底，界面不该先骗一次。
watch(() => [props.groups, props.totalCount], () => {
  deleteConfirmed.value = false
  choice.value = new Map()
})

const untouched = computed(() =>
  props.groups.filter((g) => !choice.value.has(groupKey(g))))

const truncatedNote = computed(() => truncatedNoteText(props.totalCount, props.groups.length))
const summaryText = computed(() => deleteSummaryText(props.groups))

function keepFor(group: DuplicateGroup): number {
  return keepIdForGroup(group, choice.value)
}

function pick(group: DuplicateGroup, id: number) {
  choice.value.set(groupKey(group), id)
}

function applyStrategy() {
  choice.value = applyStrategyToUntouched(props.groups, choice.value, strategy.value)
}

function submit() {
  emit('fix', resolveKeepIds(props.groups, choice.value))
}
</script>

<style scoped>
.dup-strategy {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.dup-strategy-label {
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}

.dup-group {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.dup-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.dup-group-key {
  font-size: var(--p-fs-dense);
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 55%;
}

.dup-group-size {
  font-size: var(--p-fs-micro);
  color: var(--info);
}

.dup-group-count {
  font-size: var(--p-fs-micro);
  color: var(--text-3);
  padding: 1px 6px;
  background: var(--bg);
  border-radius: 8px;
}

.dup-keep-rows {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.dup-file-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.dup-file-state {
  min-width: 3.5em;
  font-weight: 600;
  color: var(--text);
}

.dup-file-row[data-keep='keep'] .dup-file-state {
  color: var(--success);
}

.dup-file-row[data-keep='delete'] .dup-file-state {
  color: var(--error);
}

.dup-file-loc,
.dup-file-id,
.dup-file-time,
.dup-file-size {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

.mono {
  font-family: var(--font-mono);
}
</style>
```

行数预算：约 245 行（原 141），仍 < 600。

- [ ] **Step 2: 写源侧绊线（装配层要有自己的判据）**

创建 `frontend/test/unit/dupKeepWiring.spec.ts`，形状抄 `roleLabelHygiene.spec.ts`
（`new URL('../../src/', import.meta.url)` + `codeOf` 剥行首注释 + 反向探针）：

```ts
/**
 * T2（源侧绊线）：重复项保留选择的**接线**形状。
 *
 * 为什么这一层需要它：`dupKeep.spec.ts` 钉的是纯函数，`repair-center.spec.ts` 钉的是
 * 浏览器终态；中间那层「组件到底有没有真的用这些函数、有没有把 keep_ids 真的送出去」
 * 在两边都没有牙 —— 组件不装 jsdom（本仓 T2 约定），而 e2e 只看结果，
 * 「按钮文案写死『全部』但函数照常算」这种回退在 e2e 里照样绿。
 *
 * 跑：cd frontend && npx vitest run test/unit/dupKeepWiring.spec.ts
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SRC = (rel: string) => new URL(`../../src/${rel}`, import.meta.url)
/** 整行注释不参与判定：为什么这么接线必须能写在注释里，否则下一个人会当废话删掉。 */
const codeOf = (t: string) => t.split('\n').filter((l) => !/^\s*(\/\/|\/\*|\*|<!--)/.test(l)).join('\n')
const read = (rel: string) => codeOf(readFileSync(SRC(rel), 'utf8'))

const card = () => read('pages/data/components/DuplicateFilesCard.vue')
const dialog = () => read('pages/data/components/ConsistencyCheckDialog.vue')
const api = () => read('api/datafiles.ts')

describe('重复文件卡的接线', () => {
  it('选择与汇总都走 utils/dupKeep，不在组件里现算字符串', () => {
    const c = card()
    expect(c).toMatch(/from '[^']*utils\/dupKeep'/)
    for (const fn of ['resolveKeepIds', 'keepIdForGroup', 'deleteSummaryText', 'truncatedNoteText', 'applyStrategyToUntouched']) {
      expect(c, `组件里少了 ${fn}`).toContain(`${fn}(`)
    }
  })
  it('按钮数字来自当前选择，「全部」这种写死措辞不许回来', () => {
    const c = card()
    expect(c).toMatch(/\{\{\s*summaryText\s*\}\}/)
    expect(c).not.toMatch(/删除全部重复项|删除全部/)
    expect(c).toMatch(/我已确认按以上选择删除/)
  })
  it("选中态有结构钩子（按文案筛抓不到'画错行'）", () => {
    const c = card()
    expect(c).toMatch(/data-testid="dup-keep-row"/)
    expect(c).toMatch(/:data-keep="f\.id === keepFor\(group\)/)
  })
  it('fix 事件带 keep_ids 上行', () => {
    expect(card()).toMatch(/emit\('fix',\s*resolveKeepIds\(/)
  })
})

describe('对话框与 api 的接线', () => {
  it('对话框把 keep_ids 交给 api，并把 remaining_groups 拼进回执', () => {
    const d = dialog()
    expect(d).toMatch(/fixConsistency\(action,\s*keepIds\)/)
    expect(d).toMatch(/remainingGroupsNote\(/)
  })
  it('请求体真的带 keep_ids', () => {
    expect(api()).toMatch(/keep_ids/)
    expect(api()).toMatch(/remaining_groups\?: number/)
  })
})

describe('反向探针（改注释/换行/无关改名都不许红）', () => {
  it('多行 import 同判据', () => {
    const c = card()
    expect(c).toMatch(/applyStrategyToUntouched,/)
    expect(codeOf('// applyStrategyToUntouched(\n// resolveKeepIds(')).toBe('')
  })
})
```

- [ ] **Step 3: 跑 T2 两档 + 构建**

```bash
cd frontend && npx vitest run test/unit/dupKeep.spec.ts test/unit/dupKeepWiring.spec.ts 2>&1
npm run build 2>&1
```
Expected: 两条 vitest 全绿；`npm run build`（含 `vue-tsc -b`）出 `✓ built`、零 TS 诊断。
若 `@update:model-value="(id: number) => pick(group, id)"` 报 `TS2345`（EP 的 modelValue 是
`string | number | boolean`），改成 `(val: string | number | boolean) => pick(group, Number(val))`，
并在 T2 的绊线里保留 `keepFor(group)` 那个形状 —— 别为了过编译把 `Number()` 藏进 utils。

- [ ] **Step 4: 变异反证**

* M15：把 `@click="submit"` 换成 `@click="emit('fix')"`（丢掉载荷）⇒ `fix 事件带 keep_ids` 红，
  且 T3 第二条必红（服务端收不到 keep_ids 就按默认删，留下的是 -A 而不是 -B）。
* M16：把 `:data-keep` 那行删掉 ⇒ 绊线红 + T3 的 `toHaveAttribute` 红。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/DuplicateFilesCard.vue \
        frontend/test/unit/dupKeepWiring.spec.ts
git commit -m "feat(data): 重复文件卡改 radio 选保留（两颗策略 + 结构钩子），接线绊线入库"
```

---

## Task 7: 对话框与 API 接线（keep_ids 上行、remaining_groups 下行）

**Files:**
- Modify: `frontend/src/api/datafiles.ts:220-227,294-309`
- Modify: `frontend/src/pages/data/components/ConsistencyCheckDialog.vue:85-91,162-197`

- [ ] **Step 1: 改 API**

```ts
  fixConsistency(action: ConsistencyFixAction, keepIds?: number[]) {
    // import/fix may reparse many files — the axios default 30s timeout is
    // too tight for large orphan sets, so those calls get a 120s budget.
    const config = ['delete_orphaned_db', 'delete_orphaned_disk', 'delete_duplicates'].includes(action)
      ? {}
      : { timeout: 120_000 }
    // keep_ids 只在 delete_duplicates 上有意义；undefined 时**不写这个键**，
    // 让「老客户端不传」与服务端「按默认留最早」那条分支保持可区分（T1 钉着）。
    const body = keepIds ? { action, keep_ids: keepIds } : { action }
    return api.post<FixConsistencyResponse>('/consistency-check/', body, config)
  },
```

`FixConsistencyResponse` 里加一行：

```ts
  deleted_count?: number
  /** 只作用于已展示组时，删完之后还剩几组（服务端删后实测，不是算术值） */
  remaining_groups?: number
```

- [ ] **Step 2: 改对话框**

`summarize` 的 `delete_duplicates` 分支：

```ts
    case 'delete_duplicates':
      return `已删除 ${data.deleted_count} 个重复文件${remainingGroupsNote(data.remaining_groups)}`
```

`handleFix` 收第二参、卡片事件带 id：

```ts
async function handleFix(action: ConsistencyFixAction, keepIds?: number[]) {
  fixingAction.value = action
  try {
    const { data } = await datafilesApi.fixConsistency(action, keepIds)
    ElMessage.success(summarize(action, data))
    await runCheck()
    emit('done')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出（400 invalid_keep_id 走的就是这条通路：
    // 后端 detail 是中文 ⇒ pickMessage 先读 message，前端不需要 ERROR_CODE_MAP 条目）
  } finally {
    fixingAction.value = null
  }
}

async function handleFixDeleteDuplicates(keepIds: number[]) {
  await handleFix('delete_duplicates', keepIds)
}
```

两条 import 各指一处（`remainingGroupsNote` 住在 `dupKeep.ts`，`usageMismatchLine` 仍是批2 那条）：

```ts
import { usageMismatchLine } from '../../../utils/diskUsage'
import { remainingGroupsNote } from '../../../utils/dupKeep'
```

模板里那张卡的 `@fix` 不改（`@fix="handleFixDeleteDuplicates"` 现在收到的是 `number[]`）；
但 `ConsistencyCheckDialog.vue` 里 `handleFix` 的其它调用点（`@fix="handleFix"`，三个卡片）
传的是 `action` 字符串 —— EP 的 `emit('fix')` 无载荷时 `keepIds` 为 `undefined`，
TS 侧那三处的签名是 `(keepIds?: number[])` 兼容。**别顺手改成 `@fix="(a) => handleFix(a)"`**：
那只是把无谓的箭头塞进模板，且会让 Task 6 的绊线少一个匹配点。

- [ ] **Step 3: 跑构建与 vitest**

```bash
cd frontend && npx vitest run test/unit/dupKeep.spec.ts test/unit/dupKeepWiring.spec.ts 2>&1
npm run build 2>&1
```
Expected: 绊线里 `fixConsistency\(action,\s*keepIds\)` 与 `remainingGroupsNote\(` 两条此刻才第一次为真
⇒ Step 1/2 之前它们应该正红着（先红后绿，顺序不许倒）。

- [ ] **Step 4: 变异反证**

* M17：把 `const body = keepIds ? {...} : {action}` 换成恒带 `keep_ids: keepIds`（即 `undefined` 也写）⇒
  绊线 `请求体真的带 keep_ids` 不红（子串还在），但 T1 的默认分支照样绿 ——
  **这条是等价变异，不要声称判据抓住了它**；真正抓住「忘了传」的是 M15 与 T3 第二条。
* M18：把 `remainingGroupsNote(data.remaining_groups)` 整段删掉 ⇒ 绊线红。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/datafiles.ts frontend/src/pages/data/components/ConsistencyCheckDialog.vue
git commit -m "feat(data): keep_ids 上行与 remaining_groups 回执接线（含错误通路说明）"
```

---

## Task 8: T3 —— 终态判据「留下的是被选那一份」

**Files:**
- Modify: `frontend/e2e/data/repair-center.spec.ts:211-266`

- [ ] **Step 1: 加两条 spec 局部助手**（放在 `apiPost` 之后，`test.describe.serial` 之前）

```ts
const DUP_PREFIX = `DUP-E2E-${ts}`
const DUP_CONTENT = [
  '[CTA8280F]',
  'TestFileName,BPD60320.pts',
  '[Data]',
  'col1,col2',
  'mm,mm',
  '0,0',
  '1,1',
  '1,1',
  '1,1',
].join('\n')

/**
 * 同名同大小的两份文件 = 一个重复组两只成员。分装两个批次目录，因为终态判据
 * 要按 `batch_name` 认「留下的是哪一份」—— 同一目录会同名覆盖成一只物理文件。
 * 先导入 A 再导入 B ⇒ A 的 id 更小 = 「最早导入」那一条。
 */
async function seedDuplicatePair(page: Page, dupName: string, tag: string) {
  const dirA = path.join(ADMIN_BATCH_DIR, `${DUP_PREFIX}-${tag}-A`)
  const dirB = path.join(ADMIN_BATCH_DIR, `${DUP_PREFIX}-${tag}-B`)
  for (const dir of [dirA, dirB]) {
    fs.mkdirSync(dir, { recursive: true })
    fs.writeFileSync(path.join(dir, dupName), DUP_CONTENT)
  }
  for (const name of [`${DUP_PREFIX}-${tag}-A`, `${DUP_PREFIX}-${tag}-B`]) {
    const imp = await apiPost(page, '/batch-dirs/import/', { dir_name: name })
    expect(imp.status).toBe(201)
  }
  return { dirA, dirB, batchA: `${DUP_PREFIX}-${tag}-A`, batchB: `${DUP_PREFIX}-${tag}-B` }
}

/**
 * 终态串：`数量|批次名`。合成一条而不是两条断言 —— 「只剩 1 条」与「剩下的是 -B」
 * 分开写时，第一条会先红并把第二条吃掉（vitest/Playwright 都是首条失败即抛），
 * 而那正是本条要修的缺陷的形状：旧用例只断「剩 1 条」，选的是哪条没人钉。
 */
async function dupEndState(page: Page, dupName: string): Promise<string> {
  const { body } = await apiGet(page, '/files/?page_size=9999')
  const list: any[] = Array.isArray(body) ? body : (body.results ?? [])
  const rows = list.filter((f: any) => f.filename === dupName)
  return `${rows.length}|${rows[0]?.batch_name ?? '—'}`
}

async function cleanupDup(dupName: string, ...dirs: string[]) {
  for (const dir of dirs) fs.rmSync(dir, { recursive: true, force: true })
  try {
    shellDjango(`DataFile.objects.filter(owner__username='admin', filename='${dupName}').delete()`)
  } catch {
    // 环境清理失败不阻塞用例
  }
}
```

- [ ] **Step 2: 用两条用例替掉原「重复文件（同名同大小）可检测并删除」**

```ts
  test('重复文件：不改选时默认保留最早导入那一份', async ({ page }) => {
    const dupName = `dup_def_${ts}.csv`
    const pair = await seedDuplicatePair(page, dupName, 'DEF')
    try {
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      await expect(card).toContainText(dupName)
      await expect(card).toContainText('2 个')

      const group = card.locator('[data-testid="dup-group"]').filter({ hasText: dupName })
      const rowA = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchA })
      const rowB = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchB })
      await expect(rowA).toHaveCount(1, '两个批次目录各成一行')
      await expect(rowB).toHaveCount(1)
      // 结构钩子，不按颜色/文案筛：画错行的「保留」在文案上照样通顺。
      await expect(rowA).toHaveAttribute('data-keep', 'keep')
      await expect(rowB).toHaveAttribute('data-keep', 'delete')

      await card.locator('.el-checkbox').click()
      await expect(card.locator('button').filter({ hasText: '按选择删除 1 个' })).toBeVisible()
      await card.locator('button').filter({ hasText: '按选择删除' }).click()
      await expect(page.getByText(/已删除 \d+ 个重复文件/).first()).toBeVisible({ timeout: 20_000 })

      await expect
        .poll(() => dupEndState(page, dupName), { timeout: 15_000 })
        .toBe(`1|${pair.batchA}`)
      expect(fs.existsSync(path.join(pair.dirA, dupName)), '保留那份的磁盘文件必须还在').toBe(true)
      expect(fs.existsSync(path.join(pair.dirB, dupName)), '未保留那份必须从磁盘消失').toBe(false)
    } finally {
      await cleanupDup(dupName, pair.dirA, pair.dirB)
    }
  })

  test('重复文件：改选保留项后留下的是被选那一份（缺陷第 3 项的正解）', async ({ page }) => {
    const dupName = `dup_pick_${ts}.csv`
    const pair = await seedDuplicatePair(page, dupName, 'PICK')
    try {
      await openRepairCenter(page)
      const card = page.locator('[data-testid="duplicate-files-card"]')
      await expect(card).toBeVisible({ timeout: 15_000 })
      const group = card.locator('[data-testid="dup-group"]').filter({ hasText: dupName })
      const rowA = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchA })
      const rowB = group.locator('[data-testid="dup-keep-row"]').filter({ hasText: pair.batchB })

      await rowB.locator('.el-radio').click()
      await expect(rowB).toHaveAttribute('data-keep', 'keep')
      await expect(rowA).toHaveAttribute('data-keep', 'delete')

      await card.locator('.el-checkbox').click()
      await card.locator('button').filter({ hasText: '按选择删除' }).click()
      await expect(page.getByText(/已删除 \d+ 个重复文件/).first()).toBeVisible({ timeout: 20_000 })

      // 旧行为（硬编码留 id 最小）会在这里红：留下的批次名是 -A。
      await expect
        .poll(() => dupEndState(page, dupName), { timeout: 15_000 })
        .toBe(`1|${pair.batchB}`)
      expect(fs.existsSync(path.join(pair.dirB, dupName)), '被选那一份的磁盘文件必须还在').toBe(true)
      expect(fs.existsSync(path.join(pair.dirA, dupName)), '默认那条必须真的被删走').toBe(false)
    } finally {
      await cleanupDup(dupName, pair.dirA, pair.dirB)
    }
  })
```

⚠ 原用例的 `2 个` 断言与卡片可见性断言都保留在第一条里；`修复后本批次问题全部消失` 那条不动
（它按 `BATCH` 名前缀检查另三类卡片，与本批两条无交集）。

- [ ] **Step 3: 类型体检 + 跑这一档**

```bash
cd frontend && npm run lint:e2e 2>&1
cd .. && node scripts/e2e_pool.mjs --slots=1 -- e2e/data/repair-center.spec.ts 2>&1
```
Expected: `lint:e2e` 零 `error TS`；池末行 `结论 MEASURED` 且 `unexpected 0`，
`x` 行只该出现本文件那 5–6 条用例（⚠ 判级取末行与 `unexpected`，不取退出码；
`unexpected 1` 可能是负载抖动 —— 按 testing-gates §4 先看崩池判据再定）。

- [ ] **Step 4: 变异反证（这一条必须跑在浏览器层）**

* M19：把 `_delete_duplicate_files` 里 `keep = keep_by_key.get(...)` 那两行的回落改成恒取默认
  （等价于「服务端不采纳 keep_ids」）⇒ 第二条用例必红（终态 `1|...-A`），第一条照旧绿。
  **这条是 F3 教训的正面执行**：后端语义只在浏览器通路真跑（不用 `page.route` 遮响应）才可能红，
  所以这一步跑的是真后端 + 真磁盘。
* M20：把 `pending` 算成 `group['files'][1:]`（回到旧硬编码）⇒ 第二条红。
* M21：把组件里 `data-keep` 的三元反过来 ⇒ 第一条就红（默认态判据），证明结构钩子有牙。

- [ ] **Step 5: affected 门禁一次**

```bash
cd frontend && npm run test:e2e:affected 2>&1
```
Expected: 末行 `RESULT: PASS`。命中 `frontend/src/utils/` ⇒ 会升全量池（~10min），这是预期。

- [ ] **Step 6: 提交**

```bash
git add frontend/e2e/data/repair-center.spec.ts
git commit -m "test(e2e): 重复文件终态改按「留下的是被选那一份」判（补上旧用例断不出的那一半）"
```

---

## Task 9: 介绍书联动（维护时机 ②）

**Files:**
- Modify: `docs/intro/.vitepress/theme/components/FileListMock.vue:42`
- Modify: `docs/intro/.vitepress/theme/data.ts:93`

- [ ] **Step 1: 改复刻文案**

`FileListMock.vue:42` 的 `④ 重复文件（同内容多记录）` 改成与实际一致：

```js
  dialog('数据修复中心', '<p>检查四类不一致：</p><p>① 孤立 DB 记录（有元数据无磁盘文件）</p><p>② 孤立磁盘文件（有文件无元数据）</p><p>③ 产品名缺失</p><p>④ 重复文件（文件名 + 大小相同）——每组可选保留哪一份，删除只作用于已展示的组</p>',
```

`data.ts:93` 那一行的 `d` 与 `how` 同步（介绍书里「d」是功能描述、「how」是操作路径，
改完必须仍读得通）：

```js
    { t: '数据修复中心', d: '检查孤立 DB 记录 / 孤立磁盘文件 / 产品名缺失 / 重复文件四类不一致；重复项每组可选保留哪一份。', how: '点「数据修复」跑检查清单，重复卡里改选保留项后按选择删除（复刻可试）。' },
```

- [ ] **Step 2: 构建与自检**

```bash
npm run intro:build 2>&1
node scripts/intro/check.mjs 2>&1
```
Expected: check 末行 `PASS`。

- [ ] **Step 3: 真浏览器走读改动章节**（CLAUDE.md 视觉类改动要求）

```bash
cd docs/intro && npx vitepress dev 2>&1   # 记下端口
```
用桌面宽度打开 `guide/04-data.html`，点「数据修复」，确认第 ④ 句是新的那句、控制台零报错；
再按 420px 宽度看同一章不破版。⚠ 别停用 :3000/:8000 上已有的进程，另起端口。

- [ ] **Step 4: 提交**

```bash
git add docs/intro/.vitepress/theme/components/FileListMock.vue docs/intro/.vitepress/theme/data.ts
git commit -m "docs(intro): 数据修复中心复刻改说「每组可选保留、只删已展示的组」"
```

---

## Task 10: 收口门禁、台账与 lessons

- [ ] **Step 1: 收口档全跑（每档取判据行，不取退出码；输出整段落盘再 grep，禁 `| tail`）**

```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test 2>&1 > tasks/b3a_backend_full.log
cd frontend && npm run build 2>&1 > ../tasks/b3a_build.log
npx vitest run 2>&1 > ../tasks/b3a_vitest.log
npm run lint:e2e 2>&1 > ../tasks/b3a_lint.log
cd .. && node scripts/e2e_pool.mjs --slots=4 2>&1 > tasks/b3a_pool.log
```

| 档 | 判据取法 |
|---|---|
| 后端全量 | 末尾 `Ran N tests` + `OK (skipped=…)`；`grep -cE "^(FAIL|ERROR):" tasks/b3a_backend_full.log` = 0 |
| 全量池 | `结论 MEASURED`、`unexpected`、`flaky`，崩池判据先排（§4） |
| vitest | `Test Files N passed`、`Tests N passed`；`lineLimit` 那 15 条在其中 |
| lint:e2e | `error TS` 计数 0 |
| build | `✓ built`、零 TS 诊断 |

- [ ] **Step 2: 台账（`docs/tasks/todo.md` 追加一节，数字一律现取）**

新条目形如 `# 任务：批3a 重复项选保留（2026-11-14，计划 …）`，写七件：
状态（是否并入 master、base 是谁）、收口各档判据行、T1/T2/T3 例数、探针五个数、
两处用户拍板（只删已展示的组 / 体积最大作废）、变异反证表（M1–M21 逐条结果，
含**等价变异**那两条不许写成「抓住」）、遗留清单。规模**只写命令不写数**：
`git rev-list --count <base>..master`、`git diff --shortstat <base>..master`。

- [ ] **Step 3: lessons 回写（只在真的撞了坑时）**

`docs/tasks/lessons.md` 末尾追加 `## 2026-11-14 批3a …` 条目。本批预定值得写的候选两条：
「策略按钮的区分度要先量（组内恒等维度的按钮是谎话控件）」与
「语义反转类改动没有既有测试承重 ⇒ 新用例必须同时钉住旧契约不许回来」。
**没实测就别写教训**（lessons 是实测库，不是收藏夹）。

- [ ] **Step 4: 终审（整批一次，交回问题逐条复验）→ 按 finishing-a-development-branch 收尾**

`--ff-only` 并入本地 master，**绝不 push**（`origin` 是公开仓库）。

---

## Self-Review 结论（写完自查，已就地修正）

1. **规格覆盖**：§5.1 现状（Task 6 的注释里逐条点名「只读 tag 无 @click」）／§5.2 前端选型（Task 5/6，
   两颗策略按订正）／§5.3 后端契约五条（Task 2/3/4，含第 5 条 `remaining_groups` 实测）／
   §5.4 语义反转与文案（Task 4 切片用例 + Task 5 `truncatedNoteText` + Task 6 接线）／
   §5.5 不动物理删（本计划零改动，只在 Task 6 注释里点名不可撤销）／§5.6 三层判据逐条落位。
   §7 验收第 6 条（改选留被选、51 组、非法 id 400）由 Task 4 + Task 8 覆盖。
2. **无占位符**：每个改代码的步骤都给了可编译的整段；`void choice` 那处订正写在 Step 4 的注里，
   不留「待定」。
3. **类型一致性**：`_resolve_keep_selection(groups, keep_ids, limit)` 的返回
   `(displayed, keep_by_key)` 与 Task 3 的调用一致；`keep_by_key` 的键是 `_group_key(group)` 元组，
   前端 `groupKey()` 是字符串 —— 两份**互不流通**（服务端键不出模块，客户端键不发网络），
   上行载荷只有 id 列表，这点在 Task 4 的 `keep_ids` 契约里钉着。
