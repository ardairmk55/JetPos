"""RFC 6238 TOTP — hassas merkezi işlemlerde 2FA (§15.1). Harici servis gerektirmez."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, counter, digits=6):
    pad = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + pad)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    val = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(val).zfill(digits)


def now_code(secret, at=None):
    return _code(secret, int((at or time.time()) // 30))


def verify(secret, code, window=1, at=None):
    if not secret or not code:
        return False
    t = int((at or time.time()) // 30)
    code = str(code).strip()
    return any(hmac.compare_digest(_code(secret, t + w), code) for w in range(-window, window + 1))


def uri(secret, account, issuer="POSHANE"):
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}&issuer={quote(issuer)}"
