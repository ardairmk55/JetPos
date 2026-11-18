# JETPOS Mimari

## Katmanlar
```
Tarayıcı / PWA / Electron  ──HTTP(S)+WebSocket──►  daphne (ASGI)
                                                    ├─ Django + DRF  (/api/…)
                                                    ├─ Channels      (/ws/branch/)  canlı masa/mutfak/bildirim
                                                    └─ WhiteNoise    (statik dosyalar, CDN yok)
                                                    ▼
                                                  PostgreSQL (şube yerel veritabanı)
jetpos_scheduler (ayrı süreç): yedek · saklama · geri yükleme testi · sağlık · yazdırma kuyruğu · senkronizasyon
                               · hatırlatmalar · zamanlanmış rapor · lider kilidi · destek kayıt imhası
```

## Uygulamalar (`backend/apps`)
| Uygulama | Sorumluluk |
|---|---|
| `core` | Tenant (işletme) / şube, kullanıcı + rol matrisi (`roles.py`), PIN, kilit, TOTP 2FA, değiştirilemez audit, idempotency, bildirim + WebSocket, rate limit, senkronizasyon olayları |
| `catalog` | Vergi, istasyon, kategori, ürün, seçenek grubu, kanal/şube/grup/zamanlı fiyat, fiyat geçmişi, müşteri grubu, kampanya motoru (`pricing.py`) |
| `pos` | Salon/masa, adisyon (tek aktif adisyon DB kısıtı), satır snapshot'ları, mutfak partisi + istasyon siparişi, onay talepleri, indirim, ödeme/bölüştürme/iade, kasa günü ve gün sonu (`services.py`) |
| `printing` | ESC/POS üretimi (CP857), ağ/Windows/dosya adaptörleri, yönlendirme, kuyruk, tekrar deneme, yedek yazıcı |
| `inventory` | Depo, tedarikçi, malzeme, reçete + birim dönüşümü, tek seferlik satış düşümü (`SaleDeduction`), ters hareket, mal kabul, transfer, sayım, fire |
| `modules` | CRM + KVKK (erişim kaydı, dışa aktarma, anonimleştirme), cari, kurye, rezervasyon/bekleme listesi, personel (vardiya, giriş-çıkış, mola, geç kalma, devamsızlık, fazla mesai, izin, performans), finans (gelir-gider, cari, ters kayıt, kârlılık) |
| `reports` | Hazır raporlar, özel rapor oluşturucu, karşılaştırma, PDF/Excel/CSV, şablon, zamanlanmış e-posta + retry, dashboard |
| `licensing` | Ed25519 imzalı offline lisans, modül/şube/cihaz hakları, cihaz transferi, müşteri portalı, başvuru/onay, destek talebi + SLA (iş saati/takvim saati, duraklatma, yeniden açma), onaylı uzaktan destek erişimi, şifreli ek + zararlı dosya taraması, kayıt imhası |
| `ops` | Şifreli yedek, doğrulama, gerçek geri yükleme testi, saklama, geri yükleme; sağlık/telemetri/tanılama; imzalı güncelleme + rollback; tek yazıcı lider kilidi (fencing) + failover/failback; merkez senkronizasyonu |
| `integrations` | JET Menü katalog/sipariş uçları, QR sipariş onayı, HMAC imzalı çıkış kuyruğu |
| `web` | SPA kabuğu, PWA (service worker), global arama, yardım merkezi (kural tabanlı), kurulum sihirbazı |

## Güvenlik ilkeleri
- **Tenant/şube izolasyonu (NFR-03)**: `TenantViewSet` tüm sorguları sunucu tarafında işletme ve şubeye göre kapsamlar; ilişkili alanlar `BizScopedPKField` ile başka işletmenin kaydını kabul etmez. Şube kapsamlı roller başka şubeye geçemez.
- **Yetki**: `roles.py` rol → yetki matrisi; her API'de `HasPerm`. Garson indirim/iptal/fiyat/kasa yapamaz; hassas işlemde yetkili PIN/şifre ile ek doğrulama veya onay talebi.
- **Denetim (NFR-04)**: `AuditLog` kaydedildikten sonra değiştirilemez/silinemez; düzeltme ters kayıtla. Finansal kayıtlarda önceki/sonraki tutar, aktör, zaman, gerekçe.
- **Idempotency (NFR-02)**: sipariş gönderimi, ödeme, iade `Idempotency-Key` zorunlu; ilk istek kaydı işlem öncesi oluşturulur (eşzamanlı tekrarlar 409). Satır eklemede `client_uid`.
- **Kimlik**: PBKDF2 parola hash, PIN hash, başarısız giriş kaydı + hesap kilidi, şüpheli IP uyarısı, hareketsizlik kilidi (sunucu tarafında da uygulanır), platform hesaplarında TOTP 2FA, rate limit.
- **Destek erişimi**: müşteri onayı, süre sınırı, kapsam (okuma/ayar/katalog/yazıcı/ops), anonim veri varsayılan, anında iptal, her istek `SupportActionLog`'a, başlangıç/bitiş audit'e.
- **Şifreleme**: yedekler ve destek ekleri Fernet ile; aktarımda HTTPS için ters vekil (IIS/Caddy) önerilir (`JETPOS_HTTPS=1`). Sertifika/ağ keşif yöntemi açık karardır.

## Çevrimdışı ve senkronizasyon (§14)
- İnternet kesilse de LAN'daki tüm istemciler yerel sunucuyla çalışır; WebSocket bildirimleri LAN'dadır.
- Garson cihazı sunucuya ulaşamazsa sipariş işlemleri IndexedDB kuyruğuna alınır, ekranda "Kuyrukta — gönderilmedi" gösterilir; bağlantı gelince aynı idempotency anahtarı/`client_uid` ile gönderilir (çift kayıt yok).
- Şube → merkez: değişmez `SyncEvent` (UUID, cihaz, şube, kullanıcı, zaman); merkez `CentralInbox` olay kimliğiyle idempotent kabul eder; başarısızlar kuyrukta izlenir.
- Çakışma algoritması, cihaz kuyruğu kapasitesi ve şube senkronizasyon önceliği **açık teknik karar**dır; mevcut uygulama "değişmez olay + idempotent alım" yaklaşımını kullanır.

## Yedeklilik (§16.2)
`WriterLease` tek satırlık lider kilidi + monoton artan **fencing token**. Yazma isteklerinde (`JETPOS_ENFORCE_WRITER_FENCE`)
yalnızca kilidi tutan ve izole edilmemiş düğüm yazabilir. Failover yalnızca: kilit süresi dolmuş **ve** eski düğüm izole
edilmiş **ve** hedef sağlıklı ise mümkündür; tüm güvenlik koşulları (sessizlik ≥2× süre, son 24 saatte doğrulanmış yedek,
otomatik mod) sağlanmazsa yönetici onayı gerekir. Failback sağlık, veri eşitleme ve tutarlılık teyidi olmadan durur.
Veritabanı replikasyonunun kendisi (ör. PostgreSQL streaming replication) altyapı kararıdır.
