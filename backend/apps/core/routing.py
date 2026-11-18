from django.urls import path

from .consumers import BranchConsumer

websocket_urlpatterns = [path("ws/branch/", BranchConsumer.as_asgi())]
