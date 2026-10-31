"""「缺失即建」的只读点收敛到 ``provision_user_setting``（I 波 · 项 6）。

四个端点（``jobs/views.py`` 的 sftp 提交超时、``sftp/views.py`` 的 last_visit / 两个下载
端点）此前各自写 ``UserSetting.objects.get_or_create(user=request.user)``：
与 ``accounts.services.provision_user_setting`` 的差别不在 SQL 条数，而在**已有行**那一支的
缓存后果（裸 ``get_or_create`` 的 ``.get()`` 不挂缓存，helper 会把它钉回 ``request.user``
的反向缓存，同请求后续读取零 SQL）以及「建行入口有一份」这件事本身；缺行那一支两者
都由 ``Model.__init__`` 顺带挂上缓存。

``auto_connect`` **不在**这四站里，继续直接 ``get_or_create``：helper 会把行焐进
``request.user`` 的反向缓存，从而改变 ``_record_last_visit`` 记录段的语句形状（「行已存在」
分支从 1 SELECT + UPDATE 变成零读），而那条形状/新鲜度契约由
``test_sftp_last_visit_writes`` 钉住——缓存预热不是可以顺手做的事。

本文件的判据只钉入口契约里最容易被替换改坏的那一条：**没有行的用户打端点后，行按模型
默认值建出来，端点行为不变**。SQL 条数由 ``test_user_setting_reads.py`` 的
``ProvisioningStatementShapeTests`` 负责，不在这里重复。
"""
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient

from apps.accounts.models import UserSetting
from apps.accounts.services import provision_user_setting
from apps.jobs import executor
from apps.jobs.models import Job
from apps.sftp.views import SftpViewSet

User = get_user_model()
PASSWORD = 'x-provision-12345678'


class _NoRowMixin:
    """建一个**没有** UserSetting 行的用户（打包桌面版首启的真实形态）。"""

    def setUp(self):
        self.user = User.objects.create_user('provision_site', 'ps@localhost', PASSWORD)
        self.assertFalse(UserSetting.objects.filter(user=self.user).exists(),
                         '前提：这个用户的设置行不存在')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _row(self):
        return UserSetting.objects.get(user=self.user)


class JobsSubmitDefaultTimeoutTests(_NoRowMixin, APITestCase):
    """``POST /jobs/sftp_download/`` 省略 timeout ⇒ 读（并建出）默认行。"""

    def test_missing_row_is_created_with_model_defaults(self):
        fake_sftp = mock.MagicMock(name='temp_sftp')
        with mock.patch('apps.jobs.sftp_job._open_temp_sftp', return_value=fake_sftp), \
                mock.patch('apps.jobs.sftp_job.collect_remote_files',
                           return_value=[('/data/BAT01/a.csv', 'a.csv', 10, 0)]), \
                mock.patch.object(executor, 'executor_available', lambda: True), \
                mock.patch.object(executor, 'submit', lambda job, task: None):
            resp = self.client.post('/api/v1/jobs/sftp_download/',
                                    {'path': '/data/BAT01'}, format='json')

        self.assertEqual(resp.status_code, 202, resp.content)
        fake_sftp.close.assert_called_once_with()

        row = self._row()
        default = UserSetting._meta.get_field('sftp_download_timeout').default
        self.assertEqual(row.sftp_download_timeout, default)
        self.assertEqual(row.sftp_last_path, '/')
        self.assertEqual(row.sftp_last_port, 22)

        # 端点行为不变：快照里落的是刚建出来的那行的默认值，不是 None
        job = Job.objects.get(pk=resp.json()['job_id'])
        self.assertEqual(job.params['timeout_sec'], default)


class LastVisitNoRowTests(_NoRowMixin, APITestCase):
    """``GET /sftp/last_visit/`` 的「无记录也 200」是「缺失即建」在读者侧的形状。"""

    def test_missing_row_is_created_with_model_defaults(self):
        resp = self.client.get('/api/v1/sftp/last_visit/')

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['config_name'], '')
        self.assertEqual(body['port'], 22)
        self.assertEqual(body['last_path'], '/')

        row = self._row()
        self.assertEqual(row.sftp_last_config, '')
        self.assertEqual(row.sftp_last_host, '')
        self.assertEqual(row.sftp_last_port, 22)
        self.assertEqual(row.sftp_last_path, '/')


class DownloadDirNoRowTests(_NoRowMixin, APITestCase):
    """``POST /sftp/download_dir/`` 缺行 ⇒ 建出默认行，响应**不变**（仍是 not_connected 400）。

    与既有 sftp 端点用例同一个 seam：patch ``SftpViewSet._get_connection`` 返回 None
    （``test_sftp_guards`` 的 ``_with_connection`` 同源），不新造 mock 层。视图先取默认
    超时（建行）再判连接，所以缺行用户拿到的仍是 400、不是 500。
    """

    def test_missing_row_is_created_and_response_is_unchanged(self):
        with mock.patch.object(SftpViewSet, '_get_connection', return_value=None):
            resp = self.client.post('/api/v1/sftp/download_dir/',
                                    {'path': '/data/BAT01'}, format='json')

        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.json()['code'], 'not_connected')
        row = self._row()
        default = UserSetting._meta.get_field('sftp_download_timeout').default
        self.assertEqual(row.sftp_download_timeout, default)


class ProvisioningEntryTests(_NoRowMixin, APITestCase):
    """对照：helper 本身在缺行时报 ``created=True``，且拿到的是落库的那一行。"""

    def test_provision_reports_created_and_primes_the_row(self):
        setting, created = provision_user_setting(self.user)
        self.assertTrue(created)
        self.assertIsNotNone(setting.pk)
        self.assertEqual(UserSetting.objects.filter(user=self.user).count(), 1)
        # 同实例第二次调用零 SQL 且不再是「新建」
        again, created_again = provision_user_setting(self.user)
        self.assertIs(again, setting)
        self.assertFalse(created_again)
