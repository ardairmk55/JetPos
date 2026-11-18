from django.db import models

from apps.core.models import Branch, Business, User


# ------------------------------------------------------------------ CRM (§9.1)
class Customer(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, db_index=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    note = models.TextField(blank=True)
    kvkk_consent = models.BooleanField(default=False, help_text="Kişisel veri işleme açık rızası")
    consent_at = models.DateTimeField(null=True, blank=True)
    visit_count = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    last_visit = models.DateTimeField(null=True, blank=True)
    anonymized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CustomerAccountEntry(models.Model):
    """Açık hesap / veresiye cari hareketi. Borç (debit) müşterinin borcunu artırır."""

    KINDS = [("debit", "Borç"), ("credit", "Tahsilat/Alacak")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="account_entries")
    kind = models.CharField(max_length=6, choices=KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    ref = models.CharField(max_length=120, blank=True)
    payment = models.ForeignKey("pos.Payment", null=True, blank=True, on_delete=models.PROTECT)
    method = models.CharField(max_length=15, blank=True, help_text="Tahsilat yöntemi")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


# ------------------------------------------------------------------ Kurye (§9.2)
class Courier(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=40, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Delivery(models.Model):
    STATUS = [("preparing", "Hazırlanıyor"), ("waiting_courier", "Kurye bekliyor"), ("on_the_way", "Dağıtımda"),
              ("delivered", "Teslim edildi"), ("cancelled", "İptal")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    ticket = models.OneToOneField("pos.Ticket", on_delete=models.PROTECT, related_name="delivery")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    contact_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40)
    address = models.TextField()
    courier = models.ForeignKey(Courier, null=True, blank=True, on_delete=models.SET_NULL, related_name="deliveries")
    status = models.CharField(max_length=16, choices=STATUS, default="preparing", db_index=True)
    fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_note = models.CharField(max_length=120, blank=True, help_text="Kapıda nakit/kart vb.")
    promised_minutes = models.PositiveIntegerField(default=45)
    created_at = models.DateTimeField(auto_now_add=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    late_notified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


# ------------------------------------------------------------------ Rezervasyon (§9.3)
class Reservation(models.Model):
    STATUS = [("pending", "Beklemede"), ("confirmed", "Onaylandı"), ("waitlist", "Bekleme listesi"),
              ("seated", "Masaya alındı"), ("completed", "Tamamlandı"), ("cancelled", "İptal"), ("no_show", "Gelmedi")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40)
    starts_at = models.DateTimeField(db_index=True)
    duration_minutes = models.PositiveIntegerField(default=120)
    party_size = models.PositiveSmallIntegerField()
    hall = models.ForeignKey("pos.Hall", null=True, blank=True, on_delete=models.SET_NULL)
    table = models.ForeignKey("pos.Table", null=True, blank=True, on_delete=models.SET_NULL, related_name="reservations")
    status = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    note = models.TextField(blank=True)
    remind_minutes_before = models.PositiveIntegerField(default=60)
    reminded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]


# ------------------------------------------------------------------ Personel (§9.4)
class Shift(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="shifts")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    break_minutes = models.PositiveIntegerField(default=30)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["starts_at"]


class Attendance(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendances")
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.SET_NULL)
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    break_started_at = models.DateTimeField(null=True, blank=True)
    break_minutes = models.PositiveIntegerField(default=0)
    late_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-clock_in"]


class LeaveRequest(models.Model):
    KINDS = [("annual", "Yıllık izin"), ("sick", "Rapor"), ("unpaid", "Ücretsiz"), ("other", "Diğer")]
    STATUS = [("pending", "Bekliyor"), ("approved", "Onaylandı"), ("rejected", "Reddedildi")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="leaves")
    kind = models.CharField(max_length=8, choices=KINDS, default="annual")
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=8, choices=STATUS, default="pending")
    note = models.CharField(max_length=300, blank=True)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-start_date"]


# ------------------------------------------------------------------ Finans
class FinanceAccount(models.Model):
    """Cari hesap (tedarikçi/diğer)."""

    KINDS = [("supplier", "Tedarikçi"), ("customer", "Müşteri"), ("other", "Diğer")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=10, choices=KINDS, default="supplier")
    phone = models.CharField(max_length=40, blank=True)
    note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class FinanceEntry(models.Model):
    """Gelir-gider ve cari borç/alacak kaydı. Silme yerine ters kayıt."""

    KINDS = [("income", "Gelir"), ("expense", "Gider"), ("payable", "Borç (cari)"), ("receivable", "Alacak (cari)"),
             ("settle_payable", "Borç ödemesi"), ("settle_receivable", "Alacak tahsilatı")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=KINDS)
    category = models.CharField(max_length=80, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    description = models.CharField(max_length=300, blank=True)
    account = models.ForeignKey(FinanceAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
