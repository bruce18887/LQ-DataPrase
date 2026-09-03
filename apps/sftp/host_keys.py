"""SFTP 主机密钥校验（TOFU：trust-on-first-use）。

背景：``views._connect_impl`` 与 ``pool._build_entry`` 原本都是
``paramiko.Transport((host, port))`` 之后直接 ``transport.connect(username=...,
password=...)`` —— 等价于无条件接受任意主机公钥，中间人可冒充服务器骗取明文凭据。

方案：首次连接把主机公钥记入**用户数据目录**下的 known_hosts 文件
（``MEDIA_ROOT/sftp/known_hosts.json``，因此不需要任何 model 迁移）；后续连接把
已记录的公钥作为 ``hostkey`` 交给 paramiko —— ``Transport.connect`` 在
``auth_password`` **之前**比对公钥，不匹配即抛异常，凭据不会发往可疑主机。

逃生开关：``settings.SFTP_HOST_KEY_CHECK = 'off'`` 回到旧行为（不记录、不校验）。
服务器确实更换过主机密钥时，用 ``forget(host, port)``（或直接删记录文件里的那一
行）清掉旧记录即可重连。
"""

import base64
import hashlib
import json
import logging
import os

import paramiko
from django.conf import settings

logger = logging.getLogger(__name__)

CHECK_SETTING = 'SFTP_HOST_KEY_CHECK'
DEFAULT_CHECK_MODE = 'tofu'
OFF_MODE = 'off'

# known_hosts 相对 MEDIA_ROOT 的位置：用户数据目录，随备份一起走，不进代码库。
STORE_RELPATH = os.path.join('sftp', 'known_hosts.json')


# SSH 公钥类型 → paramiko 密钥类（用于把 known_hosts 记录重建成可比对的对象）。
# 用 getattr 探测：paramiko 5.x 已移除 DSSKey（DSA 弃用），旧版本上仍可支持。
def _supported_key_classes():
    classes = {}
    for key_type, attr in (('ssh-rsa', 'RSAKey'),
                           ('ssh-ed25519', 'Ed25519Key'),
                           ('ssh-dss', 'DSSKey')):
        cls = getattr(paramiko, attr, None)
        if cls is not None:
            classes[key_type] = cls
    return classes


_KEY_CLASSES = _supported_key_classes()


class HostKeyMismatchError(paramiko.SSHException):
    """服务器呈现的主机公钥与已信任记录不一致（可能是中间人攻击）。"""


def check_mode():
    """当前校验模式：``'tofu'``（默认）或 ``'off'``（逃生开关）。"""
    return str(getattr(settings, CHECK_SETTING, DEFAULT_CHECK_MODE)).lower()


def known_hosts_path():
    """known_hosts 文件绝对路径（运行时读 settings，兼容 override_settings）。"""
    return os.path.join(settings.MEDIA_ROOT, STORE_RELPATH)


def _host_id(host, port):
    try:
        return f'{host}:{int(port)}'
    except (TypeError, ValueError):
        return f'{host}:{port}'


def _key_class(key_type):
    cls = _KEY_CLASSES.get(key_type)
    if cls is not None:
        return cls
    if isinstance(key_type, str) and key_type.startswith('ecdsa-sha2-'):
        return getattr(paramiko, 'ECDSAKey', None)
    return None


def fingerprint(key):
    """``SHA256:<base64>`` 指纹（与 ssh-keygen 同格式）；无法计算返回 ``None``。

    测试替身（MagicMock）没有真实公钥字节 → 返回 None，调用方据此跳过校验/记录，
    既不阻断连接也不写脏数据。
    """
    try:
        blob = key.asbytes()
    except Exception:
        logger.warning('Cannot read SFTP host key bytes; skipping fingerprint',
                       exc_info=True)
        return None
    if not isinstance(blob, (bytes, bytearray)) or not blob:
        return None
    digest = hashlib.sha256(bytes(blob)).digest()
    return 'SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('=')


def _load():
    path = known_hosts_path()
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning('Unreadable SFTP known_hosts %s; treating as empty', path,
                       exc_info=True)
        return {}
    return data if isinstance(data, dict) else {}


def _save(entries):
    """原子写（先写 .tmp 再 replace），失败只记日志并返回 False。"""
    path = known_hosts_path()
    tmp = f'{path}.tmp'
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        logger.warning('Failed to write SFTP known_hosts %s', path, exc_info=True)
        return False
    return True


def lookup_fingerprint(host, port):
    """已记录的主机密钥指纹；无记录返回 ``None``。"""
    entry = _load().get(_host_id(host, port))
    if not isinstance(entry, dict):
        return None
    fp = entry.get('fingerprint')
    return fp if isinstance(fp, str) and fp else None


def lookup(host, port):
    """把已记录的公钥重建成 paramiko key 对象；无记录/不可重建返回 ``None``。"""
    entry = _load().get(_host_id(host, port))
    if not isinstance(entry, dict):
        return None
    key_cls = _key_class(entry.get('type'))
    blob = entry.get('key')
    if key_cls is None or not isinstance(blob, str) or not blob:
        return None
    try:
        return key_cls(data=base64.b64decode(blob))
    except Exception:
        logger.warning('Cannot rebuild pinned SFTP host key for %s',
                       _host_id(host, port), exc_info=True)
        return None


def pin(host, port, key):
    """记录主机公钥（TOFU 的「首次使用」）。无法计算指纹时返回 ``False``。"""
    fp = fingerprint(key)
    if fp is None:
        return False
    try:
        key_type = key.get_name()
        blob = base64.b64encode(key.asbytes()).decode('ascii')
    except Exception:
        logger.warning('Cannot serialize SFTP host key for %s',
                       _host_id(host, port), exc_info=True)
        return False
    entries = _load()
    entries[_host_id(host, port)] = {
        'type': key_type, 'key': blob, 'fingerprint': fp,
    }
    return _save(entries)


def forget(host, port):
    """删除某主机的记录（服务器换过主机密钥时用）。原本无记录返回 ``False``。"""
    entries = _load()
    if entries.pop(_host_id(host, port), None) is None:
        return False
    return _save(entries)


def open_verified_transport(host, port, username, password):
    """建立**已校验主机密钥**的 paramiko ``Transport``（调用方负责 close）。

    - 已有记录：把公钥交给 ``Transport.connect(hostkey=...)``；paramiko 在认证
      之前比对，不匹配抛 ``HostKeyMismatchError``，凭据不会发往可疑主机；
    - 无记录：正常连接后 best-effort 记录公钥（首次使用即信任）。
    """
    verify = check_mode() != OFF_MODE
    pinned = lookup(host, port) if verify else None
    transport = paramiko.Transport((host, port))

    if pinned is not None:
        try:
            transport.connect(hostkey=pinned, username=username, password=password)
        except paramiko.SSHException as exc:
            if 'host key' not in str(exc).lower():
                raise          # 认证失败等：不误报成主机密钥问题
            raise HostKeyMismatchError(
                f'SFTP 主机密钥不匹配：{host}:{port} 呈现的主机公钥与已信任记录不一致'
                f'（已信任指纹 {lookup_fingerprint(host, port)}，记录文件 '
                f'{known_hosts_path()}）。为防中间人窃取凭据已拒绝连接；'
                f'若服务器确实更换过主机密钥，请删除该记录后重连。'
            ) from exc
        return transport

    transport.connect(username=username, password=password)
    if verify:
        try:
            if not pin(host, port, transport.get_remote_server_key()):
                logger.warning(
                    'SFTP host key for %s:%s could not be pinned; later '
                    'connections to it stay unverified', host, port)
        except Exception:
            logger.warning('Failed to pin SFTP host key for %s:%s', host, port,
                           exc_info=True)
    return transport
