"""Rol ve yetki matrisi (şartname §2, §2.1, §15.1).

Yetkiler kod içinde tanımlıdır; sunucu tarafında her API çağrısında zorunlu tutulur.
"""

# Platform rolleri (işletmeye bağlı değildir)
PLATFORM_ADMIN = "platform_admin"
TECH = "tech"
SUPPORT = "support"
LICENSE_ADMIN = "license_admin"
FINANCE_ADMIN = "finance_admin"
# İşletme rolleri
OWNER = "owner"
BRANCH_MANAGER = "branch_manager"
CASHIER = "cashier"
WAITER = "waiter"
KITCHEN = "kitchen"
STOCK = "stock"

ROLE_CHOICES = [
    (PLATFORM_ADMIN, "Platform sistem yöneticisi"),
    (TECH, "Teknik ekip"),
    (SUPPORT, "Teknik destek"),
    (LICENSE_ADMIN, "Lisans yöneticisi"),
    (FINANCE_ADMIN, "Finans yöneticisi"),
    (OWNER, "İşletme sahibi"),
    (BRANCH_MANAGER, "Şube yöneticisi"),
    (CASHIER, "Kasiyer"),
    (WAITER, "Garson"),
    (KITCHEN, "Mutfak personeli"),
    (STOCK, "Stok personeli"),
]
PLATFORM_ROLES = {PLATFORM_ADMIN, TECH, SUPPORT, LICENSE_ADMIN, FINANCE_ADMIN}
BUSINESS_ROLES = {OWNER, BRANCH_MANAGER, CASHIER, WAITER, KITCHEN, STOCK}

FLOOR_VIEW = "floor.view"
FLOOR_MANAGE = "floor.manage"
TICKET_OPEN = "ticket.open"
TICKET_ADD = "ticket.add"
TICKET_SEND = "ticket.send"
TICKET_BILL = "ticket.request_bill"
TICKET_DISCOUNT = "ticket.discount"
TICKET_VOID = "ticket.void"
TICKET_MOVE = "ticket.move"
TICKET_PRICE_OVERRIDE = "ticket.price_override"
READY_VIEW = "ready.view"
PAYMENT_TAKE = "payment.take"
PAYMENT_REFUND = "payment.refund"
CASH_MANAGE = "cash.manage"
CASH_APPROVE = "cash.approve"
KDS_VIEW = "kds.view"
KDS_MANAGE = "kds.manage"
CATALOG_MANAGE = "catalog.manage"
STOCK_VIEW = "stock.view"
STOCK_MANAGE = "stock.manage"
REPORTS_VIEW = "reports.view"
USERS_MANAGE = "users.manage"
SETTINGS_MANAGE = "settings.manage"
APPROVALS_DECIDE = "approvals.decide"
APPROVALS_MUNICIPAL = "approvals.municipal"
CRM_MANAGE = "crm.manage"
DELIVERY_MANAGE = "delivery.manage"
RESERVATION_MANAGE = "reservation.manage"
STAFF_MANAGE = "staff.manage"
FINANCE_MANAGE = "finance.manage"
PRINTERS_MANAGE = "printers.manage"
AUDIT_VIEW = "audit.view"
OPS_MANAGE = "ops.manage"
PLATFORM_MANAGE = "platform.manage"
LICENSE_MANAGE = "license.manage"
SUPPORT_MANAGE = "support.manage"
SUPPORT_REQUEST = "support.request"
PLATFORM_FINANCE = "platform.finance"
HEALTH_VIEW = "health.view"

_MANAGER = {
    FLOOR_VIEW, FLOOR_MANAGE, TICKET_OPEN, TICKET_ADD, TICKET_SEND, TICKET_BILL, TICKET_DISCOUNT,
    TICKET_VOID, TICKET_MOVE, TICKET_PRICE_OVERRIDE, READY_VIEW, PAYMENT_TAKE, PAYMENT_REFUND,
    CASH_MANAGE, CASH_APPROVE, KDS_VIEW, KDS_MANAGE, CATALOG_MANAGE, STOCK_VIEW, STOCK_MANAGE,
    REPORTS_VIEW, USERS_MANAGE, SETTINGS_MANAGE, APPROVALS_DECIDE, APPROVALS_MUNICIPAL, CRM_MANAGE,
    DELIVERY_MANAGE, RESERVATION_MANAGE, STAFF_MANAGE, FINANCE_MANAGE, PRINTERS_MANAGE, AUDIT_VIEW,
    SUPPORT_REQUEST, OPS_MANAGE, HEALTH_VIEW,
}

ROLE_PERMISSIONS = {
    OWNER: set(_MANAGER),
    BRANCH_MANAGER: set(_MANAGER),
    CASHIER: {
        FLOOR_VIEW, TICKET_OPEN, TICKET_ADD, TICKET_SEND, TICKET_BILL, TICKET_MOVE, READY_VIEW,
        PAYMENT_TAKE, CASH_MANAGE, APPROVALS_MUNICIPAL, CRM_MANAGE, DELIVERY_MANAGE, RESERVATION_MANAGE,
    },
    # §2.1: Garson indirim, iptal, fiyat değişikliği ve kasa işlemi yapamaz.
    WAITER: {FLOOR_VIEW, TICKET_OPEN, TICKET_ADD, TICKET_SEND, TICKET_BILL, READY_VIEW},
    KITCHEN: {KDS_VIEW},
    STOCK: {STOCK_VIEW, STOCK_MANAGE},
    PLATFORM_ADMIN: {PLATFORM_MANAGE, LICENSE_MANAGE, SUPPORT_MANAGE, PLATFORM_FINANCE, HEALTH_VIEW, AUDIT_VIEW, OPS_MANAGE},
    TECH: {HEALTH_VIEW, OPS_MANAGE, SUPPORT_MANAGE},
    SUPPORT: {SUPPORT_MANAGE, HEALTH_VIEW},
    LICENSE_ADMIN: {LICENSE_MANAGE},
    FINANCE_ADMIN: {PLATFORM_FINANCE},
}

# Şube yöneticisi yalnızca atanmış şubeyi görür; sahip tüm şubeleri.
BRANCH_SCOPED_ROLES = {BRANCH_MANAGER, CASHIER, WAITER, KITCHEN, STOCK}


def has_perm(user, perm):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser and user.role in PLATFORM_ROLES:
        return True
    return perm in ROLE_PERMISSIONS.get(user.role, set())


def perms_for(user):
    return sorted(ROLE_PERMISSIONS.get(getattr(user, "role", ""), set()))
