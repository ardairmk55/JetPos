import os
import tempfile

os.environ.setdefault("JETPOS_DATA_DIR", tempfile.mkdtemp(prefix="jetpos_test_"))

from jetpos.settings import *  # noqa: E402,F401,F403
from jetpos.settings import JETPOS  # noqa: E402

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
JETPOS["RATE_LIMIT_PER_MINUTE"] = 100000
JETPOS["LOGIN_RATE_LIMIT_PER_MINUTE"] = 100000
LOGGING = {"version": 1, "disable_existing_loggers": False}
