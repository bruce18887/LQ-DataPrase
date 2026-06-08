from rest_framework import serializers

from apps.datafiles.models import DataFile, ParseHistory


# Tag normalisation policy applied both to inbound payloads (set_tags) and
# to outbound representations. We keep this as a tiny module-level helper so
# the unit tests can assert against the same contract.
TAG_MAX_LENGTH = 50
TAG_MAX_COUNT = 20


def normalize_tags(raw):
    """Trim, drop empties, dedup case-insensitively, enforce length limits.

    Returns a list of canonical (original-cased) tag strings. Always returns
    a list, even when the input is None / malformed. Raises
    ``serializers.ValidationError`` when limits are exceeded.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise serializers.ValidationError('tags 必须是列表')
    cleaned = []
    seen = set()  # case-insensitive seen
    for item in raw:
        if not isinstance(item, str):
            raise serializers.ValidationError('tag 必须是字符串')
        t = item.strip()
        if not t:
            continue
        if len(t) > TAG_MAX_LENGTH:
            raise serializers.ValidationError(
                f'tag「{t[:20]}…」长度 {len(t)} 超过 {TAG_MAX_LENGTH}'
            )
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(t)
    if len(cleaned) > TAG_MAX_COUNT:
        raise serializers.ValidationError(
            f'tag 数量 {len(cleaned)} 超过 {TAG_MAX_COUNT}'
        )
    return cleaned


class DataFileSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source='owner.username')
    format_type_display = serializers.CharField(
        source='get_format_type_display', read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True
    )
    file_type_display = serializers.CharField(
        source='get_file_type_display', read_only=True
    )

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_path', 'file_size',
            'format_type', 'format_type_display', 'file_type', 'file_type_display',
            'batch_name', 'sub_batch', 'row_count', 'col_count',
            'program_name', 'product_code', 'source_mtime',
            'metadata', 'tags',
            'status', 'status_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']

    def validate_tags(self, value):
        return normalize_tags(value)


class DataFileListSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source='owner.username')
    format_type_display = serializers.CharField(
        source='get_format_type_display', read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True
    )
    file_type_display = serializers.CharField(
        source='get_file_type_display', read_only=True
    )

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_size', 'format_type',
            'format_type_display', 'file_type', 'file_type_display',
            'batch_name', 'sub_batch', 'row_count', 'col_count', 'program_name',
            'product_code', 'source_mtime',
            'tags',
            'status', 'status_display', 'created_at', 'updated_at',
        ]

    def validate_tags(self, value):
        return normalize_tags(value)


class ParseHistorySerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source='user.username')
    datafile_name = serializers.ReadOnlyField(source='datafile.filename')

    class Meta:
        model = ParseHistory
        fields = [
            'id', 'user', 'datafile', 'datafile_name', 'filename',
            'filepath', 'format_type', 'rows', 'cols', 'parsed_at',
        ]


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
