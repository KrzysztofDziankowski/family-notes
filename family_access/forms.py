from django import forms

from .membership import BLANK_NAME_ERROR, DISPLAY_NAME_MAX_LENGTH, NAME_TOO_LONG_ERROR


class MemberRenameForm(forms.Form):
    """Display-name change; the service re-validates and checks duplicates."""

    display_name = forms.CharField(
        label='Imię',
        max_length=DISPLAY_NAME_MAX_LENGTH,
        strip=True,
        error_messages={'required': BLANK_NAME_ERROR, 'max_length': NAME_TOO_LONG_ERROR},
    )
