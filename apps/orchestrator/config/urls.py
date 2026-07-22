"""URL configuration for orchestrator project."""

from django.contrib import admin
from django.urls import include, path

from core.views import IndexView

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
