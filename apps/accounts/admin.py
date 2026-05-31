from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, UserSetting


class UserSettingInline(admin.StackedInline):
    model = UserSetting
    can_delete = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [UserSettingInline]
    list_display = [
        'username', 'email', 'display_name', 'role',
        'is_active', 'is_staff', 'login_attempts', 'lockout_until',
    ]
    list_filter = ['role', 'is_active', 'is_staff']
    search_fields = ['username', 'email', 'display_name']
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Additional Info', {
            'fields': ('role', 'display_name', 'login_attempts', 'lockout_until'),
        }),
    )


@admin.register(UserSetting)
class UserSettingAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'page_size', 'chart_engine',
        'max_recent_files',
    ]
    search_fields = ['user__username', 'user__email']
