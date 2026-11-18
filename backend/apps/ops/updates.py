"""Akıllı güncelleme: imza/bütünlük doğrulama, yedek, yönetici onayı, sağlık kontrolü ve rollback (§18.2, NFR-07).

Paket biçimi: `jetpos-<sürüm>.zip` (+ `.sig` Ed25519 imzası). Zip içinde `manifest.json`:
{"version": "1.1.0", "min_version": "1.0.0", "healthcheck": ["backend/manage.py", "check"]}
Sürümler `RELEASES_DIR/<sürüm>` altına açılır; `RELEASES_DIR/current` aktif sürümü gösterir.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

import jetpos
from apps.core import audit
from apps.core.exceptions import BusinessError
from apps.licensing import signing

from .models import UpdateRecord


def _vt(v):
    return tuple(int(x) for x in str(v).split(".") if x.isdigit())


def releases_dir():
    d = Path(settings.JETPOS["RELEASES_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    return d


def current_version():
    p = releases_dir() / "current"
    return p.read_text(encoding="utf-8").strip() if p.exists() else jetpos.__version__


def stage_package(zip_path, sig, *, source="upload", user=None):
    zip_path = Path(zip_path)
    data = zip_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    pub = settings.JETPOS["UPDATE_PUBLIC_KEY_FILE"]
    if not pub.exists():
        raise BusinessError("Güncelleme imza doğrulama anahtarı kurulu değil", code="no_update_key")
    ok = signing.verify_bytes(data, sig.strip(), signing.load_public(pub))
    if not ok:
        audit.log("update.signature_failed", user=user, entity="UpdateRecord", after={"sha256": digest})
        raise BusinessError("Güncelleme paketi imzası geçersiz", code="bad_signature")
    try:
        with zipfile.ZipFile(zip_path) as z:
            manifest = json.loads(z.read("manifest.json"))
            for n in z.namelist():
                if n.startswith("/") or ".." in Path(n).parts:
                    raise BusinessError("Pakette güvensiz dosya yolu", code="bad_package")
    except (KeyError, zipfile.BadZipFile, json.JSONDecodeError):
        raise BusinessError("Paket bozuk veya manifest eksik", code="bad_package")
    cur = current_version()
    if _vt(manifest["version"]) <= _vt(cur):
        raise BusinessError(f"Paket sürümü ({manifest['version']}) mevcut sürümden ({cur}) yeni değil", code="old_version")
    if manifest.get("min_version") and _vt(cur) < _vt(manifest["min_version"]):
        raise BusinessError(f"Bu güncelleme en az {manifest['min_version']} gerektirir", code="min_version")
    store = releases_dir() / "packages"
    store.mkdir(exist_ok=True)
    dest = store / f"jetpos-{manifest['version']}.zip"
    if dest.resolve() != zip_path.resolve():
        shutil.copy2(zip_path, dest)
    rec = UpdateRecord.objects.create(version=manifest["version"], from_version=cur, package_path=str(dest),
                                      sha256=digest, signature_ok=True, manifest=manifest, source=source)
    audit.log("update.staged", user=user, entity="UpdateRecord", entity_id=rec.pk,
              after={"version": rec.version, "sha256": digest})
    return rec


def approve(rec, *, user):
    if rec.status != "verified":
        raise BusinessError("Güncelleme onaya hazır değil")
    rec.status = "approved"
    rec.approved_by = user
    rec.save(update_fields=["status", "approved_by"])
    audit.log("update.approved", user=user, entity="UpdateRecord", entity_id=rec.pk)
    return rec


def _healthcheck(release_dir, manifest):
    cmd = manifest.get("healthcheck")
    if not cmd:
        return True, "healthcheck tanımsız; dosya bütünlüğü doğrulandı"
    exe = [sys.executable, str(release_dir / cmd[0]), *cmd[1:]]
    try:
        r = subprocess.run(exe, capture_output=True, text=True, timeout=300, cwd=str(release_dir))
        return r.returncode == 0, (r.stdout + r.stderr)[-4000:]
    except Exception as e:
        return False, str(e)


def apply(rec, *, user):
    from .backup import create_backup

    if rec.status != "approved":
        raise BusinessError("Güncelleme yönetici onayı olmadan uygulanamaz", code="not_approved")
    pkg = Path(rec.package_path)
    if hashlib.sha256(pkg.read_bytes()).hexdigest() != rec.sha256:
        raise BusinessError("Paket onaydan sonra değişmiş", code="bad_package")
    rec.backup = create_backup("pre_update", user=user, critical=True)
    log = [f"Ön yedek: {rec.backup.name}"]
    rdir = releases_dir() / rec.version
    if rdir.exists():
        shutil.rmtree(rdir)
    with zipfile.ZipFile(pkg) as z:
        z.extractall(rdir)
    pointer = releases_dir() / "current"
    previous = current_version()
    pointer.write_text(rec.version, encoding="utf-8")
    log.append(f"Aktif sürüm: {previous} → {rec.version}")
    ok, out = _healthcheck(rdir, rec.manifest)
    log.append(f"Sağlık kontrolü: {'başarılı' if ok else 'BAŞARISIZ'}\n{out}")
    rec.health_ok = ok
    if ok:
        rec.status = "applied"
        rec.applied_at = timezone.now()
    else:
        pointer.write_text(previous, encoding="utf-8")
        rec.status = "rolled_back"
        log.append(f"Rollback: aktif sürüm {previous} olarak geri alındı")
    rec.log = "\n".join(log)[-10000:]
    rec.save()
    audit.log(f"update.{rec.status}", user=user, entity="UpdateRecord", entity_id=rec.pk,
              after={"version": rec.version, "health_ok": ok})
    return rec


def rollback(rec, *, user):
    if rec.status != "applied":
        raise BusinessError("Yalnızca uygulanmış güncelleme geri alınabilir")
    (releases_dir() / "current").write_text(rec.from_version, encoding="utf-8")
    rec.status = "rolled_back"
    rec.log += f"\nManuel rollback → {rec.from_version}"
    rec.save(update_fields=["status", "log"])
    audit.log("update.rolled_back", user=user, entity="UpdateRecord", entity_id=rec.pk)
    return rec


def build_package(src_dir, version, out_dir, private_key_path, min_version=None, healthcheck=None):
    """Platform tarafı paketleme aracı (imzalı)."""
    src_dir, out_dir = Path(src_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = out_dir / f"jetpos-{version}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        manifest = {"version": version, "min_version": min_version, "healthcheck": healthcheck,
                    "built_at": timezone.now().isoformat()}
        z.writestr("manifest.json", json.dumps(manifest))
        for p in src_dir.rglob("*"):
            if p.is_file() and not any(part in (".venv", "__pycache__", "data", "node_modules") for part in p.parts):
                z.write(p, p.relative_to(src_dir).as_posix())
    sig = signing.sign_bytes(zpath.read_bytes(), signing.load_private(private_key_path))
    (out_dir / f"jetpos-{version}.zip.sig").write_text(sig, encoding="utf-8")
    return zpath, sig
