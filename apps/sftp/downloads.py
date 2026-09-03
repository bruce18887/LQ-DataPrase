"""SFTP 下载 SSE 生成器（单文件 / 目录批量共用）。

背景：旧实现 ``download`` 用 ``sftp.get()`` 一次性下载完整个文件后才返回 JSON。
大文件（GB 级）在前端 30s 的 axios timeout 下必然超时报错；即使放宽 timeout，
前端也看不到任何进度。

本模块把下载改为「分块读取 + SSE 进度事件」：
- 客户端通过 fetch 读流（无 axios 超时）；
- 服务端设置 SFTP channel 的 socket 超时（可配置，默认 600s），传输停滞即抛
  socket.timeout；同时用整体 deadline 兜底（channel 超时对传输期间有数据流动
  的慢速下载不生效，deadline 才能覆盖「永远差一点下完」的场景）；
- 单文件（``download_file_events``）与目录批量（``download_dir_events``）
  进度都基于**实际累计下载字节 / 远端总字节**，分块到达即实时更新
  （0.1s 节流），大文件下载期间进度条不再卡在低百分比。
"""

import json
import logging
import os
import time
from contextlib import contextmanager

from apps.datafiles.views import _register_file

from . import pool
from .local_paths import remove_partial as _remove_partial

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


def iter_remote_chunks(sftp, remote_path, chunk_size=DOWNLOAD_CHUNK_SIZE):
    """逐块读取单个远端文件（256KB），单文件与目录下载共用。

    ``SFTPFile.read`` 内部会按 paramiko 的请求上限拆小请求，返回恰好
    ``chunk_size`` 的首个缓冲区（不足时返回剩余字节），耗尽后返回 b''。
    """
    remote = sftp.open(remote_path, 'rb')
    try:
        while True:
            chunk = remote.read(chunk_size)
            if not chunk:
                return
            yield chunk
    finally:
        remote.close()


def _progress_ratio(done, total):
    """进度百分比（0–100）：total 为 0（远端未报大小）时视为已完成。"""
    if not total:
        return 100
    return min(100, round(done * 100 / total))


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
            with open(file_path, 'wb') as local:
                chunk_iter = iter_remote_chunks(sftp, remote_path)
                while True:
                    # 先查 deadline 再读：传输停滞（一次 read 即超时）也要先
                    # 发出进度事件（最后一次 read 后发的进度不会被吞掉）
                    now = time.time()
                    if now > deadline:
                        raise TimeoutError(
                            f'下载超时（超过 {timeout_sec} 秒）')
                    try:
                        chunk = next(chunk_iter)
                    except StopIteration:
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
                        'percent': _progress_ratio(bytes_done, total_bytes),
                        'speed': round(speed / 1048576, 2),
                        'eta': round(eta),
                        'filename': filename,
                        'bytes_done': bytes_done,
                        'total_bytes': total_bytes,
                    }
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


def download_dir_events(sftp, user, file_list, local_dir, dir_name, timeout_sec):
    """目录批量下载的 SSE 事件生成器（进度按**总下载字节数**计算）。

    ``file_list`` 由视图层 ``_collect_files`` 预收集：
    ``(remote_path, rel_path, remote_size, mtime)``（与旧实现同构）。

    Events：
    - ``{'event': 'progress', 'current', 'total', 'filename', 'rel_path',
        'percent', 'speed', 'eta', 'bytes_done', 'total_bytes'}``
      —— percent = 实际累计下载字节 / 远端文件大小总和；**分块到达即更新**
      （0.1s 节流 + 每文件至少一次补偿事件），大文件下载期间进度条实时前进，
      不会再卡在低百分比。
    - ``{'event': 'error', 'filename', 'message'}`` —— 单文件失败：清理半截
      文件后继续下一个文件（与旧行为一致）。
    - ``{'event': 'done', 'dir_name', 'file_count', 'total', 'saved_dir'}``

    超时（``DirDownloadTimeout``）是全局性的：中止整个目录下载并清理当前
    半截文件；客户端断开（GeneratorExit）时同样清理并 invalidate 连接。
    """
    total_bytes = sum(size for _, _, size, _ in file_list)
    total_files = len(file_list)
    bytes_done = 0
    success_count = 0
    start_time = time.time()
    deadline = start_time + timeout_sec
    last_event = 0.0
    current_partial = None

    def progress_event(index, rel_path):
        elapsed = time.time() - start_time
        speed = bytes_done / elapsed if elapsed > 0 else 0
        eta = (total_bytes - bytes_done) / speed if speed > 0 else 0
        return {
            'event': 'progress',
            'current': index + 1,
            'total': total_files,
            'filename': os.path.basename(rel_path),
            'rel_path': rel_path,
            'percent': _progress_ratio(bytes_done, total_bytes),
            'speed': round(speed / 1048576, 2),
            'eta': round(eta),
            'bytes_done': bytes_done,
            'total_bytes': total_bytes,
        }

    try:
        with channel_timeout(sftp, timeout_sec):
            for index, (remote_fp, rel_path, _size, _mtime) in enumerate(file_list):
                rel_path_os = rel_path.replace('/', os.sep)
                local_file_path = os.path.join(local_dir, rel_path_os)
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                current_partial = local_file_path
                pending = False
                try:
                    if time.time() > deadline:
                        raise DirDownloadTimeout(
                            f'目录下载超时（超过 {timeout_sec} 秒）')
                    with open(local_file_path, 'wb') as local:
                        chunk_iter = iter_remote_chunks(sftp, remote_fp)
                        while True:
                            # 先查 deadline 再读（与单文件下载一致）
                            if time.time() > deadline:
                                raise DirDownloadTimeout(
                                    f'目录下载超时（超过 {timeout_sec} 秒）')
                            try:
                                chunk = next(chunk_iter)
                            except StopIteration:
                                break
                            local.write(chunk)
                            bytes_done += len(chunk)
                            pending = True
                            now = time.time()
                            if now - last_event >= PROGRESS_EVENT_INTERVAL:
                                yield progress_event(index, rel_path)
                                pending = False
                                last_event = now
                    # 文件已完整写入并关闭：此后的 yield（补偿事件）若客户端
                    # 断开，不应再清理该已完成文件（外层 handler 依赖
                    # current_partial 判断待清理的半截文件）
                    current_partial = None
                    # 小文件整体读完可能不足 0.1s：补偿发最后一个事件，
                    # 保证「每文件至少一次」更新（文件计数/百分比的最终值）
                    if pending:
                        yield progress_event(index, rel_path)
                    success_count += 1
                    # 下载即注册（与单文件/旧目录下载同语义）
                    try:
                        _register_file(user, local_file_path, 'batch', dir_name)
                    except Exception as re:
                        logger.warning(
                            f"Auto-register failed for {local_file_path}: {re}")
                except DirDownloadTimeout:
                    raise
                except Exception as e:
                    # 单文件失败：清理半截文件 + 报错，继续下一文件
                    logger.warning(f"SFTP download failed for {remote_fp}: {e}")
                    _remove_partial(local_file_path)
                    yield {
                        'event': 'error',
                        'filename': os.path.basename(rel_path),
                        'message': str(e),
                    }
                # 本文件已收尾（成功或单文件错误已处理）：清除残留引用
                current_partial = None
    except DirDownloadTimeout as e:
        if current_partial is not None:
            _remove_partial(current_partial)
        pool.invalidate(user.id)
        yield {'event': 'error', 'filename': '', 'message': str(e)}
        return
    except GeneratorExit:
        # 客户端中途断开：连接状态不可靠，重建连接并清理半截文件
        if current_partial is not None:
            _remove_partial(current_partial)
        pool.invalidate(user.id)
        raise
    except Exception:
        if current_partial is not None:
            _remove_partial(current_partial)
        pool.invalidate(user.id)
        raise

    yield {
        'event': 'done',
        'dir_name': dir_name,
        'file_count': success_count,
        'total': total_files,
        'saved_dir': local_dir,
    }


def download_events_to_sse(events):
    """把事件 dict 生成器包装成 ``data: {json}\\n\\n`` 的 SSE 字节流。"""
    for event in events:
        yield f"data: {json.dumps(event)}\n\n"
