from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.licensing import signing
from apps.ops.updates import build_package


class Command(BaseCommand):
    help = "İmzalı güncelleme paketi üretir (platform tarafı). Anahtar yoksa --init-key ile oluşturun."

    def add_arguments(self, parser):
        parser.add_argument("--version", required=False)
        parser.add_argument("--src", default=str(Path(settings.BASE_DIR).parent))
        parser.add_argument("--out", default=str(settings.DATA_DIR / "release_out"))
        parser.add_argument("--min-version")
        parser.add_argument("--init-key", action="store_true")

    def handle(self, *args, **o):
        priv = settings.DATA_DIR / "update_private.pem"
        if o["init_key"]:
            signing.generate_keypair(priv, settings.JETPOS["UPDATE_PUBLIC_KEY_FILE"])
            self.stdout.write(f"Anahtar çifti oluşturuldu: {priv} / {settings.JETPOS['UPDATE_PUBLIC_KEY_FILE']}")
            if not o["version"]:
                return
        if not o["version"]:
            raise CommandError("--version gerekli")
        if not priv.exists():
            raise CommandError("Özel anahtar yok; --init-key kullanın")
        z, sig = build_package(o["src"], o["version"], o["out"], priv, min_version=o["min_version"],
                               healthcheck=["backend/manage.py", "check"])
        self.stdout.write(f"Paket: {z}\nİmza: {z}.sig")
