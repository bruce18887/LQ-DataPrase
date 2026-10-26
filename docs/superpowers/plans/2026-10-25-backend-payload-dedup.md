# B 后端载荷（解析缓存坐标化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 20 个用户打开同一个物理文件时后端只付一次解析，并把两处「每次请求重算已经算过的东西」挪到写入侧。

**Architecture:** 解析缓存的键从 `(file_id, owner_id, mtime_ns, abs_path)` 改成内容坐标 `(abs_path, mtime_ns, format_type)`；
失败值不再入缓存（`_BytesLRUCache.get_or_compute` 新增默认关闭的 `store_if` 谓词，判据住 services 层）；
`col_meta` 随解析产出并计入体积估算；dashboard 的 `clean_data` 从出口挪到缓存写入侧。
鉴权完全不进缓存——调用方照旧按 `DataFile.filter(pk, owner_id)` 判可见性，响应字节不变。

**Tech Stack:** Django 5 + DRF、pandas、进程内按字节预算的 LRU（`apps/datafiles/services.py`）、
Django unittest（T1 为主）、Playwright 仅作既有契约回归（不新增选择器）。

**Spec:** `docs/superpowers/specs/2026-10-25-backend-payload-dedup-design.md`（判据 J1-J7 的定义在 spec §5，
本计划把每条落进具体用例）

## Global Constraints

- 单个 `.vue` / `.py` 文件不超过 600 行（`.claude/CLAUDE.md:62`）；本计划落点的现状：
  `apps/datafiles/services.py` 347、`apps/datafiles/tests_parse_cache.py` 341、
  `apps/dashboard/services.py` 406、`apps/dashboard/views.py` 75、`apps/dashboard/tests.py` 见 Task 4 步骤 0。
- 不新增任何 npm / pip 依赖。
- 后端测试一律跑 `python manage.py test <label>`（默认落 `config.settings.unit` ⇒ `test/unit-data`），
  **不要用 pytest 跑**，新用例文件里也不要 `import pytest`（`docs/reference/testing-gates.md` §6）。
- 判绿取日志末尾 `RESULT:` / `Ran N tests … OK|FAILED` 本体，不取 `$?`（同上 §1）。
- 每个任务**先红后绿**；红必须是新断言在旧代码上红，不许"写了就绿"。
- 不许夹带无关改动：只 `git add` 本任务点名的文件，逐文件 add，**禁止裸 `git stash`**（共享工作区）。
- 入库文件不得提名兄弟工程名；夹具一律写 `$BIG` / `$MID` 占位。
- 本刀不改任何前端代码、不改任何响应字段、不动 `apps/*/views` 的 12 个 `get_cached_parsed_file` 调用点。

---

### Task 1: 失败值不入缓存（语义变更，坐标化的前置）

**Files:**
- Modify: `apps/datafiles/services.py`（`_BytesLRUCache.get_or_compute` :103-125、`_cached_parse` :196-199、新增 `_parse_succeeded`）
- Modify: `apps/datafiles/tests_parse_cache.py`（`:142-157` 扩展、`:159-167` 扩展、新增两条）

**Interfaces:**
- Consumes: `_BytesLRUCache.get_or_compute(key, compute, size_of)` 现有形状；`_parse_file_uncached` 的三种失败返回
  （`(None, None, fmt)` 缺路径 / `(None, metadata, fmt)` parser 返 None / `(None, None, None)` 抛异常）。
- Produces: `services._parse_succeeded(value) -> bool`（Task 2/3 的键改造复用同一条谓词，不许另立判据）；
  `_BytesLRUCache.get_or_compute(self, key, compute, size_of=_parse_value_bytes, store_if=None)`
  —— `store_if=None` 时行为与今天逐字一致（`_cache_failures` 等其它使用者零影响）。

- [ ] **Step 1: 写失败用例（两条新增 + 一条扩展）**

在 `apps/datafiles/tests_parse_cache.py` 的 `BytesLRUCacheTests` 类里新增：

```python
    def test_failed_parse_does_not_occupy_a_cache_entry(self):
        """失败结果不许占位：它算出 0 字节，而 0 字节条目连 LRU 都淘汰不动。

        旧行为是「永久化到那只文件 mtime 变化为止」；坐标化之后爆炸半径会从
        一个人放大到同一路径的所有人，所以这条必须在改键之前就绿。
        """
        class Boom:
            def parse(self, path):
                raise RuntimeError('disk on fire')

        original = services.get_parser
        services.get_parser = lambda fmt: Boom()
        self.addCleanup(setattr, services, 'get_parser', original)
        self.use_budget(64 * 1024 * 1024)

        first = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')
        second = services._cached_parse(1, 1, 1, self.path, 'CTA8290D')

        self.assertIsNone(first[0])
        self.assertIsNone(second[0])
        self.assertEqual(len(services._parse_cache), 0, '失败结果不许进缓存')
        self.assertEqual(services.get_parse_cache_stats()['misses'], 2,
                         '第二次必须真的重试，而不是命中那条 0 字节的失败记录')
```

把现有 `test_missing_file_hint_preserved`（`:159-167`）整体替换成下面这份，**保留它原有的两条断言**
（返回契约 `(None, None, format_type)` 不变、`parser.calls == 0`），只补第三与第四条：

```python
    def test_missing_file_hint_preserved(self):
        """文件不在磁盘上时返回 (None, None, format_type) 的既有契约不变，且不占缓存。"""
        parser = self.patch_parser(_frame())
        missing = os.path.join(tempfile.gettempdir(), 'nope_does_not_exist.csv')

        out = services._cached_parse(9, 1, 1, missing, 'CTA8290D')
        again = services._cached_parse(9, 1, 1, missing, 'CTA8290D')

        self.assertEqual(out, (None, None, 'CTA8290D'))
        self.assertEqual(parser.calls, 0)
        self.assertEqual(len(services._parse_cache), 0,
                         '缺文件的失败同样不许入缓存')
        self.assertEqual(again, (None, None, 'CTA8290D'),
                         '重试必须返回同一条契约，而不是被缓存改写成别的形状')
```

再加一条纯函数用例（放 `FrameBytesTests` 之后，新建 `ParseSucceededTests`），钉住谓词本身判掉三种失败形状：

```python
class ParseSucceededTests(SimpleTestCase):
    """`_parse_succeeded` 是「什么值值得进缓存」的唯一判据，三种失败形状都得判 False。"""

    def test_only_a_real_frame_is_worth_caching(self):
        frame = _frame(rows=10)
        self.assertTrue(services._parse_succeeded((frame, {'format': 'CTA8290D'}, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, None, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, {'format': 'CTA8290D'}, 'CTA8290D')))
        self.assertFalse(services._parse_succeeded((None, None, None)))
```

- [ ] **Step 2: 跑，确认新用例红**

Run: `python manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: FAIL —— `test_failed_parse_does_not_occupy_a_cache_entry` 红在 `len(...) == 1`（当前失败值被 `_store` 收下），
`test_only_a_real_frame_is_worth_caching` 红在 `AttributeError: module ... has no attribute '_parse_succeeded'`。
`test_failed_parse_is_not_stuck_as_pending`（既有那条）必须**仍然绿**——它断的是 pending 已释放，不受本任务影响。

- [ ] **Step 3: 最小实现**

`apps/datafiles/services.py` 的 `get_or_compute` 结尾（`:118-125`）改成先问谓词再存：

```python
            try:
                value = compute()
            finally:
                with self._cv:
                    self._pending.discard(key)
                    self._cv.notify_all()
            if store_if is None or store_if(value):
                self._store(key, value, size_of(value))
            return value
```

签名同步加默认关闭的参数（docstring 补一句「`store_if` 由调用方定义什么值值得占位；默认 None＝无条件存」）：

```python
    def get_or_compute(self, key, compute, size_of=_parse_value_bytes, store_if=None):
```

在 `_parse_file_uncached` 之后新增模块级判据（**住 services 层，不放通用件**——LRU 不该知道什么叫解析失败）：

```python
def _parse_succeeded(value) -> bool:
    """「这条值值得占缓存位」的唯一判据。

    三种失败形状（路径不存在 / parser 返回 df=None / 抛异常兜成 (None, None, None)）都不该存：
    `_parse_value_bytes` 给它们算 0 字节，而 `_store` 的淘汰循环只在**总量超预算**时逐条，
    0 字节条目既不占预算也永远不会被逐出 ⇒ 一次瞬时失败会永久化到该文件 mtime 变化。
    与写透路径 `put_cached_parsed_file`（df/metadata 为 None 时不写）是同一条规则。
    """
    return bool(isinstance(value, tuple) and value[0] is not None)
```

`_cached_parse` 的调用处（`:197-199`）带上谓词：

```python
    return _parse_cache.get_or_compute(
        key, lambda: _parse_file_uncached(file_id, owner_id, path_key,
                                         file_path, format_type),
        store_if=_parse_succeeded)
```

- [ ] **Step 4: 跑，确认全类绿**

Run: `python manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: `Ran 22 tests ... OK`（现 20 条 + 本任务新增 2 条：
`test_failed_parse_does_not_occupy_a_cache_entry` 与 `ParseSucceededTests`；
`test_missing_file_hint_preserved` 是就地扩展，不增数）

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/services.py apps/datafiles/tests_parse_cache.py
git commit -m "fix(jobs): 解析失败不再入缓存——0 字节条目会永久占位，坐标化前必须先摘掉"
```

---

### Task 2: 解析缓存键坐标化（J1 + J3）

**Files:**
- Modify: `apps/datafiles/services.py`（`_cached_parse` 的 key :197、`put_cached_parsed_file` 的 put :261、两处 docstring）
- Modify: `apps/datafiles/tests_parse_cache.py`（新增 J1/J3 两条；改写 `:82-97`、`:179-190`、`:192-203` 三条——
  它们都用「换 `file_id`」制造两个 key，坐标化后那个维度不再进键）

**Interfaces:**
- Consumes: Task 1 的 `store_if=_parse_succeeded`（不动）；`_disk_mtime_ns` 不变。
- Produces: 键的**唯一形状** = `(abs_path: str, path_key: int, format_type: str)`。
  `_cached_parse(file_id, owner_id, path_key, file_path, format_type)` 与
  `get_cached_parsed_file(file_id, owner_id, datafile=None)` 的签名**不变**（`owner_id` 仍用于鉴权查询与日志），
  `ModuleShapeTests:294-297` 继续绿；若它红，说明签名被动了 = 越界，退回。

- [ ] **Step 1: 写 J1（两个 owner 打同一物理文件 ⇒ 一份缓存）**

在 `_CacheCaseBase` 里加一个造第二只物理文件的助手（坐标化之后，**换 key 的唯一手段是换内容坐标**）：

```python
    def second_path(self):
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        return path
```

`BytesLRUCacheTests` 里新增：

```python
    def test_two_owners_of_one_physical_file_share_one_entry(self):
        """J1：键去 owner 化之后，同一路径的第二个调用方必须复用同一只帧。

        旧代码在这里必然红（键含 owner_id ⇒ 两个 key ⇒ parser 解析两次），
        所以这条先红后绿本身就是对照组。
        """
        frame = _frame()
        parser = self.patch_parser(frame)

        first = services._cached_parse(11, 1, 12345, self.path, 'CTA8290D')
        second = services._cached_parse(22, 2, 12345, self.path, 'CTA8290D')

        self.assertIs(first[0], second[0])
        self.assertEqual(len(services._parse_cache), 1, '同一路径只该有一条缓存')
        self.assertEqual(parser.calls, 1, f'实际解析 {parser.calls} 次')
```

- [ ] **Step 2: 写 J3（跨 owner 的单飞）**

现存的 `test_concurrent_miss_for_same_key_parses_once`（`:123-140`）断的是同 `(file_id, owner)`；
在它后面补一条把前提换成两个 owner 的版本（延时也用同一个 0.3s，别调小——它是给 t1 进"解析中"留的窗口）：

```python
    def test_concurrent_miss_from_two_owners_parses_once(self):
        """J3：跨 owner 的单飞才是这一刀的收益——20 人首开同一文件该只解析一次。"""
        parser = self.patch_parser(_frame(), delay=0.3)
        results = {}

        def worker(name, file_id, owner_id):
            results[name] = services._cached_parse(file_id, owner_id, 12345,
                                                   self.path, 'CTA8290D')

        t1 = threading.Thread(target=worker, args=('a', 11, 1))
        t2 = threading.Thread(target=worker, args=('b', 22, 2))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(parser.calls, 1,
                         f'两个 owner 并发 miss 应共用一次解析，实际 {parser.calls} 次')
        self.assertIs(results['a'][0], results['b'][0])
```

- [ ] **Step 3: 跑，确认 J1/J3 红在旧键上**

Run: `python manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: FAIL —— J1 红在 `len(...)==2` 与 `parser.calls==2`，J3 红在 `parser.calls==2`。
其余三条（`test_second_request_for_same_file_is_not_reparsed`、`PutCachedParsedFileTests`、既有并发同 owner 那条）应仍绿。

- [ ] **Step 4: 改键（读侧 + 写透侧必须逐字同源）**

`_cached_parse`（`:196-199`）：

```python
    key = (file_path, path_key, format_type)
```

并在它的 docstring 里把「key 含 file_id/owner_id」的叙述换掉（保留 mtime 失效那段）：

```python
    """Parse a DataFile and cache the result in memory (byte-budgeted LRU).

    Key = (绝对路径, 盘上 mtime_ns, format_type) —— 内容坐标。
    `file_id` / `owner_id` 不进键：`_parse_file_uncached` 只消费路径与格式，
    那两个参数在这条链上只用于鉴权与日志。把 owner 放进键会让 20 个用户各解析
    一遍同一只物理文件（夹具见 scripts/perf_load20.py:192-195），且每-key 单飞
    在跨 owner 场景完全失效。`format_type` 必须留在键里：同一路径被两行标成不同
    格式时用的是不同 parser，合并会返回错数据。
    ...
    """
```

`put_cached_parsed_file`（`:260-261`）—— 键换成同一套内容坐标，**不加 `store_if`**：

```python
    _parse_cache.put((abs_path, path_key, datafile.format_type), (df, metadata, fmt))
```

写透侧早就只写成功值（`:257-259` 那句 `df is None or metadata is None` 就是同一道闸），
所以这里不需要重复把关；`put` 也**没有** `store_if` 形参。等出现第二个写透调用方再考虑给 `put`
加与 `get_or_compute` 同名同默认值的形参——现在加就是给一条没人走的路预留参数。

- [ ] **Step 5: 改写三条用 `file_id` 制造 key 的既有用例**

`test_entries_evict_by_byte_budget_not_by_count`（`:82-97`）—— 断言语义不变（按字节淘汰），只把
"换 key 的手段"从 `file_id` 换成路径：

```python
        self.cached_parse()
        services._cached_parse(2, 2, 12345, self.second_path(), 'CTA8290D')

        cache = services._parse_cache
        self.assertLessEqual(cache.bytes_cached(), budget,
                             '缓存总量必须始终不超过预算')
        self.assertEqual(len(cache), 1)
        self.cached_parse()   # 旧条目已被挤掉 → 重新解析
        self.assertEqual(parser.calls, 3)
```

`test_evict_to_zero_keeps_last_entry_and_counts`（`:179-190`）里
`self.cached_parse(file_id=1)` / `self.cached_parse(file_id=2)` 换成：

```python
        self.cached_parse()
        services._cached_parse(2, 2, 12345, self.second_path(), 'CTA8290D')
        self.assertEqual(len(services._parse_cache), 2)
```

`test_evict_parse_cache_to_fraction`（`:192-203`）的 `for file_id in (1, 2, 3)` 循环换成三条不同路径：

```python
        paths = [self.path, self.second_path(), self.second_path()]
        for idx, path in enumerate(paths):
            services._cached_parse(idx + 1, 1, 12345, path, 'CTA8290D')
```

- [ ] **Step 6: 加「调用方不原地改共享帧」的静态扫描（spec §7 风险 1 的处置）**

坐标化之后一只帧会被多个请求并发读，唯一约束是 docstring 那句「Callers must NOT mutate」。
本步把它变成承重判据。新增类放 `apps/datafiles/tests_parse_cache.py` 末尾（该文件当前 341 行，
加完仍在 600 行内）：

```python
class SharedFrameSafetyTests(SimpleTestCase):
    """缓存帧跨请求共享 ⇒ 任何调用方原地改它就是并发写。这条扫描把它钉住。

    两个刻意的形状：① 按**载体并集**扫，且「某个载体读不到」直接判红——2026-10-23 那次
    常量搬家后单文件扫描零命中、空集反而"相等"，就是假绿（见 docs/tasks/todo.md:5325-5329）。
    ② 正则用拼接构造，否则这条测试文件自己会含住模式串、被自己抓到。
    """

    CARRIERS = [
        'apps/analysis/views/_helpers.py',
        'apps/analysis/views/analysis_views.py',
        'apps/analysis/views/file_correlation_views.py',
        'apps/batch_report/services.py',
        'apps/batch_report/views.py',
        'apps/buyoff/views.py',
        'apps/common/file_loading.py',
        'apps/dashboard/views.py',
        'apps/datafiles/views/browse_views.py',
        'apps/gage/views.py',
    ]
    MUTATION = re.compile('(' + r'\bdf\.drop\([^)]*inplace=True'
                          + r'|' + r'\bdf\[[^\]]+\]\s*=[^=]'
                          + r'|' + r'\bdf\.(loc|iloc)\[[^\]]+\]\s*=[^=]'
                          + r'|' + r'del df\[)')

    def test_no_caller_mutates_the_shared_frame(self):
        root = Path(services.__file__).resolve().parents[2]
        scanned = 0
        for rel in self.CARRIERS:
            path = root / rel
            self.assertTrue(path.is_file(), f'载体清单过期：{rel} 读不到（假绿源头）')
            text = path.read_text(encoding='utf-8')
            match = self.MUTATION.search(text)
            self.assertIsNone(match,
                              f'{rel} 在原地改共享的 df：{match and match.group(0)}')
            scanned += 1
        self.assertEqual(scanned, len(self.CARRIERS),
                         '每个载体都必须真的被扫到，扫描数与清单数必须相等')
```

顶部补两行 import：`import re` 与 `from pathlib import Path`。

Run: `python manage.py test apps.datafiles.tests_parse_cache.SharedFrameSafetyTests -v 2`
Expected: PASS（今天 10 个载体都不含原地写）。**它必须一次就绿**——这条不是"新功能红转绿"，
而是把既有约定变成判据；如果它红，说明撞到了真问题，停下来报，不许改正则放行。

- [ ] **Step 7: 跑，确认全类绿**

Run: `python manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: `Ran 25 tests ... OK`

- [ ] **Step 8: 跑解析链路相关的既有后端用例，确认没伤到别处**

Run: `python manage.py test apps.datafiles apps.dashboard apps.analysis.tests_file_correlation -v 1`
Expected: `OK`。若 `apps/datafiles/tests.py:762-797`、`:1766-1783` 那几处解析缓存用例红，
逐条读它们断的是不是「换 owner ⇒ 换条目」这种旧语义；是就按新语义重写并在提交信息里写明改了哪条口径，
**不许为了让它绿而把键改回去**。

- [ ] **Step 9: 提交**

```bash
git add apps/datafiles/services.py apps/datafiles/tests_parse_cache.py apps/datafiles/tests.py
git commit -m "perf(browse): 解析缓存改内容坐标——同一路径 20 个 owner 现在共用一次解析"
```

（`apps/datafiles/tests.py` 只在 Step 7 真的改了才 add。）

---

### Task 3: `col_meta` 随解析产出 + 体积估算计入（J4 + J7）

**Files:**
- Modify: `apps/datafiles/services.py`（`_parse_file_uncached` 成功分支、新增 `_col_meta_bytes`、`_parse_value_bytes`）
- Modify: `apps/datafiles/views/browse_views.py:246`
- Modify: `apps/analysis/views/statistics_views.py:68`
- Test: `apps/datafiles/tests_parse_cache.py`

**Interfaces:**
- Consumes: `apps.analysis.services.statistics.build_col_meta`（`limits.py:280`，Task 3 起由 services 调用，
  services 现有 import 行 `:11` 已从同一包引 `detect_fail_data_with_borderline`，加一个名字不产生新依赖）。
- Produces: `metadata['col_meta'] -> Dict[str, Dict[str, str]]`（与 `build_col_meta` 今日返回值**逐字段相同**）；
  `services._col_meta_bytes(metadata) -> int`；调用侧读取方式
  `col_meta = metadata.get('col_meta') or build_col_meta(df, metadata)`（缺键时回落，保证任何未走缓存的
  路径拿到的响应与今天一致）。

- [ ] **Step 0: 确认响应字段来源只有两处**

Run: `git grep -n "build_col_meta" -- apps`
Expected: 生产调用点只有 `apps/analysis/views/statistics_views.py:68` 与
`apps/datafiles/views/browse_views.py:246`（其余是 `statistics/__init__.py` 的 re-export）。
若多出别的点，停下来报，不要顺手一起改。

- [ ] **Step 1: 写 J4（每文件一次，且值与旧写法逐字相等）**

```python
    def test_col_meta_is_built_once_per_file_not_per_request(self):
        """J4：翻页不该再付每请求的 O(列) 循环（1702 列那档实测 260ms）。"""
        frame = _frame()
        parser = self.patch_parser(frame)
        real = services.build_col_meta
        with mock.patch('apps.datafiles.services.build_col_meta',
                        wraps=real) as spy:
            first = services._cached_parse(11, 1, 12345, self.path, 'CTA8290D')
            second = services._cached_parse(22, 2, 12345, self.path, 'CTA8290D')

        self.assertEqual(spy.call_count, 1,
                         f'build_col_meta 被调 {spy.call_count} 次，应随解析只算一次')
        self.assertEqual(first[1]['col_meta'], second[1]['col_meta'])
```

⚠ 打桩目标是 `apps.datafiles.services.build_col_meta`——按 R6③，必须 patch **消费方模块的绑定**，
patch `apps.analysis...limits` 那份不会生效（会静默全绿，这是假绿的形状）。

- [ ] **Step 2: 写等价性用例（证明响应字节没变）**

```python
    def test_col_meta_value_matches_the_per_request_builder(self):
        """缓存里那份必须与「每请求现场算」逐字段相等——响应形状不许动。"""
        frame = _frame()
        parser = self.patch_parser(frame)
        df, metadata, _fmt = services._cached_parse(1, 1, 12345, self.path, 'CTA8290D')
        cached_meta = metadata['col_meta']

        fresh_input = {k: v for k, v in metadata.items() if k != 'col_meta'}
        self.assertEqual(cached_meta, services.build_col_meta(df, fresh_input))
        self.assertEqual(sorted(cached_meta), sorted(df.columns))
```

（`fresh_input` 剥掉 `col_meta` 是必须的：否则 `build_col_meta` 的入参多一个键，虽然它只读
`units/mins/maxs`，断言读起来就成了自证。）

- [ ] **Step 3: 写 J7（预算不失真）**

```python
    def test_budget_counts_col_meta_real_bytes(self):
        """J7：`64 × len(metadata)` 会把几十 KB 的 col_meta 估成 64 字节。"""
        frame = _frame(rows=200, cols=8)
        parser = self.patch_parser(frame)
        df, metadata, fmt = services._cached_parse(1, 1, 12345, self.path, 'CTA8290D')

        value_bytes = services._parse_value_bytes((df, metadata, fmt))
        self.assertGreaterEqual(
            value_bytes,
            services._frame_bytes(df) + services._col_meta_bytes(metadata),
            '体积估算必须包含 col_meta 的真实量级')
        self.assertGreater(
            value_bytes,
            services._frame_bytes(df) + 64 * len(metadata),
            '沿用「metadata 一律按 64 字节/键」会低估')
```

- [ ] **Step 4: 跑，确认三条红**

Run: `python manage.py test apps.datafiles.tests_parse_cache -v 2`
Expected: FAIL —— `KeyError: 'col_meta'`（Step 1/2）与 `AttributeError: ... _col_meta_bytes`（Step 3）。

- [ ] **Step 5: 实现——产出侧算一次，估算侧计入**

`_parse_file_uncached` 的成功分支（`:206-212`）在返回前挂上：

```python
        if df is None:
            return None, metadata, format_type
        metadata = dict(metadata)
        metadata['col_meta'] = build_col_meta(df, metadata)
        return df, metadata, format_type
```

（`dict(metadata)` 是刻意的：`metadata` 由 parser 现场产出、此处复制一次成本可忽略，
但它会让"写缓存的 metadata"与"上传写透的 metadata"共享同一只 dict 的情况变得可预测，
J1 之后同一路径会被跨请求共享——不要往别人正在读 dict 上加键。）

新增估算函数（放在 `_parse_value_bytes` 之前）：

```python
def _col_meta_bytes(metadata) -> int:
    """`col_meta` 的真实量级：列名 + 每列三个字符串。

    1702 列那档是几十 KB 量级。`_parse_value_bytes` 若继续按 `64 × len(metadata)` 算，
    它会被估成 64 字节，1536MB 那条预算就成了自欺的数字（判据 J7）。
    """
    col_meta = metadata.get('col_meta') if isinstance(metadata, dict) else None
    if not isinstance(col_meta, dict):
        return 0
    total = 0
    for name, entry in col_meta.items():
        total += len(str(name))
        if isinstance(entry, dict):
            total += sum(len(str(v)) for v in entry.values())
    return total
```

`_parse_value_bytes`（`:49-55`）改成扣除 `col_meta` 那一个键再单独计，避免双算：

```python
def _parse_value_bytes(value) -> int:
    """``(df, metadata, format_type)`` 三元组的缓存占用（metadata 按真实量级）。"""
    df = value[0] if isinstance(value, tuple) else None
    total = _frame_bytes(df)
    if isinstance(value, tuple) and isinstance(value[1], dict):
        meta = value[1]
        total += 64 * (len(meta) - (1 if 'col_meta' in meta else 0))
        total += _col_meta_bytes(meta)
    return total
```

- [ ] **Step 6: 改两处调用侧读取（响应字段照旧每页发）**

`apps/datafiles/views/browse_views.py:246`：

```python
            + ',"col_meta":' + json.dumps(metadata.get('col_meta')
                                          or build_col_meta(df, metadata), ensure_ascii=False)
```

`apps/analysis/views/statistics_views.py:68`：

```python
        col_meta = metadata.get('col_meta') or build_col_meta(df, metadata)
```

两处都保留 `or build_col_meta(...)` 作回落，为的是任何**没走解析缓存**的路径（例如别处直接 parse）
仍然拿得到同一份值，响应字节与今天一致。

- [ ] **Step 7: 跑，确认绿 + 后端 browse/analysis 面不红**

Run: `python manage.py test apps.datafiles.tests_parse_cache apps.datafiles apps/analysis -v 1`
Expected: `Ran N tests ... OK`。若某条既有断言写死了 `metadata` 的**键集合**（等值比较整个 dict），
按新语义补上 `col_meta` 并写明这是刻意的形状变化；不要把它改成 `assertIn` 之类的弱断言。

- [ ] **Step 8: 提交**

```bash
git add apps/datafiles/services.py apps/datafiles/views/browse_views.py apps/analysis/views/statistics_views.py apps/datafiles/tests_parse_cache.py
git commit -m "perf(browse): col_meta 随解析产出，体积估算按真实量级计入"
```

---

### Task 4: dashboard 的 `clean_data` 挪到缓存写入侧（J5）

**Files:**
- Modify: `apps/dashboard/services.py:366-390`（`get_dashboard_summary` 的写入路径 + 文件头 import）
- Modify: `apps/dashboard/views.py:60-66`（出口不再清洗）
- Test: `apps/dashboard/tests.py`

**Interfaces:**
- Consumes: `apps.analysis.views._helpers.clean_data`（纯函数、幂等，`_helpers.py:84-94`）。
- Produces: `get_dashboard_summary` 命中时返回**已清洗**的 payload；
  `_summary_cache_key`（`services.py:342-363`）**不变**——它含 `datafile.id / owner_id / thresholds / filename /
  program_name / fmt`，这一层本来就该按用户阈值分键，跨用户共享是错的。

- [ ] **Step 0: 数一下 dashboard 现有用例与文件行数（防止越 600 行）**

Run: `wc -l apps/dashboard/tests.py && python manage.py test apps.dashboard -v 1`
Expected: 读到基线例数与 `OK`。若 `tests.py` 已 >560 行，新用例另建
`apps/dashboard/tests_summary_cache.py`（Django 默认 `test*.py`/`tests*.py` 能发现，见 P2-7 那条口径）。

- [ ] **Step 1: 写 J5 的两条断言（清洗只做一次 + 值等价）**

```python
class SummaryCleanOnceTests(TestCase):
    """J5：命中缓存的第二次请求不该再把整份 payload 重建一遍（clean_data 是纯函数）。"""

    def test_cache_hit_does_not_reclean(self):
        from unittest import mock

        from apps.analysis.views._helpers import clean_data
        from apps.dashboard import services as dash_services

        user = User.objects.create_user(username='clean_once', password='pw')
        datafile = DataFile.objects.create(
            owner=user, filename='a.csv', file_path='a.csv',
            file_size=1, format_type='CTA8290D', status='ready')
        raw = {'rows': [{'v': float('nan'), 'ok': 1.0}]}
        dash_services._summary_cache.clear()
        self.addCleanup(dash_services._summary_cache.clear)
        with mock.patch.object(dash_services, 'compute_dashboard_summary',
                               return_value=raw), \
             mock.patch.object(dash_services, 'clean_data', wraps=clean_data) as spy:
            first = dash_services.get_dashboard_summary(datafile, None, 'CTA8290D', {}, None)
            second = dash_services.get_dashboard_summary(datafile, None, 'CTA8290D', {}, None)

        self.assertEqual(spy.call_count, 1, '第二次是缓存命中，不该再清洗')
        self.assertIs(second, first, '命中必须返回同一只对象')
        self.assertIsNone(first['rows'][0]['v'], 'NaN 必须在缓存里就已经是 None')
```

字段照 `apps/dashboard/tests.py:205-212` 那处既有的 `DataFile.objects.create` 抄
（`owner / filename / file_path / file_size / format_type / status`），别自创新写法。
`User` 与 `DataFile` 该文件顶部已经 import（`:11` 一带与 `:18`），只缺 `TestCase` 与 `mock`：
`mock` 在测试函数里局部 import（与该文件 `:216` 的局部 import 风格一致），
`TestCase` 加到文件顶部的 `from django.test import SimpleTestCase` 那行后面。

（`_summary_cache_key` 会 `os.stat(resolve_file_path(datafile.file_path))`，文件不存在时回落 0，
所以这条不需要真造一只盘上文件；`compute_dashboard_summary` 与 `clean_data` 都按 R6③ patch
**消费方模块** `apps.dashboard.services` 的绑定。）

- [ ] **Step 2: 跑，确认红**

Run: `python manage.py test apps.dashboard -v 2`
Expected: FAIL，但**红在 `AttributeError: <module 'apps.dashboard.services'> does not have the attribute
'clean_data'`** —— 今天清洗住在视图里，`patch.object` 找不到的那个名字本身就是"还没挪进来"的证据。
这条要如实写进提交信息：**Step 4 之后判据变成计数**（`spy.call_count == 1`），那才是承重的断言；
如果你在这里改成"先加 import 再跑"来制造一个 `2 != 1` 的红，别忘了那只是同一条断言的另一种红法，
不许把它当成对照组。

- [ ] **Step 3: 实现——清洗挪到写入侧**

`apps/dashboard/services.py` 文件头 import 区加：

```python
from apps.analysis.views._helpers import clean_data
```

`get_dashboard_summary` 的未命中分支（`:380-387`）改成算完即清洗再存：

```python
    payload = clean_data(compute_dashboard_summary(
        df, datafile, fmt, metadata, thresholds=thresholds))
```

docstring 补一句：「存入的是**已清洗**结果，命中直接返回；出口侧不再过 `clean_data`。」

`apps/dashboard/views.py:65` 去掉出口清洗（并保留那两条注释的语义，改写成现状）：

```python
            # 走缓存层：同一文件 + 同一阈值 + mtime 未变时直接返回上次结果。
            # 非有限值已在写入侧过完 clean_data（见 services.get_dashboard_summary）——
            # 漏进 payload 的话 DRF 严格渲染器会在 handler 层抛 ValueError，整页 500。
            return Response(get_dashboard_summary(
                datafile, df, fmt, metadata, cpk_thresholds))
```

并删掉 `apps/dashboard/views.py:11` 那行 `from apps.analysis.views._helpers import clean_data`
（若该文件别处不再用它；`git grep -n clean_data apps/dashboard/views.py` 确认零命中再删）。

- [ ] **Step 4: 跑，确认绿**

Run: `python manage.py test apps.dashboard apps.datafiles.tests_parse_cache -v 2`
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add apps/dashboard/services.py apps/dashboard/views.py apps/dashboard/tests.py
git commit -m "perf(dashboard): clean_data 挪到缓存写入侧，命中不再重建整份 payload"
```

---

### Task 5: 收口——门禁、复测读数、账回写

**Files:**
- Modify: `docs/tasks/todo.md`（B 那条从「未做，且没有设计稿」改成实际状态 + 读数）
- Modify: `docs/reference/perf-baseline-2026-10-24-dual-profile.md`（§6 三条落点的状态列）

**Interfaces:**
- Consumes: Task 1-4 的全部产物；`services.get_parse_cache_stats()`（已挂 `/api/v1/metrics/`）。
- Produces: 台账里的 B 条目闭环记录 + 基线文档的定靶更新。**阈值按已定口径 3，等读数出来再定**。

- [ ] **Step 1: 后端全套**

Run: `python manage.py test test.backend apps.accounts apps.analysis apps.buyoff apps.common apps.dashboard apps.datafiles apps.export apps.gage apps.jobs apps.report apps settings apps.sftp -v 1`
（labels 与 `scripts/e2e_nightly.mjs:129-136` 同源枚举 `apps/` 每个目录；**别手打 `apps.*`**，那是非法标签，
实测只跑 1104 例并带一条 ModuleNotFoundError，看着像回归。）
Expected: `Ran NNNN tests ... OK`（基线例数见提交信息，逐条对账）

- [ ] **Step 2: 快门禁**

Run: `cd frontend && npm run test:e2e:affected`
Expected: 日志末尾 `RESULT: PASS`；`NO AFFECTED TESTS` 不算绿。

- [ ] **Step 3: 收口全量池**

Run: `node scripts/e2e_pool.mjs --slots=4`
Expected: `结论 MEASURED`、真红 0（负载抖动按 `testing-gates.md` §1 走独占复跑判级）。
这是本刀唯一证明「响应字节没变」的通路——browse/summary/analysis 的既有 e2e 全绿才算契约未动。

- [ ] **Step 4: 20 人档复测（读数入账，不进门禁）**

按基线 §1 的跑法复跑（浏览器档至少三轮 + 一轮无并发对照；方案 A 档需 WSL，缺环境就如实写「未跑」，
**不许拿浏览器档读数冒充两档**）：

```bash
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py migrate --run-syncdb
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe manage.py runserver 127.0.0.1:<port> --noreload
env LQDP_E2E_SLOT_DIR=test/perf-<轮名> DJANGO_SETTINGS_MODULE=config.settings.e2e_slot \
    .venv/Scripts/python.exe scripts/perf_load20.py --base http://127.0.0.1:<port> \
    --heavy job --job-submits 6 --out tasks/perf-r1-<轮名>.json
```

夹具与冷热口径不许动（基线 §1 那张表）；每轮独立 `LQDP_E2E_SLOT_DIR`；夹具放 ext4（WSL 侧）。

上面命令里的两个占位这样取：**`<轮名>`** = `dedup-r1` / `dedup-r2` / `dedup-r3`（外加 `dedup-solo`
作无并发对照），`LQDP_E2E_SLOT_DIR` 用同名目录，别复用 `test/perf-*` 里上一轮留下的目录
（那是 `scripts/test_data_gc.py` 的回收候选，混用会把读数读到旧轮上）。
**`<port>`** = 先问本机临时端口区间 `netsh int ipv4 show dynamicport tcp`（**本机实测 1024–15000，非默认**），
监听口只在 15001–49151 里选，选完用 `netstat -ano | grep -E ':<port>\s'` 确认没被占
（正则必须容 1–5 位端口，`\d{4}` 会漏掉五位端口、于是永远报"空闲"）。这是端口卫生，**不是**掉线的原因。

记录：`browse` 首页 P95、`misses`/`entries`/`evictions` 曲线（`/api/v1/metrics/` 或直接读
`get_parse_cache_stats()`）、提交跳首跳与稳态两侧对照。**阈值在这里定**：拿读数对着「无并发 12–48ms」
那条线报差值，再决定门禁线取几。

- [ ] **Step 5: 回收落盘面**

Run: `python scripts/test_data_gc.py`（默认 dry-run，看清候选再 `--apply`；禁区树整棵清零那条别绕）。

- [ ] **Step 6: 回写台账与基线，提交**

`docs/tasks/todo.md` 的 B 条目（`:5355` 区段与文末 B 档第 1 条）改成实际状态：做了什么、J1-J7 落点、
复测读数、阈值定没定。基线 §6 三条落点逐条标状态（含 §7 发现的第四条，见下）。

```bash
git add docs/tasks/todo.md docs/reference/perf-baseline-2026-10-24-dual-profile.md
git commit -m "docs(perf): B 后端载荷收口——读数入账，阈值按本次对照定"
```

---

## 计划外发现（**需用户点头才进本刀，默认不做**）

写计划时按 spec 的三条落点核对代码，发现同一族里还有**第四条、而且大概率是最贵的一条**：

`apps/datafiles/views/browse_views.py:146` 的注释写着「fail 检测按 (file, mtime) 缓存——文件内容未变时零重算」，
但 `services._cached_fail_data`（`apps/datafiles/services.py:265-289`）**没有缓存检测结果**——
它每次调用 `_cached_parse` 之后现场跑 `detect_fail_data_with_borderline(df, metadata)`（`:286`），
也就是每次 browse 请求都对全表做一次列扫描建 `fail_cells`/`borderline_cells`
（`limits.py:105` 的 `_scan_limit_cells`，夹具那档是 35,246 行 × 1,702 列）。
函数名、docstring、调用侧三处都在说"缓存过了"，全仓没有任何用例覆盖 `get_cached_fail_data`。

形状与落点 3 完全同构（结果只依赖 `(df, metadata)`，同文件每页相同 ⇒ 可以搭同一套键与预算），
所以技术上并进本刀很容易；但它是**spec §1 里没有的靶子**，并进同一刀会让「B 后端载荷」的验收范围
悄悄变大。要做的话说一声，我按同样形状加一个 Task 3.5（含「注释说谎」那条纠正与一条 J8 计数判据），
或者单独立一条待拍板项进 B 档。
