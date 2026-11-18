from django.http import HttpResponse
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.tenancy import HasPerm, TenantViewSet, current_branch, current_business
from apps.licensing.services import module_enabled

from . import services
from .models import ReportSchedule, ReportTemplate

ADVANCED = {"profit", "custom", "stock"}


def _check(request, rtype):
    if rtype in ADVANCED and not module_enabled(current_business(request), "reports_advanced") and rtype != "stock":
        raise BusinessError("Gelişmiş raporlama modülü lisansınızda etkin değil", status_code=403)
    if rtype == "stock" and not module_enabled(current_business(request), "stock"):
        raise BusinessError("Stok modülü lisansınızda etkin değil", status_code=403)


class ReportMetaView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.REPORTS_VIEW

    def get(self, request):
        return Response({"types": services.REPORT_TYPES, "dimensions": services.DIMENSIONS, "metrics": services.METRICS})


class ReportRunView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.REPORTS_VIEW

    def get(self, request, rtype):
        _check(request, rtype)
        params = request.GET.dict()
        fmt = params.pop("export", "json")
        rep = services.run_report(rtype, current_branch(request), params)
        if fmt == "json":
            return Response(rep)
        if fmt not in services.EXPORTERS:
            raise BusinessError("Geçersiz format")
        fn, mime = services.EXPORTERS[fmt]
        audit.log("report.export", request=request, entity="Report", entity_id=rtype, after={"format": fmt})
        resp = HttpResponse(fn(rep), content_type=mime)
        resp["Content-Disposition"] = f'attachment; filename="jetpos_{rtype}_{rep["date_from"]}_{rep["date_to"]}.{fmt}"'
        return resp


class DashboardView(APIView):
    def get(self, request):
        return Response(services.dashboard(current_branch(request), request.user))


class TemplateSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ReportTemplate
        exclude = ["business"]
        read_only_fields = ["created_by"]


class TemplateViewSet(TenantViewSet):
    queryset = ReportTemplate.objects.all()
    serializer_class = TemplateSerializer
    branch_scoped = False
    perm_read = roles.REPORTS_VIEW
    perm_write = roles.REPORTS_VIEW

    def perform_create(self, serializer):
        serializer.save(business=current_business(self.request), created_by=self.request.user)


class ScheduleSerializer(serializers.ModelSerializer):
    last_delivery = serializers.SerializerMethodField()

    class Meta:
        model = ReportSchedule
        exclude = ["business"]
        read_only_fields = ["branch", "last_run_at", "created_by"]

    def validate_recipients(self, v):
        from django.core.validators import validate_email

        if not isinstance(v, list) or not v:
            raise serializers.ValidationError("En az bir alıcı gerekli")
        for e in v:
            validate_email(e)
        return v

    def validate_report_type(self, v):
        if v not in services.REPORT_TYPES:
            raise serializers.ValidationError("Geçersiz rapor")
        return v

    def get_last_delivery(self, obj):
        d = obj.deliveries.first()
        return {"period": d.period_key, "ok": d.ok, "attempts": d.attempts, "error": d.error, "at": d.updated_at} if d else None


class ScheduleViewSet(TenantViewSet):
    queryset = ReportSchedule.objects.all()
    serializer_class = ScheduleSerializer
    perm_read = roles.REPORTS_VIEW
    perm_write = roles.REPORTS_VIEW

    def perform_create(self, serializer):
        serializer.save(business=current_business(self.request), branch=current_branch(self.request),
                        created_by=self.request.user)
