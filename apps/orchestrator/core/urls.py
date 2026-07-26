from django.urls import path

from .views import (
    ConversationDetailView,
    ConversationListView,
    ConversationReprocessView,
    ConversationTraceView,
    HealthView,
    QueryView,
)

urlpatterns = [
    path("query/", QueryView.as_view(), name="query"),
    path("health/", HealthView.as_view(), name="health"),
    path("conversations/", ConversationListView.as_view(), name="conversation-list"),
    path(
        "conversations/<uuid:conversation_id>/",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path(
        "conversations/<uuid:conversation_id>/reprocess/",
        ConversationReprocessView.as_view(),
        name="conversation-reprocess",
    ),
    path(
        "conversations/<uuid:conversation_id>/trace/",
        ConversationTraceView.as_view(),
        name="conversation-trace",
    ),
]
