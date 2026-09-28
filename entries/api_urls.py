from django.urls import path

from .api_views import list_family_entries, submit_notification

urlpatterns = [
    path('entries/', list_family_entries, name='automation_entries_list'),
    path('notifications/', submit_notification, name='automation_notification_submit'),
]
