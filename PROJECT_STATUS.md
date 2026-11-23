# JETPOS — Proje Durumu

Kaynak: `JETPOS_Teknik_Urun_Sartnamesi_v1.0.pdf` · Sürüm 1.0.0 · Son güncelleme: 18.11.2026

**Doğrulama:** `cd backend && ..\.venv\Scripts\python -m pytest` → **67 test geçiyor** (gerçek alt süreçle yeni
veritabanına geri yükleme testi dahil). `manage.py check` temiz, eksik migration yok. Arayüz tarayıcıda uçtan uca
denendi: giriş → kasa açılışı → masa → seçenekli ürün → mutfağa gönderim (onay özeti) → KDS hazır → WebSocket
bildirimi → eşit bölünmüş ödeme. 27 ekran ve 38 sekme hatasız yükleniyor.

Durum işaretleri: ✅ çalışır ve test edildi · 🟡 kısmi / sınırlı · ⛔ dış bilgi/erişim gerekli · 📝 açık karar (şartname)

## Kabul kriterleri (şartname §21)
| Alan | Durum | Kanıt |
|---|---|---|
| Masa/adisyon: tek aktif adisyon, kart → tam ekran | ✅ | DB kısıtı `one_active_ticket_per_table`; `test_one_active_ticket_per_table` |
| Taslak düzenlenebilir, gönderim onaylı | ✅ | `test_draft_editable_and_send_requires_confirmation` |
| Mutfak: doğru istasyon, sesli/görsel hazır bildirimi | ✅ | `test_kitchen_routing_and_ready_notification`, tarayıcı testi |
| Ödeme: bölünmüş/kısmi aynı adisyon, çift tahsilat engeli | ✅ | `test_split_payments_stay_on_same_ticket`, `test_duplicate_payment_is_blocked` |
| Kasa: açılış, hareket, beklenen/sayılan, fark, kapanış | ✅ | `test_cash_day_close_flow` |
| Stok: reçete tüketimi bir kez, kontrollü ters hareket | ✅ | `test_recipe_consumed_once`, `test_void_reverses_stock_once` |
| Offline: LAN sürer, kopuk telefondaki kuyruk mutfağa ulaşmış görünmez | ✅ | IndexedDB kuyruğu + "Kuyrukta — gönderilmedi" göstergesi; `test_offline_queue_replay_is_idempotent` |
| Yedek: restore, bütünlük, işlem kaydı | ✅ | `test_backup_encrypted_verified_and_tamper_detected`, `test_restore_*` |
| Failover: eski sunucu izole edilmeden yeni yazıcı yok | ✅ | `test_split_brain_prevented`, `test_writer_fence_middleware_blocks_standby` |
| Yetki: garson indirim/iptal yapamaz; onay + gerekçe | ✅ | `test_permissions_approvals.py` |
| Destek: müşteri onayı olmadan erişim yok; loglanır | ✅ | `test_remote_support_requires_consent_and_is_logged` |
| Güncelleme: imza, yedek, onay, sağlık testi, rollback | ✅ | `test_update_signature_backup_approval_health_rollback` |

## Modüller
| Modül (şartname) | Durum | Not |
|---|---|---|
| Rol/yetki matrisi, şube kapsamı, tenant izolasyonu (§2, §12, NFR-03) | ✅ | `apps/core/roles.py`, `tenancy.py` |
| Kimlik: şifre + PIN, personel değişimi, hareketsizlik kilidi, hesap kilidi, giriş kaydı, 2FA (TOTP) (§9.4, §15.1) | ✅ | Platform 2FA testle değil, birim kodla doğrulandı |
| UX: açık/koyu tema anlık, TR/EN, yazı boyutu, yüksek kontrast, kısayollar, rol bazlı menü, dokunmatik hedefler (§4) | ✅ | İngilizce sözlük (`i18n_en.js`, ~370 ifade): menü, başlık, sekme, sütun, form, buton, durum. Veri (ürün adları) ve bazı uzun yardım metinleri Türkçe kalır 🟡 |
| Global arama (rol/şube filtreli, son arama, öneri) (§4.2, §10.3) | ✅ | |
| Masa/salon: çoklu salon, sürükle-bırak plan, durumlar, taşıma, masa birleştirme (§5.1) | ✅ | Adisyon birleştirme/bölme 📝 kararlaştırılmadığı için uygulanmadı |
| Ürün seçenekleri, min/max, ücretli ekstra, not, fiyat hesabı (§5.3) | ✅ | |
| Ödeme yöntemleri, eşit/ürün/kişi/özel bölme, açık hesap, idempotency (§6.1) | ✅ | |
| İndirim/iptal/iade, belediye personeli akışı, ters kayıt (§6.2) | ✅ | Belediye onayının genel politika ile rol uyumu 📝 |
| Vergi snapshot, kanal/şube/grup/zamanlı fiyat, fiyat geçmişi, kampanya (yüzde, sabit, X al Y, paket, gün/saat, limit, öncelik) (§6.4) | ✅ | Kampanya motoru: satır başına en yüksek öncelikli tek kampanya |
| KDS: FIFO, gecikme, öncelik, istasyon/merkezi görünüm, hazır, teslim alındı (§7.1, §7.2) | ✅ | Çok istasyonda "tek buton": her istasyon kendi kısmını, yönetici tüm partiyi hazırlar; parti tüm istasyonlar bitince hazır (📝 doğrulanmalı) |
| Yazıcı: ESC/POS, CP857, 58/80 mm, yönlendirme, kuyruk, retry, yedek yazıcı, test baskısı (§7.3) | ✅ / ⛔ | Model bazlı uyumluluk sahada test edilmeli (NFR-11); USB için pywin32 |
| Stok/depo: reçete, birim dönüşümü, satın alma, transfer, sayım, fire, düşük stok, düşüm zamanı, politika (§8) | ✅ | |
| CRM + KVKK (erişim kaydı, dışa aktarım, anonimleştirme) (§9.1, NFR-09) | ✅ | Sadakat/puan ilk kapsam dışı (şartname) |
| Kurye (§9.2) | ✅ | Canlı GPS 📝 kararlaştırılmadı |
| Rezervasyon: kapasite, bekleme listesi, hatırlatma, adisyona dönüştürme (§9.3) | ✅ | Hatırlatma uygulama içi; SMS/e-posta müşteriye ⛔ |
| Personel: vardiya, giriş-çıkış, mola, geç kalma, devamsızlık, fazla mesai, izin, performans (§9.4) | ✅ | |
| Finans: gelir-gider, cari, ters kayıt, kârlılık | ✅ | |
| Raporlama: hazır + özel rapor, filtre, karşılaştırma, şablon, PDF/Excel/CSV/yazdır, otomatik gönderim + retry (§10.1) | ✅ | SMTP bilgisi ⛔ (yoksa dosyaya yazılır) |
| Bildirim: uygulama içi, ses, öncelik, okundu, son 24 saat, rol/olay kuralları, e-posta (§10.2) | ✅ / ⛔ | Mobil push (uygulama kapalıyken) için VAPID/FCM ⛔ |
| Yardım merkezi: SSS, rehber, karar ağacı, AI yok (§10.3, §19.1) | ✅ | Görsel/video içerik eklenmedi 🟡 |
| JET Menü (§11) | 🟡 / 📝 | JETPOS tarafı uçlar + QR sipariş + imzalı çıkış kuyruğu + yazdırılabilir masa QR'ı (içerik şablonu ayarlanabilir) çalışır; JET Menü'nün gerçek API/URL biçimi doğrulanmadı |
| Çok şube: şube seçimi, şube bazlı fiyat/görünürlük, merkez senkronizasyonu (§12) | ✅ / ⛔ | Merkez sunucu adresi ve altyapısı ⛔; senkronizasyon protokolü 📝 |
| Güvenlik: audit (değiştirilemez), rate limit, şüpheli IP, şifreli yedek/ek (§15) | ✅ | HTTPS sertifikası ve ağ keşif/cihaz eşleştirme 📝 |
| Teknik destek erişimi: onay, süre, kapsam, anonim veri, anında sonlandırma, işlem logu, şifreli/taranmış dosya, saklama-imha (§15.3, §19.3) | ✅ | Ekran kaydının kendisi uzaktan masaüstü aracına bağlı ⛔ (onay + kayıt saklama hazır) |
| Yedek: hibrit, şifreli, bütünlük, geri yükleme testi, saklama, kritik koruma (§16.1, NFR-06) | ✅ / ⛔ | Bulut yedek hedefi ⛔; RPO/RTO 📝 |
| Failover/failback, split-brain önleme (§16.2) | ✅ / ⛔ | Mantık + kilit hazır; DB replikasyon altyapısı ⛔ |
| Sağlık izleme, tanılama, uyarılar, merkezi görünüm (§16.3, NFR-08) | ✅ | Harita görünümü 🟡 yok; SMS ⛔ |
| Lisans: imzalı offline dosya, online anahtar, QR metni, modül/şube/cihaz hakkı, transfer (§17) | ✅ | Lisans QR görseli (Platform > Lisanslar > QR) ve QR'dan okunan metinle kurulum. Fiyat/limit 📝 |
| Müşteri portalı, online başvuru + onay, bakım sözleşmesi, ödeme geçmişi (§17.2) | ✅ | |
| Destek talepleri + SLA (iş saati/takvim, duraklatma, yeniden açma, hatırlatma) (§19) | ✅ | Sayısal SLA hedefleri 📝 (platformdan girilir) |
| Akıllı kurulum: betik + sihirbaz + şablonlar (§18.1) | ✅ | Ağ/donanım testleri: yazıcı bağlantı testi var; tam donanım testi 🟡 |
| Akıllı güncelleme: imza, yedek, onay, sağlık, rollback, USB (§18.2) | ✅ | Merkezden otomatik dağıtım sunucusu ⛔ |
| Garson PWA + IndexedDB offline kuyruk (§13, §14) | ✅ | |
| Electron Windows kabuğu + KDS kiosk (§13.1) | ✅ | `desktop/` — Electron 33; `npm run package` → `desktop/dist/JETPOS-win32-x64/JETPOS.exe` üretildi. Kod imzalama sertifikası ve kurulum sihirbazlı (MSI) paket ⛔/🟡 |

## UI/UX yeniden tasarım ve denetim (2026-11-23)
| Kalem | Durum | Not |
|---|---|---|
| Tasarım sistemi (token, IBM Plex Sans, Lucide `icons.js`, düz yüzeyler, turuncu az) | ✅ | `frontend/src/input.css`, `frontend/build-assets.mjs` |
| Gruplu, rol-duyarlı, daralan kenar çubuğu + yeni üst bar | ✅ | `app.html`, `app.js` (`NAV`) |
| Yeni dashboard (tarih seçici, 7 kart, 7 gün grafiği, karşılaştırma, ödeme dağılımı, operasyon listeleri) | ✅ | `P.dashboard`, `reports/services.py` `dashboard(day=)` |
| Diğer ekranlarda emoji/glif → ikon | 🟡 | Emoji taraması temiz; her ekranın tek tek görsel incelemesi yapılmadı |
| Yatay taşma | ✅ | Neden: görünmez `[data-tip]::after` tooltip'i. Düzeltme: tooltip `display:none` + `.shell{overflow-x:clip}`. 29 rota 1202 px'te, 24 rota 375 px'te taşma 0 |
| Konsol/yükleme hatası taraması (29 rota) | ✅ | JS hatası 0, boş/hatalı sayfa 0 (1202 px) |
| N+1 düzeltmeleri (katalog) | ✅ | `catalog/serializers.py`, `views.py` |
| Testler | ✅ | 70/70 geçti (69 hızlı ~31 sn + yavaş restore testi ~35 sn); yeni `tests/test_dashboard.py` 3 test |
| Karanlık tema (dashboard, ~800 px) görsel kontrolü | ✅ | Yalnız dashboard bakıldı; diğer ekranlar karanlıkta bakılmadı. Yüksek kontrast, tablet ⛔ TEST EDİLEMEDİ |
| Kritik POS akışı tarayıcıda uçtan uca | 🟡 | API düzeyinde testlerle kapsanıyor; tarayıcıda elle tekrar edilmedi |
| `J.chart` (zaten `--chart-*` token'lı, düz), `J.crud` (ikonlu "Yeni", iskelet yükleme, hata durumu), iskelet gradyanı kaldırıldı | ✅ | `ui.js`, `input.css` |
| Kabuk/menü etiketlerinin İngilizcesi | ✅ | `i18n_en.js` +50 giriş |
| Statik dosya önbellek sürümü (`?v=` = en yeni mtime) | ✅ | `apps/web/context.py` `ASSET_V`, `app.html`, `base.html` |

## Dış bilgi / erişim gerektirenler (uydurulmadı)
- Banka POS ve YN ÖKC marka/model entegrasyonları (yasal mali fiş) — cihaz/protokol dokümanı gerekli.
- JET Menü mevcut API'si, SMTP sunucusu, mobil push (VAPID/FCM), SMS sağlayıcısı, bulut yedek hedefi,
  merkez platform sunucusu, HTTPS sertifikası, PostgreSQL replikasyonu.
- Şartnamedeki açık kararlar (§22.1): paket fiyat/limitleri, SLA sayıları, RPO/RTO ve saklama varsayılanları,
  donanım profilleri, Windows Server sürümü, GPS/sadakat/adisyon bölme-birleştirme, belediye onay matrisi,
  çok istasyonlu KDS tamamlama kuralı, senkronizasyon çakışma protokolü, talep yeniden açma süresi.
  Bu değerler kodda sabitlenmedi; ilgili ekranlarda yönetici tarafından girilir.

## Dosya haritası
`backend/` Django projesi · `backend/tests/` testler · `frontend/` Tailwind kaynakları · `desktop/` Electron ·
`installer/` kurulum/başlatma/güncelleme betikleri · `docs/` kılavuzlar.

## Devam etme notu
Oturum kesilirse: önce `pytest` çalıştır; kalan 🟡: merkezi izlemede harita (harita sağlayıcısı ⛔), yardım
merkezi görsel/video içeriği, yardım metinlerinin İngilizcesi, MSI/imzalı Windows kurulum paketi.
