"""SFTP 本地落盘路径工具：重名碰撞后缀 + 半截文件清理。

为什么抽出来：视图里的 ``sftp.get`` 路径与 SSE 路径（``downloads.py``）此前各写
一份碰撞/清理逻辑，而 ``_batch_download_parse`` 两者都没有 → 重名时覆盖既有文件
并注册出指向同一路径的重复 DB 行，失败时还会留下未注册的孤儿残片。统一到这里，
两套下载语义才一致。
"""

import logging
import os
import time

logger = logging.getLogger(__name__)


def resolve_local_path(upload_dir, filename):
    """返回 ``upload_dir`` 下不与既有文件冲突的落地路径。

    沿用 ``download`` / ``download_batch`` / ``_single_download_parse`` 原有的
    时间戳后缀策略（``name_<ts><ext>``）；同一秒内的第二次碰撞再追加序号——
    批量下载里 ``/a/dup.csv`` 与 ``/b/dup.csv`` 就会撞到同一秒。
    """
    candidate = os.path.join(upload_dir, filename)
    if not os.path.exists(candidate):
        return candidate

    name, ext = os.path.splitext(filename)
    ts = int(time.time())
    candidate = os.path.join(upload_dir, f'{name}_{ts}{ext}')
    seq = 1
    while os.path.exists(candidate):
        candidate = os.path.join(upload_dir, f'{name}_{ts}_{seq}{ext}')
        seq += 1
    return candidate


def remove_partial(file_path):
    """删除下载失败留下的半截文件（绝不让未注册的残片留在用户目录）。

    best-effort：清理失败只记日志，绝不盖掉真正的下载异常。
    """
    if not file_path:
        return
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning('Failed to remove partial download: %s', file_path,
                       exc_info=True)
