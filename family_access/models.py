from django.conf import settings
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
            models.UniqueConstraint(
                fields=('user',),
                condition=Q(is_active=True),
                name='unique_active_family_membership_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.display_name} ({self.get_role_display()})'
