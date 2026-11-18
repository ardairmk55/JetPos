import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.db import models
from django.utils import timezone

from . import roles

BUSINESS_TEMPLATES = [
    ("restaurant", "Restoran"),
    ("cafe", "Kafe"),
    ("breakfast", "Kahvaltı salonu"),
    ("municipal", "Belediye sosyal tesisi"),
    ("other", "Diğer"),
]


class Business(models.Model):
    """Tenant: ayrı veri alanına sahip müşteri/işletme (§12)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    template = models.CharField(max_length=20, choices=BUSINESS_TEMPLATES, default="restaurant")
    tax_office = models.CharField(max_length=120, blank=True)
    tax_number = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    is_corporate = models.BooleanField(default=False, help_text="Kurumsal/belediye müşterisi (manuel kayıt)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Branch(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("business", "code")]

    def __str__(self):
        return f"{self.business.name} / {self.name}"

    @property
    def settings(self):
        obj, _ = BranchSettings.objects.get_or_create(branch=self)
        return obj


class BranchSettings(models.Model):
    STOCK_DEDUCT = [("send", "Mutfağa gönderimde"), ("prep", "Hazırlık başlangıcında"), ("payment", "Ödemede")]
    STOCK_POLICY = [("warn", "Uyar, satışa izin ver"), ("block", "Satışı engelle")]

    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name="branch_settings")
    auto_close_on_payment = models.BooleanField(default=False, help_text="Tam ödemede adisyonu otomatik kapat (§5.5)")
    stock_deduction = models.CharField(max_length=10, choices=STOCK_DEDUCT, default="send")
    out_of_stock_policy = models.CharField(max_length=10, choices=STOCK_POLICY, default="warn")
    late_order_minutes = models.PositiveIntegerField(default=15)
    inactivity_lock_minutes = models.PositiveIntegerField(default=5)
    max_failed_logins = models.PositiveIntegerField(default=5)
    lockout_minutes = models.PositiveIntegerField(default=15)
    max_discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=100)
    confirm_first_send = models.BooleanField(default=True)
    receipt_header = models.TextField(blank=True)
    receipt_footer = models.TextField(blank=True, default="Bu belge mali değeri olmayan bilgi fişidir.")
    default_channel = models.CharField(max_length=20, default="table")

    def __str__(self):
        return f"Ayarlar: {self.branch}"


class User(AbstractUser):
    LANGS = [("tr", "Türkçe"), ("en", "English")]
    THEMES = [("light", "Açık"), ("dark", "Koyu")]

    business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.CASCADE, related_name="users")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")
    role = models.CharField(max_length=20, choices=roles.ROLE_CHOICES, default=roles.WAITER)
    pin_hash = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    department = models.CharField(max_length=80, blank=True)
    language = models.CharField(max_length=2, choices=LANGS, default="tr")
    theme = models.CharField(max_length=5, choices=THEMES, default="light")
    font_scale = models.PositiveSmallIntegerField(default=100)
    high_contrast = models.BooleanField(default=False)
    failed_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    two_factor_secret = models.CharField(max_length=64, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    def set_pin(self, pin):
        pin = str(pin)
        if not pin.isdigit() or not 4 <= len(pin) <= 8:
            raise ValueError("PIN 4-8 haneli rakam olmalı")
        self.pin_hash = make_password(pin)

    def check_pin(self, pin):
        return bool(self.pin_hash) and check_password(str(pin), self.pin_hash)

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def is_platform(self):
        return self.role in roles.PLATFORM_ROLES

    def deactivate(self):
        """İşten ayrılan personel: hesap silinmez, devre dışı bırakılır (§9.4)."""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=["is_active", "deactivated_at"])


class LoginAttempt(models.Model):
    username = models.CharField(max_length=150)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    method = models.CharField(max_length=10, default="password")
    success = models.BooleanField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AuditLog(models.Model):
    """Değiştirilemez denetim izi (§15.2, NFR-04). Düzeltme ters kayıtla yapılır."""

    business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.PROTECT)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.PROTECT)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=60, db_index=True)
    entity = models.CharField(max_length=60, blank=True)
    entity_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    device = models.CharField(max_length=120, blank=True)
    support_session = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionDenied("Audit kaydı değiştirilemez")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionDenied("Audit kaydı silinemez")


class IdempotencyRecord(models.Model):
    """Aynı isteğin tekrarında işlemin ikinci kez oluşmaması (NFR-02, §14)."""

    business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.CASCADE)
    key = models.CharField(max_length=100)
    scope = models.CharField(max_length=80)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    device = models.CharField(max_length=120, blank=True)
    status_code = models.PositiveSmallIntegerField(default=200)
    response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["business", "scope", "key"], name="uniq_idempotency")]


class Device(models.Model):
    KINDS = [("terminal", "Sabit terminal"), ("mobile", "Mobil personel cihazı"), ("kds", "Mutfak ekranı")]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="devices")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KINDS, default="terminal")
    fingerprint = models.CharField(max_length=128)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    activated_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["business", "fingerprint"], condition=models.Q(is_active=True), name="uniq_active_device"
            )
        ]


class Notification(models.Model):
    PRIORITIES = [("low", "Düşük"), ("medium", "Orta"), ("high", "Yüksek")]

    business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    event = models.CharField(max_length=60)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    priority = models.CharField(max_length=6, choices=PRIORITIES, default="low")
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class NotificationRule(models.Model):
    """Rol/olay/öncelik bazlı bildirim kanalı yapılandırması (§10.2)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    event = models.CharField(max_length=60)
    role = models.CharField(max_length=20, choices=roles.ROLE_CHOICES)
    priority = models.CharField(max_length=6, choices=Notification.PRIORITIES, default="medium")
    in_app = models.BooleanField(default=True)
    sound = models.BooleanField(default=False)
    email = models.BooleanField(default=False)
    push = models.BooleanField(default=False)

    class Meta:
        unique_together = [("business", "event", "role")]


class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class SyncEvent(models.Model):
    """Şube → merkez senkronizasyon çıkış kuyruğu (§12, §14). Değişmez olay."""

    STATUS = [("pending", "Bekliyor"), ("sent", "Gönderildi"), ("failed", "Başarısız")]

    event_id = models.UUIDField(default=uuid.uuid4, unique=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.CASCADE)
    kind = models.CharField(max_length=60)
    payload = models.JSONField()
    node_id = models.CharField(max_length=60, blank=True)
    device = models.CharField(max_length=120, blank=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=STATUS, default="pending", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class CentralInbox(models.Model):
    """Merkez tarafında alınan şube olayları (idempotent)."""

    event_id = models.UUIDField(unique=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch_code = models.CharField(max_length=30, blank=True)
    kind = models.CharField(max_length=60)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
