"""内存版假 paramiko SFTPClient：给搜索的纯逻辑测试提供一棵可遍历的树。

真服务器测试（含 paramiko 并行正确性）在 apps/sftp/tests_search.py，它跑
frontend/e2e/helpers/sftp_server.py。两者分工不同，别互相顶替。
"""
import fnmatch
import posixpath
import stat
from dataclasses import dataclass
from typing import Dict, List, Optional

import paramiko


@dataclass
class FakeAttr:
    filename: str
    st_mode: int
    st_size: int
    st_mtime: int


class FakeRemoteFile:
    """支持 read(n) / readline() / prefetch / close，够扫描与列值读取用。"""

    def __init__(self, content: bytes):
        self.content = content
        self.pos = 0
        self.prefetched = False
        self.closed = False

    def prefetch(self, file_size=None, max_concurrent_requests=None):
        self.prefetched = True

    def read(self, n: int = -1) -> bytes:
        if self.pos >= len(self.content):
            return b''
        if n is None or n < 0:
            chunk = self.content[self.pos:]
        else:
            chunk = self.content[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def readline(self) -> bytes:
        nl = self.content.find(b'\n', self.pos)
        if nl == -1:
            line = self.content[self.pos:]
            self.pos = len(self.content)
        else:
            line = self.content[self.pos:nl + 1]
            self.pos = nl + 1
        return line

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeSftp:
    """files: {绝对路径: bytes}；unreadable: 匹中这些 glob 的目录 listdir 抛错。

    broken=True 时一切操作抛 SFTPError，用于验「连接脏了要换」那条路径。
    """

    def __init__(self, files: Dict[str, bytes],
                 unreadable: Optional[List[str]] = None,
                 mtimes: Optional[Dict[str, int]] = None,
                 broken: bool = False):
        self.files = dict(files)
        self.unreadable = unreadable or []
        self.mtimes = mtimes or {}
        self.broken = broken
        self.listdir_calls: List[str] = []
        self.open_count = 0

    def _children(self, path: str):
        norm = posixpath.normpath(path)
        prefix = '' if norm == '/' else norm + '/'
        dirs, files = set(), set()
        for full in self.files:
            if norm != '/' and not full.startswith(prefix):
                continue
            rest = full[len(prefix):] if norm != '/' else full.lstrip('/')
            if not rest:
                continue
            if '/' in rest:
                dirs.add(rest.split('/', 1)[0])
            else:
                files.add(rest)
        return dirs, files

    def listdir_attr(self, path: str) -> List[FakeAttr]:
        if self.broken:
            raise paramiko.SFTPError('Garbage packet received')
        for pattern in self.unreadable:
            if fnmatch.fnmatch(path, pattern):
                raise IOError(f'Permission denied: {path}')
        self.listdir_calls.append(path)
        norm = posixpath.normpath(path)
        dirs, files = self._children(norm)
        out = [FakeAttr(d, stat.S_IFDIR | 0o755, 0, 1_700_000_000)
               for d in sorted(dirs)]
        for f in sorted(files):
            full = posixpath.join(norm, f)
            out.append(FakeAttr(f, stat.S_IFREG | 0o644,
                                len(self.files[full]),
                                self.mtimes.get(full, 1_700_000_000)))
        return out

    def stat(self, path: str) -> FakeAttr:
        if self.broken:
            raise paramiko.SFTPError('Garbage packet received')
        content = self.files.get(path)
        if content is None:
            raise IOError(f'No such file: {path}')
        return FakeAttr(posixpath.basename(path), stat.S_IFREG | 0o644,
                        len(content), self.mtimes.get(path, 1_700_000_000))

    def realpath(self, path: str) -> str:
        return posixpath.normpath(path)

    def open(self, path: str, mode: str = 'rb', bufsize: int = -1):
        if self.broken:
            raise paramiko.SFTPError('Garbage packet received')
        if path not in self.files:
            raise IOError(f'No such file: {path}')
        self.open_count += 1
        return FakeRemoteFile(self.files[path])

    def get_channel(self):
        return None


class FakeSession:
    """SearchSession 的替身：所有借出都指向同一个 FakeSftp。"""

    def __init__(self, sftp, size: int = 1):
        self.sftp = sftp
        self._item = (object(), sftp)
        self.borrow_count = 0
        self.give_back_count = 0
        self._size = size

    def open_all(self):
        return self._size

    @property
    def size(self):
        return self._size

    def borrow(self, timeout=None):
        self.borrow_count += 1
        return self._item

    def give_back(self, item, *, broken: bool = False):
        self.give_back_count += 1

    def close_all(self):
        pass


def sample_tree() -> Dict[str, bytes]:
    """贯穿各测试的标准树：批次目录 × 同格式多文件 + 汇总 + 非 CSV + 深层 + GBK 中文。"""
    return {
        '/data/batch1/RT_001.csv':
            b'[HEADER]\r\nTestFile,D:\\stdf\\lotA_w01.stdf\r\n'
            b'StartTime,2026-09-01 08:12:33,\r\n[DATA]\r\n'
            b'SN,ShadowReg2\r\n1,0.42\r\n',
        '/data/batch1/RT_002.csv': b'[DATA]\r\nSN,ShadowReg2\r\n2,0.43\r\n',
        '/data/batch1/FT_001.csv': b'[DATA]\r\nSN,Vcc\r\n1,3\r\n',
        '/data/batch1/Sum_total.csv': b'summary,not,data\n',
        '/data/batch1/notes.txt': b'not a csv at all ShadowReg2\n',
        '/data/batch1/Deep/RT_003.csv': b'[DATA]\r\nSN,ShadowReg2\r\n3,0.44\r\n',
        '/data/batch2/RT_010.csv':
            '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk'),
        '/data/backup/RT_999.csv': b'[DATA]\r\nSN,ShadowReg2\r\n9,0.9\r\n',
        '/data/.hidden/RT_998.csv': b'[DATA]\r\nSN,ShadowReg2\r\n8,0.8\r\n',
    }
