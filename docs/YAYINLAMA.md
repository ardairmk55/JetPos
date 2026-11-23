# POSHANE'i internete yayınlama (Linux VPS + Docker + otomatik HTTPS)

Bu rehber `poshane.net` alan adı ve root SSH erişimli bir **Linux VPS** içindir. Paylaşımlı (cPanel) hostingde
Django + WebSocket genelde çalışmaz; VPS gerekir. Parolaları bu depoya veya belgelere yazmayın.

## 1. DNS
Alan adı sağlayıcısında şu kayıtları sunucunun IP adresine yönlendirin:

| Tür | Ad | Değer |
|---|---|---|
| A | `@` | sunucu IP |
| A | `www` | sunucu IP |

Yayılması birkaç dakika–birkaç saat sürebilir. Caddy sertifikayı ancak DNS doğru olunca alabilir.

## 2. Sunucuyu hazırlama
SSH ile bağlanın, root parolası yerine mümkünse SSH anahtarı kullanın ve ilk iş olarak parolayı değiştirin.

```bash
apt update && apt install -y docker.io docker-compose-plugin git ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
```

Yalnızca 22, 80 ve 443 açık olmalı. Uygulama portu (8000) dışarı açılmaz.

## 3. Kod ve yapılandırma
```bash
git clone https://github.com/ardairmk55/JetPos.git poshane && cd poshane
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # çıktıyı JETPOS_SECRET_KEY olarak .env'ye yazın
nano .env
```

## 4. Başlatma
```bash
docker compose up -d --build
docker compose logs -f app
```

İlk açılışta `https://poshane.net/setup` kurulum sihirbazını açın ve ilk işletme/sahip hesabını oluşturun.

HTTPS çalıştığını doğruladıktan sonra `.env` içinde `JETPOS_HSTS_SECONDS=31536000` yapıp `docker compose up -d` çalıştırın.

## 5. Yedekleme ve güncelleme
- Veri `poshane-data` Docker volume'ündedir (SQLite, anahtarlar, yedekler). Sunucu disk yedeği alın.
- Güncelleme: `git pull && docker compose up -d --build`
- Zamanlayıcı servisi otomatik yedek ve bakım görevlerini çalıştırır.

## Bilinen sınırlar
- Tek sunucu ve tek `app` süreci için tasarlandı (WebSocket katmanı bellek içi). Birden fazla süreç için Redis gerekir.
- Veritabanı varsayılan SQLite (WAL). Yoğun çok şubeli kullanım için `DATABASE_URL` ile PostgreSQL önerilir; PostgreSQL altında eşzamanlılık test edilmedi.
- Gerçek yazıcı, yazarkasa ve banka POS entegrasyonları internet sunucusundan değil, restoran içindeki yerel ağdan çalışır; bu uygulama bulutta bu cihazlara doğrudan erişemez.
