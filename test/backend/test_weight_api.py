"""POST /api/v1/weight/parse/ 的契约：守卫、状态码、字段；不测图表。

零落库/零落盘是本端点的**结构性承诺**（spec §4：无 model、无 migration、无 multipart、
不写 MEDIA_ROOT），所以除了「解析对不对」，本模块还钉三件事：
① 请求路径上一条 SQL 都不许发（`assertNumQueries(0)`，比数行数强：读也算违规）；
② 成功后 `DataFile`/`ParseHistory` 行数仍是 0（①的兜底，防止有人改用别的库连接）；
③ 请求前后 `MEDIA_ROOT` 下的文件集合不变，且这条探测器有对照组
   （`media_probe.MediaProbeControlMixin` 报得出新增文件）—— 没有对照组的
   「什么都没发生」断言是可以恒真的。
"""
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402
from apps.datafiles.models import DataFile, ParseHistory  # noqa: E402
from apps.weight.parser import DECLARATION_LIMIT, LENGTH_LIMIT, TEXT_LIMIT  # noqa: E402
from test.backend.media_probe import (  # noqa: E402
    MediaProbeControlMixin, media_paths,
)

URL = '/api/v1/weight/parse/'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
_SINGLE = 'double A[1] = {1.0};\n'


class ParseEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='w-parse', password='x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)   # R6①：Permission 读的是 request._auth

    def _post(self, payload):
        return self.client.post(URL, data=json.dumps(payload),
                                content_type='application/json')

    def test_requires_auth(self):
        anon = APIClient()
        self.assertIn(anon.post(URL, data='{}', content_type='application/json').status_code,
                      (401, 403))

    def test_happy_path_counts(self):
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            r = self._post({'filename': 'trim_weight_ci.csv', 'text': f.read()})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body['group_count'], body['series_count'], body['code_max']), (14, 56, 63))
        self.assertEqual(body['filename'], 'trim_weight_ci.csv')
        self.assertEqual(body['groups'][0]['series'][0]['name'], 'WT0001_1')

    def test_200_body_is_payload_plus_filename(self):
        # 视图承诺 = doc_to_payload() 再加一个 'filename'：键集合必须不多不少
        r = self._post({'filename': 'a.csv', 'text': _SINGLE})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {'code_max', 'group_count', 'series_count', 'groups', 'filename'})
        self.assertEqual(set(body['groups'][0]), {'index', 'name', 'first_row', 'series', 'mean'})
        self.assertEqual(set(body['groups'][0]['series'][0]),
                         {'name', 'source_index', 'declared_length', 'decimals', 'values'})

    def test_error_body_shape(self):
        r = self._post({'filename': 'x.csv', 'text': 'no declarations here\n'})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body['code'], 'no_declaration')
        self.assertIn('message', body)          # detail 为 None 时前端靠 ERROR_CODE_MAP，不靠这层

    def test_mismatch_detail_is_structured(self):
        r = self._post({'filename': 'x.csv', 'text': 'double A[3] = {1.0, 2.0};\n'})
        self.assertEqual(r.status_code, 400)
        d = r.json()['detail']
        self.assertEqual((d['line'], d['name'], d['declared'], d['actual']), (1, 'A', 3, 2))

    def test_bad_number_detail_is_structured(self):
        r = self._post({'filename': 'x.csv', 'text': 'double A[2] = {1.0, 2_0};\n'})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body['code'], 'weight_bad_number')
        self.assertEqual((body['detail']['line'], body['detail']['token']), (1, '2_0'))

    def test_too_large_carries_which_limit_actual(self):
        cases = {
            'text': 'x' * (TEXT_LIMIT + 1),
            'declarations': ''.join(f'double N{n}[1] = {{1.0}};\n' for n in range(DECLARATION_LIMIT + 1)),
            'length': f'double A[{LENGTH_LIMIT + 1}] = {{1.0}};\n',
        }
        for which, text in cases.items():
            r = self._post({'filename': 'x.csv', 'text': text})
            self.assertEqual(r.status_code, 400, which)
            body = r.json()
            self.assertEqual(body['code'], 'weight_too_large', which)
            d = body['detail']
            self.assertEqual(d['which'], which)
            self.assertIn('limit', d, which)
            self.assertIn('actual', d, which)
            if which == 'declarations':
                self.assertEqual((d['limit'], d['actual']), (DECLARATION_LIMIT, DECLARATION_LIMIT + 1))

    def test_missing_fields_are_param_required(self):
        for payload in ({}, {'text': 'double A[1] = {1.0};'}, {'filename': 'a.csv'}):
            r = self._post(payload)
            self.assertEqual(r.status_code, 400, payload)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_guard_body_has_no_message_and_no_detail(self):
        """接线证明：三处守卫（body / text / filename）的 `message`、`detail` 都必须是 None。

        `error_response()` 把非空字符串 detail 复制进 message（`apps/common/errors.py:29`），
        而 `pickMessage` 优先读 message、再读 detail，最后才查 `ERROR_CODE_MAP`
        （`frontend/src/utils/error.ts:60-64`）⇒ 守卫里写英文串（`'text is required'` 这种）
        会让 UI 直接显示英文，中文文案表形同虚设。只断 `code` 抓不到这个回归。
        """
        cases = ({'filename': 'a.csv'}, {'text': _SINGLE}, {}, 'nope', 123)
        for payload in cases:
            body = self._post(payload).json()
            self.assertEqual(body['code'], 'param_required', payload)
            self.assertIsNone(body['message'], payload)
            self.assertIsNone(body['detail'], payload)
            self.assertIn('field', body, payload)     # 机器可读信息走 extra

    def test_non_text_types_are_rejected(self):
        # R3②：不能假设前端已经过滤过
        for bad in (123, [], None, {'a': 1}):
            r = self._post({'filename': 'a.csv', 'text': bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_non_object_body_is_param_required(self):
        # 整个 body 是 JSON 数组/裸标量时 request.data 没有 .get —— 那是 500 的形状，必须挡成 400
        for bad in ([1, 2], 'plain string', 123, None):
            r = self._post(bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()['code'], 'param_required')
            self.assertNotIn('error', r.json())     # 错误形态契约（P1-5）：不许回到裸 error 键

    def test_filename_length_is_capped_not_trusted(self):
        r = self._post({'filename': 'x' * 300, 'text': 'double A[1] = {1.0};\n'})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()['filename']), 120)

    def test_empty_text_and_empty_filename_are_param_required(self):
        for payload in ({'filename': 'a.csv', 'text': ''}, {'filename': '', 'text': _SINGLE}):
            r = self._post(payload)
            self.assertEqual(r.status_code, 400, payload)
            self.assertEqual(r.json()['code'], 'param_required')


class NoSideEffectsTests(MediaProbeControlMixin, TestCase):
    """端点必须**只算不写**：零 SQL、零落盘、无 model。"""

    def setUp(self):
        self.user = User.objects.create_user(username='w-noside', password='x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _post(self, text):
        return self.client.post(URL, data=json.dumps({'filename': 'a.csv', 'text': text}),
                                content_type='application/json')

    def test_parse_issue_files_exist_and_no_models_or_migrations(self):
        # 结构性绊线：Task 4/5 也不许给 apps/weight 加 model/migration（spec §4）
        pkg = Path(_ROOT) / 'apps' / 'weight'   # 用 __file__ 锚，不用 BASE_DIR（development 档会重定向它）
        self.assertFalse((pkg / 'models.py').exists(), 'weight 端点不得有 model')
        self.assertFalse((pkg / 'migrations').exists(), 'weight 端点不得有 migration')

    def test_successful_parse_issues_zero_sql(self):
        before = (DataFile.objects.count(), ParseHistory.objects.count())
        self.assertEqual(before, (0, 0))
        with self.assertNumQueries(0):            # 读也算违规：承诺是「不碰库」
            r = self._post(_SINGLE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((DataFile.objects.count(), ParseHistory.objects.count()), (0, 0))

    def test_error_paths_also_issue_zero_sql(self):
        # 守卫分支同样不许碰库（否则错误路径成了「顺带写一行历史」的入口）
        for text in ('no declaration\n', 'double A[3] = {1.0};\n'):
            with self.subTest(text=text):
                with self.assertNumQueries(0):
                    r = self._post(text)
                self.assertEqual(r.status_code, 400)

    def test_parse_writes_nothing_under_media_root(self):
        before = media_paths()
        r = self._post(_SINGLE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(media_paths(), before)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    sys.exit(1 if DiscoverRunner(verbosity=1).run_tests(['test.backend.test_weight_api']) else 0)
