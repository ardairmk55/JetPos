from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.ops import backup
from apps.ops.models import BackupRecord


class Command(BaseCommand):
    help = "Yedek al / doğrula / geri yükleme testi yap"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["create", "verify", "restore-test", "list"])
        parser.add_argument("--name")

    def handle(self, *args, **o):
        if o["action"] == "create":
            rec = backup.create_backup("manual")
            ok = backup.verify_backup(rec)
            self.stdout.write(f"{rec.name} ({rec.size} bayt) doğrulama: {'OK' if ok else 'HATA'}")
        elif o["action"] == "list":
            for r in BackupRecord.objects.filter(deleted_at__isnull=True):
                self.stdout.write(f"{timezone.localtime(r.created_at):%Y-%m-%d %H:%M} {r.kind:12} {r.name} verify={r.verify_ok} restore_test={r.restore_test_ok}")
        else:
            rec = BackupRecord.objects.get(name=o["name"]) if o["name"] else BackupRecord.objects.filter(status="ok").first()
            if o["action"] == "verify":
                self.stdout.write("OK" if backup.verify_backup(rec) else "HATA")
            else:
                ok = backup.restore_test(rec)
                self.stdout.write(("OK " if ok else "HATA ") + rec.name)
                if not ok:
                    self.stdout.write(rec.restore_test_log)
