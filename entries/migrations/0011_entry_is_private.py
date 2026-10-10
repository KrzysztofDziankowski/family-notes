# Creator-only entry privacy. Additive only, no backfill: existing and
# creatorless rows stay public. The database default keeps the previous
# release's inserts public after a code-only rollback.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('entries', '0010_conversion_output_dedup_kinds'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='is_private',
            field=models.BooleanField(db_default=False, default=False, verbose_name='prywatny'),
        ),
    ]
