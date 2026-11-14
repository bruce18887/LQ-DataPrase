# 批2 · 磁盘占用量 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 数据管理页显示当前用户真实磁盘占用（`GET /api/v1/files/usage/` 逐文件实扫 + 30s 分桶缓存），并在数据修复中心按阈值露出「清单记录与磁盘不一致」。

**Architecture:** 后端一个新模块 `apps/datafiles/storage_usage.py` 承担全部口径（`os.scandir` + `os.lstat` 走树、inode 去重、DB 侧分「在根目录内/在外」两本账、差值恒等式），一个新 APIView 只做鉴权与取数，路由**排在 router include 之前**。前端 `utils/diskUsage.ts` 收全部派生文案（可 T2 钉），`FileListToolbar.vue` 只渲染一颗复用 `.section-count` 样式的 chip + `el-descriptions` 浮层；占用数据由 `FileListTab.vue` 异步拉一次，并在既有的 `filesStore.filesVersion` watch 里以 `fresh=1` 重拉，因此不需要在 8 个写路径分别挂失效钩子。

**Tech Stack:** Django 5 / DRF（`DefaultRouter` 生成的详情路由 lookup 是 `[^/.]+`）、`apps/common/keyed_lru.py` 的 `KeyedLRU`（进程内、按条数封顶、每 key 单飞）、Vue 3 `<script setup>` + Element Plus 2.14、Vitest（T2）、Playwright（T3，`page.route` 透传改写响应的既有范式）。

---

## 规格订正（写代码前读；①–⑤ 是设计稿与实测/代码的差异，一律以代码为准）

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

**订正⑤（§4.6 的恒等式在真实数据上会说一件已经被别人说过的事）** Task 1 追加探针 `tasks/probe_batch2_diff_cause.py` 在本机 dev 库实测拆开四个量：

```
A 磁盘实扫            : 112 个文件, 1,612,886,366 B (1.50 GB)
B 注册行且文件在盘上   : 112 行, 清单 1,612,886,366 B, 实际 1,612,886,366 B   ← 漂移 0 B
C 注册行但文件已不在盘 : 73 行, 清单 286,358,763 B   ← 修复中心已在报的「孤立数据库记录」
D 盘上有文件但无注册行 : 0 个, 0 B                   ← 修复中心已在报的「孤立磁盘文件」
旧口径 ratio=0.1775（永远红）／新口径 ratio=0.0000（安静）
```

按稿子的 `abs(bytes - db_bytes)/bytes`，本机现在就会常年挂一条「清单与磁盘不一致（差 273 MB）」，而它的**全部来源是那 73 条已经不存在的文件**——同一件事修复中心的孤立记录卡已经报过，只是单位不同（条 vs MB）。稿子 §4.6 自己说「常态下差值为零」，实测证明这句话只对「文件都在」的常态成立。
⇒ 处置：差值恒等式只比**交集**——「注册行 ∩ 文件确实在盘上」这一集合里，`Σ file_size`（清单值）与 `Σ st_size`（实际值）的差。这样这一行从此只说一件事：**清单里的大小数字过期了**；文件缺失归孤立记录卡、磁盘孤儿归孤立磁盘卡，三个信号不再互相重复。
⇒ 顺带的收益：Task 9 的「未超阈值时不显差值行」这条 e2e 在真实 dev 数据上是**诚实的绿**（新口径 ratio=0），不需要为了通过而注入假数据。


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
| `tasks/probe_batch2_disk_usage.py`、`tasks/probe_batch2_diff_cause.py` | 新建（**不入库**，`tasks/*` 被 gitignore） | Task 1 的两份探针；实测数回填本文件末尾「Task 1 实测结论」 |
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
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan > tasks/b2-task2-red.log 2>&1
```
Expected（2026-11-14 实跑校准过）：
```
ImportError: cannot import name 'storage_usage' from 'apps.datafiles'
Ran 1 test in 0.000s
FAILED (errors=1)
```
两个反直觉的点，别当成红错了：① 报的是 `ImportError` 而**不是** `ModuleNotFoundError`——因为测试用的是 `from apps.datafiles import storage_usage` 这种属性式导入，缺子模块时走的是 ImportError 分支；② 只 `Ran 1 test`——导入失败时 loader 用一个合成的 `_FailedTest` 顶位。日志末尾**不该**出现 `OK`。红绿两轮分别落 `tasks/b2-task2-red.log` 与 `tasks/b2-task2-green.log`，**别共用文件名**（初稿共用，结果那一轮红没留下证据）。

- [ ] **Step 3: 写实现**

> ⚠ 下面是初稿版本。**落地版有 5 处差异**（复审驱动），全部列在文末「Task 2 落地后的订正」——
> 其中一处是初稿的测试**没有判别力**（把 `os.lstat` 换成 `os.DirEntry.stat()` 后 7 例仍全绿），
> 已改掉。接手时以落地版 `apps/datafiles/storage_usage.py`（118 行）为准。

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

# 规格 §4.6 的阈值：只在超阈时提示，不做常驻的第二指标。
# 「常态下差值为零」这句在旧口径（全量比全量）下实测不成立（本机 dev ratio=0.1775，全是已删文件
# 造成的），改成订正⑤ 的交集口径后才成立 —— 改回全量比全量就会让这条阈值永远红。
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


def _scan_tree(root, registered=None):
    """扫描 ``root``。返回 ``{'bytes','unique_bytes','file_count','by_type'}``，
    传了 ``registered`` 再附 ``{'registered_count','registered_db_bytes','registered_disk_bytes'}``。

    ``by_type`` 的值是 ``{'bytes': int, 'count': int}``，键为根下第一段目录名
    （``single`` / ``batch``，散文件为空串）。各桶之和恒等于总量，这条自洽性由测试钉。

    ``registered`` 是 ``{normcase 后的绝对路径: 清单里记的 file_size}``（Task 3 的
    ``_db_map`` 造）。在同一次走树里顺手把「注册行 ∩ 文件确实在盘上」这个交集的两侧各自
    累计出来 —— 这是订正⑤ 的实现位置：差值只比交集，所以缺文件与磁盘孤儿都不会混进来，
    而且**不用第二次走树**。不传就是纯总量扫描（Task 2 的测试与将来的独立复用都走这条）。
    查表前必须 ``os.path.normcase(path)``：map 的键是 normcase 过的，而 ``entry.path`` 不是，
    Windows 上少这一步交集恒为空 —— 表现成「差值全是清单值」而不是报错。
    """
    total = 0
    count = 0
    seen = {}                      # (dev, ino) -> size
    by_type = OrderedDict()
    reg_count = reg_db = reg_disk = 0
    for path, top, dev, ino, size in _iter_files(root):
        total += size
        count += 1
        seen[(dev, ino)] = size
        bucket = by_type.get(top)
        if bucket is None:
            bucket = {'bytes': 0, 'count': 0}
            by_type[top] = bucket
        bucket['bytes'] += size
        bucket['count'] += 1
        if registered is not None:
            db_size = registered.get(os.path.normcase(path))
            if db_size is not None:
                reg_count += 1
                reg_db += int(db_size)   # map 的值就是 _db_map 里那个 int，不需要 `or 0`
                reg_disk += size
    result = {
        'bytes': total,
        'unique_bytes': sum(seen.values()),
        'file_count': count,
        'by_type': dict(by_type),
    }
    if registered is not None:
        result['registered_count'] = reg_count
        result['registered_db_bytes'] = reg_db
        result['registered_disk_bytes'] = reg_disk
    return result
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

### Task 3: DB 映射（两本账）+ 交集差值恒等式

**Files:**
- Modify: `apps/datafiles/storage_usage.py`（追加 `_db_map` 与 `_mismatch`，改 `_compute_usage`）
- Test: `test/backend/test_storage_usage_scan.py`（追加三个类）

- [ ] **Step 1: 写失败测试**

追加到 `test/backend/test_storage_usage_scan.py` 末尾（文件顶部再补这三行导入：`from django.test import TestCase`、`from apps.accounts.models import User`、`from apps.datafiles.models import DataFile`）：

```python
class DbMapTests(TestCase):
    """DB 侧两本账（订正②）：只有「resolve 后落在根目录内」的记录才可与磁盘比。

    两套计数各有用途，别混：``in_rows`` / ``in_bytes`` 是**行**口径（进返回体的 db_*），
    ``in_files`` 与 map 是**文件**口径（交集差值用它 —— 磁盘上只有那颗）。

    这里**没有** ``file_size is None`` 的用例，实现里也没有 ``or 0`` 兜底：见上面 `_db_map`
    里那段说明 —— 那个状态真库里造不出来。
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
        """记录还在、文件早没了 —— 那是孤立记录卡的活；再用 MB 说一遍会让人以为有两个毛病。"""
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

    def test_清单大还是磁盘大都算(self):
        self.assertTrue(storage_usage._mismatch(10000, 1000, 2000)[0])
        self.assertTrue(storage_usage._mismatch(10000, 2000, 1000)[0])


再追加 **ComputeUsageTests**（落地后补的，理由见文末「控制器复核后的再订正」第 2 条：`_compute_usage` 是装配层，而前面所有用例都直接打在 `_scan_tree` / `_db_map` / `_mismatch` 上 —— 装配时把清单侧换成行口径的 `db['in_bytes']`，29 条全绿。判据不能只打在零件上，装配点要自己有一条）：

```python
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
```
```

- [ ] **Step 2: 跑测试确认失败**

Run:
```bash
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_storage_usage_scan > tasks/b2-task3.log 2>&1
```
Expected: `AttributeError: module 'apps.datafiles.storage_usage' has no attribute '_db_map'`（以及 `_mismatch`），且 `test_不传registered时只回四个总量键` 通过。日志末尾**不该**是 `OK`。

注：Task 2 已经把 `_scan_tree(root, registered=...)` 的参数实现了，所以那三条走交集的用例第一次跑会先红在 `_db_map` 缺失上，而不是红在 `TypeError` —— 这是预期的（判据要看到 `_db_map`/`_mismatch` 确实不存在）。

- [ ] **Step 3: 写实现**

把 `apps/datafiles/storage_usage.py` 做两件事：**(a)** 在文件顶部的 import 段**增量补三行**（Task 2 复审指出「别为后面的任务预埋死代码」，所以只加本任务真正用到的；现有的 `import os`、`from collections import OrderedDict`、`from django.conf import settings` 不动）：

```python
from django.utils import timezone          # 本任务的 _compute_usage 用

from apps.datafiles.models import DataFile   # 本任务的 _db_map 用
from apps.datafiles.utils import resolve_file_path  # 本任务的 _db_map 用
```

再在 import 段之后加一个常量：

```python
# 规格 §4.6 的阈值：只在超阈时提示，不做常驻的第二指标。
# 「常态下差值为零」这句在旧口径（全量比全量）下实测不成立（本机 dev ratio=0.1775，
# 全部来自 73 条已删文件），换成订正⑤ 的交集口径后才成立 —— 改回全量比全量
# 就会让这条阈值在每台有遗留数据的装机上永远红。
MISMATCH_RATIO_THRESHOLD = 0.05
```

`time` / `KeyedLRU` / `USAGE_CACHE_TTL_SECONDS` / `_usage_cache` 是 Task 4 的 `get_user_usage` 要用的，**留给 Task 4 再加**，本任务不要提前带。

**(b)** 在 `_scan_tree` 之后写入下面三个函数（Task 2 没有 `_db_map`/`_mismatch`/`_compute_usage`，本任务是它们的出处）：

```python
def _db_map(user, root):
    """该用户的注册行，分成「根目录内（做成 map）」与「根目录外（只记账）」。

    ``file_size`` 是注册那一刻的 ``os.path.getsize``（``_helpers.py:123``），此后永不刷新
    ⇒ 只能当参考值。更要紧的是 ``store_file_path``（``utils.py:97``）对 MEDIA_ROOT 之外/
    跨盘的路径**保持绝对路径**、``resolve_file_path`` 又原样透传 2026-08-21 前的遗留绝对
    路径 ⇒ 那部分记录指向的文件根本不在本模块要扫的树里，混进合计就会常年报一条假的不一致
    （计划订正②）。

    键统一 ``os.path.normcase(os.path.normpath(...))``：Windows 路径大小写不敏感，DB 里写
    ``data/INROOT/...`` 而磁盘上是 ``data/inroot/`` 时不做 normcase 会让那条在交集里**凭空
    消失**。注意消失的方向：``reg_db`` 与 ``reg_disk`` 是一起少的，所以差值会变成 0、
    该报的不报（假绿），不是冒出一条虚高差值 —— 护栏是 Task 3 断言
    ``registered_count == 1``，不是差值行。

    遍历形状照抄生产写法 ``views/browse_views.py:272-277``（同一份 values_list），但**加
    ``order_by('id')``**：同一个路径上有重复注册行是已知状态（批3 整批就在处理它），
    map 按路径去重 ⇒ 不加排序的话胜者取决于数据库返回顺序，差值会在两次请求之间翻脸，
    还在 30s TTL 里冻住一个。``order_by('id')`` 把胜者定死成 id 最大的那条。

    返回的口径分两套：``in_rows``/``in_bytes`` 是**行**口径（返回体里的 db_* 用它），
    ``in_files`` = ``len(map)`` 与 map 本身是**文件**口径（交集差值用它）。
    """
    prefix = os.path.normcase(os.path.normpath(root)) + os.sep
    registered = {}
    in_rows = in_bytes = out_count = out_bytes = 0
    for file_path, file_size in DataFile.objects.filter(owner=user).order_by('id').values_list(
        'file_path', 'file_size'
    ):
        abs_path = os.path.normcase(os.path.normpath(resolve_file_path(file_path)))
        # 没有 `or 0` / `file_path or ''` 兜底：file_size 是 BigIntegerField(null=False)、
        # file_path 是 CharField(max_length=512)（0001_initial.py:22-23），两个 NULL 状态
        # 在真库里都造不出来（实测 update(file_size=None) ⇒ sqlite3.IntegrityError）。
        # 为不可能的状态写兜底，就得连带 mock 掉整个 ORM 来「造」那个状态 ——
        # 判据假象，且会让下一个人以为这种数据存在过。
        size = int(file_size)
        if abs_path.startswith(prefix):
            in_rows += 1
            in_bytes += size
            registered[abs_path] = size
        else:
            out_count += 1
            out_bytes += size
    return {
        'map': registered,
        'in_rows': in_rows,
        'in_files': len(registered),
        'in_bytes': in_bytes,
        'out_count': out_count,
        'out_bytes': out_bytes,
    }


def _mismatch(bytes_total, registered_disk_bytes, registered_db_bytes):
    """规格 §4.6 的恒等式，但两侧都只取交集（订正⑤）。

    ``registered_disk_bytes`` = 交集里每条的**实际** st_size 之和；
    ``registered_db_bytes``   = 同一条条的**清单** file_size 之和。
    于是这一行只说一件事：**清单里的大小数字过期了**。
    文件已删（=孤立数据库记录）与磁盘孤儿（=孤立磁盘文件）各归修复中心自己的卡，
    不再在这里用 MB 重复说一遍 —— 实测本机 dev 库旧口径 ratio=0.1775、新口径 0.0000。
    分母用 ``bytes_total``（用户看得见的那个数），``max(..., 1)`` 只防空目录除零；
    ``>`` 是严格大于，恰好等于阈值不算不一致。
    """
    diff = abs(registered_disk_bytes - registered_db_bytes)
    ratio = diff / max(bytes_total, 1)
    return ratio > MISMATCH_RATIO_THRESHOLD, diff


def _compute_usage(user):
    """扫盘 + 查库，组出端点返回体（口径见模块 docstring）。

    交集的三个内部量（``registered_count`` / ``registered_disk_bytes`` /
    ``registered_db_bytes``）**不进返回体**：界面只需要「超没超阈值 + 差多少」，
    多摆三个数就是规格 §4.6 明确否掉的「没人看得懂的二阶数字」。它们的正确性由
    Task 3 的 JoinedScanTests 直接打在 `_scan_tree` 上钉住。
    """
    root = _user_data_root(user.username)
    db = _db_map(user, root)
    scan = _scan_tree(root, registered=db['map'])
    mismatch, diff = _mismatch(
        scan['bytes'], scan['registered_disk_bytes'], scan['registered_db_bytes']
    )
    return {
        'data_dir': root,
        'bytes': scan['bytes'],
        'unique_bytes': scan['unique_bytes'],
        'file_count': scan['file_count'],
        'by_type': scan['by_type'],
        # db_count / db_bytes 是「全量参考」，走的是**行**口径（in_rows + out_count）；
        # 差值恒等式走的是交集（文件口径），那三个内部量不进返回体。
        'db_count': db['in_rows'] + db['out_count'],
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

Run: 同 Step 2 的命令，落 `tasks/b2-task3.log`。
Expected: `Ran 29 tests ... OK`（Task 2 落地后的 16 条 + 本任务 13 条 = DbMapTests 5 + JoinedScanTests 4 + MismatchTests 4）。`test_大小写不同的路径也能匹配上` 若在非 Windows 上跑会失败——那是它本来的意思（大小写不敏感是 Windows 事实），别改成 skip；真到 Linux CI 上要按 CI 档另开一条带平台判据的用例，本批 CI 不跑 Playwright 而后端档在 Windows 本机（`.github/workflows/ci.yml` 只有 4 档）。

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/storage_usage.py test/backend/test_storage_usage_scan.py
git commit -m "feat(datafiles): 占用统计的 DB 映射与交集差值恒等式"
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

    def _post_usage(self):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.post(USAGE_URL, {})

    def test_只读不接受POST(self):
        self.assertEqual(self._post_usage().status_code, 405)

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

在 `apps/datafiles/storage_usage.py` 里补上测试要的公开入口与清缓存钩子（`_compute_usage` 之后）。本任务才真正需要缓存，所以**这一步**才加 `import time`、`from apps.common.keyed_lru import KeyedLRU`、`USAGE_CACHE_TTL_SECONDS`、`_USAGE_CACHE_MAX_ENTRIES`、`_usage_cache = KeyedLRU(_USAGE_CACHE_MAX_ENTRIES)`，并把模块 docstring 末尾那句「进程内 TTL 缓存（`get_user_usage`）由后续任务加在本文件里」改成对它的一句话说明（分桶实现没有 per-key 过期 ⇒ 真实窗口在 `[TTL, 2*TTL)` 浮动 ⇒ 所以返回体带 `scanned_at` 让陈旧可见）：

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
Expected: `Ran 42 tests ... OK`（本文件 33 = 16+13+4，加端点契约 9），且**没有** skip。

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
第二条（未超阈值不显）依赖**真实数据恰好没超 5%**。Task 1 追加探针在本机 dev 库实测新口径 ratio=0.0000（交集两侧都是 1,612,886,366 B，size 漂移 0 条），所以这条在 dev 上是**诚实的绿**，不需要注入假数据。它红了就先跑 `tasks/probe_batch2_diff_cause.py` 归因，两种可能：真有人在 media 里改过文件大小（合法出现，按实测数更新台账并说明是哪几条），或实现又把 C/D 混回了差值（回 Task 3 的判据改实现，**别改测试迁就**）。

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

Run: `cd frontend && npx vitest run test/unit/lineLimit.spec.ts`
Expected: 全绿。**别用 `node scripts/line-limit.mjs`** —— 那个文件没有 CLI 入口（纯函数库，IO 壳与全仓断言在 `frontend/test/unit/lineLimit.spec.ts:5`），直接 node 跑它退出 0 但什么都没查，是把空跑读成过闸（2026-11-14 复审现读）。本批新增文件都远低于 600（最大的 `test_files_usage_api.py` 约 170 行），且**没有**给任何文件加豁免——加了要在台账里写理由。

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

## Task 2 落地后的订正（2026-11-14，规格复审驱动）

提交 `0f12eb7` 之后跑 spec 复审，逐条核实后落地的差异。**其中第 1 条是真缺陷**，其余是措辞与卫生。

1. **`test_硬链接按inode只计一次` 原本没有判别力（Critical）。** 初稿的树里只有「一对硬链接、两颗都是 4096 B」。把实现里的 `os.lstat(entry.path)` 换成被禁止的 `entry.stat()`（本机 `st_dev`/`st_ino` 恒 0）之后，所有条目塌到同一个 `(0, 0)` 键，`unique_bytes` 仍然是 4096 —— **7 例全绿**（`tasks/b2-mutation-lstat.log`：`Ran 7 tests / OK`）。也就是说规格 §4.2 最硬那条「取 inode 必须用 lstat」当时只活在注释里。
   ⇒ 修法：再加一颗**不是硬链接、体积不同**的独立文件（1000 B），断言改成 `bytes == 4096*2+1000`、`unique_bytes == 4096+1000`、`file_count == 3`。
   ⇒ 反证已做：改回 `entry.stat()` 后 `FAILED (failures=1)`，`AssertionError: 1000 != 5096`（`tasks/b2-task2-mutation2.log`），改回 `os.lstat` 后 `OK`（`tasks/b2-task2-green2.log`）。这条用例现在是能把已知坏实现杀掉的真判据。
2. **`_scan_tree` docstring 里 normcase 那句把失败方向说反了（Important）。** 原写「少这一步交集恒为空 —— 表现成『差值全是清单值』」。事实：`reg_db` 与 `reg_disk` 在同一个分支里一起不加，交集为空时**差值恒为 0 ⇒ 该报的不报（假绿）**。护栏因此不能指望差值行，只能靠 Task 3 断言 `registered_count == 1`；本文件 Task 3 的 `test_同一条记录的size漂移才报不一致` 里已把这条断言加在最前面。
3. **删掉了为后续任务预埋的死代码（Minor，复审指出）。** 初稿在 Task 2 就带上了 `import time`/`timezone`/`KeyedLRU`/`DataFile`/`resolve_file_path`、`USAGE_CACHE_TTL_SECONDS`、`_USAGE_CACHE_MAX_ENTRIES`、`_usage_cache`、`MISMATCH_RATIO_THRESHOLD` —— 全是当时没人用的。现按「用到的那一步再加」重新分配：`timezone`/`DataFile`/`resolve_file_path`/`MISMATCH_RATIO_THRESHOLD` 归 **Task 3**；`time`/`KeyedLRU`/两个缓存常量/`_usage_cache` 归 **Task 4**。附带实测：本仓**没有 Python 静态检查层**（pyproject 只有元数据，无 ruff/flake8/black/mypy），所以这类死导入不会被机器拦，只能靠人。
4. **`_iter_files` docstring 少了一句假话。** 初稿尾巴那句「少算的部分由差值行兜出」在订正⑤ 之后**不成立**（扫不到的文件多半也是注册行，两侧一起少 ⇒ 差值仍是 0），落地版把它删了，只保留「一次权限问题不该让整颗 chip 消失，也不该让整个请求 500」。
5. **`test_by_type_...` 的自洽性断言改成对着 `result` 自己比。** 初稿写死 `sum(...) == 1310` / `== 4`，那样「总量与分桶一起算错」查不出来，而那正是浮层与 chip 互相打脸的形状。现在断言 `sum(v['bytes'] ...) == result['bytes']`。

落地文件行数：`apps/datafiles/storage_usage.py` **118**、`test/backend/test_storage_usage_scan.py` **115**（`node scripts/line-limit.mjs` 退出 0）。

### 同一轮的代码质量复审又挖出 6 条（都核实过，都已落地）

复审给出的每条我都在本机复现或反证过，其中前两条是**复审自己也没量准**的（见下表最后一列），所以文字按实测写。

| # | 发现 | 实测 | 落地 |
|---|---|---|---|
| 6 | **junction 会被走进树里**（Critical）。模块 docstring 与 `_iter_files` 都写着「目录联接跳过」，而实现只判了 `is_symlink()` | 本机 `mklink /J` 造的条目实测 `is_symlink()=False`、`is_dir(follow_symlinks=False)=True`、`is_junction()=True`；旧写法会把目标目录的体积算到这个用户头上，自引用 junction 还能递归到 MAX_PATH 才停 —— 而那声 OSError 恰好被「跳过坏条目」那条咽掉，表现为一个偏大的数而不是报错 | `if entry.is_symlink() or entry.is_junction(): continue` + 一条 `mklink /J` 用例（造不出就 skipTest，同 `test_test_data_gc.py:157` 的写法） |
| 7 | **`registered` 命中依赖绝对 root**（Important）。`entry.path` 的绝对性是从 root 继承的 | 相对 root 实测 `registered_count=0`（而 `bytes`/`count` 照旧正常）——正是假绿方向 | `_scan_tree` 带 `registered` 时 `not os.path.isabs(root)` ⇒ `raise ValueError`（用 raise 不用 assert：`-O` 会剥掉 assert） |
| 8 | **`st_ino` 恒 0 的文件系统会把整棵树塌成一份** | 网络盘/部分虚拟盘的已知形状；后果与 lessons 2026-10-24 那次「5.0GB 报成 0.07MB」同一个形状，只是换了成因 | 去重键改成 `(dev, ino) if ino else (dev, ino, path)` —— ino 为 0 时**不去重**（宁可高估，不去猜） |
| 9 | **用户名可以就是 `..`**（复审建议用 `os.path.basename(username)` 防，**那条防护无效**） | 实测 `UnicodeUsernameValidator()('..')` **接受**（点号是合法字符）；实测 `os.path.basename('..') == '..'`。`MEDIA_ROOT/data/..` 归一化后就是 `MEDIA_ROOT` ⇒ 这一个用户会看到所有人的量 | `_user_data_root` 对 `('', '.', '..')` 与含分隔符的用户名 `raise ValueError`，并把「别拿 basename 当防护」写进 docstring。同形状的老入口 `_helpers.py:183 _user_upload_dir` 没挡 ⇒ 记进台账，不属本批 |
| 10 | **`test_目录内不可读条目…` 那条 chmod 用例其实杀不掉任何东西** | 实测 `os.chmod(0o000)` 之后 `os.lstat` **仍然成功**，所以 `except OSError` 分支根本没进过；`assertLessEqual(file_count, 1)` 在「全跳过」和「全没跳」两种实现下都绿 | 换成注入：wrapper 只对指定路径抛 `OSError`、其余委托真实现（窗口内不波及 Django 自己的调用）。条目分支与目录分支**各一条**（两处不同的 `continue`）；顺带把「根不存在 / 根是空目录 / 根是一个文件」拆成三条（原来那条名为「空目录」实际测的是目录不存在） |
| 11 | `OrderedDict` 又立刻 `dict()` 拍平、`os.path.basename(entry.name)` ≡ `entry.name` | —— | 直接用 dict（插入序即输出序）+ `entry.name` |
| 12 | `registered_count` 数的是**文件**不是**行**：map 按路径去重，重复行只留一条；而计划初稿的 `_db_map` **没有 `order_by`** | 同一路径两条不同 `file_size` 的行 ⇒ 胜者取决于 `values_list` 顺序 ⇒ 差值会在 30 s TTL 里翻脸。`_helpers.py:309 _group_duplicates` 恰好是 `order_by('id')` 的 | 契约写进 `_scan_tree` docstring；**Task 3 的 `_db_map` 改成 `order_by('id')` + 单独数 `in_rows`**（`db_count` 用行数，不用 `len(map)`），并补一条重复行用例 |

**六条变异的反证**（`tasks/mutate_b2_task2.py`，跑完自动还原原文 + `git diff` 复核）：

```
去掉 junction 跳过            → test_目录联接junction不进树            杀掉
条目分支 continue 改 raise     → test_单个文件读不到时其余照常计入且不抛错   杀掉
目录分支 continue 改 raise     → test_单个子目录读不到时其余照常计入且不抛错  杀掉
退回「无脑按 (dev,ino) 去重」   → test_ino为0时不去重_宁可高估            杀掉
去掉绝对路径守卫               → test_带registered时root必须是绝对路径     杀掉
去掉用户名守卫                 → test_点点点之类的用户名直接报错           杀掉
```

一个锚点教训（记进 lessons 候选）：给变异脚本写文本锚点时，`'        except OSError:\n            continue'` 这种**纯缩进区分**的片段会先命中外层那条更宽缩进的分支（20/24 空格的尾巴里含同样的 8/12 子串），于是「改目录分支」实际改的是条目分支、判据被误判成杀不掉。锚点要带上下一行（`\n\n\ndef _scan_tree`）才唯一。

落地文件行数（本轮之后）：`apps/datafiles/storage_usage.py` **148**、`test/backend/test_storage_usage_scan.py` **253**；`Ran 16 tests / OK`，零 skip。

---

## Task 3 落地后的订正（2026-11-14，变异反证驱动）

Step 2/Step 4 的期望形状与实测一致（红：`Ran 29 / FAILED (errors=12)`，全是
`AttributeError: ... has no attribute '_db_map'` / `'_mismatch'`，且
`test_不传registered时只回四个总量键` 当时就过；绿：`Ran 29 / OK` 零 skip）。下面四条是
计划文本与可执行代码的差，都由 `tasks/mutate_b2_task3.py`（8 个变异，跑完自动还原并复核
逐字节复现）量出来的。

1. **`test_file_size_为_None_按0计不成报错` 照抄不可执行（Critical）。**
   `DataFile.objects.filter(pk=row.pk).update(file_size=None)` 实测
   `sqlite3.IntegrityError: NOT NULL constraint failed: datafiles_datafile.file_size`
   —— `file_size` 是 `BigIntegerField()`（`apps/datafiles/migrations/0001_initial.py:23`），
   真库里造不出 NULL，于是这条红在**建数据那一步**、根本没走到 `_db_map`，什么都没判。
   ⇒ 落地改成注入一行 `(路径, None)`（本文件「chmod 造不出 OSError 就注入」同一个道理），
   并补一条 `list(db['map'].values()) == [0]`。反证：`int(file_size or 0)` → `int(file_size)`
   ⇒ `TypeError: int() argument ... not 'NoneType'`（`tasks/b2-task3-mut4.log`）。
   ⇒ 连带的教训：注入用的 fake 第一版只认 `filter().order_by().values_list()` 这条链，
   结果「去掉 `order_by`」的变异顺带把它也弄红（AttributeError 串味，归因失真）。改成
   「任意链形状都通」的 stub（`_FakeRows`）后，每个变异只红在声称判它的那条上。

2. **订正⑤ 的护栏分工和计划写的不一样（Important）。** 把 `_mismatch` 内部退回旧口径
   （`diff = abs(bytes_total - registered_db_bytes)`）之后，
   `test_文件已不在盘上时不报不一致` **不红** —— 该用例的三个入参按构造全是 1000，
   任何两个相减都是 0，它对「差值取哪两侧」这件事**天生看不见**。实测杀到它的是
   `JoinedScanTests.test_磁盘孤儿不进差值`（`AssertionError: True is not false`）和
   `MismatchTests.test_分母是磁盘总量_空目录用1防除零`（`30 != 20`）。
   ⇒ 那条命名用例仍然有牙，只是判的是另一件同样承重的事：已删行漏进交集
   （`registered_db_bytes = sum(registered.values())` ⇒ `AssertionError: 5243880 != 1000`）。
   ⇒ 落地：在它的 docstring 里写清「本条钉什么、旧口径那一半归谁」，不许再单独把它当
   订正⑤ 的护栏（计划 Task 3 的类 docstring 与 2007 行那条都把它写成护栏）。

3. **`test_分母是磁盘总量_空目录用1防除零` 原本钉不住它自己 docstring 里那句禁令。**
   变异「分母换成 `registered_disk_bytes`」实测 29 例全绿：那三笔数里 `bytes_total` 与
   `registered_disk_bytes` 要么相等，要么两侧都远越过 5%。
   ⇒ 补一笔 `_mismatch(100000, 1000, 1051) == (False, 51)`（真口径 0.051% 不报；换分母就成
   5.1% 假报），现在该变异红 `(True, 51) != (False, 51)`（`tasks/b2-task3-mut8.log`），
   顺带也把第 2 条那个旧口径变异多杀一次。

4. **`order_by('id')` 确实有判别力，不是巧合。** 去掉之后
   `AssertionError: Lists differ: [100] != [250]`（`tasks/b2-task3-mut3.log`），且只红这一条。
   起作用的是 `DataFile.Meta.ordering = ['-created_at']`（`apps/datafiles/models.py:67`）——
   `values_list()` 会带上默认排序，而它把 id 序整个倒过来，所以「SQLite 恰好按插入序返回
   ⇒ 测不出来」这个担心在 ORM 层不成立。计划预写的兜底（改成删低 id 行再读）**没启用**。

5. **遗留一条给 Task 4（本批目前无人看守的形状）。** 变异「`_compute_usage` 接线错误：
   清单侧喂 `db['in_bytes']`（在根内的全部注册行，含文件已删的那些）」实测 29 例**全绿**
   （`tasks/b2-task3-mut6.log`）—— 本文件的判据按计划是打在 `_scan_tree` + `_mismatch`
   上的，等于把调用点的接线复制了一遍写进测试，所以调用点自己写错抓不到。
   Task 4 已有的端点用例里也没有「注册行在、文件已删」这一形状（954-980 只有根外绝对路径
   与 size 漂移两种）。⇒ Task 4 的 `test_files_usage_api.py` 补一条：`single/a.csv` 在盘上
   且清单准确 + 另一条注册行的文件已删 ⇒ `mismatch_over_threshold is False` 且
   `db_count == 2`，把「缺文件不许变成 MB」这句在**端点**上钉住。
   （⇒ 这条**没留给 Task 4**，见下面「控制器复核后的再订正」第 2 条：装配层自己有了判据。）

6. **`node scripts/line-limit.mjs` 仍是空跑**（无 CLI 入口，exit 0 什么都不查，与
   2026-11-01 的记录相同）。本批的 600 行证据改用该模块导出的纯函数按
   `frontend/test/unit/lineLimit.spec.ts` 同款 IO 壳现数：959 个跟踪文件、
   violations 0、stale-exemptions 0。落地文件行数：`apps/datafiles/storage_usage.py` **256**、
   `test/backend/test_storage_usage_scan.py` **490**。

顺带：模块 docstring 末尾那句「本模块只做磁盘侧口径……由后续任务加在本文件里」在本任务之后
就不成立了（`_db_map` / `_mismatch` / `_compute_usage` 已在此），落地时改成「口径都在本文件，
HTTP 在 `views/usage_views.py`，TTL 缓存由 Task 4 加」。


### 控制器复核后的再订正（同一轮，落地方向换了三条）

复审报告是诚实的，但两处**处置方向**我不同意，另有一个装配洞没留到 Task 4。三条都现跑过。

1. **`file_size is None` 那条改成「删兜底」，不是「mock 出来测它」。** 复审把不可执行的
   `update(file_size=None)` 换成注入一行 `(路径, None)` 的 fake 查询集（`_FakeRows`，20 行）
   去测 `int(file_size or 0)`。方向不对：`file_size` 是 `BigIntegerField(null=False)`、
   `file_path` 是 `CharField`（`0001_initial.py:22-23`），实测 `update(file_size=None)` ⇒
   `sqlite3.IntegrityError` —— 那个状态真库里**进不去**。为进不去的状态留兜底，就得再为兜底
   造一个假 ORM，于是判据在测 mock 而不是测产品；更糟的是下一个读代码的人会以为存在过这种数据。
   ⇒ 落地：`int(file_size)` / `int(db_size)` / `resolve_file_path(file_path)` 三处兜底全删，
   `_FakeRows` 与那条用例删掉，换成 `test_空表返回全零而不是报错`（钉 `_db_map` 返回键的**全集**，
   顺带让改名变成红）。`or 0` 为什么不留，写在 `_db_map` 的注释里。

2. **第 5 条那个装配洞在本批就堵上了**：新增 `ComputeUsageTests`（5 条，见 Task 3 Step 1），
   两个装配变异现跑（`tasks/mutate_b2_task3_assembly.py`：跑整个类再还原，逐字节复核）——

   ```
   恒等式吃行口径 db['in_bytes']（旧口径形状）  → 杀掉 test_记录还在文件已删_恒等式必须吃交集而不是行口径
   恒等式吃磁盘总量 scan['bytes']（订正⑤ 之前）→ 杀掉 test_磁盘孤儿只进磁盘总量不进差值
   ```

   第二个变异**只有新加的「磁盘孤儿」那一笔看得见**：前四笔里 `bytes` 与
   `registered_disk_bytes` 按构造相等，任何磁盘侧替换都是等价变异。⇒ 记下这句：装配层的判据
   要**按形状逐个摆**（在盘 / 已删 / 孤儿 / 漂移 / 内部量不外泄各一笔），不是随便加一条就守得住。
   Task 4 因此不必再补同形状的端点用例。

3. **新的框架事实（Task 10 写进 lessons）**：`manage.py test` 走 `config.settings.unit`，
   其 `MEDIA_ROOT = test/unit-data/media` —— 是**跨用例共享的沙箱目录，不是 tempdir**
   （`config/settings/unit.py:56`）。所以「按 `settings.MEDIA_ROOT` 往盘上造文件」的用例，
   造的那几行与读它的那一行必须在同一个 `override_settings` 里。本次初稿把 `_write_own` 落在
   override 之外，结果扫描读到 0（断言红，算运气好），文件却写进了别人也会读的沙箱：
   `test/unit-data/media/data/assembler/`（已手工清掉）。这条比第 1 条更容易复发：
   它不报错，只留残留 + 一个看起来像业务缺陷的红。

现数：`Ran 34 tests / OK` 零 skip（`tasks/b2-task3-green8.log`）；
`apps/datafiles/storage_usage.py` **259**、`test/backend/test_storage_usage_scan.py` **562**。

---

## Self-Review（写完计划后自查）

**1. 规格覆盖（逐条 §4 → Task）**

| 规格 | 落在 |
|---|---|
| §4.1 端点 + 返回体 8 个字段 | Task 2（scan 字段）+ Task 3（`_compute_usage` 组装）+ Task 4（视图与路由）；字段按订正②/③ 增加了 5 个 |
| §4.2 口径纪律（lstat/inode、rglob 交叉核对、页面只显一个数） | Task 2 的 `test_硬链接按inode只计一次`（**已做变异反证**：坏实现必红，见「Task 2 落地后的订正」第 1 条）与 `test_口径交叉核对_用rglob独立加总必须相等`；只显一个数在 Task 7 的 `usageChipText` |
| §4.3 数据源选扫盘 | Task 3 的两本账 + `db_bytes` 只作参考（Task 6 不把它放进 chip） |
| §4.4 性能（TTL 缓存、失效、实测） | Task 4 `get_user_usage` + Task 5 四条行为判据 + Task 1 P2 + Task 10 Step 3 |
| §4.5 展示（chip 文案、hover 拆分、字号 token） | Task 6（文案纯函数）+ Task 7（chip + 浮层 + `--p-fs-*` 复用 `.section-count`）+ Task 8（渲染与 hover） |
| §4.6 差值露出（阈值恒等式、修复对话框一行） | Task 3 的 MismatchTests 5 条 + JoinedScanTests 4 条（订正⑤：只比交集）+ Task 9 |
| §4.7 配额只做到「当前用户」 | 全程无新字段、无逐用户列表；Task 10 Step 3 的「本批不做」清单写死 |
| §4.8 测试（T1 齐全/空目录/隔离/缓存/交叉核对；T3 chip 渲染） | Task 2/3/4/5（T1，共 23 例）+ Task 6（T2，15 例）+ Task 8/9（T3，6 例） |

**2. 占位符扫描**：无 TBD/「类似 Task N」/「加适当错误处理」。两处「故意写错再改」是显式教学步骤（Task 4 Step 1 的 `test_只读不接受POST`、Task 8 Step 1 末尾删掉那条用例），都写明了删/改的动作为什么，不是留白。

**3. 类型一致性**：`_scan_tree` 返回的键（`bytes`/`unique_bytes`/`file_count`/`by_type`）= `_compute_usage` 用的键 = `FileUsage` 的字段 = e2e 的 `captured.*`。`_db_totals` 的 `in_count/in_bytes/out_count/out_bytes` 只在 Task 3/4 内部与 `_compute_usage` 的映射处出现，未泄漏到前端。`get_user_usage(user, fresh=…)` / `clear_usage_cache()` 在 Task 4/5 用法一致。前端 6 个函数名在 Task 6 定义、Task 7/9 调用，逐字相同。Task 7 Step 3 的 ⚠ 要求 `usageScannedText` 去掉前缀并同步 Task 6 的断言——这条改动要在 Task 6→7 之间落地，别只改一边。

---

## Task 1 实测结论（2026-11-14 已跑完，四条判据全过）

两份探针都在本机 dev 档跑（`manage.py shell` ⇒ `config.settings.development` ⇒
`MEDIA_ROOT = C:\Users\Administrator\LQ-DataPrase\media`，注册行只有 `admin` 一个用户）。

**① `tasks/probe_batch2_disk_usage.py`**

| 判据 | 实测 | 结论 |
|---|---|---|
| P2 实扫耗时 | 112 个文件 / 1,612,886,366 B / **11.4 ms** | ≤300ms ⇒ 按本计划走「实扫 + 30s 分桶缓存」，**不建快照表** |
| P1 根目录外的注册行 | **0 条 / 0 B**（in_root=185 行） | 订正② 的两本账在本机是防御性的；「目录外 N 条」那句当前不会显示，但遗留装机仍需要它 ⇒ Task 7 保留、Task 8 不为它单开用例 |
| P3 第一段目录名 | `{'single': 98, 'batch': 14}`，无散文件、无未知键 | `TYPE_LABELS` 的两个键够用；空串与未知键的兜底分支由 Task 6 的 T2 钉（不在浏览器里造没数据的分支） |
| P4 `bytes == unique_bytes` | **True** | 硬链接目前只在 e2e slot 镜像（`scripts/e2e_pool.mjs:113`）；`unique_bytes` 确实是绊线字段，不进界面 |

**② `tasks/probe_batch2_diff_cause.py`（差值成因拆解，直接产出订正⑤）**

```
A 磁盘实扫            : 112 个文件, 1,612,886,366 B (1.50 GB)
B 注册行且文件在盘上   : 112 行, 清单 1,612,886,366 B, 实际 1,612,886,366 B   ← 漂移 0 B / 0 条
C 注册行但文件已不在盘 : 73 行, 清单 286,358,763 B
D 盘上有文件但无注册行 : 0 个, 0 B
旧口径 ratio = 0.1775（永远红）    新口径 ratio = 0.0000（安静）
```

⇒ 结论写死进实现：差值恒等式两侧都只取交集（Task 3 的 `_mismatch(bytes_total,
registered_disk_bytes, registered_db_bytes)`）。Task 9 的负例因此在 dev 上是诚实的绿。

**③ 顺手实测的库能力（不是推测，是本机 Python 3.13.12 现跑）**

```
os.DirEntry.stat()  st_dev / st_ino = 0 / 0          ← 不能用它去重
os.lstat()          st_dev / st_ino = 5494… / 1970…  ← 实现用这个
os.link / os.symlink 本机都可建                      ← Task 2 的三条判据用例不会被 skip
```

---

## Task 4 落地后的订正（2026-11-14，端点契约实测）

1. **Step 1 的 `test_清单外的遗留绝对路径单列一条不混进bytes` 照抄不可执行（Critical）。**
   该用例只建了一条**根外**注册行（legacy.csv），却断言 `db_count == 2` 与
   `db_bytes_in_root == 1000` —— 按 `_db_map` 的实现这两个数必为 `1` 与 `0`，红在数据构造
   而不是红在口径上。⇒ 落地补上 `data/usage_a/single/a.csv` 的在根注册行（`file_size` 与
   盘上相等的 1000），这条才真的钉住「两本账分开、交集差值仍是 0」的形状；其余 8 条与正文逐字相同。

2. **Step 2 的期望形状只实现了一半（Important）。** 正文写「`AttributeError: … has no
   attribute 'clear_usage_cache'`，以及 `test_路由没被router的详情路由吞` 以 404 失败」。
   实测 `Ran 9 / FAILED (errors=9)`（`tasks/b2-task4-red.log`）：`clear_usage_cache()` 在
   `setUp` 里，九条**全部先死在 setUp**，排序那条根本没走到断言。⇒ 排序的证据改由两处现读给出：
   - 接线前 `resolve('/api/v1/files/usage/')` 实测 `MATCHED_VIEW=DataFileViewSet
     KWARGS={'pk': 'usage'}`（`tasks/b2-task4-preprobe.log`）—— 订正① 说的那颗嘴本来就在；
   - 落地后把 path 行挪到 `include(router.urls)` **之后**（`tasks/mutate_b2_task4_route.py`，
     finally 逐字节还原并复核 `True`）⇒ `FAILED (failures=2, errors=5)`，其中
     `test_路由没被router的详情路由吞` 是 `AssertionError: 404 != 200` —— 是 **404**，
     不是 400/500：DRF 确实按 `pk='usage'` 去 `get_object_or_404`，`ValueError` 被转成
     `Http404`。排错的表现为「端点说它不存在」，而 urls.py 里那行看着仍在。

3. **`FileUsageView` 的导入位置按计划放不进字母序（Minor）。** 正文写「按字母序放在
   `FileActivateView` 之后」，但 `FileUploadView < FileUsageView`（`p` < `s`）。落地取字母序。

4. **连带确认**：Task 3「控制器复核后的再订正」第 2 条已在装配层堵上那个洞，所以本任务
   **没有**补「注册行在、文件已删」的端点用例，`Ran 9` 与正文一致。

现数：`Ran 9 tests / OK`（`tasks/b2-task4-green.log`；还原后复跑 `tasks/b2-task4-green2.log`
亦 OK）；邻近回归 `Ran 24 / OK`（`tasks/b2-task4-regress.log`）；Task 3 口径档
`Ran 34 / OK`（`tasks/b2-task4-scan-regress.log`）；行数 `storage_usage.py` **293**、
`urls.py` **36**、`views/__init__.py` **40**、`views/usage_views.py` **26**、
`test_files_usage_api.py` **138**；600 行门禁 `npx vitest run test/unit/lineLimit.spec.ts`
→ `15 passed`。


### 控制器复核后的再订正（Task 4 那一轮，五条落地）

复审给的结论是 SPEC 合规、质量 APPROVED WITH NITS。两条 MED 与一条 LOW 我全盘接受，
另外把我自己刚写错的一条判据一并改掉。反证脚本：`tasks/mutate_b2_task4_fresh.py`
（跑整套 44 例，finally 逐字节还原并复核）。

5. **`fresh` 解析从黑名单改成白名单（MED）。** 黑名单是 **fail-open** 的：实测 `no` / `off` /
   `TRUE` / `abc` / `' '` 全被读成「绕缓存」，而绕一次的代价不是调用者多扫一棵树，是把
   **所有人**的表清掉（`get_user_usage(fresh=True)` 走 `_usage_cache.clear()`）。
   ⇒ 改成 `raw.strip().lower() in _FRESH_TRUE`，`_FRESH_TRUE = ('1', 'true', 'yes')`。
   两个方向都有反证：退回黑名单 ⇒ 红；干脆不认 `fresh` ⇒ 也红。

6. **我第一版判据跟自己选的设计打架（同一条改出来的）。** 新加的 `fresh` 契约用例最初把
   `fresh='TRUE'` 断成「不许绕」—— 可解析里做了 `.lower()`，`'TRUE'` 就是 `'true'`，**该**绕。
   写判据的人脑子里装着黑名单的旧结论，就会造出一条永远不可能绿的"判据"。
   ⇒ 非白名单现在验 `'0' / 'no' / 'off' / '' / 'False'` 五个值，白名单只验 `'1'`，
   并且白名单那一步放在最后：绕一次就清表，前面的「不绕」断言会跟着失真。

7. **TTL 窗口的算术是错的，而且会传染（LOW，但必须改）。** 初稿在模块 docstring、常量注释、
   `get_user_usage` 三处都写「真实陈旧窗口在 `[TTL, 2*TTL)` 浮动」「最多陈旧一分钟」。
   事实：桶号在 **key 里**，一条结果的寿命最多到它所属桶的末尾 ⇒ **≤ 30s**，不是 30–60s。
   值得改的原因是 Task 7 的浮层文案与 Task 10 的台账都要引用这个数 —— 写宽一倍等于
   对着用户把陈旧说成两分钟。

8. **`clear()` 不 fence 在途 `compute` 写进 docstring（LOW，不加机制）。**
   `keyed_lru.py:53-59` 明确不清 pending，所以「写前开扫、写后发布」的那一次可能让紧随其后的
   fresh 调用拿到写前的结果；窗口 = 一次扫描（实测 11.4ms / 112 文件），下一个桶自愈。
   要消除得给条目加 epoch —— 给一个只读 chip 加事务机制不划算，写明「尽力而为」即可。

9. **四条卫生。** (a) `FileUsageApiTests` 补 `tearDown` 清表：缓存键只有 `(username, bucket)`、
   **不含 MEDIA_ROOT**，不清的话后面复用同名用户的用例会在同一桶里读到别人的临时树。
   (b) 字段齐全从逐个 `assertIn` 改成 `set(data) == set(FIELDS)` —— 前者只能发现「少了」，
   发现不了「多了」，而多摆一个数正是规格 §4.6 否掉的二阶指标。
   (c) 排序那条再加一句 `resolve(USAGE_URL).url_name == 'file-usage'`：光看 200 只证明
   「有视图接住了」，不证明是**这条**路由接住的。
   (d) `data_dir` 留在返回体里但写明理由：UI 不消费它（Task 6/7 谁都不读），
   留着是因为 Task 3 拿它当「两侧同一个根」的见证；它也不算泄露 ——
   `batch_views.py:126` 早就返回 `<MEDIA_ROOT>/data/<user>/batch`、
   `browse_views.py:292` 返回绝对文件路径，两条都按 owner 隔离。

10. 顺手去掉 `storage_usage.py` 与 `usage_views.py` 第一行的自标签路径注释
    （同目录的 `browse_views.py` / `file_views.py` / `utils.py` 都不写这一行）。

现数：`Ran 44 tests / OK`（端点 10 + 口径 34，`tasks/b2-task4-green4.log`）；
`storage_usage.py` **299**、`views/usage_views.py` **27**、`test_files_usage_api.py` **172**。

---

## Task 5 落地后的订正（2026-11-14，四条补齐 + 反证）

四条 `CacheBehaviourTests` 在 Task 4 的实现下**首跑即绿**（`Ran 4 / OK`，`tasks/b2-task5-class.log`），
所以本提交按 Step 2 的说法是「行为判据补齐」，**不是**红绿循环产物。判别力由
`tasks/mutate_b2_task5.py`（4 档变异，跑「口径 + 端点」两套 48 例，`finally` 逐字节还原并复核
`True`，还原后复跑仍 38 OK）现量：

| 变异 | 实测杀掉它的用例（在哪个文件） |
|---|---|
| M1 去掉 `if fresh: _usage_cache.clear()` 那一支 | `test_fresh为True时强制重算`（本文件）**外加** `test_fresh是白名单_且1会立刻反映新写入`（api 文件）—— 2 条 |
| M2 `bucket` 换成常量（永不换桶） | **只有** `test_bucket随TTL变化_用假时钟证明换桶必重算`（本文件）—— 1 条 |
| M3 key 去掉 username（全体共享一份缓存） | **只有** `test_不同用户不共享缓存`（本文件）—— 1 条，且**整个 api 文件全绿** |
| M4 每次直接 `return _compute_usage(user)`（缓存整体失效） | `test_同一bucket内第二次调用不再算`（本文件）**外加** api 那条里「没带 fresh ⇒ 吃缓存」那一句 —— 2 条 |

四条与计划给的表逐条相符，没有「该谁杀却由别人杀」的错位。两处值得记的实测事实：

1. **M3 揭出一个本批的看守空缺（Important）。** 去掉 key 里的 username 后端点契约一条不红：
   `FileUsageApiTests` 每条用例都只用自己的那个 user 发请求，且 setUp/tearDown 都清表
   （Task 4「四条卫生」第 9a 条），所以同一次请求序列里永远不会出现两个用户 ⇒
   「缓存 key 含 username」这件事在 **HTTP 层一句判据都没有**，本批只有 M3 这条函数级用例守着。
   留给 Task 10 台账：真要在端点上钉，得造「A 先请求、B 后请求、两侧 `bytes` 必须不同」一条。

2. **计划正文两处数过期（Minor）。** Step 1 括注「文件顶部补 `from unittest import mock`」——
   Task 2 起本文件第 18 行就已有，不用补；Step 3 期望 `Ran 42 tests / OK（本文件 33 = 16+13+4，
   加端点契约 9）`—— Task 3/4 两轮复审都往里加过例，现数是**本文件 38（34 + 4）+ 端点 10 =
   `Ran 48 / OK`**，零 skip。

3. **「追加一个类」这条撞了 600 行硬闸（Critical，处置留给控制器）。** 正文只写
   「Modify: `test/backend/test_storage_usage_scan.py`（追加一个类）」，没量过落点行数：本文件
   Task 3 时 490、Task 4 收口时 562，逐字追加这 68 行（类体 66 + 两个空行）后是 **630 > 600**。
   测试文件确实在适用面内（`.claude/CLAUDE.md`「600 行约束的适用面」：2026-10-27 实测超阈的
   **全部**是测试文件），实测 `cd frontend && npx vitest run test/unit/lineLimit.spec.ts`
   ⇒ `15 tests | 4 failed`（`tasks/b2-task5-linelimit.log`）：
   `❌ test/backend/test_storage_usage_scan.py 630 行 > 阈值 600（不在豁免账里）`，`kind: 'new'`。
   ⇒ 本任务**没有**擅自改 `scripts/line-limit.mjs` 的豁免账（那是闸自己的账，理由要写「哪一次
   工单、为什么不该由本闸拦当下改动」），也**没有**删别人的用例腾地方，二选一：
   - **(a) 拆档**：四个方法 + setUp/tearDown/`_counting_compute` 挪进
     `test/backend/test_storage_usage_cache.py`（新档要有 `__init__` 树内的位置：`test/backend/`
     已是一个包，直接放即可），本文件回到 562，条数不变（`Ran 34` + `Ran 4` 两档）。
   - **(b) 挂绊线**：`EXEMPT` 记 `test/backend/test_storage_usage_scan.py` 精确 **630** 行 + 理由。
   取舍：(a) 不动闸、账不膨胀，代价是本批口径判据从此分两档跑；(b) 一行账搞定，代价是豁免清单
   单向膨胀。推荐 (a) —— 本文件的类边界本来就是现成接缝（走树 / inode / 根守卫 / 两本账 /
   交集 / 算术 / 装配 / 缓存），且 Step 3 用两个 label 跑两套已经证明类之间互不依赖。

现数：单档 `Ran 38 tests / OK`（`tasks/b2-task5-green.log`）、端点档 `Ran 10 / OK`
（`tasks/b2-task5-api-regress.log`）、合档 `Ran 48 / OK`（`tasks/b2-task5-green-combined.log`）、
还原后复跑 `Ran 38 / OK`（`tasks/b2-task5-green2.log`）；
`test_storage_usage_scan.py` **630**（见上面第 3 条）。
