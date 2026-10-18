#!/usr/bin/env python
"""20 人并发性能基线（合并版）。

前身是 `tasks/perf_probe_*_2026-10-17.py` 六个临时探针，本脚本把它们的判据一次固化，
用于「改前 / 改后」对比。**只读**：不建用户、不写库、不落盘（matplotlib 用 Agg，临时区由
子进程自管），所以拿开发档跑也不会碰到真实数据目录。

跑法：
    .venv/Scripts/python.exe scripts/perf_baseline.py                 # 全部可跑组
    .venv/Scripts/python.exe scripts/perf_baseline.py big irm         # 只跑指定组
    .venv/Scripts/python.exe scripts/perf_baseline.py --unit ms       # 单位开关

组：
    big      解析/常驻/copy/排序/序列化（一次性成本的主体）
    screen   browse 首页元信息 + 看板汇总（含 P1-2 的缓存命中）
    analysis 直方图 10 参数 + 全列低 CPK
    batch    批次汇总里「每只文件的统计」部分
    irm      ag-grid IRM 每块的 filter+sort（真实 UI 的滚动成本）
    startup  子进程 import 成本 + 8  worker 进程池冷启（P3 作业化的验收基线）
    auth     PBKDF2 登录哈希成本

缺 `Data/SampleData` 大文件时，依赖它的组打印 SKIP 后跳过（样例数据不入库），
`startup` 与 `auth` 仍会跑。数字必须有命令产出过才写进文档，见
`docs/reference/perf-baseline-2026-10-17.md`。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tracemalloc
from concurrent.futures import ProcessPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

# 基线文件：275MB / 35,246 行 × 1,702 列 / 文本列只有 2 个（Site #、Serial #）。
BIG_REL = os.path.join(
    'Data', 'SampleData', 'Batch', 'FT', 'BP01-2605220057', 'R2605230015',
    'C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057_FT1-FT1-1_'
    'R2605230015_ETS083302_05272026.csv')

_rows = []          # [(group, label, value_ms, unit)]
_current_group = '-'


def probe(label, fn, *, unit='ms'):
    """跑一次 `fn` 并记账；返回值原样透出，便于把中间结果喂给后续探针。"""
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    value = dt * 1000 if unit == 'ms' else dt * 1e6
    _rows.append((_current_group, label, value, unit))
    print(f'  {label:<44} {value:10.0f} {unit}', flush=True)
    return out


def header(title):
    print(f'\n=== {title}', flush=True)


def emit(group_name):
    global _current_group
    _current_group = group_name


def big_path():
    return os.path.join(ROOT, BIG_REL)


def load_big():
    """识别格式 → 全量解析。返回 (fmt, df, metadata)；文件缺失返回 None。

    刻意**不**开 tracemalloc：它会把 parse() 从 3.3s 抬到 7.8s（实测），而 parse 的耗时正是
    本表的主项。峰值内存要看 `--groups ... peak`，那一组单独重跑一次解析。
    """
    path = big_path()
    if not os.path.exists(path):
        print(f'SKIP: 缺基线文件 {BIG_REL}（样例数据不入库）', flush=True)
        return None
    from apps.datafiles.parsers import get_parser
    from apps.datafiles.parsers.base import BaseATEParser

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        fmt = BaseATEParser.identify_format(f.read(4096))
    emit('big')
    header(f'{os.path.basename(path)}  {os.path.getsize(path) / 1024 / 1024:.0f} MB  fmt={fmt}')
    df, metadata = probe('parse()', lambda: get_parser(fmt).parse(path))
    print(f'  shape={df.shape}  常驻={df.memory_usage(deep=True).sum() / 1024 / 1024:.0f} MB'
          '  （MB 是内存，不进 ms 账）', flush=True)
    return fmt, df, metadata


def group_peak():
    """解析期峰值内存（tracemalloc 会拖慢解析，所以独立成一组、默认不跑）。"""
    path = big_path()
    if not os.path.exists(path):
        return
    from apps.datafiles.parsers import get_parser
    from apps.datafiles.parsers.base import BaseATEParser

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        fmt = BaseATEParser.identify_format(f.read(4096))
    emit('peak')
    header('解析期峰值内存（本组自身会让 parse 变慢，勿与 big.parse 比）')
    tracemalloc.start()
    probe('parse() under tracemalloc', lambda: get_parser(fmt).parse(path))
    _cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f'  peak={peak / 1024 / 1024:.0f} MB', flush=True)


def group_big(fmt_df_meta):
    if not fmt_df_meta:
        return
    _fmt, df, metadata = fmt_df_meta
    from apps.analysis.services.statistics import detect_fail_data

    emit('big')
    probe('detect_fail_data()', lambda: detect_fail_data(df, metadata))
    probe('df.copy()（导出/筛选首步）', lambda: df.copy())

    import pandas as pd
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])][:1]
    probe(f'sort_values 单列 {num_cols}',
          lambda: df.sort_values(by=num_cols, kind='mergesort', na_position='last'))
    probe('page(100 行) to_json',
          lambda: df.iloc[:100].to_json(orient='values', date_format='iso'))
    # 原本这里还有两条 browse `search` 探针（astype(str) 10.1s / 全链路 16.2s）。
    # 2026-10-17 P1-5 已把该参数删除并改成直连 400，故不再测量一个不存在的通路。


def group_screen(fmt_df_meta):
    if not fmt_df_meta:
        return
    fmt, df, metadata = fmt_df_meta
    import pandas as pd

    from apps.analysis.services.statistics import build_col_meta, get_site_column
    from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS
    from apps.dashboard.services import compute_dashboard_summary, get_dashboard_summary

    class _FakeFile:
        """汇总函数只读这几个字段，因此不需要建库、不需要 DataFile 行。"""
        id = 1
        owner_id = 1
        filename = 'baseline.csv'
        program_name = 'BASELINE'
        file_path = big_path()

    emit('screen')
    header('首屏（browse page==1 元信息 + 看板汇总）')

    def _page1_meta():
        site_col = get_site_column(df)
        site_options = []
        if site_col:
            site_options = [str(v) for v in df[site_col].dropna().astype(str).unique()
                            if str(v) not in ('', 'nan')]
        numeric_columns = []
        for col in df.columns:
            if df[col].dtype == object:
                if pd.to_numeric(df[col], errors='coerce').notna().any():
                    numeric_columns.append(col)
            elif (pd.api.types.is_numeric_dtype(df[col])
                  and not pd.api.types.is_bool_dtype(df[col])
                  and df[col].notna().any()):
                numeric_columns.append(col)
        return site_options, numeric_columns

    probe('browse page==1 元信息循环', _page1_meta)
    probe('build_col_meta()', lambda: build_col_meta(df, metadata))
    probe('compute_dashboard_summary()（不缓存）',
          lambda: compute_dashboard_summary(df, _FakeFile(), fmt, metadata))

    # P1-2 的承重项：同 key 第二次必须命中缓存。两条分别打「首次未命中」与「二次命中」，
    # 差值就是切 tab 省下来的钱 —— 只测第二次会看不出它到底有没有在算。
    th = DEFAULT_CPK_THRESHOLDS
    probe('get_dashboard_summary() 首次（未命中）',
          lambda: get_dashboard_summary(_FakeFile(), df, fmt, metadata, th))
    probe('get_dashboard_summary() 二次（应命中缓存）',
          lambda: get_dashboard_summary(_FakeFile(), df, fmt, metadata, th))
    probe('get_dashboard_summary() 换 thresholds（必须失效重算）',
          lambda: get_dashboard_summary(
              _FakeFile(), df, fmt, metadata,
              type(th)(cpk_a=1.0, cpk_b=1.0, cpk_c=1.0)))


def group_analysis(fmt_df_meta):
    if not fmt_df_meta:
        return
    _fmt, df, metadata = fmt_df_meta
    import pandas as pd

    from apps.analysis.services.data_services import compute_histogram_stats
    from apps.analysis.services.statistics import compute_low_cpk_test_items

    emit('analysis')
    header('分析页主路径')
    numeric = [c for c in df.columns
               if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    print(f'  数值列 = {len(numeric)}', flush=True)
    params = numeric[:10]
    site_col = 'Site_No' if 'Site_No' in df.columns else None
    probe('histogram 10 参数',
          lambda: [compute_histogram_stats(df, metadata, p, site_col) for p in params])
    probe('全列低 CPK 扫描',
          lambda: compute_low_cpk_test_items(df, metadata, 1.33, iqr_multiplier=1.5))


def group_batch(fmt_df_meta):
    if not fmt_df_meta:
        return
    fmt, df, metadata = fmt_df_meta
    from apps.analysis.services.statistics import (
        calculate_fail_bin_statistics, compute_site_yield_data, compute_uph,
        get_bin_column_name, get_site_column)

    emit('batch')
    header('批次汇总里「每只文件的统计」部分（成本主体在 parse，不在这里）')
    probe('calculate_fail_bin_statistics', lambda: calculate_fail_bin_statistics(df, metadata))
    site_col = get_site_column(df)
    bin_col = get_bin_column_name(fmt)
    print(f'  site_col = {site_col}  bin_col = {bin_col}', flush=True)
    if site_col and bin_col in df.columns:
        probe('compute_site_yield_data',
              lambda: compute_site_yield_data(df, bin_col, site_col))
    probe('compute_uph', lambda: compute_uph(df, metadata))


def group_irm(fmt_df_meta):
    if not fmt_df_meta:
        return
    _fmt, df, _metadata = fmt_df_meta
    import pandas as pd

    from apps.datafiles.views.browse_views import _apply_filter_model, _apply_sort

    emit('irm')
    header('ag-grid IRM 每块（真实滚动路径，非 search）')
    str_cols = [c for c in df.columns if df[c].dtype == object]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    print(f'  文本列 {len(str_cols)} / 数值列 {len(num_cols)}  样例 {str_cols[:5]}', flush=True)
    if not str_cols or not num_cols:
        print('  SKIP: 夹具列形态不满足（要既有文本列又有数值列）', flush=True)
        return
    fm_text = {str_cols[0]: {'filterType': 'text', 'type': 'contains', 'filter': '1'}}
    fm_num = {num_cols[0]: {'filterType': 'number', 'type': 'greaterThan', 'filter': 0}}
    sm = [{'colId': num_cols[0], 'sort': 'asc'}]
    probe('filter_model 文本列 contains', lambda: _apply_filter_model(df, fm_text))
    probe('filter_model 数值列 >0', lambda: _apply_filter_model(df, fm_num))
    probe('sort_model 单列', lambda: _apply_sort(df, sm))
    probe('filter+sort 合成一块', lambda: _apply_filter_model(_apply_sort(df, sm), fm_num))


def _worker_import_cost(_unused):
    """在子进程里量「import pandas + matplotlib」的冷启动 —— Windows 是 spawn，
    每个新 worker 都要付一遍。P3 用常驻池 + warmup 把这笔钱挪到启动期。"""
    t0 = time.perf_counter()
    import pandas  # noqa: F401
    import matplotlib
    matplotlib.use('Agg')
    return (time.perf_counter() - t0) * 1000


def _worker_chart_workers_import(_unused):
    """子进程里 import **真实 worker 模块**（`apps.export.chart_workers`）。

    与上一条的区别才是每次导出真正付的钱：worker 模块除 pandas/matplotlib 外还带
    `apps.export.charts`（渲染实现），且 Windows spawn 会把整个模块图重新走一遍。
    """
    import apps.export.chart_workers  # noqa: F401
    return 1


def group_startup(_big=None):
    emit('startup')
    header('进程/导入启动开销（P3 作业化的基线）')
    code = ('import time; t0=time.perf_counter();'
            'import pandas, matplotlib; matplotlib.use("Agg");'
            'print(f"{(time.perf_counter()-t0)*1000:.0f}")')
    t0 = time.perf_counter()
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                         encoding='utf-8', errors='replace', cwd=ROOT)
    dt = (time.perf_counter() - t0) * 1000
    _rows.append(('startup', '子进程 import pandas+matplotlib（含解释器启动）', dt, 'ms'))
    print(f'  {"子进程 import pandas+matplotlib（含解释器启动）":<44} {dt:10.0f} ms'
          f'  stdout={out.stdout.strip() or out.stderr.strip()[:60]}', flush=True)

    workers = 8  # apps/export/export_batch_charts_xlsx.py 当前的并发度
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        costs = list(ex.map(_worker_import_cost, range(workers)))
    dt = (time.perf_counter() - t0) * 1000
    _rows.append(('startup', f'ProcessPoolExecutor({workers}) 冷启 + 每 worker import', dt, 'ms'))
    print(f'  {f"ProcessPoolExecutor({workers}) 冷启 + 每 worker import":<44} {dt:10.0f} ms'
          f'  各 worker import={sorted(int(c) for c in costs)}', flush=True)

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_worker_chart_workers_import, range(workers)))
    dt = (time.perf_counter() - t0) * 1000
    _rows.append(('startup', '池冷启 + 每 worker import chart_workers（真实导出通路）', dt, 'ms'))
    print(f'  池冷启 + 每 worker import chart_workers（真实导出通路）'.ljust(44)
          + f' {dt:10.0f} ms', flush=True)
    print('  ⚠ 方案 §6 那句「715ms × 8 ≈ 5.7s 纯启动」是串行乘法，而 spawn 出来的 worker 是'
          '并发启动的 —— 真实墙钟见上两行。P3 的收益不在「省启动」，在「把活挪出请求线程」，'
          '这条已写进基线文档，验收线也随之改。', flush=True)


def group_auth(_big=None):
    emit('auth')
    header('登录路径')
    from django.contrib.auth.hashers import check_password, make_password

    password = 'x-pass-12345678'
    t0 = time.perf_counter()
    encoded = make_password(password)
    mk = (time.perf_counter() - t0) * 1000
    algo = encoded.split('$', 1)[0]  # 形如 pbkdf2_sha256$迭代数$salt$hash
    label = f'make_password（{algo}）'
    _rows.append(('auth', label, mk, 'ms'))
    print(f'  {label:<44} {mk:10.0f} ms', flush=True)

    probe(f'check_password 命中（{algo}）', lambda: check_password(password, encoded))
    probe('check_password 不匹配（同样付满迭代）', lambda: check_password('wrong-pw', encoded))


GROUPS = {
    'big': group_big,
    'screen': group_screen,
    'analysis': group_analysis,
    'batch': group_batch,
    'irm': group_irm,
    'startup': group_startup,
    'auth': group_auth,
    'peak': group_peak,
}
NEEDS_BIG = {'big', 'screen', 'analysis', 'batch', 'irm'}
# peak 默认不跑：它自己会再解析一次，且 tracemalloc 下那个数字不可与其它项同表比较。
DEFAULT_GROUPS = ['big', 'screen', 'analysis', 'batch', 'irm', 'startup', 'auth']


def main(argv=None):
    ap = argparse.ArgumentParser(description='20 人并发性能基线（只读）')
    ap.add_argument('groups', nargs='*', choices=sorted(GROUPS), help='缺省跑全部')
    ap.add_argument('--json', action='store_true', help='结果另存 JSON，便于两轮对比')
    ap.add_argument('--out', default='', help='--json 的输出路径')
    args = ap.parse_args(argv)

    import django
    django.setup()

    names = args.groups or DEFAULT_GROUPS
    big = load_big() if any(n in NEEDS_BIG for n in names) else None
    for name in names:
        if name in NEEDS_BIG and big is None:
            emit(name)
            print(f'SKIP: 组 {name} 依赖基线大文件', flush=True)
            continue
        GROUPS[name](big)

    print('\n=== 汇总（可直接贴进 docs/reference/perf-baseline-2026-10-17.md）')
    print(f'{"group":<10} {"probe":<52} {"value":>10} unit')
    for g, label, value, unit in _rows:
        print(f'{g:<10} {label:<52} {value:>10.0f} {unit}')
    print(f'\n共 {len(_rows)} 项 · 本机时间 {time.strftime("%Y-%m-%d %H:%M:%S")}')

    if args.json:
        path = args.out or os.path.join(ROOT, 'tasks', 'perf_baseline.json')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump([{'group': g, 'probe': l, 'value': round(v), 'unit': u}
                       for g, l, v, u in _rows], f, ensure_ascii=False, indent=1)
        print(f'JSON → {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
