from django.core.management.base import BaseCommand, CommandError

from apps.core.exceptions import BusinessError
from apps.core.models import User
from apps.ops import updates
from apps.ops.models import UpdateRecord


class Command(BaseCommand):
    help = "USB/offline güncelleme: stage (imza doğrula) / apply (yedek + sağlık testi + rollback) / rollback / list"

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["stage", "apply", "rollback", "list"])
        parser.add_argument("--package")
        parser.add_argument("--signature", help="İmza dosyası yolu")
        parser.add_argument("--id", type=int)
        parser.add_argument("--latest", action="store_true")
        parser.add_argument("--yes", action="store_true", help="Yönetici onayını komut satırında ver")

    def handle(self, *args, **o):
        actor = User.objects.filter(role__in=["owner", "platform_admin", "tech"], is_active=True).order_by("id").first()
        try:
            if o["action"] == "list":
                self.stdout.write(f"Aktif sürüm: {updates.current_version()}")
                for r in UpdateRecord.objects.all()[:20]:
                    self.stdout.write(f"#{r.id} {r.from_version} -> {r.version} {r.status} imza={r.signature_ok} sağlık={r.health_ok}")
                return
            if o["action"] == "stage":
                if not o["package"] or not o["signature"]:
                    raise CommandError("--package ve --signature gerekli")
                with open(o["signature"], encoding="utf-8") as f:
                    sig = f.read()
                r = updates.stage_package(o["package"], sig, source="usb", user=actor)
                self.stdout.write(self.style.SUCCESS(f"Doğrulandı: #{r.id} sürüm {r.version} sha256={r.sha256[:16]}…"))
                return
            r = UpdateRecord.objects.order_by("-id").first() if o["latest"] else UpdateRecord.objects.get(pk=o["id"])
            if o["action"] == "apply":
                if not o["yes"]:
                    raise CommandError("Uygulamak için --yes ile yönetici onayı verin")
                if r.status == "verified":
                    updates.approve(r, user=actor)
                r = updates.apply(r, user=actor)
                self.stdout.write(r.log)
                if r.status != "applied":
                    raise CommandError("Sağlık testi başarısız; önceki sürüme geri dönüldü")
                self.stdout.write(self.style.SUCCESS(f"Sürüm {r.version} uygulandı"))
            elif o["action"] == "rollback":
                updates.rollback(r, user=actor)
                self.stdout.write(self.style.SUCCESS(f"Geri alındı → {r.from_version}"))
        except BusinessError as e:
            raise CommandError(e.message)
