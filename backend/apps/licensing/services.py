"""Lisans, cihaz hakları, destek/SLA ve uzaktan destek erişimi (§15.3, §17, §19)."""
import hashlib
import secrets
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.permissions import BasePermission

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.models import Branch, Device, User
from apps.core.notify import notify

from . import signing
from .models import (InstalledLicense, LicenseRecord, PlatformConfig, SLAPolicy, SupportAccessGrant, SupportEvent,
                     SupportTicket)

CORE_MODULES = {"core"}


# ------------------------------------------------------------------ lisans
def _public_key():
    path = settings.JETPOS["LICENSE_PUBLIC_KEY_FILE"]
    if not path.exists():
        return None
    return signing.load_public(path)


def private_key_path():
    return settings.DATA_DIR / "license_private.pem"


def ensure_platform_keys():
    priv = private_key_path()
    pub = settings.JETPOS["LICENSE_PUBLIC_KEY_FILE"]
    if not priv.exists():
        signing.generate_keypair(priv, pub)
    return priv, pub


def issue_license(*, business, package, modules, user=None, max_branches=None, max_users=None, max_terminals=None,
                  max_mobile=None, support_until=None, version="1.x"):
    """Platform tarafı: lisans kaydı oluşturur ve imzalar (özel anahtar yalnızca platformda bulunur)."""
    from .models import MODULES

    valid = {m for m, _ in MODULES}
    bad = set(modules) - valid
    if bad:
        raise BusinessError(f"Bilinmeyen modül: {', '.join(sorted(bad))}")
    if not private_key_path().exists():
        raise BusinessError("Platform imza anahtarı yok. 'manage.py jetpos_keys' ile oluşturun.", code="no_signing_key")
    rec = LicenseRecord.objects.create(
        business=business, package=package, modules=sorted(set(modules)), max_branches=max_branches,
        max_users=max_users, max_terminals=max_terminals, max_mobile=max_mobile,
        support_until=support_until or (timezone.localdate() + timedelta(days=365)), version=version,
        activation_key="-".join(secrets.token_hex(2).upper() for _ in range(5)), issued_by=user)
    rec.signed_blob = signing.sign_payload(license_payload(rec), signing.load_private(private_key_path()))
    rec.save(update_fields=["signed_blob"])
    audit.log("license.issue", user=user, business=business, entity="LicenseRecord", entity_id=rec.pk,
              after={"package": package, "modules": rec.modules})
    return rec


def license_payload(rec):
    return {
        "license_id": str(rec.license_id), "business_slug": rec.business.slug, "business_name": rec.business.name,
        "package": rec.package, "modules": rec.modules, "max_branches": rec.max_branches, "max_users": rec.max_users,
        "max_terminals": rec.max_terminals, "max_mobile": rec.max_mobile,
        "support_until": str(rec.support_until) if rec.support_until else None, "version": rec.version,
        "issued_at": rec.issued_at.isoformat() if rec.issued_at else timezone.now().isoformat(),
    }


def install_license(business, blob, *, user=None):
    """Şube tarafı: imzalı lisans dosyasını (veya QR'dan okunan metni) yerelde doğrular ve kurar.
    İlk aktivasyondan sonra doğrulama internetsiz yapılır."""
    key = _public_key()
    if key is None:
        raise BusinessError("Lisans doğrulama açık anahtarı kurulu değil", code="no_public_key")
    try:
        payload = signing.verify_blob(blob, key)
    except ValueError as e:
        audit.log("license.install_failed", user=user, business=business, reason=str(e))
        raise BusinessError(str(e), code="license_invalid")
    if payload.get("business_slug") != business.slug:
        raise BusinessError("Lisans bu işletmeye ait değil", code="license_mismatch")
    obj, _ = InstalledLicense.objects.update_or_create(business=business, defaults={
        "blob": blob.strip(), "payload": payload, "installed_by": user})
    settings.JETPOS["LICENSE_FILE"].write_text(blob.strip(), encoding="utf-8")
    LicenseRecord.objects.filter(license_id=payload["license_id"], activated_at__isnull=True).update(
        activated_at=timezone.now())
    audit.log("license.install", user=user, business=business, entity="InstalledLicense", entity_id=obj.pk,
              after={"package": payload["package"], "modules": payload["modules"]})
    return obj


def activate_with_key(business, key, *, user=None):
    """Online anahtar: platform kaydı bu sunucudaysa doğrudan; değilse merkezi URL gerekir (internet)."""
    rec = LicenseRecord.objects.filter(activation_key=key.strip().upper(), status="active").first()
    if rec is None:
        central = settings.JETPOS["CENTRAL_URL"]
        if not central:
            raise BusinessError("Anahtar yerelde bulunamadı ve merkezi platform adresi (JETPOS_CENTRAL_URL) tanımlı değil. "
                                "İmzalı lisans dosyasıyla offline aktivasyon yapın.", code="central_unavailable")
        import json
        import urllib.request

        req = urllib.request.Request(central.rstrip("/") + "/api/platform/licenses/activate",
                                     data=json.dumps({"key": key, "business_slug": business.slug}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                blob = json.loads(r.read())["blob"]
        except Exception as e:
            raise BusinessError(f"Merkezi platforma bağlanılamadı: {e}", code="central_unavailable")
        return install_license(business, blob, user=user)
    if rec.business_id != business.id:
        raise BusinessError("Anahtar bu işletmeye ait değil", code="license_mismatch")
    return install_license(business, rec.signed_blob, user=user)


def current_license(business):
    if business is None:
        return None
    lic = InstalledLicense.objects.filter(business=business).first()
    if lic is None:
        return None
    key = _public_key()
    if key is None:
        return None
    try:
        return signing.verify_blob(lic.blob, key)
    except ValueError:
        return None


def license_status(business):
    p = current_license(business)
    if p is None:
        return {"licensed": False, "package": None, "modules": [], "support_active": False}
    su = p.get("support_until")
    return {"licensed": True, "package": p["package"], "modules": p["modules"], "support_until": su,
            "support_active": bool(su and su >= str(timezone.localdate())), "max_branches": p.get("max_branches"),
            "max_users": p.get("max_users"), "max_terminals": p.get("max_terminals"), "max_mobile": p.get("max_mobile"),
            "license_id": p["license_id"], "version": p.get("version")}


def module_enabled(business, module):
    if module in CORE_MODULES:
        return True
    p = current_license(business)
    return bool(p and module in p.get("modules", []))


class ModuleRequired:
    """View mixin: opsiyonel modül lisansta yoksa 403 (§3 modül sınıfları)."""

    module = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        from apps.core.tenancy import current_business

        if self.module and not module_enabled(current_business(request), self.module):
            raise PermissionDenied(f"'{self.module}' modülü lisansınızda etkin değil")


def check_branch_limit(business):
    p = current_license(business)
    if p and p.get("max_branches") is not None:
        if Branch.objects.filter(business=business, is_active=True).count() >= p["max_branches"]:
            raise BusinessError("Lisanstaki şube hakkı doldu", code="license_limit")


def register_device(*, business, branch, name, kind, fingerprint, user):
    p = current_license(business)
    limit_key = "max_mobile" if kind == "mobile" else "max_terminals"
    existing = Device.objects.filter(business=business, fingerprint=fingerprint, is_active=True).first()
    if existing:
        existing.last_seen = timezone.now()
        existing.save(update_fields=["last_seen"])
        return existing
    if p and p.get(limit_key) is not None:
        kinds = ["mobile"] if kind == "mobile" else ["terminal", "kds"]
        used = Device.objects.filter(business=business, is_active=True, kind__in=kinds).count()
        if used >= p[limit_key]:
            raise BusinessError("Lisanstaki cihaz hakkı doldu. Ek cihaz hakkı veya kontrollü transfer gerekir.",
                                code="device_limit")
    d = Device.objects.create(business=business, branch=branch, name=name[:120], kind=kind,
                              fingerprint=fingerprint[:128], last_seen=timezone.now())
    audit.log("device.register", user=user, business=business, branch=branch, entity="Device", entity_id=d.pk,
              after={"name": d.name, "kind": kind})
    return d


def transfer_device(device, *, new_fingerprint, new_name, user, reason):
    """Donanım değişiminde kontrollü transfer: eski cihaz pasiflenir, hak yenisine geçer."""
    if not reason or len(reason) < 3:
        raise BusinessError("Transfer gerekçesi zorunlu")
    with transaction.atomic():
        device.is_active = False
        device.deactivated_at = timezone.now()
        device.save(update_fields=["is_active", "deactivated_at"])
        new = Device.objects.create(business=device.business, branch=device.branch, name=new_name or device.name,
                                    kind=device.kind, fingerprint=new_fingerprint[:128], last_seen=timezone.now())
        audit.log("device.transfer", user=user, business=device.business, entity="Device", entity_id=new.pk,
                  before={"device": device.pk}, after={"device": new.pk}, reason=reason)
    return new


# ------------------------------------------------------------------ SLA hesapları
WORK_START = time(9, 0)
WORK_END = time(18, 0)


def add_business_minutes(start, minutes):
    """Hafta içi 09.00–18.00 mesaisine göre süre ekler (§19.2)."""
    t = timezone.localtime(start)
    remaining = int(minutes)
    while remaining > 0:
        if t.weekday() >= 5 or t.time() >= WORK_END:
            t = timezone.make_aware(datetime.combine(t.date() + timedelta(days=1), WORK_START), t.tzinfo) \
                if timezone.is_aware(t) else datetime.combine(t.date() + timedelta(days=1), WORK_START)
            continue
        if t.time() < WORK_START:
            t = t.replace(hour=WORK_START.hour, minute=0, second=0, microsecond=0)
        end_today = t.replace(hour=WORK_END.hour, minute=0, second=0, microsecond=0)
        avail = int((end_today - t).total_seconds() // 60)
        step = min(avail, remaining)
        t = t + timedelta(minutes=step)
        remaining -= step
    return t


def compute_priority(ticket, now=None):
    """Akıllı öncelik: iş etkisi, operasyon durması, aciliyet, bekleme süresi. Paket kritik kesintiyi geriye itemez."""
    if ticket.operation_stopped:
        return "critical"
    lvl = {"low": 1, "medium": 2, "high": 3}
    score = lvl[ticket.business_impact] + lvl[ticket.urgency]
    now = now or timezone.now()
    if ticket.created_at and (now - ticket.created_at) > timedelta(hours=24) and ticket.status in ("new", "in_review"):
        score += 1
    if score >= 6:
        return "high"
    if score >= 4:
        return "normal" if score == 4 else "high"
    return "low"


def apply_sla(ticket):
    pol = SLAPolicy.objects.filter(package=ticket.package, priority=ticket.priority).first() if ticket.package else None
    if pol is None:
        ticket.first_response_due = None
        ticket.resolution_due = None
        return ticket
    base = ticket.created_at or timezone.now()
    pause = timedelta(seconds=ticket.paused_seconds)
    if ticket.priority == "critical":
        # Kritik kesinti takvim saatine göre
        ticket.first_response_due = base + timedelta(minutes=pol.first_response_minutes) + pause
        ticket.resolution_due = base + timedelta(minutes=pol.resolution_minutes) + pause
    else:
        ticket.first_response_due = add_business_minutes(base, pol.first_response_minutes) + pause
        ticket.resolution_due = add_business_minutes(base, pol.resolution_minutes) + pause
    return ticket


def create_ticket(*, business, branch, user, data):
    with transaction.atomic():
        num = (SupportTicket.objects.aggregate(m=Max("number"))["m"] or 1000) + 1
        lic = license_status(business)
        t = SupportTicket(number=num, business=business, branch=branch, created_by=user,
                          category=data.get("category", "other"), subject=data["subject"][:200],
                          description=data["description"], business_impact=data.get("business_impact", "medium"),
                          urgency=data.get("urgency", "medium"),
                          operation_stopped=bool(data.get("operation_stopped")), package=lic.get("package") or "")
        t.priority = compute_priority(t)
        t.save()
        apply_sla(t)
        t.save(update_fields=["first_response_due", "resolution_due"])
        SupportEvent.objects.create(ticket=t, kind="created", user=user, note=t.get_priority_display())
    _notify_support(t, f"Yeni destek talebi #{t.number} ({t.get_priority_display()})")
    return t


def _notify_support(t, title):
    for u in User.objects.filter(role__in=[roles.SUPPORT, roles.TECH, roles.PLATFORM_ADMIN], is_active=True):
        from apps.core.models import Notification

        Notification.objects.create(user=u, event="support_ticket", title=title, body=t.subject,
                                    priority="high" if t.priority == "critical" else "medium",
                                    data={"ticket": t.id})


def change_status(t, *, user, status, note=""):
    now = timezone.now()
    if status not in dict(SupportTicket.STATUS):
        raise BusinessError("Geçersiz durum")
    old = t.status
    if old == status:
        return t
    if old == "waiting_customer" and t.paused_at:
        t.paused_seconds += int((now - t.paused_at).total_seconds())
        t.paused_at = None
        SupportEvent.objects.create(ticket=t, kind="sla_resumed", user=user)
    if status == "waiting_customer":
        t.paused_at = now
        SupportEvent.objects.create(ticket=t, kind="sla_paused", user=user, note=note[:300])
    if status == "resolved":
        t.resolved_at = now
    if status == "closed":
        t.closed_at = now
    if user.is_platform and t.first_response_at is None and status != "new":
        t.first_response_at = now
    t.status = status
    apply_sla(t)
    t.save()
    SupportEvent.objects.create(ticket=t, kind=f"status:{status}", user=user, note=note[:300])
    _email_creator(t, f"Destek talebiniz #{t.number}: {t.get_status_display()}", note or t.subject)
    return t


def add_message(t, *, user, body, internal=False):
    from .models import SupportMessage

    if not body.strip():
        raise BusinessError("Mesaj boş olamaz")
    internal = internal and user.is_platform
    m = SupportMessage.objects.create(ticket=t, author=user, body=body, internal=internal)
    if user.is_platform and not internal and t.first_response_at is None:
        t.first_response_at = timezone.now()
        t.save(update_fields=["first_response_at"])
    if not user.is_platform and t.status == "waiting_customer":
        change_status(t, user=user, status="in_review", note="Müşteri yanıtı")
    if user.is_platform and not internal:
        _email_creator(t, f"Destek talebiniz #{t.number} yanıtlandı", body[:500])
    return m


def reopen_ticket(t, *, user, note):
    """Aynı sorun sürüyorsa eski talep yeniden açılır; geçmiş korunur."""
    if t.status not in ("resolved", "closed"):
        raise BusinessError("Yalnızca çözülmüş/kapalı talep yeniden açılabilir")
    cfg = PlatformConfig.get()
    ref = t.closed_at or t.resolved_at
    if cfg.reopen_window_days is not None and ref and timezone.now() - ref > timedelta(days=cfg.reopen_window_days):
        raise BusinessError("Yeniden açma süresi geçti; yeni talep oluşturun", code="reopen_window")
    t.reopen_count += 1
    t.resolved_at = None
    t.closed_at = None
    t.status = "in_review"
    t.save()
    SupportEvent.objects.create(ticket=t, kind="reopened", user=user, note=note[:300])
    _notify_support(t, f"Talep #{t.number} yeniden açıldı")
    return t


def sla_state(t, now=None):
    now = now or timezone.now()
    def state(due, done):
        if due is None:
            return "undefined"
        if done:
            return "met" if done <= due else "breached"
        if t.paused_at:
            return "paused"
        return "breached" if now > due else "running"
    return {"first_response": state(t.first_response_due, t.first_response_at),
            "resolution": state(t.resolution_due, t.resolved_at)}


def send_waiting_reminders(now=None):
    now = now or timezone.now()
    cfg = PlatformConfig.get()
    n = 0
    for t in SupportTicket.objects.filter(status="waiting_customer", paused_at__isnull=False):
        last = t.last_reminder_at or t.paused_at
        if now - last >= timedelta(hours=cfg.waiting_customer_reminder_hours):
            _email_creator(t, f"Talep #{t.number} yanıtınızı bekliyor", t.subject)
            t.last_reminder_at = now
            t.save(update_fields=["last_reminder_at"])
            SupportEvent.objects.create(ticket=t, kind="reminder_sent")
            n += 1
    for t in SupportTicket.objects.exclude(status__in=("resolved", "closed")):
        st = sla_state(t, now)
        if "breached" in st.values() and not t.events.filter(kind="sla_breach_alert").exists():
            _notify_support(t, f"SLA aşıldı: talep #{t.number}")
            SupportEvent.objects.create(ticket=t, kind="sla_breach_alert")
    return n


def _email_creator(t, subject, body):
    if t.created_by.email:
        from django.core.mail import send_mail

        try:
            send_mail(f"[POSHANE Destek] {subject}", body, None, [t.created_by.email])
        except Exception:
            SupportEvent.objects.create(ticket=t, kind="email_failed", note=subject[:300])


# ------------------------------------------------------------------ uzaktan destek erişimi
def grant_support_access(*, business, granted_by, support_user, scopes, minutes, reason, data_access="anonymized",
                         recording_consent=False, ticket=None):
    if granted_by.role not in (roles.OWNER, roles.BRANCH_MANAGER) or granted_by.business_id != business.id:
        raise BusinessError("Destek erişimini yalnızca işletme sahibi/yöneticisi onaylayabilir", status_code=403)
    if support_user.role not in (roles.SUPPORT, roles.TECH):
        raise BusinessError("Seçilen kullanıcı destek personeli değil")
    cfg = PlatformConfig.get()
    minutes = int(minutes)
    if minutes < 5 or minutes > cfg.max_support_session_minutes:
        raise BusinessError(f"Süre 5–{cfg.max_support_session_minutes} dakika olmalı")
    valid = {s for s, _ in SupportAccessGrant.SCOPES}
    if not scopes or set(scopes) - valid:
        raise BusinessError("Geçersiz yetki kapsamı")
    if not reason or len(reason.strip()) < 3:
        raise BusinessError("Gerekçe zorunlu")
    g = SupportAccessGrant.objects.create(business=business, granted_by=granted_by, support_user=support_user,
                                          scopes=sorted(set(scopes)), data_access=data_access,
                                          recording_consent=bool(recording_consent), reason=reason.strip()[:300],
                                          ticket=ticket, expires_at=timezone.now() + timedelta(minutes=minutes))
    audit.log("support.grant", user=granted_by, business=business, entity="SupportAccessGrant", entity_id=g.pk,
              after={"support_user": support_user.username, "scopes": g.scopes, "minutes": minutes,
                     "data_access": data_access, "recording": g.recording_consent})
    return g


def revoke_support_access(g, *, user):
    if user.business_id != g.business_id and not user.is_platform:
        raise BusinessError("Yetkiniz yok", status_code=403)
    if g.revoked_at is None:
        g.revoked_at = timezone.now()
        g.revoked_by = user
        g.save(update_fields=["revoked_at", "revoked_by"])
        audit.log("support.revoke", user=user, business=g.business, entity="SupportAccessGrant", entity_id=g.pk)
    return g


SCOPE_PATHS = {
    "settings": ("/api/branch-settings", "/api/business", "/api/notification-rules"),
    "catalog": ("/api/categories", "/api/products", "/api/option-groups", "/api/tax-rates", "/api/stations",
                "/api/product-prices", "/api/campaigns"),
    "printers": ("/api/printers", "/api/print-jobs"),
    "ops": ("/api/ops/",),
}


def scope_allows(grant, method, path):
    if method in ("GET", "HEAD", "OPTIONS"):
        return "read" in grant.scopes or any(path.startswith(p) for s in grant.scopes for p in SCOPE_PATHS.get(s, ()))
    return any(path.startswith(p) for s in grant.scopes for p in SCOPE_PATHS.get(s, ()))


def purge_support_records(now=None):
    """Kayıtlar süre sonunda güvenli imha (§19.3)."""
    from pathlib import Path

    from .models import SupportActionLog, SupportAttachment

    now = now or timezone.now()
    cfg = PlatformConfig.get()
    n = SupportActionLog.objects.filter(created_at__lt=now - timedelta(days=cfg.action_log_retention_days)).delete()[0]
    for kind, days in (("recording", cfg.recording_retention_days), ("screenshot", cfg.session_log_retention_days),
                       ("file", cfg.session_log_retention_days)):
        for a in SupportAttachment.objects.filter(kind=kind, purged_at__isnull=True,
                                                  created_at__lt=now - timedelta(days=days)):
            p = Path(a.path)
            if p.exists():
                size = p.stat().st_size
                with open(p, "r+b") as f:  # üzerine yazarak imha
                    f.write(secrets.token_bytes(size))
                p.unlink()
            a.purged_at = now
            a.save(update_fields=["purged_at"])
            n += 1
    return n


def file_fingerprint(data: bytes):
    return hashlib.sha256(data).hexdigest()


class IsPlatform(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_platform)
