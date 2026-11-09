import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, UserSetting
from apps.accounts.role_migration import normalize_roles


class Command(BaseCommand):
    help = 'Seed dev fixture users (admin, user) and normalize legacy roles'

    def handle(self, *args, **options):
        self._refuse_weak_seed_outside_dev()
        # 幂等兜底（spec §4）：库里可能留着 choices 收敛前的历史行（viewer、或
        # 遗留 superuser + role='user'），本命令先归并再种子，跑第二次三项全 0。
        merged = normalize_roles(User)
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
                #
                # ``is_active`` belongs in this set: these two are the dev/e2e
                # fixture accounts, and ``frontend/e2e/fixtures/auth.setup.ts``
                # logs in as ``user`` to mint storageState — once it is disabled
                # the setup project fails and takes every dependent spec with it,
                # and nothing else re-enables it (2026-11-09). Non-seed users are
                # out of reach here, so an admin's deliberate disable still sticks.
                expected = {
                    'role': user_data['role'],
                    'display_name': user_data['display_name'],
                    'is_staff': user_data['role'] == 'administrator',
                    'is_superuser': user_data['role'] == 'administrator',
                    'is_active': True,
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
        # 三类计数任一非零都要出声（内核承诺「不静默改数据」）：只挑两类 viewer
        # 计数的话，`superuser_promoted` 那一条会漏网 —— 判据在
        # test/backend/test_accounts_bootstrap.py 的两条 seed 兜底用例上。
        # 文案刻意 ASCII：中文写进 stdout 在非 CJK 码页上抛 UnicodeEncodeError，
        # 而它落在数据已改、种子已建之后，手动 `manage.py seed_users` 因此退 1。
        # 钉它的是拿 cp1252 的流真跑一遍整条命令
        # （test_seed_users_writes_clean_under_non_cjk_codepage），不是查某一行字符串
        # —— 后者放过 SUCCESS/`Created user:` 这些别的中文行。
        # 自动跑的两条通路（frontend/e2e/global-setup.ts、scripts/e2e_pool.mjs）都强制
        # PYTHONIOENCODING=utf-8，打包版的后端环境同样如此（electron/backend-env.ts），
        # 所以这条只管手动与第三方脚本调用。stderr 上的中文（含下面那条 CommandError）
        # 不在此列 —— 标准库对 stderr 走 backslashreplace。日志也不崩，但本仓把 console
        # handler 指到 stdout（config/settings/base.py:62），中文记录在 cp1252 下会被
        # 标准库吞成 `--- Logging error ---`（实测），即静默丢行而不是报错。
        # 也不写「归并历史 viewer」：只有第三支非零时并没有 viewer 被动过。
        if any(merged.values()):
            self.stdout.write(
                self.style.WARNING(f'[seed_users] role normalization: {merged}')
            )

    @staticmethod
    def _refuse_weak_seed_outside_dev():
        """两个口令是公开已知的，生产档不许落地（与 ``standalone.py:104-111`` 同形）。

        那道互锁只管 ``_bootstrap`` 建 superuser 的路径，看不见本命令 —— 本方法是
        第二条通路的对应闸门。守卫放在最前，所以拒执时**一个用户都不会被创建**。
        """
        if settings.DEBUG:
            return
        if os.environ.get('LQDP_ALLOW_WEAK_SEED') == '1':
            return
        raise CommandError(
            'seed_users 写入的是公开已知的弱口令（admin123 / user123），'
            f'非开发档（DEBUG={settings.DEBUG}）拒绝执行。'
            '确需在非开发环境建演示账号时设 LQDP_ALLOW_WEAK_SEED=1 显式放行；'
            '给真实用户开号请走管理界面（/api/v1/auth/users/），'
            '或按部署文档用 LQDP_BOOTSTRAP_ADMIN_PASSWORD 预设首个管理员口令。')
