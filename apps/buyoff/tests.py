"""Buyoff 导出文件名模板测试（默认模板含日期时间戳）。"""

import os
import re

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile

User = get_user_model()


def _filename_from_cd(cd: str) -> str:
    """提取 Content-Disposition 的 filename*= 或 filename= 文件名。"""
    star = re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", cd)
    if star:
        return star.group(1).strip().strip('"')
    plain = re.search(r'filename\s*=\s*"?([^";]+)"?', cd)
    return plain.group(1).strip() if plain else cd

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'Data', 'SampleData')
GAGE_S1_PATH = os.path.join(SAMPLE_DATA_DIR, 'Gage', 'gage_m_S1.csv')


class GenerateFormFilenameTests(APITestCase):
    """POST /api/v1/buyoff/generate_form/ 文件名模板。"""

    def setUp(self):
        self.user = User.objects.create_user(username='buyoffuser', password='pw')
        self.client.force_authenticate(self.user)
        self.files = []
        for i in range(2):
            f = DataFile.objects.create(
                owner=self.user, filename=f'gage_m_S{i + 1}.csv',
                file_path=GAGE_S1_PATH, file_size=os.path.getsize(GAGE_S1_PATH),
                format_type='CTA8290D', status='ready',
            )
            self.files.append(f)

    def test_default_template_contains_datetime(self):
        resp = self.client.post('/api/v1/buyoff/generate_form/',
                                {'file_ids': [f.id for f in self.files],
                                 'role_map': {}}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data if hasattr(resp, 'data') else '')
        cd = resp['Content-Disposition']
        self.assertIsNotNone(
            re.search(r'Buyoff_Form_\d{8}_\d{6}\.xlsx', _filename_from_cd(cd)),
            f'默认模板应含日期时间戳: {cd}',
        )

    def test_custom_template_with_file_count(self):
        resp = self.client.put('/api/v1/auth/settings/',
                               {'export_filename_templates': {
                                   'buyoff': 'BO_{file_count}f'}},
                               format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        resp = self.client.post('/api/v1/buyoff/generate_form/',
                                {'file_ids': [f.id for f in self.files],
                                 'role_map': {}}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_filename_from_cd(resp['Content-Disposition']), 'BO_2f.xlsx')
