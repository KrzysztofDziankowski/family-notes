from django.urls import path

from .views import (
    account_status,
    family_member_deactivate,
    family_member_edit,
    family_member_reactivate,
    family_member_states,
    family_members,
)

urlpatterns = [
    path('', account_status, name='account_status'),
    path('family/', family_members, name='family_members'),
    path('family/_states/', family_member_states, name='family_member_states'),
    path('family/members/<int:pk>/edit/', family_member_edit, name='family_member_edit'),
    path(
        'family/members/<int:pk>/deactivate/',
        family_member_deactivate,
        name='family_member_deactivate',
    ),
    path(
        'family/members/<int:pk>/reactivate/',
        family_member_reactivate,
        name='family_member_reactivate',
    ),
]
