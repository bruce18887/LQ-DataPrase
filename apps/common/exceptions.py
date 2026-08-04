"""Custom DRF exception handler — 统一后端错误 JSON 格式。

所有错误响应归一化为:

    {"code": "machine_code", "message": "中文可读消息", "detail": <原始 detail>}

* ``message``  给前端 toast 直接展示（中文）。
* ``code``     稳定的机器码，前端可按分支处理。
* ``detail``   保留 DRF 原始错误结构（向后兼容既有前端代码）。

未捕获的异常（之前返回 Django HTML 错误页，前端无法解析）统一转为
JSON 500，保证 SPA 总能读到响应体。
"""
import logging

from django.conf import settings
from django.http import Http404
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    NotAuthenticated,
    NotFound,
    ParseError,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)

_INTERNAL_ERROR = '服务器内部错误'

# (异常类型, code) -> 中文消息
_KNOWN_EXCEPTIONS = (
    (NotFound, 'not_found', '资源不存在'),
    (PermissionDenied, 'forbidden', '没有权限执行此操作'),
    (AuthenticationFailed, 'unauthorized', '认证失败，请重新登录'),
    (NotAuthenticated, 'unauthorized', '请先登录'),
    (ParseError, 'bad_request', '请求格式错误'),
    (Throttled, 'throttled', '请求过于频繁，请稍后再试'),
    (MethodNotAllowed, 'method_not_allowed', '请求方法不允许'),
)


def _code_for_status(response_status):
    """按 HTTP 状态码推导机器码。"""
    return {
        400: 'bad_request',
        401: 'unauthorized',
        403: 'forbidden',
        404: 'not_found',
        405: 'method_not_allowed',
        429: 'throttled',
        500: 'internal_error',
    }.get(response_status, f'http_{response_status}')


def _first_validation_message(detail):
    """从 ValidationError 的 detail 中提取第一条可读消息。

    detail 可能是字符串 / 列表 / {字段: [消息]} 字典。
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, (list, tuple)):
        return str(detail[0]) if detail else '请求参数校验失败'
    if isinstance(detail, dict):
        for field, msgs in detail.items():
            if isinstance(msgs, str):
                return f'{field}: {msgs}'
            if isinstance(msgs, (list, tuple)) and msgs:
                return f'{field}: {msgs[0]}'
    return '请求参数校验失败'


def _extract_message(exc, response_status):
    """返回 (message, code)，优先用已知异常的中文映射。"""
    if isinstance(exc, Http404):
        return '资源不存在', 'not_found'
    if isinstance(exc, ValidationError):
        return _first_validation_message(exc.detail), 'validation_error'
    for exc_type, code, message in _KNOWN_EXCEPTIONS:
        if isinstance(exc, exc_type):
            return message, code
    if response_status >= 500:
        return _INTERNAL_ERROR, 'internal_error'
    # 其他 DRF 异常：detail 是字符串就直接透传，否则给兜底文案。
    detail = getattr(exc, 'detail', None)
    if isinstance(detail, str) and detail:
        return detail, _code_for_status(response_status)
    return '请求失败', _code_for_status(response_status)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        # 非 APIException 的未捕获异常（ValueError/KeyError 等）：
        # 记录堆栈，转成 JSON 500，替代 Django 的 HTML 错误页。
        logger.error(
            'Unhandled exception in API view: %r', exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        detail = str(exc) if settings.DEBUG else None
        return Response(
            {'code': 'internal_error', 'message': _INTERNAL_ERROR, 'detail': detail},
            status=500,
        )

    message, code = _extract_message(exc, response.status_code)
    response.data = {'code': code, 'message': message, 'detail': response.data}
    return response
