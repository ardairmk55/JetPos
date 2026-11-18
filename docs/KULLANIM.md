# JETPOS Kullanım Kılavuzu

Menüler role göre değişir; kullanıcı yalnızca işine uygun ekranları görür. Uygulama içi **Yardım** ekranında SSS,
rehberler ve adım adım sorun giderme (karar ağacı) bulunur.

## Ortak
- **Giriş**: kullanıcı adı + şifre. Ortak cihazda menüden **Kullanıcı değiştir** → personel seç → PIN.
- **Kilit**: hareketsizlikte otomatik (şube ayarı) veya `Ctrl+L`. PIN ile açılır.
- **Tema / dil / yazı boyutu / yüksek kontrast**: üst çubuk veya Ayarlar > Tercihlerim (hesaba kaydedilir, anında uygulanır).
- **Global arama**: `/` veya `Ctrl+K` — masa, adisyon no, ürün, kategori, personel, müşteri, ödeme, rezervasyon, stok, geçmiş. Sonuçlar yetkiye göre filtrelenir.
- Kısayollar: `F2` Masalar, `F3` Mutfak, `F4` Kasa, adisyonda `Ctrl+Enter` gönder, `F9` öde.

## Garson
1. Masalar (telefonda **Garson** ekranı): boş masaya dokun → adisyon açılır (bir masada tek aktif adisyon).
2. Kategori/favori/son kullanılan/popüler veya arama ile ürün seç; seçenekli ürünlerde zorunlu/opsiyonel seçimleri yap.
3. Taslak ürünleri düzenle (+/−, not, sil). **Mutfağa Gönder**: ilk gönderimde özet onayı, sonraki partiler hızlı.
4. Gönderilmiş ürün değiştirilemez; **İptal** gerekçe ister ve yetkili onayı gerektirir (yetkili PIN'i veya "Onay iste").
5. Mutfak hazırlayınca sesli bildirim + masada "Hazır" rozeti → **Hazır siparişler**'den **Teslim aldım**.
6. **Hesap iste** kasaya bildirim gönderir. Garson indirim, iptal, fiyat değişikliği ve kasa işlemi yapamaz.
7. Belediye personeli: adisyon menüsü > Müşteri grubu → kasiyer onaylar/reddeder.
8. Ağ koparsa: üstte "⏳ Kuyrukta — gönderilmedi" sayacı çıkar; ürünler "Kuyrukta" olarak işaretlenir ve **mutfağa ulaşmış görünmez**. Bağlantı gelince otomatik gönderilir, sonuç bildirilir.

## Kasiyer
- **Kasa**: gün başında açılış bakiyesi ile kasayı aç (ödeme almak için zorunlu). Gider/çıkış/giriş hareketlerini gerekçeyle kaydet.
- **Ödeme** (`F9`): nakit (para üstü), kart, yemek kartı, açık hesap (müşteri seçimi); bölüştürme: tamamı, özel tutar, eşit bölme, ürün/kişi bazlı. Tüm tahsilatlar aynı adisyona bağlıdır; çift tahsilat engellidir.
- Tam ödemeden sonra masa "Ödendi" olur; ayar kapalıysa masa boşaltılınca **Masayı kapat**.
- **Gün sonu**: Kasa sayımı → sayılan nakit; fark varsa neden zorunlu → rapor otomatik oluşur → yönetici onayıyla kapanır ve arşivlenir.
- İade: Ödemeler > İade (yönetici yetkisi/PIN). Silme yok; ters kayıt oluşur.

## Mutfak (KDS)
İstasyonunu seç → kartlar FIFO, geciken kırmızı. **Başla** / **Hazır** (tek dokunuşla tüm kart). Çok istasyonlu siparişte
tüm istasyonlar hazır olunca garsona bildirim gider. İptal edilen ürün kartta "İPTAL" olarak görünür ve sesli uyarı verir.
Yönetici merkezi görünümde öncelik değiştirebilir ve tüm partiyi hazır işaretleyebilir.

## Yönetici / işletme sahibi
- **Katalog**: ürün, kategori (KDS istasyonu ve KDV), seçenek grupları (min/max, ücretli/ücretsiz), kanal/şube/grup ve zamanlanmış fiyatlar, fiyat geçmişi, kampanyalar (yüzde/sabit/X al Y/paket, gün/saat/kanal/grup, limit, öncelik).
- **Onaylar**: indirim, iptal, müşteri grubu, iade talepleri.
- **Stok**: özet kartlar + tablo, malzeme, reçete (g/kg, ml/lt dönüşümü), mal kabul, transfer, sayım, fire, hareket geçmişi. Stok düşüm zamanı ve "stok yoksa" politikası şube/ürün ayarıdır.
- **Raporlar**: hazır raporlar, filtre (tarih, personel, salon, ürün, kanal), önceki dönem karşılaştırma, özel rapor (boyut × ölçü), kayıtlı şablon, PDF/Excel/CSV/yazdır, otomatik e-posta gönderimi.
- **CRM / Kurye / Rezervasyon / Personel / Finans**: lisansta etkinse menüde görünür.
- **Kullanıcılar**: rol, şube, PIN; ayrılan personel devre dışı bırakılır.
- **Sistem**: yedek/geri yükleme testi, sağlık ve tanılama, güncelleme, yedeklilik (failover/failback), senkronizasyon.
- **Destek**: talep aç; uzaktan destek için süre, kapsam ve veri erişim düzeyiyle **açık onay** ver, istediğin an sonlandır; destek personelinin her işlemi kayıtlıdır.
- **Denetim kaydı**: tüm hassas işlemler değiştirilemez şekilde listelenir.

## Platform (merkez) rolleri
Platform yöneticisi, lisans yöneticisi, finans yöneticisi, teknik ekip ve destek: işletmeler, başvurular, lisanslar,
SLA hedefleri, ticari kayıtlar, bakım sözleşmeleri, sürüm notları, destek kuyruğu ve merkezi sağlık izleme.

## Önemli not
JETPOS'un yazdırdığı termal adisyon/bilgi fişi **yasal mali fiş değildir**. Yasal fiş/fatura için uyumlu YN ÖKC/banka POS
entegrasyonu gerekir (cihaz/protokol bilgisi şartnamede yoktur).
