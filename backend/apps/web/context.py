from pathlib import Path

import jetpos

_STATIC = Path(__file__).resolve().parent / "static" / "web"


def _asset_version():
    """Statik dosyaların en yeni değişiklik zamanı: önbellek sürümü (?v=)."""
    try:
        return str(int(max(f.stat().st_mtime for f in [_STATIC / "app.css", *(_STATIC / "js").glob("*.js")])))
    except (OSError, ValueError):
        return jetpos.__version__


def jetpos_context(request):
    user = getattr(request, "user", None)
    auth = bool(user and user.is_authenticated)
    return {
        "JETPOS_VERSION": jetpos.__version__,
        "ASSET_V": _asset_version(),
        "user_theme": getattr(user, "theme", "light") if auth else "light",
        "user_lang": getattr(user, "language", "tr") if auth else "tr",
        "user_font_scale": getattr(user, "font_scale", 100) if auth else 100,
        "user_contrast": getattr(user, "high_contrast", False) if auth else False,
    }
