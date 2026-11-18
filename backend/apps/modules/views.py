from datetime import date, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.models import User
from apps.core.tenancy import HasPerm, TenantViewSet, current_branch, current_business, limit_list
from apps.licensing.services import ModuleRequired

from . import services
from .models import (Attendance, Courier, Customer, CustomerAccountEntry, Delivery, FinanceAccount, FinanceEntry,
                     LeaveRequest, Reservation, Shift)


def _range(request, default_days=0):
    today = timezone.localdate()
    d1 = parse_date(request.GET.get("date_from", "") or "") or today - timedelta(days=default_days)
    d2 = parse_date(request.GET.get("date_to", "") or "") or today
    return d1, d2


class BizUserField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        return User.objects.filter(business=current_business(self.context["request"]))


# ------------------------------------------------------------------ CRM
class CustomerSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        exclude = ["business"]
        read_only_fields = ["visit_count", "total_spent", "last_visit", "anonymized_at", "consent_at"]

    def get_balance(self, obj):
        return services.customer_balance(obj)

    def validate(self, data):
        if data.get("kvkk_consent") and not (self.instance and self.instance.consent_at):
            data["consent_at"] = timezone.now()
        return data


class CustomerViewSet(ModuleRequired, TenantViewSet):
    module = "crm"
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    branch_scoped = False
    perm_read = (roles.CRM_MANAGE, roles.TICKET_OPEN)
    perm_write = roles.CRM_MANAGE
    search_fields_simple = ("name", "phone", "email")
    ordering = ("name",)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs if self.request.GET.get("all") == "1" else qs.filter(is_active=True)

    def retrieve(self, request, *args, **kwargs):
        c = self.get_object()
        audit.log("crm.view", request=request, entity="Customer", entity_id=c.pk)  # KVKK: erişim denetlenebilir
        return Response(CustomerSerializer(c).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        c = self.get_object()
        from apps.pos.models import Ticket

        audit.log("crm.view_history", request=request, entity="Customer", entity_id=c.pk)
        tickets = Ticket.objects.filter(customer=c).order_by("-opened_at")[:200]
        return Response({
            "tickets": [{"id": t.id, "number": t.number, "date": t.opened_at, "total": t.total, "status": t.status,
                         "channel": t.channel, "items": [f"{ln.qty.normalize()} x {ln.name}" for ln in t.lines.exclude(status="void")]}
                        for t in tickets],
            "account": [{"kind": e.kind, "amount": e.amount, "ref": e.ref, "date": e.created_at}
                        for e in c.account_entries.all()[:200]],
            "visits": c.visit_count, "total_spent": c.total_spent, "balance": services.customer_balance(c),
        })

    @action(detail=True, methods=["get"])
    def kvkk_export(self, request, pk=None):
        c = self.get_object()
        audit.log("crm.kvkk_export", request=request, entity="Customer", entity_id=c.pk)
        return Response(services.export_customer_data(c))

    @action(detail=True, methods=["post"])
    def anonymize(self, request, pk=None):
        c = self.get_object()
        services.anonymize_customer(c, user=request.user, reason=request.data.get("reason", ""), request=request)
        return Response(CustomerSerializer(c).data)

    @action(detail=True, methods=["post"])
    def collect(self, request, pk=None):
        c = self.get_object()
        e = services.collect_account(c, amount=request.data.get("amount", 0), method=request.data.get("method", "cash"),
                                     user=request.user, note=request.data.get("note", ""))
        return Response({"id": e.id, "balance": services.customer_balance(c)})


# ------------------------------------------------------------------ Kurye
class CourierSerializer(serializers.ModelSerializer):
    user = BizUserField(allow_null=True, required=False)

    class Meta:
        model = Courier
        exclude = ["business", "branch"]


class DeliverySerializer(serializers.ModelSerializer):
    courier_name = serializers.CharField(source="courier.name", default="", read_only=True)
    ticket_number = serializers.IntegerField(source="ticket.number", read_only=True)
    ticket_total = serializers.DecimalField(source="ticket.total", max_digits=12, decimal_places=2, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    minutes = serializers.SerializerMethodField()
    late = serializers.SerializerMethodField()

    class Meta:
        model = Delivery
        exclude = ["business"]
        read_only_fields = ["branch", "ticket", "status", "assigned_at", "dispatched_at", "delivered_at", "late_notified"]

    def get_minutes(self, obj):
        end = obj.delivered_at or timezone.now()
        return int((end - obj.created_at).total_seconds() // 60)

    def get_late(self, obj):
        return self.get_minutes(obj) > obj.promised_minutes and obj.status != "cancelled"


class CourierViewSet(ModuleRequired, TenantViewSet):
    module = "delivery"
    queryset = Courier.objects.all()
    serializer_class = CourierSerializer
    perm_read = roles.DELIVERY_MANAGE
    perm_write = roles.DELIVERY_MANAGE
    ordering = ("name",)


class DeliveryViewSet(ModuleRequired, TenantViewSet):
    module = "delivery"
    queryset = Delivery.objects.all()
    serializer_class = DeliverySerializer
    perm_read = roles.DELIVERY_MANAGE
    perm_write = roles.DELIVERY_MANAGE
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("courier", "ticket")
        if self.request.GET.get("active") == "1":
            qs = qs.exclude(status__in=("delivered", "cancelled"))
        return limit_list(self, qs, 300)

    def create(self, request, *args, **kwargs):
        branch = current_branch(request)
        cust = Customer.objects.filter(pk=request.data.get("customer"), business=branch.business).first()
        d = services.create_delivery(branch=branch, user=request.user, contact_name=request.data.get("contact_name") or (cust.name if cust else ""),
                                     phone=request.data.get("phone") or (cust.phone if cust else ""),
                                     address=request.data.get("address") or (cust.address if cust else ""),
                                     customer=cust, fee=request.data.get("fee") or 0,
                                     payment_note=request.data.get("payment_note", ""),
                                     promised_minutes=int(request.data.get("promised_minutes") or 45))
        if not d.contact_name or not d.address:
            raise BusinessError("Müşteri adı ve adres zorunludur")
        return Response(DeliverySerializer(d).data, status=201)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        d = self.get_object()
        courier = None
        if request.data.get("courier"):
            courier = Courier.objects.get(pk=request.data["courier"], business=d.business)
        services.set_delivery_status(d, user=request.user, status=request.data.get("status"), courier=courier)
        return Response(DeliverySerializer(d).data)

    @action(detail=False, methods=["get"])
    def performance(self, request):
        d1, d2 = _range(request, 30)
        return Response(services.courier_performance(current_branch(request), d1, d2))


# ------------------------------------------------------------------ Rezervasyon
class ReservationSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source="table.name", default="", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Reservation
        exclude = ["business"]
        read_only_fields = ["branch", "reminded_at", "created_by"]

    def validate(self, data):
        branch = current_branch(self.context["request"])
        t = data.get("table") or (self.instance.table if self.instance else None)
        if t and t.branch_id != branch.id:
            raise serializers.ValidationError("Masa bu şubeye ait değil")
        tmp = Reservation(**{**({f.name: getattr(self.instance, f.name) for f in Reservation._meta.concrete_fields}
                                if self.instance else {}), **data, "branch": branch})
        if self.instance:
            tmp.pk = self.instance.pk
        services.validate_reservation(tmp)
        return data


class ReservationViewSet(ModuleRequired, TenantViewSet):
    module = "reservation"
    queryset = Reservation.objects.all()
    serializer_class = ReservationSerializer
    perm_read = (roles.RESERVATION_MANAGE, roles.FLOOR_VIEW)
    perm_write = roles.RESERVATION_MANAGE
    search_fields_simple = ("name", "phone")
    ordering = ("starts_at",)

    def get_queryset(self):
        qs = super().get_queryset().select_related("table")
        g = self.request.GET
        if g.get("date"):
            qs = qs.filter(starts_at__date=g["date"])
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(business=current_business(self.request), branch=current_branch(self.request),
                              created_by=self.request.user)
        audit.log("reservation.create", request=self.request, entity="Reservation", entity_id=obj.pk, after=obj)

    @action(detail=True, methods=["post"])
    def seat(self, request, pk=None):
        t = services.seat_reservation(self.get_object(), user=request.user)
        return Response({"ticket": t.id})

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        r = self.get_object()
        st = request.data.get("status")
        if st not in dict(Reservation.STATUS) or st == "seated":
            raise BusinessError("Geçersiz durum")
        if st in ("pending", "confirmed") and r.status == "waitlist":
            r.status = st
            services.validate_reservation(r)
        r.status = st
        r.save(update_fields=["status"])
        audit.log("reservation.status", request=request, entity="Reservation", entity_id=r.pk, after={"status": st})
        return Response(ReservationSerializer(r, context={"request": request}).data)


# ------------------------------------------------------------------ Personel
class ShiftSerializer(serializers.ModelSerializer):
    user = BizUserField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        exclude = ["business"]
        read_only_fields = ["branch"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def validate(self, data):
        if data["ends_at"] <= data["starts_at"]:
            raise serializers.ValidationError("Bitiş başlangıçtan sonra olmalı")
        return data


class AttendanceSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        exclude = ["business"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class LeaveSerializer(serializers.ModelSerializer):
    user = BizUserField()
    user_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveRequest
        exclude = ["business"]
        read_only_fields = ["branch", "status", "decided_by"]

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class ShiftViewSet(ModuleRequired, TenantViewSet):
    module = "staff"
    queryset = Shift.objects.all()
    serializer_class = ShiftSerializer
    perm_read = roles.STAFF_MANAGE
    perm_write = roles.STAFF_MANAGE
    ordering = ("starts_at",)

    def get_queryset(self):
        qs = super().get_queryset().select_related("user")
        d1, d2 = _range(self.request, 0)
        if self.request.GET.get("date_from") or self.request.GET.get("date_to"):
            qs = qs.filter(starts_at__date__gte=d1, starts_at__date__lte=d2)
        return qs


class AttendanceViewSet(ModuleRequired, TenantViewSet):
    module = "staff"
    queryset = Attendance.objects.all()
    serializer_class = AttendanceSerializer
    perm_read = roles.STAFF_MANAGE
    perm_write = roles.STAFF_MANAGE
    http_method_names = ["get"]

    def get_queryset(self):
        d1, d2 = _range(self.request, 7)
        return super().get_queryset().select_related("user").filter(clock_in__date__gte=d1, clock_in__date__lte=d2)

    @action(detail=False, methods=["get"])
    def absences(self, request):
        day = parse_date(request.GET.get("date", "") or "") or timezone.localdate()
        return Response([{"user": s.user.get_full_name() or s.user.username, "shift_start": s.starts_at}
                         for s in services.absences(current_branch(request), day)])

    @action(detail=False, methods=["get"])
    def performance(self, request):
        d1, d2 = _range(request, 30)
        return Response(services.staff_performance(current_branch(request), d1, d2))


class LeaveViewSet(ModuleRequired, TenantViewSet):
    module = "staff"
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveSerializer
    perm_read = roles.STAFF_MANAGE
    perm_write = roles.STAFF_MANAGE

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        lv = self.get_object()
        lv.status = "approved" if request.data.get("approve") else "rejected"
        lv.decided_by = request.user
        lv.save(update_fields=["status", "decided_by"])
        audit.log("staff.leave_decision", request=request, entity="LeaveRequest", entity_id=lv.pk, after={"status": lv.status})
        return Response(LeaveSerializer(lv, context={"request": request}).data)


class TimeClockView(ModuleRequired, APIView):
    """Personelin kendi giriş/çıkış/mola işlemi."""

    module = "staff"

    def get(self, request):
        a = Attendance.objects.filter(user=request.user, clock_out__isnull=True).first()
        return Response(AttendanceSerializer(a).data if a else None)

    def post(self, request):
        act = request.data.get("action")
        if act == "in":
            a = services.clock_in(request.user, branch=current_branch(request))
        elif act == "break":
            a = services.toggle_break(request.user)
        elif act == "out":
            a = services.clock_out(request.user)
        else:
            raise BusinessError("Geçersiz işlem")
        return Response(AttendanceSerializer(a).data)


# ------------------------------------------------------------------ Finans
class FinanceAccountSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()

    class Meta:
        model = FinanceAccount
        exclude = ["business"]

    def get_balance(self, obj):
        return services.account_balance(obj)


class FinanceEntrySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    account_name = serializers.CharField(source="account.name", default="", read_only=True)
    reversed = serializers.SerializerMethodField()

    class Meta:
        model = FinanceEntry
        exclude = ["business"]
        read_only_fields = ["branch", "user", "reverses"]

    def get_reversed(self, obj):
        return FinanceEntry.objects.filter(reverses=obj).exists()

    def validate_amount(self, v):
        if v <= 0:
            raise serializers.ValidationError("Tutar pozitif olmalı")
        return v

    def validate(self, data):
        if data.get("kind") in ("payable", "receivable", "settle_payable", "settle_receivable") and not data.get("account"):
            raise serializers.ValidationError("Cari kayıt için hesap seçilmeli")
        acc = data.get("account")
        if acc and acc.business_id != current_business(self.context["request"]).id:
            raise serializers.ValidationError("Geçersiz hesap")
        return data


class FinanceAccountViewSet(ModuleRequired, TenantViewSet):
    module = "finance"
    queryset = FinanceAccount.objects.all()
    serializer_class = FinanceAccountSerializer
    branch_scoped = False
    perm_read = roles.FINANCE_MANAGE
    perm_write = roles.FINANCE_MANAGE
    ordering = ("name",)


class FinanceEntryViewSet(ModuleRequired, TenantViewSet):
    module = "finance"
    queryset = FinanceEntry.objects.all()
    serializer_class = FinanceEntrySerializer
    perm_read = roles.FINANCE_MANAGE
    perm_write = roles.FINANCE_MANAGE
    http_method_names = ["get", "post"]
    ordering = ("-date", "-id")

    def get_queryset(self):
        d1, d2 = _range(self.request, 30)
        return super().get_queryset().select_related("account").filter(date__gte=d1, date__lte=d2)

    def perform_create(self, serializer):
        obj = serializer.save(business=current_business(self.request), branch=current_branch(self.request),
                              user=self.request.user)
        audit.log("finance.create", request=self.request, entity="FinanceEntry", entity_id=obj.pk, after=obj)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        rev = services.reverse_finance_entry(self.get_object(), user=request.user, reason=request.data.get("reason", ""))
        return Response(FinanceEntrySerializer(rev, context={"request": request}).data, status=201)

    @action(detail=False, methods=["get"])
    def profitability(self, request):
        d1, d2 = _range(request, 30)
        return Response({"date_from": d1, "date_to": d2, **services.profitability(current_branch(request), d1, d2)})


__all__ = ["date", "HasPerm", "permissions", "CustomerAccountEntry"]
