import hashlib
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Family(models.Model):
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'families'

    def __str__(self):
        return self.name


class FamilyMember(models.Model):
    class Role(models.TextChoices):
        PARENT = 'parent', 'Parent'
        CHILD = 'child', 'Child'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='family_memberships',
    )
    family = models.ForeignKey(
        Family,
        on_delete=models.CASCADE,
        related_name='members',
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    display_name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # S-16: a person may belong to several families, at most once
            # actively in each. Django admin validates it as a form error.
            models.UniqueConstraint(
                fields=('user', 'family'),
                condition=Q(is_active=True),
                name='unique_active_membership_per_user_family',
                violation_error_message=(
                    'This user already has an active membership in this family.'
                ),
            ),
        ]

    def __str__(self):
        return f'{self.display_name} ({self.get_role_display()})'


class AutomationToken(models.Model):
    SECRET_PREFIX = 'fnat_'
    DISPLAY_PREFIX_LENGTH = 8

    member = models.ForeignKey(
        FamilyMember,
        on_delete=models.CASCADE,
        related_name='automation_tokens',
        limit_choices_to={'role': FamilyMember.Role.PARENT, 'is_active': True},
        verbose_name='rodzic',
    )
    name = models.CharField('nazwa', max_length=120)
    prefix = models.CharField('prefiks', max_length=16, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField('utworzono', auto_now_add=True)
    expires_at = models.DateTimeField('wygasa', null=True, blank=True)
    revoked_at = models.DateTimeField('unieważniono', null=True, blank=True, editable=False)
    last_used_at = models.DateTimeField('ostatnio użyty', null=True, blank=True, editable=False)

    class Meta:
        verbose_name = 'token automatyzacji'
        verbose_name_plural = 'tokeny automatyzacji'

    def __str__(self):
        return f'{self.name} ({self.prefix}…)'

    @staticmethod
    def hash_secret(secret):
        return hashlib.sha256(secret.encode('utf-8')).hexdigest()

    @classmethod
    def generate_secret(cls):
        return cls.SECRET_PREFIX + secrets.token_urlsafe(32)

    @classmethod
    def issue(cls, member, name, expires_at=None):
        token = cls(member=member, name=name, expires_at=expires_at)
        secret = token.assign_new_secret()
        token.save()
        return token, secret

    def assign_new_secret(self):
        secret = self.generate_secret()
        self.token_hash = self.hash_secret(secret)
        self.prefix = secret[len(self.SECRET_PREFIX):][: self.DISPLAY_PREFIX_LENGTH]
        return secret

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    def is_expired(self, now):
        return self.expires_at is not None and self.expires_at <= now

    def is_usable(self, now):
        return not self.is_revoked and not self.is_expired(now)

    def clean(self):
        super().clean()
        if self.member_id is not None and self.member.role != FamilyMember.Role.PARENT:
            raise ValidationError(
                {'member': 'Token automatyzacji można wydać tylko rodzicowi.'}
            )


class AuthCacheEntry(models.Model):
    """Expiring authentication state only; never family content or credentials."""

    cache_key = models.CharField(max_length=255, primary_key=True)
    value = models.TextField()
    expires = models.DateTimeField(null=True, db_index=True)
