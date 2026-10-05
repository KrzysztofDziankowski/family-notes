from django import forms

from .membership import (
    BLANK_NAME_ERROR,
    DISPLAY_NAME_MAX_LENGTH,
    INVALID_ROLE_ERROR,
    NAME_TOO_LONG_ERROR,
    SELF_DEMOTION_CONFIRM_ERROR,
)
from .models import FamilyMember

# Polish labels for the in-app role choice (the model keeps English admin labels).
ROLE_CHOICES = [
    (FamilyMember.Role.PARENT, 'Rodzic'),
    (FamilyMember.Role.CHILD, 'Dziecko'),
]


class MemberRenameForm(forms.Form):
    """Display-name change; the service re-validates and checks duplicates."""

    display_name = forms.CharField(
        label='Imię',
        max_length=DISPLAY_NAME_MAX_LENGTH,
        strip=True,
        error_messages={'required': BLANK_NAME_ERROR, 'max_length': NAME_TOO_LONG_ERROR},
    )


class MemberRoleForm(forms.Form):
    """Role change; ``confirm_self`` exists only on the actor's own row.

    The service re-checks every rule under the family lock; this form only
    validates the choice and asks for the self-demotion confirmation.
    """

    role = forms.ChoiceField(
        label='Nowa rola',
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        error_messages={'required': INVALID_ROLE_ERROR, 'invalid_choice': INVALID_ROLE_ERROR},
    )

    def __init__(self, *args, member, is_self, **kwargs):
        super().__init__(*args, **kwargs)
        self.member = member
        self.is_self = is_self
        if is_self:
            self.fields['confirm_self'] = forms.BooleanField(
                label='Rozumiem, że stracę uprawnienia rodzica w tej rodzinie.',
                required=False,
            )

    def clean(self):
        cleaned = super().clean()
        demoting_self = (
            self.is_self
            and cleaned.get('role') == FamilyMember.Role.CHILD
            and self.member.role == FamilyMember.Role.PARENT
        )
        if demoting_self and not cleaned.get('confirm_self'):
            self.add_error('confirm_self', SELF_DEMOTION_CONFIRM_ERROR)
        return cleaned
