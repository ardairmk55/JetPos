from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import roles
from apps.core.tenancy import HasPerm, TenantViewSet, current_branch, current_business

from .models import Campaign, Category, CustomerGroup, OptionGroup, PriceHistory, Product, ProductPrice, Station, TaxRate
from .pricing import resolve_price
from .serializers import (CampaignSerializer, CategorySerializer, CustomerGroupSerializer, OptionGroupSerializer,
                          PriceHistorySerializer, ProductPriceSerializer, ProductSerializer, StationSerializer,
                          TaxRateSerializer)


class CatalogViewSet(TenantViewSet):
    branch_scoped = False
    perm_read = None
    perm_write = roles.CATALOG_MANAGE


class TaxRateViewSet(CatalogViewSet):
    queryset = TaxRate.objects.all()
    serializer_class = TaxRateSerializer
    ordering = ("rate",)


class StationViewSet(TenantViewSet):
    queryset = Station.objects.all()
    serializer_class = StationSerializer
    perm_read = None
    perm_write = roles.CATALOG_MANAGE
    ordering = ("sort", "id")


class CustomerGroupViewSet(CatalogViewSet):
    queryset = CustomerGroup.objects.all()
    serializer_class = CustomerGroupSerializer
    ordering = ("name",)


class CategoryViewSet(CatalogViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    ordering = ("sort", "name")

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.GET.get("all") != "1":
            qs = qs.filter(is_active=True)
        branch = current_branch(self.request, required=False)
        if branch and self.request.GET.get("all") != "1":
            qs = qs.filter(Q(branches__isnull=True) | Q(branches=branch)).distinct()
        return qs


class OptionGroupViewSet(CatalogViewSet):
    queryset = OptionGroup.objects.all()
    serializer_class = OptionGroupSerializer
    ordering = ("sort", "id")


class ProductViewSet(CatalogViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    search_fields_simple = ("name", "name_en", "sku", "barcode")
    ordering = ("sort", "name")

    def base_queryset(self):
        return Product.objects.select_related("category", "tax_rate", "category__tax_rate").prefetch_related("option_groups")

    def get_queryset(self):
        qs = super().get_queryset()
        g = self.request.GET
        if g.get("all") != "1":
            qs = qs.filter(is_active=True)
            branch = current_branch(self.request, required=False)
            if branch:
                qs = qs.filter(Q(branches__isnull=True) | Q(branches=branch)).distinct()
        if g.get("category"):
            qs = qs.filter(category_id=g["category"])
        if g.get("favorite") == "1":
            qs = qs.filter(is_favorite=True)
        return qs

    def perform_update(self, serializer):
        serializer.instance._actor = self.request.user
        super().perform_update(serializer)

    @action(detail=False, methods=["get"])
    def menu(self, request):
        """Adisyon ekranı için: kanal fiyatı çözülmüş ürünler + seçenekler + popüler/son kullanılan."""
        branch = current_branch(request)
        channel = request.GET.get("channel", "table")
        products = self.get_queryset()
        data = []
        for p in products:
            d = ProductSerializer(p, context={"request": request}).data
            d["price"] = resolve_price(p, branch=branch, channel=channel)
            d["option_groups_detail"] = OptionGroupSerializer(p.option_groups.all(), many=True).data
            data.append(d)
        from apps.pos.models import TicketLine

        since = timezone.now() - timezone.timedelta(days=30)
        popular = list(TicketLine.objects.filter(ticket__branch=branch, created_at__gte=since).exclude(status="void")
                       .values("product_id").annotate(n=Sum("qty")).order_by("-n").values_list("product_id", flat=True)[:12])
        recent = []
        for pid in (TicketLine.objects.filter(ticket__branch=branch, created_by=request.user)
                    .order_by("-id").values_list("product_id", flat=True)[:60]):
            if pid not in recent:
                recent.append(pid)
            if len(recent) >= 12:
                break
        stock = {}
        try:
            from apps.inventory.services import availability_map

            stock = availability_map(branch, [p.id for p in products])
        except Exception:
            stock = {}
        for d in data:
            d["stock_state"] = stock.get(d["id"], "ok")
        return Response({"products": data, "popular": popular, "recent": recent})

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        p = self.get_object()
        return Response(PriceHistorySerializer(p.price_history.all()[:100], many=True).data)


class ProductPriceViewSet(CatalogViewSet):
    queryset = ProductPrice.objects.all()
    serializer_class = ProductPriceSerializer

    def get_queryset(self):
        qs = super().get_queryset().select_related("product")
        if self.request.GET.get("product"):
            qs = qs.filter(product_id=self.request.GET["product"])
        return qs

    def perform_create(self, serializer):
        obj = serializer.save(business=current_business(self.request))
        from apps.core import audit

        audit.log("price.create", request=self.request, entity="ProductPrice", entity_id=obj.pk, after=obj)


class CampaignViewSet(CatalogViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    ordering = ("-priority", "id")


class CatalogStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.CATALOG_MANAGE

    def get(self, request):
        biz = current_business(request)
        return Response({
            "categories": Category.objects.filter(business=biz, is_active=True).count(),
            "products": Product.objects.filter(business=biz, is_active=True).count(),
            "campaigns": Campaign.objects.filter(business=biz, is_active=True).count(),
            "by_category": list(Category.objects.filter(business=biz, is_active=True)
                                .annotate(n=Count("products", filter=Q(products__is_active=True))).values("name", "n")),
        })
