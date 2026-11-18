from rest_framework import serializers

from .models import (Campaign, Category, CustomerGroup, Option, OptionGroup, PriceHistory, Product, ProductPrice,
                     Station, TaxRate)


class BizScopedPKField(serializers.PrimaryKeyRelatedField):
    """İlişkili kayıt aynı işletmeye ait olmalı (tenant izolasyonu)."""

    def get_queryset(self):
        qs = super().get_queryset()
        req = self.context.get("request")
        if req is not None and hasattr(qs.model, "business"):
            from apps.core.tenancy import current_business

            qs = qs.filter(business=current_business(req))
        return qs


class TaxRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRate
        exclude = ["business"]


class StationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        exclude = ["business", "branch"]


class CustomerGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        exclude = ["business"]


class CategorySerializer(serializers.ModelSerializer):
    tax_rate = BizScopedPKField(queryset=TaxRate.objects.all(), allow_null=True, required=False)
    station = BizScopedPKField(queryset=Station.objects.all(), allow_null=True, required=False)
    parent = BizScopedPKField(queryset=Category.objects.all(), allow_null=True, required=False)
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        exclude = ["business", "branches"]
        read_only_fields = ["uid"]

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class OptionSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = Option
        exclude = ["group"]


class OptionGroupSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, required=False)

    class Meta:
        model = OptionGroup
        exclude = ["business"]

    def validate(self, data):
        mn, mx = data.get("min_select", 0), data.get("max_select", 1)
        if data.get("required") and mn < 1:
            data["min_select"] = mn = 1
        if mx < mn:
            raise serializers.ValidationError("max_select, min_select'ten küçük olamaz")
        return data

    def _save_options(self, group, options):
        keep = []
        for o in options:
            oid = o.pop("id", None)
            obj = Option.objects.filter(group=group, pk=oid).first() if oid else None
            if obj:
                for k, v in o.items():
                    setattr(obj, k, v)
                obj.save()
            else:
                obj = Option.objects.create(group=group, **o)
            keep.append(obj.id)
        group.options.exclude(id__in=keep).update(is_active=False)

    def create(self, validated):
        options = validated.pop("options", [])
        g = OptionGroup.objects.create(**validated)
        self._save_options(g, options)
        return g

    def update(self, instance, validated):
        options = validated.pop("options", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if options is not None:
            self._save_options(instance, options)
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["options"] = OptionSerializer(instance.options.filter(is_active=True), many=True).data
        return data


class ProductSerializer(serializers.ModelSerializer):
    category = BizScopedPKField(queryset=Category.objects.all())
    tax_rate = BizScopedPKField(queryset=TaxRate.objects.all(), allow_null=True, required=False)
    station = BizScopedPKField(queryset=Station.objects.all(), allow_null=True, required=False)
    option_groups = BizScopedPKField(queryset=OptionGroup.objects.all(), many=True, required=False)
    category_name = serializers.CharField(source="category.name", read_only=True)
    effective_tax = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        exclude = ["business", "branches"]
        read_only_fields = ["uid", "updated_at"]

    def get_image_url(self, obj):
        return obj.image.url if obj.image else ""

    def validate_base_price(self, v):
        if v < 0:
            raise serializers.ValidationError("Fiyat negatif olamaz")
        return v

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["effective_tax"] = instance.effective_tax()
        return data


class ProductPriceSerializer(serializers.ModelSerializer):
    product = BizScopedPKField(queryset=Product.objects.all())
    customer_group = BizScopedPKField(queryset=CustomerGroup.objects.all(), allow_null=True, required=False)
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = ProductPrice
        exclude = ["business"]


class PriceHistorySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", default="", read_only=True)

    class Meta:
        model = PriceHistory
        exclude = ["business"]


class CampaignSerializer(serializers.ModelSerializer):
    products = BizScopedPKField(queryset=Product.objects.all(), many=True, required=False)
    categories = BizScopedPKField(queryset=Category.objects.all(), many=True, required=False)
    customer_groups = BizScopedPKField(queryset=CustomerGroup.objects.all(), many=True, required=False)

    class Meta:
        model = Campaign
        exclude = ["business"]
        read_only_fields = ["used_count"]
