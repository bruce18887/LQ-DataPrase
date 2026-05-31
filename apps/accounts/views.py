from datetime import timedelta

from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserSetting
from .permissions import FeaturePermission
from .serializers import (
    LoginSerializer,
    PasswordChangeSerializer,
    TokenResponseSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserSettingSerializer,
)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(
                {'detail': 'Invalid username or password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.lockout_until and user.lockout_until > timezone.now():
            remaining = (user.lockout_until - timezone.now()).seconds // 60
            return Response(
                {'detail': f'Account locked. Try again in {remaining} minutes.'},
                status=status.HTTP_423_LOCKED,
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
                return Response(
                    {'detail': 'Account locked due to too many failed attempts. Try again in 15 minutes.'},
                    status=status.HTTP_423_LOCKED,
                )
            user.save()
            return Response(
                {'detail': 'Invalid username or password.'},
                status=status.HTTP_401_UNAUTHORIZED,
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
        serializer = UserSerializer(
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
