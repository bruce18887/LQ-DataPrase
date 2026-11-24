from rest_framework import serializers

from apps.datafiles.combination_service import (
    managed_tags_for,
    normalize_combination_name,
)
from apps.datafiles.models import DataCombination, DataFile, ParseHistory
from apps.datafiles.utils import extract_data_date, extract_stage
from apps.datafiles.utils import resolve_file_path


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


class DataCombinationSerializer(serializers.ModelSerializer):
    file_count = serializers.IntegerField(read_only=True)
    batched_file_count = serializers.IntegerField(read_only=True)
    unbatched_file_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DataCombination
        fields = [
            'id', 'name', 'description', 'file_count', 'batched_file_count',
            'unbatched_file_count', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_name(self, value):
        try:
            return normalize_combination_name(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


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
    # DB 存相对路径（Storage Layout v2），API 契约保持绝对路径不变
    file_path = serializers.SerializerMethodField()

    # 从文件名/程序名轻量解析（不落库）：测试阶段（FT/QA/UIS/CP）与测试日期
    stage = serializers.SerializerMethodField()
    data_date = serializers.SerializerMethodField()
    combination_id = serializers.IntegerField(source='combination.id', read_only=True)
    combination_name = serializers.CharField(source='combination.name', read_only=True)
    managed_tags = serializers.SerializerMethodField()

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_path', 'file_size',
            'format_type', 'format_type_display', 'file_type', 'file_type_display',
            'batch_name', 'sub_batch', 'row_count', 'col_count',
            'program_name', 'product_code', 'source_mtime',
            'metadata', 'tags', 'stage', 'data_date',
            'combination_id', 'combination_name', 'batch_no', 'managed_tags',
            'is_hidden', 'status', 'status_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'filename', 'created_at', 'updated_at']

    def get_file_path(self, obj) -> str:
        return resolve_file_path(obj.file_path)

    def get_stage(self, obj) -> str:
        return extract_stage(obj.filename, obj.program_name)

    def get_data_date(self, obj) -> str:
        return extract_data_date(obj.filename)

    def get_managed_tags(self, obj) -> list[str]:
        combination_name = obj.combination.name if obj.combination_id else None
        return managed_tags_for(combination_name, obj.batch_no or '')

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
    # 轻量解析字段（同 DataFileSerializer）
    stage = serializers.SerializerMethodField()
    data_date = serializers.SerializerMethodField()
    combination_id = serializers.IntegerField(source='combination.id', read_only=True)
    combination_name = serializers.CharField(source='combination.name', read_only=True)
    managed_tags = serializers.SerializerMethodField()

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_size', 'format_type',
            'format_type_display', 'file_type', 'file_type_display',
            'batch_name', 'sub_batch', 'row_count', 'col_count', 'program_name',
            'product_code', 'source_mtime',
            'tags', 'stage', 'data_date',
            'combination_id', 'combination_name', 'batch_no', 'managed_tags',
            'is_hidden', 'status', 'status_display', 'created_at', 'updated_at',
        ]

    def get_stage(self, obj) -> str:
        return extract_stage(obj.filename, obj.program_name)

    def get_data_date(self, obj) -> str:
        return extract_data_date(obj.filename)

    def get_managed_tags(self, obj) -> list[str]:
        combination_name = obj.combination.name if obj.combination_id else None
        return managed_tags_for(combination_name, obj.batch_no or '')

    def validate_tags(self, value):
        return normalize_tags(value)


class ParseHistorySerializer(serializers.ModelSerializer):
    user = serializers.ReadOnlyField(source='user.username')
    datafile_name = serializers.ReadOnlyField(source='datafile.filename')
    # DB 存相对路径，API 契约保持绝对路径不变
    filepath = serializers.SerializerMethodField()

    class Meta:
        model = ParseHistory
        fields = [
            'id', 'user', 'datafile', 'datafile_name', 'filename',
            'filepath', 'format_type', 'rows', 'cols', 'parsed_at',
        ]

    def get_filepath(self, obj) -> str:
        return resolve_file_path(obj.filepath)
