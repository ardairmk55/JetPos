"""QR kod üretimi (harici servis yok)."""
import io

import qrcode
from django.http import HttpResponse


def png(data: str, box_size=6) -> bytes:
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=3)
    q.add_data(data)
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image(fill_color="#252936", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def response(data: str, filename="qr.png"):
    r = HttpResponse(png(data), content_type="image/png")
    r["Content-Disposition"] = f'inline; filename="{filename}"'
    r["Cache-Control"] = "no-store"
    return r
