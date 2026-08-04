"""Tests for the custom DRF exception handler in apps/common/exceptions.py.

Covers the unified error JSON shape:

    {"code": str, "message": str, "detail": any}

* ``message`` is always a human-readable Chinese string for the frontend toast
* ``code``   is a stable machine code
* ``detail`` keeps the original DRF payload (backwards compatible)
* uncaught exceptions become JSON 500 responses instead of HTML error pages

Run with:
    .venv\\Scripts\\python.exe manage.py test test.backend.test_exception_handler
"""
import unittest

from django.http import Http404
from django.test import override_settings
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    MethodNotAllowed,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.test import APIRequestFactory

from apps.common.exceptions import custom_exception_handler

# 无异常被抛出时传入的 context（DRF 仅在 Throttled 等场景才读取 context）。
EMPTY_CONTEXT = {}


def _handle(exc):
    return custom_exception_handler(exc, EMPTY_CONTEXT)


class TestExceptionHandlerShape(unittest.TestCase):
    """所有错误响应都必须带 code/message/detail 三个字段。"""

    def test_validation_error_dict(self):
        resp = _handle(ValidationError({'username': ['用户名已存在']}))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['code'], 'validation_error')
        self.assertEqual(resp.data['message'], 'username: 用户名已存在')
        self.assertIn('username', resp.data['detail'])

    def test_validation_error_string(self):
        resp = _handle(ValidationError('tags 必须是列表'))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data['message'], 'tags 必须是列表')

    def test_validation_error_takes_first_field(self):
        resp = _handle(ValidationError({'a': ['错误A'], 'b': ['错误B']}))
        self.assertEqual(resp.data['message'], 'a: 错误A')

    def test_not_found_is_chinese(self):
        resp = _handle(NotFound())
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data['code'], 'not_found')
        self.assertEqual(resp.data['message'], '资源不存在')

    def test_permission_denied(self):
        resp = _handle(PermissionDenied())
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(resp.data['code'], 'forbidden')
        self.assertEqual(resp.data['message'], '没有权限执行此操作')

    def test_authentication_failed(self):
        resp = _handle(AuthenticationFailed())
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(resp.data['code'], 'unauthorized')
        self.assertEqual(resp.data['message'], '认证失败，请重新登录')

    def test_method_not_allowed(self):
        resp = _handle(MethodNotAllowed('POST'))
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(resp.data['code'], 'method_not_allowed')
        self.assertEqual(resp.data['message'], '请求方法不允许')

    def test_custom_api_exception_detail_passthrough(self):
        """其他 DRF 异常：字符串 detail 直接作为 message。"""

        class CustomErr(APIException):
            status_code = 422
            default_detail = '自定义业务错误'

        resp = _handle(CustomErr())
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.data['message'], '自定义业务错误')
        self.assertEqual(resp.data['code'], 'http_422')


class TestUnhandledException(unittest.TestCase):
    """未捕获异常必须转成 JSON 500，而不是 Django HTML 错误页。"""

    @override_settings(DEBUG=True)
    def test_value_error_becomes_json_500_debug(self):
        """DEBUG=True 时 detail 携带原始信息便于排查。"""
        resp = _handle(ValueError('boom'))
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(resp.data['code'], 'internal_error')
        self.assertEqual(resp.data['message'], '服务器内部错误')
        self.assertEqual(resp.data['detail'], 'boom')

    def test_value_error_becomes_json_500_production(self):
        """非 DEBUG 时不泄露内部异常细节。"""
        resp = _handle(ValueError('boom'))
        self.assertEqual(resp.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(resp.data['code'], 'internal_error')
        self.assertEqual(resp.data['message'], '服务器内部错误')
        self.assertIsNone(resp.data['detail'])


class TestHttp404(unittest.TestCase):
    """get_object_or_404 抛出的 Http404 也应得到中文 404。"""

    def test_http404_is_chinese(self):
        resp = _handle(Http404())
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data['message'], '资源不存在')


class TestThroughAPIRequest(unittest.TestCase):
    """端到端：经 APIRequestFactory 确认 handler 在真实请求链路可用。"""

    def test_request_context_does_not_break_handler(self):
        request = APIRequestFactory().get('/api/v1/files/1/')
        resp = custom_exception_handler(NotFound(), {'request': request})
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(resp.data['message'], '资源不存在')
