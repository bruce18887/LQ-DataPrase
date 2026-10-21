#!/usr/bin/env python
"""内存峰值清单（人工工具，不进 CI）。

跑法：
    .venv/Scripts/python.exe scripts/memory_profile.py --rows 20000 --params 100

只读测量：本脚本只量 RSS，不写库、不落盘。为了让「不写库」成为结构性保证而不是
自觉，`django.setup()` 前面上了两道闸：

1. 设置档固定用 `config.settings.unit`（测试档），不用 `development`。unit 档把库 /
   MEDIA_ROOT / 临时区都指到 `test/unit-data`（`LQDP_UNIT_DATA_DIR`），与真实数据根
   无关。**刻意不用 `setdefault`**：外部环境里预置的 `DJANGO_SETTINGS_MODULE`
   若是 development，`setdefault` 会原样保留，闸门就形同虚设。
2. `django.setup()` 前后把 `sys.argv` 临时换成离线命令 `check`。`JobsConfig.ready()`
   在服务启动路径上会调 `mark_interrupted_jobs()`，把库里 `running` 的作业 UPDATE 成
   `error`（见 `apps/jobs/apps.py`）；一个量内存的脚本跑一次就把用户的作业判死，代价
   远大于这次测量。`check` 在 `OFFLINE_COMMANDS` 里，`ready()` 会走「无僵尸可收」分支。

两道闸任一单独都够拦，叠起来是纵深防御。跑完 `git status` 只应看到本脚本，
输出日志按约定放 `tasks/`（gitignored）。
"""
import argparse
import gc
import os
import sys
import threading
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.unit'

import django  # noqa: E402

_argv = sys.argv
sys.argv = ['memory_profile.py', 'check']   # OFFLINE_COMMANDS includes 'check'
try:
    django.setup()
finally:
    sys.argv = _argv

import psutil  # noqa: E402

from apps.analysis.services.data_services.histogram import compute_histogram_stats  # noqa: E402
from apps.analysis.services.statistics.kde import GaussianKDE, MAX_KDE_SAMPLES  # noqa: E402

MB = 1024 * 1024


def _rss():
    return psutil.Process(os.getpid()).memory_info().rss


class _Sampler:
    # 1ms 而非 20ms：KDE 一次调用只有 ~17ms，20ms 采样几乎必然整段错过（实测同一
    # 操作在 20ms 下读 0.0MiB、5ms 读 4–5MiB、1ms 读 5–7MiB），那样的峰值表会把
    # 「有峰值」写成「没峰值」。psutil.memory_info 本身 ~0.1ms，1ms 采样不吃掉测量对象。
    def __init__(self, interval=0.001):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, _rss())
            time.sleep(self.interval)

    def __enter__(self):
        self.peak = _rss()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2)
        return False


def _measure(name, fn):
    gc.collect()
    base = _rss()
    with _Sampler() as sampler:
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
    print(f'{name:<32} base={base/MB:8.1f}MiB '
          f'peak={sampler.peak/MB:8.1f}MiB delta={(sampler.peak-base)/MB:8.1f}MiB '
          f'{ms:8.1f}ms')


def _frame(rows, params):
    rng = np.random.default_rng(20261021)
    return pd.DataFrame({
        f'P{i}': rng.normal(10.0, 0.5, rows) for i in range(params)
    })


def _metadata(params):
    return {
        'format': 'CTA8280F',
        'mins': {f'P{i}': '8.0' for i in range(params)},
        'maxs': {f'P{i}': '12.0' for i in range(params)},
        'units': {f'P{i}': 'uA' for i in range(params)},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=20000)
    parser.add_argument('--params', type=int, default=100)
    args = parser.parse_args()

    print(f'python={sys.version.split()[0]} numpy={np.__version__} '
          f'pandas={pd.__version__} rows={args.rows} params={args.params}')
    _measure('import baseline', lambda: None)

    df = _frame(args.rows, args.params)
    meta = _metadata(args.params)
    _measure('frame resident', lambda: df.memory_usage(deep=True).sum())
    _measure('histogram no KDE',
             lambda: compute_histogram_stats(df, meta, 'P0', None,
                                             include_kde=False))
    _measure('histogram with KDE',
             lambda: compute_histogram_stats(df, meta, 'P0', None,
                                             include_kde=True, kde_variant='all'))

    vals = np.random.default_rng(7).normal(0, 1, MAX_KDE_SAMPLES)
    grid = np.linspace(-5, 5, 200)
    _measure('GaussianKDE call (16384)',
             lambda: GaussianKDE(vals, bw_method='silverman')(grid))


if __name__ == '__main__':
    main()
