"""Lisans (imzalı offline), modül/cihaz hakları; destek: müşteri onayı olmadan uzaktan erişim yok, erişim loglanır; SLA."""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.core import roles
from apps.core.exceptions import BusinessError
from apps.licensing import services as lic
from apps.licensing.models import InstalledLicense, PlatformConfig, SLAPolicy, SupportAccessGrant, SupportActionLog

from .conftest import make_business, make_user


def test_license_signature_and_modules(api, env):
    st = lic.license_status(env.biz)
    assert st["licensed"] and "crm" in st["modules"]
    blob = InstalledLicense.objects.get(business=env.biz).blob
    prefix, body, sig = blob.split(".")
    import base64
    import json

    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["modules"].append("hack")
    forged_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(BusinessError) as e:
        lic.install_license(env.biz, f"{prefix}.{forged_body}.{sig}")
    assert e.value.code == "license_invalid"
    biz2, _ = make_business("İkinci", "ikinci", code="X")
    with pytest.raises(BusinessError) as e:
        lic.install_license(biz2, blob)
    assert e.value.code == "license_mismatch"


def test_module_gating(api, env):
    biz2, br2 = make_business("Lisanssız", "lisanssiz", code="L")
    owner2 = make_user(biz2, None, "sahip2", roles.OWNER)
    r = api(owner2).get("/api/customers")
    assert r.status_code == 403
    assert api(env.owner).get("/api/customers").status_code == 200
    rec = lic.issue_license(business=biz2, package="starter", modules=["crm"])
    assert api(owner2).post("/api/license", {"key": rec.activation_key}, format="json").status_code == 200
    assert api(owner2).get("/api/customers").status_code == 200
    assert api(owner2).get("/api/deliveries").status_code == 403


def test_device_limit_and_transfer(api, env):
    rec = lic.issue_license(business=env.biz, package="starter", modules=[], max_terminals=1, max_mobile=1)
    lic.install_license(env.biz, rec.signed_blob)
    o = api(env.owner)
    d1 = o.post("/api/devices/register", {"fingerprint": "pc-1", "kind": "terminal"}, format="json")
    assert d1.status_code == 201
    r = o.post("/api/devices/register", {"fingerprint": "pc-2", "kind": "terminal"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "device_limit"
    assert o.post("/api/devices/register", {"fingerprint": "tel-1", "kind": "mobile"}, format="json").status_code == 201
    r = o.post(f"/api/devices/{d1.json()['id']}/transfer", {"fingerprint": "pc-2", "reason": "Anakart arızası"}, format="json")
    assert r.status_code == 201


def test_branch_limit(api, env):
    rec = lic.issue_license(business=env.biz, package="starter", modules=[], max_branches=1)
    lic.install_license(env.biz, rec.signed_blob)
    r = api(env.owner).post("/api/branches", {"name": "Yeni", "code": "N"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "license_limit"


@pytest.fixture
def support_user(db):
    return make_user(None, None, "destek1", roles.SUPPORT)


def test_remote_support_requires_consent_and_is_logged(api, env, support_user):
    s = api(support_user)
    assert s.get("/api/products").json() == []  # onaysız işletme verisi yok
    r = api(env.waiter).post("/api/support/grants", {"support_username": "destek1", "scopes": ["read"], "minutes": 30,
                                                     "reason": "Yazıcı sorunu"}, format="json")
    assert r.status_code == 400 or r.status_code == 403
    r = api(env.owner).post("/api/support/grants", {"support_username": "destek1", "scopes": ["read", "printers"],
                                                    "minutes": 30, "reason": "Yazıcı sorunu"}, format="json")
    assert r.status_code == 201
    gid = r.json()["grant_id"]
    hdr = {"HTTP_X_SUPPORT_GRANT": gid}
    prods = s.get("/api/products", **hdr).json()
    assert {p["name"] for p in prods} >= {"Köfte", "Ayran"}
    # Kapsam dışı yazma engellenir
    r = s.post("/api/products", {"name": "x", "category": env.food.id, "base_price": 1}, format="json", **hdr)
    assert r.status_code == 403 and r.json()["code"] == "grant_scope"
    assert SupportActionLog.objects.filter(grant__grant_id=gid).count() >= 2
    # Müşteri anında sonlandırır
    g = SupportAccessGrant.objects.get(grant_id=gid)
    assert api(env.owner).post(f"/api/support/grants/{g.id}/revoke").status_code == 200
    r = s.get("/api/products", **hdr)
    assert r.status_code == 403 and r.json()["code"] == "grant_inactive"
    from apps.core.models import AuditLog

    assert AuditLog.objects.filter(action="support.grant").exists() and AuditLog.objects.filter(action="support.revoke").exists()


def test_grant_expiry_and_duration_limit(env, support_user):
    with pytest.raises(BusinessError):
        lic.grant_support_access(business=env.biz, granted_by=env.owner, support_user=support_user, scopes=["read"],
                                 minutes=PlatformConfig.get().max_support_session_minutes + 1, reason="uzun")
    g = lic.grant_support_access(business=env.biz, granted_by=env.owner, support_user=support_user, scopes=["read"],
                                 minutes=5, reason="kısa")
    g.expires_at = timezone.now() - timedelta(seconds=1)
    g.save()
    assert not g.is_active


def test_attachment_scanning_and_encryption(api, env):
    from django.core.files.uploadedfile import SimpleUploadedFile

    o = api(env.owner)
    t = o.post("/api/support/tickets", {"subject": "Yazıcı", "description": "Çıktı yok", "category": "printer"},
               format="json").json()
    bad = SimpleUploadedFile("virus.exe", b"MZ\x90\x00", content_type="application/octet-stream")
    assert o.post(f"/api/support/tickets/{t['id']}/attach", {"file": bad}).status_code == 400
    bad2 = SimpleUploadedFile("log.txt", b"MZ\x90\x00 gizli exe", content_type="text/plain")
    assert o.post(f"/api/support/tickets/{t['id']}/attach", {"file": bad2}).status_code == 400
    good = SimpleUploadedFile("hata.txt", "Yazıcı hatası: kağıt sıkıştı".encode(), content_type="text/plain")
    r = o.post(f"/api/support/tickets/{t['id']}/attach", {"file": good})
    assert r.status_code == 201
    from apps.licensing.models import SupportAttachment
    from pathlib import Path

    a = SupportAttachment.objects.get()
    assert "kağıt".encode() not in Path(a.path).read_bytes()
    d = o.get(f"/api/support/tickets/{t['id']}/attachment/{a.id}")
    assert d.status_code == 200 and "kağıt sıkıştı" in d.content.decode()
    rec = SimpleUploadedFile("ekran.mp4", b"\x00\x00\x00\x18ftypmp42", content_type="video/mp4")
    r = o.post(f"/api/support/tickets/{t['id']}/attach", {"file": rec, "kind": "recording"})
    assert r.status_code == 400 and r.json()["code"] == "recording_consent"


def test_sla_business_hours_pause_and_reopen(api, env, support_user):
    tz = timezone.get_current_timezone()
    fri = timezone.make_aware(datetime(2026, 11, 20, 17, 0), tz)  # Cuma 17:00
    assert lic.add_business_minutes(fri, 120) == timezone.make_aware(datetime(2026, 11, 23, 10, 0), tz)
    SLAPolicy.objects.create(package="enterprise", priority="critical", first_response_minutes=30, resolution_minutes=240)
    SLAPolicy.objects.create(package="enterprise", priority="normal", first_response_minutes=240, resolution_minutes=960)
    o = api(env.owner)
    t = o.post("/api/support/tickets", {"subject": "Kasa kapandı", "description": "Satış yapamıyoruz",
                                        "operation_stopped": True, "business_impact": "low", "urgency": "low"},
               format="json").json()
    assert t["priority"] == "critical"  # paket kritik kesintiyi geriye itemez
    created = datetime.fromisoformat(t["created_at"])
    due = datetime.fromisoformat(t["first_response_due"])
    assert due - created == timedelta(minutes=30)  # kritik: takvim saati
    t2 = o.post("/api/support/tickets", {"subject": "Rapor", "description": "Soru"}, format="json").json()
    assert t2["first_response_due"] is not None and t2["sla"]["first_response"] in ("running", "breached")
    s = api(support_user)
    s.post(f"/api/support/tickets/{t2['id']}/status", {"status": "waiting_customer", "note": "Ekran görüntüsü?"}, format="json")
    d = s.get(f"/api/support/tickets/{t2['id']}").json()
    assert d["sla"]["first_response"] in ("met", "breached") and d["paused_at"]
    o.post(f"/api/support/tickets/{t2['id']}/message", {"body": "Ekledim"}, format="json")
    d = o.get(f"/api/support/tickets/{t2['id']}").json()
    assert d["status"] == "in_review" and d["paused_at"] is None
    assert any(e["kind"] == "sla_resumed" for e in d["events"])
    s.post(f"/api/support/tickets/{t2['id']}/status", {"status": "resolved"}, format="json")
    r = o.post(f"/api/support/tickets/{t2['id']}/reopen", {"note": "Sorun sürüyor"}, format="json")
    assert r.status_code == 200 and r.json()["reopen_count"] == 1
    # Müşteri durum değiştiremez (kapatma hariç)
    assert o.post(f"/api/support/tickets/{t2['id']}/status", {"status": "resolved"}, format="json").status_code == 403
    # İç not müşteriye görünmez
    s.post(f"/api/support/tickets/{t2['id']}/message", {"body": "gizli not", "internal": True}, format="json")
    assert all(m["body"] != "gizli not" for m in o.get(f"/api/support/tickets/{t2['id']}").json()["messages"])


def test_application_approval_creates_business(api, env, db):
    admin = make_user(None, None, "padmin", roles.PLATFORM_ADMIN)
    r = api().post("/api/public/apply", {"business_name": "Yeni Kafe", "contact_name": "Ayşe", "phone": "555",
                                         "email": "ayse@example.com", "template": "cafe"}, format="json")
    assert r.status_code == 201
    a = api(admin)
    app = a.get("/api/platform/applications").json()[0]
    r = a.post(f"/api/platform/applications/{app['id']}/approve", {"owner_username": "ayse"}, format="json")
    assert r.status_code == 200 and r.json()["temporary_password"]
    assert api(env.owner).get("/api/platform/applications").status_code == 403
