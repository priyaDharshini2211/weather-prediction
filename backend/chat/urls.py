from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("documents/", views.DocumentListCreateView.as_view()),
    path("documents/<int:pk>/", views.DocumentDetailView.as_view()),
    path("chat/", views.ChatView.as_view()),
    path("conversations/<uuid:conversation_id>/messages/", views.ConversationMessagesView.as_view()),
]
