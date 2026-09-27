from django.urls import path

from . import views

app_name = 'entries'

urlpatterns = [
    path('new/', views.capture, name='capture'),
    path('confirm/', views.confirm, name='confirm'),
    path('_states/', views.states, name='states'),
]
