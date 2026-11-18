from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("stock/warehouses", views.WarehouseViewSet, basename="warehouses")
router.register("stock/suppliers", views.SupplierViewSet, basename="suppliers")
router.register("stock/items", views.StockItemViewSet, basename="stock-items")
router.register("stock/recipes", views.RecipeLineViewSet, basename="recipes")
router.register("stock/movements", views.MovementViewSet, basename="movements")

urlpatterns = [
    path("stock/overview", views.StockOverview.as_view()),
    path("stock/purchases", views.PurchaseView.as_view()),
    path("stock/transfers", views.TransferView.as_view()),
    path("stock/counts", views.CountView.as_view()),
] + router.urls
