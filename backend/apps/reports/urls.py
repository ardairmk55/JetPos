from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("reports/templates", views.TemplateViewSet, basename="report-templates")
router.register("reports/schedules", views.ScheduleViewSet, basename="report-schedules")

urlpatterns = [
    path("reports/meta", views.ReportMetaView.as_view()),
    path("reports/run/<str:rtype>", views.ReportRunView.as_view()),
    path("dashboard", views.DashboardView.as_view()),
] + router.urls
