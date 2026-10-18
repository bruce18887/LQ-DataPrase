"""作业 worker 的入口函数（**禁止 import Django**）。

本模块被 `ProcessPoolExecutor` 的 spawn 子进程导入，子进程里没有 `django.setup()`，
任何 Django 依赖都会让它起不来。`apps/jobs/tests_jobs.py` 的
`WorkerModuleIsolationTests` 钉的就是这条约束 —— 它不是风格偏好，是这片设计的前提。

因此任务参数只允许纯数据（绝对路径字符串、格式名、标量、可 pickle 的 dict/list），
 DataFrame 由 worker 自己解析：275MB 的帧跨进程边界序列化比渲染本身还贵，
 而「主进程一次都不解析」正是作业化想要的效果。
"""

import os

from apps.datafiles.parsers import get_parser
# 刻意**不**走 `apps.export.export_complete` 那个门面：它会带上
# export_batch_charts_xlsx → apps.common.user_settings → apps.accounts.models，
# 于是 worker 在子进程里 import 期就撞上未配置的 Django（这条由
# `tests_jobs.WorkerModuleIsolationTests` 钉住，它就是从这里第一次抓到违规的）。
# 直接导入具体模块是唯一 Django-free 的通路。
from apps.export.export_xlsx_optimized import export_to_xlsx_optimized
from apps.export.filters import apply_export_filters


def warmup_imports() -> int:
    """进程池建好后立刻跑一次：在本进程里 import pandas/matplotlib。

    收益是亚秒级（`ProcessPoolExecutor(8)` 冷启实测 0.64–1.15s，见
    `docs/reference/perf-baseline-2026-10-17.md` §4），留着是因为免费，
    且它把第一次真实导出的尾延迟抹平。别把它写成 P3 的主要收益。
    """
    import matplotlib  # noqa: F401
    import pandas  # noqa: F401
    matplotlib.use('Agg')
    return 1


def _write_out(payload: bytes, out_path: str) -> int:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as fh:
        fh.write(payload)
    return os.path.getsize(out_path)


def run_export_excel(task: dict) -> dict:
    """解析 → 应用与表格一致的网格筛选 → 写 xlsx。返回 `{out_path, bytes_written}`。

    `task` 的字段由主进程 `apps/jobs/executor.build_export_excel_task` 拼，
    那里才能读 Django（settings / DataFile / 用户设置）。
    """
    parser = get_parser(task['fmt'])
    df, metadata = parser.parse(task['abs_path'])
    export_df = apply_export_filters(df, metadata, task['filters'])
    payload = export_to_xlsx_optimized(
        export_df, metadata, hidden_columns=task['hidden_columns'])
    size = _write_out(payload, task['out_path'])
    return {'out_path': task['out_path'], 'bytes_written': size}
