from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


class BusinessError(Exception):
    """İş kuralı ihlali; kullanıcıya açıkça gösterilir (sessiz veri kaybı yok)."""

    status_code = 400

    def __init__(self, message, code="business_rule", status_code=None, extra=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}
        if status_code:
            self.status_code = status_code


class ApprovalRequired(BusinessError):
    status_code = 403

    def __init__(self, message="Bu işlem yönetici onayı gerektirir", extra=None):
        super().__init__(message, code="approval_required", extra=extra)


def exception_handler(exc, context):
    if isinstance(exc, BusinessError):
        return Response({"detail": exc.message, "code": exc.code, **exc.extra}, status=exc.status_code)
    if isinstance(exc, DjangoValidationError):
        msg = "; ".join(exc.messages)
        return Response({"detail": msg, "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, DjangoPermissionDenied):
        return Response({"detail": str(exc) or "Yetkiniz yok", "code": "forbidden"}, status=403)
    resp = drf_handler(exc, context)
    if resp is not None and isinstance(resp.data, dict) and "detail" in resp.data:
        resp.data["code"] = getattr(exc, "default_code", "error")
    elif resp is not None and isinstance(resp.data, (dict, list)):
        resp.data = {"detail": _flatten(resp.data), "code": "invalid", "errors": resp.data}
    return resp


def _flatten(data):
    if isinstance(data, dict):
        return "; ".join(f"{k}: {_flatten(v)}" for k, v in data.items())
    if isinstance(data, list):
        return ", ".join(_flatten(v) for v in data)
    return str(data)
