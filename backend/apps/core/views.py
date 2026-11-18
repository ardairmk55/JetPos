from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView

from . import audit, roles, totp
from .models import AuditLog, Branch, BranchSettings, LoginAttempt, Notification, NotificationRule, User
from .serializers import (AuditLogSerializer, BranchSerializer, BranchSettingsSerializer, BusinessSerializer,
                          MeSerializer, NotificationRuleSerializer, NotificationSerializer, UserSerializer)
from .tenancy import HasPerm, TenantViewSet, current_branch, current_business, limit_list


def _lock_params(user):
    s = user.branch.settings if user and user.branch_id else None
    return (s.max_failed_logins if s else 5), (s.lockout_minutes if s else 15)


def _register_failure(request, username, user, method):
    LoginAttempt.objects.create(username=username[:150], user=user, method=method, success=False,
                                ip=audit.client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:300])
    if user:
        max_f, lock_min = _lock_params(user)
        user.failed_attempts += 1
        fields = ["failed_attempts"]
        if user.failed_attempts >= max_f:
            user.locked_until = timezone.now() + timedelta(minutes=lock_min)
            fields.append("locked_until")
            audit.log("security.account_locked", request=request, user=user, business=user.business,
                      entity="User", entity_id=user.pk, reason=f"{user.failed_attempts} başarısız giriş")
        user.save(update_fields=fields)
    # Şüpheli oturum algılama: aynı IP'den kısa sürede çok sayıda başarısız deneme
    since = timezone.now() - timedelta(minutes=10)
    ip = audit.client_ip(request)
    if ip and LoginAttempt.objects.filter(ip=ip, success=False, created_at__gte=since).count() == 10:
        audit.log("security.suspicious_ip", request=request, business=getattr(user, "business", None),
                  reason=f"{ip} adresinden 10 dk içinde 10 başarısız giriş")


def _register_success(request, user, method):
    LoginAttempt.objects.create(username=user.username, user=user, method=method, success=True,
                                ip=audit.client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", "")[:300])
    user.failed_attempts = 0
    user.locked_until = None
    user.save(update_fields=["failed_attempts", "locked_until"])


@method_decorator(ensure_csrf_cookie, name="dispatch")
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"ok": True})

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        user = User.objects.filter(username=username).first()
        if user and user.is_locked:
            return Response({"detail": "Hesap çok sayıda hatalı deneme nedeniyle geçici olarak kilitli", "code": "account_locked"}, status=423)
        auth_user = authenticate(request, username=username, password=password)
        if auth_user is None:
            _register_failure(request, username, user, "password")
            return Response({"detail": "Kullanıcı adı veya şifre hatalı", "code": "invalid_credentials"}, status=401)
        if auth_user.two_factor_secret:
            otp = request.data.get("otp")
            if not otp:
                return Response({"detail": "Doğrulama kodu gerekli", "code": "otp_required"}, status=401)
            if not totp.verify(auth_user.two_factor_secret, otp):
                _register_failure(request, username, auth_user, "otp")
                return Response({"detail": "Doğrulama kodu hatalı", "code": "invalid_otp"}, status=401)
        login(request, auth_user)
        request.session["last_activity"] = timezone.now().timestamp()
        request.session["locked"] = False
        _register_success(request, auth_user, "password")
        audit.log("auth.login", request=request, user=auth_user, business=auth_user.business, entity="User",
                  entity_id=auth_user.pk)
        return Response(MeSerializer(auth_user).data)


class LogoutView(APIView):
    def post(self, request):
        audit.log("auth.logout", request=request, entity="User", entity_id=request.user.pk)
        logout(request)
        return Response({"ok": True})


class MeView(APIView):
    def get(self, request):
        user = request.user
        data = MeSerializer(user).data
        data["permissions"] = roles.perms_for(user)
        data["locked"] = bool(request.session.get("locked"))
        biz = current_business(request)
        data["business_name"] = biz.name if biz else ""
        branch = current_branch(request, required=False) if biz else None
        data["branch"] = branch.id if branch else None
        data["branch_name"] = branch.name if branch else ""
        if biz:
            if user.role in roles.BRANCH_SCOPED_ROLES:
                data["branches"] = [{"id": branch.id, "name": branch.name}] if branch else []
            else:
                data["branches"] = list(Branch.objects.filter(business=biz, is_active=True).values("id", "name"))
            if branch:
                data["settings"] = BranchSettingsSerializer(branch.settings).data
            from apps.licensing.services import license_status

            data["license"] = license_status(biz)
        data["is_platform"] = user.is_platform
        data["support_grant"] = getattr(request, "support_grant_id", None)
        return Response(data)


class PreferencesView(APIView):
    def post(self, request):
        user = request.user
        for f in ("theme", "language"):
            if f in request.data:
                val = request.data[f]
                choices = dict(User._meta.get_field(f).choices)
                if val not in choices:
                    return Response({"detail": f"Geçersiz {f}"}, status=400)
                setattr(user, f, val)
        if "font_scale" in request.data:
            fs = int(request.data["font_scale"])
            if not 80 <= fs <= 160:
                return Response({"detail": "Yazı boyutu 80-160 arasında olmalı"}, status=400)
            user.font_scale = fs
        if "high_contrast" in request.data:
            user.high_contrast = bool(request.data["high_contrast"])
        user.save(update_fields=["theme", "language", "font_scale", "high_contrast"])
        return Response(MeSerializer(user).data)


class SelectBranchView(APIView):
    def post(self, request):
        biz = current_business(request)
        if request.user.role in roles.BRANCH_SCOPED_ROLES:
            return Response({"detail": "Şube değiştirme yetkiniz yok"}, status=403)
        b = Branch.objects.filter(business=biz, pk=request.data.get("branch_id"), is_active=True).first()
        if not b:
            return Response({"detail": "Şube bulunamadı"}, status=404)
        request.session["branch_id"] = b.id
        return Response({"branch": b.id, "branch_name": b.name})


class LockView(APIView):
    def post(self, request):
        request.session["locked"] = True
        return Response({"locked": True})


class UnlockView(APIView):
    def post(self, request):
        user = request.user
        pin = request.data.get("pin")
        password = request.data.get("password")
        ok = (pin and user.check_pin(pin)) or (password and user.check_password(password))
        if not ok:
            _register_failure(request, user.username, user, "pin" if pin else "password")
            return Response({"detail": "PIN/şifre hatalı", "code": "invalid_credentials"}, status=401)
        request.session["locked"] = False
        request.session["last_activity"] = timezone.now().timestamp()
        return Response({"locked": False})


class PinUsersView(APIView):
    """Ortak cihazda hızlı personel değişimi için şubedeki PIN'li kullanıcılar."""

    def get(self, request):
        biz = current_business(request)
        branch = current_branch(request, required=False)
        qs = User.objects.filter(business=biz, is_active=True).exclude(pin_hash="")
        if branch:
            qs = qs.filter(Q(branch=branch) | Q(branch__isnull=True))
        return Response([{"id": u.id, "name": u.get_full_name() or u.username, "role": u.get_role_display()} for u in qs])


class PinSwitchView(APIView):
    def post(self, request):
        biz = current_business(request)
        target = User.objects.filter(business=biz, pk=request.data.get("user_id"), is_active=True).first()
        if not target:
            return Response({"detail": "Kullanıcı bulunamadı"}, status=404)
        if target.is_locked:
            return Response({"detail": "Hesap geçici olarak kilitli", "code": "account_locked"}, status=423)
        if not target.check_pin(request.data.get("pin", "")):
            _register_failure(request, target.username, target, "pin")
            return Response({"detail": "PIN hatalı", "code": "invalid_credentials"}, status=401)
        branch_id = request.session.get("branch_id")
        login(request, target, backend="django.contrib.auth.backends.ModelBackend")
        if branch_id:
            request.session["branch_id"] = branch_id
        request.session["locked"] = False
        request.session["last_activity"] = timezone.now().timestamp()
        _register_success(request, target, "pin")
        audit.log("auth.pin_switch", request=request, user=target, business=biz, entity="User", entity_id=target.pk)
        return Response(MeSerializer(target).data)


class ChangePasswordView(APIView):
    def post(self, request):
        user = request.user
        if not user.check_password(request.data.get("old_password", "")):
            return Response({"detail": "Mevcut şifre hatalı"}, status=400)
        from django.contrib.auth.password_validation import validate_password

        new = request.data.get("new_password", "")
        validate_password(new, user)
        user.set_password(new)
        user.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        audit.log("auth.password_changed", request=request, entity="User", entity_id=user.pk)
        return Response({"ok": True})


class SetPinView(APIView):
    def post(self, request):
        user = request.user
        if not user.check_password(request.data.get("password", "")):
            return Response({"detail": "Şifre hatalı"}, status=400)
        try:
            user.set_pin(request.data.get("pin", ""))
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        user.save(update_fields=["pin_hash"])
        audit.log("auth.pin_changed", request=request, entity="User", entity_id=user.pk)
        return Response({"ok": True})


class TwoFactorView(APIView):
    def get(self, request):
        secret = totp.new_secret()
        request.session["pending_2fa"] = secret
        return Response({"secret": secret, "uri": totp.uri(secret, request.user.username)})

    def post(self, request):
        secret = request.session.get("pending_2fa")
        if not secret or not totp.verify(secret, request.data.get("otp")):
            return Response({"detail": "Kod doğrulanamadı"}, status=400)
        request.user.two_factor_secret = secret
        request.user.save(update_fields=["two_factor_secret"])
        audit.log("auth.2fa_enabled", request=request, entity="User", entity_id=request.user.pk)
        return Response({"enabled": True})


class UserViewSet(TenantViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    perm_read = roles.USERS_MANAGE
    perm_write = roles.USERS_MANAGE
    branch_scoped = False
    search_fields_simple = ("username", "first_name", "last_name")
    ordering = ("first_name", "username")

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role in roles.BRANCH_SCOPED_ROLES:
            qs = qs.filter(branch=self.request.user.branch)
        if self.request.GET.get("active") == "1":
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        actor = self.request.user
        branch = serializer.validated_data.get("branch")
        if actor.role in roles.BRANCH_SCOPED_ROLES:
            branch = actor.branch
        if branch is not None and branch.business_id != current_business(self.request).id:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Şube bu işletmeye ait değil")
        obj = serializer.save(business=current_business(self.request), branch=branch)
        audit.log("user.create", request=self.request, entity="User", entity_id=obj.pk, after=obj)

    def perform_update(self, serializer):
        target = serializer.instance
        actor = self.request.user
        if actor.role == roles.BRANCH_MANAGER and target.role in (roles.OWNER, roles.BRANCH_MANAGER) and target != actor:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Bu kullanıcıyı düzenleyemezsiniz")
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        instance.deactivate()
        audit.log("user.deactivate", request=self.request, entity="User", entity_id=instance.pk)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        u = self.get_object()
        if u == request.user:
            return Response({"detail": "Kendi hesabınızı devre dışı bırakamazsınız"}, status=400)
        u.deactivate()
        audit.log("user.deactivate", request=request, entity="User", entity_id=u.pk, reason=request.data.get("reason", ""))
        return Response(UserSerializer(u, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        u = self.get_object()
        u.is_active = True
        u.deactivated_at = None
        u.failed_attempts = 0
        u.locked_until = None
        u.save()
        audit.log("user.activate", request=request, entity="User", entity_id=u.pk)
        return Response(UserSerializer(u, context={"request": request}).data)


class BranchViewSet(TenantViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    perm_read = None
    perm_write = roles.SETTINGS_MANAGE
    branch_scoped = False
    ordering = ("id",)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.role in roles.BRANCH_SCOPED_ROLES:
            qs = qs.filter(pk=self.request.user.branch_id)
        return qs

    def perform_create(self, serializer):
        if self.request.user.role != roles.OWNER:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("Şubeyi yalnızca işletme sahibi oluşturabilir")
        from apps.licensing.services import check_branch_limit

        check_branch_limit(current_business(self.request))
        super().perform_create(serializer)


class BusinessView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.SETTINGS_MANAGE
    perm_write = roles.SETTINGS_MANAGE

    def get(self, request):
        return Response(BusinessSerializer(current_business(request)).data)

    def patch(self, request):
        biz = current_business(request)
        before = audit.snapshot(biz)
        s = BusinessSerializer(biz, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit.log("business.update", request=request, entity="Business", entity_id=biz.pk, before=before, after=biz)
        return Response(s.data)


class BranchSettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = None
    perm_write = roles.SETTINGS_MANAGE

    def get(self, request):
        return Response(BranchSettingsSerializer(current_branch(request).settings).data)

    def patch(self, request):
        obj = current_branch(request).settings
        before = audit.snapshot(obj)
        s = BranchSettingsSerializer(obj, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        audit.log("settings.update", request=request, entity="BranchSettings", entity_id=obj.pk, before=before, after=obj)
        return Response(s.data)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.GET.get("all") != "1":
            qs = qs.filter(created_at__gte=timezone.now() - timedelta(hours=24))
        if self.request.GET.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        return limit_list(self, qs, 200)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        n = Notification.objects.get(pk=pk, user=request.user)
        n.read_at = n.read_at or timezone.now()
        n.save(update_fields=["read_at"])
        return Response(NotificationSerializer(n).data)

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        Notification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"ok": True})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        since = timezone.now() - timedelta(hours=24)
        return Response({"count": Notification.objects.filter(user=request.user, read_at__isnull=True,
                                                              created_at__gte=since).count()})


class NotificationRuleViewSet(TenantViewSet):
    queryset = NotificationRule.objects.all()
    serializer_class = NotificationRuleSerializer
    perm_read = roles.SETTINGS_MANAGE
    perm_write = roles.SETTINGS_MANAGE
    branch_scoped = False

    def perform_create(self, serializer):
        serializer.save(business=current_business(self.request))


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, HasPerm]
    perm_read = roles.AUDIT_VIEW

    def get_queryset(self):
        user = self.request.user
        if user.is_platform:
            qs = AuditLog.objects.all()
        else:
            qs = AuditLog.objects.filter(business=current_business(self.request))
            if user.role in roles.BRANCH_SCOPED_ROLES:
                qs = qs.filter(branch=user.branch)
        g = self.request.GET
        if g.get("action"):
            qs = qs.filter(action__startswith=g["action"])
        if g.get("entity"):
            qs = qs.filter(entity=g["entity"], entity_id=g.get("entity_id", "")) if g.get("entity_id") else qs.filter(entity=g["entity"])
        if g.get("user"):
            qs = qs.filter(user_id=g["user"])
        if g.get("date_from"):
            qs = qs.filter(created_at__date__gte=g["date_from"])
        if g.get("date_to"):
            qs = qs.filter(created_at__date__lte=g["date_to"])
        return limit_list(self, qs.select_related("user"), 500)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def ping(request):
    import jetpos

    return Response({"ok": True, "version": jetpos.__version__, "time": timezone.now().isoformat()})


def make_slug(name):
    from .models import Business

    base = slugify(name.replace("ı", "i")) or "isletme"
    slug, i = base, 2
    while Business.objects.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


__all__ = ["BranchSettings", "status"]
