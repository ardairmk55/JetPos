import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.catalog.models import CHANNELS, CustomerGroup, Product, Station
from apps.core.models import Branch, Business, User

ACTIVE_TICKET_STATES = ("open", "bill_requested", "paid")


class Hall(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="halls")
    name = models.CharField(max_length=80)
    sort = models.PositiveIntegerField(default=0)
    width = models.PositiveIntegerField(default=1000)
    height = models.PositiveIntegerField(default=700)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name


class Table(models.Model):
    SHAPES = [("square", "Kare"), ("round", "Yuvarlak"), ("rect", "Dikdörtgen")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="tables")
    hall = models.ForeignKey(Hall, on_delete=models.CASCADE, related_name="tables")
    name = models.CharField(max_length=30)
    seats = models.PositiveSmallIntegerField(default=4)
    shape = models.CharField(max_length=6, choices=SHAPES, default="square")
    x = models.IntegerField(default=20)
    y = models.IntegerField(default=20)
    w = models.PositiveIntegerField(default=110)
    h = models.PositiveIntegerField(default=110)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="merged_tables")
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["hall__sort", "name"]

    def __str__(self):
        return self.name


class DailyCounter(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    date = models.DateField()
    name = models.CharField(max_length=20)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("branch", "date", "name")]


class Ticket(models.Model):
    """Adisyon. Bir masada aynı anda yalnızca bir aktif adisyon (§5.2) — DB kısıtıyla zorunlu."""

    STATUS = [("open", "Açık"), ("bill_requested", "Hesap istendi"), ("paid", "Ödendi"),
              ("closed", "Kapandı"), ("cancelled", "İptal")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="tickets")
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.PROTECT, related_name="tickets")
    channel = models.CharField(max_length=10, choices=CHANNELS, default="table")
    number = models.PositiveIntegerField()
    business_date = models.DateField()
    status = models.CharField(max_length=15, choices=STATUS, default="open", db_index=True)
    waiter = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="tickets")
    customer = models.ForeignKey("modules.Customer", null=True, blank=True, on_delete=models.SET_NULL)
    customer_group = models.ForeignKey(CustomerGroup, null=True, blank=True, on_delete=models.SET_NULL)
    guest_count = models.PositiveSmallIntegerField(default=1)
    note = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    campaign_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    opened_at = models.DateTimeField(auto_now_add=True)
    bill_requested_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reservation = models.ForeignKey("modules.Reservation", null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=10, default="pos", help_text="pos / qr / jetmenu")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(fields=["table"], condition=Q(status__in=ACTIVE_TICKET_STATES),
                                    name="one_active_ticket_per_table"),
        ]

    def __str__(self):
        return f"#{self.number}"

    @property
    def remaining(self):
        return max(Decimal("0.00"), self.total - self.paid_total)

    @property
    def is_active(self):
        return self.status in ACTIVE_TICKET_STATES


class KitchenBatch(models.Model):
    """Mutfağa gönderilen sipariş partisi. Sonradan eklenenler yeni parti olur (§5.4)."""

    STATUS = [("pending", "Hazırlanıyor"), ("ready", "Hazır"), ("picked_up", "Teslim alındı")]
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="batches")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    sent_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    sent_at = models.DateTimeField(auto_now_add=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    picked_up_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["sent_at"]
        unique_together = [("ticket", "number")]


class KitchenOrder(models.Model):
    """Bir partinin bir istasyona düşen kısmı (çok istasyonlu yönlendirme §7.1)."""

    STATUS = [("new", "Yeni"), ("preparing", "Hazırlanıyor"), ("ready", "Hazır")]
    batch = models.ForeignKey(KitchenBatch, on_delete=models.CASCADE, related_name="orders")
    station = models.ForeignKey(Station, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS, default="new", db_index=True)
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    ready_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-priority", "created_at"]
        unique_together = [("batch", "station")]


class TicketLine(models.Model):
    STATUS = [("draft", "Taslak"), ("sent", "Gönderildi"), ("void", "İptal")]
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    qty = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Seçenekler dahil satış anı fiyatı")
    options = models.JSONField(default=list, blank=True)
    note = models.CharField(max_length=300, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_included = models.BooleanField(default=True)
    station = models.ForeignKey(Station, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=6, choices=STATUS, default="draft", db_index=True)
    batch = models.ForeignKey(KitchenBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="lines")
    campaign_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    campaign_name = models.CharField(max_length=120, blank=True)
    net_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="İndirimler sonrası tahsil edilecek")
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    seat = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Ürün bazlı kişi ataması")
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    voided_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="void_parts")
    void_reason = models.CharField(max_length=300, blank=True)
    voided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    voided_at = models.DateTimeField(null=True, blank=True)
    client_uid = models.CharField(max_length=64, blank=True, db_index=True, help_text="Offline cihaz satır kimliği")

    class Meta:
        ordering = ["id"]

    @property
    def gross(self):
        return (self.unit_price * self.qty).quantize(Decimal("0.01"))


class TicketDiscount(models.Model):
    KINDS = [("percent", "Yüzde"), ("fixed", "Sabit"), ("group", "Müşteri grubu")]
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="discounts")
    kind = models.CharField(max_length=8, choices=KINDS)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reason = models.CharField(max_length=300)
    customer_group = models.ForeignKey(CustomerGroup, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reverse_reason = models.CharField(max_length=300, blank=True)


class ApprovalRequest(models.Model):
    """Yönetici/kasiyer onayı bekleyen işlem (§2.1, §6.2)."""

    KINDS = [("discount", "İndirim"), ("void", "Ürün iptali"), ("group", "Müşteri grubu indirimi"),
             ("refund", "İade"), ("price", "Fiyat değişikliği")]
    STATUS = [("pending", "Bekliyor"), ("approved", "Onaylandı"), ("rejected", "Reddedildi")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.CASCADE, related_name="approvals")
    kind = models.CharField(max_length=10, choices=KINDS)
    payload = models.JSONField(default=dict)
    reason = models.CharField(max_length=300)
    required_perm = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


PAYMENT_METHODS = [("cash", "Nakit"), ("card", "Banka/kredi kartı"), ("meal_card", "Yemek kartı"),
                   ("open_account", "Açık hesap / veresiye")]


class CashDay(models.Model):
    """İşletme (şube) başına günlük tek kasa çekmecesi (§6.3)."""

    STATUS = [("open", "Açık"), ("pending_approval", "Onay bekliyor"), ("closed", "Kapandı")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    business_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS, default="open", db_index=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2)
    opened_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    difference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    difference_reason = models.CharField(max_length=300, blank=True)
    counted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    counted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    report = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-business_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["branch"], condition=Q(status__in=("open", "pending_approval")),
                                    name="one_open_cash_day_per_branch"),
            models.UniqueConstraint(fields=["branch", "business_date"], name="one_cash_day_per_date"),
        ]


class Payment(models.Model):
    STATUS = [("completed", "Tamamlandı"), ("partially_refunded", "Kısmi iade"), ("refunded", "İade edildi")]
    SPLIT = [("full", "Tam"), ("partial", "Kısmi / özel tutar"), ("equal", "Eşit bölme"), ("items", "Ürün bazlı")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="payments")
    cash_day = models.ForeignKey(CashDay, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=15, choices=PAYMENT_METHODS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    change = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refunded_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    split_mode = models.CharField(max_length=8, choices=SPLIT, default="full")
    customer = models.ForeignKey("modules.Customer", null=True, blank=True, on_delete=models.PROTECT)
    reference = models.CharField(max_length=80, blank=True, help_text="POS slip / provizyon no")
    status = models.CharField(max_length=20, choices=STATUS, default="completed")
    txn_id = models.UUIDField(default=uuid.uuid4, unique=True)
    idempotency_key = models.CharField(max_length=100, blank=True)
    device = models.CharField(max_length=120, blank=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="allocations")
    line = models.ForeignKey(TicketLine, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=12, decimal_places=2)


class Refund(models.Model):
    """İade: silme yerine ters kayıt (§6.2)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    cash_day = models.ForeignKey(CashDay, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=15, choices=PAYMENT_METHODS)
    reason = models.CharField(max_length=300)
    line_ids = models.JSONField(default=list, blank=True)
    restock = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name="+")
    ticket_total_before = models.DecimalField(max_digits=12, decimal_places=2)
    ticket_paid_before = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)


class CashMovement(models.Model):
    KINDS = [("sale", "Nakit satış"), ("refund", "Nakit iade"), ("expense", "Gider"), ("withdrawal", "Kasadan çıkış"),
             ("deposit", "Kasaya giriş")]
    cash_day = models.ForeignKey(CashDay, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Kasaya giriş +, çıkış -")
    reason = models.CharField(max_length=300, blank=True)
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT)
    refund = models.ForeignKey(Refund, null=True, blank=True, on_delete=models.PROTECT)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
