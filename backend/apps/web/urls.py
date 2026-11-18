from django.urls import path, re_path
from django.views.generic import RedirectView

from . import views

api_urlpatterns = [
    path("search", views.SearchView.as_view()),
    path("help", views.HelpView.as_view()),
    path("setup", views.SetupView.as_view()),
    path("printer-probe", views.PrinterProbeView.as_view()),
]

page_urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url="/static/web/img/icon.svg", permanent=True)),
    path("login/", views.login_page),
    path("setup", views.setup_page),
    path("apply", views.apply_page),
    path("sw.js", views.service_worker),
    path("manifest.webmanifest", views.manifest),
    re_path(r"^(?!api/|static/|media/|admin/|ws/).*$", views.app_shell),
]
