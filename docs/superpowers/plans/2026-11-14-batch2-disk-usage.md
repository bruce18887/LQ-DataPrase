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
⇒ 处置：`KeyedLRU` 分桶 TTL 做正确性下界（漏挂最多陈旧 **≤30s**：桶号在 key 里，一条结果的寿命最多到它所属桶的末尾 —— 初稿这里写的「30–60s」宽了一倍，订正见文末 Task 4 复核第 5 条），刷新入口做成 `?fresh=1`，由 `FileListTab.vue` 在**已经存在**的 `filesStore.filesVersion` watch 里带 `fresh=true` 重拉（⚠ 这里原本写死 `:322-327`，Task 7 之后该 watch 已在 **`:338-346`** —— **行号会随任何同文件改动漂**，取法：`grep -n "watch(() => filesStore.filesVersion" frontend/src/pages/data/components/FileListTab.vue`）——上传/删除/批量删除/组合/修复五条流全都调 `filesStore.notifyFilesChanged()`（现号取法：`grep -n "notifyFilesChanged()" frontend/src/pages/data/components/FileListTab.vue` ⇒ **236/241/272/299/322**；本行历史上一串号 `220/225/256/283/306` 是 Task 7 之前的，`237/242/273/300/323` 是 Task 7 与导入合并之间的一分钟快照，都别再照抄），所以**一行覆盖全部**，SFTP 后台导入这类无前端信号的路径由 TTL 兜底，浮层里显示「统计时间」让陈旧可见。

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

⚠ **下面这块 docstring 里的窗口口径已过期，别照抄。** 「`[TTL, 2*TTL)` 浮动」「最多陈旧一分钟」是初稿算法：桶号在 **key 里**，一条结果最多活到它所属桶的末尾 ⇒ 真实上界是 **≤30s**。落地文本以 `apps/datafiles/storage_usage.py:14-24` 为准，订正理由见文末「Task 4 落地后的订正」第 5 条。这一段保留原样只是为了让「谁在哪一步改了什么」可追溯。

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
  ⚠ 落地后改拆档：追加使该文件 562→630 撞 600 硬闸，整类逐字节挪进新档
  `test/backend/test_storage_usage_cache.py`。详见文末「Task 5 落地后的订正」第 3 条与「控制器处置」。

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

  // GB 档是本功能新增的：formatSize 最高只到 MB，改它要动既有调用点的显示（现数 7 个文件 9 处调用），不属本批。
  it('≥1GiB 进 GB 档并保留两位', () => {
    expect(usageBytesText(1024 * 1024 * 1024)).toBe('1.00 GB')
    expect(usageBytesText(1024 * 1024 * 1024 - 1)).toBe('1024.0 MB')
    expect(usageBytesText(1.5 * 1024 * 1024 * 1024)).toBe('1.50 GB')
  })

  it('非有限值（NaN/±Infinity）不产生 NaN 字样', () => {
    expect(usageBytesText(Number.NaN)).toBe('--')
    expect(usageBytesText(Number.POSITIVE_INFINITY)).toBe('--')
    expect(usageBytesText(Number.NEGATIVE_INFINITY)).toBe('--')
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

  it('scanned_at 缺失或不可解析时返回 null，不显空串', () => {
    expect(usageScannedText(base({ scanned_at: '' }))).toBeNull()
    expect(usageScannedText(base({ scanned_at: 'not-a-date' }))).toBeNull()
    expect(usageScannedText(null)).toBeNull()
  })

  it('值只有时间本身，不带「统计时间」前缀（label 归调用方）', () => {
    // ⚠ 分工：`usageScannedText` 返回的是**浮层某一行的 value**，而那一行的 label
    // 由调用方（Task 7 的 `el-descriptions-item label="统计时间"`）给。返回值再自带
    // 前缀就会读成「统计时间：统计时间 2026-11-14 …」。所以这里只钉形状，不钉前缀。
    const text = usageScannedText(base())
    expect(text).toMatch(/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/)
    expect(text).not.toMatch(/统计时间/)
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
 * 2. `formatSize` 最高只到 MB；GB 档要加就得动既有调用点的显示（2026-11-14 现数：导入
 *    utils 版的 7 个文件、共 9 处调用；sftp 那 3 个文件各有同名本地函数，不受影响），不属本批范围。
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
  return date.toLocaleString('zh-CN', { hour12: false })
}
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run test/unit/diskUsage.spec.ts`
Expected: PASS，**16 例**（正文初稿写 15，Task 6 复审补了「原型名键」那一条 ⇒ 16；`1024 * 1024 - 1` 那条走 MB 档下界、GB 档下界的边界都在里面）。现数取法：`grep -c "  it(" frontend/test/unit/diskUsage.spec.ts`。

若 `usageScannedText` 的 `toLocaleString('zh-CN')` 输出与本机 ICU 版本有关，**别把精确文案写进断言**——本仓 `format.spec.ts:42-45` 已经因为「zh-CN 月日分隔符随 ICU 变化」改过一次，所以这里只钉形状（`toMatch(/^\d{4}[-/]\d{1,2}[-/]\d{1,2}/)`）**外加一条反向守卫** `not.toMatch(/统计时间/)`。初稿这句写的是「只钉 `startsWith('统计时间')`」，那是前缀还归 utils 时的口径，2026-11-14 复核时已随上面两处一起翻反 —— 留着就是叫下一个人把断言改回错的那一边。实测本机（Node 24 / UTC+8）该 `toLocaleString` 的**真实串**是 `2026/11/14 14:07:08`（码点逐字打过：分隔符是 `2f` 即 `/`，`/^\d{4}\/\d{1,2}\/\d{1,2}/` 为 true、横杠版为 false）。⚠ **别相信你的眼睛，要相信码点**：这条串经工具输出到屏幕上时 `/` 被渲染成了 `-`（落地方和我各看到一次「2026-11-14」），所以判据写成 `[-/]` 两类都收，而不是照抄屏上那个字符 —— 这正是 `format.spec.ts:42-45` 那条教训的具体形态。

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

⚠ **这一处落地时故意没做，Task 9 必须把两半一起补上。** 落地方选了「不给 dialog 加绑定」而不是
照抄上面这行，理由经控制器复核成立：`ConsistencyCheckDialog.vue` 的模板根节点是**单个**
`<el-dialog>`（`:1-6`）且组件**没写** `inheritAttrs: false`（`grep -n inheritAttrs` 该文件零命中），
所以把一个它尚未声明的 `usage` prop 传进去，Vue 会把它当普通属性**透传到 el-dialog 根上**，
在 Task 7→Task 9 这段窗口里页面上真会出现 `usage="[object Object]"`。
三个选项里 (a) 现在加绑定 = 留一个能看到坏属性的窗口；(c) 现在给 dialog 补一个空 prop = 要动
第四个跟踪文件、而 Step 5 的暂存清单刻意不含它，会留下未提交改动 + 跨任务隐身改动；
(b) 跳过 = 窗口宽度为零（dialog 今天只声明 `visible`，不传就是它现在的行为），且 Task 9 本来就要改那个文件。
⇒ **Task 9 的 Files 清单因此多一行：`frontend/src/pages/data/components/FileListTab.vue`（补 `:usage="usage"`）**。
这不是「落地方漏做」，是决定，别在复审里当缺失报回来。

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
            <span class="section-count" data-testid="disk-usage-chip">
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

⚠ 「统计时间」这一行**不要双份**：上面 `el-descriptions-item` 的 `label` 已经是「统计时间」，所以 value 只能是裸时间串。这条分工**已在 Task 6 正文里定死**（`usageScannedText` 返回 `date.toLocaleString(...)` 本身、T2 断言 `not.toMatch(/统计时间/)`），Task 7 **不要再动 `utils/diskUsage.ts`** —— 原稿把这个改动挂在 Task 7 上，2026-11-14 复核时挪回 Task 6，理由是这个前缀归属只有 utils 的作者能钉住，跨任务改别人的文件必然漏一边。`usageOutsideLine` 相反，它没有 label 可依附，所以保留自带的那句完整话。

⇒ 另：上面那颗 chip 的 class 只有 `section-count`，**初稿还带一个 `usage-chip`，2026-11-14 预检时删掉**。
理由：全仓 grep 下来 `usage-chip` 没有任何 CSS 规则、没有用例选它（Task 8 的 `CHIP` 走
`[data-testid="disk-usage-chip"]`，而 `data-testid` 是本仓既有约定 —— src 里 120 处、e2e 里 80 处），
`popper-class="disk-usage-popover"` 则是**真的被 Task 8 的 locator 依赖**，两者命运不同，别一起删。
留一个谁都不用的 class 就是给下一个人「这是不是该有样式？」的疑问。

- [ ] **Step 4: 类型检查与全量 vitest**

Run:
```bash
cd frontend && npx vue-tsc -b --force --pretty false && npx vitest run
```
Expected: `vue-tsc` 无输出；`npx vitest run` 全绿。**数字必须现跑现取**，别对齐本行写的快照（lessons 的「台账写命令不写快照」）。
本批 Task 6 落地并复审后的**实测基线**：`Test Files 69 passed`、`Tests 967 passed`（`diskUsage.spec.ts` 16 例 +
其余既有）。⇒ Task 7 只加接线、不加 T2 用例，跑出来**应当还是 967**；若变了要么是回归要么是新增了用例，要在报告里说清是哪一种。
`--force` 是必须的：不加时 `tsbuildinfo` 缓存会把「没类型错误」报成假绿（本批 Task 6 实测过一次）。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/api/datafiles.ts frontend/src/pages/data/components/FileListTab.vue frontend/src/pages/data/components/FileListToolbar.vue
git commit -m "feat(data): 文件列表工具栏显示磁盘占用 chip 与拆分浮层"
```

⚠ **暂存清单里刻意没有 `utils/diskUsage.ts` 与它的 spec** —— 那两个文件归 Task 6，且复审已定死
「前缀归属与查表形态都收在 Task 6 内部，Task 7 不回改 utils」（见「Task 6 落地后的订正」）。
⇒ 如果落地时你**需要**改那两个文件才能接通，那不是一个可以顺手做的决定：停下来报告需要改什么、为什么，
由控制器决定是回 Task 6 补判据还是在本批加例。把 utils 一起 `git add` 进来会让这件事在 diff 里隐身。

---

### Task 8: e2e（T3）——chip 的七条渲染与刷新判据

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
import { gotoApp, navByMenu } from '../helpers/nav'
import { uploadFile, uploadMultipleFiles } from '../helpers/upload'
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
    // 2026-11-14 用户拍板（Task 6c）：chip **只显体积**，文件数在浮层分桶行里。
    // 左边那颗 `{{ total }} 个文件` 是列表作用域，chip 的 file_count 是整棵树，两个都写
    // 「N 个文件」会打架 —— 尤其激活刷新之后，Explorer 拷进来的文件只动 chip 不动表格。
    await expect(chip).toHaveText(`磁盘占用 ${bytesText(captured.bytes)}`)
    await expect(chip).not.toContainText('个文件')
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
    // ⚠ 这条原先断的是 `String(captured.file_count)`（整棵树总数）。Task 6c 之后 chip 只显体积、
    // 浮层里给的是**每桶**的计数，总数不再以任何形式出现（两桶时它根本不在文本里 ⇒ 假红），
    // 所以改成按桶断计数串 —— 判据跟着文案分工走，不是跟着旧断言的字面走。
    for (const [key, bucket] of Object.entries<any>(captured.by_type ?? {})) {
      const countText = `${bucket.count.toLocaleString()} 个文件`
      expect(joined, `浮层里必须有 ${key} 这一桶的「${countText}」`).toContain(countText)
      expect(joined, `浮层里必须有 ${key} 这一桶的体积`).toContain(bytesText(bucket.bytes))
    }
    await expect(page.locator(CHIP)).toBeVisible()
  })

  /*
   * 下面三条是 Task 7 复审修复轮**欠下的浏览器判据**：那五个修复里 ①激活刷新 ②失败保留旧值
   * ④连发合并 都没有任何自动化测试能证明（T2 是 node 环境、仓内不装 @vue/test-utils，
   * `grep -rln "mount(" test/unit` 零命中）。不补上，这三条就只是"看起来对"的实现。
   */

  test('占用请求按激活刷新：首屏一次，离开再回来第二次', async ({ page }) => {
    // ⚠ 计数钩子必须在 gotoApp **之前**装：gotoApp 内部是 page.goto，落地那一刻首屏请求
    //    已经发完，装晚了数组永远空 —— 那会让第一条断言红得看不出原因。
    const urls: string[] = []
    page.on('request', (req) => {
      if (req.url().includes('/api/v1/files/usage/')) urls.push(req.url())
    })
    await gotoApp(page, '/data')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
    // 恰好 1 次才说明「进入即拉」只挂在一处：0 ⇒ onActivated 没挂上或挂错组件；
    // 2 ⇒ 有人把 loadUsage() 又加回了 onMounted（keep-alive 首进 mounted+activated 都触发，
    //    正是 DataManagement.vue:266-274 记过的那次双倍请求）。
    expect(urls, '首屏应恰好一次占用请求').toHaveLength(1)

    // 必须是**客户端路由**（点侧边栏），不能是 gotoApp：page.goto 是整页重载，
    // 重载后 mounted 也会重新跑一次，那条「只挂 activated」的判据就变成永真。
    await navByMenu(page, '仪表板')
    await expect(page.getByTestId('page-identity')).toContainText('仪表板')
    await navByMenu(page, '数据管理')
    await expect(page.locator(CHIP)).toBeVisible({ timeout: 15_000 })
    expect(urls, 'keep-alive 回来必须再拉一次（只挂 onMounted 时计数会停在 1）').toHaveLength(2)
  })

  test('占用接口先好后坏：chip 保留上一次的数，且只出声一条', async ({ page }) => {
    let mode: 'ok' | 'fail' = 'ok'
    await page.route(USAGE_ROUTE, async (route) => {
      if (mode === 'fail') {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ code: 'internal_error', message: '服务器内部错误', detail: null }),
        })
      }
      const response = await route.fetch()
      return route.fulfill({ response, json: await response.json() })
    })
    await gotoApp(page, '/data')
    const chip = page.locator(CHIP)
    await expect(chip).toBeVisible({ timeout: 20_000 })
    const good = await chip.innerText()
    expect(good, '前置：首屏应真的拿到一个数').toMatch(/^磁盘占用 /)

    mode = 'fail'
    await navByMenu(page, '仪表板')
    await navByMenu(page, '数据管理')
    // 这一条就是 Fix 2 的正判据：改回「失败置空」的话，红在「chip 不见了」而不是别处。
    await expect(chip, '瞬时故障不许把眼前的数拿走').toHaveText(good)
    // 出声恰好一条：拦截器对同一消息 2s 去重（api/index.ts:26-32），页面自己不该再补一句。
    // 计数**不加文案过滤**，理由同 data.spec.ts:970-975 —— 绕开拦截器的重复提示用文案筛不掉，
    // 而 .filter({hasText}) + toBeVisible 在两条时会撞 strict mode，红得像是选择器坏了。
    const errToasts = page.locator('.el-message--error')
    await expect(errToasts, '刷新失败必须出声，且只出声一次').toHaveCount(1)
    await expect(errToasts.first()).toContainText('服务器内部错误', { timeout: 10_000 })
  })

  test('连发三文件上传：写后刷新塌成 ≤2 次 fresh=1', async ({ page }) => {
    const stamp = Date.now()
    const paths = [0, 1, 2].map((i) => {
      const p = path.join(os.tmpdir(), `e2e_usage_burst_${stamp}_${i}.csv`)
      fs.writeFileSync(p, 'col1,col2\n1,2\n')
      return p
    })
    const fresh: string[] = []
    page.on('request', (req) => {
      const u = req.url()
      if (u.includes('/api/v1/files/usage/') && u.includes('fresh=1')) fresh.push(u)
    })
    try {
      await gotoApp(page, '/data')
      await expect(page.locator(CHIP)).toBeVisible({ timeout: 20_000 })
      const first = page.waitForResponse((r) =>
        r.url().includes('/api/v1/files/usage/') && r.url().includes('fresh=1'),
      )
      await page.locator('button').filter({ hasText: '上传文件' }).click()
      await uploadMultipleFiles(page, paths)
      await first
      // 等合并窗口**彻底收干**再计数：常数是量过的那道闸（USAGE_TRAIL_MS=800）的 2 倍 + 余量，
      // 不是拍脑袋。数早了会把「trailing 还没发」当成 ≤2 通过 —— 那是假绿。
      await page.waitForTimeout(2000)
      expect(fresh.length, 'leading 至少要有一次').toBeGreaterThan(0)
      // 写成 ≤2 而不是 ==2：三个响应若恰好被 Vue 合到同一 tick，只有 leading 一次也合规。
      expect(fresh.length, 'K 连发不许变成 K 次全盘扫描').toBeLessThanOrEqual(2)
    } finally {
      await deleteFilesByNameQuiet(page, 'e2e_usage_burst_')
      for (const p of paths) cleanupQuiet(p)
    }
  })
})
```

**本批上面的浏览器用例共四条，初稿是五条、删掉一条占位的。** 先说清楚一条**计数教训**（控制器自己犯的）：
初稿这一节标题写「三条」本来就少计了一条（实际四条真用例 + 一条占位 = 五条），
我在删占位例时把标题顺着改成「两条」，等于**在错误的两个方向上各走了一步** ——
两次都没数过。现号取法：`sed -n '<Task8 行段>' … | grep -c "^  test("`。
**Task 7 复审修复轮之后本任务从 4 条涨到 7 条**（新增的三条是 ①激活刷新 ②先好后坏保留旧值
④连发合并 这三处修复欠的浏览器判据 —— T2 是 node 环境、仓内不装 `@vue/test-utils`，
组件行为没有任何自动化能替浏览器作证），Task 9 段同样数法 ⇒ **2**，**T3 共 9 例**。
被删的那条占位用例是
`test('新用户目录为空时 chip 说 0 B 而不是 --')`，正文写着「先别实现」、用例体里却留了一句
`apiGet(page, '/files/usage/')` 占位 —— 2026-11-14 复核时直接删掉，理由是那条用例本身站不住：
它要一个没有数据目录的账号，而 P2 project 的 `storageState` 固定是 `ADMIN_STATE`
（`playwright.config.ts:144`），换账号得走 `helpers/auth.ts` 的登录路径，代价比判据值钱；
而 0 B 这条形状已经被 Task 6 的 T2 完整钉住（`usageChipText(base())` ⇒
`'磁盘占用 0 B · 0 个文件'`）。**留着占位用例就是它自己正文里警告的「下一个人的坑」。**
⇒ 落地时把这句理由写进 spec 文件头注释：「空目录态由 T2 钉，不在浏览器里重算」。

- [ ] **Step 2: 跑用例（单文件自起服务，先确认端口没被抢）**

Run:
```bash
netstat -ano | grep -E ":8000|:3000" | head -5
cd frontend && node ../scripts/e2e_pool.mjs --slots=1 -- e2e/data/disk-usage-chip.spec.ts > ../tasks/b2-task8.log 2>&1
```
Expected: 日志末行 `RESULT:` 之前有 `[pool] 结论 MEASURED`、`unexpected 0`。**判绿取这两行，不取退出码**（lessons/testing-gates）。若日志里出现 `EADDRINUSE`/`21001-21004` 段，是上一轮孤儿 slot 目录占着端口——先 `node scripts/e2e_pool.mjs --gc`，别改 workers 数。

⚠ **本机此刻 8000/3000 已经各有一个进程在听**（2026-11-14 控制器实测：`:3000` 是 node、`:8000` 是 python，`git worktree list` 只有主目录 ⇒ 不是别的工作树抢的）。**别 kill 它们** —— 那可能是用户自己开着的 dev 服务。先判这两台服务是不是本分支的代码，再决定复不复用，两条命令就够：
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/v1/files/usage/   # 401=路由在（Task 4 已加载）；404=服务的是旧代码
curl -s "http://localhost:3000/src/pages/data/components/FileListToolbar.vue" | grep -c "disk-usage-chip"   # ≥1 = vite 正在服务 Task 7 的 markup
```
（控制器跑过：`401` 与命中数 `2` ⇒ 两个服务都是当前分支。）服务是旧的又不是本分支 ⇒ 那是**另一个会话**的进程，同样别动，改用空闲端口档跑，并在报告里写清楚是哪个 PID。

另外一条与本任务无关但会被本任务踩到的既有耦合：`e2e/global/error-handling.spec.ts:17/32` 拦的是
`**/api/v1/files/**`，**这个 glob 现在也盖住 `/files/usage/`**。它目前仍成立，理由不是运气而是两道具体的闸：
`toastError` 对同一消息 2s 去重（`src/api/index.ts:26-32`），且它的断言是 `.filter({ hasText })` +
`toBeVisible()`。⇒ 谁以后要在这份 spec 里加「同一条 route 让多个端点都坏」的用例，或者把
`NO_TOAST_ENDPOINTS`/去重窗口改动，都得回来看这一条：`.filter()+toBeVisible()` 在命中两条时会撞
strict mode（`data.spec.ts:970-975` 记过同一次）。

- [ ] **Step 3: 若第一条红，按这个顺序排查（别先改代码）**

1. `captured` 是 `null` ⇒ app 根本没发这一请求。**⚠ 这一条在 Task 7 复审后已经翻反**：
   `loadUsage()` 现在**刻意不在** `onMounted`，而是挂 `onActivated`（keep-alive 下「进入即拉」的
   本仓约定，理由与判据见 Task 7「复审处置」第 1 条）。⇒ 排查顺序改成：
   ①`grep -n onActivated FileListTab.vue` 确认那一行还在；②用例是否真的走进了 `/data`
   （`gotoApp` 后停在别的 tab 或别的 route 就不会 activate）；③`onMounted` 里是否被谁又加回了一次
   `loadUsage()`（加了会变两条请求，第一条用例的计数判据先红，而不是这条）。
   老文案那句「没进 `onMounted`」留着就是叫下一个人去改一个正确的实现。
2. `toHaveText` 只差千位分隔符 ⇒ `toLocaleString()` 的 locale 与 Node 不一致；改成在 spec 里也 `Number(x).toLocaleString('en-US')`，**两边同参**，别改组件。
3. 第三条 `file_count + 1` 不成立 ⇒ 多半是 `fresh=1` 没带上（`params: { fresh: 1 }` 被 `paramsSerializer` 改写了）；打印 `resp.url()` 确认串里有 `fresh=1`。
4. **第五条（激活计数）停在 1** ⇒ 十有八九是这一条自己写法错：用了 `gotoApp(page, '/data')` 当"回来"。
   `gotoApp` 内部是 `page.goto`，那是**整页重载**，重载后 `onMounted` 也会重跑 ⇒ 「只挂 activated」这句
   判据变成永真，测的是浏览器而不是 keep-alive。必须是 `navByMenu(page, '仪表板')` →
   `navByMenu(page, '数据管理')`（模板见 `e2e/data/data.spec.ts:963-965`）。
   反过来 **首屏数到 2** ⇒ 有人在 `onMounted` 里又加了一次 `loadUsage()`，那是回归，改代码不改判据。
5. **第六条 `toHaveCount(1)` 数到 2** ⇒ 先看第二条 toast 的文案：若与第一条**不同文**，说明页面自己补了一句
   （去重只对同一消息生效）⇒ 按约定该删页面那句；若**同文却响两次**，说明去重窗口被改动或两请求跨了 2s
   ⇒ 那是 `api/index.ts:26-32` 的事实变化，来找我，别在 spec 里加 `first()` 把计数糊掉。
   另外 `chip` 文案在失败后变了 ⇒ 检查序号守卫是否被摘掉（过期那趟成功响应会盖掉新值）。
6. **第七条数到 3** ⇒ 合并器没生效：`grep -n "useCoalescedCall" FileListTab.vue` 看 watch 里调的是
   `reloadUsage(true)` 还是裸 `loadUsage(true)`；若代码没问题，先确认 `waitForTimeout(2000)` 确实长于
   `USAGE_TRAIL_MS`（改那道闸必须同步改这里的等待，两处不同步就会时红时绿）。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/data/disk-usage-chip.spec.ts
git commit -m "test(e2e): 磁盘占用 chip 的渲染与写后刷新判据"
```

---

### Task 9: 数据修复中心的差值行

**Files:**
- Modify: `frontend/src/pages/data/components/ConsistencyCheckDialog.vue:22-43`（`el-descriptions` 之后）、`:99-128`（props 与导入）
- Modify: `frontend/src/pages/data/components/FileListTab.vue:59-63`（**补 Task 7 有意推迟的那半**：
  `<ConsistencyCheckDialog … :usage="usage">`，理由见 Task 7 Step 2 的 ⚠ —— prop 声明与绑定必须同一批落地，
  否则今天会有一条透传出来的 `usage="[object Object]"` 属性挂在 el-dialog 根上）
- 行号提醒：Task 7 给 `FileListTab.vue` 加了 21 行、`0cc2b45` 又合并掉一行导入 ⇒ 该文件里所有旧行号
  都已漂过，**别照抄任何写死的号**。现取：
  `grep -n "notifyFilesChanged()" frontend/src/pages/data/components/FileListTab.vue` ⇒ 236/241/272/299/322；
  `grep -n "ConsistencyCheckDialog" frontend/src/pages/data/components/FileListTab.vue` ⇒ 绑定处与导入处各一。

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
- 后端：`OK`（批1 基线 `Ran 2576 … OK (skipped=16)`，**本批 +48 例**：`test_storage_usage_scan.py` 34 +
  `test_storage_usage_cache.py` 4 + `test_files_usage_api.py` 10，三个文件全是本批新建 ⇒ 期望总量 ≈ 2624，
  **数字现跑现取**，别拿这个和当判据），`grep -cE "^(FAIL|ERROR):"` 必须是 **0**。
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
| §4.8 测试（T1 齐全/空目录/隔离/缓存/交叉核对；T3 chip 渲染） | Task 2/3/4/5（T1 **48** 例 = scan 34 + cache 4 + api 10）+ Task 6/6c（T2 **16** 例，chip 文案回退后 4→3、分桶 4→5，净零）+ Task 8/9（T3 **9** 例 = Task 8 **7** + Task 9 **2**）—— 三个数都是 2026-11-14 现跑的：`grep -c "def test_" test/backend/test_storage_usage_{scan,cache}.py test/backend/test_files_usage_api.py`、`grep -c "  it(" frontend/test/unit/diskUsage.spec.ts`、代码块内 `grep -c "^  test("`。（初稿写的是 T1 23 / T2 15 / T3 6，三处都随复审、拆档、文案回退与修复轮过期：T1 多了装配层与缓存两族，T2 多了原型名键一条，T3 欠了修复轮三条浏览器判据。）|

**2. 占位符扫描**：无 TBD/「类似 Task N」/「加适当错误处理」。一处「故意写错再改」是显式教学步骤（Task 4 Step 1 的 `test_只读不接受POST`），写明了动作为什么。Task 8 原先还带一条「写进代码块、正文再叫作者删掉」的占位用例，2026-11-14 复核时判定它自己就是它警告的那种坑，已从正文移除并保留理由（见 Task 8 正文）。

**3. 类型一致性**：`_scan_tree` 返回的键（`bytes`/`unique_bytes`/`file_count`/`by_type`）= `_compute_usage` 用的键 = `FileUsage` 的字段 = e2e 的 `captured.*`。`_db_map` 的 `map/in_rows/in_files/in_bytes/out_count/out_bytes` 只在 Task 3/4 内部与 `_compute_usage` 的映射处出现，未泄漏到前端。（初稿这里写的是 `_db_totals` 与 `in_count` —— **两个名字都不存在**，`grep -rn "_db_totals\|in_count" apps/` 零命中；真名是 `_db_map`（`apps/datafiles/storage_usage.py:172`）与 `in_rows`。要钉的实质结论不变，且已独立复核：这六个键没有一个出现在 `FileUsage` 里。）`get_user_usage(user, fresh=…)` / `clear_usage_cache()` 在 Task 4/5 用法一致。前端 6 个函数名在 Task 6 定义、Task 7/9 调用，逐字相同。`usageScannedText` 的前缀归属**已收在 Task 6 内部**（返回裸时间串 + T2 断言 `not.toMatch(/统计时间/)`），Task 7 只负责给 label，不再回改 utils —— 原稿写成「Task 7 去改 Task 6 的文件」，2026-11-14 复核时挪回 Task 6，因为跨任务改别人的文件必然漏一边。

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

### 控制器处置（同一轮，第 3 条按 (a) 落地）

**(a) 拆档，没挂绊线。** `CacheBehaviourTests` 整类（66 行，含 setUp/tearDown/`_counting_compute`）
逐字节搬进新档 `test/backend/test_storage_usage_cache.py`，搬运前后各跑一次行级比对
（`old[564:630] == new[new.index('class CacheBehaviourTests'):]` ⇒ `IDENTICAL`，66/66）——
搬的是文本，不是重写，所以四条变异判据不会因为「顺手改一改」而失去效力。
新档自己带 imports（`shutil`/`tempfile`/`mock`/`TestCase`/`User`/`storage_usage`），
搬完用 AST 反查旧档未用 import ⇒ `UNUSED: []`（`mock` 在注入用例里仍要用，别顺手删）。

现数：`test_storage_usage_scan.py` **562**、`test_storage_usage_cache.py` **85**，
三档合跑 `Ran 48 tests in 19.479s / OK`（`tasks/b2-task5-split.log`，条数与拆分前一致 ⇒ 零丢失），
门禁 `npx vitest run test/unit/lineLimit.spec.ts` ⇒ `15 passed (15)`（`tasks/b2-task5-split-linelimit.log`）。

**留给后续任务的一条正文纪律：** 计划里凡是写「Modify：某文件（追加一个类/一批用例）」的步骤，
落点行数是**没量过**的 —— Task 3→4→5 每一轮都在往同一个文件里加肉（490→562→630），
单看每轮都只加几十行，撞闸的是**累计**。⇒ Task 6 起，写「追加」之前先 `wc -l` 落点，
余量不足 60 行就在正文里直接给出新档名，而不是等落地方撞红了再让控制器处置。

---

## Task 6 落地后的订正（2026-11-14，T2 文案纯函数 + 9 档变异）

落地方 `1d590e6`（3 文件 / +245），规格复审 `SPEC: ✅ compliant`（0 个代码问题），
控制器另加一次判据补强并提交 `3f10f90` + 本轮。现数：`diskUsage.ts` **84**、
`diskUsage.spec.ts` **146**、`datafiles.ts` **324**；T2 `15 passed`、全量 `69 files / 966 passed`、
`vue-tsc -b --force` exit 0、`lineLimit` `15 passed`。

1. **Step 3 的期望文案是猜的。** 实测红的是 `Cannot find module '../../src/utils/diskUsage'`，
   不是正文写的 `Failed to resolve import` —— 同一失败类、实现确实缺席，不影响判绿路径，
   但「Expected: <原文>」这种句子也必须是从输出里抄的，不能凭印象写。

2. **M8 首轮存活 ⇒ 本批第 6 次抓到「fixture 让两个实现等价」。** 原 fixture 里
   `mismatch_over_threshold` 与 `mismatch_diff_bytes` 同生同灭，所以「看标志」和
   「看差值非零」在给定断言下**字面等价**，变异换掉判据来源照样 15 全绿。
   补一条 `flag=false, diff=12345 ⇒ null`（**不动**原有两条断言；**当时**仍 15 例 —— 这个 15 是本轮的快照，
   复审又补了「原型名键」一条，现号是 **16**，取法见 Step 5 那句）：
   真库确有这一形状 —— `_mismatch()` 返回的是两个独立的量（`storage_usage.py:234-236`），
   1% 漂移就是「差值非零但未超阈值」。二轮 9/9 全杀。

3. **「8 个既有调用点」是正文里的假数字，落地方量的、控制器独立复核的一致是 7 个文件 9 处。**
   `grep -rn "import.*formatSize.*from" frontend/src` ⇒ 恰好 7 个文件；调用表达式
   `1+2+1+1+1+1+2 = 9`（`BatchDataTab`、`UnregisteredDirCard` 各 2 处）。
   sftp 那 3 个文件（`SftpBrowser.vue:510`、`SftpStatsBar.vue:52`、`SftpFileTable.vue:207`）
   各有**同名本地函数**，不碰 utils 版，所以既不计入也不受影响。
   ⇒ 落地方把实测数字写进注释（守 2026-10-17「注释里的每个数字必须有一条命令产出过它」），
   但**只改了 utils 的 docstring，漏了 T2 里那条同源的注释** —— 同一份改动里 8 和 9 互相矛盾，
   控制器补 `3f10f90` 对齐，计划正文三处同步改掉。

4. **`zh-CN` 分隔符：屏幕上看到的字符是假的，码点才是真的。** 本机（Node 24 / UTC+8）
   `toLocaleString('zh-CN',{hour12:false})` 的真实串是 `2026/11/14 14:07:08`，
   逐字码点 `32 30 32 36 2f 31 31 2f 31 34 …`（`2f` = `/`），`/^\d{4}\//` 为 true、
   横杠版为 false —— 而这条串经工具输出到屏上时 `/` 被**渲染成** `-`，落地方和控制器各看到
   一次「2026-11-14」。⇒ 判据用 `[-/]` 两类都收是对的，且**别照抄屏幕上那个字符**。

5. **控制器自己引入的一次「注释写错变异对象」，附两次工具坑。** 复审 Minor 说
   `it('负数与 NaN …')` 标题承诺了负数却只断言 NaN。改法不是补一条负数断言
   （`bytes` 来自 `st_size`、`diff` 来自 `abs()`，负数造不出来，钉它=钉不出来的形状），
   而是把标题收窄成它真正钉的东西，并补 `±Infinity` 两条。第一次把理由写成
   「换成 `!Number.isNaN(bytes)`」时实测 **11 条同时红**（那个坏实现把所有有限值都变成 `--`），
   说明我描述错了变异对象：真正只由 Infinity 两条杀的是**同极性**的
   `Number.isNaN(bytes)`（只拦 NaN）⇒ 实测 `1 failed / 14 passed`，失败信息
   `'Infinity GB' to be '--'`。注释已按这个改；两条各压一档（`+Inf` 走 GB 档、
   `-Inf` 走 B 档），所以都留。**先跑基线绿、再跑变异**现在是脚本里的硬断言。

   两次工具坑值得单独记（都在 `tasks/` 脚本里，不在产品代码里）：
   - `subprocess.run(['npx', …])` 在本机直接 `FileNotFoundError` —— `npx` 是 `.cmd`，
     得 `shell=True`。而脚本 `finally` 里那句 `sys.exit(0 if ok else 1)` 把在飞的异常
     **整个吞掉**，于是一次什么都没跑的变异看起来「还原成功」。
   - 改成 `shell=True` 后，`print` 中文用例名到 GBK stdout 抛 `UnicodeEncodeError`，
     异常从 `try` 里冒出来时 `finally` 的还原写盘又撞上 `OSError [Errno 22]`，
     **源文件被留在变异态**（守卫里成了 `Number.isNaN`，`git hash-object` ≠ HEAD）。
     是被「跑完顺手 `git status`」发现的，不是被脚本发现的。
     ⇒ 变异脚本的四条硬要求：① 基线先跑绿再变异；② `finally` 只做「写回 + flush +
     `os.fsync` + sha 复核」，不做任何可能抛异常的打印；③ stdout 用
     `TextIOWrapper(errors='replace')`，非 ASCII 一律落盘日志再看；④ 跑完**独立**用
     `git hash-object <file>` 对比 `git rev-parse HEAD:<file>` 证明源干净，别信脚本自己的话。

6. **T3 本任务不跑，是有意的。** `node scripts/e2e_affected.mjs --dry-run` 把
   `src/utils/diskUsage.ts` 判到「全局清单 ⇒ 全量 e2e」，但那是**按路径兜底命中**：
   `grep -rn diskUsage frontend/` 此刻除新 spec 外**零 importer**（Task 7 才接线），
   浏览器面上没有任何东西会变。⇒ 全量池 + 后端全量留在 Task 10 收口档，
   本批内只跑 T2 + `lineLimit` + `vue-tsc`。

7. **复审带出的两条计划正文假事实，已就地改掉**（都在本文档，不在代码）：
   Step 5 那句仍写「所以这里只钉 `startsWith('统计时间')`」—— 前缀归属翻反之后这句是错的，
   留着就是叫下一个人把断言改回错的一边；自审 §3 引的 `_db_totals` 与 `in_count`
   **两个名字都不存在**（真名 `_db_map` / `in_rows`，`grep -rn "_db_totals\|in_count" apps/` 零命中），
   实质结论「六个内部键没泄漏到前端」由复审独立复核成立。

### 控制器复核后的再订正（Task 6 那一轮）

代码质量复审给出 2 个 Important + 4 个 Minor。逐条核实后：两个 Important 都成立、各自补了能杀自己的判据；
`?? {}` 四条链本机复核全成立后删掉；两条 Minor 是判据/结构与注释；Issue 6 的两项**明确不做**（附实测理由）。
全部由 `tasks/mutate_b2_task6_fix.py` 现量（node 直连、两路 text/json 对账、`finally` 只做写回+flush+fsync+sha），
跑完再由**外部** `git hash-object` + `diff` 独立复核源文件逐字节还原，不信脚本自己的话。

1. **Important #1 —— 原型键查表：本仓第二次踩同一个坑，教训就在此。** `diskUsage.ts:53` 原写
   `TYPE_LABELS[key] ?? key`。`??` 只挡 null/undefined，而一级目录名可以是
   `constructor`/`toString`/`hasOwnProperty`/`__proto__`（`_scan_tree` 按路径第一段建桶，
   `storage_usage.py:111-112`、`:138-163`；应用自建只有 `single/`、`batch/`，但 UI 已在显示未登记目录，
   所以任意第一段是**受支持状态**不是假想），那几键会从原型取到 Function/`Object.prototype` 原样递成
   `label`——`UsageRow.label` 标 `string` 骗过 TS、不抛错，浮层把「function toString(){…}」当桶名显示。
   控制器独立复现：`JSON.stringify(label)` 得 `undefined`（值就是函数）。
   ⇒ **改判据前先例已在**：`utils/audit.ts:24-29` 与 `test/unit/audit.spec.ts:160-170` 早修过**同一形状**，
   注释原点名这个失败模式。先例存在、本轮落地方没查到——这才是教训：抽「键来自外部路径段」的查表 utils 时，
   先 grep 同类查表有没有 own-property 先例。落地用同款 `Object.hasOwn(TYPE_LABELS, key) ? TYPE_LABELS[key] : key`，
   注释一行指向先例（不复述理由，理由住在 audit.ts）。测试用 `Object.fromEntries`（走 CreateDataProperty，
   能把 `__proto__` 造成真·自有键；对象字面量与 `obj[k]=` 都会误触 `__proto__` setter），对四个键断
   `typeof label === 'string'` 且 label 集合 == 键集合。**TDD 先红**：`expected 'function' to be 'string'`。
   保留原有 `staging`（未知普通键）那条——它与之是不同失败类（本来就能原样显示，vs 本会被静默换成非字符串）。

2. **Important #2 —— 陈旧披露的时钟分量此前完全没钉。** `scanned_at` 进载荷的唯一理由就是把 ≤30s 分桶 TTL
   缓存（`storage_usage.py:21-22`、`:35`）暴露给用户；旧判据只钉日期形状 `^\d{4}[-/]\d{1,2}[-/]\d{1,2}` ⇒
   时钟对测试不可见。沿用仓内异源法（`format.spec.ts:42` 不钉精确串防 ICU 漂、`:50-59` 用 hour-cycle 边界）加
   `toMatch(/\d{1,2}:\d{2}:\d{2}/)`（钉到时:分:秒）+ `not.toMatch(/[上下]午/)`（钉 24 小时制）。
   夹具 `2026-11-14T23:07:08+00:00`，**只改本例、不动 `base()` 共享默认**——其余读 `scanned_at` 的用例
   要么自带值、要么走 null 分支，改共享默认无收益、且要重新证明它不弱化别例（报告里也说明这一选择）。
   ⚠ **「取偏晚时刻」不是杀伤力的来源**（复审指出，控制器认同）：秒针正则对任何小时都成立，
   `[上下]午` 两类都收，所以杀不杀与时值无关 —— 本机 UTC+8 下这条 UTC 串实际落**次日 07:07**，
   连「晚上」都不是。留这个值只是可读性，**下一个人别把它当边界去"修"**，也别据此再加小时相关的断言。

   ⚠ **对「删 `hour12:false`」这一变异的实测反驳（本机）**：本机 Node 24.15.0 / zh-CN ICU / TZ=+480 现量
   `toLocaleString('zh-CN')` 与 `toLocaleString('zh-CN', { hour12: false })` **逐字节相同**（`2026-11-15 07:07:08`），
   zh-CN 默认在本机已是 24 小时制 ⇒ 「删掉 `hour12:false`」在本机是**等价变异、任何行为断言都杀不掉**（N2 存活）。
   复审「删了会变 12 小时 + 上午/下午」是**他那台 ICU 的本机事实**，不是通用结论（撞 CLAUDE.md「本机实测值」那条）。
   守卫本身仍对：把 `{ hour12: false }` 翻成 `true`（N2b）本机出 `上午7:07:08`（夹具是
   `23:07:08Z`，UTC+8 落次日 07:07 —— 修复轮原先写的「`下午10:07:08`」是**拿另一个夹具算的**，
   复审实测两处引擎都出 `上午7:07:08`，2026-11-14 更正），被 `not.toMatch(/[上下]午/)` 杀掉，
   证明这条断言有牙；而「真正要紧」的那条（`toLocaleString`→`toLocaleDateString` 丢时分秒，N3）本机必红（被秒针正则杀）。

3. **Minor —— 删 `?? {}`（Issue 3）。** 四条链本机逐个复核成立：① `_scan_tree` 先置 `by_type = {}` 并无条件返回
   （`storage_usage.py:138`、`:163`）；② `_compute_usage` 逐字复制 `'by_type': scan['by_type']`（`:258`）；
   ③ 视图 `Response(get_user_usage(...))` 无 serializer 过滤（`usage_views.py:27`）；④ `KeyedLRU.get_or_compute`
   进程内缓存 `compute` 原对象、不重新序列化（`keyed_lru.py:79-81` `value = compute()` → `self._data[key] = value`）。
   ⇒ 四条全成立，`?? {}` 是死代码（且 `FileUsage.by_type` 必填，`datafiles.ts:315`，TS 侧也多余），删。
   删除本身行为不变 ⇒ 无测可钉它；改用 sanity 变异 `Object.entries(by_type)`→`Object.entries({})`（N4）
   证明 rows 判据确有牙（杀 3 条：已知键映射 + 原型名键 + 根目录散文件）。

4. **Minor —— 拆 describe（Issue 4）。** 原 `diskUsage.spec.ts:114` 把三个不相干函数塞一个 describe，
   与 `format.spec.ts`「一导出函数一 describe」相反。拆成 `usageOutsideLine` / `usageMismatchLine` / `usageScannedText`
   三段。测试名与 `base(over: Partial<FileUsage>)` 都是 house practice，保留不动。

5. **Minor —— 三处未写边界（Issue 5，纯注释）。** 每个数都本轮现量：
   - `usageBytesText` 只喂非负整数：`(-1073741824)`=`'-1073741824 B'`（负数进不了 KB/MB/GB，各档只卡上界）、
     `(1023.6)`=`'1023.6 B'`；今天载荷（bytes 来自 `st_size`、diff 来自 `abs()`）造不出这两态，故不钉负数断言，
     但下一个消费者 Task 9 修复对话框正是会往里传带符号差值的地方。
   - GB 是故意天花板：`(1024 ** 4)`=`'1024.00 GB'`，6 TiB 目录读成 `6144.00 GB`；sftp 三个本地 `formatSize`
     （`SftpBrowser.vue:510`/`SftpStatsBar.vue:52`/`SftpFileTable.vue:207`）同样封到 GB，别加 TB 档。
   - 不复用 `formatTime`：`formatTime('2026-11-14T23:07:08+00:00')`=`'11/15 07:07'`（无年份，跨年读错）、
     `formatTime('not-a-date')` 抛 `RangeError: Invalid time value`（正是 `diskUsage.ts` 里 `Number.isNaN` 守卫要挡的）。

6. **明确不做（Issue 6），附判据。**
   - **不给等 `bytes` 桶加排序 tiebreaker**：浮层只 2–3 行（Task 1 P3 实测 tops 仅 `{'single':98,'batch':14}`），
     同体积桶内容逐字相同，且本仓**没有像素快照判据**可钉顺序——`grep -rn "toHaveScreenshot" frontend/test` 零命中
     （`dashboard-loading.spec.ts:105`、`type-snapshot.spec.ts:12` 两处正文明确写本仓不用 `toHaveScreenshot`）。加了只增复杂度。
   - **不给计数的 `toLocaleString()` 强塞 locale**：`frontend/src` 有 **28** 处无参 `toLocaleString()` 走宿主 locale，
     一致性压倒精确串，与 Issue 2「分隔符随 ICU 漂所以不钉精确串」同一条取舍。

   变异表（`tasks/mutate_b2_task6_fix.py` 现量，两路对账一致）：

   | 变异 | 期望杀它 | 实测 |
   |---|---|---|
   | N1 `hasOwn` → `TYPE_LABELS[key] ?? key` | 原型名键 | 杀掉（红 1，`typeof label` 得 `function`）|
   | N2 删 `hour12: false` | —（复审变异1）| **存活：本机等价变异，见第 2 条** |
   | N2b `hour12:false → true` | 值只有时间本身 | 杀掉（`上午7:07:08`，证 `not.toMatch(/[上下]午/)` 有牙）|
   | N3 `toLocaleString → toLocaleDateString` | 值只有时间本身 | 杀掉（丢时分秒，秒针正则红）|
   | N4 `entries(by_type) → entries({})` | 已知键映射 / 原型名键 / 根目录散文件 | 杀掉 3 条（rows 判据有牙）|
   | M1–M9（复审原 9 档；M6/M9 锚点随 Issue1/2 迁到新行）| 逐条同 `mutate_b2_task6.py` | **9/9 全部仍被杀，无一脱钉** |

7. **现数（本轮之后）：** `diskUsage.spec.ts` **16 passed**（+1 原型键例；拆 describe 不增不减）、全量
   `69 files / 967 passed`（较复审基线 966 +1）、`lineLimit` `15 passed`、`vue-tsc -b --force` exit 0；
   `diskUsage.ts` **84 → 108**、`diskUsage.spec.ts` **146 → 177** 行（均在 600 闸内）。还原独立复核：
   `git hash-object frontend/src/utils/diskUsage.ts` == pristine（`e322de9c…`）、`diff` 逐字节 IDENTICAL、
   `git status --short` 只剩两处意图内改动。

8. **T3 本轮不跑，是有意的。** `node scripts/e2e_affected.mjs --dry-run` 按**路径**把 `diskUsage.ts` 判到
   「全局清单 ⇒ 全量 e2e（兜底命中）」，但它此刻除测试外零 importer（Task 7 才接线，
   `grep -rn diskUsage frontend/src` 只命中自身路径注释行），浏览器面无物可变 ⇒ **本轮不欠 T3**，
   全量池 + 后端全量仍留 Task 10 收口档（与本节既有第 6 条的分工一致）。

9. **同类缺陷在仓内还有两处，本批不动，记为遗留。** 控制器全仓 grep `tbl[key] ?? key` 形态的
   查表（`grep -rnE "[A-Z_]{3,}\[[a-z]+\] (\?\?|\|\|)" frontend/src`）⇒ 三处命中，除本文件的
   `TYPE_LABELS`（已修）外还有：
   - `frontend/src/pages/analysis/components/ChartDock.vue:141` `TITLES[k] ?? k` —— 表是
     `Record<ChartKey, string>`（**闭合联合类型**），键是 dock key；风险只来自「持久化布局里
     被写坏/被改过的 key」，今天没有正常路径能喂进原型名。
   - `frontend/src/pages/settings/components/ExportTemplateSettings.vue:91`
     `EXPORT_TEMPLATE_VARIABLE_LABELS[v] ?? v` —— 表是 `Record<string, string>`（开放），但
     `v` 来自 `constants/export-templates.ts` 里 `EXPORT_TEMPLATE_META[*].variables` 这份
     **人工维护的清单**，喂进原型名要有人故意往清单里写。
   ⇒ 判据：**同一形态、不同可达性**。`diskUsage` 这一处之所以是真 bug，唯一理由是它的键来自
   **文件系统一级目录名**（无界输入，`storage_usage.py:111-112`），另外两处的键集是闭合的。
   所以不在本批顺手改（改它们各需要自己的用例，且都不属于磁盘占用这一批），
   但**遗留清单要写明「下次谁动这两个文件，顺手换成 `Object.hasOwn` 形态并补一条原型名键的
   判据」**，别再攒第三次。`frontend/src/utils/audit.ts:24-29` 是这一族的第一次，本文件是第二次。

10. **本轮控制器补的一条注释**：`hour12: false` 是等价变异这件事只写在台账里不够 ——
   下一个人看实现代码会把它当冗余参数删掉（删了确实全绿）。已在
   `usageScannedText` 的 docstring 里补第 3 条，说明「契约由 T2 的 `not.toMatch(/[上下]午/)` 守，
   这一项留着是给换 ICU / 换 locale 兜底」，并附上实测的两条（同串 / 翻 `true` 即红）。
   ⇒ 补完现数：`diskUsage.ts` **108 → 113** 行（闸内）、T2 仍 `16 passed`、`lineLimit` `15 passed`、
   `vue-tsc -b --force` exit 0；上面第 7 条的 108 是补注释前的数，留着不改是为了让「谁加了几行」可追溯。

### 复审处置（Task 6 修复轮之后，`RE-REVIEW: 2 issue(s)` → 均已完成）

复审独立复核后**关闭**了 Issue 1、Issue 2 与 Minor 3/4/5，并把我方三条注释全部实测为真
（`zh-CN` 与 `{hour12:false}` 逐字节相同这一条，复审在 Node 24/ICU 78.2 与** shipped 引擎
Electron 33 = Chromium 130 / ICU 74.2** 两边各测一次，结论相同 ⇒ 等价变异不只是测试机的事实，
生产引擎同样，第 10 条那条注释站得住）。留下的两个 Minor 都是**注释/台账写了没人现量过的串**：
（本轮改完现数：`diskUsage.spec.ts` **177 → 180** 行、`diskUsage.ts` 仍 113、
T2 `16 passed`、`lineLimit` `15 passed`、`vue-tsc -b --force` exit 0 空日志。）

- `diskUsage.spec.ts:170` 原写「让 12 小时制的『下午』露馅」，但本机 UTC+8 下夹具落**次日 07:07**，
  翻 `hour12:true` 出的是 **`上午7:07:08`**。断言仍杀得住（`[上下]午` 两类都收），但注释指错了字形，
  下一个人看到 `上午` 会以为判据怕时区。已改成实话：杀伤力与时值无关，且**别去"修"这个跨日夹具**。
- 台账两处（正文与变异表）记的 N2b 现量是 `下午10:07:08` —— 复审实测**两个引擎都出 `上午7:07:08`**，
  `下午10:07:08` 是 `14:07:08Z` 那条**别的夹具**的 h12 渲染（修复轮大概是照着 `base()` 的旧默认心算的）。
  两处已按实测更正，并写明「原先那个值是拿另一条夹具算的」。

**复审补了一条我方漏掉的、而且是决定性的一环**（Issue 3 删 `?? {}` 的判断）：台账原本只数到四条链，
复审指出还有第五条 —— `test/backend/test_files_usage_api.py:22-24, 74-79` 用
`set(data) == set(FIELDS)` 钉返回体（刻意用集合等号，**既拦缺键也拦多键**，`by_type` 在 `FIELDS` 里）。
⇒ 「将来后端把这个键过滤掉」并不是通向渲染期 `TypeError` 的静默路径，它会先在 T1 红，
而 T1 正是拥有这份契约的那一层。复审给的结论我采纳并落在这里：**内联 `?? {}` 是错的那一侧** ——
它把一个已被上游测过的不变量复制成一份更弱、且没有测试的第二副本；`FileUsage.by_type` 是必填，
TS 本来就不许 `undefined`；而同函数读 `bucket.bytes`/`db_outside_root_count` 都不设防，
单独留一个 `??` 会读成「这个字段特殊」。

**⚠ 带进 Task 7 的复开条件**（复审给的，理由成立）：上面这套论证的前提是
「**契约边界在后端**」。今天 `frontend/src/api/*.ts` 里连取数函数都没有
（`grep -rn "usage" frontend/src/api/*.ts` 只命中接口注释行），Task 7 要新写的
`getFileUsage` 一旦**对返回体做规范化/挑字段**，边界就搬进前端，「信类型」这句立刻变弱。
⇒ Task 7 的取数函数**照原样把 `data` 交出去**，不要顺手补默认值；真要做字段归一，
就得同时在前端一侧给它自己的判据，而不是加一个 `?? {}`。

**不做的一条硬化（记录理由，不是遗漏）**：复审建议可把日 period 类扩成
`/[上下]午|凌晨|中午|晚上|AM|PM/` 以防未来 ICU 采用 CLDR 细粒度 zh 日 period。
实测当前 zh-CN 在 ICU 74.2 / 78.2 上**只出** `上午`/`下午` 两类（24 小时全扫、跨
UTC / Asia/Shanghai / America/New_York / Pacific/Midway / Europe/Warsaw），
`AM/PM` 与点号时钟在 locale 字面量仍是 `'zh-CN'` 时不可达 ⇒ **现在不加**。
这是给「假想未来的 ICU」加断言，而本批的判据纪律是给**当前可达形状**加断言；
真要哪天翻红，那时补的成本低于现在多一条没人知道为什么存在的正则。

---

## Task 7 落地后的订正（2026-11-14，接线 + 一处有意的偏差）

落地两个提交：`b925d2b`（3 文件 / +75 −2）与控制器补的 `0cc2b45`（一行导入合并）。
现数：`api/datafiles.ts` **334**、`FileListTab.vue` **393**、`FileListToolbar.vue` **173**，
（这三个数是 `b925d2b` 那一刻的快照，写晚了半拍就过期：我自己下一提交 `0cc2b45` 合并了两行导入，
`FileListTab.vue` 当场变 **392**，复审修复轮 `1651aee` 之后是 **465**；`git show <sha>:<file> | wc -l`
是唯一可靠的取法，别拿本行当现状 —— 这正是本页「行号会腐烂」那条纪律的第 4 个实例，前 3 个见第 6 条。）
全部远离 600 闸（派发前量过：324 / 372 / 131，所以这一批不存在撞闸风险，那条纪律已经生效）。
门禁现跑：`npx vue-tsc -b --force --pretty false` exit 0 且日志 **0 字节**；
`npx vitest run` ⇒ `Test Files 69 passed` / `Tests 967 passed`（**与派发前逐位相同** ⇒
Task 7 不加 T2 用例这句是对的，既无回归也无新增）；`lineLimit.spec.ts` ⇒ `15 passed`。

1. **`utils/diskUsage.ts` 与其 spec 一行未动（这是判据，不是巧合）。** 落地方的暂存清单里
   刻意不含这两个文件，`git show --stat` 只有 3 个文件 ⇒ 复审定下的「前缀归属与查表形态收在
   Task 6 内部」没有被跨任务改写。Task 7 只 import 四个函数（`usageChipText` /
   `usageBreakdownRows` / `usageOutsideLine` / `usageScannedText`），`usageMismatchLine`
   留给 Task 9、`usageBytesText` 由前四个内部调用，都不出现在 toolbar 里。

2. **正文有一行是错的，落地方没照抄，而是停下来报了三个选项 —— 这是本批第一次「落地方推翻正文」。**
   Step 2 让给 `ConsistencyCheckDialog` 也加 `:usage="usage"`。**不做的理由经复核成立**：
   该组件模板根节点是单个 `<el-dialog>`（`ConsistencyCheckDialog.vue:1-6`）且全文
   `grep -n inheritAttrs` **零命中** ⇒ 未声明的 prop 会按属性透传到根 DOM 上，
   Task 7→Task 9 这段窗口里页面真会带一条 `usage="[object Object]"`。
   三选一里 (a) 留一个肉眼可见的坏属性窗口、(c) 要动第四个跟踪文件（Step 5 暂存清单不含它 ⇒
   未提交改动 + 隐身跨任务改动），(b) 窗口宽度为零。⇒ 采纳 (b)，
   **Task 9 的 Files 清单因此多一行 `FileListTab.vue`**（已在上面 Task 9 处写明）。

3. **`filesVersion` 的覆盖面比注释写的更大，注释仍成立。** 落地方复核五个
   `notifyFilesChanged()` 调用点**内容都在、位置漂了两次**（Task 7 加 21 行 ⇒ 220/225/256/283/306 →
   237/242/273/300/323；`0cc2b45` 合并一行导入 ⇒ 再到 **236/241/272/299/322**，这是本条的现号，
   现取一律用 `grep -n "notifyFilesChanged()" FileListTab.vue`，见下面第 6 条），
   并且 `BatchDataTab`、`SftpBrowser` 这些**外部**写路径同样 bump ⇒ watch 一行覆盖得比声明的更多。
   控制器按文件现数（`grep -rc "notifyFilesChanged()" src --include=*.vue --include=*.ts`）：
   `BatchDataTab.vue` **5**、`FileListTab.vue` **5**、`SftpBrowser.vue` **4**、
   `SftpSearchPage.vue` **1**（落地方没点这个文件，一并记上）、`stores/files.ts` **2**（定义 + 内部调用）
   ⇒ 除 store 自身外**共 15 处**生产者，而 chip 只挂在 FileListTab 上，所以「一行覆盖全部」是真的覆盖了
   **15 类写事件里落在本 tab 上的 5 类**，其余 10 类只要发生在别的 tab，也会经同一个 store 传到本 tab
   的 watch（本 tab 挂载时才生效，未挂载不拉数 —— 这正是把取数放在 `FileListTab` 而非全局的含义）。
   **唯一不 bump 的 FileListTab 内写操作是标签编辑**（`:35` `@tags-changed="loadAllTags"`，
   走 `useTagEditing`→`setTags`，实测该处理器附近没有 `notifyFilesChanged`）—— 它改的是标签，
   不改字节数与文件数，所以占用 chip 不需要为它失效。⇒ 注释那句「覆盖全部『做完就要看到新数』的场景」
   在**本功能口径（bytes / count）**下是真的；如果哪天占用统计纳入跟标签有关的量，这句话就过期了。

4. **`el-descriptions` + `v-for` 会不会渲染：推理过，但没在浏览器里证明。** 落地方按
   element-plus 2.14.0 的 `descriptions/src/description.vue` 判定：它用
   `flattedChildren(slots.default())` 递归展平，`v-for` 产生的 Fragment 会被展开，
   再按 `node.type.name === COMPONENT_NAME` 过滤；`v-if` 为假时留下的是注释节点，被同一个过滤器丢掉
   ⇒ 拆分行、空态行、目录外行、统计时间行都应当渲染。**置信度高，但这类判定 tsc 与 vitest 都看不见**，
   所以 Task 8 的**四条**浏览器用例必须真的断到：hover 打开 `.el-popper.disk-usage-popover`、
   popper 里每个 `by_type` 桶有一行、`by_type` 为空出「没有文件」、
   `db_outside_root_count>0` 出「目录外记录」、统计时间那行的值是裸时间串（**不许出现「统计时间：统计时间」**）。
   残留两条风险留给 Task 8 兜：一级目录名恰好叫「单文件」会让 `:key="row.label"` 撞键（不现实，不处理）；
   popper 的 teleport 样式与 hover 行为完全未验。

5. **派发前控制器改掉的两处正文缺陷**（都属于「正文会让落地方做错事」那一类）：
   Step 5 的暂存清单原本带着 `utils/diskUsage.ts` 与它的 spec —— 与复审定下的边界矛盾，
   照抄就会让跨任务改动在 diff 里隐身；Step 4 的基线还写着 `68 文件 / 951 例 ⇒ 69/966`
   （Task 6 复审补例后真值是 69/**967**），且没写 `vue-tsc` 必须 `--force`
   （本批实测过一次 tsbuildinfo 假绿）。

6. **行号是一种会腐烂的引用，本批已经被它咬了三次 —— 规矩改成「符号 + 现取命令」。**
   第 3 条那串号在**同一天内漂了两次**：Task 7 给文件加 21 行（220/225/256/283/306 →
   237/242/273/300/323），紧接着控制器自己那一行导入合并（`0cc2b45`）又把它整体减 1
   （→ 236/241/272/299/322）—— 而后一条提交**没有碰这四个调用点里的任何一行**，
   这正是危险所在：改动与被引号无关，号却照样失效。
   规格复审抓到的是第三例（它指出台账与 Task 9 Files 清单里的号都是上一分钟的快照）。
   ⇒ 三条落地规矩：① 台账/正文引位置时**优先引符号名 + grep 命令**
   （`grep -n "watch(() => filesStore.filesVersion" FileListTab.vue`），必须写号就同排这条命令；
   ② 写号要标「截至哪一次提交」，否则下一个人无从判断它是否还活着；
   ③ 每改一个跟踪文件，收尾时 `grep` 一遍计划里对该文件的裸行号引用（本批 29 行的头部摘要就还留着
   Task 7 之前的 `:322-327`，已改为符号式）。
   这条与既有纪律同源不同物：「台账写命令不写快照」管的是**门禁输出**，这条管的是**代码位置**。

### 复审处置（Task 7 那一轮，2 Important + 5 Minor）

接线改动收在 `1651aee`（2 文件 / +99 −8），本台账与**一处样本数字订正**在紧随的那个 docs 提交里：
`FileListTab.vue` 顶上那段注释原本写「现量 3.45–6.61 ms/次、均值 4.22 ms」，那是第一轮脚本
只打 min/max/mean 时的数，重跑让命令把五个样本都打出来后正文改成了样本可复算的那一组
（理由与第 4 条同）。「一个提交」因此变成两个，拆法是按文件走的 per-file `git add`。
本轮只动接线的两个组件；`utils/diskUsage.ts`
与它的 T2、`api/datafiles.ts`、`ConsistencyCheckDialog.vue` 一行未动 —— 前两件是 Task 6
的已定契约，对话框那半 `usage` 绑定仍是 Task 9 的活（上一节第 2 条那条「根节点没有
`inheritAttrs: false`」的理由本轮复核仍然成立，复审也接受「故意留给 Task 9」）。
本轮现跑（不引用上一节的数）：`npx vue-tsc -b --force --pretty false` ⇒ exit 0、日志 0 字节；
`npx vitest run` ⇒ `Test Files 69 passed` / `Tests 967 passed`，**与派发前基线逐位相同**
（本轮刻意不加 T2 用例，理由见第 6 条）；`npx vitest run test/unit/lineLimit.spec.ts` ⇒ `15 passed`。
件数用 `wc -l frontend/src/pages/data/components/FileList*.vue` 现取：**465 / 191**
（派发前 392 / 173，本轮各加 73 / 18 行，距 600 闸还有 135 / 409 行）。

1. **Important ①：`loadUsage()` 从 `onMounted` 挪到 `onActivated`，只留一处、`fresh=false`。**
   缺陷的真实代价不是「少一次刷新」而是**旗舰场景整个会话不生效**：用户从资源管理器把文件
   拷进数据目录后，keep-alive 下 `onMounted` 一个会话只跑一次，chip 的数除非他恰好上传/删除
   什么，否则永远不会变。`storage_usage.py` 头部那句「≤ TTL（30s）」是**后端内部**的界
   （`get_user_usage` 的桶寿命），端到端不成立 —— 端到端把它钉回 ≤30s 的唯一入口就是
   「导航回来重拉」，写操作那条 watch 只覆盖「他自己在应用里做的写」。
   **翻倍算术（为什么是 activated 而不是 mounted + activated 两处）**：`MainLayout.vue:12` 的
   `<keep-alive :max="10">` 没有 include/exclude ⇒ 本组件作为 `DataManagement` 的子孙一起被缓存，
   首次进入 mounted 与 activated **同帧都触发**，两处各调一次就是首航 2 条 `/files/usage/`
   （这正是 `DataManagement.vue` 里 `onActivated(loadFiles)` 上方那段注释记录的生产形状：
   每条导航 ×2）；之后的 `/data → /仪表板 → /data` 只有 activated 会再跑（mounted 不重跑，
   实例被缓存）⇒ 修好后是每次导航 **1** 条。本轮把 0 变成 1，代价是一条**命中后端 30s 分桶缓存**
   的 GET（服务端只做一次 dict 命中，客户端往返本机现量 1.7–20.8 ms，见第 4 条），
   换来的是这个读数不再是会话级快照。代码里那段注释按**上一节第 6 条**那条教训写
   （认符号与判据名，别认行号），并明写「别把它挪回 onMounted」。
   同仓先例两条，都已在生产里数过：`DataManagement.vue` 的 `onActivated(loadFiles)`，
   和**子组件**用 activated 的 `dashboard/components/BatchYieldTab.vue`（本组件要的就是这一形）。
   **留着的理由与代价（不是遗漏）**：同文件另外四个 loader 仍只挂 `onMounted` —— 改它们的
   生命周期等于每次导航多 4 条请求，需要它自己的计数判据，不属这一批。代价现在**可见**了：
   拷完文件回本页，chip 的数会动而表格不会 ⇒「chip 比列表新」是本轮引入的新不一致，
   值得单独开一批（连同 `DataManagement.vue` 那份 `page_size=9999` 全量列表一起判）。

2. **Important ②：`catch { usage.value = null }` 改成失败时不写 `usage`。** 三条各自独立的理由
   （都写进代码注释了，因为这一处与本文件另外四个 loader 的裸 catch 相反，
   下一个人会为了「一致」把它改回来）：
   ① 拦截器已经为这条失败弹过 toast 并 `console.error`（`api/index.ts` 的
   `NO_TOAST_ENDPOINTS = ['/auth/login/', '/auth/refresh/', '/auth/logout/']` 不含
   `/files/usage/`，`getFileUsage` 也没带 `silent`）⇒ 再拿走 chip 是同一个故障发两条互相
   矛盾的信号：一句「服务器错误」＋一次工具栏重排把数拿走。
   ② 瞬时故障会被放大成长期故障：报错那一刻用户正看着这块面板，而本页没有重试路径，
   下一个能重新拉到数的时机是写操作或离开再回来。
   ③ `apps/datafiles/storage_usage.py` 对 `''` / `.` / `..` 直接 raise `ValueError`，
   而它自己的注释就写了 Django 的 `UnicodeUsernameValidator` **接受** `..` 当用户名
   ⇒ 这种账号每一次请求都是 500，置空等于这个 chip 永久消失。
   没加重试、没加第二套 UI 状态、没加错误横幅 —— 陈旧窗口由载荷里的 `scanned_at` 披露。

3. **Minor ③：序号守卫。** `let usageSeq = 0` / `const my = ++usageSeq` / 成功与失败都只在
   `my === usageSeq` 时才允许生效，形状照 `composables/useAsyncData.ts` 的 seq（那边
   「过期响应不写 data」有 T2 钉着）。**不用**在途标志：它会把**最后一次**写操作的刷新丢掉，
   而那恰恰是唯一要紧的一次；也不做前端单飞。后端 `KeyedLRU` 的单飞只在两次到达重叠同一次
   计算时合并，两次 `fresh=1` 隔几秒就是两份不同载荷，所以这一层必须自己判。
   已知且刻意不处理的相互作用：写操作后**立刻**离开再回来时，activated 那条（后发、非 fresh）
   会在守卫里赢过那条 fresh ⇒ 可能显示一个 ≤30s 桶里的旧值。窗口很窄（800 ms 的 trailing 与
   一次导航撞在一起），且 `scanned_at` 会把这个旧如实说出来 ⇒ 记在这里，不动实现。

4. **Minor ④：连发合并。** `useCoalescedCall((fresh: boolean) => loadUsage(fresh), 800)`，
   watch 里改成 `reloadUsage(true)`，activated 那条仍然直连 `loadUsage()`。
   突发的真实性本轮在**shipped 引擎**里复核过：`FileUploadArea.vue` 的 input 有 `multiple`、
   `emit('upload-success')` 在 `httpRequest` 的成功分支里（每个文件一次），而
   `element-plus/es/components/upload/src/upload-content.vue_vue_type_script_setup_true_lang.mjs`
   （认字符串 `if (autoUpload) upload(rawFile)`，别认行号）里是
   `for (const file of files) { … }` —— `upload` 是 async 且
   **循环里不 await** ⇒ K 个 POST 同帧发出、响应各落各的 tick ⇒ K 次 watch 重入。
   **每操作扫描数的界（改前 → 改后）**：本机现量 `get_user_usage(user, fresh=True)` 五连跑，
   命令把五个样本都打出来（`manage.py shell -c "exec(open('…tmp.py').read())"`，脚本用完即删）：
   `admin: samples_ms=[6.2, 3.29, 3.66, 3.21, 3.23]` ⇒ 最小 3.21 / 最大 6.20 / 均值 3.92 ms，
   树是 admin 的 112 个文件；`user`/`viewer` 两棵空树 0.19–0.25 ms；dev 档用户实测三个
   （`users= ['admin', 'user', 'viewer']`）。同一脚本早一轮跑过 3.45–6.61（均值 4.22），
   两次同分布，**正文取第二轮**因为它的五个样本是命令打出来的、可复算。
   改前：K 个文件 ⇒ K 条 `fresh=1` ⇒ K 次全盘扫描（50 个文件 ≈ 50 × 3.92 ≈ **196 ms** 后端 CPU）。
   改后：**同一 burst ≤ 2 次**（leading 1 + trailing 1 ≈ 7.8 ms），且界是**单侧**的 ——
   若相邻两次 emit 间隔超过窗口，窗口关掉重新武装，退化成每 emit 一次 leading，
   最坏就是改前的 K，所以这个改动只会更少、不会更多。
   窗口 800 ms 的选取（写在常量注释里，三条）：下界对着「两次 emit 的间隔 = 一次上传往返」，
   本机一个走完整 Django 中间件的 GET 往返现量 1.7–20.8 ms
   （`curl -s -o /dev/null -w %{time_total}` ×5 = 0.015373 / 0.002448 / 0.020797 / 0.001734 / 0.003120 s，
   未鉴权、是下界），800 ≈ 最慢那次的 38 倍；上界对着「用户还把这一下当成刚才那次操作的回应」，
   而 leading 已经把**单个**写操作（最常见路径）的感知延迟压到 0，付 800 ms 的只有真连发；
   与后端 TTL 的关系是 30s 的 2.7%，且 trailing 带 `fresh=1` 本来就绕缓存 ⇒ 不会把结果推到换桶边缘。
   **没抄 analysis 那四处 150 ms**（`useHistogram/useBoxPlot/useQQPlot/useSerialDistribution`）：
   那四处的触发器是人手连点，间隔就是点击间隔；这里的触发器是服务端响应。

5. **Minor ⑤⑥⑦**：⑤ `usageChipText(usage)` 从模板内联补齐成第四个 computed
   （`FileListToolbar.vue` 的四个派生串现在同形；性能本来只是微秒级，改它的理由是一致）。
   ⑥ `:key` 由裸 `row.label` 改成 `` `${row.label}:${index}` `` —— 选**复合键**而不是裸 index：
   两者的 diff 行为对「无状态、整批替换」的行完全等价，而 label 留着在 devtools 里能读出这行是谁。
   撞键路径确认不可达于现网（本机 dev 树第一段目录名只有 `single`/`batch`），但坏法对读数面板
   不可接受：重复 key 时 keyed diff 只保留最后一个 index，下一次 `usage` 更新可能把**另一个桶**的
   字节数 patch 到这个 label 下面，而 dev 只 warn 一声。下面三行静态 `el-descriptions-item`
   （数据目录 / 目录外记录 / 统计时间）**不需要同样处理**：它们不在 v-for 里，而「数据目录」那行的
   `v-if="!usageRows.length"` 与 v-for 互斥、永不同帧共存。⑦ `popper-class="disk-usage-popover"`
   保留不动 —— 现在 `grep -rn disk-usage-popover frontend/src frontend/e2e frontend/test`
   只有**定义处那一行**命中（CSS 选择器与定位符都是零），它的用处在**下一个任务**：
   Task 8 Step 1 的 `.el-popper.disk-usage-popover` 定位钩子；没加 CSS。

6. **七条里哪些今天有测试、哪些只有 Task 8 能证明。**
   先说为什么**没写新 T2**：`vitest.config.ts:3-6` 的 T2 层是 `environment: 'node'`、
   零 DOM，`@vue/test-utils` 不在依赖里，`test/unit` 全仓没有一件 mount 组件
   （`grep -rln "mount(" test/unit` 零命中）⇒ 本轮改的四处行为（activated 才拉、失败保留、
   burst 合并、`:key` 形状）都在组件里，vitest 看不见。**helper 层早就有钉，本轮没写装饰性用例**：
   ④ 的 leading+trailing 由 `test/unit/asyncDataAbortCoalesce.spec.ts` 那六例钉死，
   再写一件只会复述它；③ 的守卫**形状**由同文件「过期那趟晚到的成功响应不覆盖 data」钉死，
   但那一例测的是 `useAsyncData.run`，**不是** `loadUsage` 里这份手写复制品 —— 这份复制品
   本身今天无判据（见下面 ③ 那条）。
   为新写的 composable 层用例付费的理由不存在，因为**本轮没有新 composable**。
   ⇒ 下面这些**今天没有任何自动化测试证明**，Task 8 必须自己断到：
   - **①：跨导航计数。** 进 `/data` ⇒ `/files/usage/` 恰好 **1** 条（这条同时钉住
     「activated 真的触发」和「没有 mounted+activated 双发」）；
     `/data → 仪表板 → /data` ⇒ 累计 **2** 条（不是 1 —— 1 意味着 activated 没跑；
     不是 3 —— 3 意味着有人把 mounted 加回去了）。计数器必须装在 `goto` **之前**（lessons R2④）。
   - **②：失败保留上次好值。** 先让 usage 成功、chip 可见，再把 `USAGE_ROUTE` 翻成 500，
     离开再回来 ⇒ 断言 chip **仍然可见且是旧那个数**、`.el-message--error` 恰好 **1** 条。
     现有 Task 8 第二条（500 ⇒ chip 不出现）**测不到这一处**：它拦的是首屏第一次，
     `usage` 从来没被写过 ⇒ 照旧成立，但改坏 ② 也照样绿。两件事都需要各自的用例。
   - **④：一次 burst ⇒ 2 条。** 多文件上传后断 `/files/usage/` 的请求数 `=== 2` 且两条都带
     `fresh=1`，并断 chip 最终等于端点当时的 fresh 值。只断「chip 变了」抓不到回归 ——
     去掉合并器它也变。
   - **③：反序落地。** 可用 `page.route` 让第一次请求晚到、第二次早到（两份不同 payload），
     断 chip 是**后发**那份。做不到的话就承认它只有代码评审在管，别写一条抓不住的假用例。
   - **⑤⑥**：渲染层，且 ⑥ 的撞键要造一个叫「单文件」的一级目录才可达；建议不进 Task 8
     （造它要动别的用户的数据根目录），由代码评审看注释。

7. **门禁侧的三条连带结论（读断言得出的，没开浏览器池）。**
   ① `e2e/data/data.spec.ts`「进数据管理页只发一次全量文件列表」的谓词是
   `/\/files\/\?page_size=9999(&|$)/` ⇒ `/api/v1/files/usage/` 既没有 `page_size=9999`
   也不同形，**不受本轮影响**；同文件第二条 `page.route` 也只 abort 那一个谓词，
   它的「恰好 1 条 error toast」计数因此不会被本轮多出来的 usage 请求顶高。
   ② **但 `e2e/global/error-handling.spec.ts` 里那两处 `page.route('**/api/v1/files/**')`
   确实覆盖 `/files/usage/`**（现取：`grep -n "api/v1/files" frontend/e2e/global/error-handling.spec.ts`）
   —— 那两条把整个 files 前缀 fulfill 成 500/400，进 `/data` 时
   现在多一条 usage 请求也一起进这道闸。不炸的理由是实测过的机制而不是运气：
   `src/api/index.ts` 的 `toastError`（现取：`grep -n "function toastError" src/api/index.ts`）
   对**同一条文案** 2 s 内只响一次，
   且那两条断言是 `.filter({ hasText }).toBeVisible()`（不是计数）⇒ 本轮不新增可见失败模式；
   如果哪天有人给 usage 加了页面自己的第二声，这条会先红。
   ③ **Task 8 Step 3 的排查表第 1 条已经过期**（它写「captured 是 null ⇒ `loadUsage()` 没进
   `onMounted`」）：现在是 `onActivated`。它在上面、本轮不改上面，**Task 8 落地时按本条订正**，
   否则下一个人在错误的方向上找这个 bug。

8. **本轮唯一没能验的一件事**：「activated 对这个**子孙组件**真的每次进入都触发一次」这件事，
   我只有两处间接证据 —— 本仓两处生产实测的同族约定（`DataManagement.vue` 的注释与
   `BatchYieldTab.vue` 的用法）和 shipped 的 Vue 语义 —— **没有浏览器现量**（批内纪律：
   不开池、不起新 dev server，8000/3000 上是别人已在跑的这份代码，PID 未动）。
   所以第 6 条那条计数断言不是「补个覆盖」，它是这一条**第一次被证明**的地方；
   如果它红在 0 条（activated 对这个子孙组件不触发），结论就是这条约定在这一形下不成立，
   得换一个入口（`onMounted` 加一次性闸门会重新引入「会话级快照」，所以正确方向是路由级
   监听或把取数上提到 `DataManagement`），并且这一条要重新记为**未解决**，别当已修。
   顺带一条同源的小未验：窗口 800 ms 的真实判据是「一次上传往返」，我量的是**无鉴权 GET**
   的往返（1.7–20.8 ms）当下界，没真跑过 K 文件上传去量相邻两次 emit 的间隔。


### 文案回退（用户拍板：chip 只留体积）

用户决定：占用 chip 只显体积，文件数留在浮层分桶行（`usageBreakdownRows` 的
`countText`，逐桶 `sizeText · countText` 本来就在渲染）。组件零改动 —— toolbar 经
computed 调 `usageChipText`，分工收在 utils；落地 `ae0d9d4`（2 文件 / +23 −11）。

**理由（两个口径 + 一个现症）**：工具栏同款式并排两颗「N 个文件」，左边是筛选后当页
口径、右边是整树口径，无任何线索区分；且 Task 7 的激活刷新修复之后，用户从资源管理器
拷文件进数据目录，chip 随 `onActivated` 变、表格 `loadFiles` 仍只在 `onMounted`，
两数**按设计就会不一致**（用户机现症）。这同时闭合 §4.2 口径纪律里「页面只显一个数」
这一项（Task 6 台账表格里指向的正是这颗 chip）。

**用例改动（`grep -c "  it(" ` 现数 16 → 16）**：chip 档 4→3（删「文案形态：磁盘占用
X · N 个文件」「空目录也出一句完整的话…」「千位分隔走 toLocaleString…」，新增
「chip 只有体积，不带文件数…」（含 `not.toMatch(/个文件/)` 反向守卫）与「空目录也只说
体积…」）；rows 档 4→5（千位分隔判据从 chip 迁来「分桶行的文件数带千位分隔…」）。
TDD 先红现量：`2 failed | 14 passed`，两条 diff 都是「旧文案仍带计数」
（`expected '磁盘占用 1.20 GB · 3,412 个文件' to be '磁盘占用 1.20 GB'` 与 0 B 同形）。
现数（改后）：本文件 `16 passed`、全量 `69 files / 967 passed`（净零，与基线逐数相同）、
`vue-tsc -b --force` exit 0、`lineLimit` `15 passed`；`diskUsage.ts` 113→122 行、
spec 180→183 行（均闸内）。`grep -rn 磁盘占用 frontend/test` 复核：旧 chip 形态串只存在于
被删的三条里，仓内其余（e2e 等）零命中，无别处需要跟着改。

**变异表（`tasks/mutate_b2_task6c.py`，基线先绿断言，两路对账，全部杀掉、零存活）**：

| 变异 | 实测杀手 | 备注 |
|---|---|---|
| W1 计数加回 chip 旧全形 | 「chip 只有体积」+「空目录」两条红 | ⚠ **finding：死的是前置的 `toBe` 精确断言，不是 `not.toMatch(/个文件/)`** —— vitest 首条失败即抛，`toBe` 钉全串时反向守卫在任何字符串变异下都不可能先红；它的实际作用是防后人把 `toBe` 放松成形匹配，不是现役杀手。反向守卫仍在（不删），但别把它记成「已见红」 |
| W2 丢「磁盘占用 」前缀 | chip 两条（`expected '1.20 GB' to be '磁盘占用 1.20 GB'`） | 杀掉 |
| W3 `count.toLocaleString()`→`String()` | 仅新迁的千位分隔条红 1 | 小计数下 `String(3)===3.toLocaleString()` 等价，只有 7 位数夹具能杀 —— 判据迁到 rows 后这条才有活干 |
| W4 rows `sizeText` 硬编码 `''` | 已知键映射 + 根目录散文件 | 杀掉（新千位分隔条不读 sizeText，不红，符合其断言面） |
| W5 chip 无前缀且删 usage 空值守卫 | 没拿到数据（TypeError）+ chip 两条，红 3 | 杀掉，null 分支有牙 |
| N1/N2b/N3/N4（逐字沿用 fix 轮锚点） | 各 1/1/1/4 红 | 全杀；N4 现红 4 条（比台账旧记的 3 条多出的正是迁入 rows 的千位分隔条——它同样依赖 `entries(by_type)`）|
| M1–M9（同锚点） | 逐条同 fix 轮 | 9/9 全杀；M3 期望名随文案回退迁移（`文案形态`→`chip 只有体积`），GB 两位小数现由 chip 精确串守；M4/M6 各多杀 1 条属预期面 |
| M2i（`isFinite`→同极性 `isNaN`，即 ±Infinity 对） | 「非有限值」红 1 | 杀掉，与 fix 轮实测同形 |

还原独立复核（不信脚本自述）：`git hash-object` == `git rev-parse HEAD:` 逐字节一致，
`diskUsage.ts` `1be2a5ab6fcd748e440cb423c3bdf689a1114181`、spec
`6232afbd157966d9e3e415e580919f5aee4c25ca`；脚本自报 `final-restored-byte-identical: True`。

**本批一直没做到的一件事（这条必须说明白）**：触发本次文案回退的根因不是文案，而是
Task 7 的一个**行为**修复（chip 改按激活刷新）——它的用户可见后果（与只在 onMounted
拉数的表格两数打架）**没有任何人在评审时预言到**，是复审之后才暴露的。⇒ 文案决策与
刷新生命周期决策是**耦合的**：下一个批动任何「谁在何时刷新」的行为时，必须同时把
依赖同一数据的**文案口径**过一遍（两个并排的同名数、缓存新鲜度声明都在检查面里），
一起看，不能分两拨各自评审。
