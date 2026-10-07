# Seed a local test family for manual QA. Local development only.
#
# Usage:
#   DJANGO_DEBUG=true uv run python manage.py shell < scripts/dev/seed_test_family.py
#
# Creates password-login users (sign in at /accounts/login/), all with PASSWORD:
#   test_rodzic  parent "Ewa"   - Rodzina testowa
#   test_kasia   child  "Kasia" - Rodzina testowa
#   test_tymek   child  "Tymek" - Rodzina testowa (sibling)
#   test_obcy    parent "Obcy"  - Inna rodzina (foreign family)
#   test_dwie    parent "Ola"   - Rodzina testowa, and child "Ola" - Inna rodzina
#                (two families: picks one on the chooser, switches in the header)
# plus sample entries covering upcoming, today, long, past/EduVulcan,
# sibling, family-wide and foreign-family cases. Safe to re-run: it resets these
# users' passwords and recreates entries of the two test families only.
import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from entries.models import Entry
from family_access.models import Family, FamilyMember

if not settings.DEBUG:
    raise SystemExit('Refusing to seed test users: DEBUG is off (local development only).')

PASSWORD = 'test-haslo-123'
User = get_user_model()
today = timezone.localdate()
day = datetime.timedelta(days=1)


def member(username, family, role, name):
    user, _ = User.objects.get_or_create(username=username)
    user.set_password(PASSWORD)
    user.save()
    # One membership per (user, family): a person may belong to several families.
    membership, _ = FamilyMember.objects.update_or_create(
        user=user,
        family=family,
        defaults={'role': role, 'display_name': name, 'is_active': True},
    )
    return membership


family, _ = Family.objects.get_or_create(name='Rodzina testowa')
parent = member('test_rodzic', family, FamilyMember.Role.PARENT, 'Ewa')
kasia = member('test_kasia', family, FamilyMember.Role.CHILD, 'Kasia')
tymek = member('test_tymek', family, FamilyMember.Role.CHILD, 'Tymek')

foreign_family, _ = Family.objects.get_or_create(name='Inna rodzina')
foreign_parent = member('test_obcy', foreign_family, FamilyMember.Role.PARENT, 'Obcy')
two_family_parent = member('test_dwie', family, FamilyMember.Role.PARENT, 'Ola')
two_family_child = member('test_dwie', foreign_family, FamilyMember.Role.CHILD, 'Ola')

Entry.objects.filter(family__in=[family, foreign_family]).delete()


def entry(content, assignee, fam=family, **fields):
    return Entry.objects.create(
        family=fam,
        content=content,
        assigned_member=assignee,
        entry_type=fields.pop('entry_type', 'todo'),
        date=fields.pop('date', today),
        created_by=fields.pop('created_by', parent),
        **fields,
    )


entry('Sprawdzian z matematyki', kasia, entry_type='calendar_event', date=today + 2 * day,
      time=datetime.time(8, 0), school_item='test')
entry('Wycieczka do muzeum', kasia, entry_type='calendar_event', date=today)
entry('Kupić zeszyt', kasia)
entry('Bardzo długi wpis: ' + 'przynieść kredki, blok, klej i nożyczki; ' * 8, kasia,
      date=today + 5 * day)
entry('Kartkówka z historii', kasia, entry_type='calendar_event', date=today - 3 * day,
      source='eduvulcan', created_by=None)
sibling = entry('Trening piłki (rodzeństwo)', tymek, entry_type='calendar_event',
                date=today + day, time=datetime.time(17, 0))
family_wide = entry('Zebranie z wychowawcą (cała rodzina)', None, entry_type='calendar_event',
                    date=today + 4 * day)
foreign = entry('OBCY-WPIS-SENTINEL', None, fam=foreign_family, created_by=foreign_parent)
entry('Lekcja gry na pianinie (Ola w innej rodzinie)', two_family_child, fam=foreign_family,
      created_by=foreign_parent, date=today + day)

print(f'Password for all users: {PASSWORD}')
print('Users: test_rodzic (parent), test_kasia (child), test_tymek (child), test_obcy (other family),')
print('       test_dwie (parent in Rodzina testowa, child in Inna rodzina)')
print(f'Sibling entry id: {sibling.pk}; family-wide id: {family_wide.pk}; foreign id: {foreign.pk}')
