# Per-process conversion heartbeats carry the release they run, so health
# counts only the current release. The column has a database default, so a
# rolled-back release's code can still insert its heartbeat row.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('entries', '0005_inbound_notification_db_defaults'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversionworkerheartbeat',
            name='release',
            field=models.CharField(blank=True, db_default='', default='', max_length=128, verbose_name='release'),
        ),
        migrations.AddIndex(
            model_name='conversionworkerheartbeat',
            index=models.Index(fields=['release', 'beat_at'], name='heartbeat_release_beat_idx'),
        ),
    ]
