"""URL configuration for orchestrator project."""

from django.contrib import admin
from django.urls import include, path

from core.views import IndexView, dashboard_view

urlpatterns = [
    path("", IndexView.as_view(), name="index"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
