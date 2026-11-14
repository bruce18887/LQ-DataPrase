# 批2 · 磁盘占用量 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 数据管理页显示当前用户真实磁盘占用（`GET /api/v1/files/usage/` 逐文件实扫 + 30s 分桶缓存），并在数据修复中心按阈值露出「清单记录与磁盘不一致」。

**Architecture:** 后端一个新模块 `apps/datafiles/storage_usage.py` 承担全部口径（`os.scandir` + `os.lstat` 走树、inode 去重、DB 侧分「在根目录内/在外」两本账、差值恒等式），一个新 APIView 只做鉴权与取数，路由**排在 router include 之前**。前端 `utils/diskUsage.ts` 收全部派生文案（可 T2 钉），`FileListToolbar.vue` 只渲染一颗复用 `.section-count` 样式的 chip + `el-descriptions` 浮层；占用数据由 `FileListTab.vue` 异步拉一次，并在既有的 `filesStore.filesVersion` watch 里以 `fresh=1` 重拉，因此不需要在 8 个写路径分别挂失效钩子。

**Tech Stack:** Django 5 / DRF（`DefaultRouter` 生成的详情路由 lookup 是 `[^/.]+`）、`apps/common/keyed_lru.py` 的 `KeyedLRU`（进程内、按条数封顶、每 key 单飞）、Vue 3 `<script setup>` + Element Plus 2.14、Vitest（T2）、Playwright（T3，`page.route` 透传改写响应的既有范式）。

---

## 规格订正（写代码前读，这四条是设计与实测的差异）

设计稿 `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §4 有四处与此刻的代码/平台不符或承诺不成立。**代码为准**，本计划按下面的写法执行：

**订正①（§4.1 路由前提错了）** 稿子写「`urls.py` 里已有 `files/<int:pk>/` 这类形状，`usage` 不是 int 所以不会被它吞」。实际 `apps/datafiles/urls.py:20-31` 里**没有**这条 `path()`——它是 `apps/datafiles/urls.py:18` 的 `DefaultRouter` 生成的，而 DRF 3.18.3 的 lookup 模式是 `'[^/.]+'`（`.venv/Lib/site-packages/rest_framework/routers.py:143`，本仓 `apps/datafiles/views/file_views.py:101` 的 ViewSet 没有覆盖 `lookup_value_regex`），所以生成的 `^files/(?P<pk>[^/.]+)/$` **确实会吞掉 `files/usage/`**。
⇒ 处置：`path('files/usage/', …)` 必须排在 `path('', include(router.urls))`（`apps/datafiles/urls.py:21`）**之前**。Task 4 的端点测试本身就是这条排序的证明：排错了它直接 404。
⇒ 另一处连带：稿子建议把视图写进 `file_views.py`，但 `apps/datafiles/views/file_views.py` 现在 **590/600 行**、`apps/datafiles/services.py` **599/600 行**（`scripts/line-limit.mjs:197` 的判据是 `lines <= limit`，600 合法 601 红），两者都只剩个位数余量 ⇒ 口径实现与视图各开一个新文件，不在大文件里加肉。

**订正②（§4.3/§4.6 的两个数不是同一个集合）** `apps/datafiles/utils.py:97 store_file_path` 明确「MEDIA_ROOT 之外（如样例目录）或跨盘的路径**保持绝对路径原样**」，`apps/datafiles/utils.py:80 resolve_file_path` 又容忍「2026-08-21 前的遗留绝对路径原样透传」。所以 `db_bytes = SUM(file_size)` 覆盖的记录，可能有一部分**根本不在** `MEDIA_ROOT/data/<username>/` 这棵被扫的树里 ⇒ 按稿子的恒等式，任何带遗留数据的装机都会常年报一条假的不一致。
⇒ 处置：DB 侧分两本账（`db_bytes_in_root` / `db_outside_root_count`+`db_outside_root_bytes`），差值恒等式只用**在根内**那一本；「目录外还有 N 条」单独在浮层里说一次，不并进 chip。
⇒ 代价可控：这条不是新增扫描，只是把已经在做的 `values_list` 遍历分桶——同一段形状在 `apps/datafiles/views/browse_views.py:272-277` 已经是生产写法。

**订正③（§4.6 那句「可重新扫描」承诺了一个不存在的动作）** 全仓**没有任何**路径会回写 `DataFile.file_size`（唯一写入点是 `apps/datafiles/views/_helpers.py:123 file_size = os.path.getsize(file_path)`，注册那一刻之后永不刷新；`_register_file` 只在新增时调用）。所以「重新扫描」既不会让 `db_bytes` 追上磁盘，也不会让差值消失——把它写成按钮就是一句谎话。
⇒ 处置：差值行**只陈述事实、不带动作**（文案见 Task 9），并且把「补一个 `refresh_file_sizes` 修复动作」留给配额批。理由另有一条：批3 的重复判定口径是 `(filename, file_size)` 精确相等，真去回写 `file_size` 会连带改变重复组的划分，那属于跨批影响，不该在本批顺手做。

**订正④（§4.4 的「主动失效」改成客户端驱动）** 稿子要「上传/删除/修复成功后主动失效」，但满足它的服务端钩子有 8 处（`_register_file`、`_delete_datafile_file_only`、`bulk_delete`、两处 `shutil.rmtree`、两处 `shutil.move`、修复动作分发器），漏挂一处就**永久**陈旧到进程重启。
⇒ 处置：`KeyedLRU` 分桶 TTL 做正确性下界（漏挂最多陈旧 30–60s），刷新入口做成 `?fresh=1`，由 `FileListTab.vue` 在**已经存在**的 `filesStore.filesVersion` watch（`frontend/src/pages/data/components/FileListTab.vue:322-327`）里带 `fresh=true` 重拉——上传/删除/批量删除/组合/修复五条流全都调 `filesStore.notifyFilesChanged()`（`FileListTab.vue:220/225/256/288/306`），所以**一行覆盖全部**，SFTP 后台导入这类无前端信号的路径由 TTL 兜底，浮层里显示「统计时间」让陈旧可见。

---

## 文件结构

| 文件 | 动作 | 唯一职责 |
|---|---|---|
| `apps/datafiles/storage_usage.py` | 新建 | 磁盘走树 + inode 去重 + DB 两本账 + 差值恒等式 + 分桶 TTL 缓存。**只有口径，不碰 HTTP** |
| `apps/datafiles/views/usage_views.py` | 新建 | `FileUsageView`：鉴权 + 取 `fresh` 参数 + `Response`。不写任何计算 |
| `apps/datafiles/urls.py` | 改 2 处 | 导入 + 把 `files/usage/` 排在 router include 之前 |
| `apps/datafiles/views/__init__.py` | 改 1 处 | re-export `FileUsageView`（与既有 5 组导出同形） |
| `test/backend/test_storage_usage_scan.py` | 新建 | T1：口径（表观/唯一/符号链接/空树/rglob 异源交叉核对/by_type 分段）+ 两本账 + 恒等式边界 + TTL 与 fresh |
| `test/backend/test_files_usage_api.py` | 新建 | T1：端点契约（未登录、字段齐全、owner 隔离、405、`data_dir` 指向本人目录） |
| `frontend/src/api/datafiles.ts` | 改 | `FileUsage`/`UsageBucket` 类型 + `getFileUsage(fresh)` |
| `frontend/src/utils/diskUsage.ts` | 新建 | 全部派生文案：chip 那句、GB 档体积、浮层行、目录外那句、差值那句、统计时间 |
| `frontend/test/unit/diskUsage.spec.ts` | 新建 | T2 钉住上面 6 个函数 |
| `frontend/src/pages/data/components/FileListToolbar.vue` | 改 | 新增 `usage` prop + chip + `el-descriptions` 浮层（复用 `.section-count`，不新增字号声明） |
| `frontend/src/pages/data/components/FileListTab.vue` | 改 | `usage` ref + `loadUsage()` + onMounted 拉一次 + filesVersion watch 带 fresh 重拉 + 向下透传 |
| `frontend/src/pages/data/components/ConsistencyCheckDialog.vue` | 改 | 差值 `el-alert` 行（只陈述，无按钮） |
| `frontend/e2e/data/disk-usage-chip.spec.ts` | 新建 | T3：文案与端点数值异源核对 / usage 故障不影响列表 / 上传后以 fresh=1 刷新 / 差值行随注入出现 |
| `docs/superpowers/plans/2026-11-14-batch2-disk-usage.md` | 本文件 | 计划 + 落地后的实测订正 |
| `docs/tasks/todo.md`、`docs/tasks/lessons.md` | 改 | Task 10 写台账与实测耗时；踩到新坑才动 lessons |

不新建快照表、不加配额字段、不动 `file_size` 的写路径（设计稿 §4.7 决策 B：本批只落「当前用户 + 口径正确的真实字节」）。

---

### Task 1: 探针——先实测四个数，再决定实现细节

不改产品代码。四个问题里 P1/P2 直接决定 Task 3 与 Task 5 的验收口径，没实测就写数字会撞 lessons「报体积前先说明口径并交叉核对」（2026-10-24）。

**Files:**
- Create: `tasks/probe_batch2_disk_usage.py`（`tasks/*` 被 `.gitignore:162` 忽略，探针脚本**不入库**，结论写进本文件末尾的「Task 1 实测结论」与 `docs/tasks/todo.md`）

- [ ] **Step 1: 写探针脚本**

```python
# tasks/probe_batch2_disk_usage.py
"""批2 Task 1 探针：只回答四个「设计稿里没有实测值」的问题，不改任何产品代码。

P1 每个用户的注册行里，有多少条 resolve 之后落在 MEDIA_ROOT/data/<username> 之外
   （订正② 的规模：0 条 ⇒ 两本账只是防御；>0 条 ⇒ 目录外那句必须真的会显示）
P2 最大那棵用户树的实扫耗时与文件数（规格 §4.4：>300ms 要停下来回设计，不许偷偷加快照表）
P3 用户根目录下第一段目录名都有哪些（决定浮层是否需要「根目录散文件」这一档）
P4 同一棵树里 bytes 是否已等于 unique_bytes（产品树有没有硬链接；不等就说明口径变了）
"""
import os
import time
from collections import Counter

from django.conf import settings

from apps.datafiles.models import DataFile
from apps.datafiles.utils import resolve_file_path


def _probe_scan(root):
    """与 Task 2 将要实现的口径同形：scandir 递归 + os.lstat，跳符号链接。"""
    total = 0
    unique = {}
    count = 0
    tops = Counter()
    if not os.path.isdir(root):
        return total, unique, count, tops
    stack = [(root, '')]
    while stack:
        cur, top = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append((entry.path, top or os.path.basename(entry.name)))
                            continue
                        st = os.lstat(entry.path)
                        total += st.st_size
                        unique[(st.st_dev, st.st_ino)] = st.st_size
                        count += 1
                        tops[top] += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, unique, count, tops


def run():
    media = str(settings.MEDIA_ROOT)
    print('MEDIA_ROOT =', media)
    users = list(
        DataFile.objects.values_list('owner__username', flat=True).distinct().order_by('owner__username')
    )
    print('有注册行的用户数 =', len(users))
    for username in users:
        root = os.path.normpath(os.path.join(media, 'data', str(username)))
        rows = DataFile.objects.filter(owner__username=username).values_list(
            'file_path', 'file_size'
        )
        prefix = root + os.sep
        in_count = in_bytes = out_count = out_bytes = 0
        outs = []
        for file_path, file_size in rows:
            abs_path = os.path.normpath(resolve_file_path(file_path or ''))
            size = int(file_size or 0)
            if abs_path.startswith(prefix):
                in_count += 1
                in_bytes += size
            else:
                out_count += 1
                out_bytes += size
                if len(outs) < 3:
                    outs.append(abs_path)
        t0 = time.perf_counter()
        total, unique, count, tops = _probe_scan(root)
        ms = (time.perf_counter() - t0) * 1000.0
        print(
            'USER %-18s exists=%-5s files=%-6d bytes=%-12d unique=%-12d %.1fms'
            % (username, os.path.isdir(root), count, total, sum(unique.values()), ms)
        )
        print('     tops=%s' % dict(tops))
        print(
            '     P1 in_root=%d (%d B)  outside=%d (%d B)%s'
            % (in_count, in_bytes, out_count, out_bytes,
               ('  e.g. %s' % outs) if outs else '')
        )
        print('     P4 bytes==unique: %s   |db_in_root 差=%d B'
              % (total == sum(unique.values()), abs(total - in_bytes)))


run()
```

- [ ] **Step 2: 跑探针（走 manage.py shell，用日常那套 settings，不要用 unit 档）**

Run:
```bash
.venv/Scripts/python.exe -X utf8 manage.py shell -c "exec(open('tasks/probe_batch2_disk_usage.py', encoding='utf-8').read())" > tasks/probe-batch2.log 2>&1
```
（引号纪律照 `frontend/e2e/data/repair-center.spec.ts:26`：外层双引号、内层只用单引号。整段落盘再读，**别用 `tail`**——lessons 2026-11-10 记过 `tail` 会吞失败名。）

Expected: 每个用户一组 `USER / tops / P1 / P4` 四行，无 traceback。

- [ ] **Step 3: 逐条判读并写回本文件末尾的「Task 1 实测结论」**

判据（三条都是硬闸，不满足就停下来汇报，别改代码绕）：

1. **P2 最大树的 `%.1fms`**：≤300ms ⇒ 按本计划继续（实扫 + TTL 缓存够用）；>300ms ⇒ 规格 §4.4 的退路是「快照表 + 增量更新」，那是新机制、本批明确不建 ⇒ **停下来**，把实测数写进 `docs/tasks/todo.md` 再决定是否拆批。
2. **P1 `outside=`**：>0 ⇒ Task 7 的「目录外 N 条」浮层行是真会显示的，Task 8 的 e2e 不许把它当死代码删掉；=0 ⇒ 那一行仍在（遗留装机是事实），但要在结论里写明「本机当前无遗留数据」。
3. **P4 `bytes==unique`**：`True` ⇒ 硬链接目前只存在于 e2e slot 镜像（`scripts/e2e_pool.mjs:113`），`unique_bytes` 是绊线字段；`False` ⇒ 产品树里已有硬链接，**停下来**汇报：那 chip 显示的表观口径要重新说明。
4. **P3 `tops`**：只有 `{'single': …, 'batch': …}` ⇒ 浮层的标签映射够用；出现别的键或 `''` ⇒ Task 6 的 `TYPE_LABELS` 兜底分支必须被 e2e 或 T2 覆盖到，不许留成没验过的分支。

- [ ] **Step 4: 提交（只提交计划文件的结论追加，探针脚本不入库）**

先把四条结论以「## Task 1 实测结论」小节追加到本文件末尾，然后：
```bash
git add docs/superpowers/plans/2026-11-14-batch2-disk-usage.md
git commit -m "docs(plan): 批2 磁盘占用探针实测四条结论回填"
```

---

### Task 2: `storage_usage.py` 的走树核心 + 口径 T1 测试

**Files:**
- Create: `apps/datafiles/storage_usage.py`
- Test: `test/backend/test_storage_usage_scan.py`

- [ ] **Step 1: 写失败测试（口径）**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan > tasks/b2-task2.log 2>&1
```
Expected: ERROR —— `ModuleNotFoundError: No module named 'apps.datafiles.storage_usage'`（导入期就崩，还没进断言）。日志末尾**不该**出现 `OK`。

- [ ] **Step 3: 写实现**

```python
# apps/datafiles/storage_usage.py
"""当前用户的磁盘占用统计（批2 · 第 5 项）。

口径（唯一事实来源：specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md §4.2；
教训原文：docs/tasks/lessons.md 2026-10-24）：

* ``bytes``        —— 逐文件 ``st_size`` 加总，**表观口径**，页面只显示这一个数。
* ``unique_bytes`` —— 按 ``(st_dev, st_ino)`` 去重后的加总，真占盘口径。产品树目前没有
  硬链接（Task 1 探针 P4 实测），所以两者相等；留着它是**绊线**：哪天有代码往用户
  目录里硬链文件，它会先于 chip 说谎，逼人重新说明口径。
* 取 inode **必须** ``os.lstat``：本机（Python 3.13.12 / Windows）实测
  ``os.DirEntry.stat()`` 的 ``st_dev``/``st_ino`` 恒为 0，用它去重会把整棵树压成
  「1 个 inode」，几 GB 直接报成几 MB。同一条教训的实现见
  ``scripts/test_data_gc.py:144 walk_inodes()``。
* DB 侧分两本账（计划头部订正②）：落在扫描根目录内的才与 ``bytes`` 可比；不在内的
  （2026-08-21 前的绝对路径遗留、样例目录、跨盘）单独计，差值恒等式只用「在内」那一本。

本模块只有口径与缓存，不碰 HTTP——视图在 ``views/usage_views.py``。
"""
import os
import time
from collections import OrderedDict

from django.conf import settings
from django.utils import timezone

from apps.common.keyed_lru import KeyedLRU
from apps.datafiles.models import DataFile
from apps.datafiles.utils import resolve_file_path

# 规格 §4.4：进程内 TTL 缓存。分桶实现没有 per-key 过期，真实过期窗口在
# [TTL, 2*TTL) 之间浮动 —— 所以浮层必须显示 scanned_at，让陈旧对用户可见。
USAGE_CACHE_TTL_SECONDS = 30
_USAGE_CACHE_MAX_ENTRIES = 64

# 规格 §4.6 的阈值：常态下差值为零，只在超阈时提示，不做常驻的第二指标。
MISMATCH_RATIO_THRESHOLD = 0.05

_usage_cache = KeyedLRU(_USAGE_CACHE_MAX_ENTRIES)


def _user_data_root(username):
    """当前用户的数据根目录 = ``MEDIA_ROOT/data/<username>``。

    用户名只来自 ``request.user``（视图里没有入参），所以这里不存在路径穿越面；
    与 ``_helpers.py:172 _user_upload_dir`` 同一种拼法，只是不到 file_type 那一层。
    """
    return os.path.normpath(
        os.path.join(str(settings.MEDIA_ROOT), 'data', str(username))
    )


def _iter_files(root):
    """产出 ``(abs_path, top, st_dev, st_ino, st_size)``；``top`` = 根下第一段目录名。

    直接躺在根下的散文件 ``top == ''``。符号链接与目录联接跳过（链接目标可能被算成
    第二份，而它并不占这个用户的空间）。单个条目或单个目录读不到就跳过：一次权限
    问题不该让整颗 chip 消失，也不该让整个请求 500 —— 少算的部分由差值行兜出。
    """
    if not os.path.isdir(root):
        return
    stack = [(root, '')]
    while stack:
        cur, top = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(
                                (entry.path, top or os.path.basename(entry.name))
                            )
                            continue
                        st = os.lstat(entry.path)
                        yield entry.path, top, st.st_dev, st.st_ino, st.st_size
                    except OSError:
                        continue
        except OSError:
            continue


def _scan_tree(root):
    """扫描 ``root``，返回 ``{'bytes','unique_bytes','file_count','by_type'}``。

    ``by_type`` 的值是 ``{'bytes': int, 'count': int}``，键为根下第一段目录名
    （``single`` / ``batch``，散文件为空串）。各桶之和恒等于总量，这条自洽性由测试钉。
    """
    total = 0
    count = 0
    seen = {}                      # (dev, ino) -> size
    by_type = OrderedDict()
    for _path, top, dev, ino, size in _iter_files(root):
        total += size
        count += 1
        seen[(dev, ino)] = size
        bucket = by_type.get(top)
        if bucket is None:
            bucket = {'bytes': 0, 'count': 0}
            by_type[top] = bucket
        bucket['bytes'] += size
        bucket['count'] += 1
    return {
        'bytes': total,
        'unique_bytes': sum(seen.values()),
        'file_count': count,
        'by_type': dict(by_type),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2 的命令，落盘到 `tasks/b2-task2.log`。
Expected: `Ran 7 tests ... OK`（其中硬链接/符号链接两条在本机都是真跑，不是 skip——Task 1 已实测本机两种链接都能建；若出现 skip 要在台账里写明哪条被跳过）。

注意 `test_目录内不可读条目被跳过而不是整体失败`：Windows 的 `os.chmod(0o000)` 不真正拒读，所以它的判据是「不抛出去」而不是「少算 1 个」。这条不要改成断言具体数字——那会把平台差异写成假红。

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/storage_usage.py test/backend/test_storage_usage_scan.py
git commit -m "feat(datafiles): 磁盘占用走树核心（表观/inode 去重/分桶）"
```

---

### Task 3: DB 两本账 + 差值恒等式

**Files:**
- Modify: `apps/datafiles/storage_usage.py`（追加 3 个函数与常量使用）
- Test: `test/backend/test_storage_usage_scan.py`（追加一个 TestCase 类）

- [ ] **Step 1: 写失败测试**

追加到 `test/backend/test_storage_usage_scan.py` 末尾（文件顶部再补这三行导入：`from django.test import TestCase`、`from apps.accounts.models import User`、`from apps.datafiles.models import DataFile`）：

```python
class DbTotalsTests(TestCase):
    """DB 侧两本账（订正②）：只有「resolve 后落在根目录内」的记录才与 bytes 可比。"""

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-db-')
        self.addCleanup(shutil.rmtree, self.base, True)
        self.user = User.objects.create_user('inroot', 'ir@localhost', 'x-pass-12345678')
        self.root = os.path.join(self.base, 'data', 'inroot')

    def _row(self, file_path, file_size):
        return DataFile.objects.create(
            owner=self.user, filename=os.path.basename(file_path),
            file_path=file_path, file_size=file_size,
            format_type='CTA8290D', status='ready',
        )

    def test_相对路径计入根内_绝对路径计入根外(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._row('data/inroot/single/a.csv', 100)
            self._row('data/inroot/batch/B1/b.csv', 250)
            self._row(os.path.join(self.base, 'elsewhere', 'c.csv'), 999)   # 遗留绝对路径
            self._row(r'C:\SampleData\d.csv', 7)                            # 根外/跨盘
            db = storage_usage._db_totals(self.user, storage_usage._user_data_root('inroot'))
        self.assertEqual(db['in_count'], 2)
        self.assertEqual(db['in_bytes'], 350)
        self.assertEqual(db['out_count'], 2)
        self.assertEqual(db['out_bytes'], 1006)

    def test_空表返回全零(self):
        with self.settings(MEDIA_ROOT=self.base):
            db = storage_usage._db_totals(self.user, storage_usage._user_data_root('inroot'))
        self.assertEqual(
            db, {'in_count': 0, 'in_bytes': 0, 'out_count': 0, 'out_bytes': 0}
        )

    def test_file_size_为_None_按0计不成报错(self):
        with self.settings(MEDIA_ROOT=self.base):
            self._row('data/inroot/single/a.csv', 0)
            DataFile.objects.filter(owner=self.user).update(file_size=None)
            db = storage_usage._db_totals(self.user, storage_usage._user_data_root('inroot'))
        self.assertEqual(db['in_count'], 1)
        self.assertEqual(db['in_bytes'], 0)


class MismatchTests(SimpleTestCase):
    """差值恒等式（规格 §4.6 + 订正③：只陈述事实，不承诺「重新扫描」能修好）。"""

    def test_阈值是严格大于_恰好5pct不算不一致(self):
        # bytes=1000、db_in_root=950 ⇒ 差 50 ⇒ ratio=0.05 ⇒ 不报
        flag, diff = storage_usage._mismatch(1000, 950)
        self.assertFalse(flag)
        self.assertEqual(diff, 50)

    def test_略超5pct报不一致(self):
        flag, diff = storage_usage._mismatch(1000, 949)
        self.assertTrue(flag)
        self.assertEqual(diff, 51)

    def test_完全没扫到文件但清单有量时报不一致(self):
        """根目录空 + DB 里有几百 MB（外部删了文件/搬走数据目录）是最该报的一种。
        分母 max(bytes,1) 在这里防的正是除零，别顺手改成除以 db_bytes。"""
        flag, diff = storage_usage._mismatch(0, 500 * 1024 * 1024)
        self.assertTrue(flag)
        self.assertEqual(diff, 500 * 1024 * 1024)

    def test_两边都为零不算不一致(self):
        flag, diff = storage_usage._mismatch(0, 0)
        self.assertFalse(flag)
        self.assertEqual(diff, 0)

    def test_清单比磁盘大或小都算(self):
        self.assertTrue(storage_usage._mismatch(1000, 2000)[0])
        self.assertTrue(storage_usage._mismatch(2000, 1000)[0])
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan > tasks/b2-task3.log 2>&1
```
Expected: `AttributeError: ... has no attribute '_db_totals'`（以及 `_mismatch`），日志末尾不是 `OK`。

- [ ] **Step 3: 写实现**

在 `apps/datafiles/storage_usage.py` 的 `_scan_tree` 之后追加：

```python
def _db_totals(user, root):
    """DB 侧合计，分成「根目录内」与「根目录外」两本账。

    ``file_size`` 是注册那一刻的 ``os.path.getsize``（``_helpers.py:123``），此后永不
    刷新 ⇒ 它只能当参考值。但更要紧的是：``store_file_path``（``utils.py:97``）对
    MEDIA_ROOT 之外/跨盘的路径**保持绝对路径**，``resolve_file_path`` 又原样透传 2026-08-21
    前的遗留绝对路径 ⇒ 这些记录指向的文件不在本函数要扫的树里。把它们混进合计，
    任何有遗留数据的装机都会常年报一条假的不一致。

    遍历形状照抄生产写法 ``views/browse_views.py:272-277``（同一份 `values_list`）。
    """
    prefix = os.path.normpath(root) + os.sep
    in_count = in_bytes = out_count = out_bytes = 0
    for file_path, file_size in DataFile.objects.filter(owner=user).values_list(
        'file_path', 'file_size'
    ):
        abs_path = os.path.normpath(resolve_file_path(file_path or ''))
        size = int(file_size or 0)
        if abs_path.startswith(prefix):
            in_count += 1
            in_bytes += size
        else:
            out_count += 1
            out_bytes += size
    return {
        'in_count': in_count,
        'in_bytes': in_bytes,
        'out_count': out_count,
        'out_bytes': out_bytes,
    }


def _mismatch(bytes_total, db_bytes_in_root):
    """规格 §4.6 的恒等式，写成一条可测的判据而不是散文。

    分母取 ``bytes``（磁盘实扫 = 真值），``max(..., 1)`` 只防空目录除零 —— 别改成除以
    ``db_bytes``，那会让「根目录空了但清单还有几百 MB」这种最该报的情况变成 100% 而
    与「清单为 0」分不清。``>`` 是严格大于：恰好等于阈值不算不一致（钉在测试里）。
    """
    diff = abs(bytes_total - db_bytes_in_root)
    ratio = diff / max(bytes_total, 1)
    return ratio > MISMATCH_RATIO_THRESHOLD, diff


def _compute_usage(user):
    """扫盘 + 查库，组出端点返回体（口径见模块 docstring）。"""
    root = _user_data_root(user.username)
    scan = _scan_tree(root)
    db = _db_totals(user, root)
    mismatch, diff = _mismatch(scan['bytes'], db['in_bytes'])
    return {
        'data_dir': root,
        'bytes': scan['bytes'],
        'unique_bytes': scan['unique_bytes'],
        'file_count': scan['file_count'],
        'by_type': scan['by_type'],
        # db_count / db_bytes 是「全量参考」；差值恒等式用的是 *_in_root 那一本。
        'db_count': db['in_count'] + db['out_count'],
        'db_bytes': db['in_bytes'] + db['out_bytes'],
        'db_bytes_in_root': db['in_bytes'],
        'db_outside_root_count': db['out_count'],
        'db_outside_root_bytes': db['out_bytes'],
        'mismatch_over_threshold': mismatch,
        'mismatch_diff_bytes': diff,
        'scanned_at': timezone.now().isoformat(),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 3 前的命令，落 `tasks/b2-task3.log`。
Expected: `Ran 15 tests ... OK`（7 + 8）。

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/storage_usage.py test/backend/test_storage_usage_scan.py
git commit -m "feat(datafiles): 占用统计的 DB 两本账与差值恒等式"
```

---

### Task 4: 视图 + 路由（必须排在 router include 之前）+ 端点契约

**Files:**
- Create: `apps/datafiles/views/usage_views.py`
- Modify: `apps/datafiles/urls.py:4-16`（导入块）、`apps/datafiles/urls.py:21`（在其**之前**插一条 path）
- Modify: `apps/datafiles/views/__init__.py:31-36`（追加一组 re-export）
- Test: `test/backend/test_files_usage_api.py`

- [ ] **Step 1: 写失败测试**

```python
# test/backend/test_files_usage_api.py
"""GET /api/v1/files/usage/ 的端点契约（T1）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_files_usage_api
造树方式与 test_batch_dir_traversal.py:68-72 同一种：临时 MEDIA_ROOT + override_settings，
树本身用 os.makedirs/open 直接写，不走上传流程（上传归 Task 8 的 e2e 管）。
"""
import os
import shutil
import tempfile

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile

PASSWORD = 'x-pass-12345678'
USAGE_URL = '/api/v1/files/usage/'
FIELDS = (
    'data_dir', 'bytes', 'unique_bytes', 'file_count', 'by_type',
    'db_count', 'db_bytes', 'db_bytes_in_root',
    'db_outside_root_count', 'db_outside_root_bytes',
    'mismatch_over_threshold', 'mismatch_diff_bytes', 'scanned_at',
)


class FileUsageApiTests(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-api-')
        self.addCleanup(shutil.rmtree, self.base, True)
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('usage_a', 'ua@localhost', PASSWORD)
        self.other = User.objects.create_user('usage_b', 'ub@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _write(self, username, rel, size):
        path = os.path.join(self.base, 'data', username, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'a' * size)
        return path

    def _get(self, **params):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.get(USAGE_URL, params)

    def test_unauthenticated_rejected(self):
        resp = APIClient().get(USAGE_URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_路由没被router的详情路由吞(self):
        """排序判据（订正①）：DefaultRouter 生成的是 `^files/(?P<pk>[^/.]+)/$`，
        `usage` 恰好匹配 `[^/.]+` ⇒ files/usage/ 必须排在 include(router.urls) 之前，
        否则这里拿到的是 404/400 而不是 200。"""
        self.assertEqual(self._get().status_code, 200)

    def test_返回体字段齐全且类型正确(self):
        self._write('usage_a', 'single/a.csv', 2048)
        data = self._get().json()
        for field in FIELDS:
            self.assertIn(field, data)
        self.assertEqual(data['bytes'], 2048)
        self.assertEqual(data['file_count'], 1)
        self.assertEqual(data['by_type'], {'single': {'bytes': 2048, 'count': 1}})
        self.assertFalse(data['mismatch_over_threshold'])
        self.assertIsInstance(data['scanned_at'], str)

    def test_data_dir指向本人目录(self):
        data = self._get().json()
        self.assertEqual(
            os.path.normpath(data['data_dir']),
            os.path.normpath(os.path.join(self.base, 'data', 'usage_a')),
        )

    def test_没有任何注册行也没有目录时返回零不报错(self):
        data = self._get().json()
        self.assertEqual(data['bytes'], 0)
        self.assertEqual(data['file_count'], 0)
        self.assertEqual(data['db_count'], 0)
        self.assertEqual(data['db_bytes'], 0)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_owner隔离_只看得到自己的目录(self):
        self._write('usage_a', 'single/a.csv', 1000)
        self._write('usage_b', 'single/b.csv', 9000)
        DataFile.objects.create(
            owner=self.other, filename='b.csv',
            file_path='data/usage_b/single/b.csv', file_size=9000,
            format_type='CTA8290D', status='ready',
        )
        mine = self._get().json()
        self.assertEqual(mine['bytes'], 1000)
        self.assertEqual(mine['db_count'], 0)

    def test_POST不接受(self):
        self.assertIn(self._post_usage().status_code, (405,)) if False else None

    def _post_usage(self):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.post(USAGE_URL, {})

    def test_清单外的遗留绝对路径单列一条不混进bytes(self):
        """订正②的形状：遗留绝对路径指向根目录外 ⇒ 只进 db_outside_root_*，
        不进 bytes，也不因为可比集合错位而报一条假的不一致。"""
        self._write('usage_a', 'single/a.csv', 1000)
        DataFile.objects.create(
            owner=self.user, filename='legacy.csv',
            file_path=os.path.join(self.base, 'legacy', 'legacy.csv'),
            file_size=4000, format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertEqual(data['bytes'], 1000)
        self.assertEqual(data['db_bytes_in_root'], 1000)
        self.assertEqual(data['db_outside_root_count'], 1)
        self.assertEqual(data['db_outside_root_bytes'], 4000)
        self.assertEqual(data['db_count'], 2)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_磁盘与清单差5pct以上时报出不一致(self):
        self._write('usage_a', 'single/a.csv', 1000)
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/usage_a/single/a.csv', file_size=100,
            format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertTrue(data['mismatch_over_threshold'])
        self.assertEqual(data['mismatch_diff_bytes'], 900)
```

删掉上面那两行占位形状（`test_POST不接受` 与 `_post_usage` 的三元式写法是我故意留给 Step 3 的错例——**不要**照它实现），改成正常的一条：

```python
    def test_只读不接受POST(self):
        self.assertEqual(self._post_usage().status_code, 405)
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_files_usage_api > tasks/b2-task4.log 2>&1
```
Expected: `AttributeError: module 'apps.datafiles.storage_usage' has no attribute 'clear_usage_cache'`，以及 `test_路由没被router的详情路由吞` 以 404 失败。

- [ ] **Step 3: 写视图**

```python
# apps/datafiles/views/usage_views.py
"""GET /api/v1/files/usage/ —— 当前用户的磁盘占用（批2 · 第 5 项，只读）。

视图里没有任何计算：口径全在 ``apps/datafiles/storage_usage.py``。
用户名只取 ``request.user``，不接受路径/用户名入参 ⇒ 没有目录穿越面。
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.datafiles.storage_usage import get_user_usage

_FALSY = ('', '0', 'false', 'False', 'null', 'undefined')


class FileUsageView(APIView):
    """返回体字段与口径说明见 storage_usage 模块 docstring。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # fresh=1 绕过 TTL 缓存：前端在每次本地写操作后带它（计划订正④），
        # 这样「上传完立刻看到新数」不必在服务端 8 个写路径各挂一次失效。
        raw = request.query_params.get('fresh', '')
        fresh = raw not in _FALSY
        return Response(get_user_usage(request.user, fresh=fresh))
```

在 `apps/datafiles/views/__init__.py` 末尾（第 36 行之后）追加：

```python
from .usage_views import (  # noqa: F401
    FileUsageView,
)
```

改 `apps/datafiles/urls.py` 的导入块，把 `FileUsageView` 加进 `from apps.datafiles.views import (...)`（按字母序放在 `FileActivateView` 之后）；再在 `path('', include(router.urls))`（`:21`）**之前**插入：

```python
    # 必须排在 router include 之前：DefaultRouter 生成的详情路由是
    # `^files/(?P<pk>[^/.]+)/$`（lookup 是 `[^/.]+`，不是 <int>，见 routers.py:143），
    # 会把 `files/usage/` 当成 pk='usage' 的详情请求吞掉。
    path('files/usage/', FileUsageView.as_view(), name='file-usage'),
```

在 `apps/datafiles/storage_usage.py` 里补上测试要的公开入口与清缓存钩子（`_compute_usage` 之后）：

```python
def get_user_usage(user, fresh=False):
    """按用户取占用统计，带进程内分桶 TTL 缓存。

    key = ``(username, bucket)``，``bucket = int(monotonic // TTL)``。为什么不用
    ``functools.lru_cache`` 也不用精确过期：仓内已有 ``KeyedLRU``（唯一一份，按条数
    封顶 + 每 key 单飞），而它只有 ``get_or_compute``/``clear`` 两个动作、没有 per-key
    过期与 per-key 删除 ⇒ 用分桶把「过期」变成「换 key」。代价是真实窗口在
    [30s, 60s) 浮动，所以返回体带 ``scanned_at`` 让陈旧可见。
    ``fresh=True`` 清整表：会顺带让别的用户重扫一次，但触发它的只是某个用户自己的
    一次写操作，代价是一次扫描，换来的是「漏挂失效钩子最多陈旧一分钟」而不是永久。
    """
    if fresh:
        _usage_cache.clear()
    bucket = int(time.monotonic() // USAGE_CACHE_TTL_SECONDS)
    return _usage_cache.get_or_compute(
        (str(user.username), bucket), lambda: _compute_usage(user)
    )


def clear_usage_cache():
    """测试隔离入口（与 ``dashboard.services.clear_dashboard_summary_cache`` 同形）。"""
    _usage_cache.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: 同 Step 2 命令，落 `tasks/b2-task4.log`。
Expected: `Ran 9 tests ... OK`。

- [ ] **Step 5: 再跑一次既有 files 契约，确认排序没碰坏 router**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_files_options_api test.backend.test_batch_dir_traversal test.backend.test_batch_files_cap > tasks/b2-task4-regress.log 2>&1
```
Expected: `OK`。这三份直接打 `/api/v1/files/...`，是「新路由有没有抢错东西」的最近距离证据。

- [ ] **Step 6: 提交**

```bash
git add apps/datafiles/views/usage_views.py apps/datafiles/views/__init__.py apps/datafiles/urls.py apps/datafiles/storage_usage.py test/backend/test_files_usage_api.py
git commit -m "feat(api): GET /files/usage/ 只读当前用户磁盘占用"
```

---

### Task 5: TTL 与 fresh 的行为判据

**Files:**
- Modify: `test/backend/test_storage_usage_scan.py`（追加一个类）

- [ ] **Step 1: 写失败测试**

追加（文件顶部补 `from unittest import mock`）：

```python
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
            with mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                first = storage_usage.get_user_usage(self.user)
                second = storage_usage.get_user_usage(self.user)
        self.assertEqual(first['bytes'], 10)
        self.assertEqual(second['bytes'], 10)
        self.assertEqual(sink, ['cacheuser'])          # 只算了一次

    def test_fresh为True时强制重算(self):
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
                storage_usage.get_user_usage(self.user)
                third = storage_usage.get_user_usage(self.user, fresh=True)
        self.assertEqual(sink, ['cacheuser', 'cacheuser'])
        self.assertEqual(third['bytes'], 20)

    def test_不同用户不共享缓存(self):
        other = User.objects.create_user('otheruser', 'o@localhost', 'x-pass-12345678')
        with self.settings(MEDIA_ROOT=self.base):
            sink = []
            with mock.patch.object(storage_usage, '_compute_usage', self._counting_compute(sink)):
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
```

- [ ] **Step 2: 跑测试确认失败或确认通过**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan.CacheBehaviourTests > tasks/b2-task5.log 2>&1
```
Expected: 这四条在 Task 4 的实现下**应当直接绿**（Task 4 已把 `get_user_usage` 写完）。若全绿，就在 commit message 里写「行为判据补齐」而**不要**假装它是 TDD 红灯产物——lessons 里记过「把补齐的测试说成先红后绿」是把纪律写脏。若某条红，按它报的形状改 `get_user_usage`，不许改测试来迁就实现。

- [ ] **Step 3: 跑整份口径文件确认没有互相踩**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan test.backend.test_files_usage_api > tasks/b2-task5b.log 2>&1
```
Expected: `Ran 23 tests ... OK`，且**没有** skip（`clear_usage_cache` 在 setUp/tearDown 各清一次，是这两份文件能同轮跑的前提）。

- [ ] **Step 4: 提交**

```bash
git add test/backend/test_storage_usage_scan.py
git commit -m "test(datafiles): 补齐占用缓存的扫描次数判据"
```

---

### Task 6: `utils/diskUsage.ts` 全部派生文案 + T2

**Files:**
- Create: `frontend/src/utils/diskUsage.ts`
- Test: `frontend/test/unit/diskUsage.spec.ts`
- Modify: `frontend/src/api/datafiles.ts:284-299`（在类型块末尾追加两个 interface）

- [ ] **Step 1: 先加类型（`frontend/src/api/datafiles.ts`，`ConsistencyFixAction` 那段之后、与 `FixConsistencyResponse` 并列的位置）**

```ts
/** GET /files/usage/ 的返回体：口径全在 apps/datafiles/storage_usage.py。 */
export interface UsageBucket {
  bytes: number
  count: number
}

export interface FileUsage {
  data_dir: string
  /** 表观口径，chip 显示的那一个数 */
  bytes: number
  /** inode 去重口径（绊线用，界面不显示） */
  unique_bytes: number
  file_count: number
  /** 根下第一段目录名为键（single / batch，散文件为空串） */
  by_type: Record<string, UsageBucket>
  db_count: number
  db_bytes: number
  db_bytes_in_root: number
  db_outside_root_count: number
  db_outside_root_bytes: number
  mismatch_over_threshold: boolean
  mismatch_diff_bytes: number
  scanned_at: string
}
```

- [ ] **Step 2: 写失败测试**

```ts
// frontend/test/unit/diskUsage.spec.ts
import { describe, expect, it } from 'vitest'

import type { FileUsage } from '../../src/api/datafiles'
import {
  usageBytesText,
  usageChipText,
  usageBreakdownRows,
  usageMismatchLine,
  usageOutsideLine,
  usageScannedText,
} from '../../src/utils/diskUsage'

const base = (over: Partial<FileUsage> = {}): FileUsage => ({
  data_dir: 'C:/x/media/data/admin',
  bytes: 0,
  unique_bytes: 0,
  file_count: 0,
  by_type: {},
  db_count: 0,
  db_bytes: 0,
  db_bytes_in_root: 0,
  db_outside_root_count: 0,
  db_outside_root_bytes: 0,
  mismatch_over_threshold: false,
  mismatch_diff_bytes: 0,
  scanned_at: '2026-11-14T06:07:08.123456+00:00',
  ...over,
})

describe('usageBytesText', () => {
  // formatSize 的 0 → '--' 是 format.spec.ts:23-25 钉住的既有契约（那边「没大小」与
  // 「0 字节」同形是可以的），但空目录是本功能的合法状态：这里必须分开。
  it('null/undefined 才是占位符，0 是 0 B', () => {
    expect(usageBytesText(null)).toBe('--')
    expect(usageBytesText(undefined)).toBe('--')
    expect(usageBytesText(0)).toBe('0 B')
  })

  it('四档边界与 formatSize 的前三档逐字一致', () => {
    expect(usageBytesText(1023)).toBe('1023 B')
    expect(usageBytesText(1024)).toBe('1.0 KB')
    expect(usageBytesText(1536)).toBe('1.5 KB')
    expect(usageBytesText(1024 * 1024 - 1)).toBe('1024.0 KB')
    expect(usageBytesText(1024 * 1024)).toBe('1.0 MB')
  })

  // GB 档是本功能新增的：formatSize 最高只到 MB，改它要动 8 个调用点，不属本批。
  it('≥1GiB 进 GB 档并保留两位', () => {
    expect(usageBytesText(1024 * 1024 * 1024)).toBe('1.00 GB')
    expect(usageBytesText(1024 * 1024 * 1024 - 1)).toBe('1024.0 MB')
    expect(usageBytesText(1.5 * 1024 * 1024 * 1024)).toBe('1.50 GB')
  })

  it('负数与 NaN 不产生 NaN 字样', () => {
    expect(usageBytesText(Number.NaN)).toBe('--')
  })
})

describe('usageChipText', () => {
  it('没拿到数据时返回 null（调用方 v-if 决定 chip 出不出现）', () => {
    expect(usageChipText(null)).toBeNull()
  })

  it('文案形态：磁盘占用 X · N 个文件', () => {
    expect(usageChipText(base({ bytes: 1288490188, file_count: 3412 })))
      .toBe('磁盘占用 1.20 GB · 3,412 个文件')
  })

  it('空目录也出一句完整的话，而不是「磁盘占用 -- · 0 个文件」', () => {
    expect(usageChipText(base())).toBe('磁盘占用 0 B · 0 个文件')
  })

  it('千位分隔走 toLocaleString（与仓内既有写法同形）', () => {
    expect(usageChipText(base({ bytes: 10, file_count: 1234567 })))
      .toBe('磁盘占用 10 B · 1,234,567 个文件')
  })
})

describe('usageBreakdownRows', () => {
  it('已知键映射中文标签，未知键原样显示，按体积从大到小', () => {
    const rows = usageBreakdownRows(base({
      by_type: {
        single: { bytes: 1024, count: 1 },
        batch: { bytes: 2048, count: 2 },
        staging: { bytes: 4096, count: 3 },
      },
    }))
    expect(rows.map((r) => r.label)).toEqual(['staging', '批次', '单文件'])
    expect(rows[0]).toEqual({ label: 'staging', sizeText: '4.0 KB', countText: '3 个文件' })
  })

  it('根目录散文件的空串键显示为「根目录散文件」', () => {
    const rows = usageBreakdownRows(base({ by_type: { '': { bytes: 5, count: 1 } } }))
    expect(rows).toEqual([{ label: '根目录散文件', sizeText: '5 B', countText: '1 个文件' }])
  })

  it('没有文件或还没扫时返回空数组（浮层靠它决定显不显空态）', () => {
    expect(usageBreakdownRows(base())).toEqual([])
    expect(usageBreakdownRows(null)).toEqual([])
  })
})

describe('usageOutsideLine / usageMismatchLine / usageScannedText', () => {
  it('目录外记录为 0 时不显（遗留装机才有）', () => {
    expect(usageOutsideLine(base())).toBeNull()
    expect(usageOutsideLine(base({ db_outside_root_count: 7, db_outside_root_bytes: 3072 })))
      .toBe('另有 7 条记录的文件不在数据目录内（3.0 KB）')
  })

  it('未超阈值不显差值行', () => {
    expect(usageMismatchLine(base())).toBeNull()
    expect(usageMismatchLine(base({ mismatch_over_threshold: true, mismatch_diff_bytes: 123456789 })))
      .toBe('清单与磁盘不一致（差 117.7 MB）：清单里的文件大小是导入当时的快照，此后不刷新')
  })

  it('统计时间缺失时返回 null，不显「统计时间 」', () => {
    expect(usageScannedText(base({ scanned_at: '' }))).toBeNull()
    expect(usageScannedText(base())?.startsWith('统计时间')).toBe(true)
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npx vitest run test/unit/diskUsage.spec.ts`
Expected: FAIL —— `Failed to resolve import "../../src/utils/diskUsage"`。

- [ ] **Step 4: 写实现**

```ts
// frontend/src/utils/diskUsage.ts
/**
 * 磁盘占用的全部派生文案（批2 · 第 5 项）。
 *
 * 为什么单独成一个 utils 文件：chip 的那一句、浮层的几行、差值行都是**会被用户读成
 * 承诺**的文案，判据该由 T2（`test/unit/diskUsage.spec.ts`）钉住，而不是散在模板里
 * 只能靠 e2e 兜。组件里只做渲染，不算字符串。
 *
 * 与 `utils/format.ts` 的 `formatSize` 的关系：**故意不复用**。两个理由都各有测试钉着：
 * 1. `formatSize(0)` 返回 `'--'` 是 `format.spec.ts:23-25` 的既有契约（那边「没大小」与
 *    「0 字节」同形无妨），但「空目录 0 字节」是本功能的合法状态，chip 必须说成 `0 B`。
 * 2. `formatSize` 最高只到 MB；GB 档要加就得动 8 个既有调用点的显示，不属本批范围。
 */
import type { FileUsage } from '../api/datafiles'

const KiB = 1024
const MiB = 1024 * KiB
const GiB = 1024 * MiB

/** 根下第一段目录名 → 中文标签。未知键原样显示（不藏数据）。 */
const TYPE_LABELS: Record<string, string> = {
  single: '单文件',
  batch: '批次',
  '': '根目录散文件',
}

export function usageBytesText(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '--'
  if (bytes < KiB) return `${bytes} B`
  if (bytes < MiB) return `${(bytes / KiB).toFixed(1)} KB`
  if (bytes < GiB) return `${(bytes / MiB).toFixed(1)} MB`
  return `${(bytes / GiB).toFixed(2)} GB`
}

export function usageChipText(usage: FileUsage | null): string | null {
  if (!usage) return null
  return `磁盘占用 ${usageBytesText(usage.bytes)} · ${usage.file_count.toLocaleString()} 个文件`
}

export interface UsageRow {
  label: string
  sizeText: string
  countText: string
}

export function usageBreakdownRows(usage: FileUsage | null): UsageRow[] {
  if (!usage) return []
  return Object.entries(usage.by_type ?? {})
    .sort((a, b) => b[1].bytes - a[1].bytes)
    .map(([key, bucket]) => ({
      label: TYPE_LABELS[key] ?? key,
      sizeText: usageBytesText(bucket.bytes),
      countText: `${bucket.count.toLocaleString()} 个文件`,
    }))
}

export function usageOutsideLine(usage: FileUsage | null): string | null {
  if (!usage || usage.db_outside_root_count <= 0) return null
  return `另有 ${usage.db_outside_root_count.toLocaleString()} 条记录的文件不在数据目录内（${usageBytesText(usage.db_outside_root_bytes)}）`
}

/**
 * 只陈述事实、不带按钮（计划订正③）：产品里没有任何路径会回写 file_size，
 * 所以「重新扫描」修不好这一行，写成动作就是谎话。
 */
export function usageMismatchLine(usage: FileUsage | null): string | null {
  if (!usage || !usage.mismatch_over_threshold) return null
  return `清单与磁盘不一致（差 ${usageBytesText(usage.mismatch_diff_bytes)}）：清单里的文件大小是导入当时的快照，此后不刷新`
}

export function usageScannedText(usage: FileUsage | null): string | null {
  if (!usage || !usage.scanned_at) return null
  const date = new Date(usage.scanned_at)
  if (Number.isNaN(date.getTime())) return null
  return `统计时间 ${date.toLocaleString('zh-CN', { hour12: false })}`
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/diskUsage.spec.ts`
Expected: PASS，15 例（`1024 * 1024 - 1` 那条走 MB 档下界、GB 档下界的边界都在里面）。

若 `usageScannedText` 的 `toLocaleString('zh-CN')` 输出与本机 ICU 版本有关，**别把精确文案写进断言**——本仓 `format.spec.ts:42-45` 已经因为「zh-CN 月日分隔符随 ICU 变化」改过一次，所以这里只钉 `startsWith('统计时间')`。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/utils/diskUsage.ts frontend/test/unit/diskUsage.spec.ts frontend/src/api/datafiles.ts
git commit -m "feat(frontend): 磁盘占用文案纯函数与 T2 判据"
```

---

### Task 7: 接线——API 方法 + FileListTab 取数 + FileListToolbar 的 chip

**Files:**
- Modify: `frontend/src/api/datafiles.ts:143-161`（在 `list`/`listFiles` 附近加 `getFileUsage`）
- Modify: `frontend/src/pages/data/components/FileListTab.vue:4-12`、`:59-62`、`:77-83`、`:100-104`、`:322-327`、`:335-340`
- Modify: `frontend/src/pages/data/components/FileListToolbar.vue:5`、`:58-83`、props/emits 块

- [ ] **Step 1: API 方法**

`frontend/src/api/datafiles.ts`，紧跟在 `listFiles`（`:146-148`）之后插入：

```ts
  /**
   * 当前用户的磁盘占用。fresh=true 绕过后端 30s 分桶缓存：本地做完一次写操作
   * （上传/删除/组合/修复）后要立刻看到新数就带它。
   */
  getFileUsage(fresh = false) {
    return api.get<FileUsage>(
      '/files/usage/',
      fresh ? { params: { fresh: 1 } } : {},
    )
  },
```

同文件顶部（`:1` 的 `import api from './index'` 之后无需新导入——`FileUsage` 就在本文件里定义）。

- [ ] **Step 2: FileListTab 取数与透传**

在 `:79` 的 `import FileListToolbar` 附近补类型导入：

```ts
import type { FileUsage } from '../../../api/datafiles'
```

在「Core state」块里（`:100` 的 `productCodes` 声明之前）加：

```ts
const usage = ref<FileUsage | null>(null)
```

在数据加载区（`loadAllTags` 之后，`:209` 后）加：

```ts
/**
 * 占用统计单独一次异步拉：它要扫盘，可能几百毫秒。
 * **不 await**、失败也只把 usage 置空 —— chip 缺席不能连累文件列表（Task 8 的
 * e2e 用 500 拦这条，钉的就是「列表照常、chip 不出现」）。
 */
async function loadUsage(fresh = false) {
  try {
    const { data } = await datafilesApi.getFileUsage(fresh)
    usage.value = data
  } catch {
    usage.value = null
  }
}
```

改 `filesVersion` watch（`:322-327`）与 `onMounted`（`:335-340`），各加一行：

```ts
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
  // 每一条本地写路径（上传/删除/批量删除/组合/修复）都会 bump filesVersion，
  // 所以这一行覆盖全部「做完就要看到新数」的场景，不需要在各处分别挂失效。
  loadUsage(true)
})

onMounted(() => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
  loadUsage()
})
```

模板里给两个子组件加 prop（`:4-12` 的 `FileListToolbar` 与 `:59-62` 的 `ConsistencyCheckDialog`）：

```vue
    <FileListToolbar
      :total="total"
      :selected-count="selectedIds.length"
      :usage="usage"
```

```vue
    <ConsistencyCheckDialog
      v-model:visible="showConsistencyCheck"
      :usage="usage"
      @done="onConsistencyDone"
    />
```

- [ ] **Step 3: FileListToolbar 渲染 chip + 浮层**

props 改成（`:62-65`）：

```ts
const props = defineProps<{
  total: number
  selectedCount: number
  usage: FileUsage | null
}>()
```

`<script setup>` 的导入（`:59-60`）补：

```ts
import { computed, ref } from 'vue'
import { Search, Delete, Upload, Tools, Collection } from '@element-plus/icons-vue'
import type { FileUsage } from '../../../api/datafiles'
import {
  usageBreakdownRows,
  usageChipText,
  usageOutsideLine,
  usageScannedText,
} from '../../../utils/diskUsage'
```

模板里 `toolbar-left`（`:3-6`）改成：

```vue
      <div class="toolbar-left">
        <span class="section-title">📋 文件列表</span>
        <span class="section-count">{{ total }} 个文件</span>
        <!-- 磁盘占用：复用 .section-count 的外观（同一族 chip，不新增字号声明，
             过 e2e/global/fonts.spec.ts 那条禁硬编码 px 的闸），浮层用 el-descriptions
             而不是自定义样式 —— popper 被 teleport 到 body，scoped CSS 够不着它。 -->
        <el-popover
          v-if="usage"
          placement="bottom-start"
          :width="300"
          trigger="hover"
          popper-class="disk-usage-popover"
        >
          <template #reference>
            <span class="section-count usage-chip" data-testid="disk-usage-chip">
              {{ usageChipText(usage) }}
            </span>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item v-for="row in usageRows" :key="row.label" :label="row.label">
              {{ row.sizeText }} · {{ row.countText }}
            </el-descriptions-item>
            <el-descriptions-item v-if="!usageRows.length" label="数据目录">
              没有文件
            </el-descriptions-item>
            <el-descriptions-item v-if="usageOutside" label="目录外记录">
              {{ usageOutside }}
            </el-descriptions-item>
            <el-descriptions-item v-if="usageScanned" label="统计时间">
              {{ usageScanned }}
            </el-descriptions-item>
          </el-descriptions>
        </el-popover>
      </div>
```

在 `const searchText = ref('')`（`:75`）之前加三个 computed（**不在模板里重复调用纯函数**，每次重渲染都调三遍是白给的计算）：

```ts
const usageRows = computed(() => usageBreakdownRows(props.usage))
const usageOutside = computed(() => usageOutsideLine(props.usage))
const usageScanned = computed(() => usageScannedText(props.usage))
```

⚠ `usageScannedText` 的返回值已经自带「统计时间 」前缀，而上面 `el-descriptions-item` 的 `label` 也是「统计时间」——这会读成「统计时间：统计时间 2026-11-14 …」。二选一：把那一行的 value 改成 `usage.scanned_at` 的裸时间串。**Task 7 采用的做法**：`utils/diskUsage.ts` 的 `usageScannedText` 改为**不带前缀**（返回 `date.toLocaleString(...)` 本身），Task 6 的 T2 断言同步改成「非空且匹配 `/^\d{4}[/\-]\d{2}[/\-]\d{2}/`」而不是 `startsWith('统计时间')`；`usageOutsideLine` 保留自带的那句完整话（它没有 label 可依附）。改完两处的注释都要说清「label 由调用方给，值只有内容」这条分工，别留给下一个人猜。

- [ ] **Step 4: 类型检查与全量 vitest**

Run:
```bash
cd frontend && npx vue-tsc -b --pretty false && npx vitest run
```
Expected: `vue-tsc` 无输出；`npx vitest run` 全绿（基线 68 文件 / 951 例，本批 +1 文件 / +15 例 ⇒ 69 / 966）。**数字必须现跑现取**，别对齐本行写的快照（lessons 的「台账写命令不写快照」）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/datafiles.ts frontend/src/pages/data/components/FileListTab.vue frontend/src/pages/data/components/FileListToolbar.vue frontend/src/utils/diskUsage.ts frontend/test/unit/diskUsage.spec.ts
git commit -m "feat(data): 文件列表工具栏显示磁盘占用 chip 与拆分浮层"
```

---

### Task 8: e2e（T3）——chip 的三条渲染判据

**Files:**
- Create: `frontend/e2e/data/disk-usage-chip.spec.ts`

- [ ] **Step 1: 写用例**

```ts
// frontend/e2e/data/disk-usage-chip.spec.ts
import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { ACCOUNTS } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'
import { uploadFile } from '../helpers/upload'
import { cleanupQuiet, deleteFilesByNameQuiet } from '../helpers/cleanup'

/**
 * 磁盘占用 chip（批2 · 第 5 项）。
 *
 * 分层纪律：体积怎么算是后端 T1 的事（test_storage_usage_scan.py），这里只钉
 * 「渲染得出、坏了不连累列表、写完一次操作会重拉」。口径不在这里重算。
 */

const CHIP = '.toolbar-left [data-testid="disk-usage-chip"]'
const USAGE_ROUTE = '**/api/v1/files/usage/**'

/** 浏览器里读一次端点（与 repair-center.spec.ts:36 同一种拿法）。 */
function apiGet(page: Page, url: string) {
  return page.evaluate(async (u) => {
    const token = localStorage.getItem('access_token')
    const res = await fetch(`/api/v1${u}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    return { status: res.status, body: await res.json() }
  }, url)
}

/**
 * 判据异源：spec 里**自己再实现一遍**四档格式化。
 * 不是为了省一次比对，而是为了让「组件偷偷读错字段」（bytes ↔ unique_bytes、
 * file_count ↔ db_count）这条路必须红——复用 src 里的同一个函数就只会证明同一条
 * 代码等于自己。
 */
function bytesText(bytes: number): string {
  const KiB = 1024
  const MiB = 1024 * KiB
  const GiB = 1024 * MiB
  if (bytes < KiB) return `${bytes} B`
  if (bytes < MiB) return `${(bytes / KiB).toFixed(1)} KB`
  if (bytes < GiB) return `${(bytes / MiB).toFixed(1)} MB`
  return `${(bytes / GiB).toFixed(2)} GB`
}

test.describe('磁盘占用 chip', { tag: ['@p2', '@data'] }, () => {
  test('chip 文案与端点返回体逐字一致（透传捕获，不靠再猜一次缓存桶）', async ({ page }) => {
    // 用 route 透传把 app 自己那一次读取的响应体留下来 —— 不能再 apiGet 一次去比：
    // 后端缓存是按 30s 分桶的，两次读取跨桶就会给出不同的 scanned_at/数值。
    let captured: any = null
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
      captured = json
      await route.fulfill({ response, json })
    })

    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    expect(captured, 'app 应当真的拉过一次 /files/usage/').not.toBeNull()
    expect(captured.file_count, 'seed 后 admin 至少该有一个文件').toBeGreaterThanOrEqual(1)
    await expect(chip).toHaveText(
      `磁盘占用 ${bytesText(captured.bytes)} · ${captured.file_count.toLocaleString()} 个文件`,
    )
  })

  test('占用接口坏掉时列表照常渲染，chip 不出现', async ({ page }) => {
    await page.route(USAGE_ROUTE, (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'internal_error', message: 'boom' }),
      }),
    )
    await gotoApp(page, '/data')
    // 列表必须照常（占用是附赠信息，不许连累主功能）
    await expect(page.locator('.list-toolbar .section-count').first()).toBeVisible({ timeout: 20_000 })
    await expect(page.locator(CHIP)).toHaveCount(0)
  })

  test('上传一个文件后以 fresh=1 重拉，计数 +1 且 chip 变文案', async ({ page }) => {
    const uniqueName = `e2e_usage_${Date.now()}`
    const tmpPath = path.join(os.tmpdir(), `${uniqueName}.csv`)
    fs.writeFileSync(tmpPath, 'col1,col2\n1,2\n')

    try {
      await gotoApp(page, '/data')
      const chip = page.locator(CHIP)
      await expect(chip).toBeVisible({ timeout: 20_000 })
      const before = await apiGet(page, '/files/usage/?fresh=1')
      expect(before.status).toBe(200)
      const beforeText = await chip.innerText()

      // 先挂等待再触发：onUploadSuccess → notifyFilesChanged → loadUsage(true)
      // 是在上传响应之后才发生的，顺序反了就会等到超时。
      const refreshed = page.waitForResponse((r) =>
        r.url().includes('/api/v1/files/usage/') && r.url().includes('fresh=1'),
      )
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadFile(page, tmpPath)

      const resp = await refreshed
      const after = await resp.json()
      expect(after.file_count, '刚上传的那一个文件必须被计入').toBe(before.body.file_count + 1)
      await expect(chip).not.toHaveText(beforeText)
    } finally {
      // R2③ 自建/自清：这一行 col1/col2 没有 Site 列，留在库里会顶到 files[0]
      // 污染按文件推进的其它用例（upload-csv-only.spec.ts:43-48 记过同一条）。
      await deleteFilesByNameQuiet(page, 'e2e_usage_')
      cleanupQuiet(tmpPath)
    }
  })

  test('浮层能展开并给出与 chip 同一份拆分', async ({ page }) => {
    let captured: any = null
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json = await response.json()
      captured = json
      await route.fulfill({ response, json })
    })
    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    await chip.hover()

    // popper 被 teleport 到 body：判据走 popper 自己的 class（本仓 e2e 纪律——
    // 用 :visible 判「哪个浮层开着」在同页多浮层时不可靠）。
    const popper = page.locator('.el-popper.disk-usage-popover')
    await expect(popper).toBeVisible({ timeout: 10_000 })
    const total = await popper.locator('.el-descriptions__cell').allInnerTexts()
    const joined = total.join(' ')
    for (const key of Object.keys(captured.by_type ?? {})) {
      const label = key === 'single' ? '单文件' : key === 'batch' ? '批次' : key
      expect(joined, `浮层里必须有 ${key} 这一桶`).toContain(label)
    }
    expect(joined).toContain(String(captured.file_count))
    await expect(page.locator(CHIP)).toBeVisible()
  })

  test('新用户目录为空时 chip 说 0 B 而不是 --', async ({ page }) => {
    // 这条钉的是「空目录是合法状态」：formatSize 的 0 → '--' 在别处合理，
    // 在这里会被读成「还没算出来」。判据在 T2（diskUsage.spec.ts）也钉了一份。
    const body = await apiGet(page, '/files/usage/') // 需要登录态：见下面的 todo
    expect(body.status).toBe(200)
  })
})
```

最后那条「新用户」用例先**别实现**：它要一个没有数据目录的账号，而 P2 project 的 `storageState` 固定是 `ADMIN_STATE`（`playwright.config.ts:144`），换账号得走 `helpers/auth.ts` 的登录路径，代价比判据值钱——而 0 B 这条形状已经被 Task 6 的 T2 完整钉住（`usageChipText(base())` ⇒ `'磁盘占用 0 B · 0 个文件'`）。**删掉它**，并在文件头注释里写明「空目录态由 T2 钉，不在浏览器里重算」。留一条半成品用例会变成下一个人的坑。

- [ ] **Step 2: 跑用例（单文件自起服务，先确认端口没被抢）**

Run:
```bash
netstat -ano | grep -E ":8000|:3000" | head -5
cd frontend && node ../scripts/e2e_pool.mjs --slots=1 -- e2e/data/disk-usage-chip.spec.ts > ../tasks/b2-task8.log 2>&1
```
Expected: 日志末行 `RESULT:` 之前有 `[pool] 结论 MEASURED`、`unexpected 0`。**判绿取这两行，不取退出码**（lessons/testing-gates）。若日志里出现 `EADDRINUSE`/`21001-21004` 段，是上一轮孤儿 slot 目录占着端口——先 `node scripts/e2e_pool.mjs --gc`，别改 workers 数。

- [ ] **Step 3: 若第一条红，按这个顺序排查（别先改代码）**

1. `captured` 是 `null` ⇒ app 根本没发这一请求 ⇒ Task 7 的 `loadUsage()` 没进 `onMounted`。
2. `toHaveText` 只差千位分隔符 ⇒ `toLocaleString()` 的 locale 与 Node 不一致；改成在 spec 里也 `Number(x).toLocaleString('en-US')`，**两边同参**，别改组件。
3. 第三条 `file_count + 1` 不成立 ⇒ 多半是 `fresh=1` 没带上（`params: { fresh: 1 }` 被 `paramsSerializer` 改写了）；打印 `resp.url()` 确认串里有 `fresh=1`。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/data/disk-usage-chip.spec.ts
git commit -m "test(e2e): 磁盘占用 chip 的渲染与写后刷新判据"
```

---

### Task 9: 数据修复中心的差值行

**Files:**
- Modify: `frontend/src/pages/data/components/ConsistencyCheckDialog.vue:22-43`（`el-descriptions` 之后）、`:99-128`（props 与导入）

- [ ] **Step 1: 接 prop 与渲染**

`<script setup>` 里（`:103` 的 api 导入行补类型，`:110-112` 的 props 加字段）：

```ts
import { datafilesApi, type ConsistencyCheckResult, type ConsistencyFixAction, type FileUsage, type FixConsistencyResponse } from '../../../api/datafiles'
import { usageMismatchLine } from '../../../utils/diskUsage'

const props = defineProps<{
  visible: boolean
  usage: FileUsage | null
}>()
```

在 `result.value` 声明附近（`:128` 之后）加：

```ts
// 差值行读的是**已经拉过的那次占用**，不在这个对话框里再扫一遍盘（规格 §4.6：
// 它只是一个「清单与磁盘对不上」的提示，不是一个第二指标）。
const mismatchLine = computed(() => usageMismatchLine(props.usage))
```

模板里紧跟 `</el-descriptions>`（`:43`）之后插入：

```vue
      <!-- 清单/磁盘差值（规格 §4.6 + 计划订正③）：只陈述事实、不给动作按钮——
           产品里没有任何路径会回写 file_size，「重新扫描」修不好这一行。 -->
      <el-alert
        v-if="mismatchLine"
        :title="mismatchLine"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
```

- [ ] **Step 2: 补 e2e 用例（追加到 `disk-usage-chip.spec.ts` 的 describe 里）**

```ts
  test('占用差值超阈值时，数据修复中心多一行且文案带上那个差值', async ({ page }) => {
    // 透传注入：只翻 mismatch 两个字段，其余（bytes/file_count/by_type）保持真实，
    // 这样这一条同时钉住「行与 chip 读的是同一份数据」+「阈值驱动的是布尔而不是猜」。
    await page.route(USAGE_ROUTE, async (route) => {
      const response = await route.fetch()
      const json: any = await response.json()
      json.mismatch_over_threshold = true
      json.mismatch_diff_bytes = 123456789   // ⇒ 差 117.7 MB
      await route.fulfill({ response, json })
    })

    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    await page.locator('button').filter({ hasText: '数据修复' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '数据修复中心' })
    await expect(dialog).toBeVisible()
    await dialog.locator('button').filter({ hasText: '开始检查' }).click()
    await expect(dialog.locator('.el-descriptions')).toBeVisible({ timeout: 60_000 })

    const alert = dialog.locator('.el-alert').filter({ hasText: '清单与磁盘不一致' })
    await expect(alert).toBeVisible()
    await expect(alert).toContainText('差 117.7 MB')
    // 只陈述、不动作：这一行不许带任何按钮
    await expect(alert.locator('button')).toHaveCount(0)
  })

  test('未超阈值时数据修复中心不显差值行', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    await page.locator('button').filter({ hasText: '数据修复' }).click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '数据修复中心' })
    await expect(dialog).toBeVisible()
    await dialog.locator('button').filter({ hasText: '开始检查' }).click()
    await expect(dialog.locator('.el-descriptions')).toBeVisible({ timeout: 60_000 })
    await expect(dialog.locator('.el-alert').filter({ hasText: '清单与磁盘不一致' })).toHaveCount(0)
  })
```

- [ ] **Step 3: 跑本文件的六条**

Run:
```bash
cd frontend && node ../scripts/e2e_pool.mjs --slots=1 -- e2e/data/disk-usage-chip.spec.ts > ../tasks/b2-task9.log 2>&1
```
Expected: `[pool] 结论 MEASURED` + `unexpected 0`。
第二条（未超阈值不显）依赖**真实数据恰好没超 5%**——若本机 dev 库正好超阈值，它就会红。这条不许改成「先看一眼再断言」：红了就按 `docs/tasks/todo.md` 里 Task 1 记的差值实测归因，必要时给它也加一条透传注入（把 `mismatch_over_threshold` 强制 `false`），并在注释里写明是注入才成立，别把「常态下差值为零」当成前提。

- [ ] **Step 4: affected 门禁（本批改动面全跑）**

Run:
```bash
cd frontend && npm run test:e2e:affected > ../tasks/b2-affected.log 2>&1
```
Expected: 末行 `RESULT: PASS`（档名逐条 `ok`）。跳过/失败要按 testing-gates 的判据归因，不许直接重跑一遍交差。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/data/components/ConsistencyCheckDialog.vue frontend/e2e/data/disk-usage-chip.spec.ts
git commit -m "feat(data): 修复中心按阈值露出清单与磁盘差值"
```

---

### Task 10: 收口门禁、实测数与台账

**Files:**
- Modify: `docs/tasks/todo.md`（新增一节 `# 任务：批2 磁盘占用（2026-11-14）`）
- Modify: `docs/superpowers/plans/2026-11-14-batch2-disk-usage.md`（末尾「落地后的订正」）
- 可能 Modify: `docs/tasks/lessons.md`（只有真踩到新坑才加）

- [ ] **Step 1: 全量池 + 后端 + build（收口档，独占跑）**

Run:
```bash
cd frontend && node ../scripts/e2e_pool.mjs --slots=4 > ../tasks/b2-pool.log 2>&1
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test > ../tasks/b2-backend.log 2>&1
grep -cE "^(FAIL|ERROR):" ../tasks/b2-backend.log
cd frontend && npm run build > ../tasks/b2-build.log 2>&1
npx vitest run
npm run lint:e2e
```
Expected:
- 池：`[pool] 结论 MEASURED`、`unexpected 0`、末行 `RESULT:`；批1 基线是 87 文件 / 460 例，本批 **+1 文件 / +6 例**，但**以现读数为准**。
- 后端：`OK`（批1 基线 `Ran 2576 … OK (skipped=16)`，本批 +23 例左右），`grep -cE "^(FAIL|ERROR):"` 必须是 **0**。
- `npm run build`（含 `vue-tsc -b`）成功；`npx vitest run` 全绿；`npm run lint:e2e` 干净。
- 后端档**整段落盘再 grep**，不要用 `| tail`（lessons 2026-11-10：`tail` 会吞失败名）。

- [ ] **Step 2: 行数与豁免账自检**

Run: `cd frontend && node ../scripts/line-limit.mjs`
Expected: 无违规。本批新增文件都远低于 600（最大的 `test_files_usage_api.py` 约 170 行），且**没有**给任何文件加豁免——加了要在台账里写理由。

- [ ] **Step 3: 实测耗时与口径数落进台账（验收硬条）**

规格 §4.4 那条「>300ms 则回到设计，不偷偷加快照表」要有实测数背书。`docs/tasks/todo.md` 新增的批2 一节至少包含：

```markdown
# 任务：批2 磁盘占用（2026-11-14，计划 docs/superpowers/plans/2026-11-14-batch2-disk-usage.md）

- 探针实测（`manage.py shell -c "exec(open('tasks/probe_batch2_disk_usage.py', encoding='utf-8').read())"`）：
  - 最大用户树 <N> 个文件、<X> ms（判据：≤300ms ⇒ 实扫 + 30s 分桶缓存够用，未建快照表）
  - 根目录外记录：<Y> 条 / <Z> B（订正② 的规模）
  - bytes == unique_bytes：<True/False>（False 则说明产品树已有硬链接）
- 端点：`/api/v1/files/usage/`（`path` 排在 `include(router.urls)` 之前，否则被 `[^/.]+` 详情路由吞）
- 规格四处订正：① 路由前提 ② DB 两本账 ③ 差值行无动作（无处回写 file_size）④ 失效改客户端 fresh=1
- 门禁：<命令 + 现读结果>
- 本批不做（留给配额批）：逐用户列表、`storage_limit_bytes` 字段、上传拦截、`refresh_file_sizes` 修复动作、快照表
```

台账里所有数字必须是**这一轮现跑出来的**（lessons：「台账写命令不写快照」，判据给命令、结论给数）。

- [ ] **Step 4: 提交**

```bash
git add docs/tasks/todo.md docs/superpowers/plans/2026-11-14-batch2-disk-usage.md
git commit -m "docs(ledger): 批2 磁盘占用收口实测与台账"
```

- [ ] **Step 5: 收尾由用户选路径（finishing-a-development-branch）**

不 push（`origin` 是公开远端，一次 push 即全球发布）。批1 的收口方式是 `--ff-only` 并入本地 master 并记录 tree-hash 相等作为门禁沿用依据，本批照同一形状做，但要**先问**再并。

---

## Self-Review（写完计划后自查）

**1. 规格覆盖（逐条 §4 → Task）**

| 规格 | 落在 |
|---|---|
| §4.1 端点 + 返回体 8 个字段 | Task 2（scan 字段）+ Task 3（`_compute_usage` 组装）+ Task 4（视图与路由）；字段按订正②/③ 增加了 5 个 |
| §4.2 口径纪律（lstat/inode、rglob 交叉核对、页面只显一个数） | Task 2 的 `test_硬链接按inode只计一次` 与 `test_口径交叉核对_用rglob独立加总必须相等`；只显一个数在 Task 7 的 `usageChipText` |
| §4.3 数据源选扫盘 | Task 3 的两本账 + `db_bytes` 只作参考（Task 6 不把它放进 chip） |
| §4.4 性能（TTL 缓存、失效、实测） | Task 4 `get_user_usage` + Task 5 四条行为判据 + Task 1 P2 + Task 10 Step 3 |
| §4.5 展示（chip 文案、hover 拆分、字号 token） | Task 6（文案纯函数）+ Task 7（chip + 浮层 + `--p-fs-*` 复用 `.section-count`）+ Task 8（渲染与 hover） |
| §4.6 差值露出（阈值恒等式、修复对话框一行） | Task 3 `test_阈值是严格大于…` 等 5 条 + Task 9 |
| §4.7 配额只做到「当前用户」 | 全程无新字段、无逐用户列表；Task 10 Step 3 的「本批不做」清单写死 |
| §4.8 测试（T1 齐全/空目录/隔离/缓存/交叉核对；T3 chip 渲染） | Task 2/3/4/5（T1，共 23 例）+ Task 6（T2，15 例）+ Task 8/9（T3，6 例） |

**2. 占位符扫描**：无 TBD/「类似 Task N」/「加适当错误处理」。两处「故意写错再改」是显式教学步骤（Task 4 Step 1 的 `test_只读不接受POST`、Task 8 Step 1 末尾删掉那条用例），都写明了删/改的动作为什么，不是留白。

**3. 类型一致性**：`_scan_tree` 返回的键（`bytes`/`unique_bytes`/`file_count`/`by_type`）= `_compute_usage` 用的键 = `FileUsage` 的字段 = e2e 的 `captured.*`。`_db_totals` 的 `in_count/in_bytes/out_count/out_bytes` 只在 Task 3/4 内部与 `_compute_usage` 的映射处出现，未泄漏到前端。`get_user_usage(user, fresh=…)` / `clear_usage_cache()` 在 Task 4/5 用法一致。前端 6 个函数名在 Task 6 定义、Task 7/9 调用，逐字相同。Task 7 Step 3 的 ⚠ 要求 `usageScannedText` 去掉前缀并同步 Task 6 的断言——这条改动要在 Task 6→7 之间落地，别只改一边。

---

## Task 1 实测结论（Step 3 回填，写代码前完成）

（待填 —— 四条判据 + 最大树 ms/文件数 + 根外记录数 + bytes==unique 结果）
