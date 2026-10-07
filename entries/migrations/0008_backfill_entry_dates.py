"""Irreversible writing/deadline dates and metadata-based school types."""

from zoneinfo import ZoneInfo

from django.db import migrations


LOCAL_ZONE = ZoneInfo('Europe/Warsaw')
EVENT_KINDS = ('homework', 'class_test', 'test', 'quiz', 'substitution', 'room_change')
NOTE_KINDS = ('lucky_number', 'grade', 'late_arrival')


def backfill_dates_and_school_types(apps, schema_editor):
    Entry = apps.get_model('entries', 'Entry')
    entries = Entry.objects.using(schema_editor.connection.alias)
    # Avoid save(): creation/modification timestamps and provenance stay intact.
    # Finish the date pass before normalizing notes to constrained event types.
    last_pk = 0
    while True:
        batch = list(entries.filter(date__isnull=True, pk__gt=last_pk).order_by('pk')[:500])
        if not batch:
            break
        for entry in batch:
            entry.date = entry.created_at.astimezone(LOCAL_ZONE).date()
        entries.bulk_update(batch, ['date'], batch_size=500)
        last_pk = batch[-1].pk
    entries.filter(school_item__in=EVENT_KINDS).update(entry_type='calendar_event')
    entries.filter(school_item__in=NOTE_KINDS).update(entry_type='note')


class Migration(migrations.Migration):
    dependencies = [('entries', '0007_entry_school_subject')]
    operations = [migrations.RunPython(backfill_dates_and_school_types)]
