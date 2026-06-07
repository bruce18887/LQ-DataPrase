from rest_framework import serializers

from .models import SftpConfig


class SftpConfigSerializer(serializers.ModelSerializer):
    """Serialize SftpConfig. Password is WRITE-ONLY; never exposed in responses.

    Responses expose a ``has_password`` boolean so the frontend knows whether a
    stored password exists without revealing it. ``owner`` is injected by the
    view via ``serializer.save(owner=...)`` and is not a writable field.
    """

    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={'input_type': 'password'},
    )
    # TCP port must be in the valid 1..65535 range. Not required so updates that
    # omit it leave the existing value unchanged; defaults to 22 on create.
    port = serializers.IntegerField(
        min_value=1,
        max_value=65535,
        required=False,
        default=22,
    )
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = SftpConfig
        fields = [
            'id', 'name', 'host', 'port', 'username',
            'password', 'has_password', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_has_password(self, obj) -> bool:
        return bool(obj.password_encrypted)

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        instance = SftpConfig(**validated_data)
        if password:
            instance.set_password(password)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        # Only change the stored password when a non-empty one is supplied;
        # omitting / blank password leaves the existing one untouched.
        if password:
            instance.set_password(password)
        instance.save()
        return instance
