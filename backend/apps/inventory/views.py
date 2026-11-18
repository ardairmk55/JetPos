from datetime import timedelta

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone
from rest_framework import permissions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.serializers import BizScopedPKField
from apps.core import roles
from apps.core.tenancy import HasPerm, TenantViewSet, current_branch, current_business, limit_list

from . import services
from .models import (PurchaseReceipt, RecipeLine, StockCount, StockItem, StockLevel, StockMovement, Supplier, Transfer,
                     Warehouse)
from apps.catalog.models import Product


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        exclude = ["business"]
        read_only_fields = ["branch"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        exclude = ["business"]


class StockItemSerializer(serializers.ModelSerializer):
    product = BizScopedPKField(queryset=Product.objects.all(), allow_null=True, required=False)
    supplier = BizScopedPKField(queryset=Supplier.objects.all(), allow_null=True, required=False)

    class Meta:
        model = StockItem
        exclude = ["business"]


class RecipeLineSerializer(serializers.ModelSerializer):
    product = BizScopedPKField(queryset=Product.objects.all())
    item = BizScopedPKField(queryset=StockItem.objects.all())
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_unit = serializers.CharField(source="item.unit", read_only=True)

    class Meta:
        model = RecipeLine
        exclude = ["business"]

    def validate(self, data):
        services.convert(1, data["unit"], data["item"].unit)  # birim uyumu
        return data


class MovementSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    user_name = serializers.CharField(source="user.username", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = StockMovement
        exclude = ["business"]


class StockPerm:
    perm_read = roles.STOCK_VIEW
    perm_write = roles.STOCK_MANAGE


class WarehouseViewSet(StockPerm, TenantViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    ordering = ("-is_default", "id")


class SupplierViewSet(StockPerm, TenantViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    branch_scoped = False
    search_fields_simple = ("name", "phone")
    ordering = ("name",)


class StockItemViewSet(StockPerm, TenantViewSet):
    queryset = StockItem.objects.all()
    serializer_class = StockItemSerializer
    branch_scoped = False
    search_fields_simple = ("name",)
    ordering = ("name",)

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        item = self.get_object()
        wh = Warehouse.objects.filter(pk=request.data.get("warehouse"), business=item.business).first() or \
            services.default_warehouse(current_branch(request))
        mv = services.manual_movement(warehouse=wh, item=item, kind=request.data.get("kind"), qty=request.data.get("qty", 0),
                                      user=request.user, reason=request.data.get("reason", ""), request=request)
        return Response(MovementSerializer(mv).data, status=201)


class RecipeLineViewSet(StockPerm, TenantViewSet):
    queryset = RecipeLine.objects.all()
    serializer_class = RecipeLineSerializer
    branch_scoped = False
    perm_read = roles.STOCK_VIEW
    perm_write = (roles.STOCK_MANAGE, roles.CATALOG_MANAGE)

    def get_queryset(self):
        qs = super().get_queryset().select_related("item")
        if self.request.GET.get("product"):
            qs = qs.filter(product_id=self.request.GET["product"])
        return qs


class MovementViewSet(StockPerm, TenantViewSet):
    queryset = StockMovement.objects.all()
    serializer_class = MovementSerializer
    http_method_names = ["get"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("item", "warehouse", "user")
        g = self.request.GET
        if g.get("item"):
            qs = qs.filter(item_id=g["item"])
        if g.get("kind"):
            qs = qs.filter(kind=g["kind"])
        if g.get("date_from"):
            qs = qs.filter(created_at__date__gte=g["date_from"])
        if g.get("date_to"):
            qs = qs.filter(created_at__date__lte=g["date_to"])
        return limit_list(self, qs, 500)


class StockOverview(APIView):
    """Panel: üstte özet kartlar, altta ayrıntılı stok tablosu (§8)."""

    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.STOCK_VIEW

    def get(self, request):
        branch = current_branch(request)
        biz = current_business(request)
        wh_id = request.GET.get("warehouse")
        wh = Warehouse.objects.filter(pk=wh_id, branch=branch).first() if wh_id else services.default_warehouse(branch)
        levels = {lv.item_id: lv.qty for lv in StockLevel.objects.filter(warehouse=wh)}
        rows = []
        value = 0
        low = 0
        out = 0
        for it in StockItem.objects.filter(business=biz, is_active=True).select_related("supplier"):
            q = levels.get(it.id, 0)
            state = "out" if q <= 0 else ("low" if q <= it.min_level else "ok")
            low += state == "low"
            out += state == "out"
            value += q * it.cost if q > 0 else 0
            rows.append({"id": it.id, "name": it.name, "unit": it.unit, "qty": q, "min_level": it.min_level,
                         "cost": it.cost, "value": round(q * it.cost, 2) if q > 0 else 0, "state": state,
                         "supplier": it.supplier.name if it.supplier else ""})
        today = timezone.localdate()
        mv_today = StockMovement.objects.filter(warehouse=wh, created_at__date=today).count()
        waste_week = StockMovement.objects.filter(warehouse=wh, kind="waste",
                                                  created_at__gte=timezone.now() - timedelta(days=7)).annotate(
            v=ExpressionWrapper(F("qty") * F("unit_cost"), output_field=DecimalField())).aggregate(s=Sum("v"))["s"] or 0
        return Response({
            "warehouse": {"id": wh.id, "name": wh.name},
            "warehouses": list(Warehouse.objects.filter(branch=branch, is_active=True).values("id", "name")),
            "cards": {"items": len(rows), "low": low, "out": out, "value": round(value, 2),
                      "movements_today": mv_today, "waste_week": round(abs(waste_week), 2)},
            "rows": rows,
        })


class PurchaseView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.STOCK_VIEW
    perm_write = roles.STOCK_MANAGE

    def get(self, request):
        qs = PurchaseReceipt.objects.filter(branch=current_branch(request)).select_related("supplier", "user")[:100]
        return Response([{"id": r.id, "supplier": r.supplier.name if r.supplier else "", "document_no": r.document_no,
                          "total": r.total, "user": r.user.username, "created_at": r.created_at,
                          "lines": [{"item": ln.item.name, "qty": ln.qty, "unit_cost": ln.unit_cost} for ln in r.lines.all()]}
                         for r in qs])

    def post(self, request):
        branch = current_branch(request)
        wh = Warehouse.objects.filter(pk=request.data.get("warehouse"), branch=branch).first() or services.default_warehouse(branch)
        sup = Supplier.objects.filter(pk=request.data.get("supplier"), business=branch.business).first()
        r = services.receive_purchase(warehouse=wh, supplier=sup, lines=request.data.get("lines", []), user=request.user,
                                      document_no=request.data.get("document_no", ""), note=request.data.get("note", ""))
        return Response({"id": r.id, "total": r.total}, status=201)


class TransferView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.STOCK_VIEW
    perm_write = roles.STOCK_MANAGE

    def get(self, request):
        biz = current_business(request)
        qs = Transfer.objects.filter(business=biz).select_related("source", "target", "user").order_by("-id")[:100]
        return Response([{"id": t.id, "source": t.source.name, "target": t.target.name, "note": t.note,
                          "user": t.user.username, "created_at": t.created_at,
                          "lines": [{"item": ln.item.name, "qty": ln.qty} for ln in t.lines.all()]} for t in qs])

    def post(self, request):
        biz = current_business(request)
        src = Warehouse.objects.get(pk=request.data.get("source"), business=biz)
        dst = Warehouse.objects.get(pk=request.data.get("target"), business=biz)
        t = services.transfer_stock(source=src, target=dst, lines=request.data.get("lines", []), user=request.user,
                                    note=request.data.get("note", ""))
        return Response({"id": t.id}, status=201)


class CountView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.STOCK_VIEW
    perm_write = roles.STOCK_MANAGE

    def get(self, request):
        qs = StockCount.objects.filter(warehouse__branch=current_branch(request)).order_by("-id")[:50]
        return Response([{"id": c.id, "warehouse": c.warehouse.name, "status": c.status, "note": c.note,
                          "created_at": c.created_at, "applied_at": c.applied_at,
                          "lines": [{"item": ln.item.name, "expected": ln.expected, "counted": ln.counted,
                                     "diff": ln.counted - ln.expected} for ln in c.lines.all()]} for c in qs])

    def post(self, request):
        branch = current_branch(request)
        if request.data.get("apply_id"):
            c = StockCount.objects.get(pk=request.data["apply_id"], warehouse__branch=branch)
            services.apply_count(c, user=request.user)
            return Response({"id": c.id, "status": c.status})
        wh = Warehouse.objects.filter(pk=request.data.get("warehouse"), branch=branch).first() or services.default_warehouse(branch)
        c = services.create_count(warehouse=wh, user=request.user, counts=request.data.get("lines", []),
                                  note=request.data.get("note", ""))
        return Response({"id": c.id, "status": c.status}, status=201)
