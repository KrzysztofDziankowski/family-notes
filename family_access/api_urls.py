from django.urls import path

from .api_views import ping

urlpatterns = [
    path('ping/', ping, name='ping'),
]
