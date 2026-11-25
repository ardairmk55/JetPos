from django.db import models

from apps.catalog.models import Category, Station
from apps.core.models import Branch, Business


class Printer(models.Model):
    CONNECTIONS = [("network", "Ethernet / Wi-Fi (TCP 9100)"), ("windows", "Windows yazıcı (USB/sürücü)"),
                   ("file", "Dosyaya yaz (sanal/test)")]
    TARGETS = [("cashier", "Kasa"), ("kitchen", "Mutfak/istasyon"), ("bar", "İçecek"), ("dessert", "Tatlı"),
               ("other", "Diğer")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="printers")
    name = models.CharField(max_length=80)
    model_name = models.CharField(max_length=80, blank=True, help_text="Ör. Epson TM-T20 — uyumluluk ayrıca test edilmeli")
    connection = models.CharField(max_length=10, choices=CONNECTIONS, default="network")
    address = models.CharField(max_length=200, blank=True, help_text="IP adresi veya Windows yazıcı adı")
    via_agent = models.BooleanField(default=False, help_text="Restoran bilgisayarındaki yazıcı köprüsü basar")
    port = models.PositiveIntegerField(default=9100)
    width_mm = models.PositiveSmallIntegerField(choices=[(58, "58 mm"), (80, "80 mm")], default=80)
    codepage = models.CharField(max_length=10, default="cp857")
    escpos_codepage_id = models.PositiveSmallIntegerField(default=13, help_text="ESC t n (Epson: PC857=13)")
    target = models.CharField(max_length=10, choices=TARGETS, default="kitchen")
    stations = models.ManyToManyField(Station, blank=True)
    categories = models.ManyToManyField(Category, blank=True)
    print_receipts = models.BooleanField(default=False, help_text="Hesap/ödeme fişlerini bas")
    backup = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    header = models.TextField(blank=True)
    footer = models.TextField(blank=True)
    cut = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    last_error = models.TextField(blank=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def columns(self):
        return 32 if self.width_mm == 58 else 48


class PrintJob(models.Model):
    STATUS = [("queued", "Kuyrukta"), ("printing", "Basılıyor"), ("done", "Basıldı"), ("failed", "Başarısız")]
    KINDS = [("kitchen", "Mutfak siparişi"), ("void", "İptal fişi"), ("bill", "Hesap"), ("receipt", "Ödeme fişi"),
             ("test", "Test"), ("report", "Rapor")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    printer = models.ForeignKey(Printer, on_delete=models.CASCADE, related_name="jobs")
    printed_on = models.ForeignKey(Printer, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=10, choices=KINDS)
    title = models.CharField(max_length=120)
    content = models.JSONField(help_text="Satır listesi: {text, bold, size, align}")
    status = models.CharField(max_length=10, choices=STATUS, default="queued", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    ref = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    queued_at = models.DateTimeField(null=True, blank=True, help_text="Elle tekrar denemede yenilenir")
    started_at = models.DateTimeField(null=True, blank=True, help_text="Son baskı denemesinin başlangıcı")
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PrintAgent(models.Model):
    """Şubedeki yazıcı köprüsü. Anahtar yalnızca özet (SHA-256) olarak saklanır."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.OneToOneField(Branch, on_delete=models.CASCADE, related_name="print_agent")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
