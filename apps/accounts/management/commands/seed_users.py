import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, UserSetting


class Command(BaseCommand):
    help = 'Seed default users (admin, user, viewer) for development'

    def handle(self, *args, **options):
        self._refuse_weak_seed_outside_dev()
        users_to_create = [
            {
                'username': 'admin',
                'password': 'admin123',
                'role': 'administrator',
                'display_name': '管理员',
            },
            {
                'username': 'user',
                'password': 'user123',
                'role': 'user',
                'display_name': '普通用户',
            },
            {
                'username': 'viewer',
                'password': 'viewer123',
                'role': 'viewer',
                'display_name': '查看者',
            },
        ]

        for user_data in users_to_create:
            user, created = User.objects.get_or_create(
                username=user_data['username'],
                defaults={
                    'role': user_data['role'],
                    'display_name': user_data['display_name'],
                    'is_staff': user_data['role'] == 'administrator',
                    'is_superuser': user_data['role'] == 'administrator',
                },
            )
            if created:
                user.set_password(user_data['password'])
                user.save()
                UserSetting.objects.get_or_create(user=user)
                self.stdout.write(self.style.SUCCESS(f'Created user: {user.username} ({user.role})'))
            else:
                # get_or_create's ``defaults`` only apply on create: a user
                # already in the DB (e.g. a superuser created by an old
                # standalone bootstrap, whose role fell back to 'user') keeps
                # its stale role/flags. Repair those here. Passwords of
                # existing users are never reset.
                expected = {
                    'role': user_data['role'],
                    'display_name': user_data['display_name'],
                    'is_staff': user_data['role'] == 'administrator',
                    'is_superuser': user_data['role'] == 'administrator',
                }
                changed = [k for k, v in expected.items() if getattr(user, k) != v]
                if changed:
                    for field in changed:
                        setattr(user, field, expected[field])
                    user.save(update_fields=changed)
                    # Legacy bootstraps never created settings rows; keep
                    # repaired users on par with freshly seeded ones.
                    UserSetting.objects.get_or_create(user=user)
                    self.stdout.write(
                        self.style.WARNING(f'Updated user: {user.username} ({", ".join(changed)})')
                    )
                else:
                    self.stdout.write(self.style.WARNING(f'User already exists: {user.username}'))

            # e2e 确定性：Playwright 多 worker 共用同一账号，布局/勾选的账号级
            # 记忆会让用例互相污染 → seed 一律强制关闭（真实用户默认开，
            # 见 UserSetting.analysis_chart_memory default=True）。
            UserSetting.objects.update_or_create(
                user=user, defaults={'analysis_chart_memory': False},
            )

        self.stdout.write(self.style.SUCCESS('Seed users completed.'))

    @staticmethod
    def _refuse_weak_seed_outside_dev():
        """三个口令是公开已知的，生产档不许落地（与 ``standalone.py:104-111`` 同形）。

        那道互锁只管 ``_bootstrap`` 建 superuser 的路径，看不见本命令 —— 本方法是
        第二条通路的对应闸门。守卫放在最前，所以拒执时**一个用户都不会被创建**。
        """
        if settings.DEBUG:
            return
        if os.environ.get('LQDP_ALLOW_WEAK_SEED') == '1':
            return
        raise CommandError(
            'seed_users 写入的是公开已知的弱口令（admin123 / user123 / viewer123），'
            f'非开发档（DEBUG={settings.DEBUG}）拒绝执行。'
            '确需在非开发环境建演示账号时设 LQDP_ALLOW_WEAK_SEED=1 显式放行；'
            '给真实用户开号请走管理界面（/api/v1/auth/users/），'
            '或按部署文档用 LQDP_BOOTSTRAP_ADMIN_PASSWORD 预设首个管理员口令。')
