from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("halls", views.HallViewSet, basename="halls")
router.register("tables", views.TableViewSet, basename="tables")
router.register("tickets", views.TicketViewSet, basename="tickets")
router.register("approvals", views.ApprovalViewSet, basename="approvals")
router.register("kitchen", views.KitchenViewSet, basename="kitchen")
router.register("payments", views.PaymentViewSet, basename="payments")

urlpatterns = [
    path("floor", views.FloorView.as_view()),
    path("ready-orders", views.ReadyOrdersView.as_view()),
    path("cash", views.CashView.as_view()),
    path("cash/days/<int:pk>", views.CashDayReportView.as_view()),
] + router.urls
