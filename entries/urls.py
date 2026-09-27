from django.urls import path

from . import views

app_name = 'entries'

urlpatterns = [
    path('new/', views.capture, name='capture'),
]
