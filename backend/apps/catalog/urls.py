from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("tax-rates", views.TaxRateViewSet, basename="tax-rates")
router.register("stations", views.StationViewSet, basename="stations")
router.register("customer-groups", views.CustomerGroupViewSet, basename="customer-groups")
router.register("categories", views.CategoryViewSet, basename="categories")
router.register("option-groups", views.OptionGroupViewSet, basename="option-groups")
router.register("products", views.ProductViewSet, basename="products")
router.register("product-prices", views.ProductPriceViewSet, basename="product-prices")
router.register("campaigns", views.CampaignViewSet, basename="campaigns")

urlpatterns = [path("catalog/stats", views.CatalogStatsView.as_view())] + router.urls
