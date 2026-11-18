import threading
import time
from collections import defaultdict, deque

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from .audit import client_ip

_lock = threading.Lock()
_hits = defaultdict(deque)


def _allow(bucket, limit, window=60.0):
    now = time.monotonic()
    with _lock:
        q = _hits[bucket]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def reset_rate_limits():
    with _lock:
        _hits.clear()


class RateLimitMiddleware:
    """API rate limit (§15.2). Tek süreçli yerel sunucu için bellek içi pencere."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/api/"):
            ip = client_ip(request) or "?"
            cfg = settings.JETPOS
            if path.startswith("/api/auth/login") or path.startswith("/api/auth/pin"):
                if not _allow(f"login:{ip}", cfg["LOGIN_RATE_LIMIT_PER_MINUTE"]):
                    return JsonResponse({"detail": "Çok fazla deneme. Lütfen bekleyin.", "code": "rate_limited"}, status=429)
            elif not _allow(f"api:{ip}", cfg["RATE_LIMIT_PER_MINUTE"]):
                return JsonResponse({"detail": "İstek limiti aşıldı", "code": "rate_limited"}, status=429)
        return self.get_response(request)


UNLOCK_PATHS = ("/api/auth/unlock", "/api/auth/logout", "/api/auth/me", "/api/auth/pin-switch", "/api/auth/pin-users")


class ActivityMiddleware:
    """Hareketsizlikte otomatik kilit (§9.4, §15.1) sunucu tarafında da uygulanır."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and request.path.startswith("/api/"):
            sess = request.session
            now = time.time()
            last = sess.get("last_activity", now)
            minutes = 0
            if user.branch_id:
                try:
                    minutes = user.branch.settings.inactivity_lock_minutes
                except Exception:
                    minutes = 0
            if minutes and now - last > minutes * 60:
                sess["locked"] = True
            if sess.get("locked") and not request.path.startswith(UNLOCK_PATHS):
                return JsonResponse({"detail": "Oturum kilitli. PIN ile açın.", "code": "locked"}, status=423)
            sess["last_activity"] = now
            if user.is_locked:
                return JsonResponse({"detail": "Hesap geçici olarak kilitli", "code": "account_locked"}, status=423)
        return self.get_response(request)


def utcnow():
    return timezone.now()
