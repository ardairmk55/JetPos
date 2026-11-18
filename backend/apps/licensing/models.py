import uuid

from django.db import models

from apps.core.models import Branch, Business, User

PACKAGES = [("starter", "Starter"), ("professional", "Professional"), ("enterprise", "Enterprise")]
MODULES = [
    ("stock", "Stok/depo"), ("crm", "CRM"), ("delivery", "Kurye"), ("reservation", "Rezervasyon"),
    ("staff", "Personel"), ("finance", "Finans"), ("reports_advanced", "Gelişmiş raporlama"),
    ("jetmenu", "JET Menü entegrasyonu"), ("multi_branch", "Çok şube merkezi yönetim"),
]


class LicenseRecord(models.Model):
    """Platform (merkez) tarafındaki lisans kaydı. Limitler açık karar olduğundan lisansa tek tek yazılır."""

    STATUS = [("active", "Aktif"), ("suspended", "Askıda"), ("revoked", "İptal")]
    license_id = models.UUIDField(default=uuid.uuid4, unique=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="license_records")
    package = models.CharField(max_length=15, choices=PACKAGES)
    modules = models.JSONField(default=list, blank=True)
    max_branches = models.PositiveIntegerField(null=True, blank=True)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    max_terminals = models.PositiveIntegerField(null=True, blank=True)
    max_mobile = models.PositiveIntegerField(null=True, blank=True)
    support_until = models.DateField(null=True, blank=True, help_text="İlk yıl destek/güncelleme dahil")
    version = models.CharField(max_length=20, default="1.x", help_text="Kalıcı kullanım hakkı verilen sürüm")
    activation_key = models.CharField(max_length=40, unique=True)
    status = models.CharField(max_length=10, choices=STATUS, default="active")
    signed_blob = models.TextField(blank=True)
    issued_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    issued_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at"]


class InstalledLicense(models.Model):
    """Şube sunucusunda kurulu, imzası doğrulanmış lisans (offline doğrulama)."""

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="installed_license")
    blob = models.TextField()
    payload = models.JSONField()
    installed_at = models.DateTimeField(auto_now=True)
    installed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")


class BusinessApplication(models.Model):
    """Online başvuru + yönetici onayı (§17.2)."""

    STATUS = [("new", "Yeni"), ("approved", "Onaylandı"), ("rejected", "Reddedildi")]
    business_name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40)
    email = models.EmailField()
    template = models.CharField(max_length=20, default="restaurant")
    branch_count = models.PositiveIntegerField(default=1)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="new")
    business = models.ForeignKey(Business, null=True, blank=True, on_delete=models.SET_NULL)
    decided_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class MaintenanceContract(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="contracts")
    starts_on = models.DateField()
    ends_on = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ends_on"]


class PlatformPayment(models.Model):
    """Platform ticari kayıtları ve ödeme geçmişi (finans yöneticisi)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="platform_payments")
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    reference = models.CharField(max_length=80, blank=True)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on"]


class PlatformConfig(models.Model):
    """Tekil ayar kaydı: SLA ve kayıt saklama süreleri (açık kararlar; platform yöneticisi belirler)."""

    reopen_window_days = models.PositiveIntegerField(null=True, blank=True, help_text="Boş: sınırsız")
    waiting_customer_reminder_hours = models.PositiveIntegerField(default=48)
    action_log_retention_days = models.PositiveIntegerField(default=365)
    session_log_retention_days = models.PositiveIntegerField(default=365)
    recording_retention_days = models.PositiveIntegerField(default=30)
    max_support_session_minutes = models.PositiveIntegerField(default=120)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SLAPolicy(models.Model):
    PRIORITIES = [("critical", "Kritik"), ("high", "Yüksek"), ("normal", "Normal"), ("low", "Düşük")]
    package = models.CharField(max_length=15, choices=PACKAGES)
    priority = models.CharField(max_length=10, choices=PRIORITIES)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()

    class Meta:
        unique_together = [("package", "priority")]


class SupportTicket(models.Model):
    STATUS = [("new", "Yeni"), ("in_review", "İncelemede"), ("waiting_customer", "Yanıt Bekleniyor"),
              ("resolved", "Çözüldü"), ("closed", "Kapalı")]
    CATEGORIES = [("pos", "POS / satış"), ("printer", "Yazıcı"), ("network", "Ağ / bağlantı"), ("payment", "Ödeme"),
                  ("stock", "Stok"), ("report", "Rapor"), ("license", "Lisans"), ("update", "Güncelleme"),
                  ("backup", "Yedek"), ("other", "Diğer")]
    LEVELS = [("low", "Düşük"), ("medium", "Orta"), ("high", "Yüksek")]
    number = models.PositiveIntegerField(unique=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="support_tickets")
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    category = models.CharField(max_length=10, choices=CATEGORIES, default="other")
    subject = models.CharField(max_length=200)
    description = models.TextField()
    business_impact = models.CharField(max_length=6, choices=LEVELS, default="medium")
    urgency = models.CharField(max_length=6, choices=LEVELS, default="medium")
    operation_stopped = models.BooleanField(default=False)
    priority = models.CharField(max_length=10, choices=SLAPolicy.PRIORITIES, default="normal")
    package = models.CharField(max_length=15, choices=PACKAGES, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default="new", db_index=True)
    first_response_due = models.DateTimeField(null=True, blank=True)
    resolution_due = models.DateTimeField(null=True, blank=True)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    paused_seconds = models.PositiveIntegerField(default=0)
    reopen_count = models.PositiveIntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class SupportEvent(models.Model):
    """SLA duraklatma/devam/yeniden açma gibi olayların kaydı."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=30)
    note = models.CharField(max_length=300, blank=True)
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SupportMessage(models.Model):
    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    internal = models.BooleanField(default=False, help_text="Yalnızca destek ekibi görür")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class SupportAttachment(models.Model):
    """Şifreli saklanan dosya; indirmeler loglanır (§15.3)."""

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    filename = models.CharField(max_length=200)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    path = models.CharField(max_length=300)
    kind = models.CharField(max_length=12, default="file", help_text="file / screenshot / recording")
    created_at = models.DateTimeField(auto_now_add=True)
    purged_at = models.DateTimeField(null=True, blank=True)


class SupportAccessGrant(models.Model):
    """Müşteri onaylı, süre ve işlem sınırlı teknik destek erişimi (§15.3)."""

    SCOPES = [("read", "Görüntüleme"), ("settings", "Ayarlar"), ("catalog", "Katalog"), ("printers", "Yazıcı"),
              ("ops", "Yedek/sağlık")]
    grant_id = models.UUIDField(default=uuid.uuid4, unique=True)
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="support_grants")
    ticket = models.ForeignKey(SupportTicket, null=True, blank=True, on_delete=models.SET_NULL)
    support_user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="support_grants")
    granted_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    scopes = models.JSONField(default=list)
    data_access = models.CharField(max_length=12, choices=[("anonymized", "Anonim"), ("full", "Tam (ek onay)")],
                                   default="anonymized")
    recording_consent = models.BooleanField(default=False)
    reason = models.CharField(max_length=300)
    starts_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    @property
    def is_active(self):
        from django.utils import timezone

        return self.revoked_at is None and self.ended_at is None and self.expires_at > timezone.now()


class SupportActionLog(models.Model):
    grant = models.ForeignKey(SupportAccessGrant, on_delete=models.CASCADE, related_name="actions")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    status_code = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ReleaseNote(models.Model):
    version = models.CharField(max_length=20)
    title = models.CharField(max_length=200)
    body = models.TextField()
    published_at = models.DateField()

    class Meta:
        ordering = ["-published_at"]
