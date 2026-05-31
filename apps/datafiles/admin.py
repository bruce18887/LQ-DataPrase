from django.contrib import admin

from apps.datafiles.models import DataFile, ParseHistory


@admin.register(DataFile)
class DataFileAdmin(admin.ModelAdmin):
    list_display = [
        'filename', 'owner', 'format_type', 'program_name',
        'row_count', 'col_count', 'status', 'created_at',
    ]
    list_filter = ['format_type', 'status', 'created_at']
    search_fields = ['filename', 'program_name', 'owner__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(ParseHistory)
class ParseHistoryAdmin(admin.ModelAdmin):
    list_display = [
        'filename', 'user', 'format_type', 'rows', 'cols', 'parsed_at',
    ]
    list_filter = ['format_type', 'parsed_at']
    search_fields = ['filename', 'user__username']
    readonly_fields = ['parsed_at']
