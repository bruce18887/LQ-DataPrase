#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
    # 测试运行器绝不能触发默认数据目录迁移（settings 导入期会把项目根的
    # db.sqlite3 + media/ 搬到用户主目录）——见 system_config._migration_disabled。
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        os.environ.setdefault('LQDP_SKIP_STORAGE_MIGRATION', '1')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
