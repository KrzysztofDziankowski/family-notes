from django.urls import path

from .views import account_status

urlpatterns = [
    path('', account_status, name='account_status'),
]
