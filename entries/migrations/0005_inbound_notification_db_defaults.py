# Database-level defaults for the NOT NULL lifecycle columns added in 0003, so
# the previous release's code (which does not know these columns) can still
# insert notifications after a code-only rollback. Additive and forward-safe.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('entries', '0004_conversion_worker_heartbeat'),
    ]

    operations = [
        migrations.AlterField(
            model_name='inboundnotification',
            name='attempt_count',
            field=models.PositiveSmallIntegerField(db_default=0, default=0, verbose_name='attempt count'),
        ),
        migrations.AlterField(
            model_name='inboundnotification',
            name='last_error_code',
            field=models.CharField(blank=True, db_default='', default='', max_length=64, verbose_name='last error code'),
        ),
    ]
