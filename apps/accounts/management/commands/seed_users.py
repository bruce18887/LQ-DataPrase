from django.core.management.base import BaseCommand
from apps.accounts.models import User, UserSetting


class Command(BaseCommand):
    help = 'Seed default users (admin, user, viewer) for development'

    def handle(self, *args, **options):
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
