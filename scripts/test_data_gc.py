"""开发垃圾统一回收器：调试/测试/构建攒下的可再生垃圾一处收，默认只报告不删。

入口（手动触发，无 cron —— 垃圾堆积的根因是「没有触发器」，不是「删得不够狠」）：
    npm run clean          # dry-run 报告，按类别分组给「删完即掉」
    npm run clean:apply    # 真删（等价 --apply）
本文件是**引擎**（护栏 / inode 记账 / build_plan / execute / report / main）；
「回收什么」的注册表与选择器在 ``scripts/gc_categories.py``（600 行硬约束下拆出的 sibling，
加载器需把 ``scripts/`` 加进 sys.path）。对外仍是单一入口。

五类（``DataRoot.category``，报告按它分组、``--only`` 可按名字或类别过滤）：
  - test-data  槽池孤儿轮 ``<E2E base>/slots/<RUN_ID>/``、``test/e2e-data``、``test/unit-data``。
    池正常退出会 ``rmSync`` 本轮（``e2e_pool.mjs:105,373,483``），**留下的全是崩池/被杀会话的孤儿**
    （证据日志也住在里面 ⇒ 入库文档只准引复跑命令、不许引槽号）。
  - artifacts  out/dist/build/frontend-dist/electron-dist：整目录回收，下一轮 build/dist:win 重建。
  - caches     vite/.pytest_cache/.superpowers/playwright-report/test-results + 仓库自有 __pycache__。
  - scratch    tasks 草稿（保 e2e-nightly）、夜跑轮次（保 LATEST.md/最新轮）、根 db 备份、probe.local。
  - electron   **opt-in**（默认不收，``--all`` 或 ``--only electron`` 才进）。它的 userData 同时是
    Django 数据根，故只把白名单 Chromium 缓存子目录逐个注册成 self 根，profile 根永不进候选。

体积三个口径，故意不合成一个数：``e2e_pool.mjs:113`` 用**硬链接**把夹具喂进每个 slot
（同一 inode 实测最多被 34 轮共享）⇒ 表观加总严重虚报。``--list`` 给表观（找大头够用），
合计只报「唯一」和「删完即掉」，后者再扣掉仍被幸存轮引用的部分，才是能落地的收益。
实测尺寸与口径见 ``docs/reference/testing-gates.md`` §1（唯一事实来源，别在此复写会漂的数）。

护栏，缺一不可：
  1. **白名单 + 真子路径**：只认注册表里的树，候选 ``resolve()`` 后必须是树的**真子路径**
     （``..``、联接、拼错都算违规；树自己不算，否则等于把根端了）。
  2. **真实数据目录是禁区**：候选若落在 ``~/LQ-DataPrase`` 或 ``system_config.json`` 的 ``data_dir``，
     **整棵树拒绝执行** —— 不是跳过那一条，一次跳过就等于承认「有时候会删到真实数据」。
  3. **绝不删 git 跟踪文件**：``tracked_files()`` 取 ``git ls-files``，候选含任何被跟踪文件即拒
     （夜跑 LATEST.md 由此与 keep 白名单**双重**保护）。
  4. **默认 dry-run + 在跑守卫**：``--apply`` 才动刀；``--older-than-days`` 必须 > 0，
     正在跑的那一轮 mtime 一定新，因此不会被选中（设 0 直接拒绝启动）。

跑法：
    python scripts/test_data_gc.py                          # 报告（不含 electron）
    python scripts/test_data_gc.py --older-than-days 3 --apply
    python scripts/test_data_gc.py --all                    # 含 electron 缓存（清前先关 Electron）
    python scripts/test_data_gc.py --only caches --json     # 给别的脚本读
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from gc_categories import (
    REPO_ROOT, DataRoot, _ROOT_KEEP,
    is_run_dir_name, find_pycache_dirs,
    data_roots, artifact_roots, cache_roots, scratch_roots,
    electron_profile, electron_roots, collect_roots, select_roots,
)


@dataclass
class Plan:
    """一次回收的结论：待删项 + 被拒绝的东西。dry-run 与 --apply 共用同一份计划。"""
    root: str
    category: str = 'test-data'         # 报告按它分组
    candidates: list = field(default_factory=list)     # [(Path, 表观字节, mtime)]
    skipped_newer: int = 0
    refused_outside: list = field(default_factory=list)
    refused_protected: list = field(default_factory=list)
    refused_tracked: list = field(default_factory=list)   # 含被 git 跟踪的文件，拒绝删
    unreadable: list = field(default_factory=list)
    unique_bytes: int = 0               # 待删树里按 inode 去重后的字节
    freeable_bytes: int = 0             # 其中不与幸存树共享的部分
    shared_with_survivors: int = 0      # 删了也不掉空间的那部分
    multi_run_inodes: int = 0           # 跨多个待删目录共享的 inode 数

    @property
    def apparent_bytes(self) -> int:
        """表观合计 —— 会因硬链接重复计数，只用来找大头。"""
        return sum(b for _, b, _ in self.candidates)


def protected_roots() -> list:
    """真实数据目录：主目录那份 + system_config.json 指认的那份。"""
    out = [(Path.home() / 'LQ-DataPrase').resolve()]
    cfg = Path(os.environ.get('LQDP_SYSTEM_CONFIG_FILE', '')).expanduser() \
        if os.environ.get('LQDP_SYSTEM_CONFIG_FILE', '').strip() else None
    if cfg is not None:
        try:
            data_dir = json.loads(cfg.read_text(encoding='utf-8')).get('data_dir', '')
        except (OSError, ValueError):
            data_dir = ''
        if str(data_dir).strip():
            out.append(Path(str(data_dir)).resolve())
    return out


def inside(root: Path, candidate: Path) -> bool:
    """候选必须是树的**真子路径**（``resolve()`` 后比，不靠字符串前缀）。

    「树自己」算 False：把数据根连锅端不是回收，是误删 —— 下一轮缺的是父目录，
    SQLite 只报一句 ``unable to open database file``，很难归因回这条脚本。
    """
    try:
        rel = candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return str(rel) not in ('', '.')


def is_protected(candidate: Path, protected: list) -> bool:
    """候选是否落在某个真实数据目录里（含「候选就是禁区本身」）。"""
    target = candidate.resolve()
    for guard in protected:
        if target == guard or guard in target.parents:
            return True
    return False


def has_tracked(candidate: Path, tracked) -> bool:
    """候选自己或其后代里是否有被 git 跟踪的文件 —— 删了会丢入库内容，一律拒绝。

    ``tracked`` 是 resolve 后的绝对路径集合。用「候选 + 分隔符」做前缀比，避免
    ``out`` 误命中 ``output``；两侧都 resolve 过，Windows 大小写也一致。
    """
    target = candidate.resolve()
    prefix = str(target) + os.sep
    return any(t == target or str(t).startswith(prefix) for t in tracked)


def tracked_files(repo_root: Path = REPO_ROOT) -> frozenset:
    """git 跟踪的文件（resolve 后的绝对路径）。``git ls-files`` 只读，不碰工作树。

    git 不可用 / 不是仓库时返回空集 —— 这一层是纵深防御，白名单与禁区护栏仍在；
    注册表里的根全是 gitignored 目录，正常不会命中跟踪文件。
    """
    try:
        out = subprocess.run(['git', '-C', str(repo_root), 'ls-files', '-z'],
                             capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return frozenset()
    names = out.stdout.decode('utf-8', 'replace').split('\0')
    return frozenset((repo_root / n).resolve() for n in names if n)


def walk_inodes(path: Path, unreadable: list):
    """产出该树里的 ``(dev, ino, size)``，跳过符号链接与目录联接。

    必须按 inode 记账而不是按 ``st_size`` 累加：``e2e_pool.mjs:113`` 用**硬链接**把夹具
    喂进每个 slot（注释原话「硬链：不占磁盘」）。2026-10-24 实测 7,032 个文件里
    2,958 个 ``st_nlink > 1``、同一 inode 最多被 15 轮共享 —— 按表观字节加总会把
    5.0GB 的账面报成 25.4GB（差 5 倍），工具就从「帮你省盘」变成「骗你说省了」。
    """
    if path.is_file():
        # glob 会把散文件（db.sqlite3.bak*）选成候选；对文件直接 lstat，别去 scandir。
        try:
            st = os.lstat(path)
            yield str(path), (st.st_dev, st.st_ino), st.st_size
        except OSError as exc:
            unreadable.append(f'{path}: {type(exc).__name__}')
        return
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            # 这里必须用 os.lstat：os.DirEntry.stat() 在 Windows 上
                            # 不填 st_dev/st_ino（实测一律 0），拿它去重的话整棵树会压成
                            # 「1 个 inode」，5.0GB 直接报成 0.07MB。st_size 反而是对的，
                            # 所以这个 bug 只会污染去重口径、不会被表观字节暴露出来。
                            st = os.lstat(entry.path)
                            yield entry.path, (st.st_dev, st.st_ino), st.st_size
                    except OSError as exc:
                        unreadable.append(f'{entry.path}: {type(exc).__name__}')
        except OSError as exc:
            unreadable.append(f'{cur}: {type(exc).__name__}')
            return


def apparent_size(path: Path, unreadable: list):
    """表观字节与文件数 —— 只给 ``--list`` 排序用，**不进合计**。"""
    total = 0
    count = 0
    for _name, _ino, size in walk_inodes(path, unreadable):
        total += size
        count += 1
    return total, count


def inode_sets(paths: list, unreadable: list):
    """把若干棵树摊成 {inode: 字节} 与 {inode: 出现的树数}。"""
    sizes = {}
    where = {}
    for p in paths:
        for _name, ino, size in walk_inodes(Path(p), unreadable):
            sizes[ino] = size
            where.setdefault(ino, set()).add(str(p))
    return sizes, where


def _account(plan: Plan, survivors=()):
    """inode 记账：unique=候选去重字节；freeable=扣掉仍被幸存树共享的部分（删完即掉）。

    self/pycache 无幸存树（survivors 空）⇒ freeable=unique；children/glob 传入幸存树。
    """
    if not plan.candidates:
        return
    sizes, where = inode_sets([str(p) for p, _s, _m in plan.candidates], plan.unreadable)
    _ss, surv_inodes = inode_sets(list(survivors), plan.unreadable)
    plan.unique_bytes = sum(sizes.values())
    plan.freeable_bytes = sum(s for ino, s in sizes.items() if ino not in surv_inodes)
    plan.shared_with_survivors = sum(s for ino, s in sizes.items() if ino in surv_inodes)
    plan.multi_run_inodes = sum(1 for inos in where.values() if len(inos) > 1)


def build_plan(root: DataRoot, now: float, older_than_days: float,
               protected: list, tracked=frozenset()) -> Plan:
    """挑待删项。纯判定（名字/年龄/路径合法性），不删、不建。

    体积分三个口径，故意不合成一个数：
      - ``unique_bytes``   = 待删树里去重后的 inode 总字节（真正“占着”的量）
      - ``freeable_bytes`` = 其中不与「本轮要留下的树」共享的那部分，即删完立刻掉的空间
      - 表观字节只在 ``--list`` 里出现，用来找大头
    """
    plan = Plan(root=root.name, category=root.category)
    if not root.path.is_dir():
        return plan
    guard = now - older_than_days * 86400
    root_ok = not is_protected(root.path, protected)
    if root.path.is_symlink():
        plan.refused_outside.append(f'{root.path} （数据根本身是联接，拒绝整棵树）')
        return plan
    if root.pattern == 'self':
        # 整目录/文件本身成一个候选（可再生构建产物、缓存、Electron 缓存子目录用）。
        # 不走 inside()：它对「树自己」返回 False，而 self 要的正是这棵树自己。
        p = root.path
        if not root_ok or is_protected(p, protected):
            plan.refused_protected.append(str(p))
            return plan
        if has_tracked(p, tracked):
            plan.refused_tracked.append(str(p))
            return plan
        mtime = p.stat().st_mtime
        if root.age_guard and mtime > guard:
            plan.skipped_newer += 1
            return plan
        apparent, _ = apparent_size(p, plan.unreadable)
        plan.candidates.append((p, apparent, mtime))
        _account(plan)
        return plan
    if root.pattern == 'pycache':
        for p in find_pycache_dirs(root.path):
            if is_protected(p, protected):
                plan.refused_protected.append(str(p))
                continue
            if has_tracked(p, tracked):
                plan.refused_tracked.append(str(p))
                continue
            mtime = p.stat().st_mtime
            apparent, _ = apparent_size(p, plan.unreadable)
            plan.candidates.append((p, apparent, mtime))
        _account(plan)
        return plan
    if root.pattern == 'glob':
        # 按 glob 选子项（含散文件，如 db.sqlite3.bak*）：keep 命名保护 + keep_newest 保最新一轮。
        entries = sorted(root.path.glob(root.glob), key=lambda p: p.name)
        newest = None
        if root.keep_newest:
            dirs = [p for p in entries if p.is_dir()]
            if dirs:
                newest = max(dirs, key=lambda p: p.stat().st_mtime)
        survivors = []
        for p in entries:
            if p.name in root.keep or (newest is not None and p == newest):
                survivors.append(str(p))
                continue
            if not root_ok or is_protected(p, protected):
                plan.refused_protected.append(str(p))
                survivors.append(str(p))
                continue
            if not inside(root.path, p):
                plan.refused_outside.append(str(p))
                survivors.append(str(p))
                continue
            if has_tracked(p, tracked):
                plan.refused_tracked.append(str(p))
                survivors.append(str(p))
                continue
            mtime = p.stat().st_mtime
            if mtime > guard:
                plan.skipped_newer += 1
                survivors.append(str(p))
                continue
            apparent, _ = apparent_size(p, plan.unreadable)
            plan.candidates.append((p, apparent, mtime))
        _account(plan, survivors)
        return plan
    try:
        with os.scandir(root.path) as it:
            children = sorted(it, key=lambda e: e.name)
    except OSError as exc:
        plan.unreadable.append(f'{root.path}: {type(exc).__name__}')
        return plan

    survivors = []
    for entry in children:
        p = Path(entry.path)
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue        # 只按「一棵树」为单位回收，散文件不动
            if root.pattern == 'run_dir' and not is_run_dir_name(entry.name):
                survivors.append(entry.path)     # 不是池的一轮 —— 留着，也参与共享判定
                continue
            if root.pattern == 'children' and entry.name in _ROOT_KEEP:
                survivors.append(entry.path)
                continue
            if not root_ok:
                plan.refused_protected.append(str(p))
                survivors.append(entry.path)
                continue
            if is_protected(p, protected):
                plan.refused_protected.append(str(p))
                survivors.append(entry.path)
                continue
            if not inside(root.path, p):
                plan.refused_outside.append(str(p))
                survivors.append(entry.path)
                continue
            if has_tracked(p, tracked):
                plan.refused_tracked.append(str(p))
                survivors.append(entry.path)
                continue
            mtime = entry.stat(follow_symlinks=False).st_mtime
            if mtime > guard:
                plan.skipped_newer += 1
                survivors.append(entry.path)
                continue
            apparent, _ = apparent_size(p, plan.unreadable)
            plan.candidates.append((p, apparent, mtime))
        except OSError as exc:
            plan.unreadable.append(f'{p}: {type(exc).__name__}')

    if not plan.candidates:
        return plan
    _account(plan, survivors)
    return plan


def execute(plans: list, apply: bool):
    """`--apply` 时真删。返回 (删除条数, 失败条数)。

    不返回「释放了多少字节」：硬链接下的真实收益只有 ``plan.freeable_bytes`` 这一个
    计划级口径，逐条累加会把共享 inode 重复算进去 —— 宁可少报也不假报。
    """
    deleted = 0
    failed = 0
    for plan in plans:
        for path, _apparent, _mtime in list(plan.candidates):
            if not apply:
                continue
            try:
                shutil.rmtree(path)
                deleted += 1
            except OSError as exc:
                failed += 1
                plan.unreadable.append(f'删除失败 {path}: {type(exc).__name__}')
                print(f'[!] 删不掉 {path} —— {type(exc).__name__}: {exc}', file=sys.stderr)
    return deleted, failed


def report(plans: list, apply: bool, as_json: bool, deleted: int, failed: int):
    rows = [{
        'root': plan.root,
        'category': plan.category,
        'candidates': len(plan.candidates),
        'apparentBytes': plan.apparent_bytes,
        'uniqueBytes': plan.unique_bytes,
        'freeableBytes': plan.freeable_bytes,
        'sharedWithSurvivors': plan.shared_with_survivors,
        'multiRunInodes': plan.multi_run_inodes,
        'skippedNewer': plan.skipped_newer,
        'refusedProtected': len(plan.refused_protected),
        'refusedOutside': len(plan.refused_outside),
        'refusedTracked': len(plan.refused_tracked),
        'unreadable': plan.unreadable[:5],
    } for plan in plans]
    blocked = sum(r['refusedProtected'] + r['refusedOutside'] + r['refusedTracked']
                  for r in rows)
    if as_json:
        print(json.dumps({'apply': apply, 'deleted': deleted, 'failed': failed,
                          'refused': blocked, 'roots': rows}, ensure_ascii=False))
        return
    mb = 1024 * 1024
    groups = {}
    for r in rows:
        groups.setdefault(r['category'], []).append(r)
    header = (f'{"树":<26} {"待删":>5} {"表观":>9} {"唯一":>9} {"删完即掉":>9} '
              f'{"太新跳过":>7}  保护面 越界 跟踪 读失败')
    for cat, cat_rows in groups.items():
        print(f'── {cat} ──')
        print(header)
        for r in cat_rows:
            print(f'{r["root"]:<26} {r["candidates"]:>5} {r["apparentBytes"] / mb:>8.1f}M '
                  f'{r["uniqueBytes"] / mb:>8.1f}M {r["freeableBytes"] / mb:>8.1f}M '
                  f'{r["skippedNewer"]:>7}  {r["refusedProtected"]:>5} {r["refusedOutside"]:>4} '
                  f'{r["refusedTracked"]:>4} {len(r["unreadable"]):>6}')
        cat_free = sum(r['freeableBytes'] for r in cat_rows)
        print(f'小计「删完即掉」{cat_free / mb:.1f}MB')
    freeable = sum(r['freeableBytes'] for r in rows)
    apparent = sum(r['apparentBytes'] for r in rows)
    print(f'合计「删完即掉」{freeable / mb:.1f}MB（表观 {apparent / mb:.1f}MB 里含硬链接'
          f'重复计数，别当收益）· '
          + (f'已删 {deleted} 项' if apply else 'dry-run，一个文件都没删（要动刀加 --apply）'))
    if blocked:
        print(f'注意：{blocked} 项被护栏拒绝（保护区/越界/含跟踪文件）—— 先查 '
              f'--only 与 LQDP_E2E_ROOT，别改护栏')
    if failed:
        print(f'注意：{failed} 项删失败（多半是别的会话还在用这些槽）')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='开发垃圾统一回收（默认 dry-run）')
    ap.add_argument('--apply', action='store_true', help='真的删；不写就是报告')
    ap.add_argument('--older-than-days', type=float, default=1.0,
                    help='只回收早于该天数的项（兼作在跑守卫），默认 1')
    ap.add_argument('--only', default='',
                    help='逗号分隔的树名或类别名：test-data/artifacts/caches/scratch/electron')
    ap.add_argument('--all', action='store_true',
                    help='含 electron 缓存（默认不含；清前请先关掉 Electron）')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    ap.add_argument('--list', action='store_true', help='逐条列出待删项')
    args = ap.parse_args(argv)

    all_roots = collect_roots()
    known = {r.name for r in all_roots} | {r.category for r in all_roots}
    wanted = {w.strip() for w in args.only.split(',') if w.strip()}
    unknown = sorted(wanted - known)
    if unknown:
        print(f'[!] --only 里有不认识的树名/类别：{unknown} —— 可用的是 {sorted(known)}',
              file=sys.stderr)
        return 2
    if args.older_than_days <= 0:
        print('[!] --older-than-days 必须 > 0：这条龄限同时是「正在跑的那轮别动」的守卫，'
              '设成 0 等于把它关掉', file=sys.stderr)
        return 2
    roots = select_roots(all_roots, wanted, args.all)

    protected = protected_roots()
    tracked = tracked_files()
    now = time.time()
    plans = [build_plan(r, now, args.older_than_days, protected, tracked) for r in roots]
    if args.list:
        for plan in plans:
            for path, size, mtime in plan.candidates:
                print(f'{plan.root:<26} 表观{size / 1024 / 1024:>8.1f}MB '
                      f'{time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))}  {path}')
    deleted, failed = execute(plans, args.apply)
    report(plans, args.apply, args.json, deleted, failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
