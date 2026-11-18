from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.notify import notify

from .models import (Attendance, Customer, CustomerAccountEntry, Delivery, FinanceEntry, Reservation, Shift)

ZERO = Decimal("0.00")


# ------------------------------------------------------------------ CRM / cari
def post_account_entry(customer, *, amount, kind, ref, user, payment=None, method=""):
    return CustomerAccountEntry.objects.create(business=customer.business, customer=customer, kind=kind,
                                               amount=Decimal(str(amount)), ref=ref[:120], payment=payment,
                                               method=method, user=user)


def customer_balance(customer):
    agg = customer.account_entries.aggregate(d=Sum("amount", filter=Q(kind="debit")),
                                             c=Sum("amount", filter=Q(kind="credit")))
    return (agg["d"] or ZERO) - (agg["c"] or ZERO)


def collect_account(customer, *, amount, method, user, note=""):
    amount = Decimal(str(amount))
    if amount <= 0:
        raise BusinessError("Tutar pozitif olmalı")
    if amount > customer_balance(customer):
        raise BusinessError("Tahsilat borçtan büyük olamaz")
    e = post_account_entry(customer, amount=amount, kind="credit", ref=note or "Açık hesap tahsilatı", user=user,
                           method=method)
    audit.log("crm.account_collect", user=user, business=customer.business, entity="Customer", entity_id=customer.pk,
              after={"amount": str(amount), "method": method})
    if method == "cash":
        from apps.pos.models import CashDay, CashMovement

        branch = user.branch or customer.business.branches.first()
        day = CashDay.objects.filter(branch=branch, status="open").first()
        if day:
            CashMovement.objects.create(cash_day=day, kind="deposit", amount=amount, user=user,
                                        reason=f"Açık hesap tahsilatı: {customer.name}")
    return e


def touch_customer_visit(ticket):
    c = ticket.customer
    Customer.objects.filter(pk=c.pk).update(visit_count=c.visit_count + 1, total_spent=c.total_spent + ticket.total,
                                            last_visit=timezone.now())


def export_customer_data(customer):
    """KVKK erişim hakkı: müşteriye ait kişisel veri ve işlem özeti."""
    from apps.pos.models import Ticket

    tickets = Ticket.objects.filter(customer=customer).order_by("-opened_at")
    return {
        "customer": {"name": customer.name, "phone": customer.phone, "email": customer.email,
                     "address": customer.address, "note": customer.note, "kvkk_consent": customer.kvkk_consent,
                     "consent_at": customer.consent_at, "created_at": customer.created_at},
        "visits": customer.visit_count, "total_spent": str(customer.total_spent),
        "balance": str(customer_balance(customer)),
        "orders": [{"number": t.number, "date": t.opened_at, "total": str(t.total), "status": t.status} for t in tickets[:500]],
    }


def anonymize_customer(customer, *, user, reason, request=None):
    """KVKK silme: finansal kayıtlar korunur, kişisel veri anonimleştirilir."""
    if not reason or len(reason.strip()) < 3:
        raise BusinessError("Gerekçe zorunludur")
    if customer_balance(customer) != 0:
        raise BusinessError("Açık hesap bakiyesi olan müşteri anonimleştirilemez")
    before = {"name": customer.name, "phone": customer.phone[-4:]}
    customer.name = f"Anonim #{customer.pk}"
    customer.phone = ""
    customer.email = ""
    customer.address = ""
    customer.note = ""
    customer.anonymized_at = timezone.now()
    customer.is_active = False
    customer.save()
    audit.log("crm.anonymize", request=request, user=user, business=customer.business, entity="Customer",
              entity_id=customer.pk, before=before, reason=reason)
    return customer


# ------------------------------------------------------------------ Kurye
DELIVERY_FLOW = {
    "preparing": {"waiting_courier", "cancelled"},
    "waiting_courier": {"on_the_way", "cancelled"},
    "on_the_way": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def create_delivery(*, branch, user, contact_name, phone, address, customer=None, fee=0, payment_note="",
                    promised_minutes=45):
    from apps.pos.services import open_ticket

    with transaction.atomic():
        ticket, _ = open_ticket(branch=branch, user=user, channel="delivery", customer=customer)
        d = Delivery.objects.create(business=branch.business, branch=branch, ticket=ticket, customer=customer,
                                    contact_name=contact_name, phone=phone, address=address, fee=Decimal(str(fee or 0)),
                                    payment_note=payment_note, promised_minutes=promised_minutes)
        if d.fee > 0:
            from apps.catalog.models import Category, Product

            cat, _ = Category.objects.get_or_create(business=branch.business, name="Hizmet", defaults={"sort": 999})
            fee_product, _ = Product.objects.get_or_create(business=branch.business, name="Teslimat ücreti",
                                                           defaults={"category": cat, "base_price": 0})
            from apps.pos.models import TicketLine
            from apps.pos.services import recalc

            TicketLine.objects.create(ticket=ticket, product=fee_product, name="Teslimat ücreti", qty=1,
                                      base_price=d.fee, unit_price=d.fee, status="sent", created_by=user,
                                      tax_rate=fee_product.effective_tax(), sent_at=timezone.now())
            recalc(ticket)
        audit.log("delivery.create", user=user, business=branch.business, branch=branch, entity="Delivery",
                  entity_id=d.pk)
    return d


def set_delivery_status(d, *, user, status, courier=None):
    if courier is not None:
        if courier.branch_id != d.branch_id:
            raise BusinessError("Kurye farklı şubede")
        d.courier = courier
        d.assigned_at = timezone.now()
    if status and status != d.status:
        if status not in DELIVERY_FLOW.get(d.status, set()):
            raise BusinessError(f"Geçersiz durum geçişi: {d.get_status_display()} → {dict(Delivery.STATUS).get(status, status)}")
        if status == "on_the_way" and not d.courier_id:
            raise BusinessError("Dağıtıma çıkmadan önce kurye atanmalı")
        d.status = status
        if status == "on_the_way":
            d.dispatched_at = timezone.now()
        if status == "delivered":
            d.delivered_at = timezone.now()
    d.save()
    audit.log("delivery.status", user=user, business=d.business, branch=d.branch, entity="Delivery", entity_id=d.pk,
              after={"status": d.status, "courier": d.courier.name if d.courier else None})
    return d


def check_late_deliveries(now=None):
    now = now or timezone.now()
    n = 0
    for d in Delivery.objects.filter(status__in=("preparing", "waiting_courier", "on_the_way"), late_notified=False):
        if d.created_at + timedelta(minutes=d.promised_minutes) < now:
            notify(branch=d.branch, event="delivery_late", title=f"Geciken teslimat #{d.ticket.number}",
                   body=f"{d.contact_name} — {d.address[:60]}", priority="high",
                   roles=[roles.BRANCH_MANAGER, roles.CASHIER, roles.OWNER])
            d.late_notified = True
            d.save(update_fields=["late_notified"])
            n += 1
    return n


def courier_performance(branch, date_from, date_to):
    rows = {}
    for d in Delivery.objects.filter(branch=branch, status="delivered", delivered_at__date__gte=date_from,
                                     delivered_at__date__lte=date_to).select_related("courier"):
        key = d.courier.name if d.courier else "-"
        r = rows.setdefault(key, {"courier": key, "count": 0, "minutes": 0, "late": 0, "fees": ZERO})
        mins = (d.delivered_at - d.created_at).total_seconds() / 60
        r["count"] += 1
        r["minutes"] += mins
        r["late"] += mins > d.promised_minutes
        r["fees"] += d.fee
    for r in rows.values():
        r["avg_minutes"] = round(r["minutes"] / r["count"], 1) if r["count"] else 0
        r["fees"] = str(r["fees"])
        del r["minutes"]
    return list(rows.values())


# ------------------------------------------------------------------ Rezervasyon
def _overlaps(table, starts, duration, exclude_id=None):
    end = starts + timedelta(minutes=duration)
    qs = Reservation.objects.filter(table=table, status__in=("pending", "confirmed", "seated"))
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    for r in qs.filter(starts_at__lt=end, starts_at__gte=starts - timedelta(hours=12)):
        if r.starts_at + timedelta(minutes=r.duration_minutes) > starts:
            return r
    return None


def validate_reservation(res):
    if res.party_size < 1:
        raise BusinessError("Kişi sayısı en az 1 olmalı")
    if res.table_id and res.status != "waitlist":
        if res.table.seats < res.party_size:
            raise BusinessError(f"Masa kapasitesi yetersiz ({res.table.seats} kişilik)", code="capacity")
        clash = _overlaps(res.table, res.starts_at, res.duration_minutes, exclude_id=res.pk)
        if clash:
            raise BusinessError(f"Masa bu saatte dolu ({clash.name}). Bekleme listesine ekleyebilirsiniz.",
                                code="table_reserved")


def seat_reservation(res, *, user):
    from apps.pos.services import open_ticket

    if res.status not in ("pending", "confirmed", "waitlist"):
        raise BusinessError("Rezervasyon masaya alınamaz")
    if not res.table_id:
        raise BusinessError("Önce masa atayın")
    ticket, created = open_ticket(branch=res.branch, user=user, table=res.table, guest_count=res.party_size,
                                  customer=res.customer)
    if not created:
        raise BusinessError("Masada açık adisyon var", code="table_busy")
    ticket.reservation = res
    ticket.save(update_fields=["reservation"])
    res.status = "seated"
    res.save(update_fields=["status"])
    audit.log("reservation.seat", user=user, business=res.business, branch=res.branch, entity="Reservation",
              entity_id=res.pk, after={"ticket": ticket.id})
    return ticket


def send_reservation_reminders(now=None):
    now = now or timezone.now()
    n = 0
    for r in Reservation.objects.filter(status__in=("pending", "confirmed"), reminded_at__isnull=True,
                                        starts_at__gt=now, starts_at__lte=now + timedelta(hours=24)):
        if r.starts_at - timedelta(minutes=r.remind_minutes_before) <= now:
            notify(branch=r.branch, event="reservation_reminder",
                   title=f"Rezervasyon: {r.name} ({r.party_size} kişi)",
                   body=f"{timezone.localtime(r.starts_at):%H:%M} — {r.table.name if r.table else 'masa atanmadı'}",
                   priority="medium", roles=[roles.BRANCH_MANAGER, roles.CASHIER, roles.WAITER])
            r.reminded_at = now
            r.save(update_fields=["reminded_at"])
            n += 1
    return n


def table_reserved_now(table, now=None):
    now = now or timezone.now()
    return Reservation.objects.filter(table=table, status__in=("pending", "confirmed"),
                                      starts_at__lte=now + timedelta(minutes=60),
                                      starts_at__gte=now - timedelta(minutes=30)).exists()


# ------------------------------------------------------------------ Personel
def clock_in(user, *, branch):
    if Attendance.objects.filter(user=user, clock_out__isnull=True).exists():
        raise BusinessError("Zaten giriş yapılmış")
    now = timezone.now()
    shift = Shift.objects.filter(user=user, starts_at__date=timezone.localdate(), ends_at__gt=now).order_by("starts_at").first()
    late = max(0, int((now - shift.starts_at).total_seconds() // 60)) if shift else 0
    a = Attendance.objects.create(business=branch.business, branch=branch, user=user, shift=shift, clock_in=now,
                                  late_minutes=late)
    audit.log("staff.clock_in", user=user, business=branch.business, branch=branch, entity="Attendance", entity_id=a.pk,
              after={"late_minutes": late})
    return a


def toggle_break(user):
    a = Attendance.objects.filter(user=user, clock_out__isnull=True).first()
    if not a:
        raise BusinessError("Önce giriş yapın")
    now = timezone.now()
    if a.break_started_at:
        a.break_minutes += int((now - a.break_started_at).total_seconds() // 60)
        a.break_started_at = None
    else:
        a.break_started_at = now
    a.save(update_fields=["break_minutes", "break_started_at"])
    return a


def clock_out(user):
    a = Attendance.objects.filter(user=user, clock_out__isnull=True).first()
    if not a:
        raise BusinessError("Açık giriş kaydı yok")
    now = timezone.now()
    if a.break_started_at:
        a.break_minutes += int((now - a.break_started_at).total_seconds() // 60)
        a.break_started_at = None
    a.clock_out = now
    if a.shift:
        a.overtime_minutes = max(0, int((now - a.shift.ends_at).total_seconds() // 60))
    a.save()
    audit.log("staff.clock_out", user=user, business=a.business, branch=a.branch, entity="Attendance", entity_id=a.pk,
              after={"overtime_minutes": a.overtime_minutes, "break_minutes": a.break_minutes})
    return a


def absences(branch, day):
    """Vardiyası olup giriş yapmayan personel (devamsızlık)."""
    shifts = Shift.objects.filter(branch=branch, starts_at__date=day)
    return [s for s in shifts if not Attendance.objects.filter(user=s.user, clock_in__date=day).exists()
            and not s.user.leaves.filter(status="approved", start_date__lte=day, end_date__gte=day).exists()]


def staff_performance(branch, date_from, date_to):
    from apps.pos.models import Ticket, TicketLine

    out = []
    tickets = Ticket.objects.filter(branch=branch, business_date__gte=date_from, business_date__lte=date_to,
                                    status="closed")
    for row in tickets.values("waiter__id", "waiter__username", "waiter__first_name", "waiter__last_name").annotate(
            total=Sum("total")).order_by("-total"):
        wid = row["waiter__id"]
        cnt = tickets.filter(waiter_id=wid).count()
        voids = TicketLine.objects.filter(ticket__branch=branch, status="void", created_by_id=wid,
                                          voided_at__date__gte=date_from, voided_at__date__lte=date_to).count()
        att = Attendance.objects.filter(user_id=wid, clock_in__date__gte=date_from, clock_in__date__lte=date_to)
        worked = sum(((a.clock_out - a.clock_in).total_seconds() / 3600 - a.break_minutes / 60)
                     for a in att if a.clock_out)
        out.append({"user": f"{row['waiter__first_name']} {row['waiter__last_name']}".strip() or row["waiter__username"],
                    "tickets": cnt, "sales": str(row["total"] or 0),
                    "avg_ticket": str(round((row["total"] or 0) / cnt, 2)) if cnt else "0",
                    "voids": voids, "hours": round(worked, 1),
                    "late_minutes": sum(a.late_minutes for a in att),
                    "overtime_minutes": sum(a.overtime_minutes for a in att)})
    return out


# ------------------------------------------------------------------ Finans
def reverse_finance_entry(entry, *, user, reason):
    if not reason or len(reason.strip()) < 3:
        raise BusinessError("Gerekçe zorunludur")
    if hasattr(entry, "reversed_by") and FinanceEntry.objects.filter(reverses=entry).exists():
        raise BusinessError("Kayıt zaten ters kayıtla düzeltilmiş")
    rev = FinanceEntry.objects.create(business=entry.business, branch=entry.branch, kind=entry.kind,
                                      category=entry.category, amount=-entry.amount, date=timezone.localdate(),
                                      description=f"Ters kayıt: {reason}"[:300], account=entry.account, reverses=entry,
                                      user=user)
    audit.log("finance.reverse", user=user, business=entry.business, branch=entry.branch, entity="FinanceEntry",
              entity_id=entry.pk, reason=reason)
    return rev


def account_balance(account):
    agg = account.entries.aggregate(
        p=Sum("amount", filter=Q(kind="payable")), sp=Sum("amount", filter=Q(kind="settle_payable")),
        r=Sum("amount", filter=Q(kind="receivable")), sr=Sum("amount", filter=Q(kind="settle_receivable")))
    payable = (agg["p"] or ZERO) - (agg["sp"] or ZERO)
    receivable = (agg["r"] or ZERO) - (agg["sr"] or ZERO)
    q = Decimal("0.01")
    return {"payable": str(payable.quantize(q)), "receivable": str(receivable.quantize(q)),
            "net": str((receivable - payable).quantize(q))}


def profitability(branch, date_from, date_to):
    """Kârlılık: satış (KDV hariç) − reçete maliyeti − giderler."""
    from apps.inventory.services import product_cost
    from apps.pos.models import Payment, Refund, TicketLine

    lines = TicketLine.objects.filter(ticket__branch=branch, ticket__status="closed", status="sent",
                                      ticket__business_date__gte=date_from, ticket__business_date__lte=date_to)
    revenue_net = ZERO
    cogs = ZERO
    costs = {}
    for ln in lines.select_related("product"):
        revenue_net += ln.net_total - ln.tax_amount if ln.tax_included else ln.net_total - ln.tax_amount
        if ln.product_id not in costs:
            costs[ln.product_id] = product_cost(ln.product)
        cogs += costs[ln.product_id] * ln.qty
    exp = FinanceEntry.objects.filter(branch=branch, kind="expense", date__gte=date_from, date__lte=date_to) \
        .aggregate(s=Sum("amount"))["s"] or ZERO
    inc = FinanceEntry.objects.filter(branch=branch, kind="income", date__gte=date_from, date__lte=date_to) \
        .aggregate(s=Sum("amount"))["s"] or ZERO
    from apps.pos.models import CashMovement

    cash_exp = -(CashMovement.objects.filter(cash_day__branch=branch, kind="expense",
                                             cash_day__business_date__gte=date_from,
                                             cash_day__business_date__lte=date_to).aggregate(s=Sum("amount"))["s"] or ZERO)
    collected = Payment.objects.filter(branch=branch, created_at__date__gte=date_from, created_at__date__lte=date_to) \
        .aggregate(s=Sum("amount"))["s"] or ZERO
    refunded = Refund.objects.filter(branch=branch, created_at__date__gte=date_from, created_at__date__lte=date_to) \
        .aggregate(s=Sum("amount"))["s"] or ZERO
    gross_profit = revenue_net - cogs
    net = gross_profit + inc - exp - cash_exp
    return {"revenue_net": str(revenue_net.quantize(Decimal("0.01"))), "cogs": str(cogs.quantize(Decimal("0.01"))),
            "gross_profit": str(gross_profit.quantize(Decimal("0.01"))), "other_income": str(inc),
            "expenses": str(exp + cash_exp), "net_profit": str(net.quantize(Decimal("0.01"))),
            "collections": str(collected), "refunds": str(refunded)}
