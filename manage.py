#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def is_test_run(argv):
    """本命令行不解析参数，只能按位置判断：``manage.py test …``。"""
    return len(argv) > 1 and argv[1] == 'test'


def default_settings_module(argv):
    """命令 → 默认 settings 档（``--settings`` 与预先设好的环境变量都优先于此）。

    ``test`` 走 :mod:`config.settings.unit`：后端套件的库 / ``MEDIA_ROOT`` / 临时区落
    ``test/unit-data``。以前它跟着 ``development`` 走导入期存储目录重定向，而仓库根的
    ``system_config.json`` 写着用户主目录 ⇒ 测试把合成 CSV 写进了**用户真实数据目录**
    （2026-10-16 实测多出 4 个）。
    """
    return 'config.settings.unit' if is_test_run(argv) else 'config.settings.development'


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', default_settings_module(sys.argv))
    # 测试运行器绝不能触发默认数据目录迁移（settings 导入期会把项目根的
    # db.sqlite3 + media/ 搬到用户主目录）——见 system_config._migration_disabled。
    # unit 档不经那条通路，所以这条现在是给 `--settings=development` 跑测试留的兜底。
    if is_test_run(sys.argv):
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
