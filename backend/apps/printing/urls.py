from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("printers", views.PrinterViewSet, basename="printers")
router.register("print-jobs", views.PrintJobViewSet, basename="print-jobs")

urlpatterns = router.urls
