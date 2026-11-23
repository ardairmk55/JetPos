from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Category, Station
from apps.catalog.serializers import BizScopedPKField
from apps.core import audit, roles
from apps.core.tenancy import TenantViewSet, limit_list

from . import escpos, services
from .models import Printer, PrintJob


class PrinterSerializer(serializers.ModelSerializer):
    stations = BizScopedPKField(queryset=Station.objects.all(), many=True, required=False)
    categories = BizScopedPKField(queryset=Category.objects.all(), many=True, required=False)
    backup = BizScopedPKField(queryset=Printer.objects.all(), allow_null=True, required=False)
    queued = serializers.SerializerMethodField()
    failed = serializers.SerializerMethodField()

    class Meta:
        model = Printer
        exclude = ["business", "branch"]
        read_only_fields = ["last_error", "last_ok_at"]

    def get_queued(self, obj):
        if hasattr(obj, "queued_n"):  # liste görünümünde toplu hesaplanır
            return obj.queued_n
        return obj.jobs.filter(status__in=("queued", "printing")).count()

    def get_failed(self, obj):
        if hasattr(obj, "failed_n"):
            return obj.failed_n
        return obj.jobs.filter(status="failed").count()

    def validate(self, data):
        if data.get("connection", getattr(self.instance, "connection", None)) in ("network", "windows") and not data.get(
                "address", getattr(self.instance, "address", "")):
            raise serializers.ValidationError("Ağ/Windows yazıcı için adres zorunlu")
        b = data.get("backup")
        if b is not None and self.instance and b.pk == self.instance.pk:
            raise serializers.ValidationError("Yazıcı kendi yedeği olamaz")
        try:
            "ÇĞİÖŞÜçğıöşü".encode(data.get("codepage", getattr(self.instance, "codepage", "cp857")))
        except (LookupError, UnicodeEncodeError):
            raise serializers.ValidationError("Kod sayfası Türkçe karakterleri desteklemiyor")
        return data


class PrintJobSerializer(serializers.ModelSerializer):
    printer_name = serializers.CharField(source="printer.name", read_only=True)
    printed_on_name = serializers.CharField(source="printed_on.name", default="", read_only=True)
    preview = serializers.SerializerMethodField()

    class Meta:
        model = PrintJob
        exclude = ["business", "content"]

    def get_preview(self, obj):
        return escpos.as_text(obj.content, obj.printer.columns)


class PrinterViewSet(TenantViewSet):
    queryset = Printer.objects.all()
    serializer_class = PrinterSerializer
    perm_read = (roles.PRINTERS_MANAGE, roles.PAYMENT_TAKE)
    perm_write = roles.PRINTERS_MANAGE
    perm_actions = {"test": roles.PRINTERS_MANAGE}
    ordering = ("name",)

    def get_queryset(self):
        from django.db.models import Count, Q

        return super().get_queryset().annotate(
            queued_n=Count("jobs", filter=Q(jobs__status__in=("queued", "printing")), distinct=True),
            failed_n=Count("jobs", filter=Q(jobs__status="failed"), distinct=True)).prefetch_related("stations", "categories")

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        p = self.get_object()
        job = services.enqueue_test(p)
        services.process_job(job)
        job.refresh_from_db()
        audit.log("printer.test", request=request, entity="Printer", entity_id=p.pk, after={"status": job.status})
        return Response(PrintJobSerializer(job).data)


class PrintJobViewSet(TenantViewSet):
    queryset = PrintJob.objects.all()
    serializer_class = PrintJobSerializer
    perm_read = (roles.PRINTERS_MANAGE, roles.PAYMENT_TAKE)
    perm_write = (roles.PRINTERS_MANAGE, roles.PAYMENT_TAKE)
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("printer", "printed_on")
        st = self.request.GET.get("status")
        if st:
            qs = qs.filter(status=st)
        return limit_list(self, qs, 200)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        job = self.get_object()
        if job.status == "failed":
            job.status = "queued"
            job.attempts = 0
            job.save(update_fields=["status", "attempts"])
        services.process_job(job)
        job.refresh_from_db()
        return Response(PrintJobSerializer(job).data)

    @action(detail=False, methods=["post"])
    def reprint(self, request):
        from apps.pos.models import Ticket

        from apps.core.tenancy import current_branch

        t = Ticket.objects.filter(pk=request.data.get("ticket"), branch=current_branch(request)).first()
        if not t:
            return Response({"detail": "Adisyon bulunamadı"}, status=404)
        jobs = services.enqueue_bill(t)
        return Response({"jobs": len(jobs)})
