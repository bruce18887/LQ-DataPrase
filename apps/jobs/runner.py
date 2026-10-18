"""作业 worker 的入口函数（**禁止 import Django**）。

本模块被 `ProcessPoolExecutor` 的 spawn 子进程导入，子进程里没有 `django.setup()`，
任何 Django 依赖都会让它起不来。`apps/jobs/tests_jobs.py` 的
`WorkerModuleIsolationTests` 钉的就是这条约束 —— 它不是风格偏好，是这片设计的前提。

因此任务参数只允许纯数据（绝对路径字符串、格式名、标量、可 pickle 的 dict/list），
 DataFrame 由 worker 自己解析：275MB 的帧跨进程边界序列化比渲染本身还贵，
 而「主进程一次都不解析」正是作业化想要的效果。
"""

import logging
import os
from types import SimpleNamespace

logger = logging.getLogger(__name__)

from apps.analysis.services.statistics import (
    compute_uph, filter_bin1_rows, get_site_column)
from apps.common.user_settings import CpkThresholds
from apps.dashboard.services import compute_dashboard_summary
from apps.datafiles.parsers import get_parser
from apps.datafiles.parsers.base import SYSTEM_COLUMNS
# 刻意**不**走 `apps.export.export_complete` 那个门面：它会带上
# export_batch_charts_xlsx → apps.common.user_settings → apps.accounts.models，
# 于是 worker 在子进程里 import 期就撞上未配置的 Django（这条由
# `tests_jobs.WorkerModuleIsolationTests` 钉住，它就是从这里第一次抓到违规的）。
# 直接导入具体模块是唯一 Django-free 的通路。
from apps.export.columns import DEFAULT_CHART_PARAMS, measurable_numeric_columns
from apps.export.export_batch_charts_xlsx import build_batch_charts_xlsx_with_charts
from apps.export.export_ppt import build_batch_charts_pptx
from apps.export.export_xlsx_optimized import export_to_xlsx_optimized
from apps.export.filters import apply_export_filters
from apps.export.html_report import build_single_html_report

# 进度侧车：worker 没有 Django、写不了 DB，就把百分比落进作业目录里一个小文件，
# 主进程轮询器读它再写回 Job.progress。比 multiprocessing.Manager 便宜得多
# （不必为每个池再起一个 manager 进程），且 worker 崩了文件还在 —— 天然是「最后已知进度」。
PROGRESS_FILENAME = '.progress'


def progress_path_for(out_path: str) -> str:
    return os.path.join(os.path.dirname(out_path), PROGRESS_FILENAME)


def write_progress(path: str, done: int, total: int) -> int:
    """把 `done/total` 折成 1–100 写进侧车文件，返回写入的百分比。

    两条都是被 e2e 逼出来的，不是预防性铺陈：
    * **目录得自己建** —— 作业目录原本只在写结果时才创建，而进度从第一秒就要写，
      于是第一次写就 FileNotFoundError ⇒ worker 死掉、前端永远等不到下载事件。
    * **写失败要吞掉** —— 进度是装饰性的，只读盘/被锁这类故障不该让一次导出失败。
    """
    percent = max(1, min(100, int(round(done * 100 / max(1, total)))))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(str(percent))
    except OSError:
        logger.warning('jobs progress write failed: %s', path, exc_info=True)
    return percent


def read_progress(path: str) -> int:
    """读侧车文件。读不到就当 0 —— 进度缺失不该让作业看起来失败。"""
    try:
        with open(path, encoding='utf-8') as fh:
            return max(0, min(100, int((fh.read() or '0').strip())))
    except (OSError, ValueError):
        return 0


def _parse_and_filter(task: dict):
    """解析 + 可选 bin==1 过滤（与同步端点同口径，顺序也一致）。"""
    df, metadata = get_parser(task['fmt']).parse(task['abs_path'])
    if task.get('data_only_bin1'):
        df = filter_bin1_rows(df, metadata)
    return df, metadata


def _datafile_proxy(task: dict):
    """compute_dashboard_summary / pptx 只要 id / filename / program_name 三个字段。

    主进程把它们塞进 task，worker 这里重组成属性对象 —— 于是 worker 不必 import
    DataFile（那是 Django 模型），而报表里出现的文件号与名字仍与提交时一致。
    """
    d = task.get('datafile') or {}
    return SimpleNamespace(id=d.get('id', 0), filename=d.get('filename', ''),
                           program_name=d.get('program_name', ''))


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
    progress = task.get('progress_path') or progress_path_for(task['out_path'])
    write_progress(progress, 1, 3)
    df, metadata = _parse_and_filter(task)
    write_progress(progress, 2, 3)
    export_df = apply_export_filters(df, metadata, task['filters'])
    payload = export_to_xlsx_optimized(
        export_df, metadata, hidden_columns=task['hidden_columns'])
    size = _write_out(payload, task['out_path'])
    write_progress(progress, 3, 3)
    return {'out_path': task['out_path'], 'bytes_written': size,
            'progress_percent': 100}


def run_export_batch_charts(task: dict) -> dict:
    """批量图表：xlsx 与 pptx 两种产物，参数缺省时在 worker 侧算默认列表。

    `workers=1` 是硬要求：本函数已经跑在常驻作业池的子进程里，
    builder 里那一层渲染池若照默认开 8，就是 4×8=32 个 Python 进程（每个常驻
    150–250MB）。并行度只在作业池那一层给，这里串行渲染。
    """
    progress = task.get('progress_path') or progress_path_for(task['out_path'])
    df, metadata = _parse_and_filter(task)
    fmt = metadata.get('format', task['fmt'])

    params = list(task.get('params') or [])
    if not params:
        # 与同步端点同一条默认口径（views 里那段是同一个函数、同一个 exclude）
        params = measurable_numeric_columns(
            df, exclude=SYSTEM_COLUMNS.get(fmt, []))[:DEFAULT_CHART_PARAMS]

    thresholds = CpkThresholds(*task['cpk_thresholds'])
    show = {k: task[k] for k in ('show_limit', 'show_3sigma', 'show_4sigma',
                                 'show_6sigma', 'show_normal', 'show_kde')}
    write_progress(progress, 1, 3)

    if task.get('chart_format') == 'pptx':
        payload = build_batch_charts_pptx(
            _datafile_proxy(task), df, metadata, params, **show,
            dpi=task['dpi'], cpk_thresholds=thresholds)
    else:
        total = max(1, len(params))

        def _cb(done: int, _total=total, _p=progress):
            write_progress(_p, done, _total)

        payload = build_batch_charts_xlsx_with_charts(
            df, metadata, params, site_col=get_site_column(df), **show,
            dpi=task['dpi'], cpk_thresholds=thresholds,
            workers=1, progress_cb=_cb)

    size = _write_out(payload, task['out_path'])
    write_progress(progress, 3, 3)
    return {'out_path': task['out_path'], 'bytes_written': size,
            'progress_percent': 100}


def run_export_html_report(task: dict) -> dict:
    """HTML 报告：复用 `/summary/` 同一份 `compute_dashboard_summary`，杜绝数字漂移。

    `generated_at` 由主进程算好传进来 —— 报告上的时间戳必须钉在**提交那一刻**，
    否则用户看到的生成时间会随队列长度漂移。
    """
    progress = task.get('progress_path') or progress_path_for(task['out_path'])
    df, metadata = _parse_and_filter(task)
    write_progress(progress, 1, 3)
    thresholds = CpkThresholds(*task['cpk_thresholds'])
    payload = compute_dashboard_summary(
        df, _datafile_proxy(task), task['fmt'], metadata, thresholds=thresholds)
    uph = compute_uph(df, metadata)
    write_progress(progress, 2, 3)
    html = build_single_html_report(
        payload, metadata, uph, dpi=task['dpi'],
        generated_at=task['generated_at'])
    size = _write_out(html.encode('utf-8'), task['out_path'])
    write_progress(progress, 3, 3)
    return {'out_path': task['out_path'], 'bytes_written': size,
            'progress_percent': 100}
