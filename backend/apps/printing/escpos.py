"""ESC/POS çıktı üretimi. Türkçe karakterler için kod sayfası (varsayılan CP857) kullanılır."""
import socket
from pathlib import Path

ESC = b"\x1b"
GS = b"\x1d"


def render(lines, *, columns=48, codepage="cp857", codepage_id=13, cut=True):
    out = bytearray()
    out += ESC + b"@"  # init
    out += ESC + b"t" + bytes([codepage_id])
    for ln in lines:
        if ln.get("rule"):
            out += ("-" * columns + "\n").encode(codepage, "replace")
            continue
        align = {"left": 0, "center": 1, "right": 2}.get(ln.get("align", "left"), 0)
        out += ESC + b"a" + bytes([align])
        out += ESC + b"E" + (b"\x01" if ln.get("bold") else b"\x00")
        size = 0x11 if ln.get("size") == "double" else (0x01 if ln.get("size") == "tall" else 0x00)
        out += GS + b"!" + bytes([size])
        text = ln.get("text", "")
        if ln.get("right"):
            pad = columns // (2 if size == 0x11 else 1) - len(text) - len(ln["right"])
            text = text + " " * max(1, pad) + ln["right"]
        out += (text + "\n").encode(codepage, "replace")
    out += ESC + b"a\x00" + GS + b"!\x00" + ESC + b"E\x00"
    out += b"\n\n\n"
    if cut:
        out += GS + b"V\x42\x00"
    return bytes(out)


def as_text(lines, columns=48):
    rows = []
    for ln in lines:
        if ln.get("rule"):
            rows.append("-" * columns)
            continue
        text = ln.get("text", "")
        if ln.get("right"):
            text = text + " " * max(1, columns - len(text) - len(ln["right"])) + ln["right"]
        if ln.get("align") == "center":
            text = text.center(columns)
        rows.append(text)
    return "\n".join(rows)


class PrinterError(Exception):
    pass


def send(printer, data: bytes, spool_dir: Path, job_id=None):
    if printer.connection == "network":
        if not printer.address:
            raise PrinterError("Yazıcı IP adresi tanımlı değil")
        try:
            with socket.create_connection((printer.address, printer.port), timeout=5) as s:
                s.sendall(data)
        except OSError as e:
            raise PrinterError(f"Ağ yazıcısına bağlanılamadı ({printer.address}:{printer.port}): {e}")
    elif printer.connection == "windows":
        try:
            import win32print  # pywin32 — Windows sunucuda kurulmalı
        except ImportError:
            raise PrinterError("Windows yazıcı sürücüsü için pywin32 kurulu değil (pip install pywin32)")
        try:
            h = win32print.OpenPrinter(printer.address)
            try:
                win32print.StartDocPrinter(h, 1, ("JETPOS", None, "RAW"))
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
                win32print.EndDocPrinter(h)
            finally:
                win32print.ClosePrinter(h)
        except Exception as e:
            raise PrinterError(f"Windows yazıcı hatası ({printer.address}): {e}")
    elif printer.connection == "file":
        folder = Path(printer.address) if printer.address else spool_dir / f"printer_{printer.id}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"job_{job_id or 'x'}.bin").write_bytes(data)
        except OSError as e:
            raise PrinterError(f"Dosyaya yazılamadı: {e}")
    else:
        raise PrinterError("Desteklenmeyen bağlantı türü")
