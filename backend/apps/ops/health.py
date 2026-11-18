"""Sağlık/telemetri (§16.3, NFR-08)."""
import shutil
import time

import psutil
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.core import roles
from apps.core.models import Branch, SyncEvent

from .models import BackupRecord, HealthSnapshot

THRESHOLDS = {"cpu": 90.0, "ram": 90.0, "disk": 90.0}


def collect():
    t0 = time.perf_counter()
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    latency = (time.perf_counter() - t0) * 1000
    disk_path = str(settings.DATA_DIR)
    du = shutil.disk_usage(disk_path)
    from apps.printing.models import PrintJob

    last_backup = BackupRecord.objects.filter(status="ok", deleted_at__isnull=True).order_by("-created_at").first()
    net = psutil.net_io_counters()
    details = {
        "disk_free_gb": round(du.free / 1e9, 2),
        "print_queue": PrintJob.objects.filter(status__in=("queued", "printing")).count(),
        "print_failed_24h": PrintJob.objects.filter(status="failed",
                                                    created_at__gte=timezone.now() - timezone.timedelta(hours=24)).count(),
        "sync_pending": SyncEvent.objects.filter(status="pending").count(),
        "sync_failed": SyncEvent.objects.filter(status="failed").count(),
        "last_backup_at": last_backup.created_at.isoformat() if last_backup else None,
        "last_backup_age_h": round((timezone.now() - last_backup.created_at).total_seconds() / 3600, 1) if last_backup else None,
        "net_sent_mb": round(net.bytes_sent / 1e6, 1), "net_recv_mb": round(net.bytes_recv / 1e6, 1),
        "boot_time": psutil.boot_time(),
        "db_engine": connection.vendor,
    }
    data = {"cpu": psutil.cpu_percent(interval=0.2), "ram": psutil.virtual_memory().percent,
            "disk": round(du.used / du.total * 100, 1), "db_ok": db_ok, "db_latency_ms": round(latency, 2),
            "details": details}
    data["alerts"] = evaluate(data)
    return data


def evaluate(d):
    alerts = []
    for k, lim in THRESHOLDS.items():
        if d[k] >= lim:
            alerts.append({"level": "high", "code": f"{k}_high", "message": f"{k.upper()} %{d[k]}"})
    if not d["db_ok"]:
        alerts.append({"level": "critical", "code": "db_down", "message": "Veritabanı yanıt vermiyor"})
    det = d["details"]
    if det["last_backup_age_h"] is None or det["last_backup_age_h"] > 26:
        alerts.append({"level": "medium", "code": "backup_old", "message": "Son 26 saatte başarılı yedek yok"})
    if det["print_failed_24h"]:
        alerts.append({"level": "medium", "code": "print_failed", "message": f"{det['print_failed_24h']} başarısız baskı"})
    if det["sync_failed"]:
        alerts.append({"level": "low", "code": "sync_failed", "message": f"{det['sync_failed']} senkronizasyon hatası"})
    return alerts


def snapshot(notify_alerts=True):
    d = collect()
    snap = HealthSnapshot.objects.create(node_id=settings.JETPOS["NODE_ID"], cpu=d["cpu"], ram=d["ram"], disk=d["disk"],
                                         db_ok=d["db_ok"], db_latency_ms=d["db_latency_ms"], details=d["details"],
                                         alerts=d["alerts"])
    from .models import ServerNode

    ServerNode.objects.update_or_create(node_id=settings.JETPOS["NODE_ID"],
                                        defaults={"healthy": d["db_ok"] and not any(a["level"] == "critical" for a in d["alerts"])})
    if notify_alerts and d["alerts"]:
        from apps.core.notify import notify

        prev = HealthSnapshot.objects.exclude(pk=snap.pk).first()
        prev_codes = {a["code"] for a in (prev.alerts if prev else [])}
        for a in d["alerts"]:
            if a["code"] in prev_codes:
                continue  # aynı uyarıyı tekrar gönderme
            prio = {"critical": "high", "high": "high", "medium": "medium"}.get(a["level"], "low")
            for b in Branch.objects.filter(is_active=True):
                notify(branch=b, event="health_alert", title=f"Sistem uyarısı: {a['message']}", priority=prio,
                       roles=[roles.OWNER, roles.BRANCH_MANAGER])
    # Merkeze gönderilecek sağlık olayı
    for b in Branch.objects.filter(is_active=True)[:1]:
        SyncEvent.objects.create(business=b.business, branch=b, kind="health", node_id=settings.JETPOS["NODE_ID"],
                                 payload={"cpu": d["cpu"], "ram": d["ram"], "disk": d["disk"], "db_ok": d["db_ok"],
                                          "alerts": d["alerts"], "at": timezone.now().isoformat()})
    HealthSnapshot.objects.filter(created_at__lt=timezone.now() - timezone.timedelta(days=30)).delete()
    return snap


def diagnose():
    """Otomatik tanılama: kural tabanlı kontrol listesi (AI yok)."""
    d = collect()
    from apps.printing.models import Printer

    checks = [
        {"name": "Veritabanı bağlantısı", "ok": d["db_ok"], "hint": "Veritabanı servisini kontrol edin"},
        {"name": "Disk doluluk < %90", "ok": d["disk"] < 90, "hint": "Eski yedekleri temizleyin veya disk ekleyin"},
        {"name": "Bellek < %90", "ok": d["ram"] < 90, "hint": "Gereksiz uygulamaları kapatın"},
        {"name": "Son 26 saatte yedek", "ok": not any(a["code"] == "backup_old" for a in d["alerts"]),
         "hint": "Yedekler sayfasından manuel yedek alın"},
        {"name": "Yazdırma kuyruğu temiz", "ok": d["details"]["print_queue"] < 10, "hint": "Yazıcı bağlantılarını test edin"},
    ]
    for p in Printer.objects.filter(is_active=True):
        checks.append({"name": f"Yazıcı: {p.name}", "ok": not p.last_error, "hint": p.last_error or ""})
    return {"metrics": d, "checks": checks}
