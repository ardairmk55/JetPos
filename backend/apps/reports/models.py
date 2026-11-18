from datetime import time

from django.db import models

from apps.core.models import Branch, Business, User


class ReportTemplate(models.Model):
    """Kayıtlı rapor şablonu (hazır rapor + filtreler veya özel rapor tanımı)."""

    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    report_type = models.CharField(max_length=30)
    params = models.JSONField(default=dict)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    shared = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReportSchedule(models.Model):
    FREQ = [("daily", "Günlük"), ("weekly", "Haftalık"), ("monthly", "Aylık")]
    FORMATS = [("pdf", "PDF"), ("xlsx", "Excel"), ("csv", "CSV")]
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE)
    name = models.CharField(max_length=120)
    report_type = models.CharField(max_length=30)
    params = models.JSONField(default=dict)
    frequency = models.CharField(max_length=8, choices=FREQ, default="daily")
    send_time = models.TimeField(default=time(8, 0))
    weekday = models.PositiveSmallIntegerField(default=0, help_text="Haftalık için 0=Pazartesi")
    month_day = models.PositiveSmallIntegerField(default=1)
    recipients = models.JSONField(default=list)
    fmt = models.CharField(max_length=5, choices=FORMATS, default="pdf")
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")


class ReportDelivery(models.Model):
    schedule = models.ForeignKey(ReportSchedule, on_delete=models.CASCADE, related_name="deliveries")
    period_key = models.CharField(max_length=20)
    ok = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("schedule", "period_key")]
