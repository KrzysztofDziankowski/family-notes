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
    # S-02 parent management
    path('', views.index, name='index'),
    path('create/', views.create, name='create'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/delete/', views.delete, name='delete'),
]
