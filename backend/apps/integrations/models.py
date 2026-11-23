import secrets

from django.db import models

from apps.core.models import Branch, Business


def _token():
    return secrets.token_urlsafe(32)


class IntegrationConfig(models.Model):
    """JET Menü bağlantısı. JET Menü mevcut API'si doğrulanmadığından (açık karar §11) POSHANE kendi uçlarını sunar;
    giden değişiklikler yapılandırılan webhook'a HMAC imzalı gönderilir."""

    business = models.OneToOneField(Business, on_delete=models.CASCADE, related_name="jetmenu")
    enabled = models.BooleanField(default=False)
    inbound_token = models.CharField(max_length=64, default=_token, unique=True)
    webhook_url = models.URLField(blank=True)
    signing_secret = models.CharField(max_length=64, default=_token)
    qr_url_template = models.CharField(max_length=300, blank=True,
                                       help_text="Masa QR içeriği; {token} ve {branch} yer tutucuları. Boşsa yalnızca masa kimliği kodlanır.")
    auto_accept_qr = models.BooleanField(default=False, help_text="Kapalıysa QR siparişleri garson onayına düşer")
    last_push_at = models.DateTimeField(null=True, blank=True)


class OutboxMessage(models.Model):
    STATUS = [("pending", "Bekliyor"), ("sent", "Gönderildi"), ("failed", "Başarısız")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    kind = models.CharField(max_length=40)
    payload = models.JSONField()
    status = models.CharField(max_length=8, choices=STATUS, default="pending", db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class QrOrder(models.Model):
    STATUS = [("received", "Alındı - onay bekliyor"), ("accepted", "Adisyona eklendi"), ("rejected", "Reddedildi")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    table = models.ForeignKey("pos.Table", on_delete=models.PROTECT)
    ticket = models.ForeignKey("pos.Ticket", null=True, blank=True, on_delete=models.SET_NULL)
    external_id = models.CharField(max_length=80)
    items = models.JSONField()
    note = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="received", db_index=True)
    error = models.CharField(max_length=300, blank=True)
    decided_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["business", "external_id"], name="uniq_qr_order")]
