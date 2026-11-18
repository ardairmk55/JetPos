from django.http import JsonResponse

from apps.core import roles


class SupportAccessMiddleware:
    """Destek personeli işletme verisine yalnızca müşteri onaylı, süreli ve kapsamlı erişimle girer.
    Her istek ayrı ayrı kaydedilir; süre bitince/iptal edilince erişim anında kesilir (§15.3)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        grant = None
        if (user is not None and user.is_authenticated and user.role in (roles.SUPPORT, roles.TECH)
                and request.path.startswith("/api/") and not request.path.startswith(("/api/platform", "/api/auth", "/api/support"))):
            from .models import SupportAccessGrant
            from .services import scope_allows

            gid = request.headers.get("X-Support-Grant") or request.session.get("support_grant")
            if gid:
                grant = SupportAccessGrant.objects.select_related("business").filter(grant_id=gid, support_user=user).first()
                if grant is None or not grant.is_active:
                    request.session.pop("support_grant", None)
                    if grant is not None:
                        self._log(grant, request, 403)
                    return JsonResponse({"detail": "Destek erişim süresi doldu veya iptal edildi", "code": "grant_inactive"}, status=403)
                if not scope_allows(grant, request.method, request.path):
                    self._log(grant, request, 403)
                    return JsonResponse({"detail": "Bu işlem destek erişim kapsamında değil", "code": "grant_scope"}, status=403)
                request.support_grant = grant
                request.support_grant_id = str(grant.grant_id)
                request.business = grant.business
        response = self.get_response(request)
        if grant is not None:
            self._log(grant, request, response.status_code)
        return response

    @staticmethod
    def _log(grant, request, status):
        from .models import SupportActionLog

        SupportActionLog.objects.create(grant=grant, method=request.method, path=request.path[:300], status_code=status)
