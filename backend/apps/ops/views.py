import tempfile
from pathlib import Path

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import roles
from apps.core.exceptions import BusinessError
from apps.core.models import CentralInbox, SyncEvent
from apps.core.tenancy import HasPerm

from . import backup, failover, health, sync, updates
from .models import BackupPolicy, BackupRecord, FailoverEvent, HealthSnapshot, ServerNode, UpdateRecord


class OpsPerm(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = (roles.OPS_MANAGE, roles.HEALTH_VIEW)
    perm_write = roles.OPS_MANAGE


class BackupSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupRecord
        exclude = ["path"]


class PolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupPolicy
        exclude = ["id"]


class BackupsView(OpsPerm):
    def get(self, request):
        return Response({
            "backups": BackupSerializer(BackupRecord.objects.filter(deleted_at__isnull=True)[:100], many=True).data,
            "policy": PolicySerializer(BackupPolicy.get()).data,
            "mirrors": settings.JETPOS["BACKUP_MIRROR_DIRS"],
            "cloud": "Bulut yedek hedefi yapılandırılmadı (dış servis bilgisi gerekli)",
            "confirm_phrase": backup.CONFIRM_PHRASE,
        })

    def post(self, request):
        act = request.data.get("action", "create")
        if act == "create":
            rec = backup.create_backup("manual", user=request.user, critical=bool(request.data.get("critical")))
            backup.verify_backup(rec, user=request.user)
            return Response(BackupSerializer(rec).data, status=201)
        if act == "policy":
            s = PolicySerializer(BackupPolicy.get(), data=request.data.get("policy", {}), partial=True)
            s.is_valid(raise_exception=True)
            s.save()
            return Response(s.data)
        if act == "retention":
            return Response({"removed": backup.apply_retention()})
        rec = get_object_or_404(BackupRecord, pk=request.data.get("id"))
        if act == "verify":
            backup.verify_backup(rec, user=request.user)
        elif act == "restore_test":
            backup.restore_test(rec, user=request.user)
        elif act == "protect":
            rec.critical = not rec.critical
            rec.save(update_fields=["critical"])
        elif act == "restore":
            if request.user.role not in (roles.OWNER, roles.PLATFORM_ADMIN, roles.TECH):
                raise BusinessError("Geri yükleme yalnızca işletme sahibi veya teknik ekip tarafından yapılabilir", status_code=403)
            pre = backup.restore_backup(rec, request.user, request.data.get("confirm", ""))
            return Response({"restored": rec.name, "pre_restore_backup": pre.name,
                             "detail": "Geri yükleme tamamlandı. Lütfen yeniden giriş yapın."})
        else:
            raise BusinessError("Geçersiz işlem")
        rec.refresh_from_db()
        return Response(BackupSerializer(rec).data)


class HealthView(OpsPerm):
    def get(self, request):
        if request.GET.get("diagnose") == "1":
            return Response(health.diagnose())
        last = HealthSnapshot.objects.all()[:48]
        return Response({
            "now": health.collect(),
            "history": list(last.values("cpu", "ram", "disk", "db_latency_ms", "created_at")),
            "nodes": list(ServerNode.objects.values()),
            "central": central_overview() if request.user.is_platform else None,
        })

    def post(self, request):
        return Response({"snapshot": health.snapshot().id})


def central_overview():
    """Merkezi sağlık izleme: şubelerden gelen son sağlık olayları."""
    from django.db.models import Max

    rows = []
    latest = CentralInbox.objects.filter(kind="health").values("business__name", "branch_code").annotate(last=Max("received_at"))
    for r in latest:
        ev = CentralInbox.objects.filter(kind="health", business__name=r["business__name"], branch_code=r["branch_code"],
                                         received_at=r["last"]).first()
        rows.append({"business": r["business__name"], "branch": r["branch_code"], "received_at": r["last"],
                     **(ev.payload if ev else {})})
    return rows


class UpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = UpdateRecord
        exclude = ["package_path"]


class UpdatesView(OpsPerm):
    def get(self, request):
        return Response({"current": updates.current_version(),
                         "history": UpdateSerializer(UpdateRecord.objects.all()[:50], many=True).data,
                         "central": bool(settings.JETPOS["CENTRAL_URL"])})

    def post(self, request):
        act = request.data.get("action", "upload")
        if act == "upload":
            f = request.FILES.get("package")
            sig = request.data.get("signature") or (request.FILES["signature"].read().decode() if request.FILES.get("signature") else "")
            if not f or not sig:
                raise BusinessError("Paket (.zip) ve imza (.sig) gerekli")
            tmp = Path(tempfile.mkdtemp()) / Path(f.name).name
            with open(tmp, "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
            rec = updates.stage_package(tmp, sig, source=request.data.get("source", "upload"), user=request.user)
            return Response(UpdateSerializer(rec).data, status=201)
        rec = get_object_or_404(UpdateRecord, pk=request.data.get("id"))
        if act == "approve":
            updates.approve(rec, user=request.user)
        elif act == "apply":
            updates.apply(rec, user=request.user)
        elif act == "rollback":
            updates.rollback(rec, user=request.user)
        elif act == "reject":
            rec.status = "rejected"
            rec.save(update_fields=["status"])
        else:
            raise BusinessError("Geçersiz işlem")
        rec.refresh_from_db()
        return Response(UpdateSerializer(rec).data)


class FailoverView(OpsPerm):
    def get(self, request):
        lease = failover.current_lease()
        target = request.GET.get("target")
        return Response({
            "node_id": settings.JETPOS["NODE_ID"],
            "enforced": settings.JETPOS["ENFORCE_WRITER_FENCE"],
            "lease": {"holder": lease.holder, "token": lease.token, "expires_at": lease.expires_at} if lease else None,
            "nodes": list(ServerNode.objects.values()),
            "events": list(FailoverEvent.objects.values()[:50]),
            "assessment": failover.assess_failover(target) if target else None,
        })

    def post(self, request):
        act = request.data.get("action")
        if request.user.role not in (roles.OWNER, roles.PLATFORM_ADMIN, roles.TECH):
            raise BusinessError("Yetkiniz yok", status_code=403)
        if act == "fence":
            failover.fence_node(request.data["node"], user=request.user, reason=request.data.get("reason", ""))
        elif act == "failover":
            failover.failover(request.data["target"], user=request.user, approve=bool(request.data.get("approve")))
        elif act == "failback":
            failover.failback(request.data["node"], user=request.user, data_synced=request.data.get("data_synced"),
                              consistency_ok=request.data.get("consistency_ok"))
        elif act == "mode":
            ServerNode.objects.update_or_create(node_id=request.data["node"], defaults={
                "redundancy_mode": request.data.get("mode", "none"), "address": request.data.get("address", "")})
        elif act == "acquire":
            failover.acquire_or_renew(settings.JETPOS["NODE_ID"])
        else:
            raise BusinessError("Geçersiz işlem")
        return self.get(request)


class SyncView(OpsPerm):
    def get(self, request):
        qs = SyncEvent.objects.all()
        return Response({"pending": qs.filter(status="pending").count(), "failed": qs.filter(status="failed").count(),
                         "sent": qs.filter(status="sent").count(),
                         "central_url": settings.JETPOS["CENTRAL_URL"] or None,
                         "recent_failed": list(qs.filter(status="failed").values("event_id", "kind", "attempts",
                                                                                 "last_error", "created_at")[:50])})

    def post(self, request):
        return Response(sync.push_pending())


class CentralIngestView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        token = settings.JETPOS["CENTRAL_TOKEN"]
        if not token or request.headers.get("X-Central-Token") != token:
            return Response({"detail": "Yetkisiz"}, status=401)
        if not isinstance(request.data, list):
            raise BusinessError("Liste bekleniyor")
        return Response({"accepted": sync.ingest(request.data)})
