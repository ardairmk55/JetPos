"""Tek yazıcı lider, fencing ve kontrollü failover/failback (§16.2, kabul: split-brain engellenir)."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import BusinessError

from .models import BackupRecord, FailoverEvent, ServerNode, WriterLease


def lease_seconds():
    return settings.JETPOS["WRITER_LEASE_SECONDS"]


def current_lease():
    return WriterLease.objects.filter(pk=1).first()


def acquire_or_renew(node_id, now=None):
    """Lider kendi kilidini yeniler. Başka düğüm, kilit süresi dolmadan ve eski düğüm izole edilmeden alamaz."""
    now = now or timezone.now()
    with transaction.atomic():
        lease = WriterLease.objects.select_for_update().filter(pk=1).first()
        if lease is None:
            lease = WriterLease.objects.create(pk=1, holder=node_id, token=1,
                                               expires_at=now + timedelta(seconds=lease_seconds()))
            _touch(node_id, now)
            return lease
        if lease.holder == node_id:
            node = ServerNode.objects.filter(node_id=node_id).first()
            if node and node.fenced:
                raise BusinessError("Bu düğüm izole edilmiş; yazma yetkisi yok", code="fenced", status_code=503)
            lease.expires_at = now + timedelta(seconds=lease_seconds())
            lease.save(update_fields=["expires_at", "renewed_at"])
            _touch(node_id, now)
            return lease
        raise BusinessError(f"Yazma kilidi {lease.holder} düğümünde", code="not_leader", status_code=503)


def _touch(node_id, now):
    ServerNode.objects.update_or_create(node_id=node_id, defaults={"last_heartbeat": now})


def is_writer(node_id, now=None):
    now = now or timezone.now()
    lease = current_lease()
    if lease is None:
        return True
    node = ServerNode.objects.filter(node_id=node_id).first()
    if node and node.fenced:
        return False
    return lease.holder == node_id and lease.expires_at > now


def fence_node(node_id, *, user=None, reason=""):
    """Eski sunucunun yazma yetkisini izole eder (ör. ağdan çıkarıldı, servis durduruldu — operatör teyidi)."""
    node, _ = ServerNode.objects.get_or_create(node_id=node_id)
    node.fenced = True
    node.fenced_at = timezone.now()
    node.save(update_fields=["fenced", "fenced_at"])
    FailoverEvent.objects.create(kind="fence", from_node=node_id, approved_by=user, details={"reason": reason})
    audit.log("failover.fence", user=user, entity="ServerNode", entity_id=node_id, reason=reason)
    return node


def assess_failover(target_node, now=None):
    """Arızayı doğrula, yedek ve veri durumunu kontrol et; güvenliyse otomatik, riskliyse yönetici onayı."""
    now = now or timezone.now()
    lease = current_lease()
    checks = {}
    if lease is None or lease.holder == target_node:
        return {"possible": False, "reason": "Hedef düğüm zaten lider veya kilit yok", "checks": checks}
    old = ServerNode.objects.filter(node_id=lease.holder).first()
    checks["leader_expired"] = lease.expires_at < now
    checks["leader_silent_2x"] = lease.expires_at + timedelta(seconds=lease_seconds()) < now
    checks["old_fenced"] = bool(old and old.fenced)
    last_ok = BackupRecord.objects.filter(status="ok", deleted_at__isnull=True, verify_ok=True).order_by("-created_at").first()
    checks["recent_verified_backup"] = bool(last_ok and last_ok.created_at > now - timedelta(days=1))
    target = ServerNode.objects.filter(node_id=target_node).first()
    checks["target_healthy"] = bool(target and target.healthy is not False)
    checks["auto_mode"] = bool(target and target.redundancy_mode == "auto")
    possible = checks["leader_expired"] and checks["old_fenced"] and checks["target_healthy"]
    safe = possible and checks["leader_silent_2x"] and checks["recent_verified_backup"] and checks["auto_mode"]
    reason = "" if possible else ("Eski sunucu izole edilmeden yeni sunucu yazmaya başlayamaz" if not checks["old_fenced"]
                                  else "Lider kilidi hâlâ geçerli" if not checks["leader_expired"] else "Hedef sağlıksız")
    return {"possible": possible, "auto": safe, "reason": reason, "checks": checks, "leader": lease.holder,
            "token": lease.token}


def failover(target_node, *, user=None, approve=False, now=None):
    now = now or timezone.now()
    a = assess_failover(target_node, now)
    if not a["possible"]:
        FailoverEvent.objects.create(kind="blocked", from_node=a.get("leader", ""), to_node=target_node,
                                     details=a, approved_by=user)
        raise BusinessError(a["reason"], code="failover_blocked", extra={"checks": a["checks"]})
    if not a["auto"] and not approve:
        raise BusinessError("Riskli geçiş: yönetici onayı gerekli", code="approval_required",
                            extra={"checks": a["checks"]})
    with transaction.atomic():
        lease = WriterLease.objects.select_for_update().get(pk=1)
        old = lease.holder
        lease.holder = target_node
        lease.token += 1  # fencing token: eski liderin yazmaları geçersiz
        lease.expires_at = now + timedelta(seconds=lease_seconds())
        lease.save()
        ServerNode.objects.update_or_create(node_id=target_node, defaults={"role": "primary", "last_heartbeat": now,
                                                                           "fenced": False})
        ServerNode.objects.filter(node_id=old).update(role="standby")
        FailoverEvent.objects.create(kind="failover", from_node=old, to_node=target_node,
                                     decision="auto" if a["auto"] and not approve else "manual",
                                     approved_by=user, details=a)
    audit.log("failover.execute", user=user, entity="WriterLease", entity_id=1,
              before={"holder": old}, after={"holder": target_node, "token": lease.token})
    return lease


def failback(primary_node, *, user, data_synced, consistency_ok, now=None):
    """Ana sunucu test edilir, veriler eşitlenir, tutarlılık doğrulanır; risk varsa dönüş durur."""
    now = now or timezone.now()
    node = ServerNode.objects.filter(node_id=primary_node).first()
    checks = {"primary_healthy": bool(node and node.healthy), "data_synced": bool(data_synced),
              "consistency_ok": bool(consistency_ok)}
    if not all(checks.values()):
        FailoverEvent.objects.create(kind="blocked", to_node=primary_node, approved_by=user,
                                     details={"failback": checks})
        raise BusinessError("Failback durduruldu: kontroller başarısız", code="failback_blocked", extra={"checks": checks})
    with transaction.atomic():
        lease = WriterLease.objects.select_for_update().get(pk=1)
        standby = lease.holder
        ServerNode.objects.filter(node_id=standby).update(fenced=True, fenced_at=now, role="standby")
        node.fenced = False
        node.role = "primary"
        node.save(update_fields=["fenced", "role"])
        lease.holder = primary_node
        lease.token += 1
        lease.expires_at = now + timedelta(seconds=lease_seconds())
        lease.save()
        FailoverEvent.objects.create(kind="failback", from_node=standby, to_node=primary_node, approved_by=user,
                                     details=checks)
    audit.log("failover.failback", user=user, entity="WriterLease", entity_id=1,
              before={"holder": standby}, after={"holder": primary_node, "token": lease.token})
    return lease
