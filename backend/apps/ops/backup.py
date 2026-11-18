"""Şifreli yedekleme, bütünlük doğrulama, geri yükleme ve geri yükleme testi (§16.1, NFR-06)."""
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.exceptions import BusinessError

from .models import BackupPolicy, BackupRecord

EXCLUDE = ["contenttypes", "auth.permission", "sessions", "admin.logentry", "ops.backuprecord"]


def _key():
    p = settings.JETPOS["BACKUP_KEY_FILE"]
    if not p.exists():
        p.write_bytes(Fernet.generate_key())
    return p.read_bytes()


def _dir():
    d = Path(settings.JETPOS["BACKUP_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_json():
    buf = io.StringIO()
    call_command("dumpdata", exclude=EXCLUDE, natural_foreign=False, stdout=buf, indent=None)
    return buf.getvalue()


def create_backup(kind="manual", user=None, critical=False):
    ts = timezone.localtime().strftime("%Y%m%d_%H%M%S_%f")
    name = f"jetpos_{kind}_{ts}_{settings.JETPOS['NODE_ID']}.jbk"
    path = _dir() / name
    try:
        raw = dump_json().encode("utf-8")
        counts = dict(Counter(o["model"] for o in json.loads(raw)))
        enc = Fernet(_key()).encrypt(gzip.compress(raw))
        path.write_bytes(enc)
        digest = _sha(path)
    except Exception as e:
        rec = BackupRecord.objects.create(name=name, kind=kind, path=str(path), sha256="", status="failed",
                                          error=str(e), created_by=user)
        audit.log("backup.failed", user=user, entity="BackupRecord", entity_id=rec.pk, reason=str(e))
        raise BusinessError(f"Yedek alınamadı: {e}", code="backup_failed")
    mirrors = []
    for m in settings.JETPOS["BACKUP_MIRROR_DIRS"]:
        try:
            Path(m).mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, Path(m) / name)
            mirrors.append({"path": m, "ok": _sha(Path(m) / name) == digest})
        except OSError as e:
            mirrors.append({"path": m, "ok": False, "error": str(e)})
    rec = BackupRecord.objects.create(name=name, kind=kind, path=str(path), size=path.stat().st_size, sha256=digest,
                                      critical=critical or kind in ("pre_update", "pre_restore"), mirrors=mirrors,
                                      record_counts=counts, created_by=user,
                                      cloud_status="not_configured")
    audit.log("backup.create", user=user, entity="BackupRecord", entity_id=rec.pk,
              after={"name": name, "size": rec.size, "kind": kind})
    return rec


def _read(rec):
    p = Path(rec.path)
    if not p.exists():
        for m in rec.mirrors:
            alt = Path(m["path"]) / rec.name
            if alt.exists():
                p = alt
                break
        else:
            raise BusinessError("Yedek dosyası bulunamadı", code="backup_missing")
    if _sha(p) != rec.sha256:
        raise BusinessError("Yedek bütünlük kontrolü başarısız (SHA-256 uyuşmuyor)", code="backup_corrupt")
    try:
        return gzip.decompress(Fernet(_key()).decrypt(p.read_bytes()))
    except (InvalidToken, OSError) as e:
        raise BusinessError(f"Yedek çözülemedi: {e}", code="backup_corrupt")


def verify_backup(rec, user=None):
    try:
        data = json.loads(_read(rec))
        ok = isinstance(data, list) and len(data) > 0
        err = "" if ok else "Boş yedek"
    except BusinessError as e:
        ok, err = False, e.message
    rec.verified_at = timezone.now()
    rec.verify_ok = ok
    rec.error = err
    rec.save(update_fields=["verified_at", "verify_ok", "error"])
    audit.log("backup.verify", user=user, entity="BackupRecord", entity_id=rec.pk, after={"ok": ok, "error": err})
    return ok


def restore_test(rec, user=None, timeout=600):
    """Yedeği geçici bir SQLite veritabanına gerçekten geri yükler ve kayıt sayılarını karşılaştırır."""
    raw = _read(rec)
    tmp = Path(tempfile.mkdtemp(prefix="jetpos_rt_"))
    try:
        fixture = tmp / "data.json"
        fixture.write_bytes(raw)
        db = tmp / "restore_test.sqlite3"
        env = dict(os.environ)
        env["DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
        env["JETPOS_DATA_DIR"] = str(tmp / "data")
        env["DJANGO_SETTINGS_MODULE"] = "jetpos.settings"
        manage = Path(settings.BASE_DIR) / "manage.py"
        log = []
        for args in (["migrate", "--noinput"], ["loaddata", str(fixture)]):
            r = subprocess.run([sys.executable, str(manage), *args], env=env, capture_output=True, text=True,
                               timeout=timeout, cwd=str(settings.BASE_DIR))
            log.append(f"$ {' '.join(args[:1])}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
            if r.returncode != 0:
                raise RuntimeError(f"{args[0]} başarısız")
        expected = sum(rec.record_counts.values()) if rec.record_counts else len(json.loads(raw))
        ok = f"Installed {expected} object" in log[-1]
        msg = "\n".join(log)
    except Exception as e:
        ok, msg = False, f"{e}\n" + ("\n".join(log) if "log" in locals() else "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rec.restore_tested_at = timezone.now()
    rec.restore_test_ok = ok
    rec.restore_test_log = msg[-8000:]
    rec.save(update_fields=["restore_tested_at", "restore_test_ok", "restore_test_log"])
    audit.log("backup.restore_test", user=user, entity="BackupRecord", entity_id=rec.pk, after={"ok": ok})
    return ok


CONFIRM_PHRASE = "GERI YUKLE"


def restore_backup(rec, user, confirm):
    """Canlı veritabanını yedekle değiştirir. Önce mevcut durumun yedeği alınır (veri kaybına karşı)."""
    if confirm != CONFIRM_PHRASE:
        raise BusinessError(f"Onay için '{CONFIRM_PHRASE}' yazılmalı", code="confirm_required")
    raw = _read(rec)
    json.loads(raw)
    pre = create_backup("pre_restore", user=user, critical=True)
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as f:
        f.write(raw)
        fixture = f.name
    try:
        with transaction.atomic():
            call_command("flush", "--noinput", verbosity=0)
            call_command("loaddata", fixture, verbosity=0)
    finally:
        os.unlink(fixture)
    BackupRecord.objects.update_or_create(name=pre.name, defaults={
        "kind": pre.kind, "path": pre.path, "size": pre.size, "sha256": pre.sha256, "critical": True,
        "record_counts": pre.record_counts, "mirrors": pre.mirrors})
    BackupRecord.objects.update_or_create(name=rec.name, defaults={
        "kind": rec.kind, "path": rec.path, "size": rec.size, "sha256": rec.sha256, "critical": rec.critical,
        "record_counts": rec.record_counts, "mirrors": rec.mirrors})
    audit.log("backup.restore", entity="BackupRecord", after={"restored": rec.name, "pre_restore": pre.name},
              reason=f"Geri yükleyen: {user.username if user else '-'}")
    return pre


def apply_retention():
    """Günlük/haftalık/aylık ayrı saklama; kritik yedekler korunur."""
    pol = BackupPolicy.get()
    removed = 0
    for kind, keep in (("daily", pol.keep_daily), ("weekly", pol.keep_weekly), ("monthly", pol.keep_monthly),
                       ("manual", None)):
        if keep is None:
            continue
        old = BackupRecord.objects.filter(kind=kind, critical=False, deleted_at__isnull=True,
                                          status="ok").order_by("-created_at")[keep:]
        for rec in old:
            for p in [Path(rec.path)] + [Path(m["path"]) / rec.name for m in rec.mirrors]:
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
            rec.deleted_at = timezone.now()
            rec.save(update_fields=["deleted_at"])
            removed += 1
    return removed


def scheduled_kind(now=None):
    now = timezone.localtime(now)
    if now.day == 1:
        return "monthly"
    if now.weekday() == 6:
        return "weekly"
    return "daily"
