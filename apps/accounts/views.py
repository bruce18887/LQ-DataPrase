from datetime import timedelta

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserSetting
from .permissions import FeaturePermission
from .serializers import (
    LoginSerializer,
    TokenResponseSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
    UserSerializer,
    UserSettingSerializer,
)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)

# Stable error codes the front-end branches on. Never rename — the
# front-end LoginPage.vue switches on these strings to pick a Chinese
# user-facing message.
LOGIN_ERROR_CODES = {
    'MISSING_CREDENTIALS': 'missing_credentials',
    'USER_NOT_FOUND': 'user_not_found',
    'INVALID_CREDENTIALS': 'invalid_credentials',
    'ACCOUNT_DISABLED': 'account_disabled',
    'ACCOUNT_LOCKED': 'account_locked',
}


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


def _error(code, detail, *, status_code, **extra):
    """Standard error envelope so the front-end can pattern-match
    on ``code`` without parsing free-form ``detail`` text."""
    body = {'code': code, 'detail': detail}
    body.update(extra)
    return Response(body, status=status_code)


class LoginView(APIView):
    permission_classes = [AllowAny]
    # Login may take a beat (LDAP/SSO/etc) but not the full 30s axios
    # timeout. Keep the server's hard limit tight so the user gets a
    # meaningful "server slow" error rather than the generic timeout.
    authentication_classes: list = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            missing = []
            for field in ('username', 'password'):
                if not serializer.validated_data.get(field):
                    missing.append(field)
            return _error(
                LOGIN_ERROR_CODES['MISSING_CREDENTIALS'],
                f'请填写 {"、".join(missing) if missing else "用户名和密码"}',
                status_code=status.HTTP_400_BAD_REQUEST,
                missing_fields=missing,
            )

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return _error(
                LOGIN_ERROR_CODES['USER_NOT_FOUND'],
                f'用户名「{username}」不存在，请确认后重试',
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        # Disabled account is checked before lockout so the user gets a
        # stable, fixable message ("ask the admin to re-enable") rather
        # than a confusing "try again in 15 minutes".
        if not user.is_active:
            return _error(
                LOGIN_ERROR_CODES['ACCOUNT_DISABLED'],
                '账号已被禁用，请联系管理员',
                status_code=status.HTTP_403_FORBIDDEN,
            )

        if user.lockout_until and user.lockout_until > timezone.now():
            remaining_minutes = max(
                1, (user.lockout_until - timezone.now()).seconds // 60 + 1
            )
            return _error(
                LOGIN_ERROR_CODES['ACCOUNT_LOCKED'],
                f'登录失败次数过多，账号已被锁定，请在 {remaining_minutes} 分钟后重试',
                status_code=status.HTTP_423_LOCKED,
                retry_after_minutes=remaining_minutes,
                locked_until=user.lockout_until.isoformat(),
            )

        authenticated_user = authenticate(
            request, username=username, password=password
        )

        if authenticated_user is None:
            user.login_attempts += 1
            if user.login_attempts >= MAX_LOGIN_ATTEMPTS:
                user.lockout_until = timezone.now() + LOCKOUT_DURATION
                user.login_attempts = 0
                user.save()
                return _error(
                    LOGIN_ERROR_CODES['ACCOUNT_LOCKED'],
                    f'连续 {MAX_LOGIN_ATTEMPTS} 次登录失败，账号已被锁定 15 分钟',
                    status_code=status.HTTP_423_LOCKED,
                    retry_after_minutes=15,
                    locked_until=user.lockout_until.isoformat(),
                )
            user.save()
            remaining = MAX_LOGIN_ATTEMPTS - user.login_attempts
            return _error(
                LOGIN_ERROR_CODES['INVALID_CREDENTIALS'],
                '密码错误，请重试',
                status_code=status.HTTP_401_UNAUTHORIZED,
                remaining_attempts=remaining,
            )

        user.login_attempts = 0
        user.lockout_until = None
        user.save()

        tokens = get_tokens_for_user(user)

        response_data = TokenResponseSerializer({
            'token': tokens['access'],
            'user_id': user.id,
            'username': user.username,
            'role': user.role,
            'display_name': user.display_name,
        })

        return Response({
            **response_data.data,
            'refresh': tokens['refresh'],
        })


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        return Response({'detail': 'Successfully logged out.'})


class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def put(self, request):
        # UserProfileSerializer, not UserSerializer: this endpoint is open to
        # every authenticated user, so role/is_active/username must not be
        # writable here (self-promotion to administrator was a single PUT away).
        serializer = UserProfileSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserSettingsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        settings, _ = UserSetting.objects.get_or_create(user=request.user)
        serializer = UserSettingSerializer(settings)
        return Response(serializer.data)

    def put(self, request):
        settings, _ = UserSetting.objects.get_or_create(user=request.user)
        serializer = UserSettingSerializer(
            settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class UserManagementViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [IsAuthenticated, FeaturePermission]
    required_feature = 'user_management'

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def update(self, request, *args, **kwargs):
        """
        Force ``partial=True`` on PUT as well. DRF's default
        ``ModelViewSet.update()`` hard-codes ``partial=False`` when
        forwarding to ``get_serializer()``, so a plain
        ``get_serializer`` override that sets ``partial=True`` by
        default is silently ignored on PUT. The front-end
        ``UserManagement.vue`` calls ``PUT /auth/users/<id>/ {is_active:
        false}`` to disable a user — a *partial* update — and we
        need the same lax semantics as ``UserProfileView.put()`` and
        DRF's built-in PATCH handler.
        """
        kwargs['partial'] = True
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        self._guard_lockout(
            self.request, serializer.instance, serializer.validated_data
        )
        serializer.save()

    def perform_destroy(self, instance):
        # 删除没有 serializer，构造等价的「停用」变更集交给同一守卫。
        self._guard_lockout(self.request, instance, {'is_active': False})
        instance.delete()

    @staticmethod
    def _guard_lockout(request, target, changes):
        """拒绝会把请求者自己、或整个系统锁在门外的改动。

        ``changes`` 是本次实际写入的字段（部分更新时只含请求体出现的键），
        缺的键回落到目标当前值。管理员一旦被停用，登录端点会在
        ``authenticate()`` 之前直接 403（``account_disabled``），SimpleJWT
        也会立刻吊销其 token，事后只能直连数据库改回来 —— 所以这里必须拦。

        规则二实际只拦「唯一管理员把*自己*降级掉角色」：请求者必然已是
        启用的管理员（SimpleJWT 挡住停用者），目标非自己时请求者本人就在
        ``exclude(pk=target)`` 里，该规则不可能成立。
        """
        role = changes.get('role', target.role)
        is_active = changes.get('is_active', target.is_active)

        if target.pk == request.user.pk and not is_active:
            raise ValidationError('不能禁用或删除自己的账号')

        loses_admin = (
            target.role == 'administrator'
            and target.is_active
            and not (role == 'administrator' and is_active)
        )
        still_another = (
            User.objects.filter(role='administrator', is_active=True)
            .exclude(pk=target.pk)
            .exists()
        )
        if loses_admin and not still_another:
            raise ValidationError('系统必须保留至少一个启用的管理员')

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        user = self.get_object()
        new_password = request.data.get('new_password')
        if not new_password or len(new_password) < 8:
            return Response(
                {'detail': 'Password must be at least 8 characters.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(new_password)
        user.save()
        return Response({'detail': 'Password reset successfully.'})

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        user = self.get_object()
        user.login_attempts = 0
        user.lockout_until = None
        user.save()
        return Response({'detail': 'Account unlocked successfully.'})
