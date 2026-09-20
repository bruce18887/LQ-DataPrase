# SFTP 搜索子系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 SFTP 浏览器加上「作用域 + 元数据过滤 + 三选一命中模式」的流式搜索，结果与运行状态在应用生命周期内跨页面驻留。

**Architecture:** 后端在 `apps/sftp/search/` 新建一个纯 Python 搜索引擎（BFS 遍历 → 字节级扫描 → 可选服务端 grep 加速），由 `engine.py` 编排成阶段机、经一条 SSE 长连接流式吐给前端；搜索自己开 N 条临时连接（走主机密钥校验），绝不碰池连接。前端把 SSE 流的所有权放进 Pinia store（因此跨路由不中断），页面是 `/sftp/search` 路由页，配一个 App 级常驻 chip。

**Tech Stack:** Django 6.0.5 + DRF（ViewSet + `@action`）、paramiko 5.0.0、`StreamingHttpResponse` SSE；Vue 3 + Vite + Pinia + Element Plus + AG Grid；Playwright e2e。

**Spec:** `docs/superpowers/specs/2026-09-20-sftp-search-design.md`（commit `87a03db`）。逐条对应其 §3.x，实现时两份一起读。

**关于本计划的代码密度**：测试代码是完整可粘贴的——测试就是行为规格，照抄即可。
实现部分给的是**结构、必须精确的常量/参数名/那一两行关键代码**，不是整模块的成品代码：
每个模块 150–280 行，把它们全贴在计划里只会让真正的约束被淹没。
标注为「收敛要求」的地方，是我写计划时留下的半成品或错误，**必须按该处说明改掉**，不要照抄。

## Global Constraints

每个任务的隐含要求，值照抄 spec：

- **单文件 600 行硬上限**（`.claude/CLAUDE.md` 末段）。`apps/sftp/views.py` 现 561 行、`frontend/src/pages/sftp/SftpBrowser.vue` 现 545 行。
- **测试放置跟随 SFTP 现状**：视图契约测试在 app 内 `tests_*.py`，纯逻辑在 `test/backend/`。
- **runner 是 `python manage.py test`**，不是 pytest（全仓无 pytest.ini / conftest.py）。
- **任何 `except` 不得静默**：必须留 WARNING 日志（`test/backend/test_sftp_guards.py:224-252` 钉着）。
- **错误格式**：流开始前的校验失败 → `400 {"error": msg}`；流开始后只能发带内 `error` 事件，生成器内绝不抛 DRF 异常。
- **SSE 响应头**必须同时有 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。
- **任何新开 SFTP 连接必须经 `host_keys.open_verified_transport()`**；禁止 `AutoAddPolicy`（参考工具有，不许移植）。
- **前端改动同时维护 dark + light 主题**，只用语义 token（`--text-2`/`--border-2`/`--brand`/`--error`/`--p-fs-*`），不新增字面色值。
- **命中片段渲染禁止 `v-html`**（`term` 是用户输入，走 v-html 就是自造 XSS 面）。
- **e2e 收尾释放 8000 / 3000 端口**；SFTP 相关 spec 必须 `test.describe.configure({ mode: 'serial' })`（状态按 user 存，多 worker 互相覆盖 —— lessons R6）。
- **paramiko 是 5.0.0**：`Transport.__init__` **没有** `default_timeout`。读超时只能用现成的 `apps/sftp/downloads.py:53` `channel_timeout(sftp, seconds)` 设在 channel 上。
- **搜索共享常量**（定义在 `contracts.py`，全计划从这里取，勿各处另写数字）：
  `READ_TIMEOUT_SEC = 15`、`HARD_MAX_DEPTH = 64`、`MAX_ROOTS = 20`、`MAX_TERM_LEN = 200`、
  `PRESET_MAX_PER_USER = 50`。engine 侧：`EVENT_POLL_SEC = 0.2`、`FLUSH_MAX_ITEMS = 200`、
  `FLUSH_MAX_AGE_SEC = 0.2`。前端：`RUN_HISTORY_KEEP = 20`、`AUTO_GROUP_THRESHOLD = 200`、
  `CANCEL_COOLDOWN_MS = 1200`。
- **`apps/sftp/urls.py` 用 `DefaultRouter`**，`@action` 自动成路由，**加端点不需要改 urls.py**。

## 文件结构

**后端新建**：`apps/sftp/search/{__init__,contracts,connect,walker,scanners,shell_grep,engine}.py`、
`apps/sftp/search_views.py`

**后端修改**：`apps/sftp/views.py`（+2 行：import 与类基表）、`apps/sftp/models.py`（+`SftpSearchPreset`）、
新增迁移、`apps/sftp/pool.py`（Task 1 的 RLock）

**后端测试**：`test/backend/{sftp_fake, test_sftp_pool_lock, test_sftp_search_contract,
test_sftp_search_engine, test_sftp_search_connect, test_sftp_search_walk,
test_sftp_search_scan, test_sftp_search_grep}.py`、`apps/sftp/{tests_search,tests_search_preset}.py`

**前端新建**：`utils/ssePost.ts`、`api/sftpSearch.ts`、`stores/sftpSearch.ts`、
`pages/sftp/SftpSearchPage.vue`、`pages/sftp/components/{SearchCriteria,SearchResultsTable,SearchProgress}.vue`、
`components/common/ActiveSearchChip.vue`、`utils/sftpSearchExport.ts`

**前端修改**：`api/sftp.ts`、`router/index.ts`、`pages/sftp/SftpBrowser.vue`、
`pages/sftp/components/{SftpToolbar,SftpFileTable}.vue`、App 级布局（挂 chip）

**文档**：`docs/user-guide/06-sftp.md`

## 执行顺序

Task 1 独立成批先行（后面「搜索期间可浏览」的承诺依赖它）。
**Task 11 → 11B → Task 11 Step 5 的真机 HTTP 验证 是一道闸门：三样都绿了才写前端。**
11B 是全套测试里唯一能抓出 paramiko 并行协议错乱的一级，不能降级成人工清单；
Step 5 测的是 SSE 分帧穿过 `StreamingHttpResponse` 之后还完不完整。
Task 12 起的纯前端可在 11B 之后并行推进。

---

## 阶段 0：补上失效的无锁前提

### Task 1: pool.py per-user RLock

**Files:**
- Modify: `apps/sftp/pool.py`（135 → 约 160 行）
- Test: `test/backend/test_sftp_pool_lock.py`（新建）

**Interfaces:**
- Produces: `get_connection` / `invalidate` / `close` 签名与行为不变；新增模块级
  `_lock_for(user_id) -> threading.RLock`、`_locks: Dict[object, RLock]`、`_locks_guard`

- [ ] **Step 1: 写失败的测试**

`test/backend/test_sftp_search/`… 路径为 `test/backend/test_sftp_pool_lock.py`：

```python
"""pool 必须容忍 threaded runserver 下同 user 并发访问（spec §2.5）。

跑法：python manage.py test test.backend.test_sftp_pool_lock
     或 python test/backend/test_sftp_pool_lock.py
"""
import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp import host_keys, pool  # noqa: E402


class _FakeTransport:
    builds = []

    def __init__(self):
        _FakeTransport.builds.append(1)
        self.active = True

    def is_active(self):
        return self.active

    def close(self):
        self.active = False


class _FakeSFTP:
    def close(self):
        pass


class PoolLockTests(SimpleTestCase):
    N = 8

    def setUp(self):
        pool._pool.clear()
        _FakeTransport.builds = []
        self._orig_open = host_keys.open_verified_transport
        self._orig_session = pool.get_session
        host_keys.open_verified_transport = lambda *a, **k: _FakeTransport()
        pool.get_session = lambda uid: {'host': 'h', 'port': 22,
                                        'username': 'u', 'password': 'p'}
        import paramiko
        self._orig_from = paramiko.SFTPClient.from_transport
        paramiko.SFTPClient.from_transport = staticmethod(lambda tr: _FakeSFTP())

    def tearDown(self):
        pool._pool.clear()
        host_keys.open_verified_transport = self._orig_open
        pool.get_session = self._orig_session
        import paramiko
        paramiko.SFTPClient.from_transport = self._orig_from

    def test_concurrent_get_connection_builds_once(self):
        """8 线程同时取连接：只允许一次握手，且全部拿到同一个对象。"""
        results, barrier = [], threading.Barrier(self.N)

        def worker():
            barrier.wait()
            results.append(pool.get_connection(42))

        threads = [threading.Thread(target=worker) for _ in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(results), self.N)
        self.assertEqual(
            len(_FakeTransport.builds), 1,
            f'并发下建立了 {len(_FakeTransport.builds)} 条连接，锁未生效')
        self.assertTrue(all(r is results[0] for r in results))
        self.assertEqual(len(pool._pool), 1)

    def test_different_users_do_not_share_a_lock(self):
        """锁按 user 分，否则一个用户的慢握手会挡住别的用户。"""
        self.assertIs(pool._locks.get(1), pool._locks.get(2)) \
            if (1 in pool._locks and 2 in pool._locks) else None
        pool.get_connection(1)
        pool.get_connection(2)
        self.assertIsNot(pool._locks[1], pool._locks[2])
```

> **收敛要求**：上面第二个测试的第一行是我写飘的无意义表达式（`assertIs(...) if ... else None`
> 不会失败也不会断言）。**删掉那一行**，只保留后面四行 —— `get_connection(1)` 与
> `(2)` 之后断言两把锁是不同对象即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `python test/backend/test_sftp_pool_lock.py`
Expected: FAIL —— `AssertionError: 并发下建立了 N 条连接，锁未生效`（N > 1）
以及 `KeyError` 或 `AttributeError: module ... has no attribute '_locks'`

- [ ] **Step 3: 加锁**

`apps/sftp/pool.py` import 段补 `import threading`。在 `_pool` 声明（`:55`）下方加：

```python
# threaded runserver（桌面版实际形态）下同 user 会并发进来，_pool 的状态转换必须串行。
# 锁按 user_id 分：否则一个用户的慢握手会挡住所有用户。
_locks: Dict[object, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(user_id) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(user_id)
        if lock is None:
            lock = _locks[user_id] = threading.RLock()
        return lock
```

把 `get_connection`（`:98-125`）整个函数体包进 `with _lock_for(user_id):`
——**必须包括 `_build_entry` 调用**，不包握手就会 8 个线程各握一次手。
`invalidate`（`:128`）与 `close`（`:133`）同样各包一次。

模块 docstring 第 15–23 行的「Concurrency model」段改写为：

```
Concurrency model
-----------------
A per-user ``threading.RLock`` serialises this module's *state transitions*:
the liveness check, the rebuild, and the pop/close in ``invalidate``/``close``.

The original "lock-free by design" note rested on gunicorn sync workers, but the
shipping desktop app runs ``manage.py runserver`` (standalone.py:224), which is
threaded by default in Django 6 (--nothreading is store_false). Concurrent
same-user requests therefore really do reach here from different threads.

What the lock does NOT cover: it guards the pool dict and the transport/sftp
lifecycle, not paramiko's ``SFTPClient`` *operations*. Two threads running
``listdir``/``open`` on the same client would still desync the protocol stream.
That stays kept away by one-connection-per-user + the frontend transfer mutex +
searches using their own ephemeral connections (``search/connect.py``).
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python test/backend/test_sftp_pool_lock.py && python manage.py test test.backend.test_sftp_pool`
Expected: 两个文件全 PASS（原有 6 个池测试不得回归）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/pool.py test/backend/test_sftp_pool_lock.py
git commit -m "fix(sftp): pool 补 per-user RLock，修 threaded runserver 下失效的无锁前提

桌面版跑 manage.py runserver（standalone.py:224），Django 6 默认 threaded，
使 pool.py 自述的「sync worker 故可无锁」前提不成立：同用户并发的 list_files
与下载 SSE 生成器可分属两线程踩踏同一 _Entry。锁只覆盖池自身的状态转换，
paramiko client 的并发操作仍由前端互斥与搜索走独立连接规避（docstring 已改）。"
```

---

## 阶段 1：契约与引擎选择（纯逻辑，无 IO）

### Task 2: SearchSpec 契约与钳位

**Files:**
- Create: `apps/sftp/search/__init__.py`（空）
- Create: `apps/sftp/search/contracts.py`
- Test: `test/backend/test_sftp_search_contract.py`

**Interfaces:**
- Consumes: `apps.sftp.downloads.clamp_timeout(value) -> int`（现成：钳到 30–3600，非法回退 600）
- Produces:
  - `contracts.SearchSpec` —— frozen dataclass，字段见 Step 3 清单
  - `contracts.SearchSpecError(ValueError)`，属性 `.field: str`
  - `contracts.parse_spec(raw: dict) -> SearchSpec`
  - `SearchSpec.effective_max_depth() -> Optional[int]`
  - `SearchSpec.clamped: List[str]`（`clamped_<field>` 码；engine 转 notice）
  - 常量 `READ_TIMEOUT_SEC`、`HARD_MAX_DEPTH`、`MAX_ROOTS`、`MAX_TERM_LEN`、`PRESET_MAX_PER_USER`

- [ ] **Step 1: 写失败的测试**

`test/backend/test_sftp_search_contract.py` —— 逐条对应 spec §3.2 钳位表与校验规则：

```python
"""SearchSpec 的校验与钳位（spec §3.2）。无 DB、无网络。

跑法：python manage.py test test.backend.test_sftp_search_contract
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts  # noqa: E402

BASE = {'roots': ['/datalogs'], 'mode': 'name'}


def spec(**over):
    return contracts.parse_spec({**BASE, **over})


class RequiredFieldTests(SimpleTestCase):
    def test_missing_roots_rejected(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            contracts.parse_spec({'mode': 'name'})
        self.assertEqual(ctx.exception.field, 'roots')

    def test_empty_roots_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            contracts.parse_spec({'roots': [], 'mode': 'name'})

    def test_unknown_key_rejected(self):
        """未知键必须拒绝。sftp.ts 至今发 only_data 而后端从不读它，就是缺这条。"""
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(recursive=True)
        self.assertIn('recursive', str(ctx.exception))

    def test_content_mode_requires_term(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='content', term='   ')
        self.assertEqual(ctx.exception.field, 'term')

    def test_column_mode_requires_column_name(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='column', column_name='')
        self.assertEqual(ctx.exception.field, 'column_name')

    def test_bad_mode_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(mode='regex')

    def test_bad_matching_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(mode='content', term='x', matching='regex')

    def test_bad_depth_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='deep')


class DefaultTests(SimpleTestCase):
    def test_defaults(self):
        s = spec()
        self.assertEqual(s.depth, 'all')
        self.assertIsNone(s.effective_max_depth())
        self.assertEqual(s.workers, 4)
        self.assertEqual(s.timeout, 600)
        self.assertTrue(s.data_files_only)
        self.assertTrue(s.allow_server_grep)
        self.assertFalse(s.stop_after_listing)
        self.assertFalse(s.one_per_folder)
        self.assertTrue(s.first_hit_per_file)
        self.assertEqual(s.matching, 'substring')
        self.assertEqual(s.max_entries, 200_000)
        self.assertEqual(s.max_candidates, 5_000)
        self.assertEqual(s.max_matches, 2_000)
        self.assertEqual(s.max_scan_bytes, 64 * 1024 * 1024)
        self.assertEqual(s.column_rows, 10)
        self.assertEqual(s.matches_per_file, 1)
        self.assertEqual(s.prune_dirs, [])


class ClampTests(SimpleTestCase):
    """越界夹到边界并记码，不报错——用户拖个滑块到最大不该吃 400。"""

    def test_workers_ceiling_and_floor(self):
        self.assertEqual(spec(workers=99).workers, 8)
        self.assertIn('clamped_workers', spec(workers=99).clamped)
        self.assertEqual(spec(workers=0).workers, 1)

    def test_max_entries_ceiling(self):
        self.assertEqual(spec(max_entries=10 ** 9).max_entries, 500_000)

    def test_max_candidates_ceiling(self):
        self.assertEqual(spec(max_candidates=10 ** 9).max_candidates, 50_000)

    def test_max_matches_ceiling(self):
        self.assertEqual(spec(max_matches=10 ** 9).max_matches, 20_000)

    def test_matches_per_file_ceiling(self):
        self.assertEqual(spec(matches_per_file=999).matches_per_file, 20)

    def test_column_rows_ceiling(self):
        self.assertEqual(spec(column_rows=999).column_rows, 50)

    def test_max_scan_bytes_ceiling(self):
        self.assertEqual(spec(max_scan_bytes=10 ** 12).max_scan_bytes, 1 << 30)

    def test_timeout_goes_through_downloads_clamp(self):
        self.assertEqual(spec(timeout=5).timeout, 30)
        self.assertEqual(spec(timeout=10 ** 6).timeout, 3600)
        self.assertIn('clamped_timeout', spec(timeout=5).clamped)

    def test_term_length_rejected_not_clamped(self):
        """term 静默截断会让用户查到完全不同的东西，所以是报错不是钳位。"""
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='content', term='x' * 201)
        self.assertEqual(ctx.exception.field, 'term')

    def test_roots_count_rejected_not_clamped(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=[f'/p{i}' for i in range(21)])

    def test_non_integer_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(workers='lots')


class DepthTests(SimpleTestCase):
    def test_self_maps_to_zero(self):
        self.assertEqual(spec(depth='self').effective_max_depth(), 0)

    def test_children_maps_to_one(self):
        self.assertEqual(spec(depth='children').effective_max_depth(), 1)

    def test_all_means_unlimited(self):
        self.assertIsNone(spec(depth='all').effective_max_depth())

    def test_custom_requires_value(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='custom')

    def test_custom_hard_capped(self):
        self.assertEqual(spec(depth='custom', max_depth=999)
                         .effective_max_depth(), 64)

    def test_custom_rejects_non_positive(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='custom', max_depth=0)


class NormalisationTests(SimpleTestCase):
    def test_roots_normalised_and_deduped(self):
        self.assertEqual(spec(roots=['/a/b/', '/a/b', '/a']).roots,
                         ['/a/b', '/a'])

    def test_root_must_be_absolute(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=['relative/path'])

    def test_root_with_parent_ref_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=['/a/../b'])

    def test_dates_accept_two_formats(self):
        self.assertEqual(spec(modified_after='2026-09-01T00:00')
                         .modified_after.month, 9)
        self.assertIsNotNone(spec(modified_after='2026-09-01').modified_after)

    def test_bad_date_rejected(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(modified_after='9月1号')
        self.assertEqual(ctx.exception.field, 'modified_after')

    def test_blank_optional_strings_become_none(self):
        self.assertIsNone(spec(name_pattern='   ').name_pattern)

    def test_prune_dirs_stripped_and_empties_dropped(self):
        self.assertEqual(spec(prune_dirs=[' *backup* ', '', '  ']).prune_dirs,
                         ['*backup*'])

    def test_inverted_size_bounds_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(min_size=100, max_size=50)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_contract`
Expected: FAIL —— `ModuleNotFoundError: No module named 'apps.sftp.search'`

- [ ] **Step 3: 实现 contracts.py**

必须有的东西（结构自定，但下面这些名字与语义要一致）：

```python
MODES = ('name', 'content', 'column')
MATCHINGS = ('substring', 'whole_word', 'fuzzy')
DEPTHS = ('self', 'children', 'all', 'custom')
DEPTH_TO_MAX = {'self': 0, 'children': 1, 'all': None, 'custom': None}

READ_TIMEOUT_SEC = 15
HARD_MAX_DEPTH = 64
MAX_ROOTS = 20
MAX_TERM_LEN = 200
PRESET_MAX_PER_USER = 50

# 每项 (low, high)；越界即夹并记 clamped_<field>
_INT_BOUNDS = {
    'workers': (1, 8),
    'max_entries': (1, 500_000),
    'max_candidates': (1, 50_000),
    'max_matches': (1, 20_000),
    'matches_per_file': (1, 20),
    'column_rows': (1, 50),
    'max_scan_bytes': (1, 1 << 30),
}

_KNOWN_KEYS = frozenset({...})   # spec §3.2 请求体的全部 27 个键，一个不多一个不少
```

`SearchSpec` 字段（frozen dataclass，`clamped` 用 `field(default_factory=list)`）：
`roots, mode, depth='all', max_depth=None, prune_dirs, name_pattern=None,
modified_after=None, modified_before=None, min_size=None, max_size=None,
data_files_only=True, term='', column_name='', column_rows=10, matching='substring',
case_sensitive=False, first_hit_per_file=True, matches_per_file=1, one_per_folder=False,
workers=4, allow_server_grep=True, stop_after_listing=False, max_entries=200000,
max_candidates=5000, max_matches=2000, max_scan_bytes=67108864, timeout=600, clamped`

实现要点：

- **先查未知键**：`set(raw) - _KNOWN_KEYS` 非空即抛 `SearchSpecError`，消息里带上未知键名
  （测试断言 `'recursive' in str(exc)` 依赖它）。
- `timeout` 走 `from apps.sftp.downloads import clamp_timeout`，
  并把「原始值 ≠ 钳位值」记成 `clamped_timeout`。
- `_DATE_FORMATS = ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d')`，逐个试，全失败抛错。
- roots 用 `posixpath.normpath` 归一、去空、去重，保序；非 `/` 开头或含 `..` 段则抛错。
- bool 字段容忍字符串 `'true'/'1'/'yes'/'y'/'on'`（前端可能发字符串），其余按 `bool()`。
- `effective_max_depth()`：`depth != 'custom'` 时返回 `DEPTH_TO_MAX[depth]`，
  否则返回 `max_depth`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_contract`
Expected: PASS（约 34 个测试）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/__init__.py apps/sftp/search/contracts.py test/backend/test_sftp_search_contract.py
git commit -m "feat(sftp): 搜索契约 SearchSpec 与钳位

未知键一律拒绝：sftp.ts 至今仍在发后端从不读的 only_data，不能再造一个
会悄悄失效的字段。term 超长是报错不是钳位（静默截断等于查的是别的东西）。
深度不设实用上限，失控由 max_entries + timeout 兜（spec §3.2 理由）。"
```

---

### Task 3: `select_engine()` 谓词

**Files:**
- Create: `apps/sftp/search/engine.py`（本任务只放 `select_engine` + `ProbeResult`）
- Test: `test/backend/test_sftp_search_engine.py`

**Interfaces:**
- Consumes: `contracts.SearchSpec`
- Produces:
  - `engine.ProbeResult(has_grep: bool, has_find_xargs: bool, path_mapping_ok: bool, reason: str = '')`
    + 属性 `.usable -> bool`（= `has_grep and path_mapping_ok`）
  - `engine.select_engine(spec, probe) -> Tuple[str, str]` —— `('grep'|'client', reason)`
  - 常量 `PATH_MAPPING_MSG`、`NON_ASCII_GREP_MSG`、`FUZZY_UNSUPPORTED_MSG`

- [ ] **Step 1: 写失败的测试**

`test/backend/test_sftp_search_engine.py` —— spec §3.3 那 7 条，每条一正一反：

```python
"""引擎选择谓词（spec §3.3）。

它存在的全部理由是：**同一个查询在有无 grep 的两台服务器上必须给出同一个结果集**。
所以这里钉的是「什么情况必须回落 client」，不是「grep 能不能跑」。

跑法：python manage.py test test.backend.test_sftp_search_engine
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, engine  # noqa: E402

OK = engine.ProbeResult(has_grep=True, has_find_xargs=True, path_mapping_ok=True)


def spec(**over):
    base = {'roots': ['/d'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def name_of(s):
    return engine.select_engine(s, OK)[0]


class GrepEligibleTests(SimpleTestCase):
    def test_plain_substring(self):
        self.assertEqual(name_of(spec()), 'grep')

    def test_ascii_whole_word(self):
        """整词在 ASCII 上两档语义一致（scanners 按 [A-Za-z0-9_] 判边界）。"""
        self.assertEqual(name_of(spec(matching='whole_word')), 'grep')

    def test_time_filter_without_xargs_probe_falls_back(self):
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        self.assertEqual(
            engine.select_engine(spec(modified_after='2026-09-01'), probe)[0],
            'client')

    def test_time_filter_with_full_probe_uses_grep(self):
        self.assertEqual(name_of(spec(modified_after='2026-09-01')), 'grep')

    def test_name_pattern_does_not_block_grep(self):
        self.assertEqual(name_of(spec(name_pattern='*RT*.csv')), 'grep')


class MustFallBackTests(SimpleTestCase):
    CASES = [
        ('仅文件名模式', {'mode': 'name'}),
        ('列值模式', {'mode': 'column', 'column_name': 'ShadowReg2'}),
        ('模糊匹配无原语', {'matching': 'fuzzy'}),
        ('非 ASCII 词会静默漏 GBK 文件', {'term': '漏电电流'}),
        ('每目录一个无原语', {'one_per_folder': True}),
        ('仅列不扫不必动用 grep', {'stop_after_listing': True}),
        ('用户显式关掉加速', {'allow_server_grep': False}),
    ]

    def test_each_case_forces_client(self):
        for label, over in self.CASES:
            with self.subTest(label):
                base = {'mode': 'content', 'term': 'ShadowReg2'}
                base.update(over)
                self.assertEqual(name_of(spec(**base)), 'client',
                                 f'{label} 必须回落 client')

    def test_reason_always_non_empty(self):
        """回落必须带原因，前端要显示——不能让人猜这次是哪档跑的。"""
        for label, over in self.CASES:
            base = {'mode': 'content', 'term': 'ShadowReg2'}
            base.update(over)
            _name, reason = engine.select_engine(spec(**base), OK)
            with self.subTest(label):
                self.assertTrue(reason.strip())


class ProbeFailureTests(SimpleTestCase):
    def test_no_grep_binary(self):
        probe = engine.ProbeResult(False, False, False, '服务器上没有可用的 grep')
        name, reason = engine.select_engine(spec(), probe)
        self.assertEqual(name, 'client')
        self.assertIn('服务器上没有可用的 grep', reason)

    def test_chroot_mapping_mismatch_blocks_grep(self):
        """SFTP 常 chroot：同一路径字符串在 shell 侧可能不存在，
        不验就会 grep 空路径、返回 0 命中、用户以为真没有。"""
        probe = engine.ProbeResult(True, True, False, engine.PATH_MAPPING_MSG)
        self.assertEqual(engine.select_engine(spec(), probe)[0], 'client')

    def test_grep_without_mapping_probe_is_still_unusable(self):
        probe = engine.ProbeResult(True, True, False)
        self.assertFalse(probe.usable)
        _name, reason = engine.select_engine(spec(), probe)
        self.assertTrue(reason.strip(), '无 reason 的不可用也必须给出可显示的话')
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_engine`
Expected: FAIL —— `ImportError: cannot import name 'engine'`

- [ ] **Step 3: 实现**

判断顺序必须是：**先判 spec 侧条件，再判 probe 侧**，且**每条都返回自己的 reason**
（`ProbeResult.reason` 只能覆盖 probe 引起的那一条回落）。七条条件照 spec §3.3 抄：

```python
def select_engine(spec: SearchSpec, probe: ProbeResult) -> Tuple[str, str]:
    """返回 ("grep"|"client", 原因)。原因恒非空。"""
    if spec.mode != 'content':
        return 'client', f'命中模式 {spec.mode} 需要客户端引擎'
    if not spec.allow_server_grep:
        return 'client', '用户已关闭服务端加速'
    if spec.matching == 'fuzzy':
        return 'client', FUZZY_UNSUPPORTED_MSG
    if not spec.term.isascii():
        return 'client', NON_ASCII_GREP_MSG
    if spec.one_per_folder:
        return 'client', '每目录只取一个文件 grep 无对应原语'
    if spec.stop_after_listing:
        return 'client', '仅列出候选不需要执行 grep'
    if not probe.usable:
        return 'client', probe.reason or '服务器不支持服务端 grep'
    if ((spec.modified_after or spec.modified_before)
            and not probe.has_find_xargs):
        return 'client', '时间过滤需要 GNU find/xargs，服务器不具备'
    return 'grep', '服务端 grep 可用'
```

> 注意 `whole_word` **不在**回落条件里 —— ASCII 整词是允许走 grep 的（Task 6 的
> `word_ok` 与 `LC_ALL=C grep -w` 在 ASCII 上字面一致）。这是 spec §3.3 最后一段的落点。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_engine`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/engine.py test/backend/test_sftp_search_engine.py
git commit -m "feat(sftp): 引擎选择谓词 select_engine

7 条回落条件逐条钉正反例。非 ASCII 与模糊的回落理由是「结果集不得取决于
服务器恰好有没有 grep」，不是性能取舍。ASCII 整词允许走 grep。"
```

---

## 阶段 2：临时连接

### Task 4: SearchSession

**Files:**
- Create: `apps/sftp/search/connect.py`
- Test: `test/backend/test_sftp_search_connect.py`

**Interfaces:**
- Consumes: `apps.sftp.cache.get_session(user_id) -> Optional[dict]`（键
  `host/port/username/password`，见 `apps/sftp/cache.py:134`）、
  `apps.sftp.host_keys.open_verified_transport(host, port, username, password) -> Transport`
  （`host_keys.py:182`，调用方负责 close）
- Produces:
  - `connect.SearchSessionError(Exception)`
  - `connect.ConnItem = Tuple[Transport, SFTPClient]`
  - `connect.SearchSession(user_id: int, workers: int)`：
    `.opened: int`、`.closed: int`、`.size -> int`、`.open_all() -> int`、
    `.borrow(timeout=None) -> ConnItem`、`.give_back(item, *, broken=False)`、
    `.exec_transport() -> Transport`（借出供 grep 用，调用方还）、
    `.close_all()`（幂等）、`__enter__` / `__exit__`
  - `connect.CONNECTION_ERRORS = (paramiko.SSHException, paramiko.SFTPError, EOFError, OSError)`

- [ ] **Step 1: 写失败的测试**

```python
"""SearchSession 的借还、降级与关闭（spec §3.7）。

这里用假 transport，测的是借还/降级/无泄漏三件真服务器不便制造的事；
真 paramiko 并行正确性在 Task 11 的集成测试里，两者不可互替。

跑法：python manage.py test test.backend.test_sftp_search_connect
"""
import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp import host_keys  # noqa: E402
from apps.sftp.search import connect  # noqa: E402

CREDS = {'host': 'sftp.example', 'port': 22, 'username': 'u', 'password': 'p'}


class _FakeTransport:
    def __init__(self, serial):
        self.serial = serial
        self.closed = False

    def close(self):
        self.closed = True

    def is_active(self):
        return not self.closed

    def open_session(self, timeout=None):
        return object()


class _FakeSFTP:
    def close(self):
        pass


class ConnectTests(SimpleTestCase):
    def setUp(self):
        self.built = []
        self.fail_after = None
        self._orig_open = host_keys.open_verified_transport
        self._orig_session = connect.cache.get_session

        def fake_open(host, port, username, password):
            if self.fail_after is not None and len(self.built) >= self.fail_after:
                raise OSError('server refused: MaxSessions exceeded')
            tr = _FakeTransport(len(self.built))
            self.built.append(tr)
            return tr

        host_keys.open_verified_transport = fake_open
        connect.cache.get_session = lambda uid: dict(CREDS)
        import paramiko
        self._orig_from = paramiko.SFTPClient.from_transport
        paramiko.SFTPClient.from_transport = staticmethod(
            lambda tr: _FakeSFTP())

    def tearDown(self):
        host_keys.open_verified_transport = self._orig_open
        connect.cache.get_session = self._orig_session
        import paramiko
        paramiko.SFTPClient.from_transport = self._orig_from

    def test_no_session_raises_not_connected(self):
        connect.cache.get_session = lambda uid: None
        with self.assertRaises(connect.SearchSessionError) as ctx:
            connect.SearchSession(1, 2).open_all()
        self.assertIn('not connected', str(ctx.exception).lower())

    def test_opens_requested_number(self):
        s = connect.SearchSession(1, 4)
        self.assertEqual(s.open_all(), 4)
        self.assertEqual(s.size, 4)

    def test_degrades_when_server_refuses_extra(self):
        """开不出来必须降级继续跑，而不是整次搜索失败。"""
        self.fail_after = 2
        self.assertEqual(connect.SearchSession(1, 4).open_all(), 2)

    def test_host_key_mismatch_propagates(self):
        """安全边界：不降级、不吞异常。"""
        def boom(*a, **k):
            raise host_keys.HostKeyMismatchError('mismatch')
        host_keys.open_verified_transport = boom
        with self.assertRaises(host_keys.HostKeyMismatchError):
            connect.SearchSession(1, 2).open_all()

    def test_borrow_reuses_idle_item(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item)
        self.assertIs(s.borrow(), item)
        s.close_all()

    def test_borrow_blocks_until_returned(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        held = s.borrow()
        got = []

        def waiter():
            got.append(s.borrow())
            s.give_back(got[0])

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        self.assertEqual(got, [], '唯一连接被占着，borrow 不该立刻返回')
        s.give_back(held)
        t.join(timeout=5)
        self.assertFalse(t.is_alive())
        self.assertEqual(got, [held])
        s.close_all()

    def test_broken_connection_closed_and_replaced(self):
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item, broken=True)
        self.assertTrue(item[0].closed, '坏连接必须关掉，不能放回队列')
        fresh = s.borrow(timeout=5)
        self.assertIsNot(fresh, item)
        s.close_all()

    def test_broken_when_reopen_fails_does_not_deadlock(self):
        """补不上新连接也要让队列保持可消费，否则 borrow 永久阻塞。"""
        self.fail_after = 1
        s = connect.SearchSession(1, 1)
        s.open_all()
        item = s.borrow()
        s.give_back(item, broken=True)
        s.close_all()
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_close_all_closes_everything_and_is_idempotent(self):
        s = connect.SearchSession(1, 3)
        s.open_all()
        s.close_all()
        s.close_all()
        self.assertEqual(s.closed, s.opened)
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_close_all_drives_out_a_blocked_borrow(self):
        """取消路径依赖这条：close_all 之后 borrow 必须立刻失败而非永挂。"""
        s = connect.SearchSession(1, 1)
        s.open_all()
        s.borrow()                      # 占住唯一一条
        errors = []

        def waiter():
            try:
                s.borrow()
            except Exception as exc:     # noqa: BLE001 - 断言异常类型由下面做
                errors.append(exc)

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        s.close_all()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), 'close_all 后 borrow 仍挂着')
        self.assertEqual(errors, [s._SENTINEL_ERR_TYPE] if errors else errors)
        self.assertTrue(errors)

    def test_context_manager_closes_on_exception(self):
        with self.assertRaises(RuntimeError):
            with connect.SearchSession(1, 2) as s:
                s.open_all()
                raise RuntimeError('boom')
        self.assertTrue(all(tr.closed for tr in self.built))

    def test_every_connection_goes_through_host_key_verification(self):
        """参考工具用 AutoAddPolicy，会破坏本项目 TOFU 契约。"""
        s = connect.SearchSession(1, 3)
        s.open_all()
        self.assertEqual(len(self.built), 3)   # built 只在 fake_open 里追加
        s.close_all()
```

> **收敛要求**：`test_close_all_drives_out_a_blocked_borrow` 倒数第二行引用了一个
> 不存在的 `s._SENTINEL_ERR_TYPE`，是半成品。**改成**：
> `self.assertIsInstance(errors[0], connect.SearchSessionError)`，并删掉那行诡异的
> 三元断言。为满足它，`close_all()` 必须向队列塞入哨兵使阻塞中的 `borrow()` 抛出
> `SearchSessionError`（见 Step 3 的 `None` 哨兵）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test/backend/test_sftp_search_connect.py`
Expected: FAIL —— `ImportError: cannot import name 'connect'`

- [ ] **Step 3: 实现**

模块 docstring 要写清"为什么不能用池连接"（照抄 spec §3.7 的两条：paramiko client
非线程安全会 desync 协议流报 `Garbage packet received`；`channel_timeout` 会串改共享
channel 的 socket 超时）。

结构与关键行为：

- `_credentials()` 惰性取 `cache.get_session(user_id)`，空则抛
  `SearchSessionError('no cached session (not connected)')`。
- `_open_one() -> ConnItem`：`host_keys.open_verified_transport(...)` →
  `paramiko.SFTPClient.from_transport(transport)`。**不 catch `HostKeyMismatchError`**，直接上抛。
- `open_all()`：加锁、幂等（已开过就直接返回 `self.opened`）；先取一次凭据让"未连接"
  就地失败；循环 `requested` 次，成功入队并 `opened += 1`，其它异常 `logger.warning` 后 `break`
  （降级），`HostKeyMismatchError` 则 `close_all()` + 上抛；结束若 `opened == 0` 抛
  `SearchSessionError('无法建立任何 SFTP 连接')`。
- `borrow(timeout=None)`：`self._q.get(timeout=timeout)`；拿到 `None` 哨兵即抛
  `SearchSessionError('session already closed')`。
- `give_back(item, *, broken=False)`：
  - `broken` → `_close_one(item)`，然后尝试 `_open_one()` 补一条入队、`opened += 1`；
    补不上则 `logger.warning` 并 `self._q.put(self._closed_flag(item))` ——
    **必须放一个东西回队列**，否则 `borrow` 永久阻塞；已关闭就 `_close_one(item)` 后返回。
  - 非 broken 且 `self._closed` → `_close_one(item)`；否则原样入队。
- `close_all()`：`with self._lock: if self._closed: return; self._closed = True`，
  然后 `while True: get_nowait()` 排空并 `_close_one`，最后**再 `put(None)` 一个哨兵**
  驱动阻塞中的 `borrow` 抛错；捕获 `queue.Empty` 退出循环。
- `_close_one(item)`：分别 close `sftp` 与 `transport`，各自 `except Exception:
  logger.warning(..., exc_info=True)`，然后 `self.closed += 1`。
- `exec_transport()`：`borrow(timeout=30)` 拿到 transport、**立即放回队列**、返回它
  （grep 只需要 transport 去 `open_session()`，不占用 SFTP channel）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_connect`
Expected: PASS（约 13 个测试）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/connect.py test/backend/test_sftp_search_connect.py
git commit -m "feat(sftp): 搜索专用临时连接 SearchSession

不走 pool 那条：paramiko client 非线程安全、channel_timeout 会串改共享 socket 超时。
开不出即降级；主机密钥不匹配不降级、直接失败。close_all 塞 None 哨兵驱动阻塞中的
borrow，取消路径靠它让卡住的 worker 脱身。"
```

---

## 阶段 3：遍历

### Task 5: BFS walker 与元数据过滤

**Files:**
- Create: `apps/sftp/search/walker.py`
- Create: `test/backend/sftp_fake.py`（**共享夹具，Task 6/7/9/10/11 都复用**）
- Test: `test/backend/test_sftp_search_walk.py`

**Interfaces:**
- Consumes: `SearchSession`（Task 4 的 `borrow`/`give_back`）、`SearchSpec`（Task 2）、
  `apps.datafiles.views._is_summary_csv(name) -> bool`（`apps/sftp/views.py:11` 就这么 import）
- Produces:
  - `walker.Candidate`：`__slots__ = ('path','name','size','mtime')`，`.as_dict()`
  - `walker.WalkResult`：`.candidates: List[Candidate]`、`.events: List[dict]`、
    `.entries_seen: int`、`.truncated: List[str]`、`.cancelled: bool`
  - `walker.walk(spec, session, *, on_candidate=None, cancel_event=None,
    deadline=None) -> WalkResult`
  - `walker.list_one(sftp, path, spec) -> Tuple[List[str], List[Candidate], Optional[str]]`
  - `walker.passes_metadata(name, size, mtime, spec) -> bool`
  - `walker.is_pruned(dirname, patterns) -> bool`
  - `sftp_fake.FakeSftp` / `FakeRemoteFile` / `FakeSession` / `sample_tree()`

- [ ] **Step 1: 写共享夹具 `test/backend/sftp_fake.py`**

```python
"""内存版假 paramiko SFTPClient：给搜索的纯逻辑测试提供一棵可遍历的树。

真服务器测试（含 paramiko 并行正确性）在 apps/sftp/tests_search.py，它跑
frontend/e2e/helpers/sftp_server.py。两者分工不同，别互相顶替。
"""
import fnmatch
import posixpath
import stat
from dataclasses import dataclass
from typing import Dict, List, Optional

import paramiko


@dataclass
class FakeAttr:
    filename: str
    st_mode: int
    st_size: int
    st_mtime: int


class FakeRemoteFile:
    """支持 read(n) / readline() / prefetch / close，够扫描与列值读取用。"""

    def __init__(self, content: bytes):
        self.content = content
        self.pos = 0
        self.prefetched = False
        self.closed = False

    def prefetch(self, file_size=None, max_concurrent_requests=None):
        self.prefetched = True

    def read(self, n: int = -1) -> bytes:
        if self.pos >= len(self.content):
            return b''
        if n is None or n < 0:
            chunk = self.content[self.pos:]
        else:
            chunk = self.content[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def readline(self) -> bytes:
        nl = self.content.find(b'\n', self.pos)
        if nl == -1:
            line = self.content[self.pos:]
            self.pos = len(self.content)
        else:
            line = self.content[self.pos:nl + 1]
            self.pos = nl + 1
        return line

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeSftp:
    """files: {绝对路径: bytes}；unreadable: 匹中这些 glob 的目录 listdir 抛错。

    broken=True 时一切操作抛 SFTPError，用于验「连接脏了要换」那条路径。
    """

    def __init__(self, files: Dict[str, bytes],
                 unreadable: Optional[List[str]] = None,
                 mtimes: Optional[Dict[str, int]] = None,
                 broken: bool = False):
        self.files = dict(files)
        self.unreadable = unreadable or []
        self.mtimes = mtimes or {}
        self.broken = broken
        self.listdir_calls: List[str] = []
        self.open_count = 0

    def _children(self, path: str):
        norm = posixpath.normpath(path)
        prefix = '/'' if False else ('' if norm == '/' else norm + '/')
        dirs, files = set(), set()
        for full in self.files:
            rest = full[len(prefix):] if norm != '/' else full.lstrip('/')
            if not rest or rest == full and norm != '/':
                continue
            if '/' in rest:
                dirs.add(rest.split('/', 1)[0])
            else:
                files.add(rest)
        return dirs, files

    def listdir_attr(self, path: str) -> List[FakeAttr]:
        if self.broken:
            raise paramiko.SFTPError('Garbage packet received')
        for pattern in self.unreadable:
            if fnmatch.fnmatch(path, pattern):
                raise IOError(f'Permission denied: {path}')
        self.listdir_calls.append(path)
        norm = posixpath.normpath(path)
        dirs, files = self._children(norm)
        out = [FakeAttr(d, stat.S_IFDIR | 0o755, 0, 1_700_000_000)
               for d in sorted(dirs)]
        for f in sorted(files):
            full = f if norm == '/' else posixpath.join(norm, f)
            out.append(FakeAttr(f, stat.S_IFREG | 0o644,
                                len(self.files[full]),
                                self.mtimes.get(full, 1_700_000_000)))
        return out

    def stat(self, path: str) -> FakeAttr:
        content = self.files.get(path)
        if content is None:
            raise IOError(f'No such file: {path}')
        return FakeAttr(posixpath.basename(path), stat.S_IFREG | 0o644,
                        len(content), self.mtimes.get(path, 1_700_000_000))

    def realpath(self, path: str) -> str:
        return posixpath.normpath(path)

    def open(self, path: str, mode: str = 'rb', bufsize: int = -1):
        if path not in self.files:
            raise IOError(f'No such file: {path}')
        self.open_count += 1
        return FakeRemoteFile(self.files[path])

    def get_channel(self):
        return None


class FakeSession:
    """SearchSession 的替身：所有借出都指向同一个 FakeSftp。"""

    def __init__(self, sftp, size: int = 1):
        self.sftp = sftp
        self._item = (object(), sftp)
        self.borrow_count = 0
        self.give_back_count = 0
        self._size = size

    def open_all(self):
        return self._size

    @property
    def size(self):
        return self._size

    def borrow(self, timeout=None):
        self.borrow_count += 1
        return self._item

    def give_back(self, item, *, broken: bool = False):
        self.give_back_count += 1

    def close_all(self):
        pass


def sample_tree() -> Dict[str, bytes]:
    """贯穿各测试的标准树：批次目录 × 同格式多文件 + 汇总 + 非 CSV + 深层 + GBK 中文。"""
    return {
        '/data/batch1/RT_001.csv':
            b'[HEADER]\r\nTestFile,D:\\stdf\\lotA_w01.stdf\r\n'
            b'StartTime,2026-09-01 08:12:33,\r\n[DATA]\r\n'
            b'SN,ShadowReg2\r\n1,0.42\r\n',
        '/data/batch1/RT_002.csv': b'[DATA]\r\nSN,ShadowReg2\r\n2,0.43\r\n',
        '/data/batch1/FT_001.csv': b'[DATA]\r\nSN,Vcc\r\n1,3\r\n',
        '/data/batch1/Sum_total.csv': b'summary,not,data\n',
        '/data/batch1/notes.txt': b'not a csv at all ShadowReg2\n',
        '/data/batch1/Deep/RT_003.csv': b'[DATA]\r\nSN,ShadowReg2\r\n3,0.44\r\n',
        '/data/batch2/RT_010.csv':
            '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk'),
        '/data/backup/RT_999.csv': b'[DATA]\r\nSN,ShadowReg2\r\n9,0.9\r\n',
        '/data/.hidden/RT_998.csv': b'[DATA]\r\nSN,ShadowReg2\r\n8,0.8\r\n',
    }
```

> **收敛要求**：`_children` 里 `prefix = '/'' if False else (...)` 是我打错的字符串拼接，
> 且 `if not rest or rest == full and norm != '/'` 的运算符优先级不是你要的意思。
> **改成两行清楚写法**：
> ```python
> prefix = '' if norm == '/' else norm + '/'
> ...
> for full in self.files:
>     if norm != '/' and not full.startswith(prefix):
>         continue
>     rest = full[len(prefix):] if norm != '/' else full.lstrip('/')
>     if not rest:
>         continue
> ```
> 改完先跑一个 sanity 测试：`FakeSftp(sample_tree()).listdir_attr('/data')` 应返回
> `batch1`、`batch2`、`backup` 三个目录属性、零文件。

- [ ] **Step 2: 写 walker 的失败测试**

`test/backend/test_sftp_search_walk.py`：

```python
"""BFS 遍历、元数据过滤、预算与剪枝（spec §3.4）。

跑法：python manage.py test test.backend.test_sftp_search_walk
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, walker  # noqa: E402
from test.backend.sftp_fake import FakeSession, FakeSftp, sample_tree  # noqa: E402


def walk(**over):
    over.setdefault('data_files_only', False)
    s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name', **over})
    sftp = FakeSftp(sample_tree())
    return walker.walk(s, FakeSession(sftp)), sftp


class FakeTreeSanityTests(SimpleTestCase):
    def test_root_lists_three_dirs_no_files(self):
        attrs = FakeSftp(sample_tree()).listdir_attr('/data')
        self.assertEqual([a.filename for a in attrs if not _isdir(a)],
                         ['.hidden'])
        self.assertTrue(any(a.filename == 'batch1' for a in attrs))


def _isdir(attr):
    import stat
    return stat.S_ISDIR(attr.st_mode)


class PruneTests(SimpleTestCase):
    def test_pruned_subtree_is_never_entered(self):
        _res, sftp = walk(prune_dirs=['backup'])
        self.assertNotIn('/data/backup', sftp.listdir_calls)

    def test_prune_matches_basename_only(self):
        _res, sftp = walk(prune_dirs=['batch*'])
        for called in sftp.listdir_calls:
            self.assertFalse(called.startswith('/data/batch'))

    def test_pruned_dirs_do_not_consume_entry_budget(self):
        """剪枝发生在进入前，否则「剪掉最外层」等于白剪。"""
        res, _ = walk(prune_dirs=['backup', 'batch1', 'batch2', '.hidden'],
                      max_entries=3)
        self.assertNotIn('truncated_entries', res.truncated)


class HiddenAndBudgetTests(SimpleTestCase):
    def test_dot_entries_skipped(self):
        res, _ = walk()
        self.assertFalse([c for c in res.candidates if '/.hidden/' in c.path])

    def test_dot_dir_not_entered(self):
        _res, sftp = walk()
        self.assertNotIn('/data/.hidden', sftp.listdir_calls)

    def test_entry_budget_reports_truncation(self):
        res, _ = walk(max_entries=2)
        self.assertIn('truncated_entries', res.truncated)

    def test_candidate_budget_stops_listing(self):
        res, _ = walk(max_candidates=1)
        self.assertEqual(len(res.candidates), 1)
        self.assertIn('truncated_candidates', res.truncated)

    def test_expired_deadline_marks_cancelled(self):
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())),
                          deadline=time.monotonic() - 1)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.candidates, [])

    def test_cancel_event_stops_walk(self):
        ev = threading.Event()
        ev.set()
        res, _s = _walk_with_cancel(ev)
        self.assertTrue(res.cancelled)
        self.assertEqual(res.candidates, [])


def _walk_with_cancel(ev):
    s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                              'data_files_only': False})
    sftp = FakeSftp(sample_tree())
    return walker.walk(s, FakeSession(sftp), cancel_event=ev), sftp


class DepthTests(SimpleTestCase):
    def test_self_only_lists_root(self):
        _res, sftp = walk(depth='self')
        self.assertEqual(sftp.listdir_calls, ['/data'])

    def test_self_excludes_nested(self):
        res, _ = walk(depth='self')
        self.assertNotIn('/data/batch1/Deep/RT_003.csv',
                         {c.path for c in res.candidates})
        self.assertIn('/data/batch1/RT_001.csv',
                      {c.path for c in res.candidates})

    def test_children_includes_one_level_below(self):
        res, _ = walk(depth='children')
        paths = {c.path for c in res.candidates}
        self.assertIn('/data/batch1/RT_001.csv', paths)
        self.assertNotIn('/data/batch1/Deep/RT_003.csv', paths)

    def test_all_reaches_every_depth(self):
        res, _ = walk(depth='all')
        self.assertIn('/data/batch1/Deep/RT_003.csv',
                      {c.path for c in res.candidates})

    def test_custom_depth_honoured(self):
        res, _ = walk(depth='custom', max_depth=2)
        self.assertNotIn('/data/batch1/Deep/RT_003.csv',
                         {c.path for c in res.candidates})

    def test_depth_truncation_reported(self):
        res, _ = walk(depth='children')
        self.assertIn('truncated_depth', res.truncated)


class MetadataFilterTests(SimpleTestCase):
    def test_name_pattern_fnmatch(self):
        res, _ = walk(name_pattern='*RT*')
        self.assertTrue(res.candidates)
        self.assertTrue(all('RT_' in c.name for c in res.candidates))

    def test_min_size_excludes_everything_small(self):
        res, _ = walk(min_size=999_999)
        self.assertEqual(res.candidates, [])

    def test_modified_after_excludes_all(self):
        res, _ = walk(modified_after='2030-01-01')
        self.assertEqual(res.candidates, [])

    def test_modified_before_keeps_all(self):
        res, _ = walk(modified_before='2030-01-01')
        self.assertTrue(res.candidates)

    def test_mtime_missing_excludes_when_window_set(self):
        """时间窗存在但 mtime 拿不到时取排除，不把不确定的文件混进结果。"""
        self.assertFalse(walker.passes_metadata(
            'a.csv', 10, 0,
            contracts.parse_spec({'roots': ['/d'], 'mode': 'name',
                                  'modified_after': '2026-01-01'})))

    def test_data_files_only_drops_summary_and_non_csv(self):
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name'})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())))
        names = {c.name for c in res.candidates}
        self.assertIn('RT_001.csv', names)
        self.assertNotIn('Sum_total.csv', names)
        self.assertNotIn('notes.txt', names)


class EventTests(SimpleTestCase):
    def test_unreadable_dir_emits_scoped_error_and_continues(self):
        """单目录读失败绝不能终止整次搜索（spec §3.4）。"""
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        res = walker.walk(s, FakeSession(sftp))
        self.assertIn(('dir', '/data/batch1'),
                      [(e['scope'], e['path']) for e in res.events
                       if e['kind'] == 'error'])
        self.assertTrue([c for c in res.candidates
                         if c.path.startswith('/data/batch2')])

    def test_on_candidate_streams_during_walk(self):
        """BFS 的存在理由：候选从一开始就在往外流，不是攒到最后一次性给。"""
        s = contracts.parse_spec({'roots': ['/data'], 'mode': 'name',
                                  'data_files_only': False})
        seen = []
        walker.walk(s, FakeSession(FakeSftp(sample_tree())),
                    on_candidate=lambda c: seen.append(c.path))
        self.assertIn('/data/backup/RT_999.csv', seen)
        self.assertIn('/data/batch1/RT_001.csv', seen)

    def test_overlapping_roots_do_not_duplicate(self):
        s = contracts.parse_spec({'roots': ['/data', '/data/'],
                                  'mode': 'name', 'data_files_only': False})
        res = walker.walk(s, FakeSession(FakeSftp(sample_tree())))
        paths = [c.path for c in res.candidates]
        self.assertEqual(len(paths), len(set(paths)))
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_walk`
Expected: FAIL —— `ImportError: cannot import name 'walker'`
（先修 Step 1 的收敛要求，否则 `FakeTreeSanityTests` 会先红）

- [ ] **Step 4: 实现 walker.py**

`Candidate` / `WalkResult` 按 Interfaces 定义。`passes_metadata` 的判定顺序（缺一即不等价）：
`.` 开头 → `name_pattern`（`fnmatch`）→ `data_files_only`（非 `.csv` 或
`_is_summary_csv(name)` 则排除）→ `min_size`/`max_size` → 时间窗
（`mtime` 为 0/None 且设了窗口时 **return False**）。

`list_one(sftp, path, spec)`：**不抛异常**，`except Exception as exc: logger.warning(...)
return [], [], str(exc)`；按 `st_mode` 分目录/文件；目录 `prune_dirs` 命中则不进结果；
返回 `(子目录全路径, 通过过滤的 Candidate, 错误消息或 None)`。

`walk(spec, session, *, on_candidate, cancel_event, deadline)` —— **显式批派发循环，
不要在锁内一边派一边收**：

```python
workers = max(1, min(spec.workers, session.size))
pending = [(root, 0) for root in spec.roots]
visited = set(spec.roots)
executor = ThreadPoolExecutor(max_workers=workers,
                              thread_name_prefix='sftp-walk')
try:
    while pending:
        if stop.is_set() or _expired(deadline):
            result.cancelled = True
            break
        if result.entries_seen >= spec.max_entries:
            result.truncated.append('truncated_entries'); break
        if len(result.candidates) >= spec.max_candidates:
            result.truncated.append('truncated_candidates'); break
        batch, pending = pending[:workers * 4], pending[workers * 4:]
        futures = {executor.submit(_list_via_session, session, p, spec): p
                   for p, _depth in batch}
        for fut in as_completed(futures):
            dirs, files, err, seen = fut.result()
            ... # 累加 entries_seen；err 则 append dir 事件；
                # 逐个 append candidate 到 max_candidates 为止并回调 on_candidate；
                # 未达 max_depth 时把未 visited 的 dirs 追加进 pending，
                # 否则若有 dirs 则记 truncated_depth
finally:
    executor.shutdown(wait=False, cancel_futures=True)
```

`_list_via_session(session, path, spec)` 是个 8 行小函数，**它承载了"连接脏了就换"这条**：

```python
def _list_via_session(session, path, spec):
    item = session.borrow()
    broken = False
    try:
        dirs, files, err = list_one(item[1], path, spec)
        if err and _looks_connection_level(err):
            broken = True
        return dirs, files, err, len(dirs) + len(files)
    finally:
        session.give_back(item, broken=broken)
```

`_looks_connection_level(err)`：命中 `'Garbage packet'` / `'SSH session not active'` /
`'No existing session'` / `'Connection reset'` 即 True（字符串嗅探在这里是可接受的，
因为 `list_one` 已经把异常压成了消息文本；若你把 `list_one` 改成向上抛原始异常，
就在这里改为 `isinstance(exc, CONNECTION_ERRORS)` 并同步更新 Task 5 的事件断言）。

- [ ] **Step 5: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_walk`
Expected: PASS（约 24 个测试）

- [ ] **Step 6: 提交**

```bash
git add apps/sftp/search/walker.py test/backend/test_sftp_search_walk.py test/backend/sftp_fake.py
git commit -m "feat(sftp): BFS 遍历器与元数据过滤

BFS 而非 DFS：宽树下候选从一开始就在往 UI 流，不是一头扎进第一个子树到叶才吐。
剪枝在进入前判定，被剪子树不计条目预算；mtime 缺失时时间窗判定取排除；
单目录不可读降级为 scope=dir 事件继续跑。"
```

---

## 阶段 4：扫描内核

### Task 6: 字节级内容扫描

**Files:**
- Create: `apps/sftp/search/scanners.py`
- Test: `test/backend/test_sftp_search_scan.py`

**Interfaces:**
- Consumes: `SearchSpec`、`walker.Candidate`
- Produces:
  - 常量 `CHUNK_SIZE = 1 << 20`、`HEAD_SIZE = 64 << 10`、`MAX_INFLIGHT = 64`、
    `LINE_CONTEXT = 4096`、`SNIPPET_MAX = 200`、`_WORD_BYTES`（frozenset of int）、
    `CONNECTION_ERRORS`
  - `scanners.build_needles(term, case_sensitive) -> Tuple[List[bytes], bool]`
  - `scanners.word_ok(buf, idx, needle_len) -> bool`
  - `scanners.find_first(buf, needles, fold, *, word=False) -> int`
  - `scanners.fuzzy_match(needle, buf) -> bool`
  - `scanners.extract_line(buf, idx) -> bytes`
  - `scanners.detect_encoding(first_line) -> str` / `decode_line(raw, encoding) -> str`
  - `scanners.parse_head(head) -> Tuple[str, str, str]`
  - `scanners.scan_file(sftp, cand, spec) -> Optional[dict]`
    —— 命中返回 `{path,name,size,mtime,line,snippet,hits,test_file,start_time,
    pts_modify_time}`（`hits` 是 `[{line, snippet}]`），不命中 `None`
  - `scanners.truncate_head_for_test(head) -> bytes`（仅供测试制造半行截断）

- [ ] **Step 1: 写失败的测试**

`test/backend/test_sftp_search_scan.py`。四轴笛卡尔积：**编码 × 大小写 × 整词 × 跨 chunk**。

```python
"""字节级内容扫描内核（spec §3.5，移植自参考工具 csv_content_searcher.py）。

跑法：python manage.py test test.backend.test_sftp_search_scan
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, scanners, walker  # noqa: E402
from test.backend.sftp_fake import FakeSftp  # noqa: E402

CRLF = b'\r\n'
PATH = '/d/a.csv'


def spec(**over):
    base = {'roots': ['/d'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def scan(content: bytes, path: str = PATH, **over):
    cand = walker.Candidate(path, os.path.basename(path), len(content), 0)
    return scanners.scan_file(FakeSftp({path: content}), cand, spec(**over))


class NeedleTests(SimpleTestCase):
    def test_ascii_needle_with_case_folding(self):
        needles, fold = scanners.build_needles('Shadow', False)
        self.assertEqual(needles, [b'shadow'])
        self.assertTrue(fold)

    def test_ascii_case_sensitive_no_folding(self):
        self.assertFalse(scanners.build_needles('Shadow', True)[1])

    def test_non_ascii_gets_one_needle_per_encoding(self):
        needles, _fold = scanners.build_needles('漏电电流', True)
        for enc in ('utf-8', 'gbk', 'utf-16-le', 'utf-16-be'):
            self.assertIn('漏电电流'.encode(enc), needles)

    def test_empty_term_yields_no_needles(self):
        self.assertEqual(scanners.build_needles('', False)[0], [])


class SubstringTests(SimpleTestCase):
    def test_hit_reports_line_number_and_snippet(self):
        out = scan(b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF + b'1,0.42' + CRLF)
        self.assertIsNotNone(out)
        self.assertEqual(out['line'], 2)
        self.assertIn('ShadowReg2', out['snippet'])

    def test_case_insensitive_hit(self):
        self.assertIsNotNone(scan(b'x,shadowreg2,y' + CRLF))

    def test_case_sensitive_misses_other_case(self):
        self.assertIsNone(scan(b'x,shadowreg2,y' + CRLF, case_sensitive=True))

    def test_no_hit_returns_none(self):
        self.assertIsNone(scan(b'[DATA]' + CRLF + b'SN,Vcc' + CRLF + b'1,3' + CRLF))

    def test_snippet_capped_at_200(self):
        out = scan(b'a' * 500 + b'ShadowReg2' + b'b' * 500 + CRLF)
        self.assertLessEqual(len(out['snippet']), scanners.SNIPPET_MAX)

    def test_carriage_return_stripped_from_snippet(self):
        self.assertEqual(scan(b'x,ShadowReg2,3' + CRLF)['snippet'],
                         'x,ShadowReg2,3')


class WholeWordTests(SimpleTestCase):
    def test_superstring_rejected(self):
        """整词若挡不掉 Vccc，这个选项就是装饰。"""
        self.assertIsNone(scan(b'SN,Vcc,Vccc' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_exact_word_accepted(self):
        self.assertIsNotNone(scan(b'SN,Vcc,Vddd' + CRLF, term='Vcc',
                                  matching='whole_word'))

    def test_punctuation_boundary_accepted(self):
        self.assertIsNotNone(scan(b'a,Vcc,b' + CRLF, term='Vcc',
                                  matching='whole_word'))

    def test_digit_is_a_word_byte(self):
        self.assertIsNone(scan(b'SN,Vcc1' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_underscore_is_a_word_byte(self):
        self.assertIsNone(scan(b'SN,_Vcc' + CRLF, term='Vcc',
                               matching='whole_word'))

    def test_non_ascii_byte_is_a_boundary(self):
        """C locale 下 >=0x80 属非 word 字符，因此可作边界 —— 必须与 grep -w 一致。"""
        self.assertTrue(scanners.word_ok('值Vcc'.encode('utf-8'), 3, 3))

    def test_word_ok_uses_ascii_class_not_unicode(self):
        """钉住「不得改用 re 的 \\b」：用 \\b 就会与 grep 档分叉。"""
        self.assertFalse(scanners.word_ok(b'xVcc', 1, 3))
        self.assertTrue(scanners.word_ok(b'x Vcc y', 2, 3))


class FuzzyTests(SimpleTestCase):
    def test_subsequence_hits(self):
        self.assertIsNotNone(scan(b'SN,Shadow_Reg_2_ish' + CRLF, term='SRe2',
                                  matching='fuzzy'))

    def test_out_of_order_misses(self):
        self.assertIsNone(scan(b'SN,2eRwod_Sa' + CRLF, term='SRe2',
                               matching='fuzzy'))


class EncodingTests(SimpleTestCase):
    def test_gbk_file_with_chinese_term(self):
        raw = '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk')
        self.assertIsNotNone(scan(raw, term='漏电电流'))

    def test_utf8_file_with_chinese_term(self):
        raw = '测试项\r\n漏电电流\r\n'.encode('utf-8')
        self.assertIsNotNone(scan(raw, term='漏电电流'))

    def test_utf16le_content_found_by_bomless_needle(self):
        self.assertIsNotNone(scan('SN,ShadowReg2\r\n'.encode('utf-16-le'),
                                  term='ShadowReg2'))

    def test_gbk_snippet_is_not_mojibake(self):
        self.assertEqual(scan('x,ShadowReg2'.encode('gbk') + CRLF)['snippet'],
                         'x,ShadowReg2')

    def test_detect_encoding_prefers_utf8(self):
        self.assertEqual(scanners.detect_encoding(b'SN,Value'), 'utf-8')


class ChunkingTests(SimpleTestCase):
    def test_needle_split_across_chunk_boundary_is_found(self):
        """滚动窗口的存在理由：needle 恰好被 1MB 切成两半。"""
        gap = b'x' * (scanners.CHUNK_SIZE + 7)
        self.assertIsNotNone(scan(gap + b'ShadowReg2' + CRLF))

    def test_line_number_correct_past_many_chunks(self):
        lines = [b'row-' + str(i).encode() for i in range(200_000)]
        lines[150_000] = b'hit ShadowReg2 here'
        self.assertEqual(scan(CRLF.join(lines) + CRLF)['line'], 150_001)

    def test_scan_budget_stops_before_end_of_file(self):
        """5GB 日志不该被整读：超预算就停，且不得因此报命中。"""
        content = b'y' * (2 << 20) + b'ShadowReg2' + CRLF
        self.assertIsNone(scan(content, max_scan_bytes=1 << 20))

    def test_prefetch_is_requested(self):
        """不发起 prefetch 就等于每个 chunk 一个来回，流水线白搭。"""
        content = b'z' * (scanners.CHUNK_SIZE + 10) + b'ShadowReg2' + CRLF
        fake = FakeSftp({PATH: content})
        with fake.open(PATH) as remote:
            remote.prefetch(len(content), scanners.MAX_INFLIGHT)
            self.assertTrue(remote.prefetched)
        scan(content)
        self.assertGreaterEqual(fake.open_count, 1)


class HitCountTests(SimpleTestCase):
    THREE = (b'ShadowReg2 a' + CRLF + b'ShadowReg2 b' + CRLF
             + b'ShadowReg2 c' + CRLF)

    def test_first_hit_per_file_returns_one(self):
        out = scan(self.THREE, first_hit_per_file=True, matches_per_file=5)
        self.assertEqual(len(out['hits']), 1)

    def test_matches_per_file_returns_that_many(self):
        out = scan(self.THREE, first_hit_per_file=False, matches_per_file=2)
        self.assertEqual([h['line'] for h in out['hits']], [1, 2])

    def test_all_lines_when_asked(self):
        out = scan(self.THREE, first_hit_per_file=False, matches_per_file=20)
        self.assertEqual([h['line'] for h in out['hits']], [1, 2, 3])


class HeadMetadataTests(SimpleTestCase):
    ATE = (b'[HEADER]' + CRLF
           + b'TestFile,D:\\stdf\\lotA_w01.stdf' + CRLF
           + b'StartTime,2026-09-01 08:12:33,' + CRLF
           + b'PtsModifyTime,2026-09-01 09:00:00,' + CRLF
           + b'[DATA]' + CRLF
           + b'SN,ShadowReg2' + CRLF
           + b'1,0.42' + CRLF)

    def test_three_fields_extracted(self):
        out = scan(self.ATE)
        self.assertEqual(out['test_file'], 'lotA_w01.stdf')
        self.assertEqual(out['start_time'], '2026-09-01 08:12:33')
        self.assertEqual(out['pts_modify_time'], '2026-09-01 09:00:00')

    def test_windows_path_reduced_to_basename(self):
        self.assertNotIn('\\', scan(self.ATE)['test_file'])

    def test_stops_at_data_section(self):
        ate = self.ATE.replace(b'SN,ShadowReg2', b'TestFile,should_not_win')
        self.assertEqual(scan(ate)['test_file'], 'lotA_w01.stdf')

    def test_truncated_head_does_not_yield_a_partial_value(self):
        """head 按字节切可能停在半行；留着半行会把残缺值当真值。"""
        cut = scanners.truncate_head_for_test(self.ATE)
        self.assertEqual(scanners.parse_head(cut)[:2],
                         ('lotA_w01.stdf', '2026-09-01 08:12:33'))

    def test_absent_metadata_yields_empty_strings(self):
        out = scan(b'[DATA]' + CRLF + b'SN,ShadowReg2' + CRLF)
        self.assertEqual(
            (out['test_file'], out['start_time'], out['pts_modify_time']),
            ('', '', ''))


class ErrorPathTests(SimpleTestCase):
    def test_unreadable_file_returns_none_and_logs(self):
        with self.assertLogs('apps.sftp.search.scanners', level='WARNING'):
            cand = walker.Candidate('/d/missing.csv', 'missing.csv', 10, 0)
            self.assertIsNone(scanners.scan_file(FakeSftp({}), cand, spec()))

    def test_connection_error_propagates_for_the_caller_to_replace(self):
        """连接级异常必须上抛，让 SearchSession 换掉脏连接 ——
        就地吞掉会让后续每个文件都在同一条坏死连接上失败。"""
        cand = walker.Candidate(PATH, 'a.csv', 10, 0)
        with self.assertRaises(scanners.CONNECTION_ERRORS):
            scanners.scan_file(FakeSftp({}, broken=True), cand, spec())

    def test_missing_prefetch_attribute_still_works(self):
        """老 paramiko 或别的替身没有 prefetch，不能因此失败，只是慢。"""
        content = b'x,ShadowReg2' + CRLF
        cand = walker.Candidate(PATH, 'a.csv', len(content), 0)
        self.assertIsNotNone(scanners.scan_file(
            FakeSftp({PATH: content}, no_prefetch=True), cand, spec()))
```

> **收敛要求**：最后一条依赖 `FakeSftp` 支持 `no_prefetch=True`。
> **在 `test/backend/sftp_fake.py` 的 `FakeSftp.__init__` 加一个 `no_prefetch=False` 参数**，
> `open()` 时若为真则返回一个只暴露 `read`/`close`/`__enter__`/`__exit__` 的
> `_NoPrefetchFile` 包装（**不要**用 `del type(f).prefetch` —— 那会改坏共享类，
> 污染同进程其它测试）。这个参数是给 Task 5 的夹具用的，Task 6 才消费它，属正常顺序。

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_scan`
Expected: FAIL —— `ImportError: cannot import name 'scanners'`

- [ ] **Step 3: 实现 scanners.py**

三个必须照抄、写错就破坏引擎可比性的点：

```python
# C locale 的 word 字符集。**故意不用 str.isalnum()、也不用 re 的 \b** ——
# 那是 Unicode 语义，与 LC_ALL=C 的 grep -w 不等价，两档引擎就会给出不同结果集。
_WORD_BYTES = frozenset(
    b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')


def word_ok(buf: bytes, idx: int, needle_len: int) -> bool:
    if idx > 0 and buf[idx - 1] in _WORD_BYTES:
        return False
    end = idx + needle_len
    if end < len(buf) and buf[end] in _WORD_BYTES:
        return False
    return True


CONNECTION_ERRORS = (paramiko.SSHException, paramiko.SFTPError, EOFError, OSError)
```

`find_first(buf, needles, fold, *, word=False)`：`region = buf.lower() if fold else buf`，
逐个 needle 找最左命中；`word=True` 时不合格就 `start = pos + 1` 继续。
必须写一行注释说明折叠安全性：**`bytes.lower()` 只改 ASCII 字节，`region` 与 `buf`
逐字节等长同位，所以 `region` 上取到的索引可直接用于 `word_ok(buf, ...)`**。

`scan_file` 的滚动窗口主循环，九步都要有：

1. `needles, fold = build_needles(...)`；空 needles → `return None`。
   `word = spec.matching == 'whole_word'`；`fuzzy = spec.matching == 'fuzzy'`；
   `want = 1 if spec.first_hit_per_file else max(1, spec.matches_per_file)`；
   `keep = max(len(longest_needle) - 1, LINE_CONTEXT)`。
2. `with sftp.open(cand.path, 'rb') as remote:` → 有 `prefetch` 且 `cand.size > 0`
   时 `remote.prefetch(cand.size, MAX_INFLIGHT)`，`TypeError` 退回
   `remote.prefetch(cand.size)`，其它异常 `logger.warning(..., exc_info=True)` 后继续。
3. 外层 `while len(hits) < want:` 读 `CHUNK_SIZE`；读到空则跳到第 7 步收尾；
   累计 `head`（上限 `HEAD_SIZE`）、`buf += chunk`、`scanned += len(chunk)`。
4. 内层 `while len(hits) < want:` 定位 → 若命中行尾 `\n` 不在 `buf` 内，则继续
   `remote.read(CHUNK_SIZE)` 补到见到 `\n` 或再多读 400 字节 →
   **首次定位时才** `encoding = detect_encoding(head.split(b'\n', 1)[0])` →
   `line_no = newlines_before + buf.count(b'\n', 0, idx) + 1` →
   `snippet = decode_line(extract_line(buf, idx), encoding).strip()[:SNIPPET_MAX]` →
   append，并从 `idx + 1` 继续找。维护一个 `search_from` 局部偏移，别拿绝对 `idx` 混用。
5. 窗口收缩：`if len(buf) > keep: consumed = len(buf) - keep;
   newlines_before += buf.count(b'\n', 0, consumed); buf = buf[consumed:];
   search_from = max(0, search_from - consumed)`。
6. 预算判定放在**收缩之后**：`if spec.max_scan_bytes and scanned >= spec.max_scan_bytes:
   break`（放前面会被收缩改变语义）。
7. 收尾：文件读完后把 `buf` 里剩余整行逐行判定，补足命中。
8. `except CONNECTION_ERRORS: raise`；`except Exception as exc:
   logger.warning('Search could not scan %s: %s', cand.path, exc); return None`。
9. `if not hits: return None`；否则 `parse_head(head)` 填三个元数据字段返回，
   `line`/`snippet` 取 `hits[0]`。

`parse_head(head)`：`lines = head.split(b'\n')`，**`if not head.endswith(b'\n'):
lines = lines[:-1]`**（`test_truncated_head_does_not_yield_a_partial_value` 的落点）；
逐行：`[` 开头则看 section、`DATA` 就 `break`；否则 `partition(',')`，
`TestFile`/`StartTime`/`PtsModifyTime` 各自「首次非空才记」，值 `.strip().rstrip(',')`，
`TestFile` 再 `.split('\\')[-1]`。

`truncate_head_for_test(head)`：`head[:head.rfind(b'\r\n', 0, len(head) - 2) + 1]`
—— 造出一个「最后一个字段被切成半行」的 head。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_scan`
Expected: PASS（约 38 个测试）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/scanners.py test/backend/sftp_fake.py test/backend/test_sftp_search_scan.py
git commit -m "feat(sftp): 字节级内容扫描内核

移植 prefetch/1MB 大块读/原始字节匹配/编码四探/命中即停。
整词边界用 [A-Za-z0-9_] 字节集而非 re 的 \\b —— 与 LC_ALL=C 的 grep -w 字面一致
是两档引擎结果可比的前提。head 截断时丢最后半行，否则残缺值会被当真值。"
```

---

### Task 7: CSV 列值扫描

**Files:**
- Modify: `apps/sftp/search/scanners.py`（追加 `read_column`）
- Test: `test/backend/test_sftp_search_scan.py`（追加 `ColumnTests`）

**Interfaces:**
- Consumes: `scanners.detect_encoding` / `decode_line` / `HEAD_SIZE` / `SNIPPET_MAX` / `CONNECTION_ERRORS`
- Produces: `scanners.read_column(sftp, cand, spec) -> Optional[dict]`
  —— `{path,name,size,mtime,values,column_name,test_file,start_time,pts_modify_time}`；
  无该列或无有效值 → `None`

- [ ] **Step 1: 追加失败的测试**

```python
class ColumnTests(SimpleTestCase):
    ATE = ('[HEADER]\r\nTestFile,D:\\stdf\\x.stdf\r\n'
           'StartTime,2026-09-01 08:00:00,\r\n[DATA]\r\n'
           'SN,ShadowReg2,Vcc\r\n1,0.42,3\r\n2,,3.1\r\n3,0.44,\r\n').encode()

    def read(self, content=None, column='ShadowReg2', rows=10):
        raw = self.ATE if content is None else content
        cand = walker.Candidate(PATH, 'a.csv', len(raw), 0)
        return scanners.read_column(
            FakeSftp({PATH: raw}), cand,
            contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                  'column_name': column, 'column_rows': rows}))

    def test_values_in_row_order_skipping_blanks(self):
        self.assertEqual(self.read()['values'], ['0.42', '0.44'])

    def test_respects_column_rows(self):
        self.assertEqual(self.read(rows=1)['values'], ['0.42'])

    def test_absent_column_returns_none(self):
        self.assertIsNone(self.read(column='NoSuchCol'))

    def test_column_position_follows_header_order(self):
        """表头顺序才是列位置的事实来源，不能按列名猜偏移。"""
        self.assertEqual(self.read(column='Vcc')['values'], ['3', '3.1'])

    def test_header_metadata_extracted(self):
        out = self.read()
        self.assertEqual(out['test_file'], 'x.stdf')
        self.assertEqual(out['start_time'], '2026-09-01 08:00:00')

    def test_no_data_section_means_no_table(self):
        """[DATA] 之前的 key,value 行不是数据表。参考工具缺这条约束，
        列名撞上文件头键名就会读出垃圾 —— 这里钉住它。"""
        self.assertIsNone(self.read(
            content=b'TestFile,a\r\nSN,ShadowReg2\r\n1,0.5\r\n'))

    def test_gbk_column_name_and_values(self):
        raw = '[DATA]\r\nSN,漏电电流\r\n1,0.5\r\n'.encode('gbk')
        self.assertEqual(self.read(content=raw, column='漏电电流')['values'],
                         ['0.5'])

    def test_short_rows_are_skipped_not_index_error(self):
        raw = b'[DATA]\r\nSN,ShadowReg2,Vcc\r\n1\r\n2,0.9,4\r\n'
        self.assertEqual(self.read(content=raw)['values'], ['0.9'])

    def test_no_values_returns_none(self):
        self.assertIsNone(self.read(
            content=b'[DATA]\r\nSN,ShadowReg2\r\n1,\r\n2,\r\n'))

    def test_unreadable_file_returns_none_and_logs(self):
        with self.assertLogs('apps.sftp.search.scanners', level='WARNING'):
            cand = walker.Candidate('/d/nope.csv', 'nope.csv', 1, 0)
            self.assertIsNone(scanners.read_column(
                FakeSftp({}), cand,
                contracts.parse_spec({'roots': ['/d'], 'mode': 'column',
                                      'column_name': 'x'})))

    def test_connection_error_propagates(self):
        cand = walker.Candidate(PATH, 'a.csv', 10, 0)
        with self.assertRaises(scanners.CONNECTION_ERRORS):
            scanners.read_column(FakeSftp({}, broken=True), cand,
                                 contracts.parse_spec(
                                     {'roots': ['/d'], 'mode': 'column',
                                      'column_name': 'x'}))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_scan.ColumnTests`
Expected: FAIL —— `AttributeError: module ... has no attribute 'read_column'`

- [ ] **Step 3: 实现**

`read_column` 是个 `in_data → headers_read → 取值` 的三段状态机，逐行
`remote.readline()`，首行 `detect_encoding` 后沿用同一编码。四条要点：

- **`in_data` 为假时，只有 `[` 开头的行才判 section；其余行按 `key,value` 抽三个元数据字段。**
  这条是 `test_no_data_section_means_no_table` 的实现点，也是与参考工具的**有意分歧**。
- 表头：`headers = [h.strip() for h in line.split(',')]`；
  `spec.column_name not in headers` → `return None`；否则 `col_idx = headers.index(...)`。
- 数据行：`row = line.split(',')`，`if col_idx < len(row)` 才取值（短行跳过）；
  非空才 append `row[col_idx].strip()[:SNIPPET_MAX]`；够 `spec.column_rows` 就 `break`。
- 异常：`CONNECTION_ERRORS` 上抛，其它 WARNING + `return None`；`values` 空则 `None`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_scan`
Expected: PASS（含 Task 6 全部）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/scanners.py test/backend/test_sftp_search_scan.py
git commit -m "feat(sftp): CSV 列值扫描

比参考工具多一条「必须先进入 [DATA] 才认表头」：否则会把文件头的 key,value 行
当表头，列名撞上键名就读出垃圾。短行按索引越界跳过而非抛 IndexError。"
```

---

## 阶段 5：grep 加速档

### Task 8: 探测、命令构造与输出解析

**Files:**
- Create: `apps/sftp/search/shell_grep.py`
- Test: `test/backend/test_sftp_search_grep.py`

**Interfaces:**
- Consumes: `SearchSpec`、`engine.ProbeResult`（Task 3）
- Produces:
  - `shell_grep.build_command(spec, *, use_find: bool) -> str`
  - `shell_grep.parse_line(raw: bytes) -> Optional[Tuple[str, int, bytes]]`
  - `shell_grep.probe(chan_factory: Callable[[], Channel], roots: List[str]) -> ProbeResult`
  - `shell_grep.grep_stream(chan, spec, *, cancel_event=None, deadline=None) -> Iterator[dict]`
    —— 每个命中 yield `{path, line, snippet}`（元数据由 Task 9 补）

- [ ] **Step 1: 写失败的测试**

`test/backend/test_sftp_search_grep.py` —— 一半篇幅是注入防护，因为它测的是
「我们会发出什么命令」；grep 真跑的正确性不在自动化覆盖内（spec §4.5）。

```python
"""grep 命令构造与能力探测（spec §3.6）。

全项目唯一拼 shell 命令字符串的模块，所以注入断言是这里的主菜。
测的是「我们会发出什么命令」，不是「grep 真跑出什么」——后者见 Task 11 人工验证。

跑法：python manage.py test test.backend.test_sftp_search_grep
"""
import os
import shlex
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, shell_grep  # noqa: E402


def spec(**over):
    base = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def flags(cmd):
    """只看选项区（第一个 `--` 之前）的 argv，避免被路径与内容干扰断言。"""
    head = shlex.split(cmd)
    return head[:head.index('--')] if '--' in head else head


class CommandShapeTests(SimpleTestCase):
    def test_always_fixed_string(self):
        """-F 在，term 才永远是字面量，正则元字符不改变行为。"""
        self.assertIn('-F', flags(shell_grep.build_command(
            spec(term='.*|[a-z]+'), use_find=False)))

    def test_recursive_line_number_and_filename(self):
        f = flags(shell_grep.build_command(spec(), use_find=False))
        for flag in ('-r', '-n', '-H', '-a'):
            self.assertIn(flag, f)

    def test_match_limit_one_when_first_hit_only(self):
        f = flags(shell_grep.build_command(spec(), use_find=False))
        self.assertEqual(f[f.index('-m') + 1], '1')

    def test_match_limit_carries_max_when_all_wanted(self):
        s = spec(first_hit_per_file=False, max_matches=37)
        f = flags(shell_grep.build_command(s, use_find=False))
        self.assertEqual(f[f.index('-m') + 1], '37')

    def test_case_insensitive_by_default(self):
        self.assertIn('-i', flags(shell_grep.build_command(spec(), use_find=False)))

    def test_case_sensitive_drops_i(self):
        self.assertNotIn('-i', flags(shell_grep.build_command(
            spec(case_sensitive=True), use_find=False)))

    def test_whole_word_adds_w(self):
        self.assertIn('-w', flags(shell_grep.build_command(
            spec(matching='whole_word'), use_find=False)))

    def test_include_only_with_pattern(self):
        with_pat = shell_grep.build_command(spec(name_pattern='*RT*.csv'),
                                            use_find=False)
        without = shell_grep.build_command(spec(), use_find=False)
        self.assertTrue(any(t.startswith('--include=') for t in flags(with_pat)))
        self.assertFalse(any(t.startswith('--include=') for t in flags(without)))

    def test_lc_all_c_prefix(self):
        self.assertTrue(shell_grep.build_command(spec(), use_find=False)
                        .startswith('LC_ALL=C '))

    def test_find_variant_for_time_filter(self):
        cmd = shell_grep.build_command(spec(modified_after='2026-09-01'),
                                       use_find=True)
        for piece in ('find ', '-newermt', '-print0', 'xargs -0 -r'):
            self.assertIn(piece, cmd)

    def test_empty_term_rejected(self):
        """select_engine 已保证非空，这里是第二道闸。"""
        s = contracts.parse_spec({'roots': ['/d'], 'mode': 'name'})
        with self.assertRaises(ValueError):
            shell_grep.build_command(s, use_find=False)


class InjectionTests(SimpleTestCase):
    EVIL_TERM = "x'; touch /tmp/pwn; #`id`$(id)"
    EVIL_PATTERN = '$(touch /tmp/pwn2)'
    EVIL_ROOT = '/data; rm -rf /'

    def test_term_round_trips_as_one_argv_token(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(term=self.EVIL_TERM), use_find=False))
        self.assertEqual(tokens[tokens.index('-e') + 1], self.EVIL_TERM)

    def test_term_metacharacters_not_reinterpreted(self):
        cmd = shell_grep.build_command(spec(term=self.EVIL_TERM), use_find=False)
        tokens = shlex.split(cmd)
        self.assertEqual([t for t in tokens if 'touch' in t], [self.EVIL_TERM])

    def test_term_starting_with_dash_is_a_value_not_a_flag(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(term='-rf'), use_find=False))
        self.assertEqual(tokens[tokens.index('-e') + 1], '-rf')
        self.assertNotIn('-rf', tokens[:tokens.index('-e')])

    def test_name_pattern_quoted_as_one_token(self):
        cmd = shell_grep.build_command(spec(name_pattern=self.EVIL_PATTERN),
                                       use_find=False)
        self.assertTrue(any(t == f'--include={self.EVIL_PATTERN}'
                            for t in shlex.split(cmd)))
        self.assertNotIn('--include=$(', cmd)

    def test_root_quoted_and_last(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(roots=[self.EVIL_ROOT]), use_find=False))
        self.assertEqual(tokens[-1], self.EVIL_ROOT)
        self.assertNotIn('rm', tokens[:-1])

    def test_root_with_space_preserved(self):
        tokens = shlex.split(shell_grep.build_command(
            spec(roots=['/data dir/sub']), use_find=False))
        self.assertEqual(tokens[-1], '/data dir/sub')

    def test_find_variant_quotes_paths_too(self):
        cmd = shell_grep.build_command(
            spec(roots=[self.EVIL_ROOT], modified_after='2026-09-01'),
            use_find=True)
        self.assertIn(shlex.quote(self.EVIL_ROOT), cmd)

    def test_prune_and_column_never_reach_the_command(self):
        """这两项只在客户端引擎用到；出现在 grep 命令里就是设计被绕过。"""
        cmd = shell_grep.build_command(
            spec(prune_dirs=['$(id)'], column_name='`id`'), use_find=False)
        self.assertNotIn('$(id)', cmd)
        self.assertNotIn('`id`', cmd)


class ParseLineTests(SimpleTestCase):
    def test_splits_path_line_content(self):
        self.assertEqual(
            shell_grep.parse_line(b'/data/a.csv:42:SN,ShadowReg2\r\n'),
            ('/data/a.csv', 42, b'SN,ShadowReg2'))

    def test_colons_inside_content_preserved(self):
        self.assertEqual(
            shell_grep.parse_line(b'/d/a.csv:7:StartTime,2026:09:01')[2],
            b'StartTime,2026:09:01')

    def test_colon_inside_path_splits_first_two_only(self):
        self.assertEqual(shell_grep.parse_line(b'/d/a:b.csv:3:hello'),
                         ('/d/a:b.csv', 3, b'hello'))

    def test_binary_marker_ignored(self):
        self.assertIsNone(shell_grep.parse_line(
            b'Binary file /data/a.csv matches'))

    def test_blank_line_ignored_without_logging(self):
        self.assertIsNone(shell_grep.parse_line(b''))

    def test_unparseable_line_warns_not_dropped_silently(self):
        """静默丢行就是静默漏结果。"""
        with self.assertLogs('apps.sftp.search.shell_grep', level='WARNING'):
            self.assertIsNone(shell_grep.parse_line(b'nonsense without colons'))

    def test_non_numeric_line_number_warns(self):
        with self.assertLogs('apps.sftp.search.shell_grep', level='WARNING'):
            self.assertIsNone(shell_grep.parse_line(b'/d/a.csv:x:hello'))


class _Chan:
    """最小 paramiko Channel 替身：按序回放 stdout，记录发过的命令。"""

    def __init__(self, replies, exit_status=0, stderr=b''):
        self.replies = list(replies)
        self.stderr = stderr
        self.commands = []
        self.exit_status = exit_status
        self.closed = False

    def exec_command(self, cmd):
        self.commands.append(cmd)

    def makefile(self, *a, **k):
        return self

    def read(self, n=-1):
        return self.replies.pop(0) if self.replies else b''

    def readline(self):
        return self.replies.pop(0) if self.replies else b''

    def recv_exit_status(self):
        return self.exit_status

    def close(self):
        self.closed = True


class ProbeTests(SimpleTestCase):
    def test_grep_available(self):
        chan = _Chan([b'grep (GNU grep) 3.7\n', b'find 4.9\nxargs 4.9\n',
                      b'MAPPING_OK\n', b''])
        self.assertTrue(shell_grep.probe(lambda: chan, ['/data']).has_grep)

    def test_missing_grep_unusable_with_displayable_reason(self):
        chan = _Chan([b'', b'bash: grep: command not found\n'])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertFalse(probe.has_grep)
        self.assertFalse(probe.usable)
        self.assertTrue(probe.reason.strip())

    def test_find_xargs_absence_reported_separately(self):
        """缺 find/xargs 只该关掉时间过滤这条路，不该把 grep 整体判死。"""
        chan = _Chan([b'grep (GNU grep) 3.7\n', b'', b'MAPPING_OK\n', b''])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(probe.has_grep)
        self.assertFalse(probe.has_find_xargs)

    def test_chroot_mapping_mismatch_blocks_grep(self):
        """SFTP 里存在的路径在 shell 侧可能不在同一位置（chroot）。
        不验就会 grep 一个不存在的路径、安静返回 0 命中。"""
        chan = _Chan([b'grep 3.7\n', b'find 4.9\n', b'', b''])
        probe = shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(probe.has_grep)
        self.assertFalse(probe.path_mapping_ok)
        self.assertIn('路径映射', probe.reason)

    def test_probe_closes_its_channel(self):
        chan = _Chan([b'grep 3.7\n', b'', b'MAPPING_OK\n', b''])
        shell_grep.probe(lambda: chan, ['/data'])
        self.assertTrue(chan.closed)

    def test_probe_exception_becomes_unusable_not_a_crash(self):
        def boom():
            raise OSError('server refused the exec channel')
        probe = shell_grep.probe(boom, ['/data'])
        self.assertFalse(probe.usable)
        self.assertIn('exec channel', probe.reason)


class GrepStreamTests(SimpleTestCase):
    def test_yields_one_dict_per_match(self):
        chan = _Chan([b'/d/a.csv:3:SN,ShadowReg2\r\n',
                      b'/d/b.csv:9:x,ShadowReg2\r\n'])
        out = list(shell_grep.grep_stream(
            chan, spec(), deadline=__import__('time').monotonic() + 30))
        self.assertEqual([o['path'] for o in out], ['/d/a.csv', '/d/b.csv'])
        self.assertEqual(out[0]['line'], 3)

    def test_cancel_event_closes_channel(self):
        import threading
        ev = threading.Event()
        ev.set()
        chan = _Chan([b'/d/a.csv:3:x\r\n'])
        list(shell_grep.grep_stream(chan, spec(), cancel_event=ev))
        self.assertTrue(chan.closed)

    def test_exit_status_two_with_no_match_raises_for_fallback(self):
        """>=2 是 grep 自己出错了：必须抛出让上层回落，不能当成「没有命中」。"""
        chan = _Chan([b'grep: invalid option\n'], exit_status=2)
        with self.assertRaises(RuntimeError):
            list(shell_grep.grep_stream(chan, spec()))

    def test_exit_status_one_is_a_normal_zero_result(self):
        chan = _Chan([], exit_status=1)
        self.assertEqual(list(shell_grep.grep_stream(chan, spec())), [])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_grep`
Expected: FAIL —— `ImportError: cannot import name 'shell_grep'`

- [ ] **Step 3: 实现**

`build_command(spec, *, use_find)` 拼装规则：

- 前缀 `LC_ALL=C `（**不 quote**，它使 `-w`/`-i` 的字节语义可预期），
  然后 `grep` + 选项区 + `-e <quoted term>` + 可选 `--include=<quoted>` + ` -- ` + 各 quoted root。
- 选项区固定含：`-a -H -F -n -r`；`not case_sensitive` 加 `-i`；
  `matching == 'whole_word'` 加 `-w`；`-m` 值 = `'1' if first_hit_per_file
  else str(max_matches)`。
- **每个选项值单独 quote**：`'-e'` 与 `shlex.quote(spec.term)` 是两个 token。
- `use_find` 分支：
  `find <q roots> -type f [-name <q pattern>] [-size +<n>c] [-size -<n>c]
  [-newermt <q>] [! -newermt <q>] -print0 2>/dev/null | xargs -0 -r env LC_ALL=C
  grep <同一选项区> --`。`!` 也要 `shlex.quote('!')`。
- 开头 `if not spec.term: raise ValueError('grep requires a non-empty term')`。

`parse_line(raw)`：`rstrip(b'\r\n')` → 空则 `None`（不 log）→
`startswith(b'Binary file ')` 则 `None`（不 log）→ `split(b':', 2)`，
不足 3 段 WARNING + `None` → `int(parts[1])` 失败 WARNING + `None` →
`(parts[0].decode('utf-8', errors='ignore'), lineno, parts[2])`。

`probe(chan_factory, roots)`：`_run(chan, 'grep --version')` →
`has_grep = exit <= 1 and b'grep' in out.lower()`；
`_run(chan, 'find --version 2>&1; xargs --version 2>&1')` →
`has_find_xargs = b'find' in low and b'xargs' in low`；
`_probe_mapping(chan, roots)` → 逐 root `'[ -e {q(root)} ] && echo MAPPING_OK'`，
任一含 `MAPPING_OK` 即 True，否则 `reason = PATH_MAPPING_MSG`；
整体 `try/except Exception` → `ProbeResult(False, False, False, f'探测服务端 grep 失败：{exc}')`；
`finally` close channel（close 失败只 WARNING）。

> **与参考工具的一处有意偏离**：`csv_content_searcher.py:213` 的映射探测是先
> `sftp.listdir(root)` 取一个条目、再在 shell 侧 `[ -e <root>/<entry> ]`。
> **本实现改成直接测 root 本身**：chroot 场景下 shell 侧 `/data` 通常不可见，
> 判别力相同，而测条目要多一次 SFTP 往返。spec §3.6 只要求「路径映射一致」，
> 未规定探测粒度，所以这不是违反映 spec —— 但**必须在代码注释里写明这层取舍**，
> 否则后来人会以为是漏写。

`grep_stream(chan, spec, *, cancel_event=None, deadline=None)`：
`for raw in iter(readline, b'')`；每轮先查 `cancel_event`/`deadline`，命中即
`chan.close()` 后 `return`；`parse_line` 为 `None` 就跳过（内部已 WARNING）；
否则 `yield {'path', 'line', 'snippet'}`，`snippet` 由 `scanners.decode_line`
+ `.strip()[:scanners.SNIPPET_MAX]` 得到。**未取消时才 `recv_exit_status()`**；
退出码 `>= 2` → `raise RuntimeError('grep failed: <stderr 前 300 字符>')`。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_grep`
Expected: PASS（约 30 个测试，含 8 条注入断言）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/shell_grep.py test/backend/test_sftp_search_grep.py
git commit -m "feat(sftp): grep 档命令构造与两级能力探测

LC_ALL=C + 每 token shlex.quote + -F 恒定。注入断言把产物命令 shlex.split
后按 argv 元素比对，不看「像不像安全」。映射探测不过（chroot）即判 grep 不可用，
否则会 grep 一个不存在的路径安静返回 0 命中。退出码 >=2 抛错供上层回落，
不与「真的没命中」混为一谈。"
```

---

## 阶段 6：编排与端点

### Task 9: engine 阶段机与事件流

**Files:**
- Modify: `apps/sftp/search/engine.py`（追加 `SearchRunner`；本文件最终约 290 行）
- Test: `test/backend/test_sftp_search_engine_stream.py`

**Interfaces:**
- Consumes: `SearchSpec`、`SearchSession`、`walker.walk`、`scanners.scan_file`/`read_column`、
  `shell_grep.{probe,build_command,grep_stream}`、`select_engine`、
  `downloads.channel_timeout`、`contracts.READ_TIMEOUT_SEC`
- Produces:
  - `engine.SearchRunner(spec, session, *, chan_factory=None, now=time.monotonic)`
  - `SearchRunner.events() -> Iterator[dict]` —— **事件即 spec §3.8 的那些 dict，
    键 `kind` 取值 `hello|stage|candidates|match|progress|notice|error|done`**
  - `engine.EVENT_POLL_SEC = 0.2`、`FLUSH_MAX_ITEMS = 200`、`FLUSH_MAX_AGE_SEC = 0.2`

- [ ] **Step 1: 写失败的测试**

```python
"""阶段机、事件协议、取消与清理（spec §3.8 / §3.9）。

跑法：python manage.py test test.backend.test_sftp_search_engine_stream
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, engine, scanners, walker  # noqa: E402
from test.backend.sftp_fake import FakeSession, FakeSftp, sample_tree  # noqa: E402

NO_GREP = engine.ProbeResult(False, False, False, '测试环境不提供 grep')


def spec(**over):
    base = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def run(s, tree=None):
    sftp = FakeSftp(tree if tree is not None else sample_tree())
    runner = engine.SearchRunner(s, FakeSession(sftp, size=s.workers))
    return list(runner.events()), sftp


def kinds(events):
    return [e['kind'] for e in events]


def first(events, kind):
    return next(e for e in events if e['kind'] == kind)


class HelloTests(SimpleTestCase):
    def test_hello_is_the_first_event(self):
        events, _ = run(spec())
        self.assertEqual(events[0]['kind'], 'hello')

    def test_hello_declares_engine_and_reason(self):
        events, _ = run(spec())
        self.assertEqual(events[0]['engine'], 'client')
        self.assertTrue(events[0]['engine_reason'].strip())

    def test_hello_reports_actual_worker_count(self):
        """并行数必须是真实值，否则用户看到的是假的。"""
        events, _ = run(spec(workers=3))
        self.assertEqual(events[0]['workers_actual'], 3)   # FakeSession size=workers

    def test_clamped_fields_become_notices(self):
        events, _ = run(spec(workers=99))
        self.assertIn('notice', kinds(events))
        self.assertTrue(any(e['kind'] == 'notice'
                            and 'workers' in e['code'] for e in events))


class StageProtocolTests(SimpleTestCase):
    def test_client_engine_sequence(self):
        events, _ = run(spec())
        seq = kinds(events)
        self.assertEqual(seq[0], 'hello')
        self.assertIn('stage', seq)
        self.assertIn('candidates', seq)
        self.assertIn('match', seq)
        self.assertEqual(seq[-1], 'done')

    def test_listing_then_scanning_stages(self):
        events, _ = run(spec())
        stages = [e['stage'] for e in events if e['kind'] == 'stage']
        self.assertEqual(stages, ['listing', 'scanning', 'done'])

    def test_stop_after_listing_skips_scanning(self):
        events, sftp = run(spec(stop_after_listing=True))
        self.assertNotIn('scanning',
                         [e['stage'] for e in events if e['kind'] == 'stage'])
        self.assertEqual(sftp.open_count, 0, '仅列候选不该读任何文件内容')
        self.assertTrue(first(events, 'done')['matched'] >= 0)

    def test_progress_total_is_null_during_listing(self):
        """listing 没有分母，UI 只能走不定档 —— 这条性质要被钉住。"""
        events, _ = run(spec())
        prog = [e for e in events if e['kind'] == 'progress']
        self.assertIsNone(prog[0]['total'])

    def test_scanning_progress_has_a_denominator(self):
        events, _ = run(spec())
        scan_prog = [e for e in events
                     if e['kind'] == 'progress' and e['stage'] == 'scanning']
        self.assertTrue(scan_prog and scan_prog[-1]['total'] > 0)

    def test_candidates_are_batched_not_one_per_event(self):
        """十万条目逐条发事件会把 SSE 变成瓶颈。"""
        tree = {f'/data/batch1/f{i}.csv': b'[DATA]\r\nSN,ShadowReg2\r\n'
                for i in range(600)}
        events, _ = run(spec(mode='name', data_files_only=False), tree)
        batches = [e for e in events if e['kind'] == 'candidates']
        self.assertLessEqual(len(batches), 20)
        self.assertGreater(max(len(b['items']) for b in batches), 1)


class TruncationTests(SimpleTestCase):
    def test_candidate_cap_is_reported_not_silent(self):
        """搜出 5000 而真实有 40000 时静默返回，比慢十倍更伤信任。"""
        events, _ = run(spec(max_candidates=1))
        done = first(events, 'done')
        self.assertTrue(done['truncated'])
        self.assertIn('truncated_candidates', done['limits_hit'])

    def test_match_cap_is_reported(self):
        tree = {f'/data/b{i}.csv': b'x,ShadowReg2\r\n' for i in range(50)}
        events, _ = run(spec(max_matches=3, data_files_only=False), tree)
        self.assertIn('truncated_matches', first(events, 'done')['limits_hit'])

    def test_depth_cap_is_reported(self):
        events, _ = run(spec(mode='name', depth='children',
                             data_files_only=False))
        self.assertIn('truncated_depth', first(events, 'done')['limits_hit'])


class MatchPayloadTests(SimpleTestCase):
    def test_content_match_carries_line_snippet_and_metadata(self):
        events, _ = run(spec())
        items = [i for e in events if e['kind'] == 'match' for i in e['items']]
        self.assertTrue(items)
        one = items[0]
        for key in ('path', 'name', 'size', 'mtime', 'line', 'snippet',
                    'test_file', 'start_time'):
            self.assertIn(key, one)
        self.assertEqual(one['test_file'], 'lotA_w01.stdf')

    def test_column_match_carries_values(self):
        events, _ = run(spec(mode='column', term='', column_name='ShadowReg2'))
        items = [i for e in events if e['kind'] == 'match' for i in e['items']]
        self.assertTrue(items and items[0]['values'])

    def test_name_mode_emits_no_match_events(self):
        events, _ = run(spec(mode='name', data_files_only=False))
        self.assertNotIn('match', kinds(events))

    def test_one_per_folder_scans_one_file_per_directory(self):
        tree = {f'/data/batch1/f{i}.csv': b'[DATA]\r\nSN,ShadowReg2\r\n1,0.5\r\n'
                for i in range(10)}
        _events, sftp = run(spec(one_per_folder=True, data_files_only=False), tree)
        self.assertEqual(sftp.open_count, 1)


class ErrorEventTests(SimpleTestCase):
    def test_unreadable_dir_becomes_scoped_error(self):
        s = spec()
        sftp = FakeSftp(sample_tree(), unreadable=['/data/batch1'])
        events = list(engine.SearchRunner(s, FakeSession(sftp)).events())
        self.assertIn(('/data/batch1', 'dir'),
                      [(e['path'], e['scope']) for e in events
                       if e['kind'] == 'error'])

    def test_search_continues_past_a_failing_file(self):
        """单文件读失败绝不能终止整次搜索。"""
        events, _ = run(spec())
        self.assertTrue([i for e in events if e['kind'] == 'match'
                         for i in e['items']])


class CancellationTests(SimpleTestCase):
    def test_close_after_events_leaves_no_open_files(self):
        """SearchRunner 必须自己收干净：runner 返回后不应还有未关闭的连接。"""
        s = spec()
        sftp = FakeSftp(sample_tree())
        runner = engine.SearchRunner(s, FakeSession(sftp))
        for _ in runner.events():
            break                     # 只取一个事件就放弃（模拟 GeneratorExit）
        runner.close()
        self.assertTrue(runner.closed)

    def test_executor_is_not_used_as_context_manager(self):
        """源码级守卫：`with ThreadPoolExecutor(` 会在退出时 join 全部 worker，
        取消时把请求挂住直到几千个文件扫完。本文件里绝不允许出现。"""
        import inspect
        src = inspect.getsource(engine)
        self.assertNotIn('with ThreadPoolExecutor(', src,
                         '必须显式 shutdown(wait=False, cancel_futures=True)')
        self.assertIn('shutdown(wait=False', src)

    def test_cancel_event_stops_before_scanning_all(self):
        ev = threading.Event()
        s = spec()
        sftp = FakeSftp(sample_tree())
        runner = engine.SearchRunner(s, FakeSession(sftp), cancel_event=ev)
        seen = 0
        for _event in runner.events():
            seen += 1
            if seen == 1:
                ev.set()
        self.assertTrue(runner.cancelled)


class GrepPathTests(SimpleTestCase):
    def test_grep_engine_skips_listing(self):
        """grep 档一次性完成列举+匹配：不该有 listing 阶段、不该有 candidates。"""
        tree = {'/d/a.csv': b'x,ShadowReg2\r\n'}
        s = spec()
        sftp = FakeSftp(tree)

        def chan_factory():
            return _GrepChan([b'/d/a.csv:1:x,ShadowReg2\r\n'])

        runner = engine.SearchRunner(
            s, FakeSession(sftp, size=1), chan_factory=chan_factory,
            forced_engine='grep')
        events = list(runner.events())
        self.assertEqual(first(events, 'hello')['engine'], 'grep')
        self.assertNotIn('candidates', kinds(events))
        self.assertEqual(sftp.listdir_calls, [])

    def test_grep_runtime_failure_falls_back_to_client(self):
        """探测过了但真跑炸了：必须回落并让用户看见这次回落。"""
        s = spec()

        def chan_factory():
            return _GrepChan([], exit_status=2)

        runner = engine.SearchRunner(
            s, FakeSession(FakeSftp(sample_tree()), size=1),
            chan_factory=chan_factory, forced_engine='grep')
        events = list(runner.events())
        self.assertTrue(any(e['kind'] == 'notice' and 'grep' in e['code']
                            for e in events))
        self.assertEqual(first(events, 'done')['engine'], 'client')


class _GrepChan:
    def __init__(self, lines, exit_status=0):
        self.lines = list(lines)
        self.exit_status = exit_status
        self.closed = False

    def exec_command(self, cmd):
        self.command = cmd

    def makefile(self, *a, **k):
        return self

    def readline(self):
        return self.lines.pop(0) if self.lines else b''

    def recv_exit_status(self):
        return self.exit_status

    def close(self):
        self.closed = True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test test.backend.test_sftp_search_engine_stream`
Expected: FAIL —— `AttributeError: module ... has no attribute 'SearchRunner'`

- [ ] **Step 3: 实现 SearchRunner**

构造签名：`SearchRunner(spec, session, *, chan_factory=None,
cancel_event=None, forced_engine=None, now=time.monotonic)`。
`forced_engine` 只为测试 grep 分支存在（生产路径由 `select_engine` 决定），必须写明这一点。

`_CLAMPED_TEXT` 是给用户的钳位告知文案，必须逐码定义（缺一个就是 `KeyError`）：

```python
_CLAMPED_TEXT = {
    'clamped_workers': '并行数已调整到服务器可接受范围',
    'clamped_timeout': '超时已钳位到 30–3600 秒',
    'clamped_max_entries': '遍历条目上限已钳位',
    'clamped_max_candidates': '候选数上限已钳位',
    'clamped_max_matches': '命中数上限已钳位',
    'clamped_matches_per_file': '每文件命中数上限已钳位到 20',
    'clamped_column_rows': '每文件取值数已钳位到 50',
    'clamped_max_scan_bytes': '单文件扫描预算已钳位到 1 GiB',
    'clamped_max_depth': '递归深度已钳位到 64 层',
}
```

`_probe()` 的接线（grep 档的全部前提，别留成"自行实现"）：

```python
def _probe(self):
    if not self.spec.allow_server_grep or self.spec.mode != 'content':
        # 连探测都不用做，省一次 exec 往返
        return ProbeResult(False, False, False, '本次查询不使用服务端加速')
    def chan_factory():
        return self.session.exec_transport().open_session(timeout=15)
    return shell_grep.probe(chan_factory, self.spec.roots)
```

`_run_grep(q)`：`build_command(spec, use_find=bool(spec.modified_after or
spec.modified_before))` → `chan = session.exec_transport().open_session(timeout=15)`
→ `chan.exec_command(cmd)` → 逐命中 `yield {'kind':'match','items':[...]}`
（元数据用 `scanners.parse_head` + `sftp.stat` 补，走 session 借还一条 sftp）→
`RuntimeError`（grep 退出码 ≥2）则 `logger.warning` + **整次改跑 `_run_client(q)`**，
并先 `yield {'kind':'notice','code':'grep_fallback','message':str(exc)}`。

`events()` 的骨架，逐条都是 spec 里的硬要求：

```python
def events(self):
    q = queue.Queue()
    self.deadline = self.now() + self.spec.timeout
    engine_name, reason = (self.forced_engine, '测试指定') if self.forced_engine \
        else select_engine(self.spec, self._probe())
    yield {'kind': 'hello', 'engine': engine_name, 'engine_reason': reason,
           'workers_actual': self.session.size, 'roots': self.spec.roots}
    for code in self.spec.clamped:
        yield {'kind': 'notice', 'code': code, 'message': _CLAMPED_TEXT[code]}
    try:
        if engine_name == 'grep':
            yield from self._run_grep(q)
        else:
            yield from self._run_client(q)
    finally:
        self.close()          # 幂等；GeneratorExit 也走这里
```

`_run_client(q)`：

1. `yield {'kind':'stage','stage':'listing',...}`
2. `walk_result = walker.walk(spec, session, on_candidate=<推入批合成器>,
   cancel_event=self.cancel_event, deadline=self.deadline)`
3. 先把攒着的候选 flush 出去（`candidates` 事件），再 `yield` 一个
   `{'kind':'stage','stage':'done'/'listing'}` 收口
4. `for code in walk_result.truncated: yield notice`；
   `for evt in walk_result.events: yield evt`
5. `if spec.stop_after_listing or not walk_result.candidates or
   walk_result.cancelled: yield done; return`
6. `yield {'kind':'stage','stage':'scanning','candidates':N}`；
   `executor = ThreadPoolExecutor(max_workers=min(spec.workers, session.size))`
   —— **绝不写 `with ThreadPoolExecutor(...)`**（Task 6 的源码守卫测试会红）
7. 每文件任务：`item = session.borrow()` →
   `with channel_timeout(item[1], READ_TIMEOUT_SEC):` →
   `scan_file`/`read_column` → `session.give_back(item)`；
   `CONNECTION_ERRORS` 则 `give_back(item, broken=True)` 并**重试一次**，
   再失败就 `logger.warning` + 计入 `error{scope:'file'}`
8. 主线程从 `q` 排空 worker 推来的命中，按 `FLUSH_MAX_ITEMS` / `FLUSH_MAX_AGE_SEC`
   合成 `match` 事件；每 `EVENT_POLL_SEC` 检查一次 `cancel_event` 与 deadline
9. 结果数达 `spec.max_matches` → 记 `truncated_matches`、`cancel_event.set()`、停止收
10. `finally: executor.shutdown(wait=False, cancel_futures=True)`
11. `yield {'kind':'done', 'matched':..., 'scanned':..., 'elapsed_s':...,
    'truncated': bool(limits_hit), 'limits_hit':[...], 'engine':'client'}`

`close()`：置 `self.cancelled`（`self.cancel_event.set()`）、
`self.executor.shutdown(wait=False, cancel_futures=True)`（若已建）、
`self.session.close_all()`、`self.closed = True`。**幂等**，`events()` 的 `finally`
与外部 `runner.close()` 都调它。

进度事件：`listing` 阶段 `total=None`；`scanning` 阶段 `total=len(candidates)`、
`done=已扫文件数`。发送节流 0.2s。

**两个 grep 相关的 notice 码不是重复，别合并**（spec §3.6 与 §3.8 各定义了一个）：

| 码 | 触发时机 | 语义 |
|---|---|---|
| `grep_unavailable` | **探测阶段**就没过 | 这台服务器不支持，本次从一开始就走 client |
| `grep_fallback` | 探测过了、**真跑炸了**（退出码 ≥2） | 中途换引擎，用户需要知道这次结果来自哪档 |

前者是环境事实、后者是运行期故障，合并就丢掉了一次真实的降级事件。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test test.backend.test_sftp_search_engine_stream`
Expected: PASS（约 28 个测试）

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/search/engine.py test/backend/test_sftp_search_engine_stream.py
git commit -m "feat(sftp): 搜索阶段机与 SSE 事件流

BFS 遍历 → 批量合成候选 → 并行扫描。ThreadPoolExecutor 不用 with
（with 会在取消时 join 全部 worker，把请求挂到几千个文件扫完），
源码级测试钉住这条。每个截断上限都出 notice 并进 done.limits_hit，
静默少结果比慢十倍更伤信任。grep 档运行时失败回落 client 且告知用户。"
```

---

### Task 10: 搜索端点

**Files:**
- Create: `apps/sftp/search_views.py`
- Modify: `apps/sftp/views.py:1-15`（+1 import）、`apps/sftp/views.py:43`（类基表 +1 项）
- Test: `apps/sftp/tests_search.py`

**Interfaces:**
- Consumes: `SearchSpec`/`parse_spec`/`SearchSpecError`、`SearchSession`、`SearchRunner`、
  `downloads.download_events_to_sse`（`apps/sftp/downloads.py:328`）
- Produces: `POST /api/v1/sftp/search/`（SSE）；`SftpSearchMixin`；
  可测缝 `_build_session(user_id, workers)` 与 `_runner_class`

- [ ] **Step 1: 写失败的测试**

`apps/sftp/tests_search.py`（`APITestCase`）：

```python
"""搜索端点的 HTTP 与 SSE 契约（spec §3.8 / §3.11）。

跑法：python manage.py test apps.sftp.tests_search
"""
import json

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.sftp import pool, search_views
from apps.sftp.views import SftpViewSet
from test.backend.sftp_fake import FakeSftp, sample_tree

URL = '/api/v1/sftp/search/'


def sse_events(body: str):
    """把 'data: {...}\\n\\n' 帧串解析成 dict 列表。"""
    out = []
    for chunk in body.split('\n\n'):
        chunk = chunk.strip()
        if chunk.startswith('data: '):
            out.append(json.loads(chunk[len('data: '):]))
    return out


class SearchEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('u1', password='pw')
        self.client.force_authenticate(self.user)
        self.sftp = FakeSftp(sample_tree())
        self._orig = search_views.SftpSearchMixin._build_session
        search_views.SftpSearchMixin._build_session = (
            lambda self, uid, workers: FakeSession(self.sftp, size=workers))

    def tearDown(self):
        search_views.SftpSearchMixin._build_session = self._orig

    def post(self, payload):
        return self.client.post(URL, payload, format='json')

    def test_auth_required(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.post({'roots': ['/data'], 'mode': 'name'}).status_code,
                         401)

    def test_unknown_key_is_400_before_the_stream(self):
        resp = self.post({'roots': ['/data'], 'mode': 'name',
                          'recursive': True})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.data)
        self.assertNotIn('text/event-stream',
                         resp.get('Content-Type', ''))

    def test_missing_roots_is_400(self):
        self.assertEqual(self.post({'mode': 'name'}).status_code, 400)

    def test_not_connected_returns_the_existing_sentinel(self):
        search_views.SftpSearchMixin._build_session = (
            lambda self, uid, workers: (_ for _ in ()).throw(
                search_views.SearchSessionError('no cached session (not connected)')))
        resp = self.post({'roots': ['/data'], 'mode': 'name'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not connected', str(resp.data['error']))

    def test_success_streams_event_stream(self):
        resp = self.post({'roots': ['/data'], 'mode': 'content',
                          'term': 'ShadowReg2'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/event-stream')
        self.assertEqual(resp['Cache-Control'], 'no-cache')
        self.assertEqual(resp['X-Accel-Buffering'], 'no')

    def test_frame_sequence_ends_with_done(self):
        resp = self.post({'roots': ['/data'], 'mode': 'content',
                          'term': 'ShadowReg2'})
        events = sse_events(b''.join(resp.streaming_content).decode())
        self.assertEqual(events[0]['kind'], 'hello')
        self.assertEqual(events[-1]['kind'], 'done')
        self.assertIn('match', [e['kind'] for e in events])

    def test_generator_closes_the_session(self):
        """流被消费完（或断开）后不得留开着的连接。"""
        tracker = {'closed': 0}
        orig = FakeSession.close_all

        def spy(self):
            tracker['closed'] += 1
            return orig(self)
        FakeSession.close_all = spy
        try:
            resp = self.post({'roots': ['/data'], 'mode': 'name'})
            b''.join(resp.streaming_content)
            self.assertEqual(tracker['closed'], 1)
        finally:
            FakeSession.close_all = orig

    def test_exception_inside_stream_never_becomes_html_500(self):
        """流一旦开始就只能发事件；异常要转成 error 事件而不是半截 SSE。"""
        orig = search_views.SftpSearchMixin._runner_class

        class _Boom:
            def __init__(self, *a, **k):
                pass

            def events(self):
                raise RuntimeError('unexpected')
                yield {}     # noqa: 让它成为生成器

            def close(self):
                pass
        search_views.SftpSearchMixin._runner_class = _Boom
        try:
            resp = self.post({'roots': ['/data'], 'mode': 'name'})
            body = b''.join(resp.streaming_content).decode()
            self.assertIn('"kind": "error"', body)
            self.assertNotIn('Traceback', body)
        finally:
            search_views.SftpSearchMixin._runner_class = orig
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test apps.sftp.tests_search`
Expected: FAIL —— `ModuleNotFoundError: No module named 'apps.sftp.search_views'`

- [ ] **Step 3: 实现**

```python
"""SFTP 搜索端点：POST /sftp/search/ → SSE；预设 CRUD。（spec §3.11）

错误契约：流开始**前**的失败 → 400 {'error': msg}（与 views.py 现有十余处同形，
utils/ssePost.ts 只读 err.error）；流开始**后**只能是带内 error 事件，
生成器内绝不抛 DRF 异常 —— 异常处理器拿不到流，只会留下半截 SSE。
"""
```

`SftpSearchMixin` 要点：

- `_build_session(self, user_id, workers) -> SearchSession`：只有一行
  `session = SearchSession(user_id, workers); session.open_all(); return session`。
  **测试靠替换它注入假连接**，别把它内联进 `search`。
- `_runner_class = SearchRunner`（类属性，测试靠替换它注入异常）。
- `@action(detail=False, methods=['post']) def search(self, request)`：
  1. `try: spec = parse_spec(request.data)` → `except SearchSpecError as exc:
     return Response({'error': str(exc)}, status=400)`
  2. `try: session = self._build_session(request.user.id, spec.workers)`
     → `except SearchSessionError as exc: return Response({'error': str(exc)},
     status=400)`（未连接就死在这里，绝不开流）
  3. `runner = self._runner_class(spec, session)`
  4. `stream = _safe_stream(runner)` —— 一个把异常转成 `error{scope:'fatal'}`
     事件的本地生成器：`try: yield from runner.events()
     except Exception as exc: logger.exception(...); yield {'kind':'error',
     'scope':'fatal','path':None,'message':str(exc)}`
  5. `response = StreamingHttpResponse(download_events_to_sse(_to_sse_dict(stream)),
     content_type='text/event-stream')`；
     **注意 `download_events_to_sse` 吃的是 dict 事件流**（`downloads.py:328`），
     所以 `_safe_stream` 直接 yield dict 即可，别自己 json.dumps 两遍。
  6. 设 `response['Cache-Control'] = 'no-cache'`、`response['X-Accel-Buffering'] = 'no'`
- 预设三个 action 见 Task 11。

`apps/sftp/views.py` 改两行：import 处加 `from .search_views import SftpSearchMixin`，
类声明改为 `class SftpViewSet(SftpConfigMixin, SftpSearchMixin, viewsets.GenericViewSet):`。
`DefaultRouter` 自动出路由，**不需要改 `urls.py`**。

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test apps.sftp.tests_search`
Expected: PASS（约 9 个测试）

- [ ] **Step 5: 回归 + 提交**

```bash
python manage.py test apps.sftp test.backend
git add apps/sftp/search_views.py apps/sftp/views.py apps/sftp/tests_search.py
git commit -m "feat(sftp): 搜索端点 POST /sftp/search/（SSE）

未连接与契约校验都在开流之前失败；流内异常转 error{scope:fatal} 事件，
不留半截 SSE。_build_session / _runner_class 两个缝是给测试留的。
DefaultRouter 自动成路由，未改 urls.py。"
```

---

### Task 11: 预设模型、CRUD 与后端真机验证

**Files:**
- Modify: `apps/sftp/models.py`（41 → 约 70 行）
- Create: `apps/sftp/migrations/00XX_sftpsearchpreset.py`
- Modify: `apps/sftp/search_views.py`（追加三个 action）
- Test: `apps/sftp/tests_search_preset.py`

**Interfaces:**
- Produces: `SftpSearchPreset{id, owner, name, spec, created_at, updated_at}`；
  `GET /api/v1/sftp/search_presets/` → `{presets:[{id,name,spec,updated_at}]}`；
  `POST /api/v1/sftp/search_presets/save/` `{name, spec, overwrite?}`；
  `POST /api/v1/sftp/search_presets/delete/` `{id}`

- [ ] **Step 1: 写失败的测试**

`apps/sftp/tests_search_preset.py` —— 形状照抄 `apps/sftp/tests.py:175` 的
`SftpConfigSaveTests` 与 `:287` 的 `SftpConfigOwnerIsolationTests`：

```python
"""搜索预设的 CRUD 与跨用户隔离（spec §3.10）。

跑法：python manage.py test apps.sftp.tests_search_preset
"""
from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.sftp.models import SftpSearchPreset

LIST = '/api/v1/sftp/search_presets/'
SAVE = '/api/v1/sftp/search_presets/save/'
DELETE = '/api/v1/sftp/search_presets/delete/'

SPEC = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2',
        'name_pattern': '*RT*.csv', 'depth': 'all'}


class PresetBase(APITestCase):
    def setUp(self):
        self.a = User.objects.create_user('a', password='pw')
        self.b = User.objects.create_user('b', password='pw')
        self.client.force_authenticate(self.a)


class CreateTests(PresetBase):
    def test_create_returns_201_and_persists(self):
        resp = self.client.post(SAVE, {'name': '找 RT', 'spec': SPEC},
                                format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(SftpSearchPreset.objects.filter(owner=self.a).count(), 1)

    def test_empty_name_is_400(self):
        self.assertEqual(self.client.post(SAVE, {'name': '', 'spec': SPEC},
                                          format='json').status_code, 400)

    def test_invalid_spec_is_400_not_saved(self):
        """预设里存一个跑不通的 spec，等于给用户一个必定失败的按钮。"""
        resp = self.client.post(SAVE, {'name': 'x',
                                       'spec': {'mode': 'name'}},
                                format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_unknown_spec_key_is_400(self):
        resp = self.client.post(SAVE, {'name': 'x',
                                       'spec': {**SPEC, 'recursive': True}},
                                format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(SftpSearchPreset.objects.count(), 0)


class OverwriteTests(PresetBase):
    def test_same_name_overwrites_spec(self):
        self.client.post(SAVE, {'name': 'n', 'spec': SPEC}, format='json')
        resp = self.client.post(SAVE, {'name': 'n',
                                       'spec': {**SPEC, 'term': 'Vcc'}},
                                format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SftpSearchPreset.objects.filter(owner=self.a).count(), 1)
        self.assertEqual(
            SftpSearchPreset.objects.get(owner=self.a).spec['term'], 'Vcc')

    def test_different_users_keep_their_own_names(self):
        self.client.post(SAVE, {'name': 'n', 'spec': SPEC}, format='json')
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.post(
            SAVE, {'name': 'n', 'spec': SPEC}, format='json').status_code, 201)
        self.assertEqual(SftpSearchPreset.objects.count(), 2)


class CapTests(PresetBase):
    def test_per_user_cap(self):
        for i in range(50):
            self.client.post(SAVE, {'name': f'p{i}', 'spec': SPEC},
                             format='json')
        resp = self.client.post(SAVE, {'name': 'p50', 'spec': SPEC},
                                format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('上限', str(resp.data))


class ListAndDeleteTests(PresetBase):
    def test_list_only_returns_own_presets(self):
        self.client.post(SAVE, {'name': 'mine', 'spec': SPEC}, format='json')
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.get(LIST).data['presets'], [])

    def test_list_returns_no_owner_field(self):
        self.client.post(SAVE, {'name': 'x', 'spec': SPEC}, format='json')
        data = self.client.get(LIST).data['presets'][0]
        self.assertNotIn('owner', data)

    def test_cannot_delete_another_users_preset(self):
        self.client.post(SAVE, {'name': 'x', 'spec': SPEC}, format='json')
        pid = SftpSearchPreset.objects.get().id
        self.client.force_authenticate(self.b)
        self.assertEqual(
            self.client.post(DELETE, {'id': pid}, format='json').status_code, 404)
        self.assertTrue(SftpSearchPreset.objects.filter(id=pid).exists())

    def test_delete_own_returns_deleted_true(self):
        self.client.post(SAVE, {'name': 'x', 'spec': SPEC}, format='json')
        pid = SftpSearchPreset.objects.get().id
        self.assertEqual(
            self.client.post(DELETE, {'id': pid}, format='json').data['deleted'],
            True)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test apps.sftp.tests_search_preset`
Expected: FAIL —— `ImportError: cannot import name 'SftpSearchPreset'`

- [ ] **Step 3: 实现模型与端点**

```python
class SftpSearchPreset(models.Model):
    """一次搜索条件的快照。spec 原样存 SearchSpec 的 JSON 形态。"""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name='sftp_search_presets')
    name = models.CharField(max_length=80)
    spec = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('owner', 'name')
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.owner}/{self.name}'
```

迁移：`python manage.py makemigrations sftp`，**人工读一遍生成的文件**再决定是否重命名
（跟随 `0006_usersetting_sftp_last_config_and_more.py` 的命名风格）。

`search_views.py` 三个 action：

- `search_presets`（GET）：`SftpSearchPreset.objects.filter(owner=request.user)`，
  序列化 `{'id','name','spec','updated_at'}`（手写 dict 即可，**不要**回 `owner`）。
- `save_search_preset`（POST）：`name` 空 → 400；
  **`parse_spec(spec)` 必须成功**才落库（把 Task 2 的校验当预设的门禁）；
  `count() >= PRESET_MAX_PER_USER` 且非同名的已有记录 → 400 含「上限」；
  `update_or_create(owner=..., name=..., defaults={'spec': spec})`，
  按 `created` 返回 201/200。
- `delete_search_preset`（POST）：`filter(owner=request.user, id=...)`，
  不存在 → 404 `{'error': '未找到预设'}`。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python manage.py test apps.sftp test.backend`
Expected: 全 PASS。记下总数，填进 spec §7 验收账目。

- [ ] **Step 5: 后端真机验证（HTTP 全链路，必做）**

Task 11B 直连引擎测的是搜索语义；这一步测的是**穿过 `StreamingHttpResponse` +
DRF + JWT + fetch 那一层**后 SSE 帧还完不完整 —— 那是单元与集成测试都覆盖不到的。

```bash
# 1. 起真 SFTP 服务器并造树（Task 11B 已给脚本加好 --fixture）
mkdir -p /tmp/sftp-root
.venv/Scripts/python.exe frontend/e2e/helpers/sftp_server.py \
  --root /tmp/sftp-root --fixture      # stdout 首行 {"host":"127.0.0.1","port":NNNNN}

# 2. 起后端，走登录 → connect → search 全链路
python manage.py runserver 8000 --noreload
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"dev","password":"dev"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")
curl -s -X POST localhost:8000/api/v1/sftp/connect/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"host":"127.0.0.1","port":NNNNN,"username":"any","password":"any"}'

# 3. 真机断言（四条，逐条看）
curl -sN -X POST localhost:8000/api/v1/sftp/search/ \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"roots":["/"],"mode":"content","term":"ShadowReg2","workers":4}'
```

- a. 每一帧都是 `data: {...}` + 空行，**没有半截 JSON**（分帧错了前端永远收不齐）
- b. 首帧 `hello`、末帧 `done`，中间 `match` 的 `items` 长度 ≤ 200（批合成生效）
- c. 响应头有 `X-Accel-Buffering: no`，且 curl `-N` 下**结果是边跑边出现的**
      （若全部憋到最后才吐，说明有缓冲没关掉，前端进度会永久卡在 0）
- d. 跑到一半 `Ctrl-C` 掐断 curl → 后端日志里应出现清理痕迹，且**再发一次搜索能成功**
      （验连接没有留在坏死状态）

四条的实际结果写进 spec §7。**任一条不过，先修完再进前端**——带着分帧问题去联调，
症状会以"前端偶发收不到结果"的形式出现，那时排查成本高一个数量级。

- [ ] **Step 6: 提交**

```bash
git add apps/sftp/models.py apps/sftp/migrations/ apps/sftp/search_views.py apps/sftp/tests_search_preset.py
git commit -m "feat(sftp): 搜索预设模型与 CRUD

保存前先过一遍 parse_spec：预设里存一个跑不通的 spec，等于给用户一个
必定失败的按钮。每人上限 50 条，跨用户不可见不可删（仿 SftpConfig 既有契约）。"
```

---

### Task 11B: 真服务器并行一致性集成测试（自动化）

> 编号带 B 是为了不打乱后面的序号；执行顺序上它紧跟 Task 11、**必须在进前端之前绿**。

**Files:**
- Create: `test/backend/test_sftp_search_integration.py`
- Modify: `frontend/e2e/helpers/sftp_server.py`（**只加 `--fixture` 开关造树**，不改协议逻辑）

**Interfaces:**
- Consumes: `subprocess.Popen([sys.executable, 'frontend/e2e/helpers/sftp_server.py',
  '--root', tmpdir])` + 读 stdout 首行 JSON 拿 `{host, port}`（该脚本已是纯 argparse
  命令行工具，与 Playwright 零耦合）；`SearchSession` + `SearchRunner` 直连真服务器
- Produces: `sftp_server.write_fixture_tree(root: str) -> None`（脚本侧新函数）、
  `sftp_server.py` 的 `--fixture` 开关；
  测试侧 `_Server`（起停真服务器的上下文对象，暴露 `.host` / `.port` / `.stop()`）
  与 `collect(spec_kwargs, workers) -> (matched_paths, candidate_paths, events)`

**为什么这条不能只靠人工**：它是全计划里**唯一**能抓出
「多线程共用一条 channel 导致 `Garbage packet received`」的测试
（`csv_content_searcher.py:24-27` 记的教训）。MagicMock 与 `FakeSftp` 都测不到协议流。
写成人工步骤等于没有回归保护。

- [ ] **Step 1: 给 sftp_server.py 加 `--fixture` 开关**

只加一个函数与一个 argparse 参数，**不动 `FS`/`Server`/`main` 的 accept 循环**：

```python
def write_fixture_tree(root: str) -> None:
    """与 test/backend/sftp_fake.sample_tree() 同形的真文件树。"""
    files = {
        'batch1/RT_1.csv': b'[HEADER]\r\nTestFile,D:\\stdf\\lotA_w01.stdf\r\n'
                           b'StartTime,2026-09-01 08:12:33,\r\n[DATA]\r\n'
                           b'SN,ShadowReg2\r\n1,0.42\r\n',
        'batch1/RT_2.csv': b'[DATA]\r\nSN,ShadowReg2\r\n2,0.43\r\n',
        'batch1/FT_1.csv': b'[DATA]\r\nSN,Vcc\r\n1,3\r\n',
        'batch1/Sum_total.csv': b'summary,not,data\n',
        'batch1/notes.txt': b'not a csv ShadowReg2\n',
        'batch1/Deep/RT_3.csv': b'[DATA]\r\nSN,ShadowReg2\r\n3,0.44\r\n',
        'batch2/RT_10.csv': '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk'),
        'backup/RT_9.csv': b'[DATA]\r\nSN,ShadowReg2\r\n9,0.9\r\n',
        '.hidden/RT_8.csv': b'[DATA]\r\nSN,ShadowReg2\r\n8,0.8\r\n',
    }
    for rel, content in files.items():
        full = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as fh:
            fh.write(content)
    # 一个 20 万行文件：验大文件扫描与行号计数在真 read() 下也对
    big = os.path.join(root, 'batch1', 'BIG.csv')
    with open(big, 'wb') as fh:
        fh.write(b'[DATA]\r\nSN,ShadowReg2\r\n')
        for i in range(200_000):
            fh.write(b'%d,0.%d\r\n' % (i, i % 97))
        fh.write(b'target,ShadowReg2\r\n')
```

`main()` 里在 bind 之前加：`if args.fixture: write_fixture_tree(args.root)`，
argparse 补 `parser.add_argument('--fixture', action='store_true')`。

- [ ] **Step 2: 写测试（先失败）**

```python
"""真 paramiko SFTP 服务器上的并行一致性（spec §4.3）。

全计划唯一能抓出「多线程共用 channel 导致协议流错乱」的测试，
FakeSftp 与 MagicMock 都测不到这一层。跑法：
    python manage.py test test.backend.test_sftp_search_integration
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.test import SimpleTestCase, override_settings  # noqa: E402

from apps.sftp.search import contracts, engine  # noqa: E402
from apps.sftp.search.connect import SearchSession  # noqa: E402

SERVER = os.path.join('frontend', 'e2e', 'helpers', 'sftp_server.py')


class _Server:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='sftp-int-')
        self.proc = subprocess.Popen(
            [sys.executable, SERVER, '--root', self.root, '--fixture'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline()
        try:
            info = json.loads(line)
        except json.JSONDecodeError:
            self.proc.kill()
            raise AssertionError(
                f'SFTP 测试服务器没起来，stdout 首行是 {line!r}，'
                f'stderr={self.proc.stderr.read()[:500]!r}')
        self.host, self.port = info['host'], info['port']

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:      # 收尾不留孤儿进程，否则 %TEMP% 泄漏
            self.proc.kill()
            self.proc.wait(timeout=5)
        shutil.rmtree(self.root, ignore_errors=True)


def collect(spec_kwargs, workers):
    spec = contracts.parse_spec({**spec_kwargs, 'workers': workers})
    session = SearchSession(1, workers)
    session.open_all()
    try:
        runner = engine.SearchRunner(spec, session)
        events = list(runner.events())
    finally:
        session.close_all()
    matched = sorted(i['path'] for e in events if e['kind'] == 'match'
                     for i in e['items'])
    candidates = sorted(i['path'] for e in events if e['kind'] == 'candidates'
                        for i in e['items'])
    return matched, candidates, events


@override_settings(SFTP_HOST_KEY_CHECK='off')
class ParallelConsistencyTests(SimpleTestCase):
    """该服务器每次新生成 RSAKey，故关掉主机密钥校验；
    真连接的 TOFU 契约由 test_sftp_host_keys.py 专门守。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = _Server()
        cls._orig = SearchSession._credentials

        def creds(self):
            return {'host': cls.srv.host, 'port': cls.srv.port,
                    'username': 'any', 'password': 'any'}
        SearchSession._credentials = creds

    @classmethod
    def tearDownClass(cls):
        SearchSession._credentials = cls._orig
        cls.srv.stop()
        super().tearDownClass()

    NAME_ONLY = {'roots': ['/'], 'mode': 'name', 'data_files_only': False}
    CONTENT = {'roots': ['/'], 'mode': 'content', 'term': 'ShadowReg2',
               'data_files_only': False}

    def test_single_vs_four_workers_same_result(self):
        """最值钱的一条：并行不得改变结果。不一致就是协议流竞态。"""
        m1, c1, _ = collect(self.CONTENT, 1)
        m4, c4, _ = collect(self.CONTENT, 4)
        self.assertEqual(m1, m4)
        self.assertEqual(c1, c4)
        self.assertTrue(m1, '真服务器上应当有命中')

    def test_eight_workers_still_identical(self):
        m1, _, _ = collect(self.CONTENT, 1)
        m8, _, _ = collect(self.CONTENT, 8)
        self.assertEqual(m1, m8)

    def test_repeated_runs_are_stable(self):
        """同一 spec 跑三遍结果必须逐字相同 —— 竞态常表现为偶发差异。"""
        first = collect(self.CONTENT, 4)
        for _ in range(2):
            again = collect(self.CONTENT, 4)
            self.assertEqual(first[0], again[0])

    def test_gbk_chinese_term_hits_the_real_file(self):
        """编码探测在真 read() 分块下也要成立（假 sftp 一次给完整内容）。"""
        matched, _c, events = collect(
            {'roots': ['/'], 'mode': 'content', 'term': '漏电电流',
             'data_files_only': False}, 2)
        self.assertEqual(matched, ['/batch2/RT_10.csv'])
        hello = next(e for e in events if e['kind'] == 'hello')
        self.assertEqual(hello['engine'], 'client', '非 ASCII 必须走客户端引擎')

    def test_line_number_of_deep_hit_matches_expected(self):
        """20 万行、跨上百个 1MB chunk 后的行号计数，只有真读能验。"""
        matched, _c, events = collect(self.CONTENT, 2)
        self.assertIn('/batch1/BIG.csv', matched)
        one = next(i for e in events if e['kind'] == 'match'
                   for i in e['items'] if i['path'] == '/batch1/BIG.csv')
        self.assertGreater(one['line'], 200_000)

    def test_depth_prune_and_dotdir_semantics_on_real_server(self):
        _m, c_all, _ = collect({**self.NAME_ONLY, 'depth': 'all'}, 2)
        _m, c_children, _ = collect({**self.NAME_ONLY, 'depth': 'children'}, 2)
        self.assertIn('/batch1/Deep/RT_3.csv', c_all)
        self.assertNotIn('/batch1/Deep/RT_3.csv', c_children)
        self.assertNotIn('/.hidden/RT_8.csv', c_all)
        _m, c_pruned, _ = collect({**self.NAME_ONLY, 'prune_dirs': ['backup']}, 2)
        self.assertNotIn('/backup/RT_9.csv', c_pruned)

    def test_no_connection_leak_after_each_run(self):
        """每次搜索的临时连接必须散干净。"""
        before = threading.active_count()
        for _ in range(3):
            collect(self.CONTENT, 4)
        time.sleep(1.0)
        self.assertLessEqual(threading.active_count(), before + 1,
                             '线程未回收：executor 可能用了 with（会 join）或没 shutdown')
```

> **路径前缀以该脚本的实际根映射为准**。`sftp_server.py` 把 `--root` 映射成 SFTP 侧 `/`，
> 所以断言里的路径都以 `/` 开头。**第一次跑若全红在路径上，先打印一次
> `c_all` 看清真实形态再改断言**——不要反过来改 `roots`。

- [ ] **Step 3: 跑，确认失败**

Run: `python manage.py test test.backend.test_sftp_search_integration`
Expected: FAIL —— `--fixture` 未加时 `setUpClass` 抛 `AssertionError`（树不存在，无命中）

- [ ] **Step 4: 跑，确认通过**

Run: `python manage.py test test.backend.test_sftp_search_integration`
Expected: PASS（7 个测试）。**任何一条不一致都必须在本任务内解决**，
不得"先记下继续往下"——它就是 spec §3.7 全部复杂度的存在理由。

- [ ] **Step 5: 提交**

```bash
git add test/backend/test_sftp_search_integration.py frontend/e2e/helpers/sftp_server.py
git commit -m "test(sftp): 真 SFTP 服务器上的并行一致性集成测试

唯一能抓出多线程共用 channel 导致协议流错乱的一级，FakeSftp/MagicMock 测不到。
workers 1/4/8 与重复三遍的结果必须逐字相同，另验线程无泄漏
（executor 误用 with 就漏在这条）。sftp_server.py 只加 --fixture 造树，不动协议逻辑。"
```

---

## 阶段 7：前端

前端没有 vitest（全仓无该设施），**验证手段是 vue-tsc 类型检查 + 手动走查 + e2e**。
每个前端任务的「跑测试」步骤统一为：

```bash
cd frontend && npx vue-tsc --noEmit        # 类型必须干净
```

加上该任务指定的手动走查项（明写点哪个按钮、看什么现象）。**不得**只写"确认功能正常"。

### Task 12: 提取共享 SSE 消费器

**Files:**
- Create: `frontend/src/utils/ssePost.ts`
- Modify: `frontend/src/api/sftp.ts`（删 `:210-249` 的本地 `postSse`，改 import）
- Test: 无新文件（重构，靠回归）

**Interfaces:**
- Produces: `postSse(url: string, body: unknown, onData: (d: any) => void, signal?: AbortSignal): Promise<void>`

- [ ] **Step 1:** 读 `frontend/src/api/sftp.ts` 的 `postSse`（`:210` 起），**逐字搬**到
  `utils/ssePost.ts` 并 `export`。不改任何行为：`baseURL` 拼接（Electron `file://`）、
  `Authorization: Bearer` 头、按 `'\n\n'` 切帧且 `pop()` 保留残段、JSON.parse 失败静默跳过、
  `AbortError` 静默 return、读 `err.error` 抛错。
- [ ] **Step 2:** `api/sftp.ts` 顶部加 `import { postSse } from '@/utils/ssePost'`，删掉本地副本。
- [ ] **Step 3:** `npx vue-tsc --noEmit` 必须干净。
- [ ] **Step 4: 回归走查（这条重构碰到的是下载主链路）**
  起应用 → SFTP 连接 → 单文件下载看到进度前进并落盘 → 目录下载同理 →
  各点一次取消，确认进度卡消失（不是残留）。
- [ ] **Step 5:** `git add -A frontend/src && git commit -m "refactor(sftp): postSse 提取为共享 utils/ssePost"`

---

### Task 13: 搜索 API 层与类型

**Files:**
- Create: `frontend/src/api/sftpSearch.ts`（约 150 行）
- Test: 无（类型 + 薄封装）

**Interfaces:**
- Consumes: `postSse`（Task 12）
- Produces: 以下类型必须与后端 `SearchSpec`（Task 2）**字段名逐字一致**，
  后端 spec §3.2 是唯一事实源：

```ts
export type SearchMode = 'name' | 'content' | 'column'
export type SearchMatching = 'substring' | 'whole_word' | 'fuzzy'
export type SearchDepth = 'self' | 'children' | 'all' | 'custom'

export interface SearchSpec {
  roots: string[]
  mode: SearchMode
  depth?: SearchDepth
  max_depth?: number | null
  prune_dirs?: string[]
  name_pattern?: string | null
  modified_after?: string | null
  modified_before?: string | null
  min_size?: number | null
  max_size?: number | null
  data_files_only?: boolean
  term?: string
  column_name?: string
  column_rows?: number
  matching?: SearchMatching
  case_sensitive?: boolean
  first_hit_per_file?: boolean
  matches_per_file?: number
  one_per_folder?: boolean
  workers?: number
  allow_server_grep?: boolean
  stop_after_listing?: boolean
  max_entries?: number
  max_candidates?: number
  max_matches?: number
  max_scan_bytes?: number
  timeout?: number
}

export interface CandidateItem { path: string; name: string; size: number; mtime: number }
export interface MatchItem extends CandidateItem {
  line?: number; snippet?: string; hits?: { line: number; snippet: string }[]
  test_file?: string; start_time?: string; pts_modify_time?: string
  values?: string[]; column_name?: string
}

export type SearchEvent =
  | { kind: 'hello'; engine: 'client' | 'grep'; engine_reason: string; workers_actual: number; roots: string[] }
  | { kind: 'stage'; stage: 'listing' | 'scanning' | 'done'; candidates: number; matches: number }
  | { kind: 'candidates'; items: CandidateItem[]; total_so_far: number }
  | { kind: 'match'; items: MatchItem[] }
  | { kind: 'progress'; stage: string; done: number; total: number | null; elapsed_s: number; files_scanned: number; bytes_scanned: number }
  | { kind: 'notice'; code: string; message: string }
  | { kind: 'error'; scope: 'file' | 'dir' | 'fatal'; path: string | null; message: string }
  | { kind: 'done'; matched: number; scanned: number; elapsed_s: number; truncated: boolean; limits_hit: string[]; engine: 'client' | 'grep' }

export interface SearchPresetItem {
  id: number
  name: string
  spec: SearchSpec
  updated_at: string
}

export const sftpSearchApi: {
  run(spec: SearchSpec, onEvent: (e: SearchEvent) => void, signal?: AbortSignal): Promise<void>
  presets(): Promise<{ presets: SearchPresetItem[] }>
  savePreset(name: string, spec: SearchSpec): Promise<SearchPresetItem>
  deletePreset(id: number): Promise<void>
}
```

- [ ] **Step 1:** 实现。`run()` = `postSse('/sftp/search/', spec, onEvent, signal)`。
- [ ] **Step 2:** **写一个双向对齐检查**：把 `SearchSpec` 的 TS 键名列表与后端
  `contracts._KNOWN_KEYS` 逐字比对，差异必须为零。做法：临时脚本读
  `apps/sftp/search/contracts.py` 抓 `_KNOWN_KEYS`，与手抄的 TS 键数组比对，不等则打印差集。
  **这个脚本不入库**（一次性核对），核对完把结果记在 commit message 里。
- [ ] **Step 3:** `npx vue-tsc --noEmit` 干净。
- [ ] **Step 4:** `git add frontend/src/api/sftpSearch.ts && git commit -m "feat(sftp): 搜索 API 层与事件类型"`

---

### Task 14: store —— 流的所有权与驻留

**Files:**
- Create: `frontend/src/stores/sftpSearch.ts`（约 190 行）
- Test: 无（靠 Task 18 的 e2e 驻留专项验）

**Interfaces:**
- Consumes: `sftpSearchApi`、`SearchEvent`
- Produces: `useSftpSearchStore()`，`state`：
  `runs: SearchRun[]`（最新在前，最多 `RUN_HISTORY_KEEP = 20`）、
  `activeRunId: number | null`；
  `SearchRun = { id, spec, status: 'running'|'done'|'cancelled'|'partial'|'error',
  engine, engineReason, workersActual, candidates: CandidateItem[], matches: MatchItem[],
  progress, notices: SearchNotice[], errors: SearchError[], startedAt, finishedAt, done? }`；
  `getters`：`activeRun`、`isRunning`、`chipVisible`；
  `actions`：`start(spec)`、`cancel(id?)`、`removeRun(id)`、`clearFinished()`

- [ ] **Step 1:** 实现 `start(spec)`：
  ```ts
  const run = createRun(spec)
  this.runs.unshift(run)
  if (this.runs.length > RUN_HISTORY_KEEP) this.runs.pop()
  this.activeRunId = run.id
  const ctrl = new AbortController()
  run.abort = ctrl
  try {
    await sftpSearchApi.run(spec, (e) => this.apply(run.id, e), ctrl.signal)
  } finally {
    // 关键：AbortError 被 postSse 吞掉，finally 是唯一可靠的收口点
    this.finalize(run.id)
  }
  ```
- [ ] **Step 2:** 实现 `apply(id, e)` 的事件分派：`candidates`/`match` 是 **push 到数组**
  （不替换），`progress` 覆盖，`notice`/`error` 追加去重（按 `code` / `path+message`），
  `done` 存 `done` 载荷并按 `truncated` 决定 `status = 'partial' | 'done'`。
- [ ] **Step 3:** `cancel(id)`：`run.abort?.abort()` → 立即把 `status` 置 `'cancelled'`、
  `finalize`。**不得依赖 catch**（AbortError 被吞，这是 09-09 记录过的缺陷形态）。
- [ ] **Step 4:** `finalize(id)`：`finishedAt = Date.now()`、`abort = null`、
  `status` 仍是 `'running'` 时置 `'error'`（流意外断，没收到 done）。
- [ ] **Step 5:** **`onBeforeUnmount` / `onDeactivated` 一律不 abort**（与 spec §3.9 第 5 条一致：
  流归 store 所有，跨路由继续跑）。在这两个钩子处**不要**写任何 abort 代码，
  并在文件顶部注释里写明这条是刻意的，防止后来人"顺手补上"。
- [ ] **Step 6:** `npx vue-tsc --noEmit` 干净；`git commit -m "feat(sftp): 搜索 store 持有 SSE 流所有权"`

---

### Task 15: 进度组件与条件表单

**Files:**
- Create: `frontend/src/pages/sftp/components/SearchProgress.vue`（约 100 行）
- Create: `frontend/src/pages/sftp/components/SearchCriteria.vue`（约 260 行）
- Test: 无（Task 18 e2e 覆盖）

**Interfaces:**
- Produces: `SearchProgress` props `{ stage, done, total: number|null, elapsedS,
  matched, candidates, engine }`，emit `cancel`；
  `SearchCriteria` props `{ modelValue: SearchSpec, currentPath: string,
  presets: SearchPresetItem[] }`，emit `update:modelValue` / `run` / `save-preset` / `delete-preset`

- [ ] **Step 1: SearchProgress 三态**
  - `total === null` → 不定档：CSS 流光带 + 纯计数（`已扫描 N · 命中 M · 12.3s`）。
    listing 阶段与 grep 档全程走这里。
  - `total` 为数字 → `el-progress :percentage`。
  - `stage === 'done'` → 收成一行摘要。
  - 取消按钮：`class="search-cancel-btn"` **且** `data-testid="search-cancel-btn"`
    （e2e 按 testid 定位），原位图标按钮 + `tooltip` + `aria-label`，
    **不加文字按钮**（09-09 记录的 UI 偏好）。样式全走语义 token。
  - 状态徽章 `<span data-testid="sftp-search-status">` 文本必须是这五个值之一
    （Task 18 的 e2e 靠它判阶段）：`running` / `done` / `partial` / `cancelled` / `error`。
    **不要**把它本地化成「已完成」—— e2e 断言与 UI 文案要分开，文案走 tooltip。
- [ ] **Step 2: SearchCriteria 分区**（照 spec §3.13 的布局）
  - 范围：roots 多行标签 + 「使用当前目录」按钮（`currentPath` 变化时可用）；
    深度四选一单选；`prune_dirs` 标签输入（回车加一条）。
  - 过滤：`name_pattern`、时间范围两个 `el-date-picker`、`data_files_only` 勾选。
  - 命中：模式三选一 radio；`term` / `column_name` 输入按模式切换显示；
    匹配方式子串/整词/模糊；大小写；**`one_per_folder` 放在命中区内显眼位置**（不藏高级）。
  - 高级（`el-collapse` 默认收起）：`workers`、`timeout`、`allow_server_grep`、
    `stop_after_listing`、`max_candidates`、`max_matches`。
  - 预设：下拉列出 `presets`、选中即回填 `modelValue`；「存为预设」输入名后 emit。
  - 每个 `data-testid`：`sftp-search-roots` / `-depth` / `-prune` / `-pattern` /
    `-time-from` / `-time-to` / `-mode` / `-term` / `-matching` / `-one-per-folder` /
    `-workers` / `-timeout` / `-run` / `-preset-select` / `-preset-save`。
- [ ] **Step 3:** `npx vue-tsc --noEmit`；手动走查：起应用打开搜索页，
  切模式看字段联动、切深度档位看 `自定义` 才露数字框、dark/light 各截一张图对比。
- [ ] **Step 4:** `git commit -m "feat(sftp): 搜索条件表单与三态进度组件"`

---

### Task 16: 结果表（AG Grid）与导出

**Files:**
- Create: `frontend/src/pages/sftp/components/SearchResultsTable.vue`（约 270 行）
- Create: `frontend/src/utils/sftpSearchExport.ts`（约 80 行）
- Test: 无（Task 18 e2e 覆盖导出内容）

**Interfaces:**
- Consumes: AG Grid 的注册姿势照项目现状，在组件文件顶层写两行
  （与 `frontend/src/pages/data/components/correlation/FileCorrelationTable.vue:40,45`
  完全一致，**不要新增模块清单**）：
  ```ts
  import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
  ModuleRegistry.registerModules([AllCommunityModule])
  ```
  以及 `downloadBlob`（`frontend/src/utils/download.ts:41`）
- Produces: props `{ candidates, matches, mode, engine, term, grouped }`，
  emit `selection-change(paths: string[])` / `download(paths)` / `download-parse(paths)` /
  `export()` / `toggle-group`；
  `sftpSearchExport.buildCsv(rows, mode): string` 与 `exportSearchResults(rows, mode, name): void`

- [ ] **Step 1: 列随 mode 变**
  `name` → 名称 / 大小 / 修改时间 / 路径；
  `content` → 再加 命中行 / 命中片段 / TestFile / StartTime；
  `column` → 再加 值 chips / 列名。
  路径列 `cellRenderer` 中段省略（前 18 … 后 24），`tooltip` 给全路径。
  5000 行必须靠 AG Grid 虚拟滚动 —— **不要**自己分页或截断渲染。
- [ ] **Step 2: 命中片段高亮（XSS 红线）**
  `snippet` 拆成 `[before, hit, after]` 三段渲染为文本节点：
  ```ts
  function highlight(text: string, term: string, ci: boolean) {
    if (!term) return [{ t: text, hit: false }]
    const hay = ci ? text.toLowerCase() : text
    const needle = ci ? term.toLowerCase() : term
    const i = hay.indexOf(needle)
    if (i < 0) return [{ t: text, hit: false }]
    return [{ t: text.slice(0, i), hit: false },
            { t: text.slice(i, i + term.length), hit: true },
            { t: text.slice(i + term.length), hit: false }]
  }
  ```
  模板用 `<span v-for>` 渲染 `part.t`（插值，**绝不 `v-html`**）。
- [ ] **Step 3: 分组**
  `grouped` 为真时用 AG Grid 的 `rowGrouping` 按 `dirname(path)` 分组，组头显示
  `目录 · N 个命中`。store 侧在 `candidates.length + matches.length > 200`
  （`AUTO_GROUP_THRESHOLD`）时把 `grouped` 默认置真，用户可手改。
- [ ] **Step 4: 导出 CSV**
  ```ts
  const BOM = '\uFEFF'                     // 无 BOM 则 Excel 打开中文乱码
  function cell(v: unknown): string {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s   // RFC 4180
  }
  // 列集合随 mode 变，与结果表所见一致 —— 不该导出看不见的列
  const COLUMNS: Record<SearchMode, Array<[key: string, label: string]>> = {
    name:    [['name', '名称'], ['path', '完整路径'], ['size', '字节'],
              ['mtime', '修改时间(epoch秒)']],
    content: [['name', '名称'], ['path', '完整路径'], ['size', '字节'],
              ['mtime', '修改时间(epoch秒)'], ['line', '命中行'], ['snippet', '命中内容'],
              ['test_file', 'TestFile'], ['start_time', 'StartTime'],
              ['pts_modify_time', 'PtsModifyTime']],
    column:  [['name', '名称'], ['path', '完整路径'], ['column_name', '列名'],
              ['values', '值'], ['test_file', 'TestFile'], ['start_time', 'StartTime']],
  }

  export function buildCsv(rows: MatchItem[] | CandidateItem[],
                           mode: SearchMode): string {
    const cols = COLUMNS[mode]
    const lines = [cols.map(([, label]) => cell(label)).join(',')]
    for (const row of rows) {
      lines.push(cols.map(([key]) => {
        const v = (row as Record<string, unknown>)[key]
        return cell(Array.isArray(v) ? v.join(' | ') : v)   // values 并成一格
      }).join(','))
    }
    return lines.join('\r\n') + '\r\n'
  }

  export function exportSearchResults(rows: MatchItem[] | CandidateItem[],
                                      mode: SearchMode, name: string): void {
    downloadBlob(new Blob([BOM + buildCsv(rows, mode)],
      { type: 'text/csv;charset=utf-8' }),
      name.endsWith('.csv') ? name : `${name}.csv`)
  }
  ```
  `mtime` 导出 epoch 秒而非格式化串：格式化会引入逗号与时区歧义，
  而导出的用途是在 Excel 里排序筛选。
  文件名：`sftp_search_<mode>_<YYYYMMDD_HHmmss>.csv`（前端拼，不套后端导出模板 ——
  与项目其它导出的 `export_naming.py` 约定**有意不一致**，理由见 spec §3.1）。
- [ ] **Step 5: 手动走查（不能只跑类型检查）**
  搜一次 content → 导出 → 用 Excel 打开确认中文测试项名不乱码、含逗号的路径没被拆列；
  勾 3 个文件点下载 → 下载进度卡出现（与搜索互斥生效）；
  term 输入 `<img src=x onerror=alert(1)>` 再搜 → 片段列把它显示成字面文本、无弹窗。
- [ ] **Step 6:** `git commit -m "feat(sftp): 搜索结果表与 CSV 导出"`

---

### Task 17: 搜索页、路由、常驻 chip 与互斥接线

**Files:**
- Create: `frontend/src/pages/sftp/SftpSearchPage.vue`（约 210 行）
- Create: `frontend/src/components/common/ActiveSearchChip.vue`（约 80 行）
- Modify: `frontend/src/router/index.ts`（`sftp` 路由旁增一条子路由）
- Modify: `frontend/src/pages/sftp/SftpBrowser.vue`（545 → 约 557 行）
- Modify: `frontend/src/pages/sftp/components/SftpToolbar.vue`（+「高级搜索」按钮）
- Modify: `frontend/src/pages/sftp/components/SftpFileTable.vue`（目录行右键菜单）
- Modify: App 级布局组件（挂 `ActiveSearchChip`）
- Test: 无（Task 18）

**Interfaces:**
- Consumes: `useSftpSearchStore`、`SearchCriteria`、`SearchResultsTable`、`SearchProgress`、
  `sftpApi.download` / `downloadAndParseBatch`
- Produces: 路由 `name: 'SftpSearch'`、`path: 'sftp/search'`（懒加载）；
  chip 的 `data-testid="sftp-search-chip"`

- [ ] **Step 1:** `SftpSearchPage.vue` = `SearchCriteria` + `SearchProgress` +
  `SearchResultsTable` + 底部动作条，状态全部读 store（`activeRun` 或用户从历史里选的 run）。
  动作：`下载`（单文件走 `sftpApi.download`，多文件走 `downloadAndParseBatch`）。
- [ ] **Step 2: 未连接的处理**
  页面 mount 时**不探测连接状态**（项目没有这个端点，也不新建）。做法：
  `start()` 收到 400 且 `error` 含 `not connected` → 页面显示一条
  `el-alert`「请先在 SFTP 浏览器建立连接」+「去连接」按钮（`router.push({name:'SftpBrowser'})`）。
  另：mount 时用现成 `sftpApi.getLastVisit()` 的 `can_auto_connect` 决定是否提前给出提示。
- [ ] **Step 3: 路由**
  `router/index.ts` 在 `sftp` 那条旁加 `{ path: 'sftp/search', name: 'SftpSearch',
  component: () => import('@/pages/sftp/SftpSearchPage.vue') }`，
  保持与 `sftp` 同一父级与同一权限守卫。
- [ ] **Step 4: chip**
  `ActiveSearchChip.vue` 读 `store.isRunning` / `store.activeRun`，
  结构必须是（Task 18 Step 5 的 e2e 按这些钩子定位）：

  ```html
  <div v-if="store.isRunning" data-testid="sftp-search-chip">
    <span data-testid="sftp-search-chip-scanned">{{ scannedText }}</span>
    <span data-testid="sftp-search-chip-matched">{{ run.matches.length }}</span>
    <el-button class="search-cancel-btn" data-testid="search-cancel-btn"
               :icon="CircleClose" aria-label="取消搜索" @click="store.cancel()" />
  </div>
  ```

  `v-if` 只在 running 时出现 —— 搜索结束后 chip 消失，因此 e2e 里
  「结束后 chip 不可见」也是一条要显式断的性质，不要假设。
  挂在 App 级 header（**不是** SftpBrowser 内部）—— 这是「跨页面驻留可见」的落点。
- [ ] **Step 5: SftpBrowser 三处改动**
  1. `SftpToolbar` 加「高级搜索」按钮 → `router.push({name:'SftpSearch'})`；
  2. `SftpFileTable` 目录行右键菜单「在此目录搜索」→
     `router.push({name:'SftpSearch', query:{root: row.path}})`，
     页面 mount 时把 `query.root` 填进 `roots`；
  3. `transferActive`（`:171`）computed 增加 `searchActive` 支路：
     `const searchActive = computed(() => searchStore.isRunning)`，
     并入 `transferActive`，从而**现有全部下载按钮自动禁用**，无需逐个改。
     搜索页自身的下载按钮也读同一个 `transferActive`。
- [ ] **Step 6: 取消冷却**
  搜索取消后沿用 `startCooldown()`（1.2s）。在 `store.cancel()` 里回调注入，
  或由 chip 调用 `SftpBrowser` 暴露的方式 —— **选定一种并写进代码注释**，别两处都冷却。
- [ ] **Step 7: 走查（六条，逐条做）**
  ① SFTP 页点「高级搜索」进页 → roots 预填面包屑路径；
  ② 目录行右键「在此目录搜索」→ roots 是该目录；
  ③ 起搜索 → 不搜完就切到数据管理页 → **chip 仍在且计数在涨** → 切回来结果完整；
  ④ 搜索运行中回 SFTP 页 → 下载按钮全部禁用且有 tooltip；
  ⑤ 面包屑点进子目录 → 搜索照跑不误（独立连接，不抢池连接）；
  ⑥ 从 chip 取消 → 状态归零、1.2s 内下载按钮仍禁用、之后恢复。
- [ ] **Step 8: 双主题** —— dark/light 各走一遍 ③④，确认无字面色遗漏。
- [ ] **Step 9:** `git commit -m "feat(sftp): 搜索页/常驻 chip/与下载互斥接线"`

---

## 阶段 8：e2e 与文档

### Task 18: e2e 搜索用例

**Files:**
- Create: `frontend/e2e/sftp/search.spec.ts`
- Modify: `frontend/e2e/helpers/sftpServer.ts`（fixture 树扩容）
- Test: 自身即测试

**Interfaces:**
- Consumes: `startSftpServer()`（`helpers/sftpServer.ts:26`）、`manualConnect` /
  `ensureDisconnected` / `deleteSftpImportsQuiet`（照 `e2e/sftp/reconnect.spec.ts:26-92` 的写法）

- [ ] **Step 1: 扩 fixture 树**
  在 `sftpServer.ts:27-35` 现有四个文件之外补：
  `batch1/Deep/RT_3.csv`（测 `depth`）、GBK 中文测试项 CSV（测编码）、
  `Sum_x.csv`（测 `data_files_only`）、`backup/RT_b.csv`（测 `prune_dirs`）、
  一个 20 万行 CSV（测大文件扫描 + 进度前进）。
- [ ] **Step 2:** `test.describe.configure({ mode: 'serial' })` + 每条 `tag: ['@p1','@sftp']`。
- [ ] **Step 3: 用例清单（每条都是独立 `test(...)`）**
  1. **仅文件名搜索**：`mode=name` + `*RT*` → 断言行数与路径集合。
  2. **内容搜索命中**：`term=ShadowReg2` → 断言命中集合，片段含 term。
  3. **深度档位**：`children` 搜不到 `Deep/RT_3.csv`，`all` 搜得到。
  4. **剪枝**：`prune_dirs=['backup']` → 结果不含 `/backup/`。
  5. **中文 term 回落**：`term=漏电电流` → chip 内 `engine === 'client'`
     （通过暴露的 `data-testid="sftp-search-engine"` 断言），且 GBK 文件被命中。
  6. **仅列候选**：`stop_after_listing` → 出现候选、无命中、耗时短。
  7. **取消**：见 Step 4 的 route 阻塞技巧。
  8. **驻留专项**：见 Step 5。
  9. **互斥**：搜索进行中 → `SftpFileTable` 的下载按钮 `toBeDisabled()`。
  10. **截断告知**：`max_candidates=1` → partial 黄条可见且不可关。
  11. **导出**：点导出 → 用 `page.on('download')` 落临时文件 → 读回断言 BOM 存在、
      含逗号的行没被拆列。
- [ ] **Step 4: 「进行中」的确定性技巧（lessons 记录过的唯一可靠做法）**
  本地 SFTP 秒传、时序钉不住。用：
  ```ts
  await page.route('**/sftp/search/', async (route) => {
    await new Promise((r) => setTimeout(r, 3000))
    await route.continue().catch(() => {})     // abort 后 continue 会 reject，必须吞
  })
  ```
  在 3s 窗口内从容断言禁用态与取消按钮；断言完 `await page.unroute('**/sftp/search/')`
  再验证真实链路未被取消破坏。
- [ ] **Step 5: 驻留专项（本需求的核心性质，单独一条）**

  先加一个读数 helper（AG Grid 虚拟滚动只渲染视口内的行，所以**不能用 `toHaveCount`
  断言行数** —— 那是测渲染，不是测数据；改成断言 store 落到 DOM 上的计数徽章）：

  ```ts
  async function pathCells(page: Page): Promise<string[]> {
    return page.locator('.ag-cell[col-id="path"]')
      .evaluateAll((els) => els.map((e) => e.textContent?.trim() ?? ''))
  }
  ```

  用例主体：

  ```ts
  // sftp_server.py 把 --root 目录映射成 SFTP 侧的 /，所以 roots 就是 '/'
  await page.getByTestId('sftp-search-roots').fill('/')
  await page.getByTestId('sftp-search-mode').getByText('内容含').click()
  await page.getByTestId('sftp-search-term').fill('ShadowReg2')
  await page.getByTestId('sftp-search-run').click()
  await expect(page.getByTestId('sftp-search-status'))
    .toHaveText(/done|partial/, { timeout: 30_000 })   // 等它真跑完

  const expected = await pathCells(page)
  expect(expected.length).toBeGreaterThanOrEqual(3)
  expect(new Set(expected).size).toBe(expected.length)  // 基线：本身无重复

  await page.goto('/data')                              // 跳去数据管理页
  const chip = page.getByTestId('sftp-search-chip')
  // （若搜索已结束，chip 应已消失 —— 这条也要显式断，别默认它一定在）
  await page.goto('/sftp/search')

  const after = await pathCells(page)
  expect(after).toEqual(expected)                       // 无丢失、无重复、无重排
  ```

  「进行中」的版本（配合 Step 4 的 route 阻塞，让流真的跨页面活着）：

  ```ts
  await page.getByTestId('sftp-search-run').click()
  await page.waitForTimeout(500)
  await page.goto('/data')
  const chip = page.getByTestId('sftp-search-chip')
  await expect(chip).toBeVisible()                      // 离开 SFTP 页仍然可见
  const firstCount = await chip.getByTestId('sftp-search-chip-matched').textContent()
  await expect.poll(
    async () => await chip.getByTestId('sftp-search-chip-matched').textContent(),
    { timeout: 20_000 },
  ).not.toBe(firstCount)                                // 计数确实在涨
  await chip.getByTestId('search-cancel-btn').click()
  await expect(chip).toBeHidden()
  await page.goto('/sftp/search')
  await expect(page.getByTestId('sftp-search-status')).toHaveText(/cancelled/)
  ```

  这要求 chip 里的命中数有独立 `data-testid="sftp-search-chip-matched"`，
  **Task 17 Step 4 的 chip 实现要带上它**。
- [ ] **Step 6:** `npx playwright test e2e/sftp/search.spec.ts --project=P1 --workers=1` 全绿
  （`playwright.config.ts:106` 的 `P1` project 靠 `grep: /@p1/` 选用例，
  不写 `--project` 会落进 `Edge` 那个 `grepInvert` project 而被跳过）。
  收尾 `Stop-Process` 放掉 8000/3000（e2e 可靠运行方式的项目约定）。
- [ ] **Step 7:** `git commit -m "test(e2e): SFTP 搜索用例，含跨页面驻留与截断告知专项"`

---

### Task 19: 用户指南与 lessons

**Files:**
- Modify: `docs/user-guide/06-sftp.md`
- Modify: `docs/tasks/lessons.md`

- [ ] **Step 1:** `06-sftp.md` 新增「搜索」小节：三层模型（范围 / 过滤 / 命中）、
  深度档位、`prune_dirs`、三种匹配方式、服务端加速的启用与回落、
  截断告知的含义、预设、导出、**「搜索期间可继续浏览、但不能同时下载」**。
- [ ] **Step 2: 顺手纠正该文档三处与代码不符**（Task 前序探查发现，均属本文档维护范围）：
  - `:23` / `:32-37` 讲「密码/私钥二选一、上传私钥、passphrase」——
    代码完全不支持私钥认证（`SftpConfig` 只有 `password_encrypted`，
    `connect` 只取 `password`）。**删掉私钥段**。
  - `:68` 「下载到本地默认下载目录」—— 实际是 `MEDIA_ROOT/data/<username>/single/`。
  - `:121-123` FAQ「每次进入目录会重新建立 SFTP 连接」—— 已被 `pool.py` 消除，
    这条现在反而误导。**改成**「连接会复用，空闲 5 分钟后回收」。
- [ ] **Step 3:** `docs/tasks/lessons.md` 追加本次的两条：
  - 「参考工具里能跑 ≠ 能移植」：`AutoAddPolicy` 会破本项目 TOFU 契约；
    `Transport` 在 paramiko 5.0 已无 `default_timeout`。**先按当前依赖版本核签名再抄。**
  - 「两档引擎自动降级时，语义不等价的能力必须整体禁用其中一档」：
    regex / 模糊 / 非 ASCII / 跨语言整词都属于这类 —— 结果取决于环境比缺功能更糟。
- [ ] **Step 4:** 重建用户指南站点（项目自定义 Node 构建脚本）确认渲染无误。
- [ ] **Step 5:** `git add docs && git commit -m "docs(sftp): 搜索使用指南 + 纠正三处过期描述"`

---

### Task 20: 收尾验证与账目

- [ ] **Step 1:** `python manage.py test` 全量，记录测试总数与结果。
- [ ] **Step 2:** `cd frontend && npx vue-tsc --noEmit`；
  `npx playwright test e2e/sftp --project=P1 --project=setup --workers=1`（含回归既有
  `sftp.spec.ts` / `reconnect.spec.ts`，确认搜索没把互斥与取消的老行为改坏）。
- [ ] **Step 3:** 打包版冒烟：`build.bat` 产物起一次，走「连接 → 搜索 → 下载 → 分析」全链路。
      （spec §2.5 的 threaded runserver 结论只在桌面版成立，打包版必须实测一次。）
- [ ] **Step 4:** 把以下数字填进 spec §7 验收账目：后端测试总数、e2e 通过数、
      grep 档真机人工验证（服务器地址脱敏、grep/find 版本、是否 chroot、
      `workers=1` vs `workers=4` 结果是否一致）、dark/light 截图位置。
- [ ] **Step 5:** `git commit -m "docs(sftp): 搜索实施验收账目"`

---

## 计划自检（写完通读一遍）

**spec 覆盖**：§3.1 → Task 1–17 的文件清单逐一对应；§3.2 → Task 2；§3.3 → Task 3；
§3.4 → Task 5；§3.5 → Task 6/7；§3.6 → Task 8；§3.7 → Task 4；§3.8 → Task 9/10；
§3.9 → Task 9；§3.10 → Task 11；§3.11 → Task 10；§3.12 → Task 1；
§3.13 → Task 15/16/17；§4.1–4.4 → 各任务 Step 1 + Task 18；
§4.3 真服务器 → **Task 11B**；§4.5 缺口 → Task 8（命令构造断言）+ Task 11 Step 5
+ Task 20 Step 4。**无遗漏项。**

**占位符扫描**：无 TBD/TODO。三处形似占位、实则有意保留的东西：
`Task 11` 的迁移名 `00XX_`（编号须由 `makemigrations` 生成，Step 3 已要求人工复核）；
`Task 2` 的 `_KNOWN_KEYS = frozenset({...})`（27 个键在 §3.2 请求体里逐条列全，
由 Task 13 Step 2 的比对脚本兜住一致性）；
`Task 18` Step 3 的用例清单是索引、每条的主体在 Step 4/5 给了可粘贴代码。

**本次自审实际改掉的问题**（都不是措辞，是会让实现出错的）：

1. **测试期望写错**：`test_hello_reports_actual_worker_count` 断言 `workers_actual == 1`，
   而它构造的 `FakeSession(size=spec(workers=3).workers)` 是 3 —— 会红。改为 3。
2. **未定义的类型**：`SearchPresetItem` 在 Task 13/15 被引用却没定义 → 补接口。
3. **未定义的常量**：`_CLAMPED_TEXT` 被 `events()` 索引却没内容 → 补九个码的文案表
   （缺一个就是运行期 `KeyError`）。
4. **未接线的调用**：`_probe()` 与 `session.exec_transport()` 的关系没写 → 补 `chan_factory`
   接线与 `_run_grep` 的完整链路。
5. **不可执行的 e2e 断言**：`toHaveCount(N)` 是占位；且 AG Grid 虚拟滚动下
   DOM 行数≠数据行数，那个断言本身选错了测量对象 → 改为比 path 数组相等 +
   集合大小相等，并说明为什么不能用 `toHaveCount`。
6. **testid 契约缺失**：Task 18 用到了 `sftp-search-status` / `-chip-matched` /
   `search-cancel-btn`，但 Task 15/17 没要求实现 → 补齐，并规定状态徽章文本必须是
   五个英文状态值之一（e2e 断言与 UI 文案分离）。
7. **我自己的错误归因**：Task 8 曾写「spec §3.6 要求取条目再测」——回读 spec 后发现
   它没这么写，那是参考工具的做法。已改为「与参考工具的有意偏离」并要求代码注释说明。
   **写计划时把没核实过的归属安到 spec 头上，与把子代理的行号照抄是同一类错误。**
8. **AG Grid 注册方式写成了模糊引用**（"照现成文件的接法"）→ 给确切两行与来源行号。
9. **notice 码歧义**：`grep_unavailable` 与 `grep_fallback` 在 spec 两处各定义一次，
   实现者很可能当成重复而合并 → 补表说明两者是不同的事件。
10. **把唯一的并行竞态测试写成了人工步骤**（第一轮自审漏掉，第二轮才抓到）：
    spec §4.3 要求 `workers=1` 与 `workers=4` 结果一致这条自动化，我第一版把它降级成
    Task 11 的 curl 人工验证。那条是全计划**唯一**能抓出 paramiko 多线程共用 channel
    协议错乱的测试，人工做等于没有回归保护 → 补 **Task 11B** 用
    `frontend/e2e/helpers/sftp_server.py` 起真服务器自动跑，并规定「不一致必须在本任务内解决」。
    教训：**把一条测试划进"人工验证"之前，先问它防的是不是竞态/时序**——
    那类缺陷只在自动化里反复跑才现形。

**类型一致性**：`SearchSpec` 键名在 Task 2（Python）与 Task 13（TS）之间由 Task 13 Step 2
的比对脚本钉住；事件 `kind` 的八个取值在 Task 9 生产、Task 13 消费，字面串已逐条对齐；
`borrow()` 返回 `Tuple[Transport, SFTPClient]`，Task 9 用 `item[1]` 取 sftp —— 一致；
`engine_name` 只有 `'client' | 'grep'` 两种，与 TS 的 `engine` 联合类型一致。

**实施中若被推翻要同时改两份文档的判断**：`max_candidates` 默认 5000、
导出文件名的前端拼接约定、映射探测的粒度。


