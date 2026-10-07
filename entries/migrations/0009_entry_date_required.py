from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('entries', '0008_backfill_entry_dates')]
    operations = [
        migrations.AlterField(
            model_name='entry', name='date', field=models.DateField(verbose_name='data'),
        ),
    ]
