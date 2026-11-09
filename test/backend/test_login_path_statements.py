"""D2 · 登录路径的语句数收敛（2026-10-30 从 `test_accounts_write_paths.py` 拆出）。

本模块只装登录一族；设置页 GET/PUT 的写形状与原子性留在同目录
`test_accounts_write_paths.py`。**两模块合计 20 条用例**（本模块 5 + 那边 15），拆分只挪归属、
不改收集：`scripts/affected-rules.mjs` 的 `AFFECTED_RULES` 里 `['test/backend/', []]` 那条是按
**目录前缀**命中的（不是按文件名），新文件同样落在里面；同文件的 `backendLabels()` 对任何
`test/backend/` 开头的改动回 `test.backend` 标签 ⇒ 受影响门禁的 backend 档照常收到本模块。
两张表的判据本体在 `frontend/test/unit/e2eAffectedDecide.spec.ts`（改判据不开浏览器）。

下面每个数都是本机现量（本轮 2026-11-10 重测，`.venv` = Python 3.13.12 / Django 6.0.9，
`python -X utf8 manage.py test`），不是照抄计划正文；本类 5 条在 `.venv`（6.0.9）与
系统 Python（6.0.5）两台解释器上各跑一遍，动词表与 SQL 形状逐字相同。

**计划正文「成功路径 3 → 2、把 `User.objects.get` 换成 `filter(...).first()` 就少一条」被实测否证**：
两种形状在命中/缺失路径都恰好各 1 条 SELECT（唯一可观察差异是 SQL 形状：`first()` 编译为
`ORDER BY "accounts_user"."id" ASC LIMIT 1`，`get()` 为 MultipleObjectsReturned 探测编译为
`LIMIT 21`，本机 Django 6.0.9 实测），少不掉的是另外两条 —— `ModelBackend.authenticate`
无条件重取同一行（`.venv/Lib/site-packages/django/contrib/auth/backends.py`，`authenticate`
直接调 `get_by_natural_key`，没有任何 `request.user` 复用分支 —— 源码在磁盘上，可复核），以及
`RefreshToken.for_user` 必发的那条 `token_blacklist_outstandingtoken` INSERT（同 venv
`rest_framework_simplejwt/tokens.py`，refresh 轮换+拉黑的前置账，删了它轮换就坏）。
所以 2026-10-30 那次收敛**之前**的成功路径实测 4 条（SELECT+SELECT+UPDATE+INSERT），
计划的「3」只数了前三条。

**2026-11-09 变更（Task 6：登录写 `last_login` + 登录族审计）**：登录成功改为**无条件**写
`last_login`/`login_attempts`/`lockout_until`（spec §8 —— 本仓这条 JWT 登录通路从来没写过
`last_login`：`authenticate()` 走 ModelBackend，它不发 `user_logged_in`，只有
`contrib.auth.login()` 发，而本仓签 JWT 从不调它 ⇒ Django 挂在信号上的 `update_last_login`
接收器一次都没跑过；用户管理页 `UserManagement.vue` 却一直在渲染这列，实际看到的恒是空值。
唯一早就在写它的是 Django admin 登录页 —— 那条要 session 且要 `is_staff`，产品里没有入口，
所以「全仓没有任何通路」这个说法是说过头了，准确口径是「本仓的 JWT 登录通路没有」）。
于是 2026-10-30 立的那条判据「干净账号那条 UPDATE 是 no-op、必须不发」**不再成立**：成功路径
统一是 取行 SELECT + backend 复取 SELECT + UPDATE + outstanding token INSERT + 审计 INSERT
（簿记另算，见下一段）。
「确有东西要清才写」那半句条件，连同它的全部理由（过期 `lockout_until` 没有通路自我修复）
一起删掉 —— 无条件写本来就会清掉它，那半句不再是区分点；过期锁定那条用例保留，改钉**库里的值**。
第二笔新增账是 `apps/accounts/audit.py` 那条审计 INSERT。

**为什么按 DML 序列下判据、干净账号那条还另钉一记完整动词表**：`TestCase` 把每个用例包在
原子块里，`audit.record()` 因此走 `in_atomic_block` 那一支 ⇒ 每笔审计各带一对 SAVEPOINT/RELEASE
簿记（生产上登录跑在 autocommit，只有那条 INSERT —— 那一支的形状归
`test_audit_writer.py::WriterAutocommitShapeTests`，只有 `TransactionTestCase` 量得到）。
只留 DML 一记的漂移风险是 Task 5 评审抓到的（「DML 一记 + 全体一记」拆成两记时，恒真的那记
加上一个只多簿记的变异一起放过了检查）：把簿记从判据里摘掉后，「多包一层原子块」这类变异在
DML 数组上是隐形的。所以干净账号那条用例**额外**把含簿记的完整序列钉一记，两记的分工写在
该用例注释里。审计那条 INSERT 一律按**内容**（动词 INSERT + 目标表名成对）认领，不按位置 ——
位置式取数（`_sqls(cap)[-1]`）在语句顺序变化时会悄悄指到别的语句上，判据当场变恒真。

登录各用例用互不相同的 `REMOTE_ADDR`，避开 `login` 端点 200/min 的 IP 限速与共享 cache 的串扰
（`test_login_throttle.py` 那类用例自己清自己造的风暴，这里不共写一份 cache）。
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import AuditEvent

User = get_user_model()

_DML = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
_AUDIT_TABLE = AuditEvent._meta.db_table


def _verbs(captured):
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


def _dml(captured):
    """语句形状 = DML 序列。SAVEPOINT/RELEASE/BEGIN/COMMIT 是事务簿记，不计入
    （2026-11-09 起登录带审计写入，TestCase 的外层原子块必然产生这一对）。
    簿记并非没人管：干净账号那条用例把含簿记的完整序列也钉了一记。"""
    return [v for v in _verbs(captured) if v in _DML]


def _sqls(captured):
    return [q['sql'] for q in captured.captured_queries]


def _pairs(captured):
    """(动词, SQL) 成对取数 —— 下面几个「按内容认领」的取数函数都走它，
    免得「动词数组第 i 项」与「SQL 数组第 i 项」各自漂。"""
    return list(zip(_verbs(captured), _sqls(captured)))


def _audit_inserts(captured):
    """审计 INSERT：动词是 INSERT **且**目标表是审计表，两个条件成对判定。"""
    return [sql for verb, sql in _pairs(captured)
            if verb == 'INSERT' and f'"{_AUDIT_TABLE}"' in sql]


def _user_updates(captured):
    """针对 `accounts_user` 的 UPDATE（同样动词 + 表名成对判定）。"""
    return [sql for verb, sql in _pairs(captured)
            if verb == 'UPDATE' and '"accounts_user"' in sql]


def _inserts_touching(captured, needle):
    return [sql for verb, sql in _pairs(captured)
            if verb == 'INSERT' and needle in sql]


class LoginPathTests(TestCase):
    """成功路径形状：两条 SELECT + 一条 UPDATE + 两条 INSERT（其一是审计）。
    含簿记的完整序列另钉一记；缺失/密码错误路径各多一条审计 INSERT。错误包络不是一视同仁：
    缺失路径钉整个 JSON（那段的文案是前端直接显示的），密码错误只钉 `code` 与
    `remaining_attempts` 两项 —— `apps/accounts/tests.py` 的登录族用例已经把同样两项钉过一遍，
    本模块只补「这条分支现在多了一条审计 INSERT」，不重复包络判据。"""

    PASSWORD = 'x-pass-12345678'

    def _post(self, ip, username, password=None):
        # 每条用例独占一个 REMOTE_ADDR：ScopedRateThrottle('login') 按 IP 计数，
        # 共享 127.0.0.1 会把本类与 test_login_throttle 的预算搅在一起。
        return self.client.post(reverse('login'),
                                {'username': username,
                                 'password': password or self.PASSWORD},
                                REMOTE_ADDR=ip)

    def test_login_success_clean_account_shape(self):
        User.objects.create_user(username='d2-login-ok', password=self.PASSWORD)
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.11', 'd2-login-ok')
        verbs = _dml(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())
        # ① 形状（DML）：取行 + backend 复取 + last_login UPDATE + outstanding INSERT + 审计 INSERT
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'INSERT'],
                         f'成功路径形状：取行 + backend 复取 + last_login UPDATE + '
                         f'outstanding INSERT + 审计 INSERT，实测 {verbs}')
        # ② 完整序列（含事务簿记）—— 管的是 ① 看不见的那一类：审计写入器多包/少包一层原子块
        #    （`record()` 的 `in_atomic_block` 分支被改坏）、或有人给整个 `post()` 套上
        #    `atomic()`，两种都只动簿记、不动 DML 序列。
        self.assertEqual(_verbs(cap),
                         ['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'SAVEPOINT', 'INSERT', 'RELEASE'],
                         f'含簿记的完整序列，实测 {_verbs(cap)}')
        # ③ 两条 INSERT 各自按内容认领（一条审计表、一条 outstanding token 表），各一
        #    正好填满 ① 里那两个 INSERT 槽 ⇒ 既不许多一笔，也不许把哪一笔换成别的表。
        self.assertEqual(len(_audit_inserts(cap)), 1, _sqls(cap))
        self.assertEqual(len(_inserts_touching(cap, 'token_blacklist_outstandingtoken')), 1,
                         _sqls(cap))
        # `filter().first()` 与 `get()` 的唯一可观察差异在 SQL 形状（本机 Django 6.0.9 实测：
        # first() 编译为 `ORDER BY "accounts_user"."id" ASC LIMIT 1`；get() 为了
        # MultipleObjectsReturned 探测编译为 `LIMIT 21`、无 ORDER BY）。backend 那条
        # get_by_natural_key 保持 `LIMIT 21` 形状不动（「别动 authenticate」的可读证据）。
        # 把视图取行还原成 `User.objects.get` ⇒ 视图那条也变 `LIMIT 21` ⇒ 本断言红。
        view_sql = _sqls(cap)[0]
        self.assertIn('ASC LIMIT 1', view_sql, f'视图取行必须是 .first() 形状：{view_sql}')
        # 那条 UPDATE 必须是 `update_fields` 的三列窄写，不是全行 `save()`：
        # 退回不带 update_fields 的 `user.save()` ⇒ SET 里多出 password/username/role… ⇒ 本条红。
        updates = _user_updates(cap)
        self.assertEqual(len(updates), 1, updates)
        for column in ('"last_login" =', '"login_attempts" =', '"lockout_until" ='):
            self.assertIn(column, updates[0], updates[0])
        self.assertNotIn('"password" =', updates[0],
                         f'成功路径不许全行写（会把内存里的旧值盖回库）：{updates[0]}')

    def test_login_success_reset_path_still_writes(self):
        user = User.objects.create_user(username='d2-login-dirty', password=self.PASSWORD)
        user.login_attempts = 2
        user.lockout_until = None
        user.save()
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.12', 'd2-login-dirty')
        verbs = _dml(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'INSERT'],
                         f'带失败计数的账号成功路径形状（与干净账号同形：写是无条件的），'
                         f'实测 {verbs}')
        user.refresh_from_db()
        self.assertEqual(user.login_attempts, 0)

    def test_login_success_clears_an_expired_lockout(self):
        """过期 `lockout_until` 现在由**无条件写**清掉（2026-11-09 起它不再是半个条件）。

        本用例的存在理由换了但没有消失：2026-10-30 它钉的是「`or lockout_until is not None`
        那半句不许删」（复评审 Critical）；半句已随无条件写一起删掉，它改钉**库里的值**。
        仍然有牙的是「把写做回条件」那类回归 —— 只看 `login_attempts`（过期锁定的账号 attempts
        恰为 0 ⇒ 干脆不写，过期值永久留在库里并随 `UserSerializer` 的载荷一次次下发：登录判定
        看 `> timezone.now()` 早就不管它、DRF 两条序列化通路把它钉成 read_only、前端
        `UserManagement.vue` 的 `isLocked()` 也按 `> now` 判 ⇒ 页面上连「解锁」按钮都不出现，
        `unlock` 从页面上到不了），或者整句删掉。两种形状都在本条红：动词表少那条 UPDATE，
        或 `lockout_until` 仍是那个过期时刻。
        """
        user = User.objects.create_user(username='d2-login-expired', password=self.PASSWORD)
        user.login_attempts = 0
        # 余量按**小时**给，不给 1 分钟：本模块没有 freezegun（requirements 里就没装），
        # 而这条用例的前提是「库里那条戳**已经**过期」—— 机器被打满时一次 setUp + 请求
        # 停摆超过 60 s 就会让戳重新变成「未过期」，那时红的是 `status_code == 200`
        # （登录端返回 423），报的是假回归。hours=1 让同一个停摆要放大到 1 小时才翻得动前提。
        user.lockout_until = timezone.now() - timedelta(hours=1)
        user.save()

        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.15', 'd2-login-expired')
        verbs = _dml(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT', 'INSERT'],
            f'过期锁定的成功路径与干净账号同形（写是无条件的），实测 {verbs}')
        self.assertEqual(len(_audit_inserts(cap)), 1, _sqls(cap))
        user.refresh_from_db()
        self.assertIsNone(user.lockout_until,
                          '锁定期过了就得把 lockout_until 清回 None：过期后没有任何通路会碰它，'
                          '留着就是一条永远随 UserSerializer 下发的过期锁定时刻')
        self.assertEqual(user.login_attempts, 0)
        self.assertIsNotNone(user.last_login)

    def test_login_user_not_found_shape_and_envelope(self):
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.13', 'ghost-d2')
        verbs = _dml(cap)
        self.assertEqual(verbs, ['SELECT', 'INSERT'],
                         f'缺失路径 = 视图 SELECT + 审计 INSERT，实测 {verbs}')
        self.assertEqual(len(_audit_inserts(cap)), 1, _sqls(cap))
        # 还原成 `User.objects.get` ⇒ **只有本条红**：两种形状都恰好 1 条 SELECT（模块头
        # 实测过），动词数组与审计 INSERT 计数都不动，变的只有 SQL 文本 —— `first()` 的
        # `ASC LIMIT 1` 对比 `get()` 为 MultipleObjectsReturned 探测准备的 `LIMIT 21`。
        self.assertIn('ASC LIMIT 1', _sqls(cap)[0])
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {
            'code': 'user_not_found',
            'message': '用户名「ghost-d2」不存在，请确认后重试',
            'detail': '用户名「ghost-d2」不存在，请确认后重试',
        })

    def test_login_wrong_password_shape_unchanged(self):
        User.objects.create_user(username='d2-login-badpw', password=self.PASSWORD)
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.14', 'd2-login-badpw', password='wrong-pass-12345678')
        verbs = _dml(cap)
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT'],
                         f'密码错误 = 视图 SELECT + backend SELECT + 计数 UPDATE + 审计 INSERT，'
                         f'实测 {verbs}')
        self.assertEqual(len(_audit_inserts(cap)), 1, _sqls(cap))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['code'], 'invalid_credentials')
        self.assertEqual(resp.json()['remaining_attempts'], 4)
        self.assertEqual(User.objects.get(username='d2-login-badpw').login_attempts, 1)
        self.assertIsNone(User.objects.get(username='d2-login-badpw').last_login,
                          '失败计数那条 UPDATE 不许顺手写 last_login（spec §8：失败不算登录过）')
