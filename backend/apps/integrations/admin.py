from django.contrib import admin

from .models import IntegrationConfig, OutboxMessage, QrOrder

admin.site.register(IntegrationConfig)
admin.site.register(OutboxMessage)
admin.site.register(QrOrder)
