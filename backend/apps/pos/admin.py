from django.contrib import admin

from .models import CashDay, Hall, Payment, Table, Ticket, TicketLine

admin.site.register(Hall)
admin.site.register(Table)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("number", "business_date", "branch", "table", "status", "total", "paid_total")
    list_filter = ("status", "branch")


admin.site.register(TicketLine)
admin.site.register(CashDay)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("txn_id", "ticket", "method", "amount", "refunded_amount", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
