"""POS iş kuralları (§5, §6, §7). Tüm finansal işlemler atomik, denetlenebilir ve idempotent."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.catalog.models import CustomerGroup, Option, Product
from apps.catalog.pricing import apply_campaigns, money, resolve_price
from apps.core import audit, roles
from apps.core.exceptions import ApprovalRequired, BusinessError
from apps.core.models import SyncEvent, User
from apps.core.notify import branch_group, broadcast, notify

from .models import (ACTIVE_TICKET_STATES, ApprovalRequest, CashDay, CashMovement, DailyCounter, KitchenBatch,
                     KitchenOrder, Payment, PaymentAllocation, Refund, Table, Ticket, TicketDiscount, TicketLine)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------- yardımcılar
def emit_sync(branch, kind, payload, user=None):
    from django.conf import settings

    SyncEvent.objects.create(business=branch.business, branch=branch, kind=kind, payload=payload,
                             node_id=settings.JETPOS["NODE_ID"], user=user)


def next_number(branch, name="ticket"):
    today = timezone.localdate()
    with transaction.atomic():
        c, _ = DailyCounter.objects.select_for_update().get_or_create(branch=branch, date=today, name=name)
        c.value += 1
        c.save(update_fields=["value"])
        return c.value


def primary_table(table):
    seen = set()
    while table.merged_into_id and table.id not in seen:
        seen.add(table.id)
        table = table.merged_into
    return table


def authorize(user, perm, approver=None):
    """Hassas işlem yetkisi: kullanıcının yetkisi yoksa yetkili kişinin PIN/şifresiyle ek doğrulama (§15.1).

    approver: {"user_id": .., "pin": ..} veya {"username": .., "password": ..}
    Dönüş: işlemi onaylayan kullanıcı.
    """
    if roles.has_perm(user, perm):
        return user
    if approver:
        q = User.objects.filter(business=user.business, is_active=True)
        cand = q.filter(pk=approver.get("user_id")).first() if approver.get("user_id") else q.filter(
            username=approver.get("username", "")).first()
        ok = cand and ((approver.get("pin") and cand.check_pin(approver["pin"])) or
                       (approver.get("password") and cand.check_password(approver["password"])))
        if not ok:
            raise BusinessError("Onaylayan kullanıcı doğrulanamadı", code="approver_invalid", status_code=403)
        if not roles.has_perm(cand, perm):
            raise BusinessError("Onaylayan kullanıcının bu işlem için yetkisi yok", code="approver_forbidden", status_code=403)
        if user.branch_id and cand.branch_id and cand.branch_id != user.branch_id:
            raise BusinessError("Onaylayan farklı şubeye bağlı", code="approver_forbidden", status_code=403)
        return cand
    raise ApprovalRequired(extra={"perm": perm})


def _require_reason(reason):
    if not reason or len(str(reason).strip()) < 3:
        raise BusinessError("Gerekçe zorunludur (en az 3 karakter)", code="reason_required")
    return str(reason).strip()[:300]


def table_payload(table):
    from .serializers import table_state

    return table_state(table)


def broadcast_table(ticket_or_table):
    table = ticket_or_table if isinstance(ticket_or_table, Table) else ticket_or_table.table
    branch = ticket_or_table.branch
    data = {"table": table.id if table else None}
    if isinstance(ticket_or_table, Ticket):
        data["ticket"] = ticket_or_table.id
    broadcast(branch_group(branch.id), "table", data)


def broadcast_floor(branch):
    """Masaya bağlı olmayan plan değişiklikleri (salon/masa, rezervasyon, QR kuyruğu)."""
    broadcast(branch_group(branch.id), "table", {"table": None})


# ---------------------------------------------------------------- adisyon
def blank_tickets():
    """Masaya dokunulmuş ama hiçbir işlem yapılmamış adisyonlar.

    Bunlar masayı "dolu" göstermez, sayaçlara girmez ve taşıma/birleştirme/rezervasyonu engellemez.
    """
    return Ticket.objects.filter(
        status="open", source="pos", channel__in=("table", "takeaway"), reservation__isnull=True,
        customer__isnull=True, customer_group__isnull=True, lines__isnull=True, payments__isnull=True,
        batches__isnull=True, discounts__isnull=True, approvals__isnull=True)


def live_tickets(qs):
    """Gerçekten devam eden adisyonlar."""
    return qs.filter(status__in=ACTIVE_TICKET_STATES).exclude(pk__in=blank_tickets().values("pk"))


def discard_blank_ticket(table, *, user):
    for t in Ticket.objects.filter(pk__in=blank_tickets().filter(table=table).values("pk")):
        t.status = "cancelled"
        t.closed_at = timezone.now()
        t.closed_by = user
        t.save(update_fields=["status", "closed_at", "closed_by"])
        audit.log("ticket.cancel", user=user, business=t.business, branch=t.branch, entity="Ticket", entity_id=t.pk,
                  after={"blank": True})
        broadcast_table(t)


def _lock_ticket(pk):
    return Ticket.objects.select_for_update().get(pk=pk)


def open_ticket(*, branch, user, table=None, channel="table", guest_count=1, customer=None, source="pos"):
    if table is not None:
        if table.branch_id != branch.id or not table.is_active:
            raise BusinessError("Masa bu şubeye ait değil")
        table = primary_table(table)
        existing = Ticket.objects.filter(table=table, status__in=ACTIVE_TICKET_STATES).first()
        if existing:
            return existing, False
    elif channel == "table":
        raise BusinessError("Masa seçilmeli")
    elif channel == "takeaway" and customer is None and source == "pos":
        # Boş kalan gel-al adisyonu yeniden kullanılır; her dokunuşta yenisi birikmez
        spare = Ticket.objects.filter(pk__in=blank_tickets().filter(
            branch=branch, channel="takeaway", waiter=user).values("pk")).first()
        if spare:
            return spare, False
    try:
        with transaction.atomic():
            t = Ticket.objects.create(
                business=branch.business, branch=branch, table=table, channel=channel, waiter=user,
                number=next_number(branch), business_date=timezone.localdate(), guest_count=guest_count or 1,
                customer=customer, source=source,
            )
    except IntegrityError:
        # Eşzamanlı açılış: tek aktif adisyon kısıtı ikinci kaydı engeller
        return Ticket.objects.get(table=table, status__in=ACTIVE_TICKET_STATES), False
    audit.log("ticket.open", user=user, business=branch.business, branch=branch, entity="Ticket", entity_id=t.pk,
              after={"number": t.number, "table": table.name if table else None, "channel": channel})
    broadcast_table(t)
    return t, True


def _ensure_editable(ticket):
    if ticket.status not in ("open", "bill_requested"):
        raise BusinessError("Adisyon ödenmiş veya kapalı; ürün eklenemez", code="ticket_locked")


def _validate_options(product, option_ids):
    option_ids = [int(o) for o in (option_ids or [])]
    groups = list(product.option_groups.prefetch_related("options"))
    valid = {o.id: (g, o) for g in groups for o in g.options.all() if o.is_active}
    for oid in option_ids:
        if oid not in valid:
            raise BusinessError("Geçersiz ürün seçeneği", code="invalid_option")
    chosen = []
    for g in groups:
        sel = [valid[o][1] for o in option_ids if valid[o][0].id == g.id]
        mn = max(g.min_select, 1 if g.required else 0)
        if len(sel) < mn:
            raise BusinessError(f"'{g.name}' için en az {mn} seçim yapılmalı", code="option_min")
        if g.max_select and len(sel) > g.max_select:
            raise BusinessError(f"'{g.name}' için en fazla {g.max_select} seçim yapılabilir", code="option_max")
        for o in sel:
            chosen.append({"id": o.id, "group": g.name, "kind": g.kind, "name": o.name, "price": str(money(o.price_delta))})
    return chosen


def add_line(ticket, *, user, product_id, qty=1, option_ids=None, note="", seat=None, client_uid=""):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        _ensure_editable(ticket)
        if client_uid:
            dup = ticket.lines.filter(client_uid=client_uid).first()
            if dup:
                return dup, False
        product = Product.objects.filter(pk=product_id, business=ticket.business, is_active=True).first()
        if not product:
            raise BusinessError("Ürün bulunamadı veya pasif")
        if product.branches.exists() and not product.branches.filter(pk=ticket.branch_id).exists():
            raise BusinessError("Ürün bu şubede satılmıyor")
        qty = Decimal(str(qty))
        if qty <= 0 or qty > 999:
            raise BusinessError("Geçersiz miktar")
        from apps.inventory.services import check_availability

        state = check_availability(ticket.branch, product, qty)
        if state == "block":
            raise BusinessError(f"'{product.name}' stokta yok; satış engellendi", code="out_of_stock")
        chosen = _validate_options(product, option_ids)
        base = resolve_price(product, branch=ticket.branch, channel=ticket.channel, customer_group=ticket.customer_group)
        unit = money(base + sum(Decimal(c["price"]) for c in chosen))
        if blank_tickets().filter(pk=ticket.pk).exists():
            # İlk gerçek işlem: süre, personel ve iş günü eski boş açılıştan devralınmaz
            ticket.opened_at = timezone.now()
            ticket.waiter = user or ticket.waiter
            if ticket.business_date != timezone.localdate():
                ticket.business_date = timezone.localdate()
                ticket.number = next_number(ticket.branch)
            ticket.save(update_fields=["opened_at", "waiter", "business_date", "number"])
        line = TicketLine.objects.create(
            ticket=ticket, product=product, name=product.name, qty=qty, base_price=base, unit_price=unit,
            options=chosen, note=(note or "")[:300], tax_rate=product.effective_tax(),
            tax_included=product.tax_included, station=product.effective_station(), status="draft",
            created_by=user, seat=seat, client_uid=(client_uid or "")[:64],
        )
        if ticket.status == "bill_requested":
            ticket.status = "open"
            ticket.save(update_fields=["status"])
        recalc(ticket)
    broadcast_table(ticket)
    line.stock_warning = state == "warn"
    return line, True


def _lock_line(line):
    """Adisyonu ve satırı kilitleyip güncel halini döndürür (başka cihazın değişikliği ezilmesin)."""
    ticket = _lock_ticket(line.ticket_id)
    fresh = TicketLine.objects.select_for_update().filter(pk=line.pk).first()
    if fresh is None:
        raise BusinessError("Satır başka bir cihazdan silinmiş", code="line_gone")
    fresh.ticket = ticket
    return fresh, ticket


@transaction.atomic
def update_line(line, *, user, qty=None, note=None, option_ids=None, seat="__keep__"):
    line, ticket = _lock_line(line)
    if line.status != "draft":
        # Gönderilmiş ürün sessizce değiştirilemez (§5.4); yalnızca kişi ataması (hesap bölme) yapılabilir
        if qty is not None or note is not None or option_ids is not None:
            raise BusinessError("Mutfağa gönderilmiş ürün değiştirilemez; gerekçeli iptal kullanın", code="line_sent")
        if seat != "__keep__":
            line.seat = seat
            line.save(update_fields=["seat"])
        return line
    _ensure_editable(ticket)
    if qty is not None:
        qty = Decimal(str(qty))
        if qty <= 0 or qty > 999:
            raise BusinessError("Geçersiz miktar")
        line.qty = qty
    if note is not None:
        line.note = note[:300]
    if option_ids is not None:
        line.options = _validate_options(line.product, option_ids)
        line.unit_price = money(line.base_price + sum(Decimal(c["price"]) for c in line.options))
    if seat != "__keep__":
        line.seat = seat
    line.save()
    recalc(ticket)
    broadcast_table(ticket)
    return line


@transaction.atomic
def delete_draft_line(line, *, user):
    line, ticket = _lock_line(line)
    if line.status != "draft":
        raise BusinessError("Yalnızca taslak ürün silinebilir; gönderilmiş ürün için iptal kullanın", code="line_sent")
    _ensure_editable(ticket)
    line.delete()
    recalc(ticket)
    broadcast_table(ticket)


def recalc(ticket):
    """Toplamları yeniden hesaplar: kampanya → adisyon indirimi (oransal) → vergi."""
    lines = list(ticket.lines.exclude(status="void").select_related("product", "product__category"))
    camp = apply_campaigns(lines, business=ticket.business, branch=ticket.branch, channel=ticket.channel,
                           customer_group=ticket.customer_group) if lines else {}
    subtotal = ZERO
    after = []
    for i, ln in enumerate(lines):
        gross = money(ln.unit_price * ln.qty)
        c = camp.get(i)
        ln.campaign_discount = money(c[1]) if c else ZERO
        ln.campaign_name = c[0].name if c and c[1] > 0 else ""
        subtotal += gross
        after.append(gross - ln.campaign_discount)
    base = sum(after, ZERO)
    disc_total = ZERO
    for d in ticket.discounts.filter(reversed_at__isnull=True).order_by("id"):
        room = base - disc_total
        if d.kind == "percent" or (d.kind == "group" and d.customer_group and d.customer_group.discount_type == "percent"):
            amt = money(room * d.value / 100)
        else:
            amt = money(min(d.value, room))
        if d.kind == "group" and d.customer_group and d.customer_group.max_discount is not None:
            amt = min(amt, d.customer_group.max_discount)
        amt = max(ZERO, min(amt, room))
        if d.amount != amt:
            d.amount = amt
            d.save(update_fields=["amount"])
        disc_total += amt
    total = ZERO
    tax_total = ZERO
    remaining_disc = disc_total
    for i, ln in enumerate(lines):
        share = remaining_disc if i == len(lines) - 1 else (money(disc_total * after[i] / base) if base else ZERO)
        remaining_disc -= share
        net = after[i] - share
        rate = ln.tax_rate / 100
        if ln.tax_included:
            tax = money(net - net / (1 + rate)) if rate else ZERO
            collect = net
        else:
            tax = money(net * rate)
            collect = net + tax
        ln.net_total = money(collect)
        ln.tax_amount = tax
        total += ln.net_total
        tax_total += tax
    if lines:
        TicketLine.objects.bulk_update(lines, ["campaign_discount", "campaign_name", "net_total", "tax_amount"])
    paid = ticket.payments.aggregate(s=Sum("amount"), r=Sum("refunded_amount"))
    ticket.subtotal = money(subtotal)
    ticket.campaign_discount = money(sum((ln.campaign_discount for ln in lines), ZERO))
    ticket.discount_total = money(disc_total)
    ticket.tax_total = money(tax_total)
    ticket.total = money(total)
    ticket.paid_total = money((paid["s"] or ZERO) - (paid["r"] or ZERO))
    ticket.save(update_fields=["subtotal", "campaign_discount", "discount_total", "tax_total", "total", "paid_total",
                               "updated_at"])
    return ticket


def line_due(line):
    allocated = line.allocations.aggregate(s=Sum("amount"))["s"] or ZERO
    return max(ZERO, line.net_total - allocated)


# ---------------------------------------------------------------- mutfak
def send_to_kitchen(ticket, *, user, confirmed=False):
    from apps.inventory.services import check_availability, deduct_for_lines

    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        _ensure_editable(ticket)
        drafts = list(ticket.lines.filter(status="draft").select_related("product", "station"))
        if not drafts:
            raise BusinessError("Gönderilecek taslak ürün yok", code="nothing_to_send")
        settings = ticket.branch.settings
        first = not ticket.batches.exists()
        summary = [{"name": ln.name, "qty": str(ln.qty), "options": [o["name"] for o in ln.options], "note": ln.note}
                   for ln in drafts]
        if first and settings.confirm_first_send and not confirmed:
            raise BusinessError("İlk gönderim için onay gerekli", code="confirmation_required", status_code=409,
                                extra={"summary": summary})
        for ln in drafts:
            if not ln.product.is_active:
                raise BusinessError(f"'{ln.name}' artık satışta değil", code="product_inactive")
            if check_availability(ticket.branch, ln.product, ln.qty) == "block":
                raise BusinessError(f"'{ln.name}' stokta yok; gönderim engellendi", code="out_of_stock")
        number = (ticket.batches.order_by("-number").values_list("number", flat=True).first() or 0) + 1
        batch = KitchenBatch.objects.create(ticket=ticket, number=number, sent_by=user)
        now = timezone.now()
        stations = {}
        for ln in drafts:
            ln.status = "sent"
            ln.batch = batch
            ln.sent_at = now
            if ln.station_id:
                stations[ln.station_id] = ln.station
        TicketLine.objects.bulk_update(drafts, ["status", "batch", "sent_at"])
        for st in stations.values():
            KitchenOrder.objects.create(batch=batch, station=st)
        if not stations:
            # Hazırlık gerektirmeyen ürünler (istasyonsuz) doğrudan hazır sayılır
            batch.status = "ready"
            batch.ready_at = now
            batch.save(update_fields=["status", "ready_at"])
        if ticket.status == "bill_requested":
            ticket.status = "open"
            ticket.save(update_fields=["status"])
        if settings.stock_deduction == "send":
            deduct_for_lines(drafts, user=user)
        audit.log("ticket.send", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
                  entity_id=ticket.pk, after={"batch": number, "lines": summary})
        from apps.printing.services import enqueue_kitchen

        enqueue_kitchen(batch)
    broadcast(branch_group(ticket.branch_id), "kitchen", {"batch": batch.id, "ticket": ticket.id, "action": "new"})
    broadcast_table(ticket)
    return batch


def kitchen_start(order, *, user):
    from apps.inventory.services import deduct_for_lines

    with transaction.atomic():
        order = KitchenOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != "new":
            return order
        order.status = "preparing"
        order.started_at = timezone.now()
        order.save(update_fields=["status", "started_at"])
        ticket = order.batch.ticket
        if ticket.branch.settings.stock_deduction == "prep":
            deduct_for_lines(list(order.batch.lines.filter(station=order.station, status="sent")), user=user)
    broadcast(branch_group(ticket.branch_id), "kitchen", {"order": order.id, "action": "start"})
    return order


def kitchen_ready(order, *, user):
    """İstasyon personeli tek butonla kendi kısmını hazır işaretler; tüm istasyonlar hazır olunca parti hazır olur."""
    with transaction.atomic():
        order = KitchenOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != "ready":
            if order.status == "new":
                kitchen_start(order, user=user)
            order.status = "ready"
            order.ready_at = timezone.now()
            order.ready_by = user
            order.save(update_fields=["status", "ready_at", "ready_by"])
        return _maybe_batch_ready(order.batch, user)


def batch_ready_all(batch, *, user):
    """Yönetici merkezi görünümünden tüm adisyon partisini tek butonla hazır işaretler."""
    with transaction.atomic():
        for o in batch.orders.exclude(status="ready"):
            if o.status == "new":
                kitchen_start(o, user=user)
            o.status = "ready"
            o.ready_at = timezone.now()
            o.ready_by = user
            o.save(update_fields=["status", "ready_at", "ready_by"])
        return _maybe_batch_ready(batch, user)


def _maybe_batch_ready(batch, user):
    batch = KitchenBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status != "pending":
        return batch
    if batch.orders.exclude(status="ready").exists():
        broadcast(branch_group(batch.ticket.branch_id), "kitchen", {"batch": batch.id, "action": "partial"})
        return batch
    batch.status = "ready"
    batch.ready_at = timezone.now()
    batch.save(update_fields=["status", "ready_at"])
    t = batch.ticket
    label = f"Masa {t.table.name}" if t.table else f"Adisyon #{t.number}"
    audit.log("kitchen.ready", user=user, business=t.business, branch=t.branch, entity="KitchenBatch", entity_id=batch.pk)
    notify(branch=t.branch, event="order_ready", title=f"{label} hazır", body=f"Parti {batch.number}",
           priority="high", users=[t.waiter] if t.waiter else [], roles=None if t.waiter else [roles.WAITER],
           data={"ticket": t.id, "batch": batch.id, "table": t.table_id}, sound=True)
    broadcast(branch_group(t.branch_id), "ready", {"batch": batch.id, "ticket": t.id, "table": t.table_id, "label": label})
    broadcast_table(t)
    return batch


@transaction.atomic
def pickup_batch(batch, *, user):
    batch = KitchenBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == "picked_up":
        return batch  # iki cihaz aynı anda "teslim aldım" derse ikincisi hata görmez
    if batch.status != "ready":
        raise BusinessError("Sipariş henüz hazır değil")
    batch.status = "picked_up"
    batch.picked_up_at = timezone.now()
    batch.picked_up_by = user
    batch.save(update_fields=["status", "picked_up_at", "picked_up_by"])
    broadcast(branch_group(batch.ticket.branch_id), "ready", {"batch": batch.id, "action": "picked_up"})
    broadcast_table(batch.ticket)
    return batch


def set_priority(order, *, user, priority):
    order.priority = int(priority)
    order.save(update_fields=["priority"])
    audit.log("kitchen.priority", user=user, business=order.batch.ticket.business, branch=order.batch.ticket.branch,
              entity="KitchenOrder", entity_id=order.pk, after={"priority": order.priority})
    broadcast(branch_group(order.batch.ticket.branch_id), "kitchen", {"order": order.id, "action": "priority"})
    return order


# ---------------------------------------------------------------- iptal / indirim
def void_line(line, *, user, reason, qty=None, approver=None, approved_by=None):
    from apps.inventory.services import reverse_for_line

    reason = _require_reason(reason)
    if line.status == "draft":
        raise BusinessError("Taslak ürün iptal yerine silinir")
    if line.status == "void":
        raise BusinessError("Ürün zaten iptal edilmiş")
    approved_by = approved_by or authorize(user, roles.TICKET_VOID, approver)
    with transaction.atomic():
        line = TicketLine.objects.select_for_update().get(pk=line.pk)
        ticket = Ticket.objects.select_for_update().get(pk=line.ticket_id)
        if ticket.status not in ("open", "bill_requested"):
            raise BusinessError("Ödenmiş/kapalı adisyonda iptal yapılamaz; iade kullanın")
        if line.allocations.exists():
            raise BusinessError("Tahsil edilmiş ürün iptal edilemez; iade kullanın")
        qty = Decimal(str(qty)) if qty else line.qty
        if qty <= 0 or qty > line.qty:
            raise BusinessError("Geçersiz iptal miktarı")
        before_total = ticket.total
        now = timezone.now()
        if qty < line.qty:
            line.qty -= qty
            line.save(update_fields=["qty"])
            void = TicketLine.objects.create(
                ticket=ticket, product=line.product, name=line.name, qty=qty, base_price=line.base_price,
                unit_price=line.unit_price, options=line.options, note=line.note, tax_rate=line.tax_rate,
                tax_included=line.tax_included, station=line.station, status="void", batch=line.batch,
                created_by=line.created_by, sent_at=line.sent_at, voided_from=line,
                void_reason=reason, voided_by=approved_by, voided_at=now)
        else:
            void = line
            void.status = "void"
            void.void_reason = reason
            void.voided_by = approved_by
            void.voided_at = now
            void.save(update_fields=["status", "void_reason", "voided_by", "voided_at"])
        reverse_for_line(line, qty=qty, user=user, kind="void")
        recalc(ticket)
        audit.log("ticket.void", user=user, business=ticket.business, branch=ticket.branch, entity="TicketLine",
                  entity_id=void.pk, reason=reason,
                  before={"total": str(before_total)},
                  after={"total": str(ticket.total), "product": line.name, "qty": str(qty),
                         "approved_by": approved_by.username})
        from apps.printing.services import enqueue_void

        enqueue_void(void)
        _maybe_resolve_batch_after_void(void, user)
    if void.station_id:
        notify(branch=ticket.branch, event="kitchen_void", title=f"İPTAL: {void.name} x{qty}",
               body=f"Adisyon #{ticket.number} — {reason}", priority="high", roles=[roles.KITCHEN], sound=True,
               data={"ticket": ticket.id, "line": void.id, "station": void.station_id})
    broadcast(branch_group(ticket.branch_id), "kitchen", {"ticket": ticket.id, "line": void.id, "action": "void"})
    broadcast_table(ticket)
    return void


def _maybe_resolve_batch_after_void(void, user):
    if not void.batch_id:
        return
    batch = KitchenBatch.objects.select_for_update().get(pk=void.batch_id)
    if batch.status == "picked_up":
        return
    sent = batch.lines.filter(status="sent")
    for o in batch.orders.exclude(status="ready"):
        if not sent.filter(station=o.station).exists():
            o.status = "ready"
            o.ready_at = timezone.now()
            o.save(update_fields=["status", "ready_at"])
    if not sent.exists():
        # Partide ürün kalmadı: mutfakta da "hazır" listesinde de beklememeli
        batch.status = "picked_up"
        batch.save(update_fields=["status"])
        broadcast(branch_group(batch.ticket.branch_id), "ready", {"batch": batch.id, "action": "picked_up"})
    elif batch.status == "pending" and not batch.orders.exclude(status="ready").exists():
        _maybe_batch_ready(batch, user)


def apply_discount(ticket, *, user, kind, value, reason, approver=None, approved_by=None):
    reason = _require_reason(reason)
    if kind not in ("percent", "fixed"):
        raise BusinessError("Geçersiz indirim türü")
    value = Decimal(str(value))
    if value <= 0:
        raise BusinessError("İndirim değeri pozitif olmalı")
    approved_by = approved_by or authorize(user, roles.TICKET_DISCOUNT, approver)
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        _ensure_editable(ticket)
        settings = ticket.branch.settings
        recalc(ticket)
        if kind == "percent" and value > settings.max_discount_percent:
            raise BusinessError(f"İndirim üst limiti %{settings.max_discount_percent}", code="discount_limit")
        if kind == "fixed" and value > ticket.remaining:
            raise BusinessError("İndirim kalan tutardan büyük olamaz", code="discount_limit")
        before = ticket.total
        d = TicketDiscount.objects.create(ticket=ticket, kind=kind, value=value, reason=reason, created_by=user,
                                          approved_by=approved_by)
        recalc(ticket)
        if ticket.total < ticket.paid_total:
            raise BusinessError("İndirim, tahsil edilmiş tutarın altına düşüremez")
        audit.log("ticket.discount", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
                  entity_id=ticket.pk, reason=reason, before={"total": str(before)},
                  after={"total": str(ticket.total), "kind": kind, "value": str(value), "amount": str(d.amount),
                         "approved_by": approved_by.username})
    broadcast_table(ticket)
    return d


def reverse_discount(discount, *, user, reason, approver=None):
    reason = _require_reason(reason)
    approved_by = authorize(user, roles.TICKET_DISCOUNT, approver)
    with transaction.atomic():
        return _reverse_discount_locked(discount, user=user, approved_by=approved_by, reason=reason)


def _reverse_discount_locked(discount, *, user, approved_by, reason):
    ticket = _lock_ticket(discount.ticket_id)
    discount = TicketDiscount.objects.select_for_update().get(pk=discount.pk)
    _ensure_editable(ticket)
    if discount.reversed_at:
        raise BusinessError("İndirim zaten geri alınmış")
    before = ticket.total
    discount.reversed_at = timezone.now()
    discount.reversed_by = approved_by
    discount.reverse_reason = reason
    discount.save(update_fields=["reversed_at", "reversed_by", "reverse_reason"])
    recalc(ticket)
    audit.log("ticket.discount_reverse", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
              entity_id=ticket.pk, reason=reason, before={"total": str(before)}, after={"total": str(ticket.total)})
    broadcast_table(ticket)
    return discount


def request_customer_group(ticket, *, user, group, reason=""):
    """Belediye personeli akışı: garson grubu işaretler → kasiyer onay/red → onayda indirim hesaplanır (§6.2)."""
    if group.business_id != ticket.business_id or not group.is_active:
        raise BusinessError("Geçersiz müşteri grubu")
    _ensure_editable(ticket)
    perm = roles.APPROVALS_MUNICIPAL if group.approver == "cashier" else roles.APPROVALS_DECIDE
    if roles.has_perm(user, perm):
        return apply_customer_group(ticket, user=user, group=group, approved_by=user, reason=reason or group.name)
    req = ApprovalRequest.objects.create(
        business=ticket.business, branch=ticket.branch, ticket=ticket, kind="group",
        payload={"group_id": group.id, "group_name": group.name}, reason=reason or group.name,
        required_perm=perm, requested_by=user)
    target_roles = [roles.CASHIER, roles.BRANCH_MANAGER, roles.OWNER] if group.approver == "cashier" else [roles.BRANCH_MANAGER, roles.OWNER]
    notify(branch=ticket.branch, event="approval_request", title=f"Onay: {group.name} indirimi",
           body=f"Adisyon #{ticket.number}", priority="medium", roles=target_roles, sound=True,
           data={"approval": req.id, "ticket": ticket.id})
    audit.log("approval.request", user=user, business=ticket.business, branch=ticket.branch, entity="ApprovalRequest",
              entity_id=req.pk, after=req.payload)
    broadcast_table(ticket)
    return req


def apply_customer_group(ticket, *, user, group, approved_by, reason=""):
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        _ensure_editable(ticket)
        if ticket.discounts.filter(kind="group", reversed_at__isnull=True).exists():
            raise BusinessError("Adisyonda zaten müşteri grubu indirimi var")
        before = ticket.total
        ticket.customer_group = group
        ticket.save(update_fields=["customer_group"])
        d = TicketDiscount.objects.create(ticket=ticket, kind="group", value=group.discount_value, customer_group=group,
                                          reason=(reason or group.name)[:300], created_by=user, approved_by=approved_by)
        recalc(ticket)
        audit.log("ticket.group_discount", user=approved_by, business=ticket.business, branch=ticket.branch,
                  entity="Ticket", entity_id=ticket.pk, reason=reason, before={"total": str(before)},
                  after={"total": str(ticket.total), "group": group.name, "amount": str(d.amount)})
    broadcast_table(ticket)
    return d


def request_approval(*, ticket, user, kind, payload, reason, perm):
    reason = _require_reason(reason)
    req = ApprovalRequest.objects.create(business=ticket.business, branch=ticket.branch, ticket=ticket, kind=kind,
                                         payload=payload, reason=reason, required_perm=perm, requested_by=user)
    label = dict(ApprovalRequest.KINDS)[kind]
    notify(branch=ticket.branch, event="approval_request", title=f"Onay bekleyen {label.lower()}",
           body=f"Adisyon #{ticket.number}: {reason}", priority="medium",
           roles=[roles.BRANCH_MANAGER, roles.OWNER], sound=True, data={"approval": req.id, "ticket": ticket.id})
    audit.log("approval.request", user=user, business=ticket.business, branch=ticket.branch, entity="ApprovalRequest",
              entity_id=req.pk, after=payload, reason=reason)
    broadcast_table(ticket)
    return req


def decide_approval(req, *, user, approve, note=""):
    if req.status != "pending":
        raise BusinessError("Talep zaten sonuçlandırılmış")
    if not roles.has_perm(user, req.required_perm):
        raise BusinessError("Bu talebi onaylama yetkiniz yok", code="forbidden", status_code=403)
    if req.requested_by_id == user.id:
        raise BusinessError("Kendi talebinizi onaylayamazsınız", code="forbidden", status_code=403)
    with transaction.atomic():
        # İki yönetici aynı anda onaylarsa indirim/iade iki kez uygulanmamalı
        if ApprovalRequest.objects.select_for_update().get(pk=req.pk).status != "pending":
            raise BusinessError("Talep zaten sonuçlandırılmış")
        result = None
        if approve:
            p = req.payload
            requester = req.requested_by
            if req.kind == "discount":
                result = apply_discount(req.ticket, user=requester, kind=p["kind"], value=p["value"], reason=req.reason,
                                        approved_by=user)
            elif req.kind == "void":
                line = TicketLine.objects.get(pk=p["line_id"], ticket=req.ticket)
                result = void_line(line, user=requester, reason=req.reason, qty=p.get("qty"), approved_by=user)
            elif req.kind == "group":
                group = CustomerGroup.objects.get(pk=p["group_id"], business=req.business)
                result = apply_customer_group(req.ticket, user=requester, group=group, approved_by=user, reason=req.reason)
            elif req.kind == "refund":
                payment = Payment.objects.get(pk=p["payment_id"], business=req.business)
                result = refund_payment(payment, user=requester, amount=p["amount"], reason=req.reason,
                                        line_ids=p.get("line_ids"), restock=p.get("restock", False), approved_by=user)
        req.status = "approved" if approve else "rejected"
        req.decided_by = user
        req.decided_at = timezone.now()
        req.decision_note = (note or "")[:300]
        req.save(update_fields=["status", "decided_by", "decided_at", "decision_note"])
        audit.log(f"approval.{req.status}", user=user, business=req.business, branch=req.branch,
                  entity="ApprovalRequest", entity_id=req.pk, reason=note)
    notify(branch=req.branch, event="approval_result",
           title=f"Talep {'onaylandı' if approve else 'reddedildi'}", body=req.reason, priority="medium",
           users=[req.requested_by], data={"approval": req.id, "ticket": req.ticket_id})
    if req.ticket_id:
        broadcast_table(req.ticket)
    return req, result


# ---------------------------------------------------------------- masa işlemleri
@transaction.atomic
def request_bill(ticket, *, user):
    ticket = _lock_ticket(ticket.pk)
    _ensure_editable(ticket)
    if ticket.status == "bill_requested":
        return ticket
    if ticket.lines.filter(status="draft").exists():
        raise BusinessError("Önce taslak ürünleri mutfağa gönderin veya silin", code="drafts_pending")
    if not ticket.lines.filter(status="sent").exists():
        raise BusinessError("Adisyonda hesaplanacak ürün yok", code="nothing_due")
    ticket.status = "bill_requested"
    ticket.bill_requested_at = timezone.now()
    ticket.save(update_fields=["status", "bill_requested_at"])
    label = f"Masa {ticket.table.name}" if ticket.table else f"#{ticket.number}"
    notify(branch=ticket.branch, event="bill_requested", title=f"{label} hesap istiyor", priority="medium",
           roles=[roles.CASHIER], data={"ticket": ticket.id}, sound=True)
    audit.log("ticket.bill_requested", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
              entity_id=ticket.pk)
    from apps.printing.services import enqueue_bill

    enqueue_bill(ticket)
    broadcast_table(ticket)
    return ticket


@transaction.atomic
def move_ticket(ticket, *, user, target):
    ticket = _lock_ticket(ticket.pk)
    if not ticket.is_active or ticket.table is None:
        raise BusinessError("Taşınabilir aktif masa adisyonu yok")
    target = primary_table(target)
    if target.branch_id != ticket.branch_id or not target.is_active:
        raise BusinessError("Hedef masa farklı şubede veya pasif")
    old = ticket.table
    if target.pk == old.pk:
        return ticket
    discard_blank_ticket(target, user=user)
    try:
        with transaction.atomic():
            ticket.table = target
            ticket.save(update_fields=["table"])
    except IntegrityError:
        raise BusinessError("Hedef masada aktif adisyon var", code="table_busy")
    audit.log("ticket.move", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
              entity_id=ticket.pk, before={"table": old.name}, after={"table": target.name})
    broadcast_table(old)
    broadcast_table(ticket)
    return ticket


def merge_tables(primary, secondary, *, user):
    """Masa birleştirme: ikincil masa birincile bağlanır. Adisyon birleştirme kararlaştırılmadığından (§5.2)
    ikincil masada aktif adisyon varsa işlem reddedilir."""
    if primary.id == secondary.id or primary.branch_id != secondary.branch_id:
        raise BusinessError("Geçersiz masa seçimi")
    primary = primary_table(primary)
    if primary.id == secondary.id:
        raise BusinessError("Bu masalar zaten birleşik")
    discard_blank_ticket(secondary, user=user)
    if Ticket.objects.filter(table=secondary, status__in=ACTIVE_TICKET_STATES).exists():
        raise BusinessError("Birleştirilecek masada açık adisyon var. Adisyon birleştirme kapsam dışıdır; "
                            "önce adisyonu taşıyın veya kapatın.", code="ticket_merge_not_supported")
    secondary.merged_into = primary
    secondary.save(update_fields=["merged_into"])
    audit.log("table.merge", user=user, business=primary.business, branch=primary.branch, entity="Table",
              entity_id=secondary.pk, after={"merged_into": primary.name})
    broadcast_table(secondary)
    broadcast_table(primary)
    return secondary


def unmerge_table(table, *, user):
    primary = table.merged_into
    table.merged_into = None
    table.save(update_fields=["merged_into"])
    audit.log("table.unmerge", user=user, business=table.business, branch=table.branch, entity="Table", entity_id=table.pk)
    broadcast_table(table)
    if primary:
        broadcast_table(primary)
    return table


def close_ticket(ticket, *, user, auto=False):
    """Ödeme ile masanın boşaltılması ayrı durumdur (§5.5)."""
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status in ("closed", "cancelled"):
            return ticket
        recalc(ticket)
        if ticket.lines.filter(status="draft").exists():
            raise BusinessError("Taslak ürünler var; gönderin veya silin", code="drafts_pending")
        if ticket.total > 0 and ticket.paid_total < ticket.total:
            raise BusinessError(f"Kalan tutar ödenmeden kapatılamaz: {ticket.remaining} TL", code="unpaid")
        ticket.status = "closed" if ticket.total > 0 or ticket.payments.exists() else "cancelled"
        ticket.closed_at = timezone.now()
        ticket.closed_by = user
        ticket.save(update_fields=["status", "closed_at", "closed_by"])
        _settle_leftovers(ticket, user=user, table_cleared=not auto)
        audit.log("ticket.close", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket",
                  entity_id=ticket.pk, after={"status": ticket.status, "auto": auto, "total": str(ticket.total)})
        emit_sync(ticket.branch, "ticket.closed", {"ticket": ticket.id, "number": ticket.number,
                                                   "total": str(ticket.total), "date": str(ticket.business_date)}, user)
        if ticket.customer_id:
            from apps.modules.services import touch_customer_visit

            touch_customer_visit(ticket)
    broadcast_table(ticket)
    return ticket


def _settle_leftovers(ticket, *, user, table_cleared):
    """Kapanan adisyona bağlı bekleyen işler askıda kalmasın."""
    now = timezone.now()
    ticket.approvals.filter(status="pending").exclude(kind="refund").update(
        status="rejected", decided_at=now, decision_note="Adisyon kapandığı için otomatik kapatıldı")
    if ticket.reservation_id:
        from apps.modules.models import Reservation

        Reservation.objects.filter(pk=ticket.reservation_id, status="seated").update(status="completed")
    # Ödemeyle otomatik kapanışta (ör. peşin gel-al) sipariş hâlâ teslim bekliyor olabilir
    if table_cleared and ticket.batches.filter(status="ready").update(
            status="picked_up", picked_up_at=now, picked_up_by=user):
        broadcast(branch_group(ticket.branch_id), "ready", {"ticket": ticket.id, "action": "picked_up"})


@transaction.atomic
def cancel_empty_ticket(ticket, *, user):
    ticket = _lock_ticket(ticket.pk)
    if ticket.status == "cancelled":
        return ticket
    if ticket.status == "closed":
        raise BusinessError("Kapanmış adisyon iptal edilemez")
    if ticket.lines.exclude(status="draft").exists() or ticket.payments.exists():
        raise BusinessError("Gönderilmiş ürün veya ödeme içeren adisyon iptal edilemez; ürünleri gerekçeli iptal edin")
    ticket.lines.all().delete()
    ticket.status = "cancelled"
    ticket.closed_at = timezone.now()
    ticket.closed_by = user
    ticket.save(update_fields=["status", "closed_at", "closed_by"])
    _settle_leftovers(ticket, user=user, table_cleared=True)
    audit.log("ticket.cancel", user=user, business=ticket.business, branch=ticket.branch, entity="Ticket", entity_id=ticket.pk)
    broadcast_table(ticket)
    return ticket


# ---------------------------------------------------------------- ödeme
def open_cash_day_for(branch):
    return CashDay.objects.filter(branch=branch, status="open").first()


def equal_split(ticket, parts):
    parts = int(parts)
    if parts < 2 or parts > 50:
        raise BusinessError("Bölme sayısı 2-50 arasında olmalı")
    remaining = ticket.remaining
    share = money(remaining / parts)
    shares = [share] * (parts - 1) + [remaining - share * (parts - 1)]
    return shares


def take_payment(ticket, *, user, method, amount=None, tendered=None, split_mode="partial", line_ids=None,
                 customer=None, reference="", idempotency_key="", device=""):
    from apps.inventory.services import deduct_for_lines

    if method not in dict(Payment._meta.get_field("method").choices):
        raise BusinessError("Geçersiz ödeme yöntemi")
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status not in ("open", "bill_requested"):
            raise BusinessError("Adisyon ödemeye açık değil (ödenmiş veya kapalı)", code="ticket_not_payable")
        if ticket.lines.filter(status="draft").exists():
            raise BusinessError("Taslak ürünler var; önce mutfağa gönderin veya silin", code="drafts_pending")
        recalc(ticket)
        cash_day = open_cash_day_for(ticket.branch)
        if not cash_day:
            raise BusinessError("Kasa açık değil. Önce gün başı kasa açılışı yapın.", code="cash_closed")
        remaining = ticket.remaining
        if remaining <= 0:
            raise BusinessError("Ödenecek tutar yok", code="nothing_due")
        allocations = []
        if line_ids:
            lines = list(ticket.lines.filter(pk__in=line_ids, status="sent"))
            if len(lines) != len(set(int(x) for x in line_ids)):
                raise BusinessError("Seçilen ürünler geçersiz")
            for ln in lines:
                due = line_due(ln)
                if due > 0:
                    allocations.append((ln, due))
            amount = sum((d for _, d in allocations), ZERO)
            split_mode = "items"
            if amount <= 0:
                raise BusinessError("Seçilen ürünler zaten ödenmiş")
        if amount is None:
            amount = remaining
        amount = money(Decimal(str(amount)))
        if amount <= 0:
            raise BusinessError("Tutar pozitif olmalı")
        if amount > remaining:
            raise BusinessError(f"Tutar kalan bakiyeden ({remaining} TL) büyük olamaz", code="overpay")
        change = ZERO
        if method == "cash":
            tendered = money(Decimal(str(tendered))) if tendered not in (None, "") else amount
            if tendered < amount:
                raise BusinessError("Alınan nakit tutardan az")
            change = tendered - amount
        else:
            tendered = None
        if method == "open_account":
            customer = customer or ticket.customer
            if customer is None:
                raise BusinessError("Açık hesap için müşteri seçilmeli", code="customer_required")
        if amount == remaining and split_mode == "partial":
            split_mode = "full"
        p = Payment.objects.create(
            business=ticket.business, branch=ticket.branch, ticket=ticket, cash_day=cash_day, method=method,
            amount=amount, tendered=tendered, change=change, split_mode=split_mode, customer=customer,
            reference=(reference or "")[:80], idempotency_key=idempotency_key[:100], device=device[:120], user=user)
        for ln, due in allocations:
            PaymentAllocation.objects.create(payment=p, line=ln, amount=due)
        if method == "cash":
            CashMovement.objects.create(cash_day=cash_day, kind="sale", amount=amount, payment=p, user=user,
                                        reason=f"Adisyon #{ticket.number}")
        if method == "open_account":
            from apps.modules.services import post_account_entry

            post_account_entry(customer, amount=amount, kind="debit", ref=f"Adisyon #{ticket.number}", user=user,
                               payment=p)
        recalc(ticket)
        fully = ticket.paid_total >= ticket.total
        if fully:
            ticket.status = "paid"
            ticket.paid_at = timezone.now()
            ticket.save(update_fields=["status", "paid_at"])
            if ticket.branch.settings.stock_deduction == "payment":
                deduct_for_lines(list(ticket.lines.filter(status="sent")), user=user)
        audit.log("payment.create", user=user, business=ticket.business, branch=ticket.branch, entity="Payment",
                  entity_id=p.pk, after={"ticket": ticket.number, "method": method, "amount": str(amount),
                                         "split": split_mode, "remaining": str(ticket.remaining),
                                         "txn": str(p.txn_id)})
        emit_sync(ticket.branch, "payment", {"txn": str(p.txn_id), "ticket": ticket.id, "method": method,
                                             "amount": str(amount)}, user)
        if fully and ticket.branch.settings.auto_close_on_payment:
            close_ticket(ticket, user=user, auto=True)
        if fully:
            from apps.printing.services import enqueue_receipt

            enqueue_receipt(ticket)
    broadcast_table(ticket)
    return p


def refund_payment(payment, *, user, amount, reason, line_ids=None, restock=False, approver=None, approved_by=None):
    from apps.inventory.services import reverse_for_line

    reason = _require_reason(reason)
    approved_by = approved_by or authorize(user, roles.PAYMENT_REFUND, approver)
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        ticket = Ticket.objects.select_for_update().get(pk=payment.ticket_id)
        amount = money(Decimal(str(amount)))
        refundable = payment.amount - payment.refunded_amount
        if amount <= 0 or amount > refundable:
            raise BusinessError(f"İade tutarı 0 ile {refundable} TL arasında olmalı", code="refund_amount")
        cash_day = open_cash_day_for(payment.branch)
        if not cash_day:
            raise BusinessError("İade için kasa açık olmalı", code="cash_closed")
        r = Refund.objects.create(business=payment.business, branch=payment.branch, payment=payment, cash_day=cash_day,
                                  amount=amount, method=payment.method, reason=reason, line_ids=line_ids or [],
                                  restock=restock, user=user, approved_by=approved_by,
                                  ticket_total_before=ticket.total, ticket_paid_before=ticket.paid_total)
        payment.refunded_amount += amount
        payment.status = "refunded" if payment.refunded_amount >= payment.amount else "partially_refunded"
        payment.save(update_fields=["refunded_amount", "status"])
        if payment.method == "cash":
            CashMovement.objects.create(cash_day=cash_day, kind="refund", amount=-amount, refund=r, user=user,
                                        reason=reason)
        if payment.method == "open_account" and payment.customer_id:
            from apps.modules.services import post_account_entry

            post_account_entry(payment.customer, amount=amount, kind="credit", ref=f"İade #{r.id}", user=user)
        if restock and line_ids:
            for ln in ticket.lines.filter(pk__in=line_ids):
                reverse_for_line(ln, qty=ln.qty, user=user, kind="refund")
        paid_before = ticket.paid_total
        recalc(ticket)
        if ticket.status == "paid" and ticket.paid_total < ticket.total:
            ticket.status = "open"
            ticket.save(update_fields=["status"])
        audit.log("payment.refund", user=user, business=ticket.business, branch=ticket.branch, entity="Refund",
                  entity_id=r.pk, reason=reason, before={"paid": str(paid_before)},
                  after={"paid": str(ticket.paid_total), "amount": str(amount), "method": payment.method,
                         "approved_by": approved_by.username})
        emit_sync(ticket.branch, "refund", {"refund": r.id, "payment": str(payment.txn_id), "amount": str(amount)}, user)
    broadcast_table(ticket)
    return r


# ---------------------------------------------------------------- kasa
def open_cash_day(branch, *, user, opening_balance):
    opening = money(Decimal(str(opening_balance)))
    if opening < 0:
        raise BusinessError("Açılış bakiyesi negatif olamaz")
    today = timezone.localdate()
    if CashDay.objects.filter(branch=branch, status__in=("open", "pending_approval")).exists():
        raise BusinessError("Açık veya onay bekleyen bir kasa günü var", code="cash_day_exists")
    if CashDay.objects.filter(branch=branch, business_date=today).exists():
        raise BusinessError("Bugünün kasası zaten açılıp kapatıldı", code="cash_day_exists")
    try:
        with transaction.atomic():
            d = CashDay.objects.create(business=branch.business, branch=branch, business_date=today,
                                       opening_balance=opening, opened_by=user)
    except IntegrityError:
        raise BusinessError("Kasa günü zaten açık", code="cash_day_exists")
    audit.log("cash.open", user=user, business=branch.business, branch=branch, entity="CashDay", entity_id=d.pk,
              after={"opening": str(opening)})
    return d


def add_cash_movement(day, *, user, kind, amount, reason):
    reason = _require_reason(reason)
    if day.status != "open":
        raise BusinessError("Kasa günü açık değil")
    if kind not in ("expense", "withdrawal", "deposit"):
        raise BusinessError("Geçersiz kasa hareketi")
    amount = money(Decimal(str(amount)))
    if amount <= 0:
        raise BusinessError("Tutar pozitif olmalı")
    signed = amount if kind == "deposit" else -amount
    m = CashMovement.objects.create(cash_day=day, kind=kind, amount=signed, reason=reason, user=user)
    audit.log("cash.movement", user=user, business=day.business, branch=day.branch, entity="CashMovement",
              entity_id=m.pk, after={"kind": kind, "amount": str(signed)}, reason=reason)
    return m


def expected_cash(day):
    return money(day.opening_balance + (day.movements.aggregate(s=Sum("amount"))["s"] or ZERO))


def build_day_report(day):
    pays = Payment.objects.filter(cash_day=day)
    by_method = {}
    for m, label in Payment._meta.get_field("method").choices:
        agg = pays.filter(method=m).aggregate(s=Sum("amount"), n=Sum(1) if False else Sum("amount"))
        cnt = pays.filter(method=m).count()
        refunds = Refund.objects.filter(cash_day=day, method=m).aggregate(s=Sum("amount"))["s"] or ZERO
        by_method[m] = {"label": label, "count": cnt, "amount": str(money(agg["s"] or ZERO)),
                        "refunds": str(money(refunds)), "net": str(money((agg["s"] or ZERO) - refunds))}
    tickets = Ticket.objects.filter(branch=day.branch, business_date=day.business_date)
    voids = TicketLine.objects.filter(ticket__branch=day.branch, status="void", voided_at__date=day.business_date)
    mv = day.movements
    def msum(kind):
        return str(money(mv.filter(kind=kind).aggregate(s=Sum("amount"))["s"] or ZERO))
    by_user = {}
    for m in mv.select_related("user"):
        key = m.user.get_full_name() or m.user.username
        by_user.setdefault(key, {"count": 0, "amount": ZERO})
        by_user[key]["count"] += 1
        by_user[key]["amount"] += m.amount
    gross_sales = pays.aggregate(s=Sum("amount"))["s"] or ZERO
    refunds_total = Refund.objects.filter(cash_day=day).aggregate(s=Sum("amount"))["s"] or ZERO
    return {
        "branch": day.branch.name,
        "business_date": str(day.business_date),
        "generated_at": timezone.now().isoformat(),
        "payments": by_method,
        "gross_collections": str(money(gross_sales)),
        "refunds": str(money(refunds_total)),
        "net_collections": str(money(gross_sales - refunds_total)),
        "tickets_closed": tickets.filter(status="closed").count(),
        "tickets_open": live_tickets(tickets).count(),
        "tickets_cancelled": tickets.filter(status="cancelled").count(),
        "discount_total": str(money(tickets.aggregate(s=Sum("discount_total"))["s"] or ZERO)),
        "campaign_discount_total": str(money(tickets.aggregate(s=Sum("campaign_discount"))["s"] or ZERO)),
        "void_count": voids.count(),
        "void_amount": str(money(sum((v.unit_price * v.qty for v in voids), ZERO))),
        "cash": {
            "opening": str(day.opening_balance),
            "sales": msum("sale"), "refunds": msum("refund"), "expenses": msum("expense"),
            "withdrawals": msum("withdrawal"), "deposits": msum("deposit"),
            "expected": str(expected_cash(day)),
            "counted": str(day.counted_cash) if day.counted_cash is not None else None,
            "difference": str(day.difference) if day.difference is not None else None,
            "difference_reason": day.difference_reason,
        },
        "movements_by_user": {k: {"count": v["count"], "amount": str(money(v["amount"]))} for k, v in by_user.items()},
    }


def count_cash_day(day, *, user, counted, reason=""):
    if day.status != "open":
        raise BusinessError("Kasa günü açık değil")
    counted = money(Decimal(str(counted)))
    if counted < 0:
        raise BusinessError("Sayılan nakit negatif olamaz")
    exp = expected_cash(day)
    diff = counted - exp
    if diff != 0 and (not reason or len(reason.strip()) < 3):
        raise BusinessError(f"Kasa farkı {diff} TL; fark nedeni zorunludur", code="difference_reason_required",
                            extra={"expected": str(exp), "difference": str(diff)})
    day.expected_cash = exp
    day.counted_cash = counted
    day.difference = diff
    day.difference_reason = (reason or "").strip()[:300]
    day.counted_by = user
    day.counted_at = timezone.now()
    day.status = "pending_approval"
    day.report = build_day_report(day)
    day.save()
    audit.log("cash.count", user=user, business=day.business, branch=day.branch, entity="CashDay", entity_id=day.pk,
              after={"expected": str(exp), "counted": str(counted), "difference": str(diff)}, reason=reason)
    notify(branch=day.branch, event="day_end_pending", title="Gün sonu onay bekliyor",
           body=f"Fark: {diff} TL", priority="medium", roles=[roles.BRANCH_MANAGER, roles.OWNER])
    return day


def approve_cash_day(day, *, user):
    if day.status != "pending_approval":
        raise BusinessError("Kasa günü onay beklemiyor")
    if not roles.has_perm(user, roles.CASH_APPROVE):
        raise BusinessError("Gün sonu onayı için yetkiniz yok", status_code=403)
    day.status = "closed"
    day.approved_by = user
    day.closed_at = timezone.now()
    day.report = build_day_report(day)
    day.report["approved_by"] = user.get_full_name() or user.username
    day.save()
    audit.log("cash.close", user=user, business=day.business, branch=day.branch, entity="CashDay", entity_id=day.pk,
              after={"difference": str(day.difference)})
    emit_sync(day.branch, "day_end", day.report, user)
    return day


def reject_cash_count(day, *, user, reason):
    reason = _require_reason(reason)
    if day.status != "pending_approval":
        raise BusinessError("Kasa günü onay beklemiyor")
    day.status = "open"
    day.save(update_fields=["status"])
    audit.log("cash.count_rejected", user=user, business=day.business, branch=day.branch, entity="CashDay",
              entity_id=day.pk, reason=reason)
    return day


__all__ = ["Q"]
