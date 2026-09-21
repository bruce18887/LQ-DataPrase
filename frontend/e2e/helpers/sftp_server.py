"""本地 paramiko SFTP 服务器（e2e 专用）。

接受任意账号/密码，root 指向 --root 指定目录，监听 127.0.0.1 随机端口。
stdout 首行打印 {"host": ..., "port": ...} JSON，供 sftpServer.ts 解析。
用法: python sftp_server.py --root <dir> [--fixture]

--fixture 在 --root 下造一棵搜索集成测试用的文件树（见 write_fixture_tree）；
**不带这个开关时行为一字不变**，故现有 e2e 用例不受影响。协议逻辑（FS/Server/
main 的 accept 循环）不因 --fixture 而改变。

注意：paramiko.Transport 传入 (host, port) 元组是「客户端」构造（会尝试连接，
Windows 下抛 WinError 10049）；服务端必须 bind 监听 socket 后把连接对象交给
Transport。accept 循环参考 paramiko 官方 interactive_sftp_server 示例。
"""

import argparse
import errno
import json
import os
import posixpath
import socket
import time

import paramiko

from paramiko.sftp_server import SFTPServer

# --fixture 造的「不可读目录」靠这个标记文件表达（见 FS._deny_unreadable_dirs）。
DENY_LIST_MARKER = '.no-access'


class Server(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return 'password'

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_subsystem_request(self, channel, name):
        # paramiko 只在此处回调，不会自动启动 handler —— 需自行从
        # transport._get_subsystem_handler 取出注册的 handler 类并 start
        # （参考官方 interactive_sftp_server 示例）。
        if name != 'sftp':
            return False
        transport = channel.get_transport()
        handler_class, args, kwargs = transport._get_subsystem_handler(name)
        if handler_class is None:
            return False
        handler_class(channel, name, transport, *args, **kwargs).start()
        return True


class FHandle(paramiko.SFTPHandle):
    def stat(self):
        try:
            return paramiko.SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def chattr(self, attr):
        return paramiko.SFTP_OK


class FS(paramiko.SFTPServerInterface):
    ROOT = None
    # 只有 --fixture 模式会把它设成一个标记文件名：目录里含这个文件就列不出来（EACCES）。
    # 默认 None ⇒ 这条判定恒不生效，非 fixture 的现有 e2e 行为一字不变。
    DENY_LIST_MARKER = None

    def _real(self, path):
        p = os.path.normpath(path.strip('/').replace('/', os.sep))
        return os.path.join(self.ROOT, p) if p else self.ROOT

    def _deny_unreadable_dirs(self, real):
        """含标记文件的目录报 EACCES：验 walker 的 error{scope:"dir"} 单目录隔离。

        Windows 的 chmod 只管只读位、夺不掉列目录的能力，NTFS ACL 又要外部命令且要权限，
        所以「服务端不可读的目录」只能由服务端自己拒不服务 —— 用文件树里的一个标记文件
        来表达，跨平台确定，且不带 --fixture 时永远不会触发。
        """
        if self.DENY_LIST_MARKER and os.path.isdir(real):
            if os.path.exists(os.path.join(real, self.DENY_LIST_MARKER)):
                raise PermissionError(errno.EACCES, 'Permission denied')

    def list_folder(self, path):
        try:
            out = []
            real = self._real(path)
            self._deny_unreadable_dirs(real)
            for name in os.listdir(real):
                attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(real, name)))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def lstat(self, path):
        return self.stat(path)

    def open(self, path, flags, attr):
        try:
            f = open(self._real(path), 'rb')
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        h = FHandle(flags)
        h.readfile = f
        h.writefile = f
        return h

    def canonicalize(self, path):
        """realpath/normalize 的返回：按 posix 归一，与 ``_real`` 同一口径。

        paramiko 的默认实现走 ``os.path.normpath``，在 Windows 上就是 ntpath ——
        ``ntpath.normpath('/' + '/batch1')`` 得 ``'\\\\batch1'``，它再把反斜杠换成斜杠
        就成了 ``//batch1``。客户端于是拿到双斜杠路径（``posixpath.normpath`` 恰好
        原样保留前导双斜杠，救不回来）。这台服务器映射的是「--root 即 /」，
        归一本来就该是 posix 的。
        """
        stripped = path.strip('/')
        return posixpath.normpath('/' + stripped) if stripped else '/'


def write_fixture_tree(root: str) -> None:
    """与 ``test/backend/sftp_fake.sample_tree()`` 同形的真文件树（Task 11B 用）。

    树里每一项都为一条断言而存在：多层目录（深度档）、同目录多份同格式 CSV（并行）、
    GBK 编码的中文测试项（编码探测在真 read() 分块下）、``Sum_*.csv`` 与 ``notes.txt``
    （``data_files_only`` 排除，两者都刻意含查询串，否则「被排除」是空转）、
    ``NoAccess/``（服务端列不出来，验 ``error{scope:"dir"}`` 隔离）、
    一个 20 万行的 ``BIG.csv``（跨 chunk 的行号计数与进度），以及 ``batch1/many/`` 下
    200 份小文件（把并行扫描的借还次数推到能抓出偶发协议竞态的量级）。
    """
    files = {
        'batch1/RT_1.csv': b'[HEADER]\r\nTestFile,D:\\stdf\\lotA_w01.stdf\r\n'
                           b'StartTime,2026-09-01 08:12:33,\r\n[DATA]\r\n'
                           b'SN,ShadowReg2\r\n1,0.42\r\n',
        'batch1/RT_2.csv': b'[DATA]\r\nSN,ShadowReg2\r\n2,0.43\r\n',
        'batch1/FT_1.csv': b'[DATA]\r\nSN,Vcc\r\n1,3\r\n',
        'batch1/Sum_total.csv': b'summary,ShadowReg2,data\n',
        'batch1/notes.txt': b'not a csv ShadowReg2\n',
        'batch1/Deep/RT_3.csv': b'[DATA]\r\nSN,ShadowReg2\r\n3,0.44\r\n',
        'batch2/RT_10.csv': '测试项,值\r\n漏电电流,0.5\r\n'.encode('gbk'),
        'backup/RT_9.csv': b'[DATA]\r\nSN,ShadowReg2\r\n9,0.9\r\n',
        '.hidden/RT_8.csv': b'[DATA]\r\nSN,ShadowReg2\r\n8,0.8\r\n',
        'NoAccess/RT_7.csv': b'[DATA]\r\nSN,ShadowReg2\r\n7,0.7\r\n',
        f'NoAccess/{DENY_LIST_MARKER}': b'',
    }
    for rel, content in files.items():
        full = os.path.join(root, *rel.split('/'))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'wb') as fh:
            fh.write(content)
    # 一个 20 万行文件：验大文件扫描与行号计数在真 read() 下也对
    big = os.path.join(root, 'batch1', 'BIG.csv')
    with open(big, 'wb') as fh:
        fh.write(b'[DATA]\r\nSN,ShadowReg2\r\n')
        for i in range(200_000):
            fh.write(b'%d,0.%d\r\n' % (i, i % 97))
        fh.write(b'target,ShadowReg2\r\n')
    # 200 份小文件（一半含查询串）：并行一致要建立在几百次「借连接 → open → read →
    # 还」的 interleaving 上。9 个文件的量级抓不到偶发协议竞态，只会抓到「共用一条
    # channel」那种必然炸的写法 —— 这一批才是把前者也变成必然炸的那把杠杆。
    many = os.path.join(root, 'batch1', 'many')
    os.makedirs(many, exist_ok=True)
    for i in range(200):
        needle = b'SN,ShadowReg2' if i % 2 == 0 else b'SN,Vcc'
        with open(os.path.join(many, 'RT_%d.csv' % (100 + i)), 'wb') as fh:
            fh.write(b'[DATA]\r\n%s\r\n%d,0.%d\r\n' % (needle, i, i % 97))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--fixture', action='store_true',
                    help='在 --root 下造一棵搜索集成测试用的文件树（默认不造）')
    args = ap.parse_args()
    FS.ROOT = os.path.abspath(args.root)
    if args.fixture:
        FS.DENY_LIST_MARKER = DENY_LIST_MARKER
        write_fixture_tree(args.root)

    host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)

    print(json.dumps({
        'host': '127.0.0.1',
        'port': listener.getsockname()[1],
    }), flush=True)

    while True:
        conn, _addr = listener.accept()
        try:
            transport = paramiko.Transport(conn)
            transport.add_server_key(host_key)
            transport.set_subsystem_handler('sftp', SFTPServer, FS)
            transport.start_server(server=Server())
        except Exception:
            try:
                conn.close()
            except OSError:
                pass


if __name__ == '__main__':
    main()
