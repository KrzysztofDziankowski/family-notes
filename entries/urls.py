from django.urls import path

from . import views

app_name = 'entries'

urlpatterns = [
    path('new/', views.capture, name='capture'),
    path('confirm/', views.confirm, name='confirm'),
    path('_states/', views.states, name='states'),
    # S-03 child view
    path('mine/', views.child_list, name='child_list'),
    path('mine/_states/', views.child_states, name='child_states'),
    path('mine/<int:pk>/', views.child_detail, name='child_detail'),
]
