import uuid
from decimal import Decimal

from django.db import models

from apps.core.models import Branch, Business

CHANNELS = [("table", "Masa"), ("delivery", "Teslimat"), ("takeaway", "Gel-al"), ("qr", "QR")]


class TaxRate(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=60)
    rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Yüzde, ör. 10.00")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} %{self.rate}"


class Station(models.Model):
    """KDS istasyonu: ana mutfak, içecek, tatlı vb. (§7.1)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    sort = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CustomerGroup(models.Model):
    """Müşteri grubu: belediye personeli vb. (§6.2)."""

    APPROVER = [("cashier", "Kasiyer onayı"), ("manager", "Yönetici onayı")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    discount_type = models.CharField(max_length=10, choices=[("percent", "Yüzde"), ("fixed", "Sabit")], default="percent")
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_discount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    approver = models.CharField(max_length=10, choices=APPROVER, default="cashier")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    tax_rate = models.ForeignKey(TaxRate, null=True, blank=True, on_delete=models.SET_NULL)
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL)
    color = models.CharField(max_length=9, blank=True)
    sort = models.PositiveIntegerField(default=0)
    branches = models.ManyToManyField(Branch, blank=True, help_text="Boş ise tüm şubeler")
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name


class OptionGroup(models.Model):
    KINDS = [("size", "Boyut"), ("cooking", "Pişirme"), ("sauce", "Sos"), ("extra", "Ekstra"), ("side", "Ek ürün"),
             ("other", "Diğer")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=KINDS, default="extra")
    required = models.BooleanField(default=False)
    min_select = models.PositiveSmallIntegerField(default=0)
    max_select = models.PositiveSmallIntegerField(default=1)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class Option(models.Model):
    group = models.ForeignKey(OptionGroup, on_delete=models.CASCADE, related_name="options")
    name = models.CharField(max_length=80)
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class Product(models.Model):
    STOCK_POLICY = [("inherit", "Şube ayarı"), ("warn", "Uyar"), ("block", "Engelle")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=40, blank=True)
    barcode = models.CharField(max_length=40, blank=True)
    image = models.ImageField(upload_to="products/", null=True, blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_rate = models.ForeignKey(TaxRate, null=True, blank=True, on_delete=models.SET_NULL)
    tax_included = models.BooleanField(default=True)
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL)
    option_groups = models.ManyToManyField(OptionGroup, blank=True)
    branches = models.ManyToManyField(Branch, blank=True, help_text="Boş ise tüm şubeler")
    is_favorite = models.BooleanField(default=False)
    stock_policy = models.CharField(max_length=8, choices=STOCK_POLICY, default="inherit")
    sort = models.PositiveIntegerField(default=0)
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, help_text="Ortak ürün kimliği (JET Menü)")
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name

    def effective_tax(self):
        tr = self.tax_rate or self.category.tax_rate
        return tr.rate if tr else Decimal("0")

    def effective_station(self):
        return self.station or self.category.station


class ProductPrice(models.Model):
    """Kanal/şube/müşteri grubu bazlı ve zamanlanmış fiyat (§6.4)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="prices")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=CHANNELS, blank=True)
    customer_group = models.ForeignKey(CustomerGroup, null=True, blank=True, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)


class PriceHistory(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="price_history")
    scope = models.CharField(max_length=120, default="base")
    old_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    new_price = models.DecimalField(max_digits=10, decimal_places=2)
    user = models.ForeignKey("core.User", null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Campaign(models.Model):
    """Kampanya kuralları (§6.4). Deterministik; AI yok."""

    KINDS = [
        ("percent", "Yüzde indirim"),
        ("fixed", "Sabit indirim (birim başına)"),
        ("buy_x_get_y", "X al Y bedava / ikinci ürün"),
        ("bundle_price", "Combo / menü paketi sabit fiyat"),
    ]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=15, choices=KINDS)
    value = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                help_text="percent: yüzde; fixed: TL; buy_x_get_y: bedava üründe indirim yüzdesi; bundle_price: paket fiyatı")
    buy_qty = models.PositiveIntegerField(default=1)
    get_qty = models.PositiveIntegerField(default=1)
    products = models.ManyToManyField(Product, blank=True)
    categories = models.ManyToManyField(Category, blank=True)
    branches = models.ManyToManyField(Branch, blank=True)
    customer_groups = models.ManyToManyField(CustomerGroup, blank=True)
    channels = models.JSONField(default=list, blank=True)
    weekdays = models.JSONField(default=list, blank=True, help_text="0=Pazartesi ... 6=Pazar; boş = her gün")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    priority = models.IntegerField(default=0, help_text="Çakışmada büyük öncelik kazanır")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name
