from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("devices", views.DeviceViewSet, basename="devices")
router.register("support/tickets", views.SupportTicketViewSet, basename="support-tickets")
router.register("support/grants", views.SupportGrantViewSet, basename="support-grants")
router.register("platform/businesses", views.PlatformBusinessViewSet, basename="platform-businesses")
router.register("platform/applications", views.ApplicationViewSet, basename="platform-applications")
router.register("platform/licenses", views.LicenseAdminViewSet, basename="platform-licenses")
router.register("platform/sla-policies", views.SLAPolicyViewSet, basename="platform-sla")
router.register("platform/payments", views.PlatformPaymentViewSet, basename="platform-payments")
router.register("platform/contracts", views.ContractViewSet, basename="platform-contracts")
router.register("platform/release-notes", views.ReleaseNoteViewSet, basename="platform-release-notes")

urlpatterns = [
    path("license", views.LicenseView.as_view()),
    path("portal/summary", views.PortalSummary.as_view()),
    path("public/apply", views.PublicApplyView.as_view()),
    path("platform/licenses/activate", views.RemoteActivateView.as_view()),
    path("platform/config", views.PlatformConfigView.as_view()),
] + router.urls
