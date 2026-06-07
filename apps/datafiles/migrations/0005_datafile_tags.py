from django.db import migrations, models


class Migration(migrations.Migration):
    """Add a ``tags`` JSONField to DataFile for user-defined labels.

    Existing rows default to an empty list. No backfill needed because tags
    are user-driven, not derivable from filename.
    """

    dependencies = [
        ('datafiles', '0004_datafile_product_code_datafile_source_mtime'),
    ]

    operations = [
        migrations.AddField(
            model_name='datafile',
            name='tags',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
