import secrets
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.models import Branch, BranchSettings, Business, SearchHistory, User
from apps.core.tenancy import current_branch, current_business

from .help_content import search_help


# ------------------------------------------------------------------ sayfalar (SPA kabuğu)
@ensure_csrf_cookie
def login_page(request):
    if not Business.objects.exists() and not User.objects.filter(is_superuser=True).exists():
        return redirect("/setup")
    return render(request, "web/login.html")


@ensure_csrf_cookie
@login_required
def app_shell(request, *args, **kwargs):
    return render(request, "web/app.html")


@ensure_csrf_cookie
def setup_page(request):
    if Business.objects.exists():
        return redirect("/login/")
    return render(request, "web/setup.html")


@ensure_csrf_cookie
def apply_page(request):
    return render(request, "web/apply.html")


def service_worker(request):
    from django.http import HttpResponse
    from django.contrib.staticfiles import finders

    path = finders.find("web/js/sw.js")
    with open(path, "rb") as f:
        resp = HttpResponse(f.read(), content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp


def manifest(request):
    from django.http import JsonResponse

    return JsonResponse({
        "name": "POSHANE", "short_name": "POSHANE", "description": "Hızlı Servis, Akıllı Yönetim.",
        "start_url": "/waiter", "scope": "/", "display": "standalone", "background_color": "#252936",
        "theme_color": "#252936", "lang": "tr",
        "icons": [{"src": "/static/web/img/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/web/img/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    })


# ------------------------------------------------------------------ global arama (§4.2, §10.3)
class SearchView(APIView):
    def get(self, request):
        q = (request.GET.get("q") or "").strip()
        user = request.user
        if len(q) < 2 and not q.isdigit():
            recent = list(SearchHistory.objects.filter(user=user).values_list("query", flat=True)[:30])
            seen = []
            for r in recent:
                if r not in seen:
                    seen.append(r)
            return Response({"results": [], "recent": seen[:8]})
        SearchHistory.objects.create(user=user, query=q[:200])
        biz = current_business(request)
        branch = current_branch(request)
        out = []

        def add(kind, label, sub, url):
            out.append({"kind": kind, "label": label, "sub": sub, "url": url})

        from apps.catalog.models import Category, Product
        from apps.pos.models import Payment, Table, Ticket

        if roles.has_perm(user, roles.FLOOR_VIEW):
            for t in Table.objects.filter(branch=branch, is_active=True, name__icontains=q)[:8]:
                add("table", f"Masa {t.name}", t.hall.name, f"/floor?table={t.id}")
            tq = Ticket.objects.filter(branch=branch)
            tq = tq.filter(number=int(q)) if q.isdigit() else tq.filter(Q(table__name__icontains=q) | Q(note__icontains=q))
            for t in tq.order_by("-id")[:8]:
                add("ticket", f"Adisyon #{t.number}", f"{t.business_date} · {t.get_status_display()} · {t.total} TL",
                    f"/ticket/{t.id}")
            for p in Product.objects.filter(business=biz, is_active=True).filter(
                    Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode=q))[:8]:
                add("product", p.name, f"{p.category.name} · {p.base_price} TL", f"/catalog?product={p.id}")
            for c in Category.objects.filter(business=biz, is_active=True, name__icontains=q)[:5]:
                add("category", c.name, "Kategori", f"/catalog?category={c.id}")
        if roles.has_perm(user, roles.USERS_MANAGE):
            for u in User.objects.filter(business=biz).filter(
                    Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))[:8]:
                add("staff", u.get_full_name() or u.username, u.get_role_display(), f"/users?user={u.id}")
        if roles.has_perm(user, roles.CRM_MANAGE) or roles.has_perm(user, roles.TICKET_OPEN):
            from apps.modules.models import Customer

            for c in Customer.objects.filter(business=biz, is_active=True).filter(Q(name__icontains=q) | Q(phone__icontains=q))[:8]:
                add("customer", c.name, c.phone[-4:].rjust(len(c.phone), "•") if c.phone else "", f"/customers?id={c.id}")
        if roles.has_perm(user, roles.PAYMENT_TAKE):
            pq = Payment.objects.filter(branch=branch)
            cond = Q(reference__icontains=q) | Q(txn_id__icontains=q)
            try:
                cond |= Q(amount=Decimal(q.replace(",", ".")))
            except Exception:
                pass
            for p in pq.filter(cond).order_by("-id")[:8]:
                add("payment", f"{p.get_method_display()} {p.amount} TL", f"Adisyon #{p.ticket.number} · {p.created_at:%d.%m %H:%M}",
                    f"/ticket/{p.ticket_id}")
        if roles.has_perm(user, roles.RESERVATION_MANAGE) or roles.has_perm(user, roles.FLOOR_VIEW):
            from apps.modules.models import Reservation

            for r in Reservation.objects.filter(branch=branch).filter(Q(name__icontains=q) | Q(phone__icontains=q))[:5]:
                add("reservation", r.name, f"{r.starts_at:%d.%m %H:%M} · {r.party_size} kişi · {r.get_status_display()}",
                    "/reservations")
        if roles.has_perm(user, roles.STOCK_VIEW):
            from apps.inventory.models import StockItem

            for s in StockItem.objects.filter(business=biz, is_active=True, name__icontains=q)[:5]:
                add("stock", s.name, s.get_unit_display(), "/stock")
        if roles.has_perm(user, roles.AUDIT_VIEW):
            from apps.core.models import AuditLog

            for a in AuditLog.objects.filter(business=biz, action__icontains=q)[:5]:
                add("history", a.action, f"{a.created_at:%d.%m %H:%M} · {a.user.username if a.user else ''}", "/audit")
        suggestions = list(Product.objects.filter(business=biz, is_active=True, name__istartswith=q[:2])
                           .values_list("name", flat=True)[:5])
        return Response({"results": out, "suggestions": suggestions})


class HelpView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        role = request.user.role if request.user.is_authenticated else ""
        return Response(search_help(request.GET.get("q"), role))


# ------------------------------------------------------------------ kurulum sihirbazı (§18.1)
TEMPLATES = {
    "restaurant": {"halls": ["İç Salon", "Bahçe"], "stations": ["Ana Mutfak", "İçecek", "Tatlı"],
                   "categories": [("Çorbalar", "Ana Mutfak"), ("Ana Yemekler", "Ana Mutfak"), ("Salatalar", "Ana Mutfak"),
                                  ("Tatlılar", "Tatlı"), ("İçecekler", "İçecek")]},
    "cafe": {"halls": ["Salon", "Teras"], "stations": ["Bar", "Mutfak"],
             "categories": [("Sıcak İçecekler", "Bar"), ("Soğuk İçecekler", "Bar"), ("Tatlılar", "Mutfak"),
                            ("Atıştırmalıklar", "Mutfak")]},
    "breakfast": {"halls": ["Salon", "Bahçe"], "stations": ["Mutfak", "İçecek"],
                  "categories": [("Kahvaltı Tabakları", "Mutfak"), ("Yumurtalar", "Mutfak"), ("Sıcak İçecekler", "İçecek"),
                                 ("Soğuk İçecekler", "İçecek")]},
    "municipal": {"halls": ["Salon"], "stations": ["Mutfak", "İçecek"],
                  "categories": [("Ana Yemekler", "Mutfak"), ("Çorbalar", "Mutfak"), ("İçecekler", "İçecek")]},
    "other": {"halls": ["Salon"], "stations": ["Mutfak"], "categories": [("Genel", "Mutfak")]},
}


def run_setup(data, actor=None):
    """Sihirbaz: işletme, şube/salon, masa, kullanıcı/rol, menü şablonu, yazıcı, kasa/ödeme, yedek/güvenlik, son kontrol."""
    from apps.catalog.models import Category, Station, TaxRate
    from apps.core.views import make_slug
    from apps.pos.models import Hall, Table
    from apps.printing.models import Printer

    biz_d = data.get("business") or {}
    owner_d = data.get("owner") or {}
    if not biz_d.get("name") or not owner_d.get("username") or not owner_d.get("password"):
        raise BusinessError("İşletme adı, yönetici kullanıcı adı ve şifresi zorunludur")
    from django.contrib.auth.password_validation import validate_password

    validate_password(owner_d["password"])
    # Kullanıcı adları benzersiz olmalı; aksi halde veritabanı hatası (500) yerine açık bir uyarı verilir.
    names = [owner_d["username"].strip()] + [u["username"].strip() for u in data.get("users") or [] if u.get("username")]
    seen = set()
    for n in names:
        if n.lower() in seen:
            raise BusinessError(f"'{n}' kullanıcı adı birden fazla kez girilmiş; her kullanıcı adı benzersiz olmalıdır")
        seen.add(n.lower())
    taken = User.objects.filter(username__in=names).values_list("username", flat=True).first()
    if taken:
        raise BusinessError(f"'{taken}' kullanıcı adı zaten kullanılıyor")
    tpl_key = biz_d.get("template", "restaurant")
    tpl = TEMPLATES.get(tpl_key, TEMPLATES["other"])
    with transaction.atomic():
        biz = Business.objects.create(name=biz_d["name"], slug=make_slug(biz_d["name"]), template=tpl_key,
                                      phone=biz_d.get("phone", ""), email=biz_d.get("email", ""),
                                      tax_office=biz_d.get("tax_office", ""), tax_number=biz_d.get("tax_number", ""),
                                      is_corporate=tpl_key == "municipal")
        br_d = data.get("branch") or {}
        branch = Branch.objects.create(business=biz, name=br_d.get("name") or "Merkez", code=br_d.get("code") or "MRK",
                                       address=br_d.get("address", ""))
        sec = data.get("security") or {}
        BranchSettings.objects.create(
            branch=branch, auto_close_on_payment=bool((data.get("payment") or {}).get("auto_close")),
            inactivity_lock_minutes=int(sec.get("inactivity_lock_minutes") or 5),
            stock_deduction=(data.get("stock") or {}).get("deduction", "send"),
            receipt_header=biz_d["name"])
        owner = User(username=owner_d["username"], first_name=owner_d.get("first_name", ""),
                     last_name=owner_d.get("last_name", ""), email=owner_d.get("email", ""), business=biz,
                     role=roles.OWNER)
        owner.set_password(owner_d["password"])
        if owner_d.get("pin"):
            owner.set_pin(owner_d["pin"])
        owner.save()
        stations = {name: Station.objects.create(business=biz, branch=branch, name=name, sort=i)
                    for i, name in enumerate(tpl["stations"])}
        tax = None
        for t in data.get("taxes") or []:
            if t.get("name") and t.get("rate") not in (None, ""):
                obj = TaxRate.objects.create(business=biz, name=t["name"], rate=Decimal(str(t["rate"])))
                tax = tax or obj
        if (data.get("menu") or {}).get("use_template", True):
            for i, (cname, st) in enumerate(tpl["categories"]):
                Category.objects.create(business=biz, name=cname, station=stations.get(st), tax_rate=tax, sort=i)
        halls = data.get("halls") or [{"name": h, "tables": 0} for h in tpl["halls"]]
        for hi, h in enumerate(halls):
            hall = Hall.objects.create(business=biz, branch=branch, name=h["name"], sort=hi)
            for n in range(int(h.get("tables") or 0)):
                Table.objects.create(business=biz, branch=branch, hall=hall, name=f"{h.get('prefix', '')}{n + 1}",
                                     x=20 + (n % 6) * 140, y=20 + (n // 6) * 140)
        for u in data.get("users") or []:
            if not u.get("username"):
                continue
            if u.get("role") not in roles.BUSINESS_ROLES or u["role"] == roles.OWNER:
                raise BusinessError(f"Geçersiz rol: {u.get('role')}")
            nu = User(username=u["username"], first_name=u.get("first_name", ""), business=biz, branch=branch,
                      role=u["role"])
            nu.set_password(u.get("password") or secrets.token_urlsafe(12))
            if u.get("pin"):
                nu.set_pin(u["pin"])
            nu.save()
        for p in data.get("printers") or []:
            if p.get("name"):
                pr = Printer.objects.create(business=biz, branch=branch, name=p["name"], connection=p.get("connection", "network"),
                                            address=p.get("address", ""), port=int(p.get("port") or 9100),
                                            width_mm=int(p.get("width_mm") or 80), target=p.get("target", "kitchen"),
                                            print_receipts=p.get("target") == "cashier")
                if p.get("station") in stations:
                    pr.stations.add(stations[p["station"]])
        bk = data.get("backup") or {}
        if bk.get("time"):
            from apps.ops.models import BackupPolicy

            pol = BackupPolicy.get()
            pol.daily_time = bk["time"]
            pol.save()
        audit.log("setup.complete", user=owner, business=biz, branch=branch, entity="Business", entity_id=biz.pk,
                  after={"template": tpl_key})
    if data.get("license_blob"):
        from apps.licensing.services import install_license

        install_license(biz, data["license_blob"], user=owner)
    return biz, owner


class SetupView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.conf import settings

        import psutil

        return Response({
            "needed": not Business.objects.exists(),
            "templates": list(TEMPLATES.keys()),
            "checks": {
                "database": settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1],
                "disk_free_gb": round(psutil.disk_usage(str(settings.DATA_DIR)).free / 1e9, 1),
                "license_public_key": settings.JETPOS["LICENSE_PUBLIC_KEY_FILE"].exists(),
                "smtp": settings.EMAIL_BACKEND.endswith("smtp.EmailBackend"),
            },
        })

    def post(self, request):
        if Business.objects.exists() and not (request.user.is_authenticated and request.user.is_platform):
            raise BusinessError("Kurulum zaten tamamlanmış", status_code=403)
        biz, owner = run_setup(request.data)
        return Response({"business": biz.name, "owner": owner.username}, status=201)


class PrinterProbeView(APIView):
    """Kurulumda ağ yazıcısı erişim testi (TCP bağlantısı)."""

    def post(self, request):
        import socket

        if not roles.has_perm(request.user, roles.PRINTERS_MANAGE):
            raise BusinessError("Yetkiniz yok", status_code=403)
        host, port = request.data.get("address", ""), int(request.data.get("port") or 9100)
        try:
            with socket.create_connection((host, port), timeout=3):
                return Response({"ok": True})
        except OSError as e:
            return Response({"ok": False, "error": str(e)})
