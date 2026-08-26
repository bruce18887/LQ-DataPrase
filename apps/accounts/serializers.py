from rest_framework import serializers

from apps.common.export_naming import EXPORT_TEMPLATE_DEFAULTS, MAX_TEMPLATE_LENGTH
from .models import User, UserSetting, DEFAULT_HIDDEN_COLUMNS


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
            'chart_engine', 'chart_renderer', 'aggrid_header_font_size',
            'recent_files', 'max_recent_files', 'histogram_label_offset',
            'export_filename_templates',
            'export_timeout',
            'default_hidden_columns',
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Always expose the full 8-key table (defaults merged with overrides)
        templates = data.get('export_filename_templates') or {}
        data['export_filename_templates'] = {**EXPORT_TEMPLATE_DEFAULTS, **templates}
        # 默认隐藏列：空列表（未设置/用户清空）回退到默认 8 列
        hidden = instance.default_hidden_columns
        data['default_hidden_columns'] = (
            hidden if isinstance(hidden, list) and hidden else list(DEFAULT_HIDDEN_COLUMNS)
        )
        return data

    def validate_export_filename_templates(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('export_filename_templates 必须是对象')
        for key, tpl in value.items():
            if not isinstance(key, str) or key not in EXPORT_TEMPLATE_DEFAULTS:
                raise serializers.ValidationError(f'未知导出类型: {key}')
            if not isinstance(tpl, str):
                raise serializers.ValidationError(f'{key} 的模板必须是字符串')
            if len(tpl) > MAX_TEMPLATE_LENGTH:
                raise serializers.ValidationError(
                    f'{key} 的模板不能超过 {MAX_TEMPLATE_LENGTH} 字符')
        return value

    def validate_export_timeout(self, value):
        if not isinstance(value, int) or not 30 <= value <= 3600:
            raise serializers.ValidationError('导出超时必须在 30-3600 秒之间')
        return value

    def validate_default_hidden_columns(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('default_hidden_columns 必须是数组')
        if any(not isinstance(v, str) or not v.strip() for v in value):
            raise serializers.ValidationError('default_hidden_columns 的元素必须是字符串')
        if len(value) > 100:
            raise serializers.ValidationError('默认隐藏列数量不能超过 100')
        return [v.strip() for v in value]

    def validate_chart_renderer(self, value):
        if value not in ('svg', 'canvas'):
            raise serializers.ValidationError('图表渲染器必须为 svg 或 canvas')
        return value


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
