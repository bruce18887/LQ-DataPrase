"""D4 `test_sftp_last_visit_writes.py` 的共享夹具（语句形状口径 + 三个调用点的脚手架）。

拆出来只因为**判据文件撞了 600 行闸**（`.claude/CLAUDE.md`：跟踪的 `.py` ≤600，601 即红）：
正文那 20 多条形状用例连同它们的「形状表 + 收敛前参照」叙述必须留在一个文件里好对着读，
能搬走的只有这套与断言无关的工具。**口径解释一律在消费方**（那个模块文档），这里只放机制。

命名：本文件不以 `test` 开头 ⇒ Django discovery 不把它当测试模块收（里面没有用例，
只有 `_RecordBase` 这个没有 test_ 方法的基类），只被 import。同目录先例：
`test/backend/job_cancel_fixtures.py`。
"""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import UserSetting
from apps.sftp.views import SftpViewSet

User = get_user_model()

# 断线续连用的五列（`_record_last_visit` 的写入面）。顺序 = helper 里那个 `fields` **字典**的
# 构造顺序（apps/sftp/views.py 的 `fields['sftp_last_path'] = …` 那五行），也 = 这五列在
# `apps/accounts/models.py` 里的声明顺序。收窄判据**不读**这个常量 —— 它们拿字面量子列表直接比
# SET 子句（`_set_columns(...)`）；它今天唯一的消费方是
# `SerializerWhitelistUnaffectedTests` 那条「这五列不许进序列化器白名单」的准入判据。
LAST_VISIT_FIELDS = ['sftp_last_path', 'sftp_last_config', 'sftp_last_host',
                     'sftp_last_port', 'sftp_last_username']

# 事务簿记动词：生产 autocommit 下 `get_or_create` 的原子块发 BEGIN/COMMIT，
# `TestCase` 把自己的外层事务拆成 SAVEPOINT/RELEASE —— 同一个原子块两种拼写，
# 所以形状判据按「核心动词」比，条数另断（D2 的 `test_atomic_wrapper_costs_two_extra_savepoint_statements`
# 是同一条事实的另一半）。
_BOOKKEEPING = {'BEGIN', 'COMMIT', 'SAVEPOINT', 'RELEASE'}
_TABLE = 'accounts_user_setting'


def _verbs(captured):
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


def _core_verbs(captured):
    return [v for v in _verbs(captured) if v not in _BOOKKEEPING]


def _sqls(captured):
    return [q['sql'] for q in captured.captured_queries]


def _write_sqls(captured):
    return [s for s in _sqls(captured)
            if s.lstrip().upper().startswith(('UPDATE', 'INSERT'))]


def _update_sqls(captured):
    return [s for s in _sqls(captured) if s.lstrip().upper().startswith('UPDATE')]


def _set_columns(sql):
    """取 UPDATE 的 SET 子句列名（按 SQL 顺序）。

    锚点用 Django 自己生成的 `WHERE "accounts_user_setting".`，不是裸 `WHERE`：
    JSON 列的值理论上可能含 “WHERE” 字样，裸切会截断（列名数就会少算）。
    """
    m = re.search(r'\bSET\b(.*?)\bWHERE "%s"\.' % _TABLE, sql, re.S)
    return re.findall(r'"([a-z_]+)"\s*=', m.group(1))


def _insert_columns(sql):
    m = re.search(r'INSERT INTO "%s" \((.*?)\)' % _TABLE, sql, re.S)
    return re.findall(r'"([a-z_]+)"', m.group(1)) if m else []


def _ok_sftp():
    sftp = mock.MagicMock(name='SFTPClient')
    sftp.listdir_attr.return_value = []
    return sftp


def _fresh(pk):
    """复现真实请求的起点：认证通路每次都新建 User 实例 ⇒ settings 实例缓存是冷的。"""
    return User.objects.get(pk=pk)


def _client_for(user):
    """force_authenticate 直接吃**这个实例** ⇒ 请求结束后可在外面读它的 fields_cache。"""
    client = APIClient()
    client.force_authenticate(user)
    return client


class RecordBase(TestCase):
    """三个调用点路径的脚手架（连接池整段替掉，只留 settings 那条写通路）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d4visit', password='pw')
        self.row = UserSetting.objects.create(user=self.user, sftp_last_path='/')

    def browse(self, user, path):
        client = _client_for(user)
        sftp = _ok_sftp()
        with mock.patch.object(SftpViewSet, '_get_connection', return_value=sftp):
            return client.get(f'/api/v1/sftp/list_files/?path={path}')

    def connect(self, user, **payload):
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            return _client_for(user).post('/api/v1/sftp/connect/', payload)

    def record(self, user, **kwargs):
        """直调被测 helper（五个字段都在它的签名里，调用点各只传自己那几个）。"""
        return SftpViewSet()._record_last_visit(user, **kwargs)

    def visitor(self):
        """**测量块外**取的那个 User 实例。

        这次 `SELECT accounts_user` 是夹具自己的（生产里由认证通路每请求新建实例，
        不属于被测的写通路）；把它放进 `CaptureQueriesContext` 就会让形状多读出一条
        SELECT，形状判据也不再等于「这条请求对 settings 干了什么」。
        """
        return _fresh(self.user.pk)

    def reload(self):
        return UserSetting.objects.get(user_id=self.user.pk)
