from rest_framework import serializers

from . import roles
from .models import AuditLog, Branch, BranchSettings, Business, Notification, NotificationRule, User


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["id", "name", "slug", "template", "tax_office", "tax_number", "phone", "email", "is_active",
                  "is_corporate", "created_at"]
        read_only_fields = ["slug", "created_at"]


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ["id", "name", "code", "address", "phone", "is_active", "created_at"]


class BranchSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchSettings
        exclude = ["branch"]


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    pin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    has_pin = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "phone", "department", "role", "role_label",
                  "branch", "branch_name", "is_active", "password", "pin", "has_pin", "language", "theme",
                  "deactivated_at", "last_login"]
        read_only_fields = ["deactivated_at", "last_login", "is_active"]

    def get_has_pin(self, obj):
        return bool(obj.pin_hash)

    def validate_role(self, value):
        actor = self.context["request"].user
        if value in roles.PLATFORM_ROLES:
            raise serializers.ValidationError("İşletme kullanıcısına platform rolü verilemez")
        if actor.role == roles.BRANCH_MANAGER and value in (roles.OWNER, roles.BRANCH_MANAGER):
            raise serializers.ValidationError("Şube yöneticisi bu rolü atayamaz")
        return value

    def validate_password(self, value):
        if value:
            from django.contrib.auth.password_validation import validate_password

            validate_password(value)
        return value

    def create(self, validated):
        pw = validated.pop("password", "")
        pin = validated.pop("pin", "")
        if not pw:
            raise serializers.ValidationError({"password": "Şifre zorunludur"})
        user = User(**validated)
        user.set_password(pw)
        if pin:
            user.set_pin(pin)
        user.save()
        return user

    def update(self, instance, validated):
        pw = validated.pop("password", "")
        pin = validated.pop("pin", "")
        for k, v in validated.items():
            setattr(instance, k, v)
        if pw:
            instance.set_password(pw)
        if pin:
            instance.set_pin(pin)
        instance.save()
        return instance


class MeSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "role", "role_label", "language", "theme",
                  "font_scale", "high_contrast", "branch", "business"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "event", "title", "body", "priority", "data", "read_at", "created_at"]


class NotificationRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationRule
        exclude = ["business"]


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.username", default="", read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "action", "entity", "entity_id", "before", "after", "reason", "ip", "device", "user",
                  "user_name", "branch", "support_session", "created_at"]
