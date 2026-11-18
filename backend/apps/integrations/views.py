from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.models import Branch
from apps.core.tenancy import HasPerm, current_branch, current_business
from apps.licensing.services import ModuleRequired, module_enabled

from . import services
from .models import IntegrationConfig, OutboxMessage, QrOrder


class ConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationConfig
        exclude = ["business"]
        read_only_fields = ["inbound_token", "signing_secret", "last_push_at"]


class JetMenuSettingsView(ModuleRequired, APIView):
    module = "jetmenu"
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.SETTINGS_MANAGE
    perm_write = roles.SETTINGS_MANAGE

    def get(self, request):
        cfg, _ = IntegrationConfig.objects.get_or_create(business=current_business(request))
        q = OutboxMessage.objects.filter(business=cfg.business)
        return Response({"config": ConfigSerializer(cfg).data,
                         "outbox": {"pending": q.filter(status="pending").count(), "failed": q.filter(status="failed").count(),
                                    "sent": q.filter(status="sent").count()},
                         "note": "JET Menü mevcut API'si doğrulanmadı; sözleşme JETPOS tarafında tanımlıdır (docs/JETMENU_API.md)."})

    def patch(self, request):
        cfg, _ = IntegrationConfig.objects.get_or_create(business=current_business(request))
        s = ConfigSerializer(cfg, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit.log("integration.jetmenu_update", request=request, entity="IntegrationConfig", entity_id=cfg.pk,
                  after={"enabled": cfg.enabled, "webhook": bool(cfg.webhook_url)})
        return Response(ConfigSerializer(cfg).data)

    def post(self, request):
        if request.data.get("action") == "push":
            return Response({"sent": services.push_outbox()})
        if request.data.get("action") == "resync":
            from apps.catalog.models import Product

            n = 0
            for p in Product.objects.filter(business=current_business(request)):
                if services.queue_catalog_change(p):
                    n += 1
            return Response({"queued": n})
        raise BusinessError("Geçersiz işlem")


def _cfg_from_token(request):
    tok = request.headers.get("X-Integration-Token", "")
    cfg = IntegrationConfig.objects.filter(inbound_token=tok, enabled=True).select_related("business").first() if tok else None
    if not cfg or not module_enabled(cfg.business, "jetmenu"):
        raise BusinessError("Geçersiz entegrasyon anahtarı", status_code=401)
    return cfg


class JetMenuCatalogView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        cfg = _cfg_from_token(request)
        branch = get_object_or_404(Branch, business=cfg.business, code=request.GET.get("branch", ""), is_active=True)
        return Response(services.catalog_export(cfg.business, branch))


class JetMenuOrderView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        cfg = _cfg_from_token(request)
        order, created = services.receive_qr_order(cfg.business, external_id=request.data.get("external_id", ""),
                                                   table_token=request.data.get("table_token", ""),
                                                   items=request.data.get("items", []), note=request.data.get("note", ""))
        return Response({"id": order.id, "status": order.status, "duplicate": not created}, status=201 if created else 200)


class QrOrderSerializer(serializers.ModelSerializer):
    table_name = serializers.CharField(source="table.name", read_only=True)

    class Meta:
        model = QrOrder
        exclude = ["business"]


class QrOrdersView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.TICKET_ADD
    perm_write = roles.TICKET_ADD

    def get(self, request):
        qs = QrOrder.objects.filter(branch=current_branch(request)).select_related("table")
        if request.GET.get("all") != "1":
            qs = qs.filter(status="received")
        return Response(QrOrderSerializer(qs[:100], many=True).data)

    def post(self, request):
        o = get_object_or_404(QrOrder, pk=request.data.get("id"), branch=current_branch(request))
        if request.data.get("action") == "accept":
            services.accept_qr_order(o, user=request.user)
        else:
            services.reject_qr_order(o, user=request.user, reason=request.data.get("reason", ""))
        return Response(QrOrderSerializer(o).data)
