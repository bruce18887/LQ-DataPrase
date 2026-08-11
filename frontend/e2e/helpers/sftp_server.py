"""本地 paramiko SFTP 服务器（e2e 专用）。

接受任意账号/密码，root 指向 --root 指定目录，监听 127.0.0.1 随机端口。
stdout 首行打印 {"host": ..., "port": ...} JSON，供 sftpServer.ts 解析。
用法: python sftp_server.py --root <dir>

注意：paramiko.Transport 传入 (host, port) 元组是「客户端」构造（会尝试连接，
Windows 下抛 WinError 10049）；服务端必须 bind 监听 socket 后把连接对象交给
Transport。accept 循环参考 paramiko 官方 interactive_sftp_server 示例。
"""

import argparse
import json
import os
import socket
import time

import paramiko

from paramiko.sftp_server import SFTPServer


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

    def _real(self, path):
        p = os.path.normpath(path.strip('/').replace('/', os.sep))
        return os.path.join(self.ROOT, p) if p else self.ROOT

    def list_folder(self, path):
        try:
            out = []
            real = self._real(path)
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    args = ap.parse_args()
    FS.ROOT = os.path.abspath(args.root)

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
