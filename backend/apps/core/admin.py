from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, Branch, BranchSettings, Business, Device, LoginAttempt, User


@admin.register(User)
class JetUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("POSHANE", {"fields": ("business", "branch", "role", "phone", "department")}),)
    list_display = ("username", "first_name", "last_name", "role", "business", "branch", "is_active")
    list_filter = ("role", "is_active", "business")


admin.site.register(Business)
admin.site.register(Branch)
admin.site.register(BranchSettings)
admin.site.register(Device)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity", "entity_id", "user", "business")
    list_filter = ("action",)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display = ("created_at", "username", "method", "success", "ip")

    def has_change_permission(self, request, obj=None):
        return False
