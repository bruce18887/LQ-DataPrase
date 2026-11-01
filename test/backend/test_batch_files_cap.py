"""B6：``/batch-dirs/`` 每批 ``files`` 明细封顶 500，``files_truncated`` 报省略条数。

前端 ``BatchDataTab`` 直接用 ``group.files.length`` 计数，所以封顶必须同时给出缺口：

* ``files`` 只放最新的 500 条（批内顺序 = ``-created_at, -id``）；
* ``files_truncated`` = 被省略的条数（0 = 全量），前端可据此提示；
* ``registered`` / ``file_count`` 仍按**全量** DB 行与磁盘集合判定，封顶不得影响它们。

runner: ``python -X utf8 manage.py test test.backend.test_batch_files_cap``
"""
import os
import shutil
import tempfile

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.datafiles.models import DataFile
from apps.datafiles.views._helpers import _user_upload_dir

CAP = 500


class BatchDirFilesCapTests(APITestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='lqdp-b6-')
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(username='b6', password='pw')
        self.client.force_authenticate(self.user)
        self.batch_base = _user_upload_dir(self.user, 'batch')

    def _write_csv(self, batch, name):
        path = os.path.join(self.batch_base, batch, 'R1', name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('a,b\n1,2\n')
        return path

    def _create_phantom_rows(self, batch, count):
        rows = [DataFile(
            owner=self.user,
            filename=f'{batch}-{i:04d}.csv',
            file_path=os.path.join(
                self.batch_base, batch, 'R1', f'{batch}-{i:04d}.csv'),
            file_size=8, format_type='CTA8290D', file_type='batch',
            batch_name=batch, status='ready',
        ) for i in range(count)]
        DataFile.objects.bulk_create(rows)

    def _entry(self, name):
        resp = self.client.get('/api/v1/batch-dirs/')
        self.assertEqual(resp.status_code, 200, resp.content)
        return next(e for e in resp.data if e['name'] == name)

    def test_caps_files_and_reports_the_omitted_count(self):
        self._write_csv('LOT-CAP', 'disk.csv')
        self._create_phantom_rows('LOT-CAP', CAP + 3)
        entry = self._entry('LOT-CAP')
        self.assertEqual(len(entry['files']), CAP)
        self.assertEqual(entry['files_truncated'], 3)
        # 批内顺序 -created_at/-id：最新 500 条留下，最老的 3 条被省略
        ids = [f['id'] for f in entry['files']]
        self.assertEqual(ids, list(range(CAP + 3, 3, -1)))

    def test_exactly_at_the_cap_is_not_truncated(self):
        self._write_csv('LOT-EXACT', 'disk.csv')
        self._create_phantom_rows('LOT-EXACT', CAP)
        entry = self._entry('LOT-EXACT')
        self.assertEqual(len(entry['files']), CAP)
        self.assertEqual(entry['files_truncated'], 0)

    def test_cap_is_per_batch_not_global(self):
        self._write_csv('LOT-A', 'disk.csv')
        self._write_csv('LOT-B', 'disk.csv')
        self._create_phantom_rows('LOT-A', CAP + 1)
        self._create_phantom_rows('LOT-B', 3)
        a = self._entry('LOT-A')
        b = self._entry('LOT-B')
        self.assertEqual((len(a['files']), a['files_truncated']), (CAP, 1))
        self.assertEqual((len(b['files']), b['files_truncated']), (3, 0))

    def test_registration_still_uses_every_row_not_just_the_cap(self):
        """被省略的两行恰好是磁盘上的那两个文件：只按截断后的 500 行判定会误报未注册。"""
        real1 = self._write_csv('LOT-REG', 'real1.csv')
        real2 = self._write_csv('LOT-REG', 'real2.csv')
        DataFile.objects.bulk_create([
            DataFile(owner=self.user, filename='real1.csv', file_path=real1,
                     file_size=8, format_type='CTA8290D', file_type='batch',
                     batch_name='LOT-REG', status='ready'),
            DataFile(owner=self.user, filename='real2.csv', file_path=real2,
                     file_size=8, format_type='CTA8290D', file_type='batch',
                     batch_name='LOT-REG', status='ready'),
        ])
        self._create_phantom_rows('LOT-REG', CAP)
        entry = self._entry('LOT-REG')
        self.assertEqual(len(entry['files']), CAP)
        self.assertEqual(entry['files_truncated'], 2)
        self.assertTrue(entry['registered'], '全量集合都已注册，不该因封顶误报')
        self.assertEqual(entry['file_count'], 2)
