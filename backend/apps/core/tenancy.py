"""Tenant ve şube izolasyonu (NFR-03): tüm sorgular sunucu tarafında kapsamlanır."""
from django.core.exceptions import PermissionDenied
from rest_framework import permissions, viewsets

from . import audit, roles
from .models import Branch


def current_business(request):
    if getattr(request, "business", None) is not None:
        return request.business
    user = request.user
    biz = getattr(user, "business", None)
    if biz is None:
        grant = getattr(request, "support_grant", None)
        biz = grant.business if grant else None
    request.business = biz
    return biz


def current_branch(request, required=True):
    if getattr(request, "branch", None) is not None:
        return request.branch
    user = request.user
    biz = current_business(request)
    branch = None
    if biz is not None:
        if user.role in roles.BRANCH_SCOPED_ROLES:
            branch = user.branch if user.branch and user.branch.business_id == biz.id else None
        else:
            qs = Branch.objects.filter(business=biz, is_active=True)
            bid = request.headers.get("X-Branch") or request.GET.get("branch") or request.session.get("branch_id")
            if bid and str(bid).isdigit():
                branch = qs.filter(pk=int(bid)).first()
            if branch is None:
                branch = (user.branch if user.branch_id and user.branch.business_id == biz.id else None) or qs.order_by("id").first()
    if branch is None and required:
        raise PermissionDenied("Şube bağlamı bulunamadı")
    request.branch = branch
    return branch


class HasPerm(permissions.BasePermission):
    """View üzerinde `perm_read`, `perm_write` ve `perm_actions` ile tanımlanır."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        action = getattr(view, "action", None)
        action_perms = getattr(view, "perm_actions", {}) or {}
        if action in action_perms:
            needed = action_perms[action]
        elif request.method in permissions.SAFE_METHODS:
            needed = getattr(view, "perm_read", None)
        else:
            needed = getattr(view, "perm_write", None)
        if needed is None:
            return True
        if isinstance(needed, (list, tuple, set)):
            return any(roles.has_perm(request.user, p) for p in needed)
        return roles.has_perm(request.user, needed)


class TenantViewSet(viewsets.ModelViewSet):
    """İşletme (ve isteğe bağlı şube) kapsamlı CRUD + audit."""

    permission_classes = [permissions.IsAuthenticated, HasPerm]
    branch_scoped = True
    branch_nullable = False  # True: şubesiz (işletme geneli) kayıtlar da görünür
    audit_entity = None
    search_fields_simple = ()
    ordering = ("-id",)

    def base_queryset(self):
        return self.queryset.model.objects.all()

    def get_queryset(self):
        biz = current_business(self.request)
        if biz is None:
            return self.base_queryset().none()
        qs = self.base_queryset().filter(business=biz)
        if self.branch_scoped:
            branch = current_branch(self.request)
            if self.branch_nullable:
                from django.db.models import Q

                qs = qs.filter(Q(branch=branch) | Q(branch__isnull=True))
            else:
                qs = qs.filter(branch=branch)
        q = self.request.GET.get("q")
        if q and self.search_fields_simple:
            from django.db.models import Q

            cond = Q()
            for f in self.search_fields_simple:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return qs.order_by(*self.ordering)

    def _entity(self):
        return self.audit_entity or self.queryset.model.__name__

    def perform_create(self, serializer):
        kwargs = {"business": current_business(self.request)}
        if self.branch_scoped and "branch" not in serializer.validated_data:
            kwargs["branch"] = current_branch(self.request)
        obj = serializer.save(**kwargs)
        audit.log(f"{self._entity().lower()}.create", request=self.request, entity=self._entity(), entity_id=obj.pk,
                  after=obj)

    def perform_update(self, serializer):
        before = audit.snapshot(serializer.instance)
        obj = serializer.save()
        audit.log(f"{self._entity().lower()}.update", request=self.request, entity=self._entity(), entity_id=obj.pk,
                  before=before, after=obj, reason=self.request.data.get("reason", "") if hasattr(self.request.data, "get") else "")

    def perform_destroy(self, instance):
        before = audit.snapshot(instance)
        pk = instance.pk
        if hasattr(instance, "is_active"):
            instance.is_active = False
            instance.save(update_fields=["is_active"])
        else:
            instance.delete()
        audit.log(f"{self._entity().lower()}.delete", request=self.request, entity=self._entity(), entity_id=pk,
                  before=before)


def validate_same_business(request, *objs):
    biz = current_business(request)
    for o in objs:
        if o is not None and getattr(o, "business_id", biz.id) != biz.id:
            raise PermissionDenied("Farklı işletmeye ait kayıt")


def limit_list(view, qs, n):
    """Liste yanıtını sınırlar; detay aksiyonlarında (get_object) dilimlenmemiş sorgu döner."""
    return qs[:n] if getattr(view, "action", None) == "list" else qs
