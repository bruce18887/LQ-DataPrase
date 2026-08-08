"""batch_charts 多进程渲染 worker。

⚠️ 本模块被 ProcessPoolExecutor（Windows spawn）子进程 import：
- 只允许 import io/os/numpy/pandas/matplotlib 等无 Django 依赖的模块，
  禁止 import 任何 apps.* / Django 模块（apps.export.charts 除外——它无 Django 依赖）。
- 若未来给 apps/export/charts.py 添加 Django import，会导致 worker 启动失败，
  届时须将渲染逻辑移入本模块。
"""

import atexit
import io
import os
import shutil
import tempfile

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use('Agg')
# 每个 worker 独立 matplotlib 配置目录，避免并发写 font cache 竞争。
# 进程退出时清理（Windows spawn 每次导出新建子进程，不清理会累积 mpl_* 目录）
_MPL_CONFIG_DIR = tempfile.mkdtemp(prefix='mpl_')
os.environ['MPLCONFIGDIR'] = _MPL_CONFIG_DIR
atexit.register(shutil.rmtree, _MPL_CONFIG_DIR, ignore_errors=True)

from apps.export.charts import _render_histogram_payload  # noqa: E402


def render_histogram_worker(task: dict) -> bytes:
    """渲染单个参数直方图 PNG。task 为可 pickle 的标量/ndarray 字典。

    返回 PNG bytes（空数据 → 空 bytes，调用方按现状跳过）。
    """
    buf = _render_histogram_payload(**task)
    data = buf.getvalue()
    buf.close()
    return data
