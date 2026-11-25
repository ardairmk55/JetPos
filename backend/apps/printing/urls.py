from django.urls import path
from rest_framework.routers import DefaultRouter

from . import agent_api, views

router = DefaultRouter(trailing_slash=False)
router.register("printers", views.PrinterViewSet, basename="printers")
router.register("print-jobs", views.PrintJobViewSet, basename="print-jobs")

urlpatterns = router.urls + [
    path("print-agent/claim", agent_api.ClaimView.as_view()),
    path("print-agent/result", agent_api.ResultView.as_view()),
]
