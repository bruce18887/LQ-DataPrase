"""用户名能否安全地用作数据目录名（账号名会拼进 MEDIA_ROOT 路径）。"""
import os

UNSAFE_USERNAMES = ('', '.', '..')


def is_safe_username(username):
    """用户名能否作为单个路径段使用。

    Django 的 ``UnicodeUsernameValidator`` 接受 ``..`` / ``.`` 作为完整用户名；
    把它们拼进 ``MEDIA_ROOT/data/<username>`` 会归一化到 ``MEDIA_ROOT`` 或
    ``MEDIA_ROOT/data``。上传路径与占用扫描共用这一份判据。
    """
    name = str(username)
    return not (
        name in UNSAFE_USERNAMES
        or os.sep in name
        or (os.altsep and os.altsep in name)
    )
