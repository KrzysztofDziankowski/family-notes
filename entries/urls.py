from django.urls import path

from . import views

app_name = 'entries'

urlpatterns = [
    path('new/', views.capture, name='capture'),
    path('answer/', views.answer, name='answer'),
    path('correct/', views.correct, name='correct'),
    path('confirm/', views.confirm, name='confirm'),
    path('confirm-batch/', views.confirm_batch, name='confirm_batch'),
    path('_states/', views.states, name='states'),
    # S-03 child view
    path('mine/', views.child_list, name='child_list'),
    path('mine/_states/', views.child_states, name='child_states'),
    # Child natural-language capture: entries for the child only
    path('mine/new/', views.child_capture, name='child_capture'),
    path('mine/answer/', views.child_answer, name='child_answer'),
    path('mine/correct/', views.child_correct, name='child_correct'),
    path('mine/confirm/', views.child_confirm, name='child_confirm'),
    path('mine/confirm-batch/', views.child_confirm_batch, name='child_confirm_batch'),
    path('mine/<int:pk>/', views.child_detail, name='child_detail'),
    # Creator-only privacy change: the child's only post-creation action
    path('mine/<int:pk>/privacy/', views.child_privacy, name='child_privacy'),
    # S-02 parent management
    path('', views.index, name='index'),
    path('create/', views.create, name='create'),
    path('<int:pk>/', views.detail, name='detail'),
    path('<int:pk>/edit/', views.edit, name='edit'),
    path('<int:pk>/delete/', views.delete, name='delete'),
    path('<int:pk>/privacy/', views.privacy, name='privacy'),
]
