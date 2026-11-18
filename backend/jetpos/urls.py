from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.web.urls import api_urlpatterns, page_urlpatterns

api = [
    path("", include("apps.core.urls")),
    path("", include("apps.catalog.urls")),
    path("", include("apps.pos.urls")),
    path("", include("apps.printing.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.modules.urls")),
    path("", include("apps.reports.urls")),
    path("", include("apps.licensing.urls")),
    path("", include("apps.ops.urls")),
    path("", include("apps.integrations.urls")),
    path("", include(api_urlpatterns)),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(api)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) + page_urlpatterns
