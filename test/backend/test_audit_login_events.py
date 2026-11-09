"""登录族审计事件与 `last_login`（spec §5.2 触发点 / §5.3 detail 约定 / §8）。

与本批另一条判据的分工：这里只管「审计表落没落行、落的行内容对不对，以及
`last_login` 到底有没有写」；每条登录分支发几条 SQL 归同目录
`test_login_path_statements.py`，那边还有一条 `accounts_audit_event` 的 INSERT
按**内容**（动词 + 表名成对）钉着，摘掉 `record()` 调用两边各红各的。

三条实现口径：

1. 每条用例独占一个 `REMOTE_ADDR`，并显式抬高 `login` 限速。200/min 是
   unit / development / e2e_slot 三档给的放宽值，多用例共享 127.0.0.1 会互相吃 429；
   而 `SimpleRateThrottle.THROTTLE_RATES` 是 **import 期绑定的类属性**，
   `override_settings` 改不动，只能 `patch.object`（出处：`test_login_throttle.py`
   模块头的约束 1）。那边守档位值的 `test_configured_rate_survives_a_normal_burst`
   本文件一行都不碰。
2. 锁定族的时间期望一律从 `views.LOCKOUT_DURATION` **推导**，不抄字面 15。
   审计 detail 里的 `retry_after_minutes` 是实现按常量算出来的（改常量它就跟着变），
   响应载荷里那两个 15 是**冻结的 API 契约**（前端按它出文案，`apps/accounts/tests.py`
   与既有形状判据钉死）。两个数故意不同源，所以本文件同时钉「审计跟着常量」和
   「载荷仍是 15」：把常量改成 20 分钟时前者跟着红、后者不动；把实现退回字面 15 时
   只有前者红（变异 M5）。
3. `detail.locked_until` 必须是 ISO **字符串**（spec §5.3）。写入器对不可序列化的
   detail 是「整行没 + 一条 warning」（`test_audit_writer.py` 量出来的边界，它不兜）。
   本文件只有 `test_fifth_failure_records_failure_then_lock` 一处把 datetime 交给过
   `detail`（第 5 次失败的 `account_locked`），所以「交 datetime ⇒ 那一行静默丢失」这件事
   只由**那一条**的行数断言接住；其余分支的 detail 只有字符串和整数，交什么上去都落得了行。
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.test import TestCase  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from rest_framework.throttling import SimpleRateThrottle  # noqa: E402

from apps.accounts.models import AuditEvent, User  # noqa: E402
from apps.accounts.views import LOCKOUT_DURATION, MAX_LOGIN_ATTEMPTS  # noqa: E402

PASSWORD = 'x-pass-12345678'
WRONG = 'wrong-pass-12345'
FAST = {'login': '10000/min'}

# 口径 2：审计侧从常量推导，载荷侧的字面 15 是另一回事（两者不同源是刻意的）。
LOCKOUT_MINUTES = int(LOCKOUT_DURATION.total_seconds() // 60)
PAYLOAD_RETRY_AFTER_MINUTES = 15


class LoginEventsTests(TestCase):
    def setUp(self):
        patcher = patch.object(SimpleRateThrottle, 'THROTTLE_RATES', FAST)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.user = User.objects.create_user('ev-user', 'e@localhost', PASSWORD)

    def _post(self, ip, username, password=PASSWORD):
        return self.client.post(
            reverse('login'),
            {'username': username, 'password': password},
            REMOTE_ADDR=ip,
        )

    def _rows(self):
        return list(AuditEvent.objects.order_by('-id').values(
            'event', 'actor_username', 'target_username', 'ip_address', 'detail'))

    def _only_row(self):
        """每个分支各自只落一行 —— 行数断言顺带兜住「detail 不可序列化 ⇒ 整行没」
        （真正交过 datetime 的只有 `account_locked` 那一支，见模块头口径 3），
        以及「同一次登录多记了一笔」（例如把成功事件同时记两遍）。"""
        rows = self._rows()
        self.assertEqual(len(rows), 1, f'该分支应恰好落一行审计，实测 {rows}')
        return rows[0]

    # ------------------------------------------------------------------
    # §8：成功写 last_login；失败不写
    # ------------------------------------------------------------------
    def test_success_writes_last_login_and_one_row(self):
        before = timezone.now()
        resp = self._post('10.98.0.1', 'ev-user')
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertIsNotNone(self.user.last_login,
                             'spec §8：登录成功必须写 last_login（本仓这条 JWT 通路此前从不写它）')
        self.assertGreaterEqual(self.user.last_login, before)
        row = self._only_row()
        self.assertEqual(row['event'], 'login_success')
        self.assertEqual(row['actor_username'], 'ev-user')
        self.assertEqual(row['target_username'], 'ev-user')
        self.assertEqual(row['ip_address'], '10.98.0.1')
        self.assertEqual(row['detail'], {})

    def test_failure_does_not_touch_last_login(self):
        self._post('10.98.0.8', 'ev-user', password=WRONG)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.last_login,
                          '只有成功登录才动 last_login：失败计数不得伪装成「上次登录过」')

    # ------------------------------------------------------------------
    # §5.2/§5.3：四条 login_failure 的 reason，各自一条判据
    # ------------------------------------------------------------------
    def test_unknown_username_records_reason_and_keeps_no_actor(self):
        resp = self._post('10.98.0.2', 'ev-ghost')
        self.assertEqual(resp.status_code, 401)
        row = self._only_row()
        self.assertEqual(row['event'], 'login_failure')
        self.assertEqual(row['detail']['reason'], 'unknown_user')
        self.assertEqual(row['target_username'], 'ev-ghost')
        self.assertEqual(row['actor_username'], '',
                         '登录端点恒匿名（authentication_classes 为空）⇒ 操作者快照必须留空')

    def test_overlong_username_is_truncated_not_500(self):
        resp = self._post('10.98.0.3', 'z' * 400)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(len(self._only_row()['target_username']), 150)

    def test_wrong_password_records_remaining_attempts(self):
        resp = self._post('10.98.0.4', 'ev-user', password=WRONG)
        self.assertEqual(resp.status_code, 401)
        row = self._only_row()
        self.assertEqual(row['event'], 'login_failure')
        self.assertEqual(row['detail']['reason'], 'bad_password')
        self.assertEqual(row['detail']['remaining_attempts'], MAX_LOGIN_ATTEMPTS - 1)
        self.assertEqual(row['target_username'], 'ev-user')
        self.assertEqual(row['ip_address'], '10.98.0.4')

    def test_disabled_and_locked_attempts_record_their_own_reason(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)
        resp = self._post('10.98.0.6', 'ev-user')
        self.assertEqual(resp.status_code, 403)

        User.objects.filter(pk=self.user.pk).update(is_active=True)
        User.objects.filter(pk=self.user.pk).update(
            lockout_until=timezone.now() + timedelta(minutes=5)
        )
        resp = self._post('10.98.0.7', 'ev-user')
        self.assertEqual(resp.status_code, 423)
        # 一记数组同时钉住：两支各只落一行（总数 2）、倒序即时间线（锁定那次更新）、
        # 事件码与 reason 一一对应。分两记写会被「在 login_failure 之前多插一笔」放过
        # —— 那时 `_rows()[0]` 仍是最新那一行，只有整表比对才看得见多出来的那行。
        self.assertEqual(
            [(r['event'], r['detail']['reason'], r['target_username']) for r in self._rows()],
            [('login_failure', 'account_locked', 'ev-user'),
             ('login_failure', 'account_disabled', 'ev-user')],
            self._rows())
        # 审计里的「还要等多久」必须等于用户被告知的那个剩余分钟数，两处同源。
        # 这一支是**剩余**时长（`remaining_minutes`），和第 5 次失败那条的**整段**时长
        # （从 `LOCKOUT_DURATION` 推导）不是同一个量 —— 两条用例各钉各的，别合并。
        self.assertEqual(self._rows()[0]['detail']['retry_after_minutes'],
                         resp.data['retry_after_minutes'])

    # ------------------------------------------------------------------
    # 第 5 次失败：一条 login_failure + 一条 account_locked，顺序即时间线
    # ------------------------------------------------------------------
    def test_fifth_failure_records_failure_then_lock(self):
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            self._post('10.98.0.5', 'ev-user', password=WRONG)
        resp = self._post('10.98.0.5', 'ev-user', password=WRONG)
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(AuditEvent.objects.count(), MAX_LOGIN_ATTEMPTS + 1,
                         '四次失败 + 第五次那两行，多一行少一行都算漂')
        rows = self._rows()
        self.assertEqual([r['event'] for r in rows[:2]],
                         ['account_locked', 'login_failure'],
                         '倒序取最新：锁定必须排在触发它的失败之后（正序时间线 = 先失败后锁定）')
        locked, failure = rows[0], rows[1]
        self.assertEqual(locked['target_username'], 'ev-user')
        self.assertEqual(locked['detail']['retry_after_minutes'], LOCKOUT_MINUTES,
                         'account_locked 的等待时长从 LOCKOUT_DURATION 推导，不抄字面量')
        self.assertEqual(failure['detail']['reason'], 'bad_password')
        self.assertEqual(failure['detail']['remaining_attempts'], 0,
                         '第 5 次失败的 detail 也要留痕（计数已被清零，不记就查不到那次）')
        # detail 必须是 ISO 字符串：交 datetime 的话整行会被写入器咽掉（模块头口径 3），
        # 那时红的是上面的行数断言与本条取值。
        self.assertIsInstance(locked['detail']['locked_until'], str)
        self.assertEqual(locked['detail']['locked_until'], resp.data['locked_until'])
        self.assertIsInstance(
            datetime.fromisoformat(locked['detail']['locked_until']), datetime)
        # 载荷那两个 15 是冻结契约：常量若改，本断言不动，上面那条跟着动（口径 2）。
        self.assertEqual(resp.data['retry_after_minutes'], PAYLOAD_RETRY_AFTER_MINUTES)
