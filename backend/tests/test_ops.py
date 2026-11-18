"""Kabul: Yedek (restore, bütünlük, işlem kaydı), Failover (split-brain), Güncelleme (imza, yedek, onay, sağlık, rollback)."""
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from apps.core.exceptions import BusinessError
from apps.core.models import AuditLog
from apps.licensing import signing
from apps.ops import backup, failover, updates
from apps.ops.models import BackupRecord, ServerNode, WriterLease


def test_backup_encrypted_verified_and_tamper_detected(env):
    rec = backup.create_backup("manual", user=env.owner)
    raw = Path(rec.path).read_bytes()
    assert b"Test Lokanta" not in raw  # şifreli
    assert backup.verify_backup(rec) is True
    assert rec.record_counts.get("core.business") == 1
    assert AuditLog.objects.filter(action="backup.create").exists()
    Path(rec.path).write_bytes(raw[:-5] + b"XXXXX")
    assert backup.verify_backup(rec) is False
    rec.refresh_from_db()
    assert "bütünlük" in rec.error


def test_restore_requires_confirmation_and_restores(env):
    from apps.catalog.models import Product

    rec = backup.create_backup("manual", user=env.owner)
    Product.objects.filter(pk=env.ayran.pk).update(name="Değişti")
    with pytest.raises(BusinessError):
        backup.restore_backup(rec, env.owner, confirm="evet")
    pre = backup.restore_backup(rec, env.owner, confirm=backup.CONFIRM_PHRASE)
    assert Product.objects.get(pk=env.ayran.pk).name == "Ayran"
    assert BackupRecord.objects.filter(name=pre.name, kind="pre_restore", critical=True).exists()
    assert AuditLog.objects.filter(action="backup.restore").exists()


@pytest.mark.slow
def test_restore_test_into_fresh_database(env):
    rec = backup.create_backup("manual")
    ok = backup.restore_test(rec)
    rec.refresh_from_db()
    assert ok, rec.restore_test_log
    assert rec.restore_test_ok is True


def test_retention_keeps_critical(env):
    from apps.ops.models import BackupPolicy

    pol = BackupPolicy.get()
    pol.keep_daily = 1
    pol.save()
    a = backup.create_backup("daily")
    a.critical = True
    a.save()
    b = backup.create_backup("daily")
    c = backup.create_backup("daily")
    backup.apply_retention()
    alive = set(BackupRecord.objects.filter(deleted_at__isnull=True).values_list("pk", flat=True))
    assert a.pk in alive and c.pk in alive and b.pk not in alive
    assert not Path(b.path).exists()


def test_split_brain_prevented(env):
    now = timezone.now()
    lease = failover.acquire_or_renew("node-A", now=now)
    assert lease.token == 1
    with pytest.raises(BusinessError) as e:
        failover.acquire_or_renew("node-B", now=now)
    assert e.value.code == "not_leader"
    later = now + timedelta(seconds=settings.JETPOS["WRITER_LEASE_SECONDS"] * 3)
    # Kilit süresi dolsa bile eski sunucu izole edilmeden yeni sunucu yazmaya başlamaz
    with pytest.raises(BusinessError) as e:
        failover.failover("node-B", user=env.owner, approve=True, now=later)
    assert e.value.code == "failover_blocked"
    assert WriterLease.objects.get().holder == "node-A"
    failover.fence_node("node-A", user=env.owner, reason="Sunucu ağdan çıkarıldı")
    ServerNode.objects.create(node_id="node-B", role="standby", healthy=True, redundancy_mode="hot")
    with pytest.raises(BusinessError) as e:
        failover.failover("node-B", user=env.owner, approve=False, now=later)  # riskli → onay gerekir
    assert e.value.code == "approval_required"
    lease = failover.failover("node-B", user=env.owner, approve=True, now=later)
    assert lease.holder == "node-B" and lease.token == 2
    assert failover.is_writer("node-B", now=later) and not failover.is_writer("node-A", now=later)
    with pytest.raises(BusinessError):
        failover.acquire_or_renew("node-A", now=later)
    # Failback: kontroller başarısızsa durur
    with pytest.raises(BusinessError):
        failover.failback("node-A", user=env.owner, data_synced=True, consistency_ok=False, now=later)
    ServerNode.objects.filter(node_id="node-A").update(healthy=True)
    lease = failover.failback("node-A", user=env.owner, data_synced=True, consistency_ok=True, now=later)
    assert lease.holder == "node-A" and lease.token == 3
    assert ServerNode.objects.get(node_id="node-B").fenced is True


@override_settings(JETPOS={**settings.JETPOS, "ENFORCE_WRITER_FENCE": True, "NODE_ID": "standby-1"})
def test_writer_fence_middleware_blocks_standby(api, env):
    WriterLease.objects.create(pk=1, holder="primary-1", token=5, expires_at=timezone.now() + timedelta(minutes=5))
    r = api(env.waiter).post(f"/api/tables/{env.tables[0].id}/open", {}, format="json")
    assert r.status_code == 503 and r.json()["code"] == "not_leader"
    assert api(env.waiter).get("/api/floor").status_code == 200  # okuma serbest


def _make_package(tmp_path, version, healthcheck, priv, sign=True):
    src = tmp_path / f"src{version}"
    (src / "backend").mkdir(parents=True, exist_ok=True)
    (src / "backend" / "hc.py").write_text("import sys; sys.exit(0)", encoding="utf-8")
    (src / "backend" / "hc_fail.py").write_text("import sys; sys.exit(3)", encoding="utf-8")
    z, sig = updates.build_package(src, version, tmp_path / "out", priv, healthcheck=healthcheck)
    return z, (sig if sign else "AAAA" + sig[4:])


def test_update_signature_backup_approval_health_rollback(env, tmp_path):
    priv = tmp_path / "upd_priv.pem"
    signing.generate_keypair(priv, settings.JETPOS["UPDATE_PUBLIC_KEY_FILE"])
    z, bad = _make_package(tmp_path, "1.1.0", ["backend/hc.py"], priv, sign=False)
    with pytest.raises(BusinessError) as e:
        updates.stage_package(z, bad, user=env.owner)
    assert e.value.code == "bad_signature"
    z, sig = _make_package(tmp_path, "1.1.0", ["backend/hc.py"], priv)
    rec = updates.stage_package(z, sig, user=env.owner)
    with pytest.raises(BusinessError):
        updates.apply(rec, user=env.owner)  # onaysız uygulanamaz
    updates.approve(rec, user=env.owner)
    rec = updates.apply(rec, user=env.owner)
    assert rec.status == "applied" and rec.health_ok and rec.backup.kind == "pre_update"
    assert updates.current_version() == "1.1.0"
    # Sağlık testi başarısız sürüm → otomatik rollback
    z2, sig2 = _make_package(tmp_path, "1.2.0", ["backend/hc_fail.py"], priv)
    rec2 = updates.stage_package(z2, sig2, user=env.owner)
    updates.approve(rec2, user=env.owner)
    rec2 = updates.apply(rec2, user=env.owner)
    assert rec2.status == "rolled_back" and updates.current_version() == "1.1.0"
    # Eski sürüm reddedilir
    z3, sig3 = _make_package(tmp_path, "1.0.5", None, priv)
    with pytest.raises(BusinessError) as e:
        updates.stage_package(z3, sig3)
    assert e.value.code == "old_version"


def test_update_rejects_path_traversal(env, tmp_path):
    priv = tmp_path / "p.pem"
    signing.generate_keypair(priv, settings.JETPOS["UPDATE_PUBLIC_KEY_FILE"])
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": "9.0.0"}))
        zf.writestr("../../evil.txt", "x")
    sig = signing.sign_bytes(z.read_bytes(), signing.load_private(priv))
    with pytest.raises(BusinessError) as e:
        updates.stage_package(z, sig)
    assert e.value.code == "bad_package"


def test_health_and_scheduler_tick(env):
    from apps.ops import health
    from apps.ops.management.commands.jetpos_scheduler import tick
    from apps.ops.models import ScheduledTaskRun

    d = health.collect()
    assert d["db_ok"] and 0 <= d["cpu"] <= 100
    state = tick()
    assert ScheduledTaskRun.objects.filter(name="health", ok=True).exists()
    assert state.get("health_at")
    assert not ScheduledTaskRun.objects.filter(ok=False).exclude(name="restore_test").exists(), \
        list(ScheduledTaskRun.objects.filter(ok=False).values_list("name", "detail"))


def test_sync_push_and_central_ingest(api, env):
    from apps.core.models import CentralInbox, SyncEvent
    from apps.ops import sync

    from apps.pos.services import emit_sync

    emit_sync(env.branch, "test", {"a": 1})
    emit_sync(env.branch, "test", {"a": 2})
    res = sync.push_pending(transport=lambda payload: {"accepted": sync.ingest(payload)})
    assert res["sent"] == 2 and CentralInbox.objects.count() == 2
    # Tekrar gönderim idempotent
    SyncEvent.objects.update(status="pending")
    sync.push_pending(transport=lambda payload: {"accepted": sync.ingest(payload)})
    assert CentralInbox.objects.count() == 2
    # Bağlantı hatası kuyrukta izlenir
    emit_sync(env.branch, "test", {"a": 3})

    def down(payload):
        raise OSError("ağ yok")

    assert sync.push_pending(transport=down)["sent"] == 0
    assert SyncEvent.objects.filter(status="failed", last_error__icontains="ağ yok").count() == 1
