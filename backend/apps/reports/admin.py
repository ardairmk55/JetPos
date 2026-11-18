from django.contrib import admin

from .models import ReportDelivery, ReportSchedule, ReportTemplate

admin.site.register(ReportTemplate)
admin.site.register(ReportSchedule)
admin.site.register(ReportDelivery)
