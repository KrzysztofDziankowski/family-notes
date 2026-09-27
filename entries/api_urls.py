from django.urls import path

from .api_views import submit_notification

urlpatterns = [
    path('notifications/', submit_notification, name='automation_notification_submit'),
]
