# Optional free-text school subject on entries (S-01). Additive only, no
# backfill: existing rows get an empty subject. The database default lets the
# previous release's code still insert entries after a code-only rollback.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('entries', '0006_heartbeat_release'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='school_subject',
            field=models.CharField(blank=True, db_default='', default='', max_length=100, verbose_name='przedmiot'),
        ),
    ]
