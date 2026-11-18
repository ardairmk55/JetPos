from django.contrib import admin

from .models import BackupRecord, FailoverEvent, HealthSnapshot, UpdateRecord, WriterLease

admin.site.register(BackupRecord)
admin.site.register(HealthSnapshot)
admin.site.register(UpdateRecord)
admin.site.register(WriterLease)
admin.site.register(FailoverEvent)
