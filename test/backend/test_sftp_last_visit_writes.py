"""D4 · SFTP 断线续连记录：值未变 ⇒ 零写（`_record_last_visit` 的语句形状）。

下面每个形状都是本机现量（2026-10-31 第二轮收尾，PATH 上的系统 Python = Django 6.0.5，命令
`python -X utf8 manage.py test test.backend.test_sftp_last_visit_writes`；收口时再对 `.venv`
= Django 6.0.9 交叉复核，形状逐字相同），不是照抄计划正文。
**计划正文那句「每次浏览少两次写」在稳态下不成立**：同目录重复浏览在改动前只发
1 条 UPDATE（外加 1 条读 settings 的 SELECT），省下的就是这 1 条写；「两次写」只在
**账号还没有 settings 行**的那一次出现（`get_or_create` 先 INSERT 默认值、随后
`save(update_fields=…)` 再 UPDATE 一次）——本批把那条也压成「值直接进 INSERT」的一条写。

**现形状**（逐分支的核心动词 = 钉住它的那个用例，去掉 BEGIN/SAVEPOINT 这类事务簿记）：

- 有行 + 值变（冷实例）：`SELECT + UPDATE`，SET 只含真变的那一列
  —— `BrowseStatementShapeTests.test_first_browse_writes_once_with_only_the_path_column`
- 有行 + 值未变（冷实例）：`SELECT`，**0 写**（本批的主判据）—— 同上的
  `test_repeat_browse_of_the_same_directory_performs_zero_writes`
- 缺行（冷实例）：`SELECT + INSERT`，1 写、值直接进 INSERT
  —— `MissingRowProvisioningTests.test_no_row_first_browse_creates_the_row_carrying_the_path`
- 热正缓存 + 值变：`UPDATE`（读被省掉）；热正缓存 + 值未变：**零语句**
  —— `WarmCacheReadFreeTests` 那两条
- `auto_connect` 且**缺行**（它自己的 `get_or_create` 先建行并焐热本请求缓存）：记录段
  `UPDATE`、零读；同一路径**行已存在**时（`.get()` 不挂缓存）回到 `SELECT + UPDATE`
  —— `AutoConnectWarmCacheTests` 那两条（第三轮复审就是在这里否证了 views 里「调用点缓存必冷」）
- 并发建行：`SELECT + UPDATE`，且**冷缓存**与「本请求先读过一次、落下『没有行』的负缓存」
  两种交错**同数**（helper 内那次缓存咨询零 SQL）—— `MissingRowRaceTests` 里同一个 `_raced`
  helper 取 `prime_read=False` / `True` 的两条用例
- 一个字段都没传（有行/缺行同）：**零语句**，不读不写也不建
  —— `MissingRowProvisioningTests` 的两条 `test_nothing_to_record_*`

读侧因此与收敛前**逐分支同数**（有行 1 SELECT、缺行 1 SELECT）。这句在第二轮 Minor 4 之前是假的
（那时缺行是 `SELECT + SELECT + INSERT`，描述符探一次 + `get_or_create` 再 SELECT 一次），
把缓存咨询挪进 `provision_user_setting` 之后才成为真 —— 少的那 1 条写仍然只在缺行那次。

**「改动前」那几张表怎么再取出来对**（原本是同轮量的，别处复制不走）：
`git show 9cf1a0a:apps/sftp/views.py` 的 `_record_last_visit` —— 本批之外最后一次改动这个
文件的提交就是它（复核：`git log --format=%h -- apps/sftp/views.py` 去掉本批那一笔后的头一条），
所以它那份正文 == 本批收敛前的正文。把那个函数体临时换回去再逐场景量一遍即可复现
（换回去时本文件钉**新**形状的用例会红 —— 那时读的正是下面这一列）。
写提交号而不是 `HEAD`：本批落地后 `HEAD` 就不再是收敛前那一份了。收敛前的逐场景形状：

- 有行、path 变 / 有行、path 未变：**同形** `SELECT + UPDATE`（UPDATE 的 SET 只有 `sftp_last_path`）
- 直调五个字段（两个变 / 全不变）：**同形** `SELECT + UPDATE`，SET 恒为**被传入的全部列**（5 列）
- 无行 + 首次浏览：`SELECT + (BEGIN|SAVEPOINT) + INSERT + (COMMIT|RELEASE) + UPDATE` = **2 条写**
- 无行 + 无字段可记：`SELECT + INSERT`（**会**建一条全默认值的行 —— 纯粹因为 `get_or_create` 在 `if updates:` 之上）
- 有行 + 无字段可记：`SELECT`（读一遍，然后什么都不做）
- 同一个 user 实例连调两次：两次都是 `SELECT + UPDATE`（HEAD 的 `get_or_create` 不吃 D1 的实例缓存）
- 缺行 + 并发（别的请求在本请求那次读之后把行建好）：`SELECT + UPDATE`，本请求的值**落地**
  （那一版读完就无条件 `save`，所以它不丢值 —— 丢值是本轮补之前那版的洞，见 `MissingRowRaceTests`）

「缺失即建」的语义**故意保留**（判据 `MissingRowProvisioningTests`），但它**不等于**收敛前那句
`get_or_create`：`defaults` 只在 create 分支生效，并发那一支（`created=False`）必须继续走
「已有行」的 diff+save 收敛，否则本请求的值被静默丢掉、实例缓存还停在「没有行」的负缓存上
（判据 `MissingRowRaceTests`；建行统一走 `apps/accounts/services.py::provision_user_setting`）。
唯一不再建行的情形是「一个字段都没传」——而那两个调用点（`list_files` 的成功分支、
`_connect_impl` 的记录分支）永远至少传一个非 `None` 值，所以这一支**在生产里不可达**：
下面那两条「无字段可记」的用例钉的是给未来调用方定的规矩，不是在跑的策略。
读这五列的通路只有 `auto_connect` 与 `last_visit`（它们自己就带 `get_or_create`，所以「有值才建」
不会让读者扑空）；两个下载端点读的是 `sftp_download_timeout`，**不在**这五列里，别把它算进来。

写侧仍走 `save(update_fields=变更列)` 而**不是** `QuerySet.update()`：后者会让 D1 挂在
`user` 实例上的那份缓存变成陈旧值（同请求内后续 `user.settings` 读到旧路径）。

runner: `manage.py test test.backend.test_sftp_last_visit_writes`
形状口径的工具与三调用点脚手架住在 `test/backend/sftp_last_visit_fixtures.py`（本文件撞 600 行闸
才拆的，口径解释仍在这里）。
"""

from unittest import mock

from django.db import DatabaseError, connection
from django.test.utils import CaptureQueriesContext

from apps.accounts import services
from apps.accounts.models import UserSetting
from apps.accounts.serializers import UserSettingSerializer
from apps.sftp.models import SftpConfig
from apps.sftp.views import SftpViewSet
from test.backend.sftp_last_visit_fixtures import (
    LAST_VISIT_FIELDS, RecordBase, _client_for, _core_verbs, _fresh, _insert_columns,
    _set_columns, _sqls, _update_sqls, _verbs, _write_sqls,
)


class BrowseStatementShapeTests(RecordBase):
    """调用点 1（`list_files` 成功分支）：变了写一条、没变写零条。"""

    def test_first_browse_writes_once_with_only_the_path_column(self):
        """对照/平价条（改动前后都该绿）：值真变时**仍**只有一条写、SET 只有 `sftp_last_path`。

        读侧一条 SELECT，与收敛前同数 —— 第二轮 Minor 4 之后这句对**两条**分支都成立（缺行一支也是
        1 条 SELECT，见模块文档的形状表与 `MissingRowProvisioningTests`）。
        """
        self.browse(self.visitor(), '/sub')          # 起点：先把 '/' 变成 '/sub'
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            resp = self.browse(visitor, '/sub/deep')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_core_verbs(cap), ['SELECT', 'UPDATE'], _sqls(cap))
        self.assertEqual(_set_columns(_update_sqls(cap)[0]), ['sftp_last_path'])
        row = self.reload()
        self.assertEqual(row.sftp_last_path, '/sub/deep')
        # 未传的列不许被顺手重写（这五列之外的值也不许动：D2 把 PUT 收窄到变更列，
        # 这条通路不能又把整行抹回去）。
        self.assertEqual(row.chart_dpi, UserSetting._meta.get_field('chart_dpi').default)

    def test_repeat_browse_of_the_same_directory_performs_zero_writes(self):
        """本批的主判据：同目录重复浏览 ⇒ 零写（改动前这里是 `SELECT + UPDATE`）。"""
        self.browse(self.visitor(), '/sub')
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            resp = self.browse(visitor, '/sub')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_core_verbs(cap), ['SELECT'], _sqls(cap))
        self.assertEqual(_write_sqls(cap), [], '值未变仍发写语句 —— 收窄没生效')
        self.assertEqual(self.reload().sftp_last_path, '/sub')

    def test_browse_response_contract_is_unchanged(self):
        """响应体键集逐字钉住：D4 的写收窄不许动契约，B1 的分页只能**加**两键。

        2026-11-01 B1 按用户拍板给目录列表加帽：`total` / `truncated` 是新增的加性键
        （前端不读也安全），`path` / `items` 与 item 内部形状一字未动 —— 这里把新形状
        一起钉死，防的不是这次，是下一次顺手改。
        """
        sftp = mock.MagicMock(name='SFTPClient')
        entry = mock.MagicMock()
        entry.filename = 'a.csv'
        entry.st_mode = 0o100644
        entry.st_size = 7
        entry.st_mtime = 111
        sftp.listdir_attr.return_value = [entry]
        with mock.patch.object(SftpViewSet, '_get_connection', return_value=sftp):
            data = _client_for(_fresh(self.user.pk)).get(
                '/api/v1/sftp/list_files/?path=/sub').json()
        self.assertEqual(sorted(data), ['items', 'path', 'total', 'truncated'])
        self.assertEqual(data['path'], '/sub')
        self.assertEqual(data['total'], 1)
        self.assertIs(data['truncated'], False)
        self.assertEqual(data['items'], [{'name': 'a.csv', 'is_dir': False,
                                         'size': 7, 'mtime': 111}])


class ConnectStatementShapeTests(RecordBase):
    """调用点 2（`_connect_impl` 的记录分支）：多字段只写变过的那几列。"""

    def _manual_connect_payload(self):
        return {'host': '10.0.0.1', 'port': 2222, 'username': 'alice',
                'password': 'secret'}

    def test_replayed_connect_performs_zero_writes(self):
        """同一份凭据连两次 ⇒ 第二次零写；响应契约仍是 `{'status', 'host'}`。"""
        first = self.connect(self.visitor(), **self._manual_connect_payload())
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {'status': 'connected', 'host': '10.0.0.1'})
        self.assertEqual(self.reload().sftp_last_host, '10.0.0.1')

        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            again = self.connect(visitor, **self._manual_connect_payload())
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), {'status': 'connected', 'host': '10.0.0.1'})
        self.assertEqual(_core_verbs(cap), ['SELECT'], _sqls(cap))
        self.assertEqual(_write_sqls(cap), [])

    def test_five_fields_two_changed_set_clause_is_exactly_those_two(self):
        """部分相等要算对：五个字段里两个变 ⇒ SET 只含那两列（改动前恒为五列）。"""
        self.record(_fresh(self.user.pk), path='/p', config_name='cfg',
                    host='h1', port=22, username='u1')
        changed = _fresh(self.user.pk)
        with CaptureQueriesContext(connection) as cap:
            self.record(changed, path='/q', config_name='cfg',
                        host='h2', port=22, username='u1')
        self.assertEqual(_core_verbs(cap), ['SELECT', 'UPDATE'], _sqls(cap))
        self.assertEqual(_set_columns(_update_sqls(cap)[0]),
                         ['sftp_last_path', 'sftp_last_host'])
        row = self.reload()
        self.assertEqual((row.sftp_last_path, row.sftp_last_config, row.sftp_last_host,
                          row.sftp_last_port, row.sftp_last_username),
                         ('/q', 'cfg', 'h2', 22, 'u1'))

    def test_five_fields_all_unchanged_performs_zero_writes(self):
        self.record(self.visitor(), path='/p', config_name='cfg',
                    host='h1', port=22, username='u1')
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            self.record(visitor, path='/p', config_name='cfg',
                        host='h1', port=22, username='u1')
        self.assertEqual(_core_verbs(cap), ['SELECT'], _sqls(cap))
        self.assertEqual(_write_sqls(cap), [])
        row = self.reload()
        self.assertEqual((row.sftp_last_path, row.sftp_last_config, row.sftp_last_host,
                          row.sftp_last_port, row.sftp_last_username),
                         ('/p', 'cfg', 'h1', 22, 'u1'))


class AutoConnectWarmCacheTests(RecordBase):
    """调用点 3（``auto_connect`` → ``_connect_impl``）：**它自己会把实例缓存焐热**。

    ``auto_connect``（apps/sftp/views.py 的 ``setting, _ = UserSetting.objects.get_or_create(
    user=request.user)``）在**缺行**那一支由 create 分支把新行挂进 ``request.user`` 的反向缓存
    （D1 记录的 ``Model.__init__`` 副作用），于是走到 ``_record_last_visit`` 时缓存是**热的**：
    记录段零读、只剩一条 UPDATE，比较基准是几秒前（TCP 握手期间）刚建出的那份默认行。
    第三轮复审就是拿这条否证了 views 里「两个调用点走到这里时实例缓存必是冷的」——
    那句只对了 ``list_files`` 与手动 ``connect``。行已存在时 ``get_or_create`` 走 manager 的
    ``.get()``（不挂缓存），记录段回到 1 读 + 1 写，所以下面两条 case 钉的是同一路径的两个起点。
    """

    def _auto_connect(self, user):
        """发一次 ``auto_connect``，只捕获其中 ``_record_last_visit`` 那一段的语句。"""
        cfg = SftpConfig(owner=self.user, name='prod', host='10.0.0.1', port=2222,
                         username='alice')
        cfg.set_password('secret')
        cfg.save()
        real = SftpViewSet._record_last_visit
        seen = []

        def spy(viewself, *args, **kwargs):
            with CaptureQueriesContext(connection) as cap:
                out = real(viewself, *args, **kwargs)
            seen.append(cap)
            return out

        transport = mock.MagicMock()
        with mock.patch.object(SftpViewSet, '_record_last_visit', spy), \
                mock.patch('apps.sftp.views.paramiko.Transport',
                           mock.MagicMock(return_value=transport)):
            resp = _client_for(user).post('/api/v1/sftp/auto_connect/',
                                          {'config_name': 'prod'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(len(seen), 1, '记录段没被执行一次（前置条件变了）')
        return seen[0]

    def test_missing_row_leaves_the_record_segment_reading_nothing(self):
        """缺行 ⇒ auto_connect 自己建行并焐热缓存 ⇒ 记录段 0 SELECT + 1 UPDATE，值照样落地。"""
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        visitor = self.visitor()
        cap = self._auto_connect(visitor)
        # 前置条件本身要钉住：它哪天不再焐热缓存，这条会退化成下一 case 的形状而不是静默失配。
        cached = services._SETTINGS_REL.get_cached_value(visitor, None)
        self.assertIsNotNone(cached, 'auto_connect 的建行分支没把行挂进本请求缓存')
        self.assertFalse(cached._state.adding)
        self.assertEqual(_core_verbs(cap), ['UPDATE'], _sqls(cap))
        row = self.reload()
        self.assertEqual((row.sftp_last_config, row.sftp_last_host, row.sftp_last_port,
                          row.sftp_last_username), ('prod', '10.0.0.1', 2222, 'alice'))

    def test_existing_row_starts_cold_so_the_record_segment_pays_one_read(self):
        """行已存在 ⇒ ``get_or_create`` 的 ``.get()`` 不挂缓存 ⇒ 记录段回到 1 读 + 1 写。"""
        cap = self._auto_connect(self.visitor())
        self.assertEqual(_core_verbs(cap), ['SELECT', 'UPDATE'], _sqls(cap))
        self.assertEqual(self.reload().sftp_last_config, 'prod')


class MissingRowProvisioningTests(RecordBase):
    """「缺失即建」是**故意保留**的语义，不是漏改（改动前 `get_or_create` 无条件建行）。"""

    def test_no_row_first_browse_creates_the_row_carrying_the_path(self):
        """无行 + 有值可记 ⇒ 建行、行里带那个值：**1 读 + 1 写**（值进 INSERT，不再补 UPDATE）。

        读侧与收敛前**同数**（都是 1 条 SELECT，形状表见模块文档开头）：建行入口自己会先看
        D1 的实例缓存（`_cached_setting`，含 `_state.adding` 守卫），所以缺行分支不再
        「先拿描述符探一次、`get_or_create` 再 SELECT 一次」。

        下面「值字面量出现在那条 INSERT 里」的判据是 `defaults` 不许丢的承重墙：变异 M10
        （`provision_user_setting` 不再把 `defaults` 递给 `get_or_create`，见
        `tasks/d4/mutate.py`）红的就是这条实测消息（`"'/deep'" not found in 'INSERT INTO …'`），
        把它摘掉则由下面那条行内容断言接住。上面那行列清单的判据钉的是「这一列在 INSERT 的
        列清单里」（Django 的单行 INSERT 恒带全部列，所以它抓不到 M10，它抓的是「列清单解析
        不出来」这种走偏）。
        """
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            resp = self.browse(visitor, '/deep')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_core_verbs(cap), ['SELECT', 'INSERT'], _sqls(cap))
        writes = _write_sqls(cap)
        self.assertEqual(len(writes), 1, writes)
        self.assertTrue(writes[0].lstrip().upper().startswith('INSERT'), writes)
        self.assertIn('sftp_last_path', _insert_columns(writes[0]), writes[0])
        self.assertIn("'/deep'", writes[0], '值没跟着进 INSERT ⇒「一条写」不成立')
        row = self.reload()
        self.assertEqual(row.sftp_last_path, '/deep')

    def test_no_row_browse_with_the_default_path_still_creates_the_row(self):
        """「值等于默认值 + 缺行」不许顺手跳过 —— 这正是「skip when equal」会把
        「还没有行」变成「永远没有行」的形状（改动前后都建行，判据钉住的是**别变成不建**）。"""
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            self.browse(visitor, '/')
        self.assertIn('INSERT', _verbs(cap), _sqls(cap))
        writes = _write_sqls(cap)
        self.assertEqual(len(writes), 1, writes)
        self.assertTrue(writes[0].lstrip().upper().startswith('INSERT'), writes)
        self.assertTrue(UserSetting.objects.filter(user_id=self.user.pk).exists())
        self.assertEqual(self.reload().sftp_last_path, '/')

    def test_nothing_to_record_and_no_row_performs_zero_statements(self):
        """拍板：一个字段都没传 ⇒ 不读不写也不建那条全默认值的空行。

        改动前会发 `SELECT + INSERT` 建出一行（值全是默认，对 断线续连 没有任何信息量）。
        这一支**在生产里不可达** —— 两个调用点永远至少传一个非 `None` 值，所以这里钉的是
        给未来调用方定的规矩；真触发时也不会有读者扑空，因为读这五列的两条通路
        （`auto_connect` / `last_visit`）各自带 `get_or_create`。
        """
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            self.record(visitor)
        self.assertEqual(_verbs(cap), [], _sqls(cap))
        self.assertFalse(UserSetting.objects.filter(user_id=self.user.pk).exists())

    def test_nothing_to_record_with_a_row_performs_zero_statements(self):
        """有行 + 无字段可记 ⇒ 整条调用零语句（改动前这里仍发一条 SELECT 读一遍再什么都不做）。"""
        visitor = self.visitor()
        with CaptureQueriesContext(connection) as cap:
            self.record(visitor)
        self.assertEqual(_verbs(cap), [], _sqls(cap))
        self.assertEqual(_write_sqls(cap), [])

    def test_provisioning_primes_the_instance_cache(self):
        """建行的那次要顺手把行挂进 D1 的实例缓存 ⇒ 同实例第二次「无值可写」时零语句。

        这条同时挡住两种走偏：`QuerySet.update()` 式写（缓存不更新）、
        以及把未落库实例留在缓存里（D1 的 `_state.adding` 毒缓存）。
        """
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        one = _fresh(self.user.pk)
        self.record(one, path='/x')
        with CaptureQueriesContext(connection) as cap:
            self.record(one, path='/x')
        self.assertEqual(_verbs(cap), [], _sqls(cap))
        self.assertEqual(self.reload().sftp_last_path, '/x')
        cached = services._SETTINGS_REL.get_cached_value(one, None)
        self.assertIsNotNone(cached, '建行后没把实例挂回 user 的反向缓存')
        self.assertFalse(cached._state.adding, '缓存里躺着没落库的实例（D1 叫它毒缓存）')
        self.assertEqual(cached.sftp_last_path, '/x')


class MissingRowRaceTests(RecordBase):
    """「本请求看到没有行」与「别的请求建行」之间的那个并发窗口
    （第一轮复审的 Important 1 + Minor 5；下面提到「第 N 轮 Minor …」是为了和第二轮的编号区分）。

    形状真实可达，不是为测试造的：反向描述符对**「没有这一行」也做负缓存**（D1 的
    ``_cached_setting`` 明写这条），而 ``get_or_create`` 命中已有行时走的是 manager 的
    ``.get()`` —— 它**既忽略 ``defaults``、也不碰 ``user._state.fields_cache``**。

    把本请求的值丢掉的是**本轮补之前那版写法**（``get_or_create(user=…, defaults=fields)``
    之后无条件 ``return``）：这一支只发 1 条 SELECT、0 条写，库里停在别的请求写的那值上。
    收敛前那一版**不会**丢，它读完就无条件 ``save`` —— 按模块文档那条配方把函数体换回去、
    在同一次注入下量到 `SELECT + UPDATE`、值落地。
    「让那份陈旧负缓存活完整个请求」倒是两版都有（``_prime_settings_cache`` 的文档就是冲着
    这一支写的，但它当时只接在 ``create=True`` 那一条路上）：第一轮的裁定是把钉缓存收进
    ``provision_user_setting``，``created`` 两个分支共用同一次，所以现树在这一点上比收敛前更好。

    **这个类钉的是哪一种交错（第二轮 Minor 3 的裁定：seam 改了以后两种都要量，别只留一种）**，
    两种都用**两个不同的 User 实例** = 生产里的两个请求，另一个实例建行时用 ``user_id=``
    构造（不挂缓存）：

    * ``_raced(..., prime_read=True)`` —— 本请求在窗口**之前**先只读过一次（``get_user_setting``
      拿描述符探到「没有行」并把它负缓存起来）。今天没有调用点以这个起点进 helper，
      它是「同请求内别处先读过 settings 并扑空」那一类交错的形状，也是第一轮唯一钉着的一支。
    * ``_raced(..., prime_read=False)`` —— 实例缓存从头到尾是冷的：那次缓存咨询发生在
      ``provision_user_setting`` 内部、零 SQL，行在别处已经建好。这是今天 ``list_files`` 与
      手动 ``connect`` 的真实起点；``auto_connect`` 只在**行已存在**时同这个起点（它的
      ``get_or_create`` 走 ``.get()``，不挂缓存），缺行时它把新建的行焐热了缓存，见
      ``AutoConnectWarmCacheTests``。

    第二轮 Minor 4 把缓存咨询收进 ``provision_user_setting`` 之后，**两种交错的形状是同一个**
    ``SELECT + UPDATE``：窗口前读不读那一次，都不在被测的「记录」那一段里多花 SQL
    （那次咨询本身零 SQL），所以两支同数。第一轮只有前者那一支，它的断言于是被当成了生产形状；
    现 seam 下两支都钉住，形状再不是测试造的。
    """

    def _raced(self, other_path, mine_path, *, prime_read=True):
        """→ (本请求的 user 实例, 记录那一段的语句捕获)。三段都走真实 ORM。

        第一次读（``prime_read=True``）刻意落在捕获块**之外**：它是窗口前那一次只读，
        不是被测的那次记录；``prime_read=False`` 就是今天两个调用点的冷缓存起点。
        """
        UserSetting.objects.filter(user_id=self.user.pk).delete()
        visitor = _fresh(self.user.pk)
        if prime_read:
            self.assertIsNone(services.get_user_setting(visitor))  # ⇒ 落下「没有行」的负缓存
        other = _fresh(self.user.pk)                               # 另一个请求 ⇒ 另一个实例
        UserSetting.objects.create(user_id=other.pk, sftp_last_path=other_path)
        with CaptureQueriesContext(connection) as cap:
            self.record(visitor, path=mine_path)
        return visitor, cap

    def test_row_appearing_after_the_read_still_lands_this_request_values(self):
        """并发建行 ⇒ ``created=False``，值必须走「已有行」那套 diff+save 收敛才落得了地。"""
        _visitor, cap = self._raced('/other-req', '/mine')
        self.assertEqual(_core_verbs(cap), ['SELECT', 'UPDATE'], _sqls(cap))
        self.assertEqual(len(_write_sqls(cap)), 1, _sqls(cap))
        # 收敛走的是同一套 diff+save，所以 SET 只含真变的那一列（不是整份 fields）。
        self.assertEqual(_set_columns(_update_sqls(cap)[0]), ['sftp_last_path'])
        self.assertEqual(self.reload().sftp_last_path, '/mine',
                         'defaults 被 get_or_create 的 get 分支吞了 —— 本请求的值没落地')

    def test_cold_cache_produces_the_same_shape_and_the_same_convergence(self):
        """今天两个调用点的真实起点（冷缓存）：形状与上面那条同数，值一样落地。

        这条是第二轮 Minor 3 要的「生产交错」那一支：窗口前的那次只读不存在，缓存咨询就在
        ``provision_user_setting`` 内部（零 SQL），所以记录那一段只剩 ``get_or_create``
        自己那 1 条 SELECT + 收敛的 1 条 UPDATE。
        """
        visitor, cap = self._raced('/other-req', '/mine', prime_read=False)
        self.assertEqual(_core_verbs(cap), ['SELECT', 'UPDATE'], _sqls(cap))
        self.assertEqual(_set_columns(_update_sqls(cap)[0]), ['sftp_last_path'])
        self.assertEqual(self.reload().sftp_last_path, '/mine')
        cached = services._SETTINGS_REL.get_cached_value(visitor, None)
        self.assertIsInstance(cached, UserSetting)
        self.assertEqual(cached.sftp_last_path, '/mine')
        self.assertFalse(cached._state.adding)

    def test_the_race_leaves_no_stale_negative_cache_on_the_instance(self):
        """``.get()`` 分支不挂缓存 ⇒ 必须显式钉一次，否则通路 2/3 整请求读默认值。"""
        visitor, _cap = self._raced('/other-req', '/mine')
        cached = services._SETTINGS_REL.get_cached_value(visitor, None)
        self.assertIsInstance(cached, UserSetting,
                              '并发建行后实例缓存仍是「没有行」的负缓存（陈旧）')
        self.assertEqual(cached.sftp_last_path, '/mine')
        self.assertFalse(cached._state.adding)
        with CaptureQueriesContext(connection) as cap:
            self.assertIs(services.get_user_setting(visitor), cached)
        self.assertEqual(_verbs(cap), [], _sqls(cap))

    def test_race_with_identical_values_still_costs_zero_writes(self):
        """收敛不许过头：并发那行已经带着同一个值 ⇒ 只剩那一次读，不补写。

        改动前这条**同样是绿的**（那时靠 ``get 分支直接 return`` 恰好也是零写），所以它
        不是本修的 red-first 判据，它钉的是修法别退化成「``created=False`` 就无条件 save」
        —— 那种写法在这里会多出一条 UPDATE。
        """
        _visitor, cap = self._raced('/mine', '/mine')
        self.assertEqual(_core_verbs(cap), ['SELECT'], _sqls(cap))
        self.assertEqual(_write_sqls(cap), [])
        self.assertEqual(self.reload().sftp_last_path, '/mine')


class WarmCacheReadFreeTests(RecordBase):
    """比较要读一次；D1 的实例缓存命中时那次读是**零 SQL**（用形状证，不靠散文）。"""

    def test_unchanged_repeat_on_one_instance_costs_no_statement_at_all(self):
        self.record(_fresh(self.user.pk), path='/sub')
        one = _fresh(self.user.pk)
        self.record(one, path='/x')                       # 冷缓存：1 读 + 1 写
        with CaptureQueriesContext(connection) as cap:
            self.record(one, path='/x')                   # 热缓存 + 值未变
        self.assertEqual(_verbs(cap), [], _sqls(cap))

    def test_changed_repeat_on_one_instance_skips_the_read(self):
        one = _fresh(self.user.pk)
        self.record(one, path='/x')                        # 冷：SELECT + UPDATE
        with CaptureQueriesContext(connection) as cap:
            self.record(one, path='/y')                    # 热：只剩 UPDATE
        self.assertEqual(_core_verbs(cap), ['UPDATE'], _sqls(cap))
        self.assertEqual(_set_columns(_update_sqls(cap)[0]), ['sftp_last_path'])
        self.assertEqual(self.reload().sftp_last_path, '/y')


class RecordingFailureContractTests(RecordBase):
    """helper 的 docstring 与 `list_files` 那句注释都是契约：记录失败不许弄坏主流程，也不许静音。

    注入点选 `UserSetting.save`（**不是**把 `_record_last_visit` 整个 patch 掉）——
    那两个调用点的 `try/except` 必须兜得住「收窄后的真实写路径」，
    把被调方换成异常替身做不到这一点（`test.backend.test_sftp_guards::SilentExceptLoggingTests`
    那种写法验的是守卫还在，这里验的是守卫罩得住新形状）。
    """

    def test_browse_still_returns_and_logs_when_the_write_raises(self):
        with mock.patch.object(UserSetting, 'save',
                               side_effect=DatabaseError('database is locked')):
            with self.assertLogs('apps.sftp.views', level='WARNING') as cm:
                resp = self.browse(_fresh(self.user.pk), '/boom')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['path'], '/boom')
        self.assertTrue(any('Failed to record last SFTP path' in line for line in cm.output),
                        cm.output)
        self.assertIsNotNone(cm.records[0].exc_info, '留痕必须带 traceback（exc_info=True）')

    def test_connect_still_returns_and_logs_when_the_write_raises(self):
        payload = {'host': '10.0.0.1', 'port': 22, 'username': 'alice',
                   'password': 'secret'}
        with mock.patch.object(UserSetting, 'save',
                               side_effect=DatabaseError('database is locked')):
            with self.assertLogs('apps.sftp.views', level='WARNING') as cm:
                resp = self.connect(_fresh(self.user.pk), **payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'connected', 'host': '10.0.0.1'})
        self.assertTrue(any('Failed to record last SFTP visit' in line for line in cm.output),
                        cm.output)


class SerializerWhitelistUnaffectedTests(RecordBase):
    """`tests_last_visit.py` 头那句「五列不在序列化器白名单里」今天仍成立（与 D2 无交互）。"""

    def test_last_visit_columns_are_not_exposed_by_the_settings_serializer(self):
        fields = set(UserSettingSerializer.Meta.fields)
        self.assertFalse(fields & set(LAST_VISIT_FIELDS),
                         f'断线续连列进了白名单：{fields & set(LAST_VISIT_FIELDS)}')
        # 浏览只写 `sftp_last_path`，所以设置页的写通路（D2 收窄到变更列）不会被这批准入牵动。
        self.browse(_fresh(self.user.pk), '/sub')
        self.assertEqual(UserSetting.objects.get(user_id=self.user.pk).sftp_last_path, '/sub')
