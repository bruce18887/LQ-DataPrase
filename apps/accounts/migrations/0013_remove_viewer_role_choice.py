from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0012_normalize_user_roles'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('administrator', 'Administrator'), ('user', 'User')],
                default='user',
                max_length=20,
            ),
        ),
    ]
