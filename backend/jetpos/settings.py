"""JETPOS ayarları.

Tüm ortam bağımlı değerler ortam değişkenlerinden okunur (bkz. docs/KURULUM.md).
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("JETPOS_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def env_bool(name, default=False):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _secret_key():
    key = os.environ.get("JETPOS_SECRET_KEY")
    if key:
        return key
    # Kurulum sırasında üretilip veri klasöründe saklanır; kodda sabit anahtar yok.
    path = DATA_DIR / "secret.key"
    if not path.exists():
        import secrets

        path.write_text(secrets.token_urlsafe(64), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
DEBUG = env_bool("JETPOS_DEBUG", False)
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("JETPOS_ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [h.strip() for h in os.environ.get("JETPOS_CSRF_ORIGINS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "apps.core",
    "apps.catalog",
    "apps.pos",
    "apps.printing",
    "apps.inventory",
    "apps.modules",
    "apps.reports",
    "apps.licensing",
    "apps.ops",
    "apps.integrations",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RateLimitMiddleware",
    "apps.core.middleware.ActivityMiddleware",
    "apps.ops.middleware.WriterFenceMiddleware",
    "apps.licensing.middleware.SupportAccessMiddleware",
]

ROOT_URLCONF = "jetpos.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context.jetpos_context",
            ]
        },
    }
]
WSGI_APPLICATION = "jetpos.wsgi.application"
ASGI_APPLICATION = "jetpos.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        env="DATABASE_URL",
        default=f"sqlite:///{(DATA_DIR / 'jetpos.sqlite3').as_posix()}",
        conn_max_age=60,
    )
}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # Eşzamanlı yazımda "database is locked" olmaması için: yazma işlemleri BEGIN IMMEDIATE ile başlar
    # (okumadan yazmaya yükseltme kilitlenmesi yok) ve WAL ile okuyucular yazıcıyı bloklamaz.
    DATABASES["default"].setdefault("OPTIONS", {}).update({
        "timeout": 20, "transaction_mode": "IMMEDIATE",
        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
    })

CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]
LOGIN_URL = "/login/"

LANGUAGE_CODE = "tr"
TIME_ZONE = os.environ.get("JETPOS_TIME_ZONE", "Europe/Istanbul")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = DATA_DIR / "staticfiles"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
WHITENOISE_USE_FINDERS = True  # collectstatic yapılmamış kurulumda da statik dosyalar sunulur
WHITENOISE_MAX_AGE = 0  # LAN: her istekte ETag doğrulaması; güncelleme sonrası eski JS kalmaz
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SESSION_COOKIE_AGE = int(os.environ.get("JETPOS_SESSION_SECONDS", 12 * 3600))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
if env_bool("JETPOS_HTTPS", False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": None,
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    "COERCE_DECIMAL_TO_STRING": False,
}

# E-posta: SMTP bilgileri işletmeye özgüdür; tanımlı değilse e-postalar dosyaya yazılır.
if os.environ.get("JETPOS_SMTP_HOST"):
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ["JETPOS_SMTP_HOST"]
    EMAIL_PORT = int(os.environ.get("JETPOS_SMTP_PORT", 587))
    EMAIL_HOST_USER = os.environ.get("JETPOS_SMTP_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("JETPOS_SMTP_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("JETPOS_SMTP_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = DATA_DIR / "outbox_mail"
DEFAULT_FROM_EMAIL = os.environ.get("JETPOS_MAIL_FROM", "jetpos@localhost")

# JETPOS'a özgü
JETPOS = {
    "NODE_ID": os.environ.get("JETPOS_NODE_ID", "node-1"),
    "BACKUP_DIR": Path(os.environ.get("JETPOS_BACKUP_DIR", DATA_DIR / "backups")),
    "BACKUP_MIRROR_DIRS": [p for p in os.environ.get("JETPOS_BACKUP_MIRRORS", "").split(";") if p],
    "BACKUP_KEY_FILE": DATA_DIR / "backup.key",
    "LICENSE_PUBLIC_KEY_FILE": Path(os.environ.get("JETPOS_LICENSE_PUBKEY", DATA_DIR / "license_public.pem")),
    "LICENSE_FILE": DATA_DIR / "license.jetlic",
    "UPDATE_PUBLIC_KEY_FILE": Path(os.environ.get("JETPOS_UPDATE_PUBKEY", DATA_DIR / "update_public.pem")),
    "RELEASES_DIR": Path(os.environ.get("JETPOS_RELEASES_DIR", DATA_DIR / "releases")),
    "PRINT_SPOOL_DIR": DATA_DIR / "print_spool",
    "CENTRAL_URL": os.environ.get("JETPOS_CENTRAL_URL", ""),
    "CENTRAL_TOKEN": os.environ.get("JETPOS_CENTRAL_TOKEN", ""),
    "JETMENU_WEBHOOK_URL": os.environ.get("JETPOS_JETMENU_WEBHOOK", ""),
    "RATE_LIMIT_PER_MINUTE": int(os.environ.get("JETPOS_RATE_LIMIT", 600)),
    "LOGIN_RATE_LIMIT_PER_MINUTE": int(os.environ.get("JETPOS_LOGIN_RATE_LIMIT", 20)),
    "WRITER_LEASE_SECONDS": int(os.environ.get("JETPOS_WRITER_LEASE_SECONDS", 30)),
    "ENFORCE_WRITER_FENCE": env_bool("JETPOS_ENFORCE_WRITER_FENCE", False),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(DATA_DIR / "jetpos.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "std",
            "encoding": "utf-8",
        },
    },
    "root": {"handlers": ["console", "file"], "level": os.environ.get("JETPOS_LOG_LEVEL", "INFO")},
}
