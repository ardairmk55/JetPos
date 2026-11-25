from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import CustomerGroup
from apps.core import audit, roles
from apps.core.exceptions import ApprovalRequired, BusinessError
from apps.core.idempotency import idempotent
from apps.core.tenancy import HasPerm, TenantViewSet, current_branch, current_business, limit_list

from . import services
from .models import (ACTIVE_TICKET_STATES, ApprovalRequest, CashDay, Hall, KitchenBatch, KitchenOrder, Payment, Table,
                     Ticket, TicketDiscount, TicketLine)
from .serializers import (ApprovalSerializer, CashDaySerializer, CashMovementSerializer, HallSerializer,
                          KitchenOrderSerializer, PaymentSerializer, TableSerializer, TicketDetailSerializer,
                          TicketSerializer, table_state)


def _approver(request):
    a = request.data.get("approver")
    return a if isinstance(a, dict) and a else None


def _remove_tables(tables, user):
    """Üzerinde işlem süren masa silinemez; boş açılışlar ve birleştirme bağları temizlenir."""
    busy = services.live_tickets(Ticket.objects.filter(table__in=tables)).select_related("table").first()
    if busy:
        raise BusinessError(f"Masa {busy.table.name} üzerinde açık adisyon var; önce kapatın veya taşıyın",
                            code="table_busy")
    for t in tables:
        services.discard_blank_ticket(t, user=user)
    Table.objects.filter(merged_into__in=tables).update(merged_into=None)


class LiveFloorViewSet(TenantViewSet):
    """Salon/masa tanımı değişince diğer cihazların plan ekranı da yenilenir."""

    def perform_create(self, serializer):
        super().perform_create(serializer)
        services.broadcast_floor(current_branch(self.request))

    def perform_update(self, serializer):
        super().perform_update(serializer)
        services.broadcast_floor(current_branch(self.request))


class HallViewSet(LiveFloorViewSet):
    queryset = Hall.objects.all()
    serializer_class = HallSerializer
    perm_read = roles.FLOOR_VIEW
    perm_write = roles.FLOOR_MANAGE
    ordering = ("sort", "id")

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    @transaction.atomic
    def perform_destroy(self, instance):
        tables = list(Table.objects.filter(hall=instance, is_active=True))
        _remove_tables(tables, self.request.user)
        Table.objects.filter(pk__in=[t.pk for t in tables]).update(is_active=False, merged_into=None)
        super().perform_destroy(instance)
        services.broadcast_floor(current_branch(self.request))


class TableViewSet(LiveFloorViewSet):
    queryset = Table.objects.all()
    serializer_class = TableSerializer
    perm_read = roles.FLOOR_VIEW
    perm_write = roles.FLOOR_MANAGE
    perm_actions = {"open": roles.TICKET_OPEN, "merge": (roles.FLOOR_MANAGE, roles.TICKET_MOVE),
                    "unmerge": (roles.FLOOR_MANAGE, roles.TICKET_MOVE), "layout": roles.FLOOR_MANAGE,
                    "state": roles.FLOOR_VIEW, "qr": roles.FLOOR_MANAGE}
    ordering = ("hall__sort", "name")

    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)

    @transaction.atomic
    def perform_destroy(self, instance):
        _remove_tables([instance], self.request.user)
        instance.merged_into = None
        instance.save(update_fields=["merged_into"])
        super().perform_destroy(instance)
        services.broadcast_floor(current_branch(self.request))

    @action(detail=False, methods=["post"])
    def layout(self, request):
        """Sürükle-bırak masa yerleşimini kaydeder."""
        branch = current_branch(request)
        n = 0
        for item in request.data.get("tables", []):
            t = Table.objects.filter(pk=item.get("id"), branch=branch).first()
            if t:
                for f in ("x", "y", "w", "h"):
                    if f in item:
                        setattr(t, f, max(0, int(item[f])))
                t.save(update_fields=["x", "y", "w", "h"])
                n += 1
        audit.log("floor.layout", request=request, entity="Hall", after={"tables": n})
        services.broadcast_floor(branch)
        return Response({"updated": n})

    @action(detail=True, methods=["post"])
    def open(self, request, pk=None):
        t = self.get_object()
        ticket, created = services.open_ticket(branch=current_branch(request), user=request.user, table=t,
                                               guest_count=int(request.data.get("guest_count") or 1))
        return Response(TicketDetailSerializer(ticket).data, status=201 if created else 200)

    @action(detail=True, methods=["post"])
    def merge(self, request, pk=None):
        primary = self.get_object()
        secondary = get_object_or_404(Table, pk=request.data.get("table"), branch=current_branch(request))
        services.merge_tables(primary, secondary, user=request.user)
        return Response({"ok": True})

    @action(detail=True, methods=["post"])
    def unmerge(self, request, pk=None):
        services.unmerge_table(self.get_object(), user=request.user)
        return Response({"ok": True})

    @action(detail=True, methods=["get"])
    def qr(self, request, pk=None):
        """Masa QR kodu (JET Menü). İçerik JET Menü ayarındaki URL şablonundan üretilir."""
        from apps.core.qr import response
        from apps.integrations.models import IntegrationConfig

        t = self.get_object()
        cfg = IntegrationConfig.objects.filter(business=t.business).first()
        tpl = cfg.qr_url_template if cfg and cfg.qr_url_template else "{token}"
        data = tpl.replace("{token}", str(t.qr_token)).replace("{branch}", t.branch.code)
        return response(data, f"masa-{t.name}.png")

    @action(detail=True, methods=["get"])
    def state(self, request, pk=None):
        return Response(table_state(self.get_object()))


class FloorView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.FLOOR_VIEW

    def get(self, request):
        branch = current_branch(request)
        halls = Hall.objects.filter(branch=branch, is_active=True)
        tables = list(Table.objects.filter(branch=branch, is_active=True).select_related("hall"))
        tickets = {t.table_id: t for t in services.live_tickets(
            Ticket.objects.filter(branch=branch, table__isnull=False)).select_related("waiter").prefetch_related("batches", "lines")}
        reserved_ids = set()
        try:
            from apps.modules.models import Reservation

            now = timezone.now()
            reserved_ids = set(Reservation.objects.filter(
                branch=branch, status__in=("pending", "confirmed"), table__isnull=False,
                starts_at__lte=now + timezone.timedelta(minutes=60),
                starts_at__gte=now - timezone.timedelta(minutes=30)).values_list("table_id", flat=True))
        except Exception:
            pass
        states = [table_state(t, tickets.get(t.id), reserved=t.id in reserved_ids, lookup=False) for t in tables]
        others = services.live_tickets(Ticket.objects.filter(branch=branch, table__isnull=True)).select_related(
            "table", "waiter", "customer", "customer_group")
        return Response({
            "halls": HallSerializer(halls, many=True).data,
            "tables": states,
            "other_tickets": TicketSerializer(others, many=True).data,
            "summary": {s: sum(1 for x in states if x["status"] == s) for s in
                        ("empty", "occupied", "waiting", "reserved", "bill", "paid")},
        })


class TicketViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.FLOOR_VIEW
    perm_actions = {
        "create": roles.TICKET_OPEN, "add_line": roles.TICKET_ADD, "update_line": roles.TICKET_ADD,
        "delete_line": roles.TICKET_ADD, "send": roles.TICKET_SEND, "void_line": roles.TICKET_ADD,
        "discount": roles.TICKET_ADD, "reverse_discount": roles.TICKET_ADD, "customer_group": roles.TICKET_ADD,
        "request_bill": roles.TICKET_BILL, "move": roles.TICKET_MOVE, "pay": roles.PAYMENT_TAKE,
        "split_preview": roles.PAYMENT_TAKE, "close": (roles.PAYMENT_TAKE, roles.FLOOR_MANAGE),
        "cancel": roles.TICKET_OPEN, "set_customer": roles.TICKET_ADD, "pickup": roles.READY_VIEW,
    }

    def get_queryset(self):
        branch = current_branch(self.request)
        qs = Ticket.objects.filter(branch=branch).select_related("table", "waiter", "customer", "customer_group")
        g = self.request.GET
        if g.get("active") == "1":
            qs = qs.filter(status__in=ACTIVE_TICKET_STATES)
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        if g.get("date"):
            qs = qs.filter(business_date=g["date"])
        if g.get("number"):
            qs = qs.filter(number=g["number"])
        if self.action == "list":
            qs = qs.exclude(pk__in=services.blank_tickets().values("pk"))
        return limit_list(self, qs, 300)

    def get_serializer_class(self):
        return TicketDetailSerializer if self.action == "retrieve" else TicketSerializer

    def get_object(self):
        return get_object_or_404(Ticket, pk=self.kwargs["pk"], branch=current_branch(self.request))

    def _detail(self, ticket, code=200):
        ticket.refresh_from_db()
        return Response(TicketDetailSerializer(ticket).data, status=code)

    def create(self, request):
        """Masasız adisyon: gel-al / teslimat / QR."""
        branch = current_branch(request)
        channel = request.data.get("channel", "takeaway")
        if channel == "table":
            table = get_object_or_404(Table, pk=request.data.get("table"), branch=branch)
            t, created = services.open_ticket(branch=branch, user=request.user, table=table)
        else:
            t, created = services.open_ticket(branch=branch, user=request.user, channel=channel)
        return self._detail(t, 201 if created else 200)

    @action(detail=True, methods=["post"])
    def add_line(self, request, pk=None):
        t = self.get_object()
        line, created = services.add_line(t, user=request.user, product_id=request.data.get("product"),
                                          qty=request.data.get("qty", 1), option_ids=request.data.get("options", []),
                                          note=request.data.get("note", ""), seat=request.data.get("seat"),
                                          client_uid=request.data.get("client_uid", ""))
        resp = self._detail(t, 201 if created else 200)
        if getattr(line, "stock_warning", False):
            resp.data["warning"] = f"'{line.name}' için stok yetersiz görünüyor"
        return resp

    @action(detail=True, methods=["post"])
    def update_line(self, request, pk=None):
        t = self.get_object()
        line = get_object_or_404(TicketLine, pk=request.data.get("line"), ticket=t)
        kw = {}
        for f in ("qty", "note"):
            if f in request.data:
                kw[f] = request.data[f]
        if "options" in request.data:
            kw["option_ids"] = request.data["options"]
        if "seat" in request.data:
            kw["seat"] = request.data["seat"]
        services.update_line(line, user=request.user, **kw)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def delete_line(self, request, pk=None):
        t = self.get_object()
        services.delete_draft_line(get_object_or_404(TicketLine, pk=request.data.get("line"), ticket=t), user=request.user)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    @idempotent("ticket.send")
    def send(self, request, pk=None):
        t = self.get_object()
        batch = services.send_to_kitchen(t, user=request.user, confirmed=bool(request.data.get("confirmed")))
        resp = self._detail(t)
        resp.data["sent_batch"] = batch.number
        return resp

    @action(detail=True, methods=["post"])
    def void_line(self, request, pk=None):
        t = self.get_object()
        line = get_object_or_404(TicketLine, pk=request.data.get("line"), ticket=t)
        try:
            services.void_line(line, user=request.user, reason=request.data.get("reason", ""),
                               qty=request.data.get("qty"), approver=_approver(request))
        except ApprovalRequired:
            if not request.data.get("request_approval"):
                raise
            req = services.request_approval(ticket=t, user=request.user, kind="void",
                                            payload={"line_id": line.id, "qty": request.data.get("qty"), "name": line.name},
                                            reason=request.data.get("reason", ""), perm=roles.TICKET_VOID)
            return Response({"approval": ApprovalSerializer(req).data, "pending": True}, status=202)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def discount(self, request, pk=None):
        t = self.get_object()
        kind, value, reason = request.data.get("kind"), request.data.get("value"), request.data.get("reason", "")
        try:
            services.apply_discount(t, user=request.user, kind=kind, value=value, reason=reason,
                                    approver=_approver(request))
        except ApprovalRequired:
            if not request.data.get("request_approval"):
                raise
            req = services.request_approval(ticket=t, user=request.user, kind="discount",
                                            payload={"kind": kind, "value": str(value)}, reason=reason,
                                            perm=roles.TICKET_DISCOUNT)
            return Response({"approval": ApprovalSerializer(req).data, "pending": True}, status=202)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def reverse_discount(self, request, pk=None):
        t = self.get_object()
        d = get_object_or_404(TicketDiscount, pk=request.data.get("discount"), ticket=t)
        services.reverse_discount(d, user=request.user, reason=request.data.get("reason", ""), approver=_approver(request))
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def customer_group(self, request, pk=None):
        t = self.get_object()
        g = get_object_or_404(CustomerGroup, pk=request.data.get("group"), business=t.business)
        res = services.request_customer_group(t, user=request.user, group=g, reason=request.data.get("reason", ""))
        if isinstance(res, ApprovalRequest):
            return Response({"approval": ApprovalSerializer(res).data, "pending": True}, status=202)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def set_customer(self, request, pk=None):
        t = self.get_object()
        from apps.modules.models import Customer

        c = Customer.objects.filter(pk=request.data.get("customer"), business=t.business).first() if request.data.get("customer") else None
        t.customer = c
        t.save(update_fields=["customer"])
        audit.log("ticket.customer", request=request, entity="Ticket", entity_id=t.pk, after={"customer": c.name if c else None})
        services.broadcast_table(t)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def request_bill(self, request, pk=None):
        t = services.request_bill(self.get_object(), user=request.user)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        t = self.get_object()
        target = get_object_or_404(Table, pk=request.data.get("table"), branch=current_branch(request))
        services.move_ticket(t, user=request.user, target=target)
        return self._detail(t)

    @action(detail=True, methods=["get"])
    def split_preview(self, request, pk=None):
        t = self.get_object()
        services.recalc(t)
        parts = request.GET.get("parts")
        data = {"remaining": t.remaining, "total": t.total, "paid": t.paid_total}
        if parts:
            data["shares"] = services.equal_split(t, parts)
        seats = {}
        for ln in t.lines.filter(status="sent"):
            due = services.line_due(ln)
            if due > 0:
                key = str(ln.seat or 0)
                seats.setdefault(key, {"seat": ln.seat, "lines": [], "amount": 0})
                seats[key]["lines"].append({"id": ln.id, "name": ln.name, "qty": ln.qty, "due": due})
                seats[key]["amount"] += due
        data["by_seat"] = list(seats.values())
        return Response(data)

    @action(detail=True, methods=["post"])
    @idempotent("payment")
    def pay(self, request, pk=None):
        t = self.get_object()
        from apps.modules.models import Customer

        cust = Customer.objects.filter(pk=request.data.get("customer"), business=t.business).first() if request.data.get("customer") else None
        p = services.take_payment(
            t, user=request.user, method=request.data.get("method"), amount=request.data.get("amount"),
            tendered=request.data.get("tendered"), split_mode=request.data.get("split_mode", "partial"),
            line_ids=request.data.get("lines") or None, customer=cust, reference=request.data.get("reference", ""),
            idempotency_key=request.headers.get("Idempotency-Key", ""), device=request.headers.get("X-Device", ""))
        resp = self._detail(t, 201)
        resp.data["payment"] = PaymentSerializer(p).data
        return resp

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        t = services.close_ticket(self.get_object(), user=request.user)
        return self._detail(t)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        t = services.cancel_empty_ticket(self.get_object(), user=request.user)
        return self._detail(t)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        t = self.get_object()
        from apps.core.models import AuditLog

        logs = AuditLog.objects.filter(Q(entity="Ticket", entity_id=str(t.id)) |
                                       Q(entity="TicketLine", entity_id__in=[str(i) for i in t.lines.values_list("id", flat=True)]) |
                                       Q(entity="Payment", entity_id__in=[str(i) for i in t.payments.values_list("id", flat=True)]))
        return Response([{"action": a.action, "user": a.user.username if a.user else "", "reason": a.reason,
                          "before": a.before, "after": a.after, "created_at": a.created_at} for a in logs.order_by("created_at")])


class ApprovalViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApprovalSerializer

    def get_queryset(self):
        branch = current_branch(self.request)
        qs = ApprovalRequest.objects.filter(branch=branch).select_related("ticket", "ticket__table", "requested_by")
        st = self.request.GET.get("status", "pending")
        if st != "all":
            qs = qs.filter(status=st)
        u = self.request.user
        perms = [p for p in (roles.APPROVALS_DECIDE, roles.APPROVALS_MUNICIPAL, roles.TICKET_VOID,
                             roles.TICKET_DISCOUNT, roles.PAYMENT_REFUND) if roles.has_perm(u, p)]
        return limit_list(self, qs.filter(Q(required_perm__in=perms) | Q(requested_by=u)), 200)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        req, _ = services.decide_approval(self.get_object(), user=request.user, approve=True,
                                          note=request.data.get("note", ""))
        return Response(ApprovalSerializer(req).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req, _ = services.decide_approval(self.get_object(), user=request.user, approve=False,
                                          note=request.data.get("note", ""))
        return Response(ApprovalSerializer(req).data)


class KitchenViewSet(viewsets.ReadOnlyModelViewSet):
    """KDS: istasyon personeli kendi istasyonunu, yönetici merkezi görünümü görür (§7.1)."""

    serializer_class = KitchenOrderSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.KDS_VIEW
    perm_actions = {"start": roles.KDS_VIEW, "ready": roles.KDS_VIEW, "priority": roles.KDS_MANAGE,
                    "ready_all": roles.KDS_MANAGE}

    def get_queryset(self):
        branch = current_branch(self.request)
        qs = KitchenOrder.objects.filter(batch__ticket__branch=branch).select_related(
            "station", "batch", "batch__ticket", "batch__ticket__table", "batch__ticket__waiter")
        station = self.request.GET.get("station")
        if station:
            qs = qs.filter(station_id=station)
        elif not roles.has_perm(self.request.user, roles.KDS_MANAGE) and self.action == "list":
            if not station:
                return qs.none()
        if self.request.GET.get("done") == "1":
            return qs.filter(status="ready", ready_at__gte=timezone.now() - timezone.timedelta(hours=2)).order_by("-ready_at")
        return qs.exclude(status="ready").order_by("-priority", "created_at")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["late_minutes"] = current_branch(self.request).settings.late_order_minutes
        return ctx

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        o = services.kitchen_start(self.get_object(), user=request.user)
        return Response(KitchenOrderSerializer(o, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def ready(self, request, pk=None):
        o = self.get_object()
        services.kitchen_ready(o, user=request.user)
        o.refresh_from_db()
        return Response(KitchenOrderSerializer(o, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def priority(self, request, pk=None):
        o = services.set_priority(self.get_object(), user=request.user, priority=request.data.get("priority", 0))
        return Response(KitchenOrderSerializer(o, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def ready_all(self, request, pk=None):
        o = self.get_object()
        services.batch_ready_all(o.batch, user=request.user)
        return Response({"ok": True})


class ReadyOrdersView(APIView):
    """Hazır Siparişler ekranı; garson teslim aldı olarak işaretler (§7.1)."""

    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.READY_VIEW
    perm_write = roles.READY_VIEW

    def get(self, request):
        branch = current_branch(request)
        qs = KitchenBatch.objects.filter(ticket__branch=branch, status="ready").select_related("ticket", "ticket__table", "ticket__waiter")
        if request.GET.get("mine") == "1":
            qs = qs.filter(ticket__waiter=request.user)
        return Response([{"id": b.id, "number": b.number, "ticket": b.ticket_id, "ticket_number": b.ticket.number,
                          "table": b.ticket.table.name if b.ticket.table else b.ticket.get_channel_display(),
                          "waiter": b.ticket.waiter.username if b.ticket.waiter else "", "ready_at": b.ready_at,
                          "minutes": int((timezone.now() - b.ready_at).total_seconds() // 60) if b.ready_at else 0,
                          "items": [f"{ln.qty.normalize()} x {ln.name}" for ln in b.lines.exclude(status="void")]}
                         for b in qs.order_by("ready_at")])

    def post(self, request):
        b = get_object_or_404(KitchenBatch, pk=request.data.get("batch"), ticket__branch=current_branch(request))
        services.pickup_batch(b, user=request.user)
        return Response({"ok": True})


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.PAYMENT_TAKE
    perm_actions = {"refund": roles.PAYMENT_TAKE}

    def get_queryset(self):
        qs = Payment.objects.filter(branch=current_branch(self.request)).select_related("ticket", "user")
        g = self.request.GET
        if g.get("date"):
            qs = qs.filter(created_at__date=g["date"])
        if g.get("ticket"):
            qs = qs.filter(ticket_id=g["ticket"])
        if g.get("cash_day"):
            qs = qs.filter(cash_day_id=g["cash_day"])
        return limit_list(self, qs.order_by("-created_at"), 300)

    @action(detail=True, methods=["post"])
    @idempotent("refund")
    def refund(self, request, pk=None):
        p = self.get_object()
        try:
            r = services.refund_payment(p, user=request.user, amount=request.data.get("amount"),
                                        reason=request.data.get("reason", ""), line_ids=request.data.get("lines") or [],
                                        restock=bool(request.data.get("restock")), approver=_approver(request))
        except ApprovalRequired:
            if not request.data.get("request_approval"):
                raise
            req = services.request_approval(ticket=p.ticket, user=request.user, kind="refund",
                                            payload={"payment_id": p.id, "amount": str(request.data.get("amount")),
                                                     "line_ids": request.data.get("lines") or [],
                                                     "restock": bool(request.data.get("restock"))},
                                            reason=request.data.get("reason", ""), perm=roles.PAYMENT_REFUND)
            return Response({"approval": ApprovalSerializer(req).data, "pending": True}, status=202)
        return Response({"refund": r.id, "payment": PaymentSerializer(p.__class__.objects.get(pk=p.pk)).data}, status=201)


class CashView(APIView):
    """Kasa ve gün sonu (§6.3)."""

    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.CASH_MANAGE
    perm_write = roles.CASH_MANAGE

    def get(self, request):
        branch = current_branch(request)
        day = CashDay.objects.filter(branch=branch, status__in=("open", "pending_approval")).first()
        history = CashDay.objects.filter(branch=branch, status="closed").order_by("-business_date")[:30]
        data = {"current": CashDaySerializer(day).data if day else None,
                "history": CashDaySerializer(history, many=True).data}
        if day:
            data["movements"] = CashMovementSerializer(day.movements.select_related("user"), many=True).data
            data["live_report"] = services.build_day_report(day)
        return Response(data)

    def post(self, request):
        branch = current_branch(request)
        act = request.data.get("action")
        day = CashDay.objects.filter(branch=branch, status__in=("open", "pending_approval")).first()
        if act == "open":
            day = services.open_cash_day(branch, user=request.user, opening_balance=request.data.get("opening_balance", 0))
        elif day is None:
            raise BusinessError("Açık kasa günü yok", code="cash_closed")
        elif act == "movement":
            services.add_cash_movement(day, user=request.user, kind=request.data.get("kind"),
                                       amount=request.data.get("amount", 0), reason=request.data.get("reason", ""))
        elif act == "count":
            services.count_cash_day(day, user=request.user, counted=request.data.get("counted", 0),
                                    reason=request.data.get("reason", ""))
        elif act == "approve":
            services.approve_cash_day(day, user=request.user)
        elif act == "reject":
            services.reject_cash_count(day, user=request.user, reason=request.data.get("reason", ""))
        else:
            raise BusinessError("Geçersiz işlem")
        return self.get(request)


class CashDayReportView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.CASH_MANAGE

    def get(self, request, pk):
        day = get_object_or_404(CashDay, pk=pk, branch=current_branch(request))
        return Response({"day": CashDaySerializer(day).data, "report": day.report or services.build_day_report(day),
                         "movements": CashMovementSerializer(day.movements.select_related("user"), many=True).data})


__all__ = ["status", "current_business"]
