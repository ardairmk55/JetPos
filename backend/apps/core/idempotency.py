"""Idempotency (NFR-02): Aynı `Idempotency-Key` ile gelen tekrar istek ikinci kayıt üretmez."""
import functools
import json

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from rest_framework.response import Response

from .models import IdempotencyRecord
from .tenancy import current_business

IN_PROGRESS = 0


def get_key(request):
    key = request.headers.get("Idempotency-Key")
    if not key and hasattr(request, "data") and hasattr(request.data, "get"):
        key = request.data.get("idempotency_key")
    return (key or "").strip()[:100]


def idempotent(scope, required=True):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, request, *args, **kwargs):
            key = get_key(request)
            if not key:
                if required:
                    return Response({"detail": "Idempotency-Key başlığı zorunludur", "code": "idempotency_key_required"}, status=400)
                return fn(self, request, *args, **kwargs)
            biz = current_business(request)
            full_scope = f"{scope}:{kwargs.get('pk', '')}"
            try:
                with transaction.atomic():
                    rec = IdempotencyRecord.objects.create(
                        business=biz, key=key, scope=full_scope, user=request.user, status_code=IN_PROGRESS,
                        device=request.headers.get("X-Device", "")[:120],
                    )
            except IntegrityError:
                rec = IdempotencyRecord.objects.filter(business=biz, scope=full_scope, key=key).first()
                if rec is None or rec.status_code == IN_PROGRESS:
                    return Response({"detail": "Aynı işlem hâlen işleniyor", "code": "in_progress"}, status=409)
                resp = Response(rec.response, status=rec.status_code)
                resp["Idempotent-Replay"] = "true"
                return resp
            try:
                resp = fn(self, request, *args, **kwargs)
            except Exception:
                rec.delete()
                raise
            if resp.status_code >= 400:
                # Başarısız işlem tekrar denenebilsin
                rec.delete()
                return resp
            data = json.loads(json.dumps(resp.data, cls=DjangoJSONEncoder))
            IdempotencyRecord.objects.filter(pk=rec.pk).update(status_code=resp.status_code, response=data)
            return resp

        return wrapper

    return deco
