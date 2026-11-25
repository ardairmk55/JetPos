from django.utils import timezone
from rest_framework import serializers

from .models import (ACTIVE_TICKET_STATES, ApprovalRequest, CashDay, CashMovement, Hall, KitchenOrder, Payment, Refund,
                     Table, Ticket, TicketDiscount, TicketLine)

TABLE_STATUS_LABELS = {
    "empty": "Boş", "occupied": "Dolu", "waiting": "Sipariş bekliyor", "reserved": "Rezerve",
    "bill": "Hesap bekliyor", "paid": "Ödendi",
}


def table_state(table, ticket=None, reserved=None, lookup=True):
    """lookup=False: çağıran aktif adisyonları zaten topluca çekti (masa boşsa ek sorgu atma)."""
    if ticket is None and lookup:
        from .services import live_tickets

        ticket = live_tickets(Ticket.objects.filter(table=table)).first()
    info = None
    status = "empty"
    if ticket:
        # all() kullanılır: çağıran prefetch_related("batches", "lines") yaptıysa ek sorgu atılmaz
        batches = list(ticket.batches.all())
        pending = any(b.status == "pending" for b in batches)
        ready = sum(1 for b in batches if b.status == "ready")
        lines = [ln for ln in ticket.lines.all() if ln.status != "void"]
        drafts = sum(1 for ln in lines if ln.status == "draft")
        if ticket.status == "paid":
            status = "paid"
        elif ticket.status == "bill_requested":
            status = "bill"
        elif pending or drafts:
            status = "waiting"
        else:
            status = "occupied"
        info = {"id": ticket.id, "number": ticket.number, "total": ticket.total, "paid": ticket.paid_total,
                "waiter": (ticket.waiter.get_full_name() or ticket.waiter.username) if ticket.waiter else "",
                "items": sum(int(ln.qty) for ln in lines), "drafts": drafts, "ready": ready,
                "minutes": int((timezone.now() - ticket.opened_at).total_seconds() // 60), "status": ticket.status}
    else:
        if reserved is None:
            try:
                from apps.modules.services import table_reserved_now

                reserved = table_reserved_now(table)
            except Exception:
                reserved = False
        if reserved:
            status = "reserved"
    return {"id": table.id, "name": table.name, "hall": table.hall_id, "seats": table.seats, "shape": table.shape,
            "x": table.x, "y": table.y, "w": table.w, "h": table.h, "merged_into": table.merged_into_id,
            "status": status, "status_label": TABLE_STATUS_LABELS[status], "ticket": info}


class HallSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hall
        exclude = ["business", "branch"]


class TableSerializer(serializers.ModelSerializer):
    class Meta:
        model = Table
        exclude = ["business", "branch", "qr_token"]

    def validate_hall(self, hall):
        from apps.core.tenancy import current_branch

        if hall.branch_id != current_branch(self.context["request"]).id:
            raise serializers.ValidationError("Salon bu şubeye ait değil")
        return hall


class LineSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    station_name = serializers.CharField(source="station.name", default="", read_only=True)
    batch_number = serializers.IntegerField(source="batch.number", default=None, read_only=True)
    paid = serializers.SerializerMethodField()

    class Meta:
        model = TicketLine
        fields = ["id", "product", "name", "qty", "base_price", "unit_price", "options", "note", "tax_rate",
                  "tax_included", "station", "station_name", "status", "status_label", "batch", "batch_number",
                  "campaign_discount", "campaign_name", "net_total", "tax_amount", "seat", "created_at", "sent_at",
                  "void_reason", "voided_at", "client_uid", "paid"]

    def get_paid(self, obj):
        from .services import line_due

        return obj.status == "sent" and line_due(obj) == 0


class DiscountSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", default="", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.username", default="", read_only=True)

    class Meta:
        model = TicketDiscount
        fields = ["id", "kind", "value", "amount", "reason", "customer_group", "created_by_name", "approved_by_name",
                  "created_at", "reversed_at", "reverse_reason"]


class PaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True)
    ticket_number = serializers.IntegerField(source="ticket.number", read_only=True)
    refundable = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        exclude = ["business", "idempotency_key"]

    def get_refundable(self, obj):
        return obj.amount - obj.refunded_amount


class BatchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.IntegerField()
    status = serializers.CharField()
    sent_at = serializers.DateTimeField()
    ready_at = serializers.DateTimeField()


class TicketSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source="table.name", default="", read_only=True)
    waiter_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    remaining = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    customer_name = serializers.CharField(source="customer.name", default="", read_only=True)
    customer_group_name = serializers.CharField(source="customer_group.name", default="", read_only=True)

    class Meta:
        model = Ticket
        exclude = ["business"]

    def get_waiter_name(self, obj):
        return (obj.waiter.get_full_name() or obj.waiter.username) if obj.waiter else ""


class TicketDetailSerializer(TicketSerializer):
    lines = serializers.SerializerMethodField()
    discounts = DiscountSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    batches = serializers.SerializerMethodField()
    pending_approvals = serializers.SerializerMethodField()
    delivery = serializers.SerializerMethodField()

    def get_lines(self, obj):
        return LineSerializer(obj.lines.select_related("station", "batch"), many=True).data

    def get_batches(self, obj):
        return BatchSerializer(obj.batches.all(), many=True).data

    def get_pending_approvals(self, obj):
        return list(obj.approvals.filter(status="pending").values("id", "kind", "reason", "payload", "created_at"))

    def get_delivery(self, obj):
        d = getattr(obj, "delivery", None)
        if not d:
            return None
        return {"id": d.id, "status": d.status, "address": d.address, "contact_name": d.contact_name, "phone": d.phone,
                "courier": d.courier.name if d.courier else ""}


class ApprovalSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source="requested_by.username", read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.username", default="", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    ticket_number = serializers.IntegerField(source="ticket.number", default=None, read_only=True)
    table_name = serializers.CharField(source="ticket.table.name", default="", read_only=True)

    class Meta:
        model = ApprovalRequest
        exclude = ["business"]


class KitchenOrderSerializer(serializers.ModelSerializer):
    station_name = serializers.CharField(source="station.name", read_only=True)
    ticket = serializers.IntegerField(source="batch.ticket_id", read_only=True)
    ticket_number = serializers.IntegerField(source="batch.ticket.number", read_only=True)
    batch_number = serializers.IntegerField(source="batch.number", read_only=True)
    batch_id = serializers.IntegerField(source="batch.id", read_only=True)
    table_name = serializers.CharField(source="batch.ticket.table.name", default="", read_only=True)
    channel = serializers.CharField(source="batch.ticket.channel", read_only=True)
    waiter = serializers.CharField(source="batch.ticket.waiter.username", default="", read_only=True)
    lines = serializers.SerializerMethodField()
    elapsed = serializers.SerializerMethodField()
    late = serializers.SerializerMethodField()

    class Meta:
        model = KitchenOrder
        fields = ["id", "station", "station_name", "status", "priority", "created_at", "started_at", "ready_at",
                  "ticket", "ticket_number", "batch_number", "batch_id", "table_name", "channel", "waiter", "lines",
                  "elapsed", "late"]

    def get_lines(self, obj):
        return [{"id": ln.id, "name": ln.name, "qty": ln.qty, "options": [o["name"] for o in ln.options],
                 "note": ln.note, "void": ln.status == "void", "void_reason": ln.void_reason}
                for ln in obj.batch.lines.filter(station=obj.station).order_by("id")]

    def get_elapsed(self, obj):
        return int((timezone.now() - obj.created_at).total_seconds() // 60)

    def get_late(self, obj):
        limit = self.context.get("late_minutes", 15)
        return obj.status != "ready" and self.get_elapsed(obj) >= limit


class CashMovementSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = CashMovement
        fields = ["id", "kind", "kind_label", "amount", "reason", "user_name", "created_at", "payment"]


class CashDaySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    opened_by_name = serializers.CharField(source="opened_by.username", read_only=True)
    approved_by_name = serializers.CharField(source="approved_by.username", default="", read_only=True)
    expected_now = serializers.SerializerMethodField()

    class Meta:
        model = CashDay
        exclude = ["business"]

    def get_expected_now(self, obj):
        from .services import expected_cash

        return expected_cash(obj)


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        exclude = ["business"]
