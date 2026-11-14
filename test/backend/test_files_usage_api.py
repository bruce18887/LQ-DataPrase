"""GET /api/v1/files/usage/ 的端点契约（T1）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_files_usage_api
造树方式与 test_batch_dir_traversal.py:68-72 同一种：临时 MEDIA_ROOT + override_settings，
树本身用 os.makedirs/open 直接写，不走上传流程（上传归 Task 8 的 e2e 管）。
"""
import os
import shutil
import tempfile
from unittest import mock

from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile

PASSWORD = 'x-pass-12345678'
USAGE_URL = '/api/v1/files/usage/'
FIELDS = (
    'data_dir', 'bytes', 'unique_bytes', 'file_count', 'by_type',
    'db_count', 'db_bytes', 'db_bytes_in_root',
    'db_outside_root_count', 'db_outside_root_bytes',
    'mismatch_over_threshold', 'mismatch_diff_bytes', 'scanned_at',
)


class FileUsageApiTests(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-usage-api-')
        self.addCleanup(shutil.rmtree, self.base, True)
        storage_usage.clear_usage_cache()
        self.user = User.objects.create_user('usage_a', 'ua@localhost', PASSWORD)
        self.other = User.objects.create_user('usage_b', 'ub@localhost', PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        # 缓存表是进程全局的，而它的键只有 (username, bucket) —— **不含 MEDIA_ROOT**。
        # 不清的话，后面某个复用同名用户的用例在同一桶里会读到本用例那棵临时树的量。
        storage_usage.clear_usage_cache()

    def _write(self, username, rel, size):
        path = os.path.join(self.base, 'data', username, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'a' * size)
        return path

    def _get(self, **params):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.get(USAGE_URL, params)

    def test_unauthenticated_rejected(self):
        resp = APIClient().get(USAGE_URL)
        self.assertIn(resp.status_code, (401, 403))

    def test_路由没被router的详情路由吞(self):
        """排序判据（订正①）：DefaultRouter 生成的是 `^files/(?P<pk>[^/.]+)/$`，
        `usage` 恰好匹配 `[^/.]+` ⇒ files/usage/ 必须排在 include(router.urls) 之前，
        否则这里拿到的是 404 而不是 200（2026-11-14 把 path 挪到 include 之后实测
        `AssertionError: 404 != 200`，挪之前预探测直接打印 `MATCHED_VIEW=DataFileViewSet
        KWARGS={'pk': 'usage'}`）。
        再加一句 resolver 断言：光看 200 只能证明「有个视图接住了」，证明不了是**这条**
        路由接住的（视图内改成 redirect 也照样 200）。"""
        self.assertEqual(self._get().status_code, 200)
        self.assertEqual(resolve(USAGE_URL).url_name, 'file-usage')

    def test_返回体字段齐全且类型正确(self):
        self._write('usage_a', 'single/a.csv', 2048)
        data = self._get().json()
        # 集合相等而不是逐个 assertIn：逐个判只能发现「少了」，发现不了「多了」——
        # 多摆一个数就是规格 §4.6 否掉的二阶指标，得让它变红。
        self.assertEqual(set(data), set(FIELDS))
        self.assertEqual(data['bytes'], 2048)
        self.assertEqual(data['file_count'], 1)
        self.assertEqual(data['by_type'], {'single': {'bytes': 2048, 'count': 1}})
        self.assertFalse(data['mismatch_over_threshold'])
        self.assertIsInstance(data['scanned_at'], str)

    def test_data_dir指向本人目录(self):
        data = self._get().json()
        self.assertEqual(
            os.path.normpath(data['data_dir']),
            os.path.normpath(os.path.join(self.base, 'data', 'usage_a')),
        )

    def test_没有任何注册行也没有目录时返回零不报错(self):
        data = self._get().json()
        self.assertEqual(data['bytes'], 0)
        self.assertEqual(data['file_count'], 0)
        self.assertEqual(data['db_count'], 0)
        self.assertEqual(data['db_bytes'], 0)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_owner隔离_只看得到自己的目录(self):
        self._write('usage_a', 'single/a.csv', 1000)
        self._write('usage_b', 'single/b.csv', 9000)
        DataFile.objects.create(
            owner=self.other, filename='b.csv',
            file_path='data/usage_b/single/b.csv', file_size=9000,
            format_type='CTA8290D', status='ready',
        )
        mine = self._get().json()
        self.assertEqual(mine['bytes'], 1000)
        self.assertEqual(mine['db_count'], 0)

    def _post_usage(self):
        with self.settings(MEDIA_ROOT=self.base):
            return self.client.post(USAGE_URL, {})

    def test_fresh是白名单_且1会立刻反映新写入(self):
        """`fresh` 的 HTTP 契约在 T1 里原先一句都没有（Task 5 直接调函数、e2e 要到
        Task 8 才有）⇒ 解析写错了没人拦。这里同时钉住白名单本身：
        黑名单写法把 'no' / 'off' / 'TRUE' 全读成「绕缓存」，而绕一次的代价是清掉
        **所有人**的缓存 —— fail-open 的那一侧是共享表，不是调用者自己。

        锁死 monotonic：不锁的话两次 GET 之间跨了 30s 桶边界，第 ② 步会假红 ——
        桶边界每 30 秒来一次，那是定时 flaky 的教科书形状。
        """
        self._write('usage_a', 'single/a.csv', 1000)
        with mock.patch.object(storage_usage.time, 'monotonic', return_value=1_000.0):
            first = self._get().json()['bytes']
            self._write('usage_a', 'single/b.csv', 2000)
            self.assertEqual(self._get().json()['bytes'], first)          # 没带 fresh ⇒ 吃缓存
            # 非白名单一律不许绕。'TRUE' 不在这里面：解析先 strip().lower()，
            # 所以它就是 'true' ⇒ **该**绕（2026-11-14 本条初稿把 TRUE 断成不绕，
            # 是拿判据跟自己的白名单设计打架）。绕一次会清整表，所以白名单那两条放最后。
            for ignored in ('0', 'no', 'off', '', 'False'):
                self.assertEqual(self._get(fresh=ignored).json()['bytes'], first, ignored)
            self.assertEqual(self._get(fresh='1').json()['bytes'], 3000)  # 白名单命中 ⇒ 重扫

    def test_只读不接受POST(self):
        self.assertEqual(self._post_usage().status_code, 405)

    def test_清单外的遗留绝对路径单列一条不混进bytes(self):
        """订正②的形状：遗留绝对路径指向根目录外 ⇒ 只进 db_outside_root_*，
        不进 bytes，也不因为可比集合错位而报一条假的不一致。"""
        self._write('usage_a', 'single/a.csv', 1000)
        # 计划正文漏了这条在根内的注册行，而它自己断言 db_count == 2 /
        # db_bytes_in_root == 1000 —— 没有这条行时那两个数按实现必为 0 与 1，
        # 用例红在数据上而不是红在口径上。按断言的形状补上 a.csv 的注册行。
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/usage_a/single/a.csv', file_size=1000,
            format_type='CTA8290D', status='ready',
        )
        DataFile.objects.create(
            owner=self.user, filename='legacy.csv',
            file_path=os.path.join(self.base, 'legacy', 'legacy.csv'),
            file_size=4000, format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertEqual(data['bytes'], 1000)
        self.assertEqual(data['db_bytes_in_root'], 1000)
        self.assertEqual(data['db_outside_root_count'], 1)
        self.assertEqual(data['db_outside_root_bytes'], 4000)
        self.assertEqual(data['db_count'], 2)
        self.assertFalse(data['mismatch_over_threshold'])

    def test_磁盘与清单差5pct以上时报出不一致(self):
        self._write('usage_a', 'single/a.csv', 1000)
        DataFile.objects.create(
            owner=self.user, filename='a.csv',
            file_path='data/usage_a/single/a.csv', file_size=100,
            format_type='CTA8290D', status='ready',
        )
        data = self._get().json()
        self.assertTrue(data['mismatch_over_threshold'])
        self.assertEqual(data['mismatch_diff_bytes'], 900)

    def test_用户名拼不出安全目录时返回204而不是500(self):
        """终审 F3（2026-11-14 用户拍板走 204）。

        Django 默认的 ``UnicodeUsernameValidator`` 实测**接受** ``..`` 作用户名，而
        ``MEDIA_ROOT/data/..`` 归一化就是 ``MEDIA_ROOT`` —— 所以这一族账号既不能给它扫到别人的树
        （``_user_data_root`` 一直挡着，见 test_storage_usage_scan.py 的 raise 例），
        也不该让它冒成 500：占用是**激活刷新**拉的，500 等于这个人每次进 /data 都吃一条错误 toast，
        而「这个账号的数据根目录不合法」根本不是服务器故障。
        反过来返回一串 0 更糟 —— 那是把「算不出来」谎报成「没占盘」。
        """
        bad = User.objects.create_user('..', 'dd@localhost', PASSWORD)
        client = APIClient()
        client.force_authenticate(user=bad)
        # 先给正常账号铺一棵树：204 这一支不许读到它（同 MEDIA_ROOT 下的另一个目录）
        self._write('usage_a', 'single/a.csv', 1000)
        with self.settings(MEDIA_ROOT=self.base):
            resp = client.get(USAGE_URL)
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b'')
        self.assertIsNone(resp.data)

    def test_安全用户名照旧走完整返回体(self):
        """204 那一支是**白名单式早退**，别把它写成「凡 ValueError 都吞」：
        正常账号（含点号但不是 ..）必须照旧拿到 13 个字段的完整返回体。"""
        dotted = User.objects.create_user('a.b', 'ab@localhost', PASSWORD)
        client = APIClient()
        client.force_authenticate(user=dotted)
        self._write('a.b', 'single/x.csv', 700)
        with self.settings(MEDIA_ROOT=self.base):
            resp = client.get(USAGE_URL)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(set(data), set(FIELDS))
        self.assertEqual(data['bytes'], 700)
        self.assertEqual(data['file_count'], 1)
