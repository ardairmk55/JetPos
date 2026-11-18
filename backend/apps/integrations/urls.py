from django.urls import path

from . import views

urlpatterns = [
    path("integrations/jetmenu", views.JetMenuSettingsView.as_view()),
    path("integrations/jetmenu/catalog", views.JetMenuCatalogView.as_view()),
    path("integrations/jetmenu/orders", views.JetMenuOrderView.as_view()),
    path("qr-orders", views.QrOrdersView.as_view()),
]
