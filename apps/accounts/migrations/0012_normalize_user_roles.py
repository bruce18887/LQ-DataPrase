from django.db import migrations

from apps.accounts.role_migration import normalize_roles


def merge_viewer_roles(apps, schema_editor):
    UserModel = apps.get_model('accounts', 'User')
    counts = normalize_roles(UserModel)
    # 三类计数任一非零都要打印：内核承诺「不静默改数据」，只 viewer 两
    # 类进文案的话，superuser_promoted 那一条就会成为漏网的静默改写。
    # flush 是仓内惯例（standalone.py 15 条启动期打印全部带），Electron 侧按行
    # 消费后端 stdout。文案刻意 ASCII：局域网服务器上人手跑 `manage.py migrate`
    # 且输出被重定向、系统码页非 CJK 时，中文 print 会抛 UnicodeEncodeError，
    # 而那正好发生在迁移事务里 —— 数据无损，但升级当场趴下。钉它的是
    # test/backend/test_role_normalization.py 的 MigrationPrintCodepageTests：
    # 拿 cp1252 的流真跑一次本函数，而不是查这一行的字符串。
    if any(counts.values()):
        print(f"[0012] role normalization: {counts}", flush=True)


def no_op(apps, schema_editor):
    """反向故意留空：viewer 的独立身份按已批准决策不再恢复，
    只允许后面的 choices 迁移自身回退（spec §4）。"""


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_chart_dpi_default_100'),
    ]

    operations = [
        migrations.RunPython(merge_viewer_roles, no_op),
    ]
