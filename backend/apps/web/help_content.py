"""Yardım merkezi içeriği: SSS, rehberler ve karar ağaçları. Yapay zekâ yoktur; kurallar deterministiktir (§10.3, §19.1)."""

FAQ = [
    {"q": "İnternet kesildi, satış yapabilir miyim?", "roles": "*",
     "a": "Evet. Kasa, mutfak ve garson cihazları aynı yerel ağdaki JETPOS sunucusuna bağlı olduğu sürece çalışmaya devam eder. "
          "E-posta, bulut yedek ve merkez senkronizasyonu bağlantı geldiğinde otomatik tamamlanır."},
    {"q": "Garson telefonu ağdan koptu, sipariş ne oldu?", "roles": "waiter,branch_manager,owner",
     "a": "Sipariş telefonda 'Gönderilmedi (kuyrukta)' olarak saklanır ve mutfağa ulaşmış görünmez. Bağlantı gelince otomatik "
          "gönderilir ve sonuç ekranda bildirilir."},
    {"q": "Garson neden indirim yapamıyor?", "roles": "*",
     "a": "Güvenlik gereği garson indirim, iptal ve fiyat değişikliği yapamaz. 'Onay iste' ile yöneticiye talep gönderilir "
          "veya yetkili kişi PIN'ini girerek işlemi onaylar."},
    {"q": "Hesap kişilere bölünürse ayrı adisyon oluşur mu?", "roles": "*",
     "a": "Hayır. Eşit bölme, ürün bazlı veya özel tutarlı tüm tahsilatlar aynı adisyona bağlı kalır."},
    {"q": "Gün sonu nasıl yapılır?", "roles": "cashier,branch_manager,owner",
     "a": "Kasa ekranında 'Kasa sayımı' ile sayılan nakdi girin. Fark varsa nedenini yazın. Rapor otomatik oluşur; "
          "yönetici kontrol edip onaylayınca gün kapanır ve rapor arşivlenir."},
    {"q": "Termal adisyon çıktısı mali fiş midir?", "roles": "*",
     "a": "Hayır. JETPOS'un yazdırdığı bilgi fişi yasal mali fiş yerine geçmez. Yasal fiş/fatura için uyumlu YN ÖKC/banka POS "
          "entegrasyonu gerekir."},
    {"q": "Yedekler nerede ve şifreli mi?", "roles": "owner,branch_manager",
     "a": "Yedekler sunucudaki veri klasöründe şifreli (.jbk) tutulur; tanımlıysa harici disk/NAS klasörlerine kopyalanır. "
          "Her yedeğin SHA-256 bütünlük kontrolü ve geri yükleme testi yapılabilir."},
]

GUIDES = [
    {"id": "first-sale", "title": "İlk satış: masadan ödemeye", "roles": "*", "steps": [
        "Masalar ekranında boş masaya dokunun; adisyon tam ekran açılır.",
        "Üstteki kategorilerden ürünü seçin; seçenekli ürünlerde açılan pencerede tercihleri yapın.",
        "Taslak ürünler istediğiniz gibi düzenlenebilir. 'Mutfağa Gönder' ile ilk gönderimde özet onayı verin.",
        "Mutfak hazır işaretleyince masada 'Hazır' rozeti ve sesli bildirim çıkar; 'Teslim aldım' deyin.",
        "Kasiyer 'Öde' ile yöntem seçer; bölüştürme ve kısmi ödeme aynı adisyonda kalır.",
        "Ayar 'otomatik kapanış' değilse masa boşaltılınca 'Masayı kapat' ile kapatın."]},
    {"id": "kds", "title": "Mutfak ekranı (KDS)", "roles": "kitchen,branch_manager,owner", "steps": [
        "İstasyonunuzu seçin (ana mutfak, içecek, tatlı...).",
        "Kartlar geliş sırasına (FIFO) göre dizilir; gecikenler kırmızı vurgulanır.",
        "'Başla' ile hazırlığa alın, 'Hazır' ile tek dokunuşta tüm kartı hazır işaretleyin.",
        "Çok istasyonlu siparişte tüm istasyonlar hazır olunca garsona bildirim gider."]},
    {"id": "approvals", "title": "İndirim, iptal ve onaylar", "roles": "*", "steps": [
        "Gönderilmiş ürün sessizce değiştirilemez; 'İptal' gerekçe ister ve mutfağa bildirilir.",
        "Yetkiniz yoksa 'Onay iste' seçin veya yetkili PIN ile anında onaylatın.",
        "Belediye personeli için garson müşteri grubunu işaretler; kasiyer onaylar/reddeder."]},
    {"id": "stock", "title": "Stok ve reçete", "roles": "stock,branch_manager,owner", "steps": [
        "Malzemeleri birim ve minimum seviyeleriyle tanımlayın.",
        "Ürünlere reçete ekleyin (gram/ml dönüşümü otomatik).",
        "Mal kabul ile tedarikçi girişlerini yapın; satışta tüketim otomatik düşer ve bir kez işlenir.",
        "Fire, sayım ve düzeltmeler gerekçe ile kaydedilir."]},
    {"id": "offline", "title": "Çevrimdışı çalışma", "roles": "*", "steps": [
        "İnternet yokken yerel ağ üzerinden tüm temel işlemler sürer.",
        "Telefon ağdan koparsa siparişler cihazda kuyruğa alınır, üstte 'Kuyrukta' sayacı görünür.",
        "Bağlantı gelince kuyruk otomatik gönderilir; her işlem benzersiz kimlikle tekrarlanmadan işlenir."]},
]

DECISION_TREES = [
    {"id": "printer", "title": "Yazıcı çıktı vermiyor", "nodes": {
        "start": {"q": "Yazıcının ışığı yanıyor ve kâğıdı var mı?", "yes": "net", "no": "power"},
        "power": {"end": "Yazıcıyı açın, kâğıt rulosunu kontrol edin ve kapağı kapatın. Ardından Ayarlar > Yazıcılar > Test baskısı."},
        "net": {"q": "Yazıcı ağ (Ethernet/Wi-Fi) yazıcısı mı?", "yes": "ip", "no": "usb"},
        "ip": {"q": "Ayarlardaki IP adresi yazıcının self-test çıktısındaki IP ile aynı mı?", "yes": "queue", "no": "fixip"},
        "fixip": {"end": "Yazıcı ayarındaki IP adresini self-test çıktısındaki değerle güncelleyin ve test baskısı alın."},
        "usb": {"end": "Windows yazıcı adının ayardakiyle birebir aynı olduğunu ve sunucuda 'pywin32' kurulu olduğunu doğrulayın."},
        "queue": {"q": "Yazdırma kuyruğunda 'Başarısız' iş var mı?", "yes": "retry", "no": "support"},
        "retry": {"end": "Kuyruktan 'Tekrar dene'ye basın. Yedek yazıcı tanımlıysa iş otomatik oraya yönlenir."},
        "support": {"end": "Sorun sürüyorsa Destek > Yeni talep ile 'Yazıcı' kategorisinde talep açın."}}},
    {"id": "network", "title": "Cihaz sunucuya bağlanamıyor", "nodes": {
        "start": {"q": "Cihaz işletmenin Wi-Fi/yerel ağına bağlı mı?", "yes": "server", "no": "wifi"},
        "wifi": {"end": "Cihazı işletme ağına bağlayın. Misafir ağı sunucuya erişemeyebilir."},
        "server": {"q": "Sunucu bilgisayar açık ve JETPOS hizmeti çalışıyor mu?", "yes": "fw", "no": "start_srv"},
        "start_srv": {"end": "Sunucuda 'JETPOS' hizmetini başlatın (installer\\start_server.ps1)."},
        "fw": {"end": "Windows güvenlik duvarında JETPOS portuna (varsayılan 8000) yerel ağ izni verildiğini kontrol edin."}}},
    {"id": "cash_diff", "title": "Gün sonunda kasa farkı çıktı", "nodes": {
        "start": {"q": "Kasadan yapılan tüm gider/çıkışlar sisteme girildi mi?", "yes": "refund", "no": "enter"},
        "enter": {"end": "Eksik kasa hareketlerini gerekçeleriyle girin; beklenen tutar yeniden hesaplanır."},
        "refund": {"q": "Nakit iadeler sistemde kayıtlı mı?", "yes": "explain", "no": "enter_refund"},
        "enter_refund": {"end": "İadeyi Ödemeler ekranından ilgili ödeme üzerinden yapın; kasa hareketi otomatik oluşur."},
        "explain": {"end": "Farkı nedeniyle birlikte kaydedin; yönetici onayıyla gün kapanır ve fark raporlanır."}}},
]


def search_help(q, role):
    q = (q or "").lower().strip()

    def allowed(item):
        r = item.get("roles", "*")
        return r == "*" or role in r.split(",")

    def hit(*texts):
        return not q or any(q in (t or "").lower() for t in texts)

    return {
        "faq": [f for f in FAQ if allowed(f) and hit(f["q"], f["a"])],
        "guides": [g for g in GUIDES if allowed(g) and hit(g["title"], *g["steps"])],
        "trees": [t for t in DECISION_TREES if hit(t["title"], *[n.get("q", n.get("end", "")) for n in t["nodes"].values()])],
    }
