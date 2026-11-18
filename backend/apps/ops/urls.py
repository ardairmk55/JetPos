from django.urls import path

from . import views

urlpatterns = [
    path("ops/backups", views.BackupsView.as_view()),
    path("ops/health", views.HealthView.as_view()),
    path("ops/updates", views.UpdatesView.as_view()),
    path("ops/failover", views.FailoverView.as_view()),
    path("ops/sync", views.SyncView.as_view()),
    path("central/ingest", views.CentralIngestView.as_view()),
]
