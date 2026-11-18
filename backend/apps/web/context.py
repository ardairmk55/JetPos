import jetpos


def jetpos_context(request):
    user = getattr(request, "user", None)
    auth = bool(user and user.is_authenticated)
    return {
        "JETPOS_VERSION": jetpos.__version__,
        "user_theme": getattr(user, "theme", "light") if auth else "light",
        "user_lang": getattr(user, "language", "tr") if auth else "tr",
        "user_font_scale": getattr(user, "font_scale", 100) if auth else 100,
        "user_contrast": getattr(user, "high_contrast", False) if auth else False,
    }
