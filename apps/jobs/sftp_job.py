"""SFTP 批量下载作业（线程 lane）。

为什么是线程不是进程池：SFTP 传输是 IO-bound（不占 CPU），而下载过程中要**在主进程里**
注册 DataFile、写进度 —— 那些都要 Django。所以这一类作业跑在 `ThreadPoolExecutor` 上，
CPU-bound 的三个导出才跑进程池。

为什么每作业开一条**临时**连接：paramiko 的 `SFTPClient` 不是线程安全的。
`pool.py` 的 per-user 常驻连接是给交互式浏览用的（一次只有一条请求在用），
作业后台跑几分钟还攥着它，用户在前端一点 SFTP 就会互踩。
临时连接的做法沿用 `apps/sftp/search/connect.py`。上限由
`executor.MAX_DOWNLOAD_WORKERS` 兜住 —— 不设限的话 20 人一起下载会撞
`sshd MaxStartups`。

产物语义（与今天的 SSE 通路一致，没 invent 新东西）：批量下载的文件**当场注册进用户库**，
所以作业的 `result_path` 是那个批次目录（相对 MEDIA_ROOT）、`result_name` 是目录名，
而 `GET /jobs/<id>/download/` 对这类作业返回 409 —— 它没有一个「可再下载的单文件」，
伪造一个 zip 只是把已经落盘的东西再打包一遍。
"""

import logging
import os
import time

from django.utils import timezone

from apps.datafiles.views._helpers import _user_upload_dir
from apps.jobs.models import Job
from apps.sftp import cache, downloads as sftp_downloads
from apps.sftp import host_keys

logger = logging.getLogger(__name__)

# 进度写库限频：生成器每 0.1s 就发一个 progress 事件，透传就变成 SQLite 写放大
# （spec §10 的第一条风险）。1 次/秒/作业足够人眼阅读。
PROGRESS_WRITE_INTERVAL = 1.0


def progress_should_write(now: float, last_write: float,
                          percent: int, last_percent: int) -> bool:
    """这一次进度事件要不要写库。抽成函数是为了能被直接验算 ——
    用 mock 去拦 `Job.objects.filter` 数写入次数，会把 Manager 本身搞坏
    （第一版就这么红过：`cannot unpack non-iterable Manager object`）。

    两个条件都要满足：距上次写够久（限频，防 SQLite 写放大），
    且百分比真的前进了（去重，防同一秒内反复写同一个值）。
    """
    return (now - last_write) >= PROGRESS_WRITE_INTERVAL and percent > last_percent


class SftpJobError(Exception):
    """携带稳定错误码的作业异常（视图据此答 not_connected）。"""

    def __init__(self, code, detail=''):
        self.code = code
        super().__init__(f'{code}: {detail}' if detail else code)


def _open_temp_sftp(user_id: int):
    """按缓存里的会话开一条只属于本作业的 SFTP 连接（调用方负责 close）。

    没有缓存会话 = 用户当前没连上 SFTP ⇒ 直接抛 `not_connected`。
    这道判断**只在这里做**：视图不再单独查一次 cache，两处查法迟早漂移。
    """
    creds = cache.get_session(user_id)
    if not creds:
        raise SftpJobError('not_connected', f'user {user_id} 没有可用的 SFTP 会话')
    transport = host_keys.open_verified_transport(
        creds['host'], creds['port'], creds['username'], creds['password'])
    import paramiko
    sftp = paramiko.SFTPClient.from_transport(transport)
    if sftp is None:
        transport.close()
        raise SftpJobError('not_connected', 'from_transport 返回 None（连接已断）')
    return sftp


def collect_remote_files(sftp, remote_path: str) -> list:
    """列出要下载的 CSV（跳过规则与 SSE 端点同一份实现）。"""
    result: list = []
    sftp_downloads.collect_files(sftp, remote_path, result, '', True)
    return result


def run_sftp_download(task: dict) -> dict:
    """消费与 SSE 端点**同一个**事件生成器，把进度写回 Job 行。

    复用生成器是刻意的：跳过汇总 CSV、半截文件清理、超时即 invalidate、
    「下载即注册」这些语义都已经在 `downloads.download_dir_events` 里验过，
    作业化不该重新实现一遍下载。
    """
    job = Job.objects.get(pk=task['job_id'])
    user = job.owner
    file_list = [tuple(item) for item in task['file_list']]
    dir_name = task['dir_name']
    timeout_sec = task['timeout_sec']

    upload_dir = _user_upload_dir(user, 'batch')
    local_dir = os.path.join(upload_dir, dir_name)
    os.makedirs(local_dir, exist_ok=True)

    errors: list = []
    done_event: dict = {}
    last_write = 0.0
    last_percent = -1

    sftp = _open_temp_sftp(user.pk)
    try:
        for event in sftp_downloads.download_dir_events(
                sftp, user, file_list, local_dir, dir_name, timeout_sec):
            kind = event.get('event')
            if kind == 'progress':
                percent = int(event.get('percent') or 0)
                now = time.monotonic()
                if progress_should_write(now, last_write, percent, last_percent):
                    Job.objects.filter(pk=job.pk, status='running').update(
                        progress=max(1, min(99, percent)))
                    last_write, last_percent = now, percent
            elif kind == 'error':
                errors.append(f"{event.get('filename')}: {event.get('message')}")
            elif kind == 'done':
                done_event = event
    finally:
        try:
            sftp.close()
        except Exception:  # 关闭失败不改变作业结果
            logger.warning('sftp job %s: temp connection close failed', job.pk,
                           exc_info=True)

    file_count = int(done_event.get('file_count') or 0)
    rel = os.path.join('data', str(user.username), 'batch', dir_name)
    finished = timezone.now()

    if not errors:
        Job.objects.filter(pk=job.pk).update(
            status='done', progress=100, result_path=rel, result_name=dir_name,
            finished_at=finished)
    elif file_count or _any_registered(user, dir_name):
        # 部分失败：既有 SSE 语义就是「清半截 + error 事件 + 继续下一只」，
        # 所以成功过的作业仍是 done，失败信息留在 error 字段给人看。
        Job.objects.filter(pk=job.pk).update(
            status='done', progress=100, result_path=rel, result_name=dir_name,
            error='部分失败（%d 只）：%s' % (len(errors), '; '.join(errors[:3])),
            finished_at=finished)
    else:
        Job.objects.filter(pk=job.pk).update(
            status='error', progress=0,
            error='全部失败：%s' % '; '.join(errors[:3]), finished_at=finished)

    # 全失败时**不再抛异常**：终态与人话已经写进行里了，再抛只会让
    # done-callback 用异常文本（`SftpJobError: download_failed: ...`）覆盖掉
    # 「哪几只失败」这句更有用的话。调用方读 Job.status 判断成败即可。
    return {'downloadable': False, 'result_path': rel, 'result_name': dir_name,
            'file_count': file_count, 'errors': errors}


def _any_registered(user, dir_name: str) -> bool:
    """done 事件缺失时（生成器被中断）用库里的行判断有没有真的下载成功。"""
    from apps.datafiles.models import DataFile
    prefix = os.path.join(_user_upload_dir(user, 'batch'), dir_name)
    return DataFile.objects.filter(owner=user,
                                   file_path__startswith=prefix).exists()


def build_sftp_task(*, job_id, owner_id, remote_path, dir_name,
                    file_list, timeout_sec) -> dict:
    """task 里带 file_list：要下什么在**提交那一刻**定死。

    不这么做的后果是排队期间远端目录变了，用户拿到的是一份他没点过的清单。
    清单本身不进 `Job.params`（大目录能到几千条，那是把内部结构当用户意图存起来），
    params 只存 path / dir_name / 条数。
    """
    return {
        'job_id': job_id,
        'owner_id': owner_id,
        'remote_path': remote_path,
        'dir_name': dir_name,
        'timeout_sec': int(timeout_sec),
        'file_list': [list(item) for item in file_list],
    }
