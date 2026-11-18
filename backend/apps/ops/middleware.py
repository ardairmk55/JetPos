from django.conf import settings
from django.http import JsonResponse

SAFE = ("GET", "HEAD", "OPTIONS")


class WriterFenceMiddleware:
    """Yedeklilik modunda yalnızca lider düğüm yazabilir (split-brain önleme). Tek sunucuda kapalıdır."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.JETPOS["ENFORCE_WRITER_FENCE"] and request.method not in SAFE
                and request.path.startswith("/api/") and not request.path.startswith(("/api/ops/failover", "/api/auth"))):
            from .failover import is_writer

            if not is_writer(settings.JETPOS["NODE_ID"]):
                return JsonResponse({"detail": "Bu sunucu yazma yetkisine sahip değil (yedek/izole düğüm)",
                                     "code": "not_leader"}, status=503)
        return self.get_response(request)
