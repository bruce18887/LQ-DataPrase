"""统一的密码强度校验入口。

Django 的 ``AUTH_PASSWORD_VALIDATORS`` 只在 Django admin 的表单路径生效；
API 的创建用户 / 自助改密 / 管理员重置都直接 ``set_password``，不会自动触发。
本模块把 ``validate_password`` 包成 DRF 异常，供三条写路径共用。
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


def validate_password_or_raise(password, user=None):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(
            '密码不符合要求：' + '；'.join(exc.messages)
        ) from exc
