"""Bildirim ve gerçek zamanlı yayın (§7.2, §10.2).

LAN içi WebSocket yayınları internetsiz çalışır; e-posta internet ve SMTP yapılandırması gerektirir.
"""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q

from .models import Notification, NotificationRule, User

log = logging.getLogger(__name__)


def branch_group(branch_id):
    return f"b{branch_id}"


def role_group(branch_id, role):
    return f"b{branch_id}_{role}"


def user_group(user_id):
    return f"u{user_id}"


def broadcast(group, event, data):
    def _send():
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(group, {"type": "push", "event": event, "data": data})
        except Exception as exc:  # yayın hatası işlemi bozmamalı, ama loglanır
            log.warning("broadcast failed %s %s: %s", group, event, exc)

    transaction.on_commit(_send)


def notify(*, branch, event, title, body="", priority="low", roles=None, users=None, data=None, sound=False):
    """Rol(ler)e veya kullanıcılara bildirim üretir ve canlı yayınlar."""
    business = branch.business
    qs = User.objects.filter(business=business, is_active=True)
    cond = Q(pk__in=[u.pk for u in (users or [])])
    if roles:
        cond |= Q(role__in=roles) & (Q(branch=branch) | Q(branch__isnull=True))
    targets = list(qs.filter(cond).distinct())
    rules = {r.role: r for r in NotificationRule.objects.filter(business=business, event=event)}
    created = []
    for u in targets:
        rule = rules.get(u.role)
        if rule and not rule.in_app and not rule.email:
            continue
        pr = rule.priority if rule else priority
        n = Notification.objects.create(business=business, branch=branch, user=u, event=event, title=title, body=body,
                                        priority=pr, data=data or {})
        created.append(n)
        payload = {"id": n.id, "event": event, "title": title, "body": body, "priority": pr, "data": data or {},
                   "sound": bool(sound or (rule and rule.sound)), "created_at": n.created_at.isoformat()}
        broadcast(user_group(u.id), "notification", payload)
        if rule and rule.email and u.email:
            _email(u.email, title, body)
    return created


def _email(to, subject, body):
    def _send():
        try:
            send_mail(f"[POSHANE] {subject}", body or subject, None, [to], fail_silently=False)
        except Exception as exc:
            log.error("e-posta gönderilemedi %s: %s", to, exc)

    transaction.on_commit(_send)
