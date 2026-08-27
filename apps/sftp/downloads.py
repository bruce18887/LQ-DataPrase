"""SFTP 单文件下载 SSE 生成器。

背景：旧实现 ``download`` 用 ``sftp.get()`` 一次性下载完整个文件后才返回 JSON。
大文件（GB 级）在前端 30s 的 axios timeout 下必然超时报错；即使放宽 timeout，
前端也看不到任何进度。

本模块把单文件下载改为「分块读取 + SSE 进度事件」：
- 客户端通过 fetch 读流（与 download_dir 同构，无 axios 超时）；
- 服务端设置 SFTP channel 的 socket 超时（可配置，默认 600s），传输停滞即抛
  socket.timeout；同时用整体 deadline 兜底（channel 超时对传输期间有数据流动
  的慢速下载不生效，deadline 才能覆盖「永远差一点下完」的场景）；
- 进度事件携带 percent / speed(MB/s) / eta(s) / bytes，前端渲染百分比 + 速率进度条。
"""

import json
import logging
import os
import time
from contextlib import contextmanager

from apps.datafiles.views import _register_file

from . import pool

logger = logging.getLogger(__name__)

# 分块大小：256KB —— 与 paramiko 内部读缓冲兼容，SSE 事件节流到 ~10/s，避免
# 小文件催出一堆 99% 的事件（见下方 PROGRESS_EVENT_INTERVAL）。
DOWNLOAD_CHUNK_SIZE = 256 * 1024
PROGRESS_EVENT_INTERVAL = 0.1  # 秒：两次 progress 事件的最小间隔

DEFAULT_TIMEOUT_SEC = 600
MIN_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 3600


class DirDownloadTimeout(TimeoutError):
    """目录下载整体超时：中止整个 SSE 流（不再逐文件重试）。"""


def clamp_timeout(value):
    """钳位用户传入的超时（秒）到 [30, 3600]，非法输入回退默认 600。"""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        seconds = DEFAULT_TIMEOUT_SEC
    return min(MAX_TIMEOUT_SEC, max(MIN_TIMEOUT_SEC, seconds))


@contextmanager
def channel_timeout(sftp, seconds):
    """临时把 SFTP channel 的 socket 超时设为 ``seconds``，退出时恢复原值。

    pool 里的连接会被复用（pool._Entry），若不恢复，后续 listdir 等操作会继承
    这个宽松超时。contextmanager 保证异常路径也恢复。
    """
    try:
        channel = sftp.get_channel()
    except Exception:
        # 测试替身或异常连接没有 channel：交给下游处理
        yield
        return
    try:
        old = channel.gettimeout()
        channel.settimeout(seconds)
    except Exception:
        old = None
    try:
        yield
    finally:
        try:
            if old is not None:
                channel.settimeout(old)
        except Exception:
            logger.warning('Failed to restore SFTP channel timeout', exc_info=True)


def _remove_partial(file_path):
    """删除下载失败留下的半截文件（绝不让未注册的残片留在用户目录）。"""
    try:
        os.remove(file_path)
    except OSError:
        pass


def download_file_events(sftp, user, remote_path, file_path, timeout_sec):
    """生成单文件下载的 SSE 事件（dict 序列，由调用方 json.dumps 组装）。

    Events:
    - ``{'event': 'progress', 'percent', 'speed', 'eta', 'filename',
        'bytes_done', 'total_bytes'}``
    - ``{'event': 'done', 'filename', 'size', 'datafile_id'}``
    - ``{'event': 'error', 'message'}``

    失败/超时/客户端断开时清理半截文件；客户端断开（GeneratorExit）时还要
    invalidate 池里可能已失效的连接。
    """
    filename = os.path.basename(remote_path)
    start = time.time()
    deadline = start + timeout_sec
    bytes_done = 0
    last_event = 0.0

    # 目标目录：视图层经 _user_upload_dir 已创建；此处兜底保证生成器独立可用
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
    except OSError:
        pass

    try:
        # 远端大小：一次 stat（进度百分比/秒速/ETA 的基准）
        total_bytes = sftp.stat(remote_path).st_size or 0

        with channel_timeout(sftp, timeout_sec):
            remote = sftp.open(remote_path, 'rb')
            try:
                with open(file_path, 'wb') as local:
                    while True:
                        now = time.time()
                        if now > deadline:
                            raise TimeoutError(
                                f'下载超时（超过 {timeout_sec} 秒）')
                        chunk = remote.read(DOWNLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        local.write(chunk)
                        bytes_done += len(chunk)
                        now = time.time()
                        elapsed = now - start
                        # 节流：0.1s 内不重复发 progress；最后一块强制发（100%）
                        if now - last_event < PROGRESS_EVENT_INTERVAL and bytes_done < total_bytes:
                            continue
                        last_event = now
                        speed = bytes_done / elapsed if elapsed > 0 else 0
                        eta = (total_bytes - bytes_done) / speed if speed > 0 else 0
                        yield {
                            'event': 'progress',
                            'percent': min(100, round(bytes_done * 100 / total_bytes)) if total_bytes else 100,
                            'speed': round(speed / 1048576, 2),
                            'eta': round(eta),
                            'filename': filename,
                            'bytes_done': bytes_done,
                            'total_bytes': total_bytes,
                        }
            finally:
                remote.close()
    except GeneratorExit:
        # 客户端中途断开：连接状态不可靠，重建连接
        pool.invalidate(user.id)
        _remove_partial(file_path)
        raise
    except Exception as e:
        pool.invalidate(user.id)
        _remove_partial(file_path)
        yield {
            'event': 'error',
            'message': str(e) or e.__class__.__name__,
        }
        return

    # 下载完成 → 注册（与 download / download_batch 同语义：下载即注册）
    try:
        datafile = _register_file(user, file_path, 'single')
    except Exception as e:
        pool.invalidate(user.id)
        _remove_partial(file_path)
        yield {'event': 'error', 'message': str(e) or e.__class__.__name__}
        return

    yield {
        'event': 'done',
        'filename': os.path.basename(file_path),
        'size': datafile.file_size,
        'datafile_id': datafile.id,
    }


def download_events_to_sse(events):
    """把事件 dict 生成器包装成 ``data: {json}\\n\\n`` 的 SSE 字节流。"""
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"
