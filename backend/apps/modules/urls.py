from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("customers", views.CustomerViewSet, basename="customers")
router.register("couriers", views.CourierViewSet, basename="couriers")
router.register("deliveries", views.DeliveryViewSet, basename="deliveries")
router.register("reservations", views.ReservationViewSet, basename="reservations")
router.register("staff/shifts", views.ShiftViewSet, basename="shifts")
router.register("staff/attendance", views.AttendanceViewSet, basename="attendance")
router.register("staff/leaves", views.LeaveViewSet, basename="leaves")
router.register("finance/accounts", views.FinanceAccountViewSet, basename="finance-accounts")
router.register("finance/entries", views.FinanceEntryViewSet, basename="finance-entries")

urlpatterns = [path("staff/timeclock", views.TimeClockView.as_view())] + router.urls
