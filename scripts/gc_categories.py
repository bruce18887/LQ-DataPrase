"""回收器的「注册表 + 选择器」层：声明有哪些可回收的树、按什么单位挑、哪些名字永不碰。

与引擎（``scripts/test_data_gc.py``）分开，是为了把 600 行硬约束下的职责切清：
这里只回答「回收什么」（DataRoot 注册表 + 名字/缓存发现选择器），不回答「怎么删」
（护栏、inode 记账、build_plan、execute、report 都在引擎里）。引擎从本模块 import 这些名字，
对外仍是单一入口；测试加载器需把 ``scripts/`` 加进 sys.path 才能解析这层 sibling import。

类别（``DataRoot.category``）：test-data / artifacts / caches / scratch / electron。
electron 是 opt-in（默认不收，``--all`` 或 ``--only electron`` 才进），因为它的 userData
同时是 Django 的数据根，只有白名单缓存子目录可清。
"""
import os
from dataclasses import dataclass
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
    pattern: str          # 'run_dir' = 一轮一个子目录；'children' = 直接子项；'self' = 整目录自己
    category: str = 'test-data'   # 报告分组与 --only 过滤用：test-data/artifacts/caches/scratch/electron
    keep: frozenset = frozenset()   # 子项名白名单：永不删（如 e2e-nightly、LATEST.md）
    keep_newest: bool = False       # 保最新一个子目录（夜跑最新轮，LATEST.md 引用它）
    glob: str = ''                  # 'glob' 模式的匹配串（'*' / 'db.sqlite3.bak*'）
    age_guard: bool = False         # 仅 'self' 用：产物/缓存默认随时可清；probe.local 等设 True


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


def artifact_roots(repo_root: Path = REPO_ROOT) -> list:
    """可再生构建产物：整目录回收，删了下一轮 build / dist:win 重建。全 gitignored。"""
    return [
        DataRoot('out', repo_root / 'out', 'self', category='artifacts'),
        DataRoot('dist', repo_root / 'dist', 'self', category='artifacts'),
        DataRoot('build', repo_root / 'build', 'self', category='artifacts'),
        DataRoot('frontend-dist', repo_root / 'frontend' / 'dist', 'self',
                 category='artifacts'),
        DataRoot('electron-dist', repo_root / 'frontend' / 'electron-dist', 'self',
                 category='artifacts'),
    ]


def cache_roots(repo_root: Path = REPO_ROOT) -> list:
    """可再生缓存：显式目录（self）+ 一个 pycache 发现根。node_modules/.venv 本体不碰。"""
    return [
        DataRoot('vite', repo_root / 'frontend' / 'node_modules' / '.vite', 'self',
                 category='caches'),
        DataRoot('pytest-cache', repo_root / '.pytest_cache', 'self', category='caches'),
        DataRoot('superpowers', repo_root / '.superpowers', 'self', category='caches'),
        DataRoot('playwright-report', repo_root / 'frontend' / 'playwright-report',
                 'self', category='caches'),
        DataRoot('frontend-test-results', repo_root / 'frontend' / 'test-results',
                 'self', category='caches'),
        DataRoot('test-results', repo_root / 'test-results', 'self', category='caches'),
        DataRoot('pycache', repo_root, 'pycache', category='caches'),
    ]


def scratch_roots(repo_root: Path = REPO_ROOT) -> list:
    """任务草稿与临时探针：tasks 草稿（保 e2e-nightly）、夜跑轮次（保 LATEST.md/最新轮）、
    根 db 备份、probe.local。夜跑最新轮被 LATEST.md 引用，keep_newest 保住它不断链。"""
    return [
        DataRoot('tasks', repo_root / 'tasks', 'glob', category='scratch',
                 glob='*', keep=frozenset({'e2e-nightly'})),
        DataRoot('e2e-nightly', repo_root / 'tasks' / 'e2e-nightly', 'glob',
                 category='scratch', glob='*',
                 keep=frozenset({'LATEST.md', 'latest.json'}), keep_newest=True),
        DataRoot('db-backups', repo_root, 'glob', category='scratch',
                 glob='db.sqlite3.bak*'),
        DataRoot('probe-local', repo_root / 'probe.local', 'self', category='scratch',
                 age_guard=True),
    ]


# Chromium 纯可再生缓存。Network（Cookies/传输安全）、Local/Session Storage、blob_storage
# 都是会话状态而非缓存，清了会掉登录态 —— 一律不注册。media/secret.key 是真实数据，更不碰。
ELECTRON_CACHE_DIRS = ('Cache', 'Code Cache', 'GPUCache', 'DawnGraphiteCache',
                       'DawnWebGPUCache', 'ShaderCache')


def electron_profile() -> Path:
    """Electron userData。dev 档是小写 ``lq-dataprase``；Windows 大小写不敏感，
    与打包档 ``LQ-DataPrase`` 实为同一目录（实测 os.path.samefile=True）。"""
    appdata = os.environ.get('APPDATA', '').strip()
    base = Path(appdata) if appdata else Path.home() / 'AppData' / 'Roaming'
    return (base / 'lq-dataprase').resolve()


def electron_roots(profile: Path = None) -> list:
    """只把白名单缓存子目录逐个注册成 self 根 —— profile 根本身永不进候选，
    因为它是 Django 的 LQDP_BASE_DIR，media/secret.key 都住在里面。opt-in（--all/--only electron）。"""
    profile = electron_profile() if profile is None else profile
    return [DataRoot('electron-' + name.lower().replace(' ', '-'), profile / name,
                     'self', category='electron')
            for name in ELECTRON_CACHE_DIRS]


def is_run_dir_name(name: str) -> bool:
    """``HHMMSS-pid``（可带 ``-recheckN``）才算池的一轮；别的名字一律不碰。"""
    if len(name) > SLOT_DIR_NAME_MAX or name in _ROOT_KEEP or name.startswith('.'):
        return False
    head, sep, tail = name.partition('-')
    if not sep or not tail:
        return False
    return head.isdigit() and len(head) == 6 and tail.split('-')[0].isdigit()


_PYCACHE_SKIP = {'node_modules', '.venv', '.venv-wsl', 'venv', 'env', '.worktrees', '.git'}


def find_pycache_dirs(repo_root: Path) -> list:
    """仓库自有代码的 __pycache__。剪掉依赖/工作树/.git —— 那不是我们的垃圾，走它们还慢。"""
    out = []
    for dirpath, dirnames, _files in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in _PYCACHE_SKIP]
        if '__pycache__' in dirnames:
            out.append(Path(dirpath) / '__pycache__')
            dirnames.remove('__pycache__')   # 不必钻进 __pycache__ 内部
    return sorted(out)


def collect_roots(repo_root: Path = REPO_ROOT) -> list:
    """五类注册表汇总（含 electron）。只造 DataRoot 对象，不碰盘；过滤交给 select_roots。"""
    return (data_roots(repo_root) + artifact_roots(repo_root) + cache_roots(repo_root)
            + scratch_roots(repo_root) + electron_roots())


def select_roots(roots: list, wanted: set, include_electron: bool) -> list:
    """按 --only（名字或类别）/ --all 选根。

    wanted 非空：命中名字或类别即收（显式 ``--only electron`` 本身就是 opt-in）。
    wanted 为空：默认收除 electron 外全部，``include_electron``(--all) 才含 electron。
    """
    out = []
    for r in roots:
        if wanted:
            if r.name in wanted or r.category in wanted:
                out.append(r)
        elif include_electron or r.category != 'electron':
            out.append(r)
    return out