from django.db import models

from apps.catalog.models import Product
from apps.core.models import Branch, Business, User

UNITS = [("adet", "Adet"), ("kg", "Kilogram"), ("g", "Gram"), ("lt", "Litre"), ("ml", "Mililitre"), ("porsiyon", "Porsiyon")]


class Warehouse(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="warehouses")
    name = models.CharField(max_length=80)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Supplier(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    tax_number = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class StockItem(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=10, choices=UNITS, default="adet")
    min_level = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=4, default=0, help_text="Birim maliyet (TL)")
    product = models.OneToOneField(Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock_item",
                                   help_text="Doğrudan stoklu ürün (ör. şişe içecek)")
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RecipeLine(models.Model):
    """Reçete / ürün ağacı: bir ürün satıldığında tüketilen malzemeler."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="recipe_lines")
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=10, choices=UNITS)

    class Meta:
        unique_together = [("product", "item")]


class StockLevel(models.Model):
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="levels")
    item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="levels")
    qty = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    class Meta:
        unique_together = [("warehouse", "item")]


class StockMovement(models.Model):
    KINDS = [
        ("sale", "Satış tüketimi"), ("sale_reversal", "Satış ters hareket"), ("purchase", "Satın alma girişi"),
        ("transfer_out", "Transfer çıkış"), ("transfer_in", "Transfer giriş"), ("waste", "Fire"),
        ("count", "Sayım düzeltme"), ("adjust", "Manuel düzeltme"), ("opening", "Açılış stoku"),
    ]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=15, choices=KINDS, db_index=True)
    qty = models.DecimalField(max_digits=14, decimal_places=4, help_text="Giriş +, çıkış -")
    before = models.DecimalField(max_digits=14, decimal_places=4)
    after = models.DecimalField(max_digits=14, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    reason = models.CharField(max_length=300, blank=True)
    ref_type = models.CharField(max_length=30, blank=True)
    ref_id = models.CharField(max_length=40, blank=True)
    user = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class SaleDeduction(models.Model):
    """Reçete tüketiminin bir kez işlenmesini garanti eder (çift stok düşümü engeli §8)."""

    line = models.ForeignKey("pos.TicketLine", on_delete=models.CASCADE, related_name="stock_deductions")
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    line_qty = models.DecimalField(max_digits=8, decimal_places=2)
    qty = models.DecimalField(max_digits=14, decimal_places=4)
    reversed_qty = models.DecimalField(max_digits=14, decimal_places=4, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["line", "item"], name="uniq_sale_deduction")]


class PurchaseReceipt(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT)
    document_no = models.CharField(max_length=60, blank=True)
    note = models.TextField(blank=True)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PurchaseLine(models.Model):
    receipt = models.ForeignKey(PurchaseReceipt, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=14, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=4)


class Transfer(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    source = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="transfers_out")
    target = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="transfers_in")
    note = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class TransferLine(models.Model):
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=14, decimal_places=4)


class StockCount(models.Model):
    STATUS = [("draft", "Taslak"), ("applied", "Uygulandı")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    status = models.CharField(max_length=8, choices=STATUS, default="draft")
    note = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)


class StockCountLine(models.Model):
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT)
    expected = models.DecimalField(max_digits=14, decimal_places=4)
    counted = models.DecimalField(max_digits=14, decimal_places=4)
