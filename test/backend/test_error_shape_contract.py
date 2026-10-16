"""错误形态契约（架构评审 P1-5）。

后端曾并存四种错误形态：全局处理器的 ``{code,message,detail}``、视图里 148 处
``Response({'error': 机器码})``、登录侧 ``{code,detail}``、SFTP 连接侧
``{status:'error'}``。前端的 ``utils/error.ts`` 因此必须留一条 ``data.error`` 兜底分支 ——
而那个键名又和「成功响应体里的 per-item error 字段」撞名，谁都不能删。

本用例把收敛结果钉住：AST 扫描禁止视图再产出 ``Response({'error': ...})``，
并用真实守卫分支验证形态与附加字段。

判据用 AST 而不是 grep：grep 会把 ``errors.py`` 自己解释历史的 docstring 也数成违规，
一个天天假红的护栏最后没人看。**已知盲区**：先把 dict 存进变量再
``Response(body)`` 的写法 AST 认不出来 —— 那条要靠 review，不靠这条扫描假装全覆盖。

刻意**不**管的三种（各有独立语义，别顺手改）：
* SSE 帧 ``{'event':'error'}`` / ``{'kind':'error'}``（流内错误事件，不是 HTTP 错误体）；
* 200 响应体内的 ``details[].error`` / ``level:'error'``（per-item / 告警级别字段）；
* ``status='error'`` 枚举值（数据模型与修复中心的行状态）。
"""
import ast
import types
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

APPS_DIR = Path(__file__).resolve().parents[2] / 'apps'


def _production_sources():
    for path in sorted(APPS_DIR.rglob('*.py')):
        name = path.name
        if name.startswith('test') or 'tests' in name.split('_'):
            continue
        if 'migrations' in path.parts:
            continue
        yield path


def _legacy_error_responses(path):
    """返回该文件里 ``Response({'error': ...})`` 的行号（含跨行与嵌套 dict）。"""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func_name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
        if func_name != 'Response':
            continue
        body = node.args[0]
        if not isinstance(body, ast.Dict):
            continue
        keys = [k.value for k in body.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if 'error' in keys:
            lines.append(node.lineno)
    return lines


def _fake_user():
    return types.SimpleNamespace(
        pk=1, is_authenticated=True, is_active=True, is_anonymous=False,
        is_staff=False, is_superuser=False, settings=None,
    )


def post_view(url, payload, view_method):
    """POST 一个已认证请求并渲染响应（守卫分支不碰 DB，故用 SimpleTestCase）。"""
    request = APIRequestFactory().post(url, payload, format='json')
    force_authenticate(request, user=_fake_user())
    response = view_method(request)
    response.render()
    return response


class NoLegacyErrorShapeInViewsTests(SimpleTestCase):
    """``Response({'error': ...})`` 这种写法必须清零。"""

    def test_no_view_returns_the_legacy_error_key(self):
        offenders = []
        for path in _production_sources():
            for lineno in _legacy_error_responses(path):
                offenders.append(f'{path.relative_to(APPS_DIR.parent)}:{lineno}')
        self.assertEqual(
            offenders, [],
            '视图必须用 apps/common/errors.py::error_response（产出 {code,message,detail}），'
            "不得再手写 Response({'error': ...}) —— 它和成功响应体里的 error 字段撞名")


class UnifiedErrorEnvelopeTests(SimpleTestCase):
    """守卫分支的真实形态：三个键齐全、附加字段按原名保留。"""

    def test_missing_file_id_yields_the_unified_envelope(self):
        """无 file_id → 走 _load_df_from_request 的守卫，机器码原样保留。"""
        from apps.analysis.views import AnalysisViewSet

        response = post_view(
            '/api/v1/analysis/cpk/', {},
            AnalysisViewSet.as_view({'post': 'cpk'}))

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            set(response.data), {'code', 'message', 'detail'},
            '错误体只允许这三个键（附加上下文另算，见上一条用例）')
        self.assertEqual(response.data['code'], 'file_id_required')
        # 只有机器码、没有中文时 message 留空，由前端 ERROR_CODE_MAP 查表 ——
        # 后端不再复制一份中文表（两份必漂）
        self.assertIsNone(response.data['message'])

    def test_detail_text_is_mirrored_into_message(self):
        """有中文 detail 时 message 直接取它，让 curl/脚本也读得出话。"""
        import pandas as pd
        from apps.analysis.test_support import fake_datafile, patch_df_loader
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}
        restore = patch_df_loader(df, fake_datafile(), metadata)
        try:
            response = post_view(
                '/api/v1/analysis/histogram/',
                {'file_id': 1, 'range_type': 'CL',
                 'params': ['Param0'], 'custom_low': 5, 'custom_high': 1},
                AnalysisViewSet.as_view({'post': 'histogram'}))
        finally:
            restore()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data['code'], 'invalid_custom_limits')
        self.assertEqual(response.data['message'], '自定义下限不能大于上限')
        self.assertEqual(response.data['detail'], '自定义下限不能大于上限')

    def test_structured_context_keys_survive_the_conversion(self):
        """``requested`` / ``missing`` 是前端按名读的字段，改造时必须原样保留。"""
        import pandas as pd
        from apps.analysis.test_support import fake_datafile, patch_df_loader
        from apps.analysis.views import AnalysisViewSet

        df = pd.DataFrame({'Param0': [1.0, 2.0, 3.0]})
        metadata = {'format': 'CTA8290D', 'mins': {}, 'maxs': {}, 'units': {}}
        restore = patch_df_loader(df, fake_datafile(), metadata)
        try:
            response = post_view(
                '/api/v1/analysis/cpk/', {'file_id': 1, 'params': ['GONE']},
                AnalysisViewSet.as_view({'post': 'cpk'}))
        finally:
            restore()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data['code'], 'param_not_found')
        self.assertEqual(response.data['requested'], ['GONE'])
        self.assertEqual(response.data['missing'], ['GONE'])


class LoginEnvelopeTests(SimpleTestCase):
    """登录侧的 ``_error`` 现在只是 error_response 的一层薄壳。"""

    def test_login_error_carries_three_keys_plus_extras(self):
        from django.core.cache import cache
        from apps.accounts.views import LoginView

        # 空 body → 序列化不过 → missing_credentials 分支（不查库，SimpleTestCase 够用）
        cache.clear()   # 登录有 ScopedRateThrottle('login')，别攒到 5 次/min 的上限
        request = APIRequestFactory().post('/api/v1/auth/login/', {}, format='json')
        response = LoginView.as_view()(request)
        response.render()

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.data['code'], 'missing_credentials')
        self.assertTrue(response.data['message'], '登录侧 detail 是中文，必须镜像进 message')
        self.assertEqual(response.data['detail'], response.data['message'])
        # 附加字段键名不得改：LoginPage.vue 按 missing_fields / remaining_attempts 分支
        self.assertEqual(sorted(response.data['missing_fields']), ['password', 'username'])
