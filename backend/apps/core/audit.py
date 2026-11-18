import json

from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import AuditLog


def snapshot(instance, exclude=("password", "pin_hash", "two_factor_secret")):
    if instance is None:
        return None
    data = model_to_dict(instance)
    for k in exclude:
        data.pop(k, None)
    return json.loads(json.dumps(data, cls=DjangoJSONEncoder, default=str))


def client_ip(request):
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def log(action, *, request=None, user=None, business=None, branch=None, entity="", entity_id="",
        before=None, after=None, reason=""):
    if request is not None:
        user = user or (request.user if getattr(request, "user", None) and request.user.is_authenticated else None)
        business = business or getattr(request, "business", None) or getattr(user, "business", None)
        branch = branch or getattr(request, "branch", None)
    device = request.headers.get("X-Device", "")[:120] if request is not None else ""
    support = getattr(request, "support_grant_id", "") if request is not None else ""
    return AuditLog.objects.create(
        action=action,
        user=user,
        business=business,
        branch=branch,
        entity=entity,
        entity_id=str(entity_id or ""),
        before=before if before is None or isinstance(before, (dict, list)) else snapshot(before),
        after=after if after is None or isinstance(after, (dict, list)) else snapshot(after),
        reason=reason or "",
        ip=client_ip(request),
        device=device,
        support_session=str(support or ""),
    )
