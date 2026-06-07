"""Align sftp_config.user_id → owner_id (matches the model FK name).

History: the dev DB was bootstrapped with an older model version that
named the owner FK ``user`` (column ``user_id``). The model was later
renamed to ``owner`` (column ``owner_id``) and the schema migration
``0001_initial`` was generated to match. However, the running dev DB
was never updated — Django still reports ``0001_initial`` as applied,
but the live table column is still ``user_id``. As a result, any query
that touches ``SftpConfig.owner`` raises
``OperationalError: no such column: sftp_config.owner_id``, surfacing
in the browser as "保存配置失败".

This migration renames the legacy ``user_id`` column to ``owner_id`` on
SQLite so the live schema matches the model state. It is a no-op on a
fresh DB where the column was already created with the right name.
"""
from django.db import migrations


def rename_user_to_owner(apps, schema_editor):
    """Rename sftp_config.user_id → owner_id (SQLite syntax).

    SQLite supports ``ALTER TABLE ... RENAME COLUMN`` since 3.25.0
    (Django 4.2+ requires it). Guard for older SQLite by checking the
    column exists first; if it doesn't (fresh DB), skip silently.
    """
    if schema_editor.connection.vendor != 'sqlite':
        # For other backends (PostgreSQL / MySQL) the project has not
        # encountered this drift, so leave them to a manual fix.
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("PRAGMA table_info(sftp_config)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'user_id' in columns and 'owner_id' not in columns:
            # SQLite 3.25+ supports RENAME COLUMN. DROP+ADD the index
            # implicitly — Django's unique_together index uses the
            # current column name and will be re-created by the model
            # state on next `makemigrations` if needed.
            cursor.execute(
                "ALTER TABLE sftp_config RENAME COLUMN user_id TO owner_id"
            )


def noop_reverse(apps, schema_editor):
    """Reverse migration is intentionally a no-op.

    Renaming a column back would risk data loss (any rows added under
    the new name would be lost), and on a fresh DB there's nothing to
    undo. The forward direction is idempotent.
    """
    return


class Migration(migrations.Migration):
    dependencies = [
        ('sftp', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(rename_user_to_owner, noop_reverse),
    ]
