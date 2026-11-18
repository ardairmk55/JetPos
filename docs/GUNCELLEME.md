# JETPOS Güncelleme Kılavuzu

Şartname §18.2 ve NFR-07: sürüm kontrolü, imza/bütünlük doğrulama, güncelleme öncesi yedek, yönetici onayı, kurulum
sonrası sağlık kontrolü ve başarısızlıkta rollback.

## Akış
1. **Paket üretimi (platform tarafı)**
   ```powershell
   cd backend
   ..\.venv\Scripts\python manage.py jetpos_release --init-key            # bir kez: imza anahtar çifti
   ..\.venv\Scripts\python manage.py jetpos_release --version 1.1.0 --min-version 1.0.0
   ```
   Çıktı: `jetpos-1.1.0.zip` + `jetpos-1.1.0.zip.sig` (Ed25519). `update_public.pem` şube sunucularına dağıtılır.
2. **Yükleme ve doğrulama (şube)** — Sistem > Güncelleme: paket + imza yüklenir. İmza geçersizse, paket bozuksa,
   güvensiz dosya yolu içeriyorsa veya sürüm mevcut sürümden eski ise reddedilir.
3. **Yönetici onayı** — "Onayla". Onaysız paket uygulanamaz.
4. **Uygulama** — "Uygula": önce **kritik (silinmeyen) güncelleme öncesi yedek** alınır, paket
   `data/releases/<sürüm>` klasörüne açılır, `data/releases/current` yeni sürümü gösterir, manifest'teki sağlık
   kontrolü (`manage.py check`) çalışır. **Başarısızsa otomatik olarak önceki sürüme dönülür.**
5. **Yeniden başlatma** — `installer\start_server.ps1` aktif sürümü `releases\current` dosyasından okur.
6. **Manuel rollback** — Uygulanmış güncellemede "Geri al".

## USB / offline güncelleme
```powershell
cd installer
.\update_offline.ps1 -Package E:\jetpos-1.1.0.zip -Signature E:\jetpos-1.1.0.zip.sig
```
Aynı işlem komut satırından: `manage.py jetpos_update stage|apply|rollback|list`.

## Şube bazında dağıtım ve sürüm geçmişi
Her şube sunucusu kendi güncelleme kaydını (Sistem > Güncelleme geçmişi) tutar. Merkezden otomatik dağıtım için
`JETPOS_CENTRAL_URL` ile merkezi güncelleme sunucusu gerekir (dış altyapı; şartnamede tanımlı değil).

## Veritabanı
Yeni sürüm migration içeriyorsa `start_server.ps1` başlarken `migrate` çalıştırır. Güncelleme öncesi yedek, gerekirse
Sistem > Yedekler > "Geri yükle" ile geri dönüş sağlar (onay ifadesi: `GERI YUKLE`; geri yükleme öncesinde de otomatik
yedek alınır).

## Yedekleme (özet)
- Otomatik: zamanlayıcı her gün belirlenen saatte günlük/haftalık/aylık yedek alır, doğrular ve saklama politikasını uygular.
- Şifreleme: Fernet (AES-128-CBC + HMAC); anahtar `data/backup.key`. **Bu anahtarı sunucu dışında güvenli yerde saklayın**;
  anahtarsız yedek açılamaz.
- Bütünlük: SHA-256. Geri yükleme testi: yedek geçici bir veritabanına gerçekten geri yüklenir ve kayıt sayısı doğrulanır.
- Harici disk/NAS: `JETPOS_BACKUP_MIRRORS`. Bulut yedek hedefi dış servis bilgisi gerektirir.
- RPO/RTO ve varsayılan saklama süreleri **açık karar**dır; Sistem > Yedekler > Saklama politikası'ndan ayarlanır.
