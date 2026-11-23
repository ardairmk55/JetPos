# POSHANE Kurulum Kılavuzu

## 1. Gereksinimler
| Bileşen | Gereksinim |
|---|---|
| Sunucu işletim sistemi | Windows Server veya Windows 10/11 (şartname §13). Sürüm/lisans matrisi **açık karar**dır. |
| Python | 3.11+ (3.12 ile test edildi) |
| Veritabanı | PostgreSQL 14+ önerilir. SQLite yalnızca geliştirme/deneme içindir. |
| Ağ | Kasa, mutfak ve garson cihazları aynı yerel ağda (LAN/Wi-Fi) olmalıdır. İnternet yalnızca e-posta, bulut yedek, merkez senkronizasyonu ve online lisans aktivasyonu için gerekir. |
| Donanım | Kapasite/eşzamanlı kullanıcı matrisi **açık karar**dır (şartname §13.2). Küçük işletmede kasa PC sunucu olabilir. |

## 2. Akıllı kurulum (önerilen)
Yönetici PowerShell'de proje klasöründe:

```powershell
cd installer
.\install.ps1 -DatabaseUrl "postgres://jetpos:GUCLU_SIFRE@localhost:5432/jetpos" -RegisterTasks -OpenFirewall
```

Betik: sanal ortam + bağımlılıklar, `jetpos.env` yapılandırması, migration'lar, statik dosyalar, (isteğe bağlı)
güvenlik duvarında **yalnızca özel/etki alanı ağı** için port kuralı, sunucu ve zamanlayıcının açılışta otomatik
başlaması. Sonunda yerel ağ adresini yazar.

İlk açılışta **kurulum sihirbazı** çalışır: işletme → şube/salon → masa → kullanıcı/rol → menü/vergi → yazıcı →
kasa/ödeme → yedek/güvenlik → son kontrol. Şablonlar: restoran, kafe, kahvaltı salonu, belediye sosyal tesisi, diğer.

> POSHANE hazır KDV oranı varsaymaz; sihirbaz oranları sorar. Mevzuata uygun oranları mali müşavirinizle doğrulayın.

## 3. Manuel / teknik kurulum
```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
$env:DATABASE_URL="postgres://jetpos:...@localhost:5432/jetpos"
$env:JETPOS_DATA_DIR="D:\POSHANE\data"
cd backend
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py collectstatic --noinput
..\.venv\Scripts\python -m daphne -b 0.0.0.0 -p 8000 jetpos.asgi:application   # HTTP + WebSocket
..\.venv\Scripts\python manage.py jetpos_scheduler                              # ayrı pencerede: periyodik görevler
```

PostgreSQL:
```sql
CREATE USER jetpos WITH PASSWORD 'GUCLU_SIFRE';
CREATE DATABASE jetpos OWNER jetpos ENCODING 'UTF8';
```

## 4. Ortam değişkenleri (`jetpos.env`)
| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `DATABASE_URL` | Veritabanı bağlantısı | `backend/data/jetpos.sqlite3` |
| `JETPOS_DATA_DIR` | Veri klasörü (yedek, anahtar, log, yazdırma kuyruğu) | `backend/data` |
| `JETPOS_NODE_ID` | Sunucu düğüm adı (yedeklilik) | `node-1` |
| `JETPOS_PORT` | Dinleme portu (betikler) | `8000` |
| `JETPOS_ALLOWED_HOSTS` | İzinli host adları | `*` |
| `JETPOS_HTTPS` | HTTPS ters vekil arkasındaysa `1` (güvenli çerez) | kapalı |
| `JETPOS_SECRET_KEY` | Django gizli anahtarı | ilk açılışta `data/secret.key` üretilir |
| `JETPOS_SMTP_HOST/PORT/USER/PASSWORD/TLS` | E-posta (bildirim, zamanlanmış rapor) | tanımsızsa e-postalar `data/outbox_mail` klasörüne yazılır |
| `JETPOS_BACKUP_DIR` | Yedek klasörü | `data/backups` |
| `JETPOS_BACKUP_MIRRORS` | Harici disk/NAS kopya klasörleri (`;` ile) | yok |
| `JETPOS_CENTRAL_URL`, `JETPOS_CENTRAL_TOKEN` | Merkez platform adresi ve paylaşılan anahtar | yok → olaylar kuyrukta bekler |
| `JETPOS_LICENSE_PUBKEY` | Lisans doğrulama açık anahtarı | `data/license_public.pem` |
| `JETPOS_UPDATE_PUBKEY` | Güncelleme imza açık anahtarı | `data/update_public.pem` |
| `JETPOS_ENFORCE_WRITER_FENCE` | Yedekli kurulumda tek yazıcı lider kilidi | kapalı |
| `JETPOS_RATE_LIMIT`, `JETPOS_LOGIN_RATE_LIMIT` | Dakika başı API/giriş limiti | 600 / 20 |

## 5. İstemciler
| Cihaz | Kullanım |
|---|---|
| Kasa PC / Windows tablet | Tarayıcı veya Electron uygulaması: hazır paket `desktop\dist\POSHANE-win32-x64\POSHANE.exe` (klasörü kopyalayın; ilk açılışta sunucu adresi sorulur). Yeniden üretmek: `cd desktop && npm install && npm run package` |
| Mutfak ekranı (KDS) | `POSHANE.exe --kds` (tam ekran kiosk) veya tarayıcıda `/kds` |
| Garson telefonu | Tarayıcıda sunucu adresi → "Ana ekrana ekle" (PWA). Ağ koparsa siparişler cihazda kuyruğa alınır. |
| Yönetici | Tarayıcı (web panel) |

> Tarayıcı kapalıyken mobil push için VAPID/FCM gibi dış servis bilgisi gerekir (şartnamede yok). Uygulama açıkken
> bildirimler yerel ağ üzerinden sesli/görsel gelir.

## 6. Yazıcılar
Yazıcılar ekranı. Bağlantı: **Ağ (TCP 9100, ESC/POS)**, **Windows yazıcı** (USB/sürücü; `pywin32`), **Dosya** (sanal/test).
58/80 mm, CP857 Türkçe, kategori/istasyon yönlendirme, yedek yazıcı, tekrar deneme, test baskısı, bağlantı testi.
Epson TM, Xprinter, Bixolon, Star, HPRT, SNBC modellerinin her biri sahada **ayrıca test edilmelidir** (NFR-11).

## 7. Lisans
- Platform tarafı imza anahtarı ilk lisans üretiminde `data/license_private.pem` olarak oluşur. **Özel anahtar yalnızca
  platform sunucusunda kalmalıdır**; şube sunucusuna yalnızca `license_public.pem` kopyalanır.
- Platform > Lisanslar: online anahtar + indirilebilir imzalı `.jetlic` (QR ile okutulabilir metin). Şube: Ayarlar >
  Lisans ve cihazlar. İlk aktivasyon sonrası doğrulama internetsiz yapılır.
- Paket fiyatları ve şube/kullanıcı/cihaz limitleri **açık karar**dır; lisans üretilirken tek tek girilir.

## 8. Değerlendirme (DEMO)
`manage.py jetpos_demo` boş veritabanına örnek işletme, menü, masa, kullanıcı ve tam modüllü lisans oluşturur.
Demo hesapları `backend/apps/core/management/commands/jetpos_demo.py` dosyasının başında. Üretimde kullanmayın.
