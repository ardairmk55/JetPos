from datetime import time

from django.db import models

from apps.core.models import User


class BackupPolicy(models.Model):
    """Saklama politikası (RPO/RTO ve varsayılan süreler açık karardır; değerler yönetici tarafından ayarlanır)."""

    enabled = models.BooleanField(default=True)
    daily_time = models.TimeField(default=time(3, 0))
    keep_daily = models.PositiveIntegerField(default=7)
    keep_weekly = models.PositiveIntegerField(default=4)
    keep_monthly = models.PositiveIntegerField(default=12)
    restore_test_days = models.PositiveIntegerField(default=7, help_text="Otomatik geri yükleme testi sıklığı (gün)")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class BackupRecord(models.Model):
    KINDS = [("daily", "Günlük"), ("weekly", "Haftalık"), ("monthly", "Aylık"), ("manual", "Manuel"),
             ("pre_update", "Güncelleme öncesi"), ("pre_restore", "Geri yükleme öncesi")]
    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=12, choices=KINDS)
    path = models.CharField(max_length=400)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=10, default="ok")
    error = models.TextField(blank=True)
    critical = models.BooleanField(default=False, help_text="Kritik yedek: otomatik temizlikten korunur")
    mirrors = models.JSONField(default=list, blank=True)
    cloud_status = models.CharField(max_length=20, default="not_configured")
    verified_at = models.DateTimeField(null=True, blank=True)
    verify_ok = models.BooleanField(null=True)
    restore_tested_at = models.DateTimeField(null=True, blank=True)
    restore_test_ok = models.BooleanField(null=True)
    restore_test_log = models.TextField(blank=True)
    record_counts = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class HealthSnapshot(models.Model):
    node_id = models.CharField(max_length=60)
    cpu = models.FloatField()
    ram = models.FloatField()
    disk = models.FloatField()
    db_ok = models.BooleanField()
    db_latency_ms = models.FloatField(default=0)
    details = models.JSONField(default=dict)
    alerts = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class UpdateRecord(models.Model):
    STATUS = [("verified", "Doğrulandı"), ("approved", "Onaylandı"), ("applied", "Uygulandı"),
              ("rolled_back", "Geri alındı"), ("failed", "Başarısız"), ("rejected", "Reddedildi")]
    version = models.CharField(max_length=30)
    from_version = models.CharField(max_length=30)
    package_path = models.CharField(max_length=400)
    sha256 = models.CharField(max_length=64)
    signature_ok = models.BooleanField(default=False)
    manifest = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=STATUS, default="verified")
    source = models.CharField(max_length=10, default="upload", help_text="upload / usb / central")
    backup = models.ForeignKey(BackupRecord, null=True, blank=True, on_delete=models.SET_NULL)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    health_ok = models.BooleanField(null=True)
    log = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class WriterLease(models.Model):
    """Tek yazıcı lider kilidi. Fencing token her lider değişiminde artar (split-brain önleme §16.2)."""

    holder = models.CharField(max_length=60)
    token = models.PositiveBigIntegerField(default=1)
    expires_at = models.DateTimeField()
    renewed_at = models.DateTimeField(auto_now=True)


class ServerNode(models.Model):
    ROLES = [("primary", "Ana"), ("standby", "Yedek")]
    MODES = [("none", "Yedeksiz"), ("manual", "Manuel yedek"), ("hot", "Sıcak yedek"), ("auto", "Otomatik geçiş")]
    node_id = models.CharField(max_length=60, unique=True)
    role = models.CharField(max_length=8, choices=ROLES, default="primary")
    redundancy_mode = models.CharField(max_length=8, choices=MODES, default="none")
    address = models.CharField(max_length=120, blank=True)
    last_heartbeat = models.DateTimeField(null=True, blank=True)
    fenced = models.BooleanField(default=False, help_text="Yazma yetkisi izole edildi")
    fenced_at = models.DateTimeField(null=True, blank=True)
    healthy = models.BooleanField(null=True)


class FailoverEvent(models.Model):
    KINDS = [("failover", "Failover"), ("failback", "Failback"), ("fence", "İzolasyon"), ("blocked", "Engellendi")]
    kind = models.CharField(max_length=10, choices=KINDS)
    from_node = models.CharField(max_length=60, blank=True)
    to_node = models.CharField(max_length=60, blank=True)
    decision = models.CharField(max_length=10, default="manual")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ScheduledTaskRun(models.Model):
    name = models.CharField(max_length=60)
    ok = models.BooleanField()
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
