"""管理员跨用户只读清单（T1）：``?owner_id=`` 与 ``/admin/files/users/``。

契约（唯一事实来源：``docs/superpowers/specs/2026-11-22-gap-review-knife2-4`` 的 Task 4）：
- ``FEATURE_PERMISSIONS['data_view_all'] = ['administrator']``；
- ``GET /api/v1/files/?owner_id=<id>`` 只在 ``action == 'list'`` 且具备
  ``data_view_all`` 时把清单换成目标用户的；无权限却带 ``owner_id`` ⇒ 403；
  ``owner_id`` 非整数 ⇒ 400 ``validation_error``；
- **只放开清单**：详情 ``GET /files/<他人 id>/`` 与其它 action（options 等）仍
  只看 ``owner=request.user``；
- ``GET /api/v1/admin/files/users/``：管理员 200 / 普通用户 403 / 匿名 401，
  只列启用账号、按 id 升序、每人带 ``get_user_usage`` 的占用（不安全用户名 ⇒ null）。

Run directly: .venv/Scripts/python.exe -X utf8 manage.py test test.backend.test_admin_files_api
造盘方式与 test_files_usage_api.py 同一种：临时 MEDIA_ROOT + override_settings，
树用 os.makedirs/open 直接写，不走上传流程。
"""
import os
import shutil
import tempfile

from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles import storage_usage
from apps.datafiles.models import DataFile

PASSWORD = 'x-pass-12345678'
FILES_URL = '/api/v1/files/'
USERS_URL = '/api/v1/admin/files/users/'
USAGE_FIELDS = ('bytes', 'jobs_bytes', 'total_bytes')
ROW_FIELDS = {'id', 'username', 'display_name', 'role', 'is_active', 'usage'}


class AdminScopeBase(TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix='lqdp-admin-scope-')
        self.addCleanup(shutil.rmtree, self.base, True)
        # 占用缓存是进程全局的，键只有 (username, bucket) —— **不含 MEDIA_ROOT**，
        # 不清的话同名的另一个用例会在同一个桶里读到上一棵临时树的量。
        storage_usage.clear_usage_cache()
        self.admin = User.objects.create_user(
            'scope_admin', 'sa@localhost', PASSWORD, role='administrator')
        self.plain = User.objects.create_user('scope_plain', 'sp@localhost', PASSWORD)
        self.target = User.objects.create_user('scope_target', 'st@localhost', PASSWORD)
        self.own = self._seed_file(self.admin, 'admin.csv')
        self.theirs = self._seed_file(self.target, 'target.csv')

    def tearDown(self):
        storage_usage.clear_usage_cache()

    def _seed_file(self, owner, filename):
        return DataFile.objects.create(
            owner=owner, filename=filename,
            file_path=f'data/{owner.username}/single/{filename}',
            file_size=128, format_type='CTA8290D', status='ready',
        )

    def _client(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def _write(self, rel, size):
        path = os.path.join(self.base, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as fh:
            fh.write(b'a' * size)
        return path


class ScopedFileListTests(AdminScopeBase):
    def test_管理员带owner_id只列出目标用户文件(self):
        resp = self._client(self.admin).get(FILES_URL, {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results']
        self.assertEqual({row['id'] for row in rows}, {self.theirs.id})
        self.assertEqual({row['owner'] for row in rows}, {self.target.username})

    def test_跨用户清单仍是列表序列化器不含file_path与metadata(self):
        """放开的是「看清单」：``file_path``/``metadata`` 只属于详情序列化器，
        跨用户清单不能顺带把它们带出去（那等于给管理员开了另一条详情通道）。"""
        resp = self._client(self.admin).get(FILES_URL, {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        row = resp.data['results'][0]
        self.assertNotIn('file_path', row)
        self.assertNotIn('metadata', row)

    def test_普通用户带owner_id被拒403(self):
        resp = self._client(self.plain).get(FILES_URL, {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data['code'], 'forbidden')

    def test_普通用户带非法owner_id也403而不是400(self):
        """先鉴权再解析：非管理员不该从「400 还是 403」反问出他人 id 的取值范围。"""
        resp = self._client(self.plain).get(FILES_URL, {'owner_id': 'abc'})
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data['code'], 'forbidden')

    def test_owner_id非整数400(self):
        resp = self._client(self.admin).get(FILES_URL, {'owner_id': 'abc'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(resp.data['code'], 'validation_error')
        self.assertEqual(resp.data['message'], 'owner_id: 必须是整数')

    def test_匿名带owner_id401(self):
        resp = self._client().get(FILES_URL, {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.data['code'], 'unauthorized')

    def test_管理员不带owner_id仍只看自己(self):
        resp = self._client(self.admin).get(FILES_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual({row['id'] for row in resp.data['results']}, {self.own.id})

    def test_空owner_id按未传处理(self):
        """``?owner_id=`` 空白 = 没筛选（前端把未选中序列化成空串时不应 400），
        也绝不能被读成「0 号用户」而返回空集。"""
        resp = self._client(self.admin).get(FILES_URL + '?owner_id=')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual({row['id'] for row in resp.data['results']}, {self.own.id})

    def test_管理员看他人文件详情仍404(self):
        resp = self._client(self.admin).get(f'{FILES_URL}{self.theirs.id}/')
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.data['code'], 'not_found')

    def test_非list动作不受owner_id影响(self):
        """``options``（下拉清单）是 @action，不是 list ⇒ 即便带了 owner_id
        也只能看见自己的文件：放开口径只落在 list 这一个动作上。"""
        resp = self._client(self.admin).get(
            f'{FILES_URL}options/', {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual({row['id'] for row in resp.data['results']}, {self.own.id})

    def test_owner_id搜索标签时不混入管理员自己的命中行(self):
        """``?owner_id`` 已把清单换成目标用户的集：搜索的标签兜底若仍按
        ``owner=request.user`` 自己重查一遍再并集回来，管理员自己的标签命中行
        就会混进他人清单。两人标签同名、文件名都不含搜索词，命中只能来自标签。"""
        DataFile.objects.filter(pk=self.own.id).update(tags=['shared'])
        DataFile.objects.filter(pk=self.theirs.id).update(tags=['shared'])
        resp = self._client(self.admin).get(
            FILES_URL, {'owner_id': self.target.id, 'search': 'shared'})
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.data['results']
        self.assertEqual({row['id'] for row in rows}, {self.theirs.id})
        self.assertEqual({row['owner'] for row in rows}, {self.target.username})


class AdminScopeDoesNotLeakIntoNonListActionsTests(AdminScopeBase):
    """``?owner_id=`` 只放开清单，详情 / 删除 / 改标签仍只看自己的文件。

    「只放开 list」的反证：没有这三条，把 ``admin_scope.py`` 里
    ``_resolve_scope_owner_id`` 的 ``action != 'list'`` 删掉仍然全绿 —— 而那样
    管理员就能读他人详情的 ``file_path``/``metadata``、删他人文件、改他人标签。
    三条都**带 owner_id** 且取**目标用户的 id**（不是文件 id）：带上错人的 id 时
    作用域是「一个没有文件的用户」，404 与判定无关，变异仍会绿。
    """

    def test_详情带owner_id仍404(self):
        resp = self._client(self.admin).get(
            f'{FILES_URL}{self.theirs.id}/', {'owner_id': self.target.id})
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.data['code'], 'not_found')

    def test_删除带owner_id仍404且目标文件还在(self):
        resp = self._client(self.admin).delete(
            f'{FILES_URL}{self.theirs.id}/?owner_id={self.target.id}')
        self.assertEqual(resp.status_code, 404, resp.content)
        self.assertEqual(resp.data['code'], 'not_found')
        self.assertTrue(DataFile.objects.filter(pk=self.theirs.id).exists(),
                        '跨用户删除必须挡在 get_object 的 404 上，不能真删')

    def test_改标签带owner_id仍404且标签未变(self):
        """``set_tags`` 是 ``@action(detail=True, methods=['post'])``（见
        ``file_views.py``），与详情同经 ``get_queryset`` 的 owner 作用域。"""
        resp = self._client(self.admin).post(
            f'{FILES_URL}{self.theirs.id}/set_tags/?owner_id={self.target.id}',
            {'tags': ['leak']}, format='json')
        self.assertIn(resp.status_code, (404, 405), resp.content)
        self.theirs.refresh_from_db()
        self.assertEqual(self.theirs.tags or [], [], '跨用户改标签必须一个字都没写进去')


SPA_ADMIN_PATTERN = r'^admin/(?:users|audit|files)/?$'


class AdminFilesSpaRouteTests(TestCase):
    """``/admin/files`` 的整页刷新通路（单端口形态）。

    Vite dev server 自带 history fallback，e2e 走的永远是它 ⇒「这条路径有没有交给
    SPA」在浏览器里**不可判**（testing-gates §2 的 T1 优先）。判据取 ``resolve().route``：
    命中的必须是 SPA 白名单正则本身，而不是 ``path('admin/', admin.site.urls)`` 的
    catch-all —— 后者会把整页加载 302 到 ``/admin/login/``（2026-11-11 部署实测）。
    """

    def test_admin_files命中SPA白名单而不是django_admin(self):
        match = resolve('/admin/files')
        self.assertEqual(match.route, SPA_ADMIN_PATTERN)
        # 白名单挂的视图就是 SPA 壳（TemplateView(index.html)），不是 admin 的 redirect。
        self.assertEqual(match.func.view_initkwargs['template_name'], 'index.html')

    def test_带尾斜杠同样命中(self):
        self.assertEqual(resolve('/admin/files/').route, SPA_ADMIN_PATTERN)

    def test_白名单三兄弟共用同一条正则(self):
        for path in ('/admin/users', '/admin/audit', '/admin/files'):
            with self.subTest(path=path):
                self.assertEqual(resolve(path).route, SPA_ADMIN_PATTERN)

    def test_admin根仍归django_admin(self):
        """白名单只放开三个精确路径：``/admin/`` 本身不许被顺手交出去。

        两条判据分开断：``route`` 不相等只能证明「不是那条正则」，若正则将来
        被改写（例如变成 catch-all 前缀），这一条会假绿；``app_name == 'admin'``
        钉住它确实还在 Django admin 的命名空间里。
        """
        match = resolve('/admin/')
        self.assertNotEqual(match.route, SPA_ADMIN_PATTERN)
        self.assertEqual(match.app_name, 'admin')


class AdminUserUsageListTests(AdminScopeBase):
    def test_管理员200且路由与返回形状正确(self):
        resp = self._client(self.admin).get(USERS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        # 200 只能证明「有个视图接住了」；resolver 断言证明接住的是这条路由
        # （DefaultRouter 的详情路由会吞 ``files/<pk>/`` 形状，这类排序错误
        # 只有 url_name 才拦得住，见 test_files_usage_api 的同款判据）。
        self.assertEqual(resolve(USERS_URL).url_name, 'admin-file-users')
        results = resp.data['results']
        self.assertTrue(results)
        for row in results:
            self.assertEqual(set(row), ROW_FIELDS, row)
        ids = [row['id'] for row in results]
        self.assertEqual(ids, sorted(ids), '用户清单必须按 id 升序')
        usernames = [row['username'] for row in results]
        self.assertEqual(
            set(usernames),
            {'scope_admin', 'scope_plain', 'scope_target'},
        )

    def test_只列启用账号(self):
        disabled = User.objects.create_user(
            'scope_off', 'so@localhost', PASSWORD, is_active=False)
        rows = self._client(self.admin).get(USERS_URL).data['results']
        self.assertNotIn(disabled.id, [row['id'] for row in rows])
        self.assertTrue(all(row['is_active'] for row in rows))

    def test_普通用户403(self):
        resp = self._client(self.plain).get(USERS_URL)
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.data['code'], 'forbidden')

    def test_匿名401(self):
        resp = self._client().get(USERS_URL)
        self.assertEqual(resp.status_code, 401, resp.content)
        self.assertEqual(resp.data['code'], 'unauthorized')

    def test_usage含data与jobs三段计数(self):
        self._write('data/scope_target/single/a.csv', 1000)
        self._write(f'jobs/{self.target.id}/9/out.csv', 2000)
        with self.settings(MEDIA_ROOT=self.base):
            rows = self._client(self.admin).get(USERS_URL).data['results']
        row = next(r for r in rows if r['id'] == self.target.id)
        usage = row['usage']
        self.assertIsNotNone(usage)
        for key in USAGE_FIELDS:
            self.assertIn(key, usage, key)
            self.assertIsInstance(usage[key], int, key)
        self.assertEqual(usage['bytes'], 1000)
        self.assertEqual(usage['jobs_bytes'], 2000)
        self.assertEqual(usage['total_bytes'], 3000)

    def test_不安全用户名的usage为None(self):
        """``..`` 拼不出安全的数据根目录（``_user_data_root`` 抛 ValueError）——
        单个账号算不出来既不能让整份清单 500，也不能谎报 0。"""
        unsafe = User.objects.create_user('..', 'dd@localhost', PASSWORD)
        with self.settings(MEDIA_ROOT=self.base):
            resp = self._client(self.admin).get(USERS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = {row['username']: row for row in resp.data['results']}
        self.assertIn('..', rows)
        self.assertIsNone(rows['..']['usage'])
        self.assertEqual(rows['..']['id'], unsafe.id)
        # 同一份清单里其他人照旧有数（不是「一坏全坏」的实现）。
        self.assertIsNotNone(rows['scope_target']['usage'])
        self.assertIn('total_bytes', rows['scope_target']['usage'])
