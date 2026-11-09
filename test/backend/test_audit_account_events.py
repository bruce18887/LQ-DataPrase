"""账号写路径与存储路径的审计接线（spec §5.2 触发点表剩下那 7 个码 / §5.3 detail 约定）。

与本仓其余审计判据的分工：`test_audit_writer.py` 量写入器本身（快照、截断、异常咽掉、
语句形状），`test_audit_login_events.py` 量登录族那 3 个码，本文件只管**剩下 7 个码接在
哪个动作上、落的那一行内容对不对**。五条口径：

1. 行数整表钉：先按 `id` 正序（= 写入顺序）把整表读出来数行数，再逐行整值比对
   `_ROW_FIELDS` 那七列（`ip_address` 在里面，`id`/`created_at` 不在，理由见那个元组上方）。
   不按位置取「最新一条」——那种写法会放过「同一次动作多写一笔」与「把别的事件码也写成
   这一次」。
2. `detail` 按 spec §5.3 钉**整个字典**，不逐键比：键集合本身就是契约，多出键也算漂。
   spec 没固定形状的（`account_unlocked` / `password_changed`）钉成 `{}`，同样整值比。
   `changed_fields` 额外有一条专门钉顺序：validated_data 的键序是序列化器的**可写字段声明序**
   （DRF `Serializer.to_internal_value` 遍历 `self._writable_fields`），role/is_active
   那对正好与字母序相反。
   另有一条钉语义而不是钉格式：`changed_fields` 是「这次请求**带了**哪些可记字段」，
   不是「哪些字段的值真的变了」——重发同一个值也算 changed（`_guard_lockout` 与
   `serializer.save()` 都只看请求带了什么，审计跟着它们走才是同一条时间线）。
3. 被拒绝的请求不许留痕：`_guard_lockout` 或序列化器校验抛错时审计表必须仍是空的。
   一次没发生过的改动留下记录 = 假记录，事后取证会被它误导，比缺记录更糟。
   两条路各一条用例，是因为**失守的位置**不同：守卫那两条（`perform_update` /
   `perform_destroy`）的 400 出在 `_guard_lockout` 里，`serializer.save()` 还没跑；
   序列化器那几条的 400 出在 `is_valid(raise_exception=True)`，视图函数体一行都没进。
   两处都是「审计写在业务写之后」，所以两种漏法都得各自钉一遍才分得清哪道闸先失守。
4. 口令绝不进 detail，键名与值一起看（`str(detail)` 里连 `password` 这个词都不许出现）。
   四条写路径里只有 update 那条把变更集交给白名单，而 `UserSerializer` 现在**没有**可写
   口令字段 —— 白名单在这条路上此刻挡不到任何东西，所以
   `test_password_never_reaches_user_updated_detail` 自己造一个带可写 `password` 的序列化器
   subclass 把形状顶出来。另外三条（create / reset / change）的序列化器**是**有可写口令字段
   的（`UserCreateSerializer.password`、`AdminResetPasswordSerializer.new_password`、
   `PasswordChangeSerializer` 的那三个），但它们的 `detail` 是视图里手搓的字面量、
   根本不经过白名单 —— 那三条靠构造护住，不靠白名单。别把这条判据读成
   「白名单罩住了全部写路径」，也别读成「视图里已经在记口令」。
5. 还有一条**语句形状**判据（`test_unlock_writes_only_the_two_lockout_columns`）：解锁那处
   从整行 `save()` 换成 `update_fields` 窄写，在返回体与审计行上都不可区分，只能看 UPDATE
   的 SET 列表。它不属于上面四条口径，是本文件唯一一处按 SQL 内容下的判据。
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test import TestCase  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework import serializers as drf_serializers  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import AuditEvent, User  # noqa: E402
from apps.accounts.serializers import UserSerializer  # noqa: E402
from apps.accounts.views import UserManagementViewSet  # noqa: E402

ADMIN_PW = 'x-admin-pass-123'
TARGET_PW = 'x-target-pass-123'
NEW_PW = 'x-brand-new-pass-123'

USERS_URL = '/api/v1/auth/users/'
CHANGE_URL = '/api/v1/auth/change-password/'
PATHS_URL = '/api/v1/system/paths/'

# 一行审计里判据要看的全部列：整值比对的形状由它决定，加列要同时改本元组与每条用例。
# 不参与的两列各有理由：`id`/`created_at` 同一次跑里会变、钉死等于制造 flake；
# `ip_address` 反而**参与**（写入器侧只证「给了合法 IP 就存下来」，端点侧要证的是
# 接线时真的把 request 传进了 `record()` —— 传了 `None` 或另造一个 Request 都会漏掉 IP）。
_ROW_FIELDS = ('event', 'actor_id', 'actor_username', 'target_id',
               'target_username', 'ip_address', 'detail')

# APIClient 不设 X-Forwarded-For，`REMOTE_ADDR` 恒是这个值（Django test client 的默认）。
CLIENT_IP = '127.0.0.1'


def _rows():
    return list(AuditEvent.objects.order_by('id').values(*_ROW_FIELDS))


def _user_update_set_columns(captured):
    """每条 `accounts_user` 的 UPDATE，取其 SET 里被写的列名（按 SQL 出现顺序）。

    锚点用 Django 自己生成的 `WHERE "accounts_user".`，不是裸 `WHERE`：JSON 列的值理论上
    可能含 “WHERE” 字样，裸切会截断、列名就会少算。取法与 `test_accounts_write_paths.py`
    里的同名助手一致，只是锚的表不同（那边钉 `accounts_user_setting`，这边钉 `accounts_user`），
    所以两份不合并 —— 合并要把锚参数化，两边各自的注释就都对不上号了。
    子串判定用带后引号的 `"accounts_user"`，因此不会把 `"accounts_user_setting"` 也算进来。
    """
    result = []
    for sql in (q['sql'] for q in captured.captured_queries):
        if not sql.lstrip().upper().startswith('UPDATE') or '"accounts_user"' not in sql:
            continue
        match = re.search(r'\bSET\b(.*?)\bWHERE "accounts_user"\.', sql, re.S)
        result.append(re.findall(r'"([a-z_]+)"\s*=', match.group(1)))
    return result


class _WritablePasswordSerializer(UserSerializer):
    """判据专用：把「将来有人给管理端序列化器加一个可写口令字段」这个形状造出来。

    白名单 `AUDITABLE_FIELDS` 是它和审计 detail 之间唯一的一道闸；不这么顶的话，
    白名单在真实序列化器上永远跑不出差异（`UserSerializer` 现在没有可写 password）。
    """

    password = drf_serializers.CharField(required=False, write_only=True)

    class Meta(UserSerializer.Meta):
        # DRF 要求显式声明的字段必须出现在 fields 里（否则直接 AssertionError），
        # 所以把母类的字段表抄过来再加这一列；write_only 保证它不进响应体。
        fields = UserSerializer.Meta.fields + ['password']


class AccountEventsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('ev-admin', 'a@localhost', ADMIN_PW)
        self.target = User.objects.create_user('ev-target', 't@localhost', TARGET_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _only_row(self):
        rows = _rows()
        self.assertEqual(len(rows), 1, f'该动作应恰好落一行审计，实测 {rows}')
        return rows[0]

    def test_user_created_records_role_and_active(self):
        resp = self.client.post(USERS_URL, {'username': 'ev-new', 'password': NEW_PW,
                                            'role': 'user'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        created = User.objects.get(username='ev-new')
        self.assertEqual(self._only_row(), {
            'event': 'user_created',
            'actor_id': self.admin.pk,
            'actor_username': 'ev-admin',
            'target_id': created.pk,
            'target_username': 'ev-new',
            'ip_address': CLIENT_IP,
            'detail': {'role': 'user', 'is_active': True},
        })

    def test_user_updated_lists_only_allowlisted_changed_fields(self):
        resp = self.client.put(f'{USERS_URL}{self.target.pk}/',
                               {'display_name': 'Renamed', 'is_active': False},
                               format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = self._only_row()
        self.assertEqual(row, {
            'event': 'user_updated',
            'actor_id': self.admin.pk,
            'actor_username': 'ev-admin',
            'target_id': self.target.pk,
            'target_username': 'ev-target',
            'ip_address': CLIENT_IP,
            # changed_fields 排序 = 稳定可比；values 是**改完之后**的值（改之前
            # is_active 是 True，记旧值就等于把「停用了谁」写成「谁本来就是启用的」）。
            'detail': {'changed_fields': ['display_name', 'is_active'],
                       'values': {'display_name': 'Renamed', 'is_active': False}},
        })
        blob = str(row['detail'])
        for secret in (TARGET_PW, NEW_PW, 'password'):
            self.assertNotIn(secret, blob, blob)

    def test_user_updated_sorts_changed_fields(self):
        """`changed_fields` 的顺序是排过序的，不是 validated_data 的键序。

        DRF 的 `Serializer.to_internal_value` 按 `self._writable_fields`（= 可写字段的
        声明序）遍历，所以 role/is_active 这对键天然拿到 ['role', 'is_active'] —— 与字母序
        相反（实测：去掉 `sorted()` 后本条红）。不排序的话数组就得跟着 `Meta.fields` 的写法
        走，改一次字段顺序 = 同一件事的审计值换一种拼法。
        """
        resp = self.client.put(f'{USERS_URL}{self.target.pk}/',
                               {'is_active': False, 'role': 'user'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._only_row()['detail'], {
            'changed_fields': ['is_active', 'role'],
            'values': {'is_active': False, 'role': 'user'},
        })

    def test_user_updated_records_requested_fields_not_a_diff(self):
        """重发**当前值**仍算一次变更：`changed_fields` 是「请求带了哪些字段」，不是值差集。

        这不是偷懒，是和这条路上另外两方对齐：`_guard_lockout` 与 `serializer.save()` 都只
        看请求带了什么（partial 更新里没带的键根本不写），审计要是自己去比 before/after，
        就会记下两件不同时间线上的事 —— 而且比的是「视图取行那一刻」的旧值，同一次请求里
        别人改过的它看不见。代价是这条记录不能说「这个人被改动了」，只能说「这次请求动了这些
        字段」；把它读成值差集会高估审计的信息量。判据：只交回当前值，值没变、行照留。
        """
        payload = {'display_name': self.target.display_name, 'is_active': self.target.is_active}
        resp = self.client.put(f'{USERS_URL}{self.target.pk}/', payload, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._only_row()['detail'], {
            'changed_fields': ['display_name', 'is_active'],
            'values': payload,
        })
        self.target.refresh_from_db()
        # 值确实一个都没动 —— 这一行记的是「请求动过这些字段」，不是「字段变了」。
        self.assertEqual(self.target.display_name, payload['display_name'])
        self.assertEqual(self.target.is_active, payload['is_active'])

    def test_password_never_reaches_user_updated_detail(self):
        with mock.patch.object(UserManagementViewSet, 'get_serializer_class',
                               lambda self: _WritablePasswordSerializer):
            resp = self.client.put(f'{USERS_URL}{self.target.pk}/',
                                   {'password': TARGET_PW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        # 口令键被白名单滤掉 ⇒ 变更集为空，行仍留（这次 PUT 在 HTTP 上确实成功了）。
        # 注意本条用的是 `_WritablePasswordSerializer` 那个形状夹具：它会把**明文**写进
        # password 列，生产序列化器不允许这样 —— 判据只看审计那一行不含口令，别把它读成
        # 「生产通路会这样写库」。
        self.assertEqual(self._only_row()['detail'],
                         {'changed_fields': [], 'values': {}})

    def test_user_deleted_keeps_username_after_fk_gone(self):
        resp = self.client.delete(f'{USERS_URL}{self.target.pk}/')
        self.assertEqual(resp.status_code, 204, resp.content)
        # 本行钉的是**内容**（快照在、FK 空）。视图为什么写 `target_username=` 而不是
        # `target=instance`：删除后实例 pk 已被 Django 置 None，`audit._live()` 把两种写法
        # 折成完全同一行，所以在这个调用点换写法测不出差别（实测：探针 P10 全绿）；真正
        # 管住那个形状的是写入器侧的
        # `test_audit_writer.py::test_deleted_target_instance_still_records_the_snapshot`。
        self.assertEqual(self._only_row(), {
            'event': 'user_deleted',
            'actor_id': self.admin.pk,
            'actor_username': 'ev-admin',
            'target_id': None,
            'target_username': 'ev-target',
            'ip_address': CLIENT_IP,
            'detail': {'role': 'user'},
        })

    def test_password_reset_then_unlock_records_both(self):
        User.objects.filter(pk=self.target.pk).update(
            login_attempts=3, lockout_until=timezone.now() + timedelta(minutes=9))
        resp = self.client.post(f'{USERS_URL}{self.target.pk}/reset_password/',
                                {'new_password': NEW_PW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._only_row(), {
            'event': 'password_reset',
            'actor_id': self.admin.pk,
            'actor_username': 'ev-admin',
            'target_id': self.target.pk,
            'target_username': 'ev-target',
            'ip_address': CLIENT_IP,
            'detail': {'lockout_cleared': True},
        })
        self.target.refresh_from_db()
        # `lockout_cleared` 是契约声明而不是条件：本端点无条件清这两个字段（下面两记
        # 断言钉住事实），所以那个 true 永远不谎报。把它改成条件判断就是让审计说谎。
        self.assertEqual(self.target.login_attempts, 0)
        self.assertIsNone(self.target.lockout_until)

        resp = self.client.post(f'{USERS_URL}{self.target.pk}/unlock/')
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = _rows()
        self.assertEqual([r['event'] for r in rows],
                         ['password_reset', 'account_unlocked'], rows)
        self.assertEqual(rows[1], {
            'event': 'account_unlocked',
            'actor_id': self.admin.pk,
            'actor_username': 'ev-admin',
            'target_id': self.target.pk,
            'target_username': 'ev-target',
            'ip_address': CLIENT_IP,
            'detail': {},
        })
        self.target.refresh_from_db()
        self.assertEqual(self.target.login_attempts, 0)
        self.assertIsNone(self.target.lockout_until)

    def test_unlock_writes_only_the_two_lockout_columns(self):
        """解锁那句 `save(update_fields=[...])` 是窄写，判据只能看 UPDATE 的 SET 列集合。

        窄写与整行写在返回体、审计行、甚至两列的最终值上都不可区分（写进去的本来就要写成
        0/None），所以这条形状判据是它唯一的判据。整行 `user.save()` 的代价是把**内存里那份
        实例**整个盖回库：password、last_login、is_superuser、first_name 全都会被 SET 一遍，
        同一次请求取行之后另一位管理员改过的东西就丢了。列集合按**整值**判（多一列少一列都算
        漂），不逐列 `assertIn`/`assertNotIn` —— 后者漏掉的那几列恰好是最贵的那几列。
        顺带钉这句响应文案：本批把英文 `'Account unlocked successfully.'` 换成中文，全仓与
        前端都没有钉住旧串（`UserManagement.vue` 的 `unlockUser` 只 POST、不读响应体）。
        """
        User.objects.filter(pk=self.target.pk).update(
            login_attempts=3, lockout_until=timezone.now() + timedelta(minutes=9))
        with CaptureQueriesContext(connection) as cap:
            resp = self.client.post(f'{USERS_URL}{self.target.pk}/unlock/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['detail'], '账号已解锁。')
        sets = _user_update_set_columns(cap)
        self.assertEqual(len(sets), 1, f'解锁只该发一条 accounts_user 的 UPDATE，实测 {sets}')
        self.assertEqual(sorted(sets[0]), ['lockout_until', 'login_attempts'], sets[0])

    def test_self_password_change_records_actor_and_target_as_one(self):
        client = APIClient()
        client.force_authenticate(user=self.target)
        resp = client.post(CHANGE_URL, {'old_password': TARGET_PW,
                                        'new_password': NEW_PW,
                                        'confirm_password': NEW_PW}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        row = self._only_row()
        self.assertEqual(row, {
            'event': 'password_changed',
            'actor_id': self.target.pk,
            'actor_username': 'ev-target',
            'target_id': self.target.pk,
            'target_username': 'ev-target',
            'ip_address': CLIENT_IP,
            'detail': {},
        })
        self.assertNotIn(NEW_PW, str(row))
        self.target.refresh_from_db()
        # 留痕的前提是口令真的换了，否则这一行本身就是假记录。
        self.assertTrue(self.target.check_password(NEW_PW))

    def test_rejected_requests_leave_no_audit_row(self):
        """四条被拒的写请求：序列化器 400 与守卫 400 都不许留下审计行。"""
        cases = (
            ('post', USERS_URL, {'username': 'ev-weak', 'password': '12345678',
                                 'role': 'user'}),
            ('put', f'{USERS_URL}{self.admin.pk}/', {'is_active': False}),
            ('delete', f'{USERS_URL}{self.admin.pk}/', None),
            ('put', f'{USERS_URL}{self.admin.pk}/', {'role': 'user'}),
        )
        for method, url, body in cases:
            with self.subTest(method=method, url=url, body=body):
                sender = getattr(self.client, method)
                resp = sender(url, body, format='json') if body is not None \
                    else sender(url)
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(AuditEvent.objects.count(), 0, _rows())

    def test_rejected_password_operations_leave_no_row(self):
        """两条口令写路径在**进业务之前**就被序列化器挡下：不许留痕。

        与 `test_rejected_requests_leave_no_audit_row` 分开一条：那边走的是
        `_guard_lockout`（业务写已经发生、审计写在守卫之后），这边连业务都没进。
        两道闸失守的表现不同 —— 合并成一条就分不清是哪道先漏。
        """
        self_client = APIClient()
        self_client.force_authenticate(user=self.target)
        cases = (
            (self.client, f'{USERS_URL}{self.target.pk}/reset_password/',
             {'new_password': '12345678'}),
            (self_client, CHANGE_URL,
             {'old_password': 'wrong-old-pass-123', 'new_password': NEW_PW,
              'confirm_password': NEW_PW}),
        )
        for client, url, body in cases:
            with self.subTest(url=url, body=body):
                resp = client.post(url, body, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(AuditEvent.objects.count(), 0, _rows())


class SystemPathsEventTests(TestCase):
    """`system_paths_changed`。配置文件必须落临时目录，否则这条用例会改写本机真实的
    `system_config.json` —— 隔离手法照 `apps/common/tests_system_paths.py` 的
    setUp/_restore_env（那套 env + 临时目录是本仓已验证的写法）。"""

    def setUp(self):
        self.admin = User.objects.create_superuser('sp-admin', 's@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self._cfg_dir = tempfile.TemporaryDirectory()
        self._cfg_file = Path(self._cfg_dir.name) / 'system_config.json'
        self.addCleanup(self._cfg_dir.cleanup)
        self._old_env = os.environ.get('LQDP_SYSTEM_CONFIG_FILE')
        os.environ['LQDP_SYSTEM_CONFIG_FILE'] = str(self._cfg_file)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._old_env is None:
            os.environ.pop('LQDP_SYSTEM_CONFIG_FILE', None)
        else:
            os.environ['LQDP_SYSTEM_CONFIG_FILE'] = self._old_env

    def _row_for(self, index):
        rows = _rows()
        self.assertEqual(len(rows), index + 1, f'第 {index + 1} 次 PUT 后应恰好 {index + 1} 行，实测 {rows}')
        return rows[index]

    def test_paths_change_records_before_and_after(self):
        new_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(new_dir, ignore_errors=True))
        resp = self.client.put(PATHS_URL, {'data_dir': new_dir}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(self._row_for(0), {
            'event': 'system_paths_changed',
            'actor_id': self.admin.pk,
            'actor_username': 'sp-admin',
            # 系统级事件没有「目标账号」：FK 与快照都留空，操作者就是全部线索。
            'target_id': None,
            'target_username': '',
            'ip_address': CLIENT_IP,
            'detail': {
                'before': {'data_dir': None, 'temp_dir': None},
                'after': {'data_dir': new_dir, 'temp_dir': None},
                'restart_required': True,
            },
        })

        # 第二次 PUT 交回同一个值：`restart_required` 必须由 before/after 的比较推导，
        # 写死 true 的话上面那记跟着绿、这一记红（与端点载荷同源，见视图里同一个表达式）。
        resp = self.client.put(PATHS_URL, {'data_dir': new_dir}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(resp.data['restart_required'])
        second = self._row_for(1)['detail']
        self.assertEqual(second, {
            'before': {'data_dir': new_dir, 'temp_dir': None},
            'after': {'data_dir': new_dir, 'temp_dir': None},
            'restart_required': False,
        })

    def test_paths_change_counts_a_key_it_drops_as_a_restart(self):
        """配置里有端点不托管的第三个键时：载荷说要重启，审计的 before/after 看着却没变。

        `save_config` 是**整份重写**且只写 `data_dir`/`temp_dir`（见该函数本体），所以一个
        手改出来的 `legacy_dir` 会被这次 PUT 抹掉。`restart_required` 按整份字典比 ⇒ True
        是对的（磁盘上的配置确实变了，也确实要重启才生效）；而 spec §5.3 把 detail 钉死在
        这两个键上，于是那一行看起来 before == after。本条把这个不一致钉成**已知语义**，
        不是留给谁顺手把比较改成投影字典 —— 那样会把「真的少了个键」报成「不用重启」。
        """
        new_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(new_dir, ignore_errors=True))
        self._cfg_file.write_text(
            json.dumps({'data_dir': new_dir, 'temp_dir': None, 'legacy_dir': 'x'}),
            encoding='utf-8',
        )
        resp = self.client.put(PATHS_URL, {'data_dir': new_dir}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data['restart_required'], resp.data)
        detail = self._row_for(0)['detail']
        self.assertEqual(detail, {
            'before': {'data_dir': new_dir, 'temp_dir': None},
            'after': {'data_dir': new_dir, 'temp_dir': None},
            'restart_required': True,
        })

    def test_rejected_path_change_leaves_no_audit_row(self):
        for bad in ('relative/path', ''):
            with self.subTest(bad=bad):
                resp = self.client.put(PATHS_URL, {'data_dir': bad}, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(AuditEvent.objects.count(), 0, _rows())


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    sys.exit(1 if runner.run_tests(['test.backend.test_audit_account_events']) else 0)
