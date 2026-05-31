from rest_framework import serializers
from .models import User, UserSetting


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name', 'role',
            'is_active', 'date_joined', 'last_login', 'lockout_until',
        ]
        read_only_fields = ['id', 'date_joined', 'last_login', 'lockout_until']


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name', 'role',
            'password', 'is_active',
        ]
        read_only_fields = ['id']

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        UserSetting.objects.create(user=user)
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    role = serializers.CharField()
    display_name = serializers.CharField()


class UserSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSetting
        fields = [
            'page_size', 'chart_height', 'table_height', 'chart_dpi',
            'cpk_a_threshold', 'cpk_b_threshold', 'cpk_c_threshold',
            'chart_engine', 'aggrid_header_font_size',
            'recent_files', 'max_recent_files', 'histogram_label_offset',
        ]


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)
    confirm_password = serializers.CharField(min_length=8)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {'confirm_password': 'New passwords do not match.'}
            )
        return data
