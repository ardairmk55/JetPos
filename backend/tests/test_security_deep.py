"""Derin güvenlik testleri: kiracı sızıntısı (IDOR), çapraz kiracı FK enjeksiyonu, CSRF, anonim erişim,
güvenlik başlıkları, saklı XSS ve toplu atama (mass assignment)."""
import re
from decimal import Decimal

import pytest
from django.urls import get_resolver
from rest_framework.test import APIClient

from apps.catalog.models import Category, Product, Station, TaxRate
from apps.core import roles
from apps.core.models import User
from apps.pos.models import Hall, Table

from .conftest import install_full_license, make_business, make_user


@pytest.fixture
def other(db):
    """İkinci işletme (B): ilk işletmenin hiçbir kaydı buna görünmemeli ve tersi."""
    biz, branch = make_business("Diger Lokanta", "diger-lokanta", "DGR")
    owner = make_user(biz, None, "b_sahip", roles.OWNER, pin="9191")
    waiter = make_user(biz, branch, "b_garson", roles.WAITER, pin="9292")
    tax = TaxRate.objects.create(business=biz, name="B KDV", rate=Decimal("10"))
    st = Station.objects.create(business=biz, branch=branch, name="B Mutfak")
    cat = Category.objects.create(business=biz, name="B Kategori", station=st, tax_rate=tax)
    prod = Product.objects.create(business=biz, category=cat, name="B Urun", base_price=Decimal("50"))
    hall = Hall.objects.create(business=biz, branch=branch, name="B Salon")
    table = Table.objects.create(business=biz, branch=branch, hall=hall, name="B1")
    install_full_license(biz)
    return type("B", (), dict(biz=biz, branch=branch, owner=owner, waiter=waiter, tax=tax, station=st, cat=cat,
                              prod=prod, hall=hall, table=table))


def _detail_routes():
    """(şablon, callback) — pk içeren tüm detay rotaları."""
    out = []

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                walk(p.url_patterns, prefix + str(p.pattern))
            else:
                full = prefix + str(p.pattern)
                if "<pk>" in full or "(?P<pk>" in full:
                    out.append((full, p.callback))

    walk(get_resolver().url_patterns)
    return out


def _clean(route, pk):
    r = re.sub(r"\(\?P<pk>[^)]*\)", str(pk), route)
    r = r.replace("<pk>", str(pk)).replace("^", "").replace("$", "").replace("?", "")
    return "/" + r.rstrip("/") + "/"


def _clone_a_rows_into_b(env, other):
    """A'nın tüm iş kayıtlarının kopyasını B'ye yazar: tarama her model için B nesnesi bulur."""
    from django.apps import apps as dj_apps
    from django.db import transaction

    n = 0
    for model in dj_apps.get_models():
        names = {f.name for f in model._meta.get_fields()}
        if "business" not in names or model._meta.app_label in ("core", "licensing") and model.__name__ in ("Business", "User", "Branch"):
            continue
        for row in list(model.objects.filter(business=env.biz)[:3]):
            row.pk = None
            row.id = None
            row.business = other.biz
            if "branch" in names and getattr(row, "branch_id", None):
                row.branch = other.branch
            try:
                with transaction.atomic():
                    row.save()
                    n += 1
            except Exception:
                pass
    return n


def test_cross_tenant_detail_routes_never_succeed(api, env, other, open_cash):
    """A işletmesi sahibi, B işletmesinin kayıtlarına hiçbir detay uç/aksiyon ile ulaşamaz veya değiştiremez."""
    w = api(env.waiter)
    t = w.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    w.post(f"/api/tickets/{t['id']}/add_line", {"product": env.tatli.id, "qty": 1}, format="json")
    cloned = _clone_a_rows_into_b(env, other)
    a = api(env.owner)
    a.raise_request_exception = False
    leaks = []
    checked = 0
    for route, cb in _detail_routes():
        cls = getattr(cb, "cls", None)
        qs = getattr(cls, "queryset", None)
        model = getattr(qs, "model", None) if qs is not None else None
        if model is None or not any(f.name == "business" for f in model._meta.get_fields()):
            continue
        target = model.objects.filter(business=other.biz).first()
        if target is None:
            continue
        url = _clean(route, target.pk)
        if "<" in url or "(" in url or "\\" in url:
            continue
        checked += 1
        for method in ("get", "patch", "delete", "post"):
            kw = {} if method in ("get", "delete") else {"data": {}, "format": "json"}
            resp = getattr(a, method)(url, **kw)
            if 200 <= resp.status_code < 300:
                leaks.append(f"{method.upper()} {url} -> {resp.status_code}")
    assert checked >= 15, "tarama çok az rota gördü"
    assert not leaks, "\n".join(leaks)
    assert Product.objects.filter(pk=other.prod.pk, is_active=True).exists()


def test_cross_tenant_lists_do_not_contain_foreign_rows(api, env, other):
    a = api(env.owner)
    for url in ("/api/products", "/api/categories", "/api/tables", "/api/halls", "/api/stations", "/api/tax-rates"):
        resp = a.get(url)
        assert resp.status_code == 200, url
        body = resp.content.decode()
        assert "B Urun" not in body and "B Kategori" not in body and "B Salon" not in body and "B Mutfak" not in body, url


def test_cross_tenant_foreign_keys_are_rejected(api, env, other, open_cash):
    """Başka işletmenin kaydı id ile bağlanmaya çalışılırsa reddedilir."""
    owner = api(env.owner)
    owner.raise_request_exception = False
    r = owner.patch(f"/api/products/{env.ayran.id}", {"category": other.cat.id}, format="json")
    assert r.status_code >= 400, r.content
    env.ayran.refresh_from_db()
    assert env.ayran.category_id == env.drinks.id
    r = owner.post("/api/products", {"name": "Sizinti", "category": other.cat.id, "base_price": "10"}, format="json")
    assert r.status_code >= 400, r.content
    assert not Product.objects.filter(business=env.biz, name="Sizinti").exists()

    w = api(env.waiter)
    w.raise_request_exception = False
    assert w.post(f"/api/tables/{other.table.id}/open", {}, format="json").status_code in (403, 404)
    t = w.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    r = w.post(f"/api/tickets/{t['id']}/add_line", {"product": other.prod.id, "qty": 1}, format="json")
    assert r.status_code >= 400, r.content


def test_foreign_ticket_not_visible_to_other_business(api, env, other, open_cash):
    t = api(other.waiter).post(f"/api/tables/{other.table.id}/open", {}, format="json").json()
    a = api(env.owner)
    a.raise_request_exception = False
    assert a.get(f"/api/tickets/{t['id']}").status_code == 404
    assert a.post(f"/api/tickets/{t['id']}/request_bill", {}, format="json").status_code == 404


# --------------------------------------------------------------------------- anonim erişim
PUBLIC_OK = re.compile(r"^/api/(auth/login|auth/pin-login|auth/pin-users|public|qr|jetmenu|licensing/public|applications|ops/ping|health|setup|portal/public)")


def test_anonymous_cannot_use_private_api(db):
    c = APIClient()
    c.raise_request_exception = False
    leaks = []
    seen = set()

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)

    for r in walk(get_resolver().url_patterns):
        r = re.sub(r"\(\?P<\w+>[^)]*\)", "1", r)
        r = re.sub(r"<(?:int:|str:|uuid:|slug:)?\w+>", "1", r)
        r = r.replace("^", "").replace("$", "").replace("?", "")
        if not r.startswith("api/") or "\\" in r or "format" in r:
            continue
        url = "/" + r.rstrip("/") + "/"
        if url in seen:
            continue
        seen.add(url)
        for method in ("get", "post", "patch", "delete"):
            kw = {} if method in ("get", "delete") else {"data": {}, "format": "json"}
            resp = getattr(c, method)(url, **kw)
            if resp.status_code < 300 and not PUBLIC_OK.match(url.rstrip("/")):
                leaks.append(f"{method.upper()} {url} -> {resp.status_code}")
    assert not leaks, "Anonim erişime açık beklenmeyen uçlar:\n" + "\n".join(leaks[:30])


def test_csrf_is_enforced_for_session_posts(env):
    c = APIClient(enforce_csrf_checks=True)
    c.raise_request_exception = False
    c.force_login(env.cashier)
    r = c.post("/api/auth/preferences", {"language": "en"}, format="json")
    assert r.status_code == 403, r.status_code


# --------------------------------------------------------------------------- başlıklar ve çerezler
def test_security_headers_and_cookies(env, client):
    r = client.get("/login/")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options", "").upper() in ("DENY", "SAMEORIGIN")
    resp = client.post("/api/auth/login", {"username": "sahip", "password": "Test-Pass-2026!"}, content_type="application/json")
    assert resp.status_code == 200
    ck = resp.cookies.get("sessionid")
    assert ck is not None and ck["httponly"] and ck["samesite"].lower() == "lax"


def test_login_error_does_not_reveal_which_part_is_wrong(env, client):
    a = client.post("/api/auth/login", {"username": "yok", "password": "x"}, content_type="application/json")
    b = client.post("/api/auth/login", {"username": "sahip", "password": "yanlis"}, content_type="application/json")
    assert a.status_code == b.status_code
    assert a.json().get("detail") == b.json().get("detail")


def test_weak_password_is_rejected(api, env):
    c = api(env.cashier)
    c.raise_request_exception = False
    for weak in ("123456", "password", "abc", env.cashier.username):
        r = c.post("/api/auth/change-password", {"old_password": "Test-Pass-2026!", "new_password": weak}, format="json")
        assert r.status_code == 400, (weak, r.status_code, r.content)


# --------------------------------------------------------------------------- toplu atama
def test_mass_assignment_cannot_escalate_role(api, env):
    c = api(env.cashier)
    c.raise_request_exception = False
    c.patch("/api/auth/preferences", {"language": "en", "role": roles.OWNER, "is_superuser": True, "is_staff": True,
                                      "business": 999}, format="json")
    u = User.objects.get(pk=env.cashier.pk)
    assert u.role == roles.CASHIER and not u.is_superuser and not u.is_staff and u.business_id == env.biz.id
    m = api(env.manager)
    m.raise_request_exception = False
    r = m.patch(f"/api/users/{env.cashier.id}", {"role": roles.OWNER}, format="json")
    env.cashier.refresh_from_db()
    assert env.cashier.role != roles.OWNER, r.content
    r = m.post("/api/users", {"username": "yeni_sahip", "role": roles.OWNER, "password": "Strong-Pass-2026!"}, format="json")
    assert not User.objects.filter(username="yeni_sahip", role=roles.OWNER).exists(), r.content


# --------------------------------------------------------------------------- saklı XSS
def test_stored_xss_payload_is_not_rendered_raw_in_server_html(api, env, client):
    payload = "<script>alert(1)</script>"
    owner = api(env.owner)
    r = owner.post("/api/products", {"name": payload, "category": env.food.id, "base_price": "10"}, format="json")
    assert r.status_code in (200, 201), r.content
    for url in ("/", "/login/", "/floor", "/catalog"):
        resp = client.get(url, follow=True)
        if "text/html" in resp.headers.get("Content-Type", ""):
            assert payload not in resp.content.decode(errors="ignore"), url
