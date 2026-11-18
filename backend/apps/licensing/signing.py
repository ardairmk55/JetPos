"""Ed25519 imza yardımcıları — lisans dosyaları ve güncelleme paketleri için."""
import base64
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def generate_keypair(private_path: Path, public_path: Path):
    key = Ed25519PrivateKey.generate()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    public_path.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                          serialization.PublicFormat.SubjectPublicKeyInfo))
    return private_path, public_path


def load_private(path):
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def load_public(path_or_pem):
    data = path_or_pem if isinstance(path_or_pem, bytes) else Path(path_or_pem).read_bytes()
    key = serialization.load_pem_public_key(data)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Ed25519 açık anahtarı bekleniyor")
    return key


def _b64(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_payload(payload: dict, private_key) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"JETLIC1.{_b64(body)}.{_b64(private_key.sign(body))}"


def verify_blob(blob: str, public_key) -> dict:
    blob = blob.strip()
    try:
        prefix, body, sig = blob.split(".")
    except ValueError:
        raise ValueError("Lisans biçimi geçersiz")
    if prefix != "JETLIC1":
        raise ValueError("Lisans sürümü desteklenmiyor")
    raw = _unb64(body)
    try:
        public_key.verify(_unb64(sig), raw)
    except InvalidSignature:
        raise ValueError("Lisans imzası doğrulanamadı")
    return json.loads(raw)


def sign_bytes(data: bytes, private_key) -> str:
    return _b64(private_key.sign(data))


def verify_bytes(data: bytes, signature: str, public_key) -> bool:
    try:
        public_key.verify(_unb64(signature), data)
        return True
    except InvalidSignature:
        return False
