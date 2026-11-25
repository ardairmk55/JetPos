from datetime import timedelta
from pathlib import Path

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import Category, Station
from apps.catalog.serializers import BizScopedPKField
from apps.core import audit, roles
from apps.core.tenancy import TenantViewSet, current_branch, limit_list

from . import agent_api, escpos, services
from .models import PrintAgent, Printer, PrintJob


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
        via_agent = data.get("via_agent", getattr(self.instance, "via_agent", False))
        if via_agent and data.get("connection", getattr(self.instance, "connection", "network")) == "file":
            raise serializers.ValidationError("Yazıcı köprüsü yalnızca ağ veya Windows yazıcı ile kullanılır")
        backup = data.get("backup", getattr(self.instance, "backup", None))
        if backup is not None and backup.via_agent != via_agent:
            raise serializers.ValidationError("Yedek yazıcı da aynı şekilde (köprülü/köprüsüz) basılmalı")
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
    perm_actions = {"test": roles.PRINTERS_MANAGE, "agent_token": roles.PRINTERS_MANAGE,
                    "agent_status": (roles.PRINTERS_MANAGE, roles.PAYMENT_TAKE),
                    "agent_script": roles.PRINTERS_MANAGE}
    ordering = ("name",)

    @action(detail=False, methods=["post"], url_path="agent-token")
    def agent_token(self, request):
        if getattr(request, "support_grant", None):
            return Response({"detail": "Köprü anahtarını yalnızca işletme oluşturabilir"}, status=403)
        branch = current_branch(request)
        token = agent_api.issue_token(branch.business, branch)
        audit.log("printer.agent_token", request=request, entity="PrintAgent", entity_id=branch.pk)
        return Response({"token": token})

    @action(detail=False, url_path="agent-status")
    def agent_status(self, request):
        agent = PrintAgent.objects.filter(branch=current_branch(request)).first()
        seen = agent.last_seen_at if agent else None
        return Response({"configured": agent is not None,
                         "online": bool(seen and timezone.now() - seen < timedelta(seconds=30)),
                         "last_seen_at": seen})

    @action(detail=False, url_path="agent-script")
    def agent_script(self, request):
        # Windows .cmd dosyası: BOM'suz, CRLF satır sonlu. Anahtar dosyaya yazılmaz.
        text = (Path(__file__).parent / "agent" / "poshane-yazici-koprusu.cmd").read_text(encoding="utf-8")
        text = text.replace("__SERVER_URL__", request.build_absolute_uri("/").rstrip("/"))
        resp = HttpResponse("\r\n".join(text.splitlines()).encode("utf-8") + b"\r\n",
                            content_type="application/octet-stream")
        resp["Content-Disposition"] = 'attachment; filename="POSHANE-Yazici-Koprusu.cmd"'
        return resp

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
            services.requeue(job)
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
