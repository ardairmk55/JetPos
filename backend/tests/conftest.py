from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Category, CustomerGroup, Option, OptionGroup, Product, Station, TaxRate
from apps.core import roles
from apps.core.middleware import reset_rate_limits
from apps.core.models import Branch, BranchSettings, Business, User
from apps.pos.models import Hall, Table


def make_user(biz, branch, username, role, pin="1234", password="Test-Pass-2026!"):
    u = User(username=username, business=biz, branch=branch if role in roles.BRANCH_SCOPED_ROLES else None, role=role,
             first_name=username.title())
    u.set_password(password)
    u.set_pin(pin)
    u.save()
    return u


def make_business(name="Test Lokanta", slug="test-lokanta", code="MRK"):
    biz = Business.objects.create(name=name, slug=slug)
    branch = Branch.objects.create(business=biz, name="Merkez", code=code)
    BranchSettings.objects.create(branch=branch)
    return biz, branch


def install_full_license(biz, modules=None):
    from apps.licensing.services import ensure_platform_keys, install_license, issue_license

    ensure_platform_keys()
    rec = issue_license(business=biz, package="enterprise", modules=modules if modules is not None else [
        "stock", "crm", "delivery", "reservation", "staff", "finance", "reports_advanced", "jetmenu", "multi_branch"])
    install_license(biz, rec.signed_blob)
    return rec


@pytest.fixture(autouse=True)
def _no_rate_limit():
    reset_rate_limits()
    from apps.printing import services

    services.SYNC_PRINT["enabled"] = False
    yield


@pytest.fixture
def env(db):
    biz, branch = make_business()
    owner = make_user(biz, None, "sahip", roles.OWNER, pin="9999")
    manager = make_user(biz, branch, "mudur", roles.BRANCH_MANAGER, pin="8888")
    cashier = make_user(biz, branch, "kasiyer", roles.CASHIER, pin="7777")
    waiter = make_user(biz, branch, "garson", roles.WAITER, pin="1111")
    waiter2 = make_user(biz, branch, "garson2", roles.WAITER, pin="2222")
    cook = make_user(biz, branch, "asci", roles.KITCHEN, pin="3333")
    stocker = make_user(biz, branch, "depo", roles.STOCK, pin="4444")
    tax = TaxRate.objects.create(business=biz, name="KDV test", rate=Decimal("10"))
    kitchen = Station.objects.create(business=biz, branch=branch, name="Ana Mutfak")
    bar = Station.objects.create(business=biz, branch=branch, name="İçecek")
    food = Category.objects.create(business=biz, name="Yemek", station=kitchen, tax_rate=tax)
    drinks = Category.objects.create(business=biz, name="İçecek", station=bar, tax_rate=tax)
    cooking = OptionGroup.objects.create(business=biz, name="Pişirme", kind="cooking", required=True, min_select=1, max_select=1)
    o_az = Option.objects.create(group=cooking, name="Az pişmiş")
    o_orta = Option.objects.create(group=cooking, name="Orta")
    extra = OptionGroup.objects.create(business=biz, name="Ekstra", kind="extra", min_select=0, max_select=2)
    o_peynir = Option.objects.create(group=extra, name="Peynir", price_delta=Decimal("20"))
    o_sos = Option.objects.create(group=extra, name="Sos", price_delta=Decimal("5"))
    kofte = Product.objects.create(business=biz, category=food, name="Köfte", base_price=Decimal("200"))
    kofte.option_groups.set([cooking, extra])
    ayran = Product.objects.create(business=biz, category=drinks, name="Ayran", base_price=Decimal("30"))
    tatli = Product.objects.create(business=biz, category=food, name="Sütlaç", base_price=Decimal("90"))
    hall = Hall.objects.create(business=biz, branch=branch, name="İç Salon")
    tables = [Table.objects.create(business=biz, branch=branch, hall=hall, name=str(i)) for i in range(1, 6)]
    belediye = CustomerGroup.objects.create(business=biz, name="Belediye personeli", discount_type="percent",
                                            discount_value=Decimal("20"), approver="cashier")
    install_full_license(biz)
    return SimpleNamespace(**locals())


@pytest.fixture
def api():
    def make(user=None):
        c = APIClient()
        if user is not None:
            c.force_login(user)
        return c

    return make


@pytest.fixture
def open_cash(env):
    from apps.pos.services import open_cash_day

    return open_cash_day(env.branch, user=env.cashier, opening_balance=500)
