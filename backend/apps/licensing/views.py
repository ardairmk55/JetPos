import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.models import Branch, Business, BranchSettings, Device, User
from apps.core.tenancy import HasPerm, current_branch, current_business

from . import services
from .models import (BusinessApplication, LicenseRecord, MaintenanceContract, PlatformConfig, PlatformPayment,
                     ReleaseNote, SLAPolicy, SupportAccessGrant, SupportAttachment, SupportTicket)


# ------------------------------------------------------------------ lisans (şube tarafı)
class LicenseView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = None
    perm_write = roles.SETTINGS_MANAGE

    def get(self, request):
        return Response(services.license_status(current_business(request)))

    def post(self, request):
        biz = current_business(request)
        if request.data.get("key"):
            services.activate_with_key(biz, request.data["key"], user=request.user)
        elif request.data.get("blob"):
            services.install_license(biz, request.data["blob"], user=request.user)
        elif request.FILES.get("file"):
            services.install_license(biz, request.FILES["file"].read().decode("utf-8", "ignore"), user=request.user)
        else:
            raise BusinessError("Lisans anahtarı veya imzalı lisans dosyası gerekli")
        return Response(services.license_status(biz))


class DeviceSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", default="", read_only=True)

    class Meta:
        model = Device
        exclude = ["business", "token"]


class DeviceViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.SETTINGS_MANAGE
    perm_actions = {"register": None, "deactivate": roles.SETTINGS_MANAGE, "transfer": roles.SETTINGS_MANAGE}

    def get_queryset(self):
        qs = Device.objects.filter(business=current_business(self.request)).order_by("-is_active", "-activated_at")
        return qs

    @action(detail=False, methods=["post"])
    def register(self, request):
        d = services.register_device(business=current_business(request), branch=current_branch(request, required=False),
                                     name=request.data.get("name") or request.META.get("HTTP_USER_AGENT", "Cihaz")[:60],
                                     kind=request.data.get("kind", "terminal"),
                                     fingerprint=request.data.get("fingerprint", ""), user=request.user)
        if not d.fingerprint:
            raise BusinessError("Cihaz kimliği gerekli")
        return Response(DeviceSerializer(d).data, status=201)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        d = self.get_object()
        d.is_active = False
        d.deactivated_at = timezone.now()
        d.save(update_fields=["is_active", "deactivated_at"])
        audit.log("device.deactivate", request=request, entity="Device", entity_id=d.pk,
                  reason=request.data.get("reason", ""))
        return Response(DeviceSerializer(d).data)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        new = services.transfer_device(self.get_object(), new_fingerprint=request.data.get("fingerprint", ""),
                                       new_name=request.data.get("name", ""), user=request.user,
                                       reason=request.data.get("reason", ""))
        return Response(DeviceSerializer(new).data, status=201)


# ------------------------------------------------------------------ destek
class SupportTicketSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True)
    sla = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = "__all__"
        read_only_fields = [f.name for f in SupportTicket._meta.fields if f.name not in
                            ("category", "subject", "description", "business_impact", "urgency", "operation_stopped")]

    def get_sla(self, obj):
        return services.sla_state(obj)


class SupportTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    http_method_names = ["get", "post"]

    def get_queryset(self):
        u = self.request.user
        if u.is_platform:
            if u.role not in (roles.SUPPORT, roles.TECH, roles.PLATFORM_ADMIN):
                return SupportTicket.objects.none()
            qs = SupportTicket.objects.all()
        else:
            if not roles.has_perm(u, roles.SUPPORT_REQUEST):
                return SupportTicket.objects.none()
            qs = SupportTicket.objects.filter(business=u.business)
        st = self.request.GET.get("status")
        if st:
            qs = qs.filter(status=st)
        return qs.select_related("business", "created_by")

    def create(self, request, *args, **kwargs):
        if request.user.is_platform or not roles.has_perm(request.user, roles.SUPPORT_REQUEST):
            raise BusinessError("Talep oluşturma yetkiniz yok", status_code=403)
        s = SupportTicketSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        t = services.create_ticket(business=request.user.business, branch=current_branch(request, required=False),
                                   user=request.user, data=s.validated_data)
        return Response(SupportTicketSerializer(t).data, status=201)

    def retrieve(self, request, *args, **kwargs):
        t = self.get_object()
        data = SupportTicketSerializer(t).data
        msgs = t.messages.select_related("author")
        if not request.user.is_platform:
            msgs = msgs.filter(internal=False)
        data["messages"] = [{"id": m.id, "author": m.author.get_full_name() or m.author.username,
                             "is_support": m.author.is_platform, "body": m.body, "internal": m.internal,
                             "created_at": m.created_at} for m in msgs]
        data["events"] = [{"kind": e.kind, "note": e.note, "created_at": e.created_at} for e in t.events.all()]
        data["attachments"] = [{"id": a.id, "filename": a.filename, "size": a.size, "kind": a.kind,
                                "purged": bool(a.purged_at), "created_at": a.created_at} for a in t.attachments.all()]
        return Response(data)

    @action(detail=True, methods=["post"])
    def message(self, request, pk=None):
        t = self.get_object()
        services.add_message(t, user=request.user, body=request.data.get("body", ""),
                             internal=bool(request.data.get("internal")))
        return self.retrieve(request, pk=pk)

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        t = self.get_object()
        st = request.data.get("status")
        if not request.user.is_platform and st not in ("closed",):
            raise BusinessError("Müşteri yalnızca talebi kapatabilir", status_code=403)
        services.change_status(t, user=request.user, status=st, note=request.data.get("note", ""))
        return Response(SupportTicketSerializer(t).data)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        t = services.reopen_ticket(self.get_object(), user=request.user, note=request.data.get("note", ""))
        return Response(SupportTicketSerializer(t).data)

    @action(detail=True, methods=["post"])
    def attach(self, request, pk=None):
        t = self.get_object()
        f = request.FILES.get("file")
        if not f:
            raise BusinessError("Dosya gerekli")
        a = store_attachment(t, f, request.user, kind=request.data.get("kind", "file"))
        return Response({"id": a.id, "filename": a.filename}, status=201)

    @action(detail=True, methods=["get"], url_path=r"attachment/(?P<aid>\d+)")
    def attachment(self, request, pk=None, aid=None):
        t = self.get_object()
        a = t.attachments.get(pk=aid)
        if a.purged_at:
            raise BusinessError("Dosya saklama süresi dolduğu için imha edildi", status_code=410)
        data = Fernet(_attachment_key()).decrypt(Path(a.path).read_bytes())
        audit.log("support.attachment_download", request=request, business=t.business, entity="SupportAttachment",
                  entity_id=a.pk)
        resp = HttpResponse(data, content_type="application/octet-stream")
        resp["Content-Disposition"] = f'attachment; filename="{a.filename}"'
        return resp


ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".log", ".csv", ".json", ".zip", ".mp4", ".webm"}
BLOCKED_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"PK\x03\x04\x14\x00\x06\x00")


def _attachment_key():
    p = settings.DATA_DIR / "attachments.key"
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
    return p.read_bytes()


def scan_upload(name, data):
    """Basit zararlı dosya taraması: uzantı izin listesi, çalıştırılabilir imzası, makro/script içerik."""
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise BusinessError(f"İzin verilmeyen dosya türü: {ext or '-'}", code="file_blocked")
    if data[:4].startswith(BLOCKED_MAGIC[:3]) or data.startswith(b"MZ"):
        raise BusinessError("Çalıştırılabilir içerik engellendi", code="file_blocked")
    low = data[:4096].lower()
    if ext in (".txt", ".log", ".csv", ".json") and (b"<script" in low or b"powershell" in low and b"-enc" in low):
        raise BusinessError("Şüpheli içerik engellendi", code="file_blocked")
    if ext == ".zip":
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if Path(n).suffix.lower() in (".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".scr"):
                        raise BusinessError(f"Arşivde çalıştırılabilir dosya: {n}", code="file_blocked")
        except zipfile.BadZipFile:
            raise BusinessError("Bozuk arşiv", code="file_blocked")


def store_attachment(ticket, f, user, kind="file"):
    if f.size > 20 * 1024 * 1024:
        raise BusinessError("Dosya 20 MB'tan büyük olamaz")
    data = f.read()
    scan_upload(f.name, data)
    if kind == "recording":
        grant = ticket.supportaccessgrant_set.filter(recording_consent=True).exists()
        if not grant:
            raise BusinessError("Ekran kaydı için müşterinin açık onayı yok", code="recording_consent")
    folder = settings.DATA_DIR / "support_files"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ticket.number}_{secrets.token_hex(8)}.bin"
    path.write_bytes(Fernet(_attachment_key()).encrypt(data))
    a = SupportAttachment.objects.create(ticket=ticket, uploaded_by=user, filename=Path(f.name).name[:200],
                                         content_type=getattr(f, "content_type", "")[:100], size=len(data),
                                         sha256=services.file_fingerprint(data), path=str(path), kind=kind)
    audit.log("support.attachment_upload", user=user, business=ticket.business, entity="SupportAttachment",
              entity_id=a.pk, after={"filename": a.filename, "sha256": a.sha256})
    return a


class GrantSerializer(serializers.ModelSerializer):
    support_user_name = serializers.CharField(source="support_user.username", read_only=True)
    granted_by_name = serializers.CharField(source="granted_by.username", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)
    active = serializers.BooleanField(source="is_active", read_only=True)
    action_count = serializers.SerializerMethodField()

    class Meta:
        model = SupportAccessGrant
        fields = "__all__"

    def get_action_count(self, obj):
        return obj.actions.count()


class SupportGrantViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = GrantSerializer

    def get_queryset(self):
        u = self.request.user
        if u.role in (roles.SUPPORT, roles.TECH):
            return SupportAccessGrant.objects.filter(support_user=u)
        if u.role in (roles.OWNER, roles.BRANCH_MANAGER):
            return SupportAccessGrant.objects.filter(business=u.business)
        return SupportAccessGrant.objects.none()

    def create(self, request):
        support_user = User.objects.filter(username=request.data.get("support_username", ""),
                                           role__in=[roles.SUPPORT, roles.TECH], is_active=True).first()
        if not support_user:
            raise BusinessError("Destek kullanıcısı bulunamadı")
        ticket = SupportTicket.objects.filter(pk=request.data.get("ticket"), business=request.user.business).first()
        g = services.grant_support_access(
            business=request.user.business, granted_by=request.user, support_user=support_user,
            scopes=request.data.get("scopes", ["read"]), minutes=request.data.get("minutes", 30),
            reason=request.data.get("reason", ""), data_access=request.data.get("data_access", "anonymized"),
            recording_consent=request.data.get("recording_consent", False), ticket=ticket)
        return Response(GrantSerializer(g).data, status=201)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        return Response(GrantSerializer(services.revoke_support_access(self.get_object(), user=request.user)).data)

    @action(detail=True, methods=["post"])
    def use(self, request, pk=None):
        g = self.get_object()
        if g.support_user_id != request.user.id or not g.is_active:
            raise BusinessError("Erişim aktif değil", status_code=403)
        request.session["support_grant"] = str(g.grant_id)
        audit.log("support.session_start", user=request.user, business=g.business, entity="SupportAccessGrant",
                  entity_id=g.pk)
        return Response({"ok": True, "business": g.business.name, "expires_at": g.expires_at})

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        g = self.get_object()
        if g.support_user_id == request.user.id:
            g.ended_at = timezone.now()
            g.save(update_fields=["ended_at"])
            request.session.pop("support_grant", None)
            audit.log("support.session_end", user=request.user, business=g.business, entity="SupportAccessGrant",
                      entity_id=g.pk)
        return Response(GrantSerializer(g).data)

    @action(detail=True, methods=["get"])
    def actions(self, request, pk=None):
        g = self.get_object()
        return Response(list(g.actions.values("method", "path", "status_code", "created_at")[:500]))


# ------------------------------------------------------------------ müşteri portalı
class PortalSummary(APIView):
    def get(self, request):
        biz = current_business(request)
        if biz is None or not roles.has_perm(request.user, roles.SETTINGS_MANAGE):
            raise BusinessError("Yetkiniz yok", status_code=403)
        from apps.ops.models import BackupRecord, UpdateRecord
        import jetpos

        return Response({
            "business": {"name": biz.name, "slug": biz.slug, "template": biz.template},
            "license": services.license_status(biz),
            "branches": list(Branch.objects.filter(business=biz).values("id", "name", "code", "is_active")),
            "users": User.objects.filter(business=biz, is_active=True).count(),
            "devices": Device.objects.filter(business=biz, is_active=True).count(),
            "contracts": list(MaintenanceContract.objects.filter(business=biz).values("starts_on", "ends_on", "note")),
            "payments": list(PlatformPayment.objects.filter(business=biz).values("description", "amount", "paid_on", "reference")),
            "tickets_open": SupportTicket.objects.filter(business=biz).exclude(status__in=("resolved", "closed")).count(),
            "last_backups": list(BackupRecord.objects.order_by("-created_at").values("name", "created_at", "status", "verified_at")[:5]),
            "version": jetpos.__version__,
            "updates": list(UpdateRecord.objects.order_by("-created_at").values("version", "status", "created_at")[:5]),
            "release_notes": list(ReleaseNote.objects.values("version", "title", "body", "published_at")[:10]),
        })


# ------------------------------------------------------------------ platform yönetimi
class PlatformPerm(permissions.BasePermission):
    def has_permission(self, request, view):
        need = getattr(view, "platform_perm", roles.PLATFORM_MANAGE)
        return bool(request.user and request.user.is_authenticated and roles.has_perm(request.user, need))


class BusinessAdminSerializer(serializers.ModelSerializer):
    branch_count = serializers.IntegerField(source="branches.count", read_only=True)
    license = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = "__all__"
        read_only_fields = ["slug"]

    def get_license(self, obj):
        rec = obj.license_records.first()
        return {"package": rec.package, "status": rec.status, "modules": rec.modules} if rec else None


def create_business_with_owner(*, name, template, owner_username, owner_email, owner_name="", is_corporate=False,
                               branch_name="Merkez", actor=None):
    from apps.core.views import make_slug

    if User.objects.filter(username=owner_username).exists():
        raise BusinessError("Kullanıcı adı kullanımda")
    with transaction.atomic():
        biz = Business.objects.create(name=name, slug=make_slug(name), template=template, email=owner_email,
                                      is_corporate=is_corporate)
        branch = Branch.objects.create(business=biz, name=branch_name, code="MRK")
        BranchSettings.objects.create(branch=branch)
        temp_pw = secrets.token_urlsafe(10)
        owner = User(username=owner_username, email=owner_email, first_name=owner_name, business=biz,
                     role=roles.OWNER)
        owner.set_password(temp_pw)
        owner.save()
        audit.log("platform.business_create", user=actor, business=biz, entity="Business", entity_id=biz.pk)
    return biz, owner, temp_pw


class PlatformBusinessViewSet(viewsets.ModelViewSet):
    serializer_class = BusinessAdminSerializer
    permission_classes = [PlatformPerm]
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        return Business.objects.all().order_by("name")

    def create(self, request):
        d = request.data
        biz, owner, pw = create_business_with_owner(name=d["name"], template=d.get("template", "restaurant"),
                                                    owner_username=d["owner_username"], owner_email=d.get("owner_email", ""),
                                                    owner_name=d.get("owner_name", ""), is_corporate=bool(d.get("is_corporate")),
                                                    actor=request.user)
        return Response({"business": BusinessAdminSerializer(biz).data, "owner": owner.username,
                         "temporary_password": pw}, status=201)


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessApplication
        fields = "__all__"
        read_only_fields = ["status", "business", "decided_by", "created_at"]


class PublicApplyView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        s = ApplicationSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        app = s.save()
        for u in User.objects.filter(role=roles.PLATFORM_ADMIN, is_active=True):
            from apps.core.models import Notification

            Notification.objects.create(user=u, event="application", title=f"Yeni başvuru: {app.business_name}",
                                        priority="medium", data={"application": app.id})
        return Response({"id": app.id, "status": app.status}, status=201)


class ApplicationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ApplicationSerializer
    permission_classes = [PlatformPerm]
    queryset = BusinessApplication.objects.all()

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        app = self.get_object()
        if app.status != "new":
            raise BusinessError("Başvuru zaten sonuçlandırılmış")
        username = request.data.get("owner_username") or app.email.split("@")[0]
        biz, owner, pw = create_business_with_owner(name=app.business_name, template=app.template,
                                                    owner_username=username, owner_email=app.email,
                                                    owner_name=app.contact_name, actor=request.user)
        app.status = "approved"
        app.business = biz
        app.decided_by = request.user
        app.save()
        return Response({"business": biz.id, "owner": owner.username, "temporary_password": pw})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        app = self.get_object()
        app.status = "rejected"
        app.decided_by = request.user
        app.save()
        return Response(ApplicationSerializer(app).data)


class LicenseRecordSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = LicenseRecord
        fields = "__all__"
        read_only_fields = ["license_id", "activation_key", "signed_blob", "issued_by", "issued_at", "activated_at", "status"]


class LicenseAdminViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = LicenseRecordSerializer
    permission_classes = [PlatformPerm]
    platform_perm = roles.LICENSE_MANAGE
    queryset = LicenseRecord.objects.select_related("business")

    def create(self, request):
        d = request.data
        biz = Business.objects.get(pk=d["business"])
        rec = services.issue_license(
            business=biz, package=d["package"], modules=d.get("modules", []), user=request.user,
            max_branches=d.get("max_branches") or None, max_users=d.get("max_users") or None,
            max_terminals=d.get("max_terminals") or None, max_mobile=d.get("max_mobile") or None,
            support_until=d.get("support_until") or None)
        return Response(LicenseRecordSerializer(rec).data, status=201)

    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        rec = self.get_object()
        if request.data.get("status") not in ("active", "suspended", "revoked"):
            raise BusinessError("Geçersiz durum")
        rec.status = request.data["status"]
        rec.save(update_fields=["status"])
        audit.log("license.status", user=request.user, business=rec.business, entity="LicenseRecord", entity_id=rec.pk,
                  after={"status": rec.status})
        return Response(LicenseRecordSerializer(rec).data)

    @action(detail=True, methods=["get"])
    def qr(self, request, pk=None):
        """İmzalı lisans metnini QR olarak verir; şube tarafında okutulan metin Ayarlar > Lisans'a girilir."""
        from apps.core.qr import response

        rec = self.get_object()
        return response(rec.signed_blob, f"{rec.business.slug}-lisans.png")

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        rec = self.get_object()
        resp = HttpResponse(rec.signed_blob, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{rec.business.slug}.jetlic"'
        return resp


class RemoteActivateView(APIView):
    """Online anahtar ile aktivasyon (merkez tarafı)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        rec = LicenseRecord.objects.filter(activation_key=str(request.data.get("key", "")).upper(), status="active",
                                           business__slug=request.data.get("business_slug", "")).first()
        if not rec:
            return Response({"detail": "Geçersiz anahtar"}, status=404)
        rec.activated_at = rec.activated_at or timezone.now()
        rec.save(update_fields=["activated_at"])
        return Response({"blob": rec.signed_blob})


class SimpleAdminViewSet(viewsets.ModelViewSet):
    permission_classes = [PlatformPerm]


class SLAPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SLAPolicy
        fields = "__all__"


class SLAPolicyViewSet(SimpleAdminViewSet):
    serializer_class = SLAPolicySerializer
    queryset = SLAPolicy.objects.all()
    platform_perm = roles.SUPPORT_MANAGE


class PaymentAdminSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = PlatformPayment
        fields = "__all__"
        read_only_fields = ["user"]


class PlatformPaymentViewSet(SimpleAdminViewSet):
    serializer_class = PaymentAdminSerializer
    queryset = PlatformPayment.objects.select_related("business")
    platform_perm = roles.PLATFORM_FINANCE

    def perform_create(self, s):
        s.save(user=self.request.user)


class ContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaintenanceContract
        fields = "__all__"


class ContractViewSet(SimpleAdminViewSet):
    serializer_class = ContractSerializer
    queryset = MaintenanceContract.objects.all()
    platform_perm = roles.LICENSE_MANAGE


class ReleaseNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseNote
        fields = "__all__"


class ReleaseNoteViewSet(SimpleAdminViewSet):
    serializer_class = ReleaseNoteSerializer
    queryset = ReleaseNote.objects.all()


class PlatformConfigView(APIView):
    permission_classes = [PlatformPerm]

    class S(serializers.ModelSerializer):
        class Meta:
            model = PlatformConfig
            exclude = ["id"]

    def get(self, request):
        return Response(self.S(PlatformConfig.get()).data)

    def patch(self, request):
        s = self.S(PlatformConfig.get(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
