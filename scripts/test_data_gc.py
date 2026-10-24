"""测试落盘面回收：把 e2e / 后端套件攒下的合成数据收回去，默认只报告不删。

三棵数据根（2026-10-24 实测，同一轮 dry-run：``C:\\lqdp-e2e\\slots`` 185 轮、表观
25.4GB 而**按 inode 去重只有 4.8GB**（``du -sh`` 报 5.0G，对得上）；
``test/e2e-data/media`` 712MB；``test/unit-data`` 此刻 0MB）：

  - ``<E2E base>/slots/<RUN_ID>/``  池每轮自己的目录。正常退出时 ``e2e_pool.mjs:105,373,483``
    会 ``rmSync`` 掉自己造的那份，**留下来的全是崩池/被杀会话的孤儿**（证据日志也住在里面，
    所以删旧轮等于丢掉当期取证 —— 台账早就定过：入库文档只准引复跑命令，不许引槽号）。
  - ``test/e2e-data/``  串行档 e2e 的库 / media / temp。
  - ``test/unit-data/`` 后端套件（``config.settings.unit``）的 media / temp。

体积分三个口径，故意不合成一个数：``e2e_pool.mjs:113`` 用**硬链接**把夹具喂进每个 slot
（注释原话「硬链：不占磁盘」），实测同一 inode 最多被 34 轮共享 —— 表观加总会把
4.8GB 念成 25.4GB。``--list`` 给表观（找大头够用），合计只报「唯一」和「删完即掉」，
后者还扣掉了仍被幸存轮引用的部分，所以它才是能落地的收益。

三条护栏，缺一不可：

  1. **白名单**：只认这三棵树，且候选路径 ``resolve()`` 后必须是树的**真子路径**
     （``..``、联接、拼错的路径都算违规；树自己不算，否则等于把根端了）。
  2. **真实数据目录是禁区**：候选若落在用户主目录那份数据根（``~/LQ-DataPrase``）或
     ``system_config.json`` 指认的 ``data_dir`` 里，整棵树拒绝执行 ——
     不是跳过那一条，因为一次跳过就等于承认「有时候会删到真实数据」。
  3. **默认 dry-run**：``--apply`` 才动刀；``--older-than-days`` 兼作在跑守卫，
     正在跑的那一轮 mtime 一定是新的，因此不会被选中（设成 0 直接拒绝启动）。

跑法：
    python scripts/test_data_gc.py                      # 报告
    python scripts/test_data_gc.py --older-than-days 3 --apply
    python scripts/test_data_gc.py --only slots --json  # 给别的脚本读
"""
import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SLOT_DIR_NAME_MAX = 40          # RUN_ID 形态：HHMMSS-pid（可带 -recheckN 后缀）

# 数据根之外绝不触碰的名字（删了会让下一轮重新播种，但也可能撞别人正在跑的会话）
_ROOT_KEEP = {'template'}


@dataclass(frozen=True)
class DataRoot:
    """一棵可回收的数据树。``pattern`` 决定它下面「按什么单位」挑选待删项。"""
    name: str
    path: Path
    pattern: str          # 'run_dir' = 直接子目录（一轮一个）；'children' = 直接子项


@dataclass
class Plan:
    """一次回收的结论：待删项 + 被拒绝的东西。dry-run 与 --apply 共用同一份计划。"""
    root: str
    candidates: list = field(default_factory=list)     # [(Path, 表观字节, mtime)]
    skipped_newer: int = 0
    refused_outside: list = field(default_factory=list)
    refused_protected: list = field(default_factory=list)
    unreadable: list = field(default_factory=list)
    unique_bytes: int = 0               # 待删树里按 inode 去重后的字节
    freeable_bytes: int = 0             # 其中不与幸存树共享的部分
    shared_with_survivors: int = 0      # 删了也不掉空间的那部分
    multi_run_inodes: int = 0           # 跨多个待删目录共享的 inode 数

    @property
    def apparent_bytes(self) -> int:
        """表观合计 —— 会因硬链接重复计数，只用来找大头。"""
        return sum(b for _, b, _ in self.candidates)


def e2e_base(repo_root: Path = REPO_ROOT) -> Path:
    """槽池的落盘根，与 ``scripts/e2e_pool.mjs:36`` 的 `LQDP_E2E_ROOT || 'C:\\lqdp-e2e'` 同源。"""
    raw = os.environ.get('LQDP_E2E_ROOT', '').strip()
    if raw:
        return Path(raw).resolve()
    if os.name == 'nt':
        return Path('C:/lqdp-e2e').resolve()
    # 非 Windows 上池本身跑不了（它写 .bat 与 C: 盘路径），但仍要能给个不碰真实数据的默认值
    return Path(os.sep) / 'tmp' / 'lqdp-e2e'


def data_roots(repo_root: Path = REPO_ROOT) -> list:
    slots = e2e_base(repo_root) / 'slots'
    return [
        DataRoot('slots', slots, 'run_dir'),
        DataRoot('e2e-data', repo_root / 'test' / 'e2e-data', 'children'),
        DataRoot('unit-data', repo_root / 'test' / 'unit-data', 'children'),
    ]


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


def is_run_dir_name(name: str) -> bool:
    """``HHMMSS-pid``（可带 ``-recheckN``）才算池的一轮；别的名字一律不碰。"""
    if len(name) > SLOT_DIR_NAME_MAX or name in _ROOT_KEEP or name.startswith('.'):
        return False
    head, sep, tail = name.partition('-')
    if not sep or not tail:
        return False
    return head.isdigit() and len(head) == 6 and tail.split('-')[0].isdigit()


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


def walk_inodes(path: Path, unreadable: list):
    """产出该树里的 ``(dev, ino, size)``，跳过符号链接与目录联接。

    必须按 inode 记账而不是按 ``st_size`` 累加：``e2e_pool.mjs:113`` 用**硬链接**把夹具
    喂进每个 slot（注释原话「硬链：不占磁盘」）。2026-10-24 实测 7,032 个文件里
    2,958 个 ``st_nlink > 1``、同一 inode 最多被 15 轮共享 —— 按表观字节加总会把
    5.0GB 的账面报成 25.4GB（差 5 倍），工具就从「帮你省盘」变成「骗你说省了」。
    """
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


def build_plan(root: DataRoot, now: float, older_than_days: float,
               protected: list) -> Plan:
    """挑待删项。纯判定（名字/年龄/路径合法性），不删、不建。

    体积分三个口径，故意不合成一个数：
      - ``unique_bytes``   = 待删树里去重后的 inode 总字节（真正“占着”的量）
      - ``freeable_bytes`` = 其中不与「本轮要留下的树」共享的那部分，即删完立刻掉的空间
      - 表观字节只在 ``--list`` 里出现，用来找大头
    """
    plan = Plan(root=root.name)
    if not root.path.is_dir():
        return plan
    guard = now - older_than_days * 86400
    root_ok = not is_protected(root.path, protected)
    if root.path.is_symlink():
        plan.refused_outside.append(f'{root.path} （数据根本身是联接，拒绝整棵树）')
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
    cand_sizes, cand_where = inode_sets([str(p) for p, _s, _m in plan.candidates],
                                        plan.unreadable)
    _surv_sizes, surv_inodes = inode_sets(survivors, plan.unreadable)
    plan.unique_bytes = sum(cand_sizes.values())
    plan.freeable_bytes = sum(size for ino, size in cand_sizes.items()
                              if ino not in surv_inodes)
    plan.shared_with_survivors = sum(size for ino, size in cand_sizes.items()
                                     if ino in surv_inodes)
    plan.multi_run_inodes = sum(1 for inos in cand_where.values() if len(inos) > 1)
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
        'candidates': len(plan.candidates),
        'apparentBytes': plan.apparent_bytes,
        'uniqueBytes': plan.unique_bytes,
        'freeableBytes': plan.freeable_bytes,
        'sharedWithSurvivors': plan.shared_with_survivors,
        'multiRunInodes': plan.multi_run_inodes,
        'skippedNewer': plan.skipped_newer,
        'refusedProtected': len(plan.refused_protected),
        'refusedOutside': len(plan.refused_outside),
        'unreadable': plan.unreadable[:5],
    } for plan in plans]
    blocked = sum(r['refusedProtected'] + r['refusedOutside'] for r in rows)
    if as_json:
        print(json.dumps({'apply': apply, 'deleted': deleted, 'failed': failed,
                          'refused': blocked, 'roots': rows}, ensure_ascii=False))
        return
    mb = 1024 * 1024
    print(f'{"树":<10} {"待删":>5} {"表观":>9} {"唯一":>9} {"删完即掉":>9} '
          f'{"太新跳过":>7}  保护面 越界 读失败')
    for r in rows:
        print(f'{r["root"]:<10} {r["candidates"]:>5} {r["apparentBytes"] / mb:>8.1f}M '
              f'{r["uniqueBytes"] / mb:>8.1f}M {r["freeableBytes"] / mb:>8.1f}M '
              f'{r["skippedNewer"]:>7}  {r["refusedProtected"]:>5} {r["refusedOutside"]:>4} '
              f'{len(r["unreadable"]):>6}')
    freeable = sum(r['freeableBytes'] for r in rows)
    apparent = sum(r['apparentBytes'] for r in rows)
    print(f'合计「删完即掉」{freeable / mb:.1f}MB（表观 {apparent / mb:.1f}MB 里含硬链接'
          f'重复计数，别当收益）· '
          + (f'已删 {deleted} 项' if apply else 'dry-run，一个文件都没删（要动刀加 --apply）'))
    if blocked:
        print(f'注意：{blocked} 项被护栏拒绝 —— 数据根落进了真实数据目录，先查 '
              f'--only 与 LQDP_E2E_ROOT，别改护栏')
    if failed:
        print(f'注意：{failed} 项删失败（多半是别的会话还在用这些槽）')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='测试落盘面回收（默认 dry-run）')
    ap.add_argument('--apply', action='store_true', help='真的删；不写就是报告')
    ap.add_argument('--older-than-days', type=float, default=1.0,
                    help='只回收早于该天数的项（兼作在跑守卫），默认 1')
    ap.add_argument('--only', default='', help='逗号分隔的树名：slots,e2e-data,unit-data')
    ap.add_argument('--json', action='store_true', help='机器可读输出')
    ap.add_argument('--list', action='store_true', help='逐条列出待删项')
    args = ap.parse_args(argv)

    all_roots = data_roots()
    known = {r.name for r in all_roots}
    wanted = {w.strip() for w in args.only.split(',') if w.strip()}
    unknown = sorted(wanted - known)
    if unknown:
        print(f'[!] --only 里有不认识的树名：{unknown} —— 可用的是 {sorted(known)}',
              file=sys.stderr)
        return 2
    if args.older_than_days <= 0:
        print('[!] --older-than-days 必须 > 0：这条龄限同时是「正在跑的那轮别动」的守卫，'
              '设成 0 等于把它关掉', file=sys.stderr)
        return 2
    roots = [r for r in all_roots if not wanted or r.name in wanted]

    protected = protected_roots()
    now = time.time()
    plans = [build_plan(r, now, args.older_than_days, protected) for r in roots]
    if args.list:
        for plan in plans:
            for path, size, mtime in plan.candidates:
                print(f'{plan.root:<10} 表观{size / 1024 / 1024:>8.1f}MB '
                      f'{time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))}  {path}')
    deleted, failed = execute(plans, args.apply)
    report(plans, args.apply, args.json, deleted, failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
