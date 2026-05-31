from rest_framework import serializers

from apps.datafiles.models import DataFile, ParseHistory


class DataFileSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source='owner.username')
    format_type_display = serializers.CharField(
        source='get_format_type_display', read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True
    )

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_path', 'file_size',
            'format_type', 'format_type_display', 'row_count', 'col_count',
            'program_name', 'metadata', 'status', 'status_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'owner', 'created_at', 'updated_at']


class DataFileListSerializer(serializers.ModelSerializer):
    owner = serializers.ReadOnlyField(source='owner.username')
    format_type_display = serializers.CharField(
        source='get_format_type_display', read_only=True
    )
    status_display = serializers.CharField(
        source='get_status_display', read_only=True
    )

    class Meta:
        model = DataFile
        fields = [
            'id', 'owner', 'filename', 'file_size', 'format_type',
            'format_type_display', 'row_count', 'col_count', 'program_name',
            'status', 'status_display', 'created_at', 'updated_at',
        ]


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
