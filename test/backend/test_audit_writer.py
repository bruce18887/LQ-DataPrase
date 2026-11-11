"""审计写入器：快照、截断、IP、以及「审计炸了业务不许跟着炸」（spec §5.4）。

三个类各管一层，互不重叠：

* `WriterTests` —— `record()` 的字段语义（快照 / 截断 / IP / 事件码清单 / detail 的
  序列化边界 / 删号后仍可读）与「异常不外溢 + 留痕带 traceback」，外加那张表的
  Meta 形状（表名、ordering、索引组合、快照列宽）。
* `WriterIsolationTests` —— 外层有事务时（改密、重置、账号变更的真实形状）一笔失败的
  审计 INSERT 只许带走审计自己。两条用例的差别全在**注入方式**上，见各自 docstring。
* `WriterAutocommitShapeTests` —— 外层是 autocommit 时（Task 6 接线后登录走的就是这一支）
  的语句形状。`TestCase` 把每个用例包进一个原子块，`in_atomic_block` 恒为 True ⇒
  `record()` 的 autocommit 一支在 `TestCase` 里**一次都跑不到**，所以只能由
  `TransactionTestCase` 量。

形状事实是本机现量（2026-11-10，`.venv` = Python 3.13.12 / Django 6.0.9，
`config.settings.unit` 的 SQLite 测试库）。探法是一张 2×2 四格表：外层 `atomic()` 里先写
一条业务行，再让一笔 INSERT 失败，咽掉，再写一条，退出外层看两行是否都提交 ——
「有/无内层 atomic」×「真 DB 错误 / mock 在 Python 层抛错」：

                         真 DB 错误            Python 层抛错（mock）
    有内层 atomic()      业务行活着 ✓          业务行活着 ✓
    无内层 atomic()      业务行没了 ✗          业务行活着 ✓

左列那一格（无 savepoint + 真错误）就是 savepoint 支的存在理由，根因在 Django 里、
不在本仓代码：Django 6.0.9 的 `Model._save` 对无父表模型（`AuditEvent` 就是）包一层
`transaction.mark_for_rollback_on_error()`，异常穿过它就把 `connection.needs_rollback`
置 True；只有带 savepoint 的 `Atomic.__exit__` 会把它复位，没有可退的 savepoint 时整笔
外层事务被标死 —— 于是咽掉之后下一条写语句先抛 `TransactionManagementError`
（`An error occurred in the current transaction`），外层提交变回滚，改密那一行跟着没。
出处按符号名 + 版本指代，不写 `.venv` 里的行号：那份树不入库，行号会在升级时静默腐烂。
右列两格说明为什么「patch `_insert` 抛 Python 异常」证不了 savepoint 的必要性：SQL 根本
没发出去，`needs_rollback` 从没被点着，所以有/无内层 atomic 两种写法业务行都活着。
四格各自的落点：左列上格 = `test_real_insert_failure_...`（正面判据）；左列下格 = 变异
M-nosavepoint 复现（本文件唯一红的那条就是它）；右列上格 = `test_mocked_insert_failure_...`；
右列下格只在那次探量里出现过，**没有单独判据**，也不必为它加一条（它证的是「mock 证不了
savepoint」这件事本身，写在这儿是为了别让人以为四格都有牙）。
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from datetime import datetime, timezone  # noqa: E402

from django.contrib.auth.models import AnonymousUser  # noqa: E402
from django.db import DatabaseError, connection, transaction  # noqa: E402
from django.test import RequestFactory, TestCase, TransactionTestCase  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402

from apps.accounts import audit  # noqa: E402
from apps.accounts.models import AuditEvent, User  # noqa: E402

PASSWORD = 'x-pass-12345678'


def _verbs(captured):
    """整条语句序列的首词大写表 —— 形状判据拿它比「全体」，不拆 DML/簿记。"""
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


class WriterTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser('w-admin', 'a@localhost', PASSWORD)

    def _request(self, ip='10.99.0.31'):
        request = self.factory.post('/api/v1/auth/login/')
        request.META['REMOTE_ADDR'] = ip
        request.user = self.admin
        return request

    def test_records_actor_and_target_snapshot(self):
        target = User.objects.create_user('w-target', 't@localhost', PASSWORD)
        audit.record(self._request(), 'user_updated', actor=self.admin, target=target,
                     detail={'changed_fields': ['role']})
        row = AuditEvent.objects.get()
        self.assertEqual((row.event, row.actor_username, row.target_username),
                         ('user_updated', 'w-admin', 'w-target'))
        self.assertEqual(row.ip_address, '10.99.0.31')
        self.assertEqual(row.detail, {'changed_fields': ['role']})

    def test_anonymous_actor_leaves_empty_snapshot_but_keeps_target(self):
        request = self._request()
        request.user = AnonymousUser()
        audit.record(request, 'login_failure', target_username='ghost',
                     detail={'reason': 'unknown_user'})
        row = AuditEvent.objects.get()
        self.assertIsNone(row.actor_id)
        self.assertEqual(row.actor_username, '')
        self.assertEqual(row.target_username, 'ghost')

    def test_overlong_username_is_truncated_not_raised(self):
        audit.record(self._request(), 'login_failure',
                     target_username='x' * 400)
        row = AuditEvent.objects.get()
        self.assertEqual(len(row.target_username), 150)

    def test_unsaved_actor_falls_back_to_snapshot_only(self):
        """没主键的 actor 实例：FK 留空、快照照写，而且一样要截断。

        两条腿各钉一处 `_live` / `_snapshot` 的**调用点**：`target` 那侧由
        `test_deleted_target_instance_still_records_the_snapshot` 钉，actor 这侧原本
        谁都看不见 —— 把 `actor=_live(user)` 换成 `actor=user`（整行被 ValueError 咽掉）
        与把 `actor_username=_snapshot(...)` 换成裸值（400 字符原样入库）两记变异当时
        都是全绿。用未保存实例是因为登录失败那条路径正是这个形状：用户名来自请求体，
        库里未必有对应账号。
        """
        ghost = User(username='y' * 400)
        audit.record(self._request(), 'login_failure', actor=ghost)
        row = AuditEvent.objects.get()
        self.assertIsNone(row.actor_id)
        self.assertEqual(len(row.actor_username), 150, '快照列宽必须被 _snapshot 管住')
        self.assertEqual(row.target_username, '')

    def test_illegal_ip_leaves_null(self):
        audit.record(self._request(ip='not-an-ip'), 'login_success',
                     actor=self.admin, target=self.admin)
        self.assertIsNone(AuditEvent.objects.get().ip_address)

    def test_failure_does_not_escape_and_is_logged(self):
        # 注入点选真实写路径 `AuditEvent.save`（照 test_sftp_last_visit_writes.py:463-481
        # 的口径）：把 `_insert` 换成异常替身只测得到守卫存在，测不到守卫罩得住真 INSERT。
        # 两个注入点因此不重复、也不互相覆盖：本条把写路径换成任何绕过 `Model.save` 的写法
        # （例：`bulk_create`）就红，而 patch `_insert` 的 `test_mocked_insert_failure_...`
        # 对同一种换法全绿（它只看得到那个接缝）。
        with mock.patch.object(AuditEvent, 'save',
                               side_effect=DatabaseError('database is locked')):
            with self.assertLogs('apps.accounts.audit', level='WARNING') as cm:
                audit.record(self._request(), 'login_success',
                             actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertTrue(any('审计写入失败' in line for line in cm.output), cm.output)
        self.assertIsNotNone(cm.records[0].exc_info, '留痕必须带 traceback')

    def test_event_list_is_the_single_source(self):
        self.assertEqual(
            audit.AUDIT_EVENTS,
            ('login_success', 'login_failure', 'account_locked', 'account_unlocked',
             'password_changed', 'password_reset', 'user_created', 'user_updated',
             'user_deleted', 'system_paths_changed'),
        )

    def test_login_failure_reason_list(self):
        self.assertEqual(
            audit.LOGIN_FAILURE_REASONS,
            ('unknown_user', 'bad_password', 'account_disabled', 'account_locked'),
        )

    def test_non_string_username_snapshot_is_empty(self):
        """非字符串取值落空串，而不是把 `repr()` 写进快照列。"""
        audit.record(self._request(), 'login_failure', target_username=123)
        self.assertEqual(AuditEvent.objects.get().target_username, '')

    def test_unknown_event_code_is_written_and_flagged(self):
        """没登记的码名：行照写 + 一条 warning，不拒写。

        拒写会把「码名写错」升级成「事件丢失」，比留一行前端贴不出标签的事件更糟。
        但也不能无声收下：Task 9 的前端标签表按 `AUDIT_EVENTS` 逐码出标签，多出来的
        码在那边是空白，得有一条 warning 指路。
        """
        with self.assertLogs('apps.accounts.audit', level='WARNING') as cm:
            audit.record(self._request(), 'login_faided', actor=self.admin)
        self.assertEqual(AuditEvent.objects.get().event, 'login_faided')
        self.assertTrue(any('未登记' in line for line in cm.output), cm.output)

    def test_unserializable_detail_drops_the_row_and_is_logged(self):
        """detail 不可 JSON 序列化 ⇒ 整行没 + warning（边界，不假装被兜住）。

        datetime 撞 `TypeError` 被 best-effort 咽掉，事件因此静默丢失。这条存在的
        理由就是把代价量出来给人看：spec §5.3 约定 detail 里写 ISO 字符串，Task 6
        接线时不能直接把 `locked_until` 那种 datetime 塞进来。
        """
        with self.assertLogs('apps.accounts.audit', level='WARNING'):
            audit.record(self._request(), 'account_locked', actor=self.admin,
                         detail={'locked_until': datetime.now(timezone.utc)})
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_deleted_target_instance_still_records_the_snapshot(self):
        """把 `instance.delete()` 之后的那个实例交给 `target=`：行必须还在。

        不摘 pk 的话 `Model.save()` 抛 `ValueError: save() prohibited to prevent data
        loss due to unsaved related object 'target'`，被咽掉的后果是**整行丢失** ——
        而 Task 7 的 `user_deleted` 正是这个形状（`apps/accounts/views.py` 的 destroy
        先删实例再记事件）。摘掉 `_live()`（变异）⇒ 本条红。
        """
        victim = User.objects.create_user('w-victim', 'v@localhost', PASSWORD)
        victim.delete()
        audit.record(self._request(), 'user_updated', actor=self.admin, target=victim)
        row = AuditEvent.objects.get()
        self.assertIsNone(row.target_id)
        self.assertEqual(row.target_username, 'w-victim')

    def test_events_stay_readable_after_actor_and_target_are_deleted(self):
        """spec §5.1：账号删掉之后，事件仍要读得出「当时是谁对谁做了什么」。

        快照与 FK 分开存的全部意义就在这条上 —— SET_NULL 把关联抹平，标签留在快照里。
        """
        victim = User.objects.create_user('w-gone', 'g@localhost', PASSWORD)
        audit.record(self._request(), 'user_deleted', actor=self.admin, target=victim)
        victim.delete()
        self.admin.delete()
        row = AuditEvent.objects.get()
        self.assertIsNone(row.actor_id)
        self.assertIsNone(row.target_id)
        self.assertEqual((row.actor_username, row.target_username), ('w-admin', 'w-gone'))
        self.assertEqual(row.event, 'user_deleted')

    def test_request_user_property_that_raises_is_swallowed(self):
        """`request.user` 自己抛（DRF 懒解析的形状）也必须被咽掉。

        取用户那几行原本写在 `try` 外面，异常因此直接溢到调用方 —— 违反「业务动作
        永远优先」，接线时会把登录/改密端点 500。搬进 `try` 之后本条才有牙。
        """
        class Exploding:
            META = {}

            @property
            def user(self):
                raise RuntimeError('auth layer exploded')

        with self.assertLogs('apps.accounts.audit', level='WARNING'):
            audit.record(Exploding(), 'login_success')
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_table_shape_matches_the_model_declaration(self):
        """表名、排序、索引组合与两条快照列宽 —— 计划正文写死的东西要有判据。

        复合改 Meta（翻 ordering + 撤 `event` 索引 + `db_index=False`）原本 10 例全绿。
        Task 8 的查询靠 `ordering=['-created_at']` 与 `(event, created_at)` 索引，漂了
        不会有人知道，只会在审计页上表现为一次全表扫。列宽那一断同时钉住
        `USERNAME_MAX_LENGTH` 是从字段读的：把列收窄到 60 ⇒ 本条红，而不是 `_snapshot`
        安静截出比列宽更长的值。
        """
        meta = AuditEvent._meta
        self.assertEqual(meta.db_table, 'accounts_audit_event')
        self.assertEqual([o.lstrip('-') for o in meta.ordering], ['created_at'])
        self.assertTrue(meta.ordering[0].startswith('-'), '默认必须是新→旧')
        self.assertEqual(
            sorted(tuple(idx.fields) for idx in meta.indexes),
            sorted([('actor_username', 'created_at'), ('event', 'created_at'),
                    ('target_username', 'created_at')]),
        )
        self.assertTrue(meta.get_field('created_at').db_index)
        for name in ('actor_username', 'target_username'):
            self.assertEqual(meta.get_field(name).max_length, audit.USERNAME_MAX_LENGTH)
        self.assertEqual(str(AuditEvent(event='user_updated',
                                       actor_username='a', target_username='b')),
                         'user_updated a → b')

    def test_loopback_proxy_takes_rightmost_xff_entry(self):
        """本机 TLS 反代：REMOTE_ADDR 恒为回环，真实客户端在 XFF 最右一条
        （nginx $proxy_add_x_forwarded_for 追加）；左侧条目客户端可伪造，不许取。"""
        request = self._request(ip='127.0.0.1')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9, 198.51.100.7'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '198.51.100.7')

    def test_non_loopback_source_ignores_xff(self):
        """直连（非回环）时 XFF 整条都不可信，仍记 REMOTE_ADDR。"""
        request = self._request(ip='10.99.0.31')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '10.99.0.31')

    def test_loopback_without_xff_unchanged(self):
        """桌面档 Electron 直连回环、没有 XFF：行为与改前逐字相同。"""
        audit.record(self._request(ip='::1'), 'login_success',
                     actor=self.admin, target=self.admin)
        self.assertEqual(AuditEvent.objects.get().ip_address, '::1')

    def test_loopback_with_garbage_xff_rightmost_leaves_null(self):
        """替换后的值仍过 ip_address 校验：最右一条非法 → None，不入库脏值。"""
        request = self._request(ip='127.0.0.1')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.9, not-an-ip'
        audit.record(request, 'login_success', actor=self.admin, target=self.admin)
        self.assertIsNone(AuditEvent.objects.get().ip_address)


class WriterIsolationTests(TestCase):
    """审计 INSERT 失败不能把外层业务事务一起带走 —— 改密/重置/账号变更都在真事务里。

    生产调用点分两批接进来：登录族在 Task 6（**已落地**，端点侧判据 `test_audit_login_events.py`），
    改密 / 账号 CRUD / 存储路径在 Task 7（还没有 `audit.record` 调用）。这两条因此直接对机制
    下判据（外层 `atomic()` 里写业务行 + 调 `record()`），不走端点 —— 端点接没接线与本文件的
    隔离判据无关。
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.admin = User.objects.create_superuser('w-iso-admin', 'i@localhost', PASSWORD)

    def _request(self):
        request = self.factory.post('/api/v1/auth/change-password/')
        request.META['REMOTE_ADDR'] = '10.99.0.32'
        request.user = self.admin
        return request

    def test_mocked_insert_failure_keeps_outer_business_transaction(self):
        """Python 层抛错的守卫判据（外层有事务那一支）。

        注入用 `mock.patch(audit._insert)` ⇒ 一条 SQL 都没发出去，`needs_rollback`
        从没被点着（本文件头四格表的右列：有/无内层 atomic 两种写法业务行都活着）。
        所以这条**只**证「`record()` 就地咽异常、不外溢」，不证 savepoint 的必要性 ——
        后者是下面那条的职责。摘掉 `record()` 的 `try/except`（变异 M-swallow）⇒ 本条红
        （DatabaseError 直接从 `record()` 溢到用例里）。
        """
        with transaction.atomic():
            User.objects.create_user('w-biz-mock', 'b@localhost', PASSWORD)
            with mock.patch.object(
                audit, '_insert', side_effect=DatabaseError('no such table: mock')
            ):
                audit.record(self._request(), 'password_changed',
                             actor=self.admin, target_username='w-biz-mock')
            # 咽下来之后同一笔事务还要能继续写：这条就是「外层没被标成 needs_rollback」。
            User.objects.create_user('w-after-mock', 'c@localhost', PASSWORD)
        self.assertEqual(
            User.objects.filter(username__in=['w-biz-mock', 'w-after-mock']).count(), 2,
            '审计失败必须不影响业务提交')
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_real_insert_failure_keeps_outer_business_transaction(self):
        """真 DB 错误的隔离判据 —— savepoint 支的存在理由，也是它唯一的判据。

        失败是真的：`event=None` 让 INSERT 撞 `accounts_audit_event.event` 的 NOT NULL
        约束（0014 建表时带的），SQLite 报 IntegrityError，Django 6.0.9 的
        `Model._save` 那层 `mark_for_rollback_on_error()`（模块头引的符号名）就把这笔
        写标成「要回滚」。
        有内层 savepoint ⇒ 只回滚审计自己，业务行照常提交；
        摘掉内层 `atomic()`（变异 M-nosavepoint）⇒ 本文件头四格表左列下格那个形状复现：
        下一条写语句抛 `TransactionManagementError`，业务行整笔被带走，本条红。
        """
        with transaction.atomic():
            User.objects.create_user('w-biz-real', 'b@localhost', PASSWORD)
            audit.record(self._request(), None, actor=self.admin,
                         target_username='w-biz-real')
            User.objects.create_user('w-after-real', 'c@localhost', PASSWORD)
        self.assertEqual(
            User.objects.filter(username__in=['w-biz-real', 'w-after-real']).count(), 2,
            '真·失败的审计 INSERT 只许带走审计自己那一笔')
        self.assertEqual(AuditEvent.objects.count(), 0)


class WriterAutocommitShapeTests(TransactionTestCase):
    """autocommit 支（登录热路径）的语句形状 —— `TestCase` 里够不着，只能这里量。

    摘掉 `in_atomic_block` 判断、让 `record()` 永远包一层 `atomic()`（变异 M-branch）
    ⇒ 本条红：本机同环境实测 autocommit 下 `atomic()` 的净代价就是 BEGIN/COMMIT 两条
    （裸 `create_user` 1 条 INSERT vs 包一层 `atomic()` 的 BEGIN/INSERT/COMMIT 3 条）。
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_record_in_autocommit_costs_exactly_one_insert(self):
        admin = User.objects.create_superuser('w-tx-admin', 't@localhost', PASSWORD)
        request = self.factory.post('/api/v1/auth/login/')
        request.META['REMOTE_ADDR'] = '10.99.0.33'
        request.user = admin
        self.assertFalse(transaction.get_connection().in_atomic_block,
                         '前置：本用例必须真跑在 autocommit 上，否则测的是另一支')
        with CaptureQueriesContext(connection) as cap:
            audit.record(request, 'login_success', actor=admin, target=admin)
        # 一记不可拆的断言：整个语句序列必须恰好是那条 INSERT。原先拆成
        # 「_dml == ['INSERT']」+「_dml == 全体」两记时，M-branch 只多 BEGIN/COMMIT、
        # 不改 DML 序列，前一记永远绿，后一记还能被写成恒真 —— 两条一起放过那次变异。
        self.assertEqual(_verbs(cap), ['INSERT'], 'autocommit 下必须只有一条 INSERT')
        self.assertEqual(AuditEvent.objects.count(), 1)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    sys.exit(1 if runner.run_tests(['test.backend.test_audit_writer']) else 0)
