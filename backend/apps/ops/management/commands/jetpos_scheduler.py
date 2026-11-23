"""Periyodik görevler: yedek, saklama, geri yükleme testi, sağlık, yazdırma kuyruğu, senkronizasyon, hatırlatmalar,
zamanlanmış raporlar, lider kilidi yenileme ve destek kayıt imhası. Windows hizmeti olarak sürekli çalışır."""
import time
import traceback
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from apps.ops.models import BackupPolicy, BackupRecord, ScheduledTaskRun


def _run(name, fn):
    try:
        res = fn()
        ScheduledTaskRun.objects.create(name=name, ok=True, detail=str(res)[:2000])
        return True
    except Exception as e:
        ScheduledTaskRun.objects.create(name=name, ok=False, detail=f"{e}\n{traceback.format_exc()[-1500:]}")
        return False


def tick(now=None, state=None):
    from apps.licensing.services import purge_support_records, send_waiting_reminders
    from apps.modules.services import check_late_deliveries, send_reservation_reminders
    from apps.ops import backup, failover, health, sync
    from apps.printing.services import retry_pending
    from apps.reports.services import run_due_schedules

    state = state if state is not None else {}
    now = now or timezone.now()
    local = timezone.localtime(now)
    _run("print_retry", retry_pending)
    _run("late_deliveries", check_late_deliveries)
    _run("reservation_reminders", send_reservation_reminders)
    _run("report_schedules", run_due_schedules)
    if settings.JETPOS["ENFORCE_WRITER_FENCE"]:
        _run("writer_lease", lambda: failover.acquire_or_renew(settings.JETPOS["NODE_ID"]).token)
    if state.get("health_at") is None or now - state["health_at"] > timedelta(minutes=5):
        _run("health", lambda: health.snapshot().id)
        _run("sync_push", sync.push_pending)
        from apps.integrations.services import push_outbox

        _run("jetmenu_push", push_outbox)
        state["health_at"] = now
    pol = BackupPolicy.get()
    today_auto = BackupRecord.objects.filter(kind__in=("daily", "weekly", "monthly"), created_at__date=local.date()).exists()
    if pol.enabled and not today_auto and local.time() >= pol.daily_time:
        def do_backup():
            rec = backup.create_backup(backup.scheduled_kind(now))
            backup.verify_backup(rec)
            backup.apply_retention()
            return rec.name
        _run("backup", do_backup)
    last_test = BackupRecord.objects.filter(restore_tested_at__isnull=False).order_by("-restore_tested_at").first()
    if pol.enabled and (last_test is None or now - last_test.restore_tested_at > timedelta(days=pol.restore_test_days)):
        latest = BackupRecord.objects.filter(status="ok", deleted_at__isnull=True).first()
        if latest and local.hour in (3, 4, 5):
            _run("restore_test", lambda: backup.restore_test(latest))
    if state.get("daily_at") != local.date():
        _run("support_reminders", send_waiting_reminders)
        _run("support_purge", purge_support_records)
        state["daily_at"] = local.date()
    return state


class Command(BaseCommand):
    help = "POSHANE periyodik görev zamanlayıcısı"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=30)

    def handle(self, *args, **opts):
        state = {}
        while True:
            close_old_connections()
            state = tick(state=state)
            if opts["once"]:
                self.stdout.write("tick tamamlandı")
                return
            time.sleep(opts["interval"])
