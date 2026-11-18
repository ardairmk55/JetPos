from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("users", views.UserViewSet, basename="users")
router.register("branches", views.BranchViewSet, basename="branches")
router.register("notifications", views.NotificationViewSet, basename="notifications")
router.register("notification-rules", views.NotificationRuleViewSet, basename="notification-rules")
router.register("audit", views.AuditLogViewSet, basename="audit")

urlpatterns = [
    path("ping", views.ping),
    path("auth/login", views.LoginView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/me", views.MeView.as_view()),
    path("auth/preferences", views.PreferencesView.as_view()),
    path("auth/branch", views.SelectBranchView.as_view()),
    path("auth/lock", views.LockView.as_view()),
    path("auth/unlock", views.UnlockView.as_view()),
    path("auth/pin-users", views.PinUsersView.as_view()),
    path("auth/pin-switch", views.PinSwitchView.as_view()),
    path("auth/change-password", views.ChangePasswordView.as_view()),
    path("auth/set-pin", views.SetPinView.as_view()),
    path("auth/2fa", views.TwoFactorView.as_view()),
    path("business", views.BusinessView.as_view()),
    path("branch-settings", views.BranchSettingsView.as_view()),
] + router.urls
