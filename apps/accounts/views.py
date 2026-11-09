from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.errors import error_response

from .models import User, UserSetting
from .permissions import FeaturePermission
from .serializers import (
    AdminResetPasswordSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    TokenResponseSerializer,
    UserCreateSerializer,
    UserProfileSerializer,
    UserSerializer,
    UserSettingSerializer,
)
from .services import get_user_setting
from .tokens import revoke_refresh_tokens

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
    on ``code`` without parsing free-form ``detail`` text.

    形态由 apps/common/errors.error_response 统一（评审 P1-5）：这里只是保留
    登录侧既有的「detail 必填 + 任意附加字段」调用习惯，附加字段原样透传。
    """
    return error_response(code, detail, status_code, **extra)


class LoginView(APIView):
    permission_classes = [AllowAny]
    # Login may take a beat (LDAP/SSO/etc) but not the full 30s axios
    # timeout. Keep the server's hard limit tight so the user gets a
    # meaningful "server slow" error rather than the generic timeout.
    authentication_classes: list = []
    # IP-scoped rate limit — the 'login' scope in
    # ``REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']`` (config/settings/base.py).
    #
    # ``ScopedRateThrottle`` keys on the authenticated user when there is one
    # and on the client IP otherwise. Login requests are always anonymous here
    # (``authentication_classes`` is empty), so this is purely an IP throttle.
    # It is a *complement* to the per-account lockout below (5 failures → 423 +
    # 15 min): that one defends a single username, this one defends the
    # endpoint — one host cannot enumerate usernames, nor lock real users out
    # by spraying failures against them.
    #
    # Exceeding it returns 429 with ``code: 'throttled'`` via the global
    # exception handler (apps/common/exceptions.py), not the local ``_error``
    # envelope — the front-end maps that code already.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

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

        # `filter().first()` 而非 `get()`：两条路径的语句数实测相同（各 1 条 SELECT，
        # 见 test_accounts_write_paths.py 模块注释），差异只在 SQL 形状与不走异常控制流。
        user = User.objects.filter(username=username).first()
        if user is None:
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

        # 成功即清零计数，但只在**确有东西要清**时写：干净账号（attempts=0、无 lockout）
        # 原来那句无条件 `user.save()` 是把库里已有的默认值再 UPDATE 一遍（no-op 写，
        # 成功路径实测 4 条里的第 3 条）。收敛后干净账号 3 条、需重置的仍 4 条。
        # `or user.lockout_until is not None` 这半句不许跟着删。锁定期**已过期**的账号
        # `login_attempts` 也是 0，只靠前半句就永远不清它，而过期之后**没有任何通路会自我修复**：
        # 本视图的锁定判定看 `> timezone.now()`（上面第 122 行，过期即放行、不写回）；DRF 两条
        # 序列化通路把 `lockout_until` 钉成 read_only（`serializers.py:31`/`:55`），API 写不掉；
        # 前端管理页的 `isLocked()` 同样按 `> now` 判（`UserManagement.vue` 里的状态 chip 与
        # `kpi.locked` 都走它）⇒ 过期值不渲染成锁定，连「解锁」按钮
        # （`v-if="isLocked(row)"`）都不出现，`unlock` 那条唯一的清除通路从页面上到不了。
        # 于是它的实际代价是：**这条过期值永久留在库里，并随 `UserSerializer` 的载荷
        # （用户列表接口）一次次下发**；今天唯一真看得见它的界面是 Django admin
        # （`admin.py:17` 的 `list_display` 与 `:23` 的 fieldset 都列了这列）。
        # 判据 `test/backend/test_login_path_statements.py::LoginPathTests`。
        if user.login_attempts or user.lockout_until is not None:
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
    # 登出要能在 access 已过期时仍然生效：被吊销的凭据在 body 的 refresh 里，
    # 不能因为 Authorization 头过期就先 401 掉。
    permission_classes = [AllowAny]
    authentication_classes: list = []

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
        """只读：缺行时**不建行**，交出内存默认实例（D2）。

        读走 D1 的单一入口 `get_user_setting`（只读分支，`apps/accounts/services.py`）：
        行缺失 ⇒ None ⇒ 构造 `UserSetting(user_id=request.user.pk)` 交给序列化器。
        为什么不是计划正文那句 `UserSetting(user=request.user)`：传 `user` 对象会让
        Django 的 `Model.__init__` 把这条**未落库**实例挂进 `request.user` 的反向缓存
        （D1 的毒缓存，`test_user_setting_reads.py::UnsavedCacheGuardTests` 钉着可达性），
        同请求内直读 `user.settings` 的通路（`apps/common/user_settings.py` 的
        `get_cpk_thresholds`、`apps/export/views.py` 的 `to_excel`）就会把它当真实设置；
        `user_id=` 形状实测（Django 6.0.9，本机 2026-10-30 量出）不碰那份缓存，判据在
        `test/backend/test_accounts_write_paths.py::SettingsGetCacheShapeTests`。
        序列化器不暴露 `id`/`user`，内存默认实例与 HEAD「先建行再序列化」的 JSON 逐字段
        等价（同文件 `test_get_without_row_serializes_the_head_row_body` 现场比对）。
        """
        settings = get_user_setting(request.user)
        if settings is None:
            settings = UserSetting(user_id=request.user.pk)
        serializer = UserSettingSerializer(settings)
        return Response(serializer.data)

    def put(self, request):
        """写通路：缺行仍建行（走 helper 的 `create=True`），但 UPDATE 只写本次变更的列 ——
        不带 `update_fields` 的全行写实测 SET 里 **26 列**（`user_id` + 25 个设置列，含 5 个
        `sftp_last_*`；`UserSettingSerializer` 只暴露 20 个字段，那是字段数不是列数，
        两个数别混 —— 出处是现量：同文件 `SettingsPutWriteShapeTests
        .test_head_full_row_update_sets_26_columns_not_the_20_serializer_fields`）。
        空变更集 ⇒ `update_fields=[]` ⇒ Django 6.0.9 在 `db/models/base.py:843` 直接早退，
        一条 UPDATE 都不发，因此这里**不需要**额外的 `if changed:` 守卫（守卫是死码，复评审
        Minor 1 已删）。别把 `test_put_empty_body_writes_nothing` 读成「视图里没有守卫」的判据 ——
        它钉的是零写与语句形状；守卫加回去本批照样 `Ran 20 / OK`（2026-10-30 两轮各量一次）。
        整块包在 `transaction.atomic()` 里：建行与补写同生同灭 —— 失败或校验不过时
        库里不留一条只有默认值的行。这层包裹是**新增**保证，不是找回丢掉的东西：
        本仓 DRF 3.18.3 的 `serializer.save()` 自己不带原子块（`ATOMIC_REQUESTS` 也没开），
        代价是一对 SAVEPOINT/RELEASE，账面钉在 `SettingsPutAtomicityTests`。
        """
        with transaction.atomic():
            settings = get_user_setting(request.user, create=True)
            serializer = UserSettingSerializer(
                settings, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            changed = serializer.validated_data
            for attr, value in changed.items():
                setattr(settings, attr, value)
            settings.save(update_fields=list(changed))
        return Response(serializer.data)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={'user': request.user}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            request.user.set_password(serializer.validated_data['new_password'])
            request.user.save(update_fields=['password'])
            revoke_refresh_tokens(request.user)
        return Response({'detail': '密码已修改，请重新登录。'})


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
        serializer = AdminResetPasswordSerializer(
            data=request.data, context={'user': user}
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])
            user.login_attempts = 0
            user.lockout_until = None
            user.save(
                update_fields=['password', 'login_attempts', 'lockout_until']
            )
            revoke_refresh_tokens(user)
        return Response({'detail': '密码已重置，请告知用户登录后立即修改。'})

    @action(detail=True, methods=['post'])
    def unlock(self, request, pk=None):
        user = self.get_object()
        user.login_attempts = 0
        user.lockout_until = None
        user.save()
        return Response({'detail': 'Account unlocked successfully.'})
