# POSHANE — Hızlı Servis, Akıllı Yönetim.

Restoran, kafe, kahvaltı salonu ve belediye sosyal tesisleri için çok işletmeli, çok şubeli, **yerel ağda
çevrimdışı çalışan** POS ve işletme yönetim platformu. Kaynak gereksinim: *POSHANE Teknik & Ürün Gereksinimleri
Şartnamesi v1.0*.

| Belge | İçerik |
|---|---|
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | Tamamlanan / eksik / dış bağımlı özellikler |
| [docs/KURULUM.md](docs/KURULUM.md) | Sunucu kurulumu, PostgreSQL, ağ, yazıcı, lisans, istemciler |
| [docs/GUNCELLEME.md](docs/GUNCELLEME.md) | İmzalı güncelleme, yedek, rollback, USB/offline |
| [docs/KULLANIM.md](docs/KULLANIM.md) | Rollere göre kullanım akışları |
| [docs/MIMARI.md](docs/MIMARI.md) | Mimari, modüller, güvenlik, çevrimdışı/senkronizasyon |
| [docs/JETMENU_API.md](docs/JETMENU_API.md) | JET Menü entegrasyon uçları |

## Hızlı başlangıç (geliştirme / değerlendirme)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
cd backend
..\.venv\Scripts\python manage.py migrate
..\.venv\Scripts\python manage.py jetpos_demo      # isteğe bağlı DEMO verisi (hesaplar komut dosyasında)
..\.venv\Scripts\python manage.py runserver 0.0.0.0:8000
```

Tarayıcıda `http://<sunucu-ip>:8000` açın. Veritabanı boşsa kurulum sihirbazı açılır.

Testler: `cd backend && ..\.venv\Scripts\python -m pytest`

Arayüz CSS'i yeniden derlemek için: `cd frontend && npm install && npm run build`

## Teknoloji
Python 3.12 · Django 5.2 · Django REST Framework · Django Channels (WebSocket, daphne) · PostgreSQL (SQLite yalnızca
geliştirme/test) · Tailwind CSS (yerel derleme) · vanilla JavaScript · PWA + IndexedDB · Electron (Windows kabuğu).
Yapay zekâ kullanılmaz; tüm otomasyonlar deterministik kurallarla çalışır.
