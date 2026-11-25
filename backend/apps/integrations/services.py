"""JET Menü entegrasyonu (§11): sert bağımlılık yok; internet kesilince yerel operasyon sürer, kuyruk sonra gönderilir."""
import hashlib
import hmac
import json
import urllib.error
import urllib.request

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import roles
from apps.core.exceptions import BusinessError
from apps.core.notify import notify

from .models import IntegrationConfig, OutboxMessage, QrOrder


def _config(business):
    return IntegrationConfig.objects.filter(business=business, enabled=True).first()


def queue_catalog_change(product):
    cfg = _config(product.business)
    if not cfg:
        return None
    return OutboxMessage.objects.create(business=product.business, kind="product.upsert", payload={
        "uid": str(product.uid), "name": product.name, "name_en": product.name_en,
        "category_uid": str(product.category.uid), "category": product.category.name,
        "price": str(product.base_price), "active": product.is_active, "updated_at": product.updated_at.isoformat()})


def catalog_export(business, branch):
    from apps.catalog.models import Category, Product
    from apps.catalog.pricing import resolve_price
    from apps.inventory.services import availability_map
    from django.db.models import Q

    products = Product.objects.filter(business=business, is_active=True).filter(
        Q(branches__isnull=True) | Q(branches=branch)).distinct().select_related("category").prefetch_related("option_groups__options")
    stock = availability_map(branch, [p.id for p in products])
    return {
        "branch": branch.code,
        "generated_at": timezone.now().isoformat(),
        "categories": [{"uid": str(c.uid), "name": c.name, "name_en": c.name_en, "sort": c.sort}
                       for c in Category.objects.filter(business=business, is_active=True).filter(
                           Q(branches__isnull=True) | Q(branches=branch)).distinct()],
        "products": [{"uid": str(p.uid), "category_uid": str(p.category.uid), "name": p.name, "name_en": p.name_en,
                      "description": p.description, "price": str(resolve_price(p, branch=branch, channel="qr")),
                      "available": stock.get(p.id) != "out", "image": p.image.url if p.image else "",
                      "option_groups": [{"id": g.id, "name": g.name, "required": g.required, "min": g.min_select,
                                         "max": g.max_select,
                                         "options": [{"id": o.id, "name": o.name, "price": str(o.price_delta)}
                                                     for o in g.options.filter(is_active=True)]}
                                        for g in p.option_groups.all()]}
                     for p in products],
    }


def receive_qr_order(business, *, external_id, table_token, items, note=""):
    from apps.catalog.models import Product
    from apps.pos.models import Table

    cfg = _config(business)
    if not cfg:
        raise BusinessError("JET Menü entegrasyonu etkin değil", status_code=403)
    table = Table.objects.filter(business=business, qr_token=table_token, is_active=True).first()
    if not table:
        raise BusinessError("Masa bulunamadı", status_code=404)
    if not items:
        raise BusinessError("Sipariş boş")
    norm = []
    for it in items:
        p = Product.objects.filter(business=business, uid=it.get("product_uid"), is_active=True).first()
        if not p:
            raise BusinessError(f"Ürün bulunamadı: {it.get('product_uid')}")
        norm.append({"product": p.id, "name": p.name, "qty": str(it.get("qty", 1)),
                     "options": [int(o) for o in it.get("options", [])], "note": str(it.get("note", ""))[:300]})
    try:
        with transaction.atomic():
            order = QrOrder.objects.create(business=business, branch=table.branch, table=table,
                                           external_id=str(external_id)[:80], items=norm, note=note[:300])
    except IntegrityError:
        return QrOrder.objects.get(business=business, external_id=str(external_id)[:80]), False
    _refresh_floor(table.branch)
    if cfg.auto_accept_qr:
        accept_qr_order(order, user=None)
    else:
        notify(branch=table.branch, event="qr_order", title=f"QR sipariş: Masa {table.name}",
               body=", ".join(f"{i['qty']} x {i['name']}" for i in norm), priority="high",
               roles=[roles.WAITER, roles.CASHIER, roles.BRANCH_MANAGER], sound=True, data={"qr_order": order.id})
    return order, True


def accept_qr_order(order, *, user):
    from apps.pos import services as pos

    if order.status != "received":
        raise BusinessError("Sipariş zaten işlenmiş")
    actor = user
    with transaction.atomic():
        order = QrOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != "received":
            raise BusinessError("Sipariş zaten işlenmiş")
        ticket, _ = pos.open_ticket(branch=order.branch, user=actor, table=order.table, source="qr")
        for i, it in enumerate(order.items):
            pos.add_line(ticket, user=actor, product_id=it["product"], qty=it["qty"], option_ids=it["options"],
                         note=it["note"], client_uid=f"qr:{order.external_id}:{i}")
        order.status = "accepted"
        order.ticket = ticket
        order.decided_by = user
        order.save(update_fields=["status", "ticket", "decided_by"])
    _refresh_floor(order.branch)
    return order


def _refresh_floor(branch):
    from apps.pos.services import broadcast_floor

    broadcast_floor(branch)


def reject_qr_order(order, *, user, reason=""):
    if order.status != "received":
        raise BusinessError("Sipariş zaten işlenmiş")
    order.status = "rejected"
    order.error = reason[:300]
    order.decided_by = user
    order.save(update_fields=["status", "error", "decided_by"])
    _refresh_floor(order.branch)
    return order


def push_outbox(transport=None):
    sent = 0
    for cfg in IntegrationConfig.objects.filter(enabled=True).exclude(webhook_url=""):
        msgs = list(OutboxMessage.objects.filter(business=cfg.business, status__in=("pending", "failed"),
                                                 attempts__lt=20)[:100])
        if not msgs:
            continue
        body = json.dumps([{"id": m.id, "kind": m.kind, "payload": m.payload} for m in msgs]).encode()
        sig = hmac.new(cfg.signing_secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            if transport:
                transport(cfg.webhook_url, body, sig)
            else:
                req = urllib.request.Request(cfg.webhook_url, data=body, headers={
                    "Content-Type": "application/json", "X-JETPOS-Signature": sig})
                with urllib.request.urlopen(req, timeout=15):
                    pass
        except (urllib.error.URLError, OSError) as e:
            for m in msgs:
                m.attempts += 1
                m.status = "failed"
                m.last_error = str(e)[:300]
            OutboxMessage.objects.bulk_update(msgs, ["attempts", "status", "last_error"])
            continue
        now = timezone.now()
        for m in msgs:
            m.status = "sent"
            m.sent_at = now
        OutboxMessage.objects.bulk_update(msgs, ["status", "sent_at"])
        cfg.last_push_at = now
        cfg.save(update_fields=["last_push_at"])
        sent += len(msgs)
    return sent
