# JET Menü Entegrasyon Uçları (POSHANE tarafı)

> **Açık karar (şartname §11):** JET Menü'nün (jetmenu.net) mevcut API ve veri modeli doğrulanmamıştır. Aşağıdaki
> sözleşme POSHANE tarafında tanımlanmıştır; JET Menü sistemi incelendikten sonra eşleme kesinleştirilmelidir.
> Sert bağımlılık yoktur: entegrasyon kapalıyken veya internet yokken POSHANE çalışmaya devam eder.

Etkinleştirme: lisansta `jetmenu` modülü + Ayarlar > JET Menü > "Entegrasyon etkin". Gelen istekler
`X-Integration-Token` başlığı ile doğrulanır (ayar ekranında gösterilir).

## Katalog — `GET /api/integrations/jetmenu/catalog?branch=<ŞUBE_KODU>`
Ortak ürün/kategori kimlikleri (`uid`), şube bazlı kategori/ürün görünürlüğü, QR kanalı fiyatı, stok uygunluğu, seçenek grupları.
```json
{"branch":"MRK","categories":[{"uid":"…","name":"Çorbalar"}],
 "products":[{"uid":"…","category_uid":"…","name":"Mercimek Çorbası","price":"90.00","available":true,
              "option_groups":[{"id":3,"name":"Porsiyon","required":true,"min":1,"max":1,"options":[{"id":7,"name":"1,5","price":"60.00"}]}]}]}
```

## QR sipariş — `POST /api/integrations/jetmenu/orders`
```json
{"external_id":"jm-123","table_token":"<masa QR kimliği>","items":[{"product_uid":"…","qty":2,"options":[7],"note":"acısız"}],"note":""}
```
- `external_id` ile idempotent (tekrar gönderimde `duplicate: true`).
- Varsayılan: sipariş **garson onayına** düşer (Masalar ekranında "QR siparişleri"); onayda masanın aktif adisyonuna
  **taslak** olarak eklenir ve garson mutfağa gönderir. `auto_accept_qr` açıksa doğrudan adisyona eklenir.

## Değişiklik bildirimi (çıkış)
Ürün oluşturma/güncellemede `product.upsert` olayı kuyruğa alınır. Webhook adresine toplu JSON gönderilir:
`X-JETPOS-Signature: HMAC-SHA256(signing_secret, gövde)`. Bağlantı yoksa kuyrukta bekler, zamanlayıcı yeniden dener.
