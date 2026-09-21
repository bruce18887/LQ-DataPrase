"""搜索预设的 CRUD 与跨用户隔离（spec §3.10）。

跑法：``python manage.py test apps.sftp.tests_search_preset``

三条不该被代码漂移掉的契约：

1. **保存前必须先过一遍 ``parse_spec``** —— 预设里存一个跑不通的 spec，等于给用户
   一个点了才报错的按钮（``search`` 端点会拒的东西，预设必须更早拒）。
2. **跨用户不可见 / 不可改 / 不可删**（仿 ``apps/sftp/tests.py`` 的
   ``SftpConfigOwnerIsolationTests`` 既有契约），列表也不回 ``owner`` 字段。
3. **每人上限 50 条**（``contracts.PRESET_MAX_PER_USER``，数字只在那儿定义一次）。

上限与「同名覆盖」必须能共存：夹在中间的那条（已达上限但改的是自己已有的预设）
若被上限分支误伤，用户改了条件就再也存不回去。
"""
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.sftp.models import SftpSearchPreset
from apps.sftp.search.contracts import PRESET_MAX_PER_USER

# 项目换过 AUTH_USER_MODEL（accounts.User），照抄计划的 contrib import 会炸
# "Manager isn't available"（同 tests_search.py 的那处修正）。
User = get_user_model()

LIST = '/api/v1/sftp/search_presets/'
SAVE = '/api/v1/sftp/search_presets/save/'
DELETE = '/api/v1/sftp/search_presets/delete/'

SPEC = {'roots': ['/data'], 'mode': 'content', 'term': 'ShadowReg2',
        'name_pattern': '*RT*.csv', 'depth': 'all'}


class PresetBase(APITestCase):
    def setUp(self):
        self.a = User.objects.create_user('a', password='pw')
        self.b = User.objects.create_user('b', password='pw')
        self.client.force_authenticate(self.a)

    def save(self, name='x', spec=SPEC, **extra):
        return self.client.post(SAVE, {'name': name, 'spec': spec, **extra},
                                format='json')


class AuthTests(PresetBase):
    def test_endpoints_require_auth(self):
        self.client.force_authenticate(None)
        for method, url in (('get', LIST), ('post', SAVE), ('post', DELETE)):
            resp = getattr(self.client, method)(url, {}, format='json')
            self.assertIn(resp.status_code, (401, 403), f'{method.upper()} {url}')


class CreateTests(PresetBase):
    def test_create_returns_201_and_persists(self):
        resp = self.save('找 RT')
        self.assertEqual(resp.status_code, 201, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.filter(owner=self.a).count(), 1)
        row = SftpSearchPreset.objects.get(owner=self.a)
        self.assertEqual(row.name, '找 RT')
        self.assertEqual(row.spec, SPEC, 'spec 必须原样存回，不做静默改写')

    def test_empty_name_is_400(self):
        self.assertEqual(self.save('').status_code, 400)
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_whitespace_only_name_is_400(self):
        """``'   '`` 是「空名字」的另一种写法：不 strip 就会存出一条渲染成空白的预设。"""
        self.assertEqual(self.save('   ').status_code, 400)
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_name_over_80_chars_is_400(self):
        """模型是 ``max_length=80``：视图不拦的话 SQLite 静默存超长、真库直接 500。"""
        self.assertEqual(self.save('n' * 81).status_code, 400)
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_invalid_spec_is_400_not_saved(self):
        """预设里存一个跑不通的 spec，等于给用户一个必定失败的按钮。"""
        resp = self.client.post(SAVE, {'name': 'x', 'spec': {'mode': 'name'}},
                                format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_unknown_spec_key_is_400(self):
        resp = self.save(spec={**SPEC, 'recursive': True})
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_missing_spec_is_400(self):
        resp = self.client.post(SAVE, {'name': 'x'}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_non_dict_spec_is_400(self):
        """``parse_spec`` 对非 dict 抛的是 SearchSpecError，视图不能先 TypeError 500。"""
        for bad in (['/data'], 'ShadowReg2', 7, None):
            resp = self.save(spec=bad)
            self.assertEqual(resp.status_code, 400, f'spec={bad!r} → {resp.data}')
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_error_body_shape_matches_search_endpoint(self):
        """校验失败一律 ``400 {'error': msg}``（spec §3.11），不是 DRF 那套 code/detail。"""
        resp = self.save('x', spec={'mode': 'name'})
        self.assertEqual(list(resp.data.keys()), ['error'])
        self.assertIsInstance(resp.data['error'], str)


class OverwriteTests(PresetBase):
    def test_same_name_overwrites_spec(self):
        self.save('n')
        resp = self.save('n', spec={**SPEC, 'term': 'Vcc'})
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.filter(owner=self.a).count(), 1)
        self.assertEqual(
            SftpSearchPreset.objects.get(owner=self.a).spec['term'], 'Vcc')

    def test_overwrite_false_rejects_an_existing_name(self):
        """「另存为」语义：显式 overwrite=False 时同名不悄悄吃掉旧预设。"""
        self.save('n', spec={**SPEC, 'term': 'old'})
        resp = self.save('n', spec={**SPEC, 'term': 'new'}, overwrite=False)
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('已存在', str(resp.data))
        self.assertEqual(
            SftpSearchPreset.objects.get(owner=self.a).spec['term'], 'old',
            '拒绝就必须一字不改')

    def test_overwrite_false_allows_a_brand_new_name(self):
        resp = self.save('fresh', overwrite=False)
        self.assertEqual(resp.status_code, 201, getattr(resp, 'data', resp))

    def test_different_users_keep_their_own_names(self):
        self.save('n')
        self.client.force_authenticate(self.b)
        self.assertEqual(self.save('n').status_code, 201)
        self.assertEqual(SftpSearchPreset.objects.count(), 2)


class CapTests(PresetBase):
    def _fill(self):
        for i in range(PRESET_MAX_PER_USER):
            self.save(f'p{i}')

    def test_per_user_cap(self):
        self._fill()
        resp = self.save(f'p{PRESET_MAX_PER_USER}')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('上限', str(resp.data))
        self.assertEqual(
            SftpSearchPreset.objects.filter(owner=self.a).count(),
            PRESET_MAX_PER_USER)

    def test_at_cap_own_preset_can_still_be_updated(self):
        """上限挡新名字，不能挡「改自己已有的那条」，否则用户永远存不回去。"""
        self._fill()
        resp = self.save('p0', spec={**SPEC, 'term': 'Vcc'})
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.get(owner=self.a, name='p0')
                         .spec['term'], 'Vcc')

    def test_cap_is_per_user_not_global(self):
        self._fill()
        self.client.force_authenticate(self.b)
        self.assertEqual(self.save('someone-else').status_code, 201)


class ListTests(PresetBase):
    def test_list_only_returns_own_presets(self):
        self.save('mine')
        self.client.force_authenticate(self.b)
        self.assertEqual(self.client.get(LIST).data['presets'], [])

    def test_list_returns_no_owner_field(self):
        self.save()
        data = self.client.get(LIST).data['presets'][0]
        self.assertNotIn('owner', data)
        self.assertEqual(set(data), {'id', 'name', 'spec', 'updated_at'})

    def test_list_carries_the_spec_verbatim(self):
        """载入预设 = 把 spec 原样回填表单，前端不发第二次请求。"""
        self.save('找 RT')
        data = self.client.get(LIST).data['presets'][0]
        self.assertEqual(data['spec'], SPEC)
        self.assertEqual(data['name'], '找 RT')

    def test_list_is_ordered_by_recently_updated(self):
        """Meta ordering=['-updated_at']：最近改过的排最前。"""
        self.save('old')
        self.save('new')
        names = [p['name'] for p in self.client.get(LIST).data['presets']]
        self.assertEqual(names, ['new', 'old'])


class DeleteTests(PresetBase):
    def test_cannot_delete_another_users_preset(self):
        self.save()
        pid = SftpSearchPreset.objects.get().id
        self.client.force_authenticate(self.b)
        self.assertEqual(
            self.client.post(DELETE, {'id': pid}, format='json').status_code, 404)
        self.assertTrue(SftpSearchPreset.objects.filter(id=pid).exists())

    def test_cannot_update_another_users_preset(self):
        """同名即覆盖的写法必须 owner-scoped：否则 b 存一个 a 的名字就覆盖了 a 的预设。"""
        self.save('n', spec={**SPEC, 'term': 'a-term'})
        pid = SftpSearchPreset.objects.get().id
        self.client.force_authenticate(self.b)
        self.assertEqual(self.save('n', spec={**SPEC, 'term': 'b-term'}).status_code,
                         201)
        self.assertEqual(SftpSearchPreset.objects.get(id=pid).spec['term'], 'a-term')

    def test_delete_own_returns_deleted_true(self):
        self.save()
        pid = SftpSearchPreset.objects.get().id
        resp = self.client.post(DELETE, {'id': pid}, format='json')
        self.assertEqual(resp.data['deleted'], True)
        self.assertFalse(SftpSearchPreset.objects.filter(id=pid).exists())

    def test_delete_missing_id_is_404(self):
        resp = self.client.post(DELETE, {'id': 999999}, format='json')
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.data['error'], '未找到预设')

    def test_delete_without_id_is_400(self):
        """缺参数是 400（客户端错），不能和「没有这条预设」的 404 混成一个。"""
        self.assertEqual(
            self.client.post(DELETE, {}, format='json').status_code, 400)

    def test_delete_non_numeric_id_is_400_not_500(self):
        """``id='abc'`` 在 SQLite 上会直接抛 ValueError → 500 页。"""
        resp = self.client.post(DELETE, {'id': 'abc'}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertEqual(SftpSearchPreset.objects.count(), 0)

    def test_deleting_frees_a_slot_under_the_cap(self):
        for i in range(PRESET_MAX_PER_USER):
            self.save(f'p{i}')
        pid = SftpSearchPreset.objects.filter(name='p0').get().id
        self.client.post(DELETE, {'id': pid}, format='json')
        self.assertEqual(self.save('p-after-delete').status_code, 201)
