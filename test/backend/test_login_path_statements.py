"""D2 · 登录路径的语句数收敛（2026-10-30 从 `test_accounts_write_paths.py` 拆出）。

本模块只装登录一族；设置页 GET/PUT 的写形状与原子性留在同目录
`test_accounts_write_paths.py`。**两模块合计 20 条用例**（本模块 5 + 那边 15），拆分只挪归属、
不改收集：`scripts/affected-rules.mjs:74` 那条 `['test/backend/', []]` 是按**目录前缀**命中的（不是按
文件名），新文件同样落在里面；同文件的 `backendLabels()`（258-266 行）对任何 `test/backend/` 开头的
改动回 `test.backend` 标签 ⇒ 受影响门禁的 backend 档照常收到本模块。本轮实测：
`node tasks/d2r/affected_probe.mjs` 打出 `matchRule=[]` + `backendLabels=["test.backend"]`
（那份 log 与下面引用的变异 log 都在 gitignored 的 `tasks/` 里，只在本机存在；判据本体在库里）。

下面每个数都是本机现量（2026-10-30，`.venv` = Python 3.13.12 / Django 6.0.9，
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
所以 HEAD 成功路径实测是 **4 条**（SELECT+SELECT+UPDATE+INSERT），计划的「3」只数了前三条。

**真正的收敛来自第 3 条本身**：干净账号（`login_attempts=0` 且无 `lockout_until`）成功后那句
`user.save()` 写回的全是库里已有的默认值 —— 一条纯 no-op 的 UPDATE。改成「确有重置要做才写」
⇒ 干净账号成功路径 4 → 3（下界就是 3：两条 SELECT + 一条 INSERT 各自都有上面的出处，删不动）；
真需要重置的账号仍写那条 UPDATE（4 条），判据单钉，防止将错就错把该写的也跳掉。

**「确有东西要清」= `login_attempts or lockout_until is not None`**，后半句的理由（2026-10-30
按复评审 Important 2 更正过 —— 原文写「前端用户列表里就是一个『仍在锁定』的残影」**不成立**，
`frontend/src/pages/admin/UserManagement.vue` 的 `isLocked()` 判的是 `> now`，过期值在那里
压根不渲染成锁定）：锁定期**已过期**、`login_attempts` 又是 0 的账号看上去干净，但那条过期值
**没有任何通路会自我修复** —— 本视图的锁定判定看 `> timezone.now()`（`views.py:122`，过期即
放行、不写回）；DRF 两条序列化通路把 `lockout_until` 钉成 read_only（`serializers.py:31`、
`:55`），API 写不掉；前端管理页的「解锁」按钮 `v-if="isLocked(row)"` 同样按 `> now` 判
⇒ 过期后连点它的机会都没有，`unlock` 那条唯一的 API 清除通路从页面上到不了。
留下的实际代价是：**这条过期值永远留在库里，并随 `UserSerializer` 的载荷（用户列表接口，
`serializers.py:29` 的 fields 里有它）一次次下发**；今天唯一**看得见**它的界面是 Django admin
（`admin.py:17` 的 `list_display` 与 `:23` 的 fieldset 都列了 `lockout_until`）。
摘掉后半句 ⇒ 那条 UPDATE 消失（变异见 `tasks/d2r/mut_lockout_cond.log`）。

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

User = get_user_model()


def _verbs(captured):
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


def _sqls(captured):
    return [q['sql'] for q in captured.captured_queries]


class LoginPathTests(TestCase):
    """成功路径 4 → 3（干净账号）；需要重置的仍写；缺失路径形状与错误包络一字不变。"""

    PASSWORD = 'x-pass-12345678'

    def _post(self, ip, username, password=None):
        # 每条用例独占一个 REMOTE_ADDR：ScopedRateThrottle('login') 按 IP 计数，
        # 共享 127.0.0.1 会把本类与 test_login_throttle 的预算搅在一起。
        return self.client.post(reverse('login'),
                                {'username': username,
                                 'password': password or self.PASSWORD},
                                REMOTE_ADDR=ip)

    def test_login_success_clean_account_costs_three_statements(self):
        User.objects.create_user(username='d2-login-ok', password=self.PASSWORD)
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.11', 'd2-login-ok')
        verbs = _verbs(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'INSERT'],
                         f'干净账号成功路径应为 取行 + backend 复取 + outstanding INSERT，实测 {verbs}')
        self.assertEqual(_verbs(cap).count('UPDATE'), 0,
                         'login_attempts/lockout 已是默认值 ⇒ 那条 UPDATE 是 no-op，必须不发')
        # `filter().first()` 与 `get()` 的唯一可观察差异在 SQL 形状（本机 Django 6.0.9 实测：
        # first() 编译为 `ORDER BY "accounts_user"."id" ASC LIMIT 1`；get() 为了
        # MultipleObjectsReturned 探测编译为 `LIMIT 21`、无 ORDER BY）。backend 那条
        # get_by_natural_key 保持 `LIMIT 21` 形状不动（「别动 authenticate」的可读证据）。
        # 把视图取行还原成 `User.objects.get` ⇒ 视图那条也变 `LIMIT 21` ⇒ 本断言红。
        view_sql = _sqls(cap)[0]
        self.assertIn('ASC LIMIT 1', view_sql, f'视图取行必须是 .first() 形状：{view_sql}')
        self.assertIn('token_blacklist_outstandingtoken', _sqls(cap)[2])

    def test_login_success_reset_path_still_writes(self):
        user = User.objects.create_user(username='d2-login-dirty', password=self.PASSWORD)
        user.login_attempts = 2
        user.lockout_until = None
        user.save()
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.12', 'd2-login-dirty')
        verbs = _verbs(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT'],
                         f'确有重置要做时仍须写那行 user，实测 {verbs}')
        user.refresh_from_db()
        self.assertEqual(user.login_attempts, 0)

    def test_login_success_clears_an_expired_lockout_and_still_writes(self):
        """`or user.lockout_until is not None` 那半句的存在理由（复评审 Critical）。

        锁定期**已过期**、`login_attempts` 又是 0 的账号，看上去「干净」，但库里还挂着一条
        过期的 `lockout_until`：只有那半句条件让它被清掉。少了它，登录成功仍返回 200、
        `login_attempts` 本来就是 0 ⇒ 库里那条过期锁定**永远留着**（过期后没有任何通路会碰它：
        登录判定看 `> now`、DRF 侧 read_only、前端 `isLocked()` 也看 `> now` 所以连「解锁」
        按钮都不出现），并随 `UserSerializer` 在用户列表载荷里一次次下发。
        删掉那半句（变异 M7）⇒ **第一条**断言红：动词表少了那条 UPDATE，实测 3 条；
        第二条（`lockout_until is None`）在同一变异下同红，只是轮不到它跑。
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
        verbs = _verbs(cap)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            verbs, ['SELECT', 'SELECT', 'UPDATE', 'INSERT'],
            f'过期锁定也算「确有东西要清」，成功登录必须仍写那条重置 UPDATE，实测 {verbs}')
        user.refresh_from_db()
        self.assertIsNone(user.lockout_until,
                          '锁定期过了就得把 lockout_until 清回 None：没人会自我修复它，'
                          '留着就是一条永远随 UserSerializer 下发的过期锁定时刻')
        self.assertEqual(user.login_attempts, 0)

    def test_login_user_not_found_shape_and_envelope(self):
        with CaptureQueriesContext(connection) as cap:
            resp = self._post('10.99.0.13', 'ghost-d2')
        verbs = _verbs(cap)
        self.assertEqual(verbs, ['SELECT'], f'缺失路径与 HEAD 平价（1 SELECT），实测 {verbs}')
        self.assertIn('ASC LIMIT 1', _sqls(cap)[0])   # get→first 还原 ⇒ 变 LIMIT 21，这条与上一条一起红
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
        verbs = _verbs(cap)
        self.assertEqual(verbs, ['SELECT', 'SELECT', 'UPDATE'],
                         f'失败计数路径不许被收敛顺手改坏（HEAD 实测同形），动词表 {verbs}')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['code'], 'invalid_credentials')
        self.assertEqual(resp.json()['remaining_attempts'], 4)
        self.assertEqual(User.objects.get(username='d2-login-badpw').login_attempts, 1)
