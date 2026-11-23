"""Performans bekçisi: sık kullanılan okuma uçlarının sorgu sayısı veri büyüdükçe artmamalı (N+1 koruması).

Aynı uç iki farklı veri boyutuyla çağrılır; sorgu sayısı veriyle birlikte büyüyorsa test başarısız olur.
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Product
from apps.pos.models import Table

ENDPOINTS = ["/api/floor", "/api/dashboard", "/api/products?all=1", "/api/categories", "/api/tickets", "/api/kitchen",
             "/api/ready-orders", "/api/stations", "/api/tables", "/api/notifications", "/api/users", "/api/stock/overview",
             "/api/payments", "/api/cash", "/api/halls", "/api/customers", "/api/couriers", "/api/deliveries?active=1",
             "/api/reservations", "/api/staff/shifts", "/api/finance/entries", "/api/printers", "/api/audit", "/api/qr-orders",
             "/api/option-groups", "/api/tax-rates", "/api/customer-groups", "/api/approvals"]


def _count(client, url):
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(url)
    return resp.status_code, len(ctx)


def _grow(env, api, n_tables, n_products):
    for i in range(n_tables):
        Table.objects.create(business=env.biz, branch=env.branch, hall=env.hall, name=f"x{i}")
    for i in range(n_products):
        Product.objects.create(business=env.biz, category=env.food, name=f"Urun {i}", base_price=Decimal("10"))
    from django.utils import timezone

    from apps.modules.models import Courier, Customer, FinanceEntry, Reservation
    from apps.printing.models import Printer

    for i in range(20):
        c = Customer.objects.create(business=env.biz, name=f"Musteri {i}", phone=f"555000{i:04d}")
        Courier.objects.create(business=env.biz, branch=env.branch, name=f"Kurye {i}")
        Reservation.objects.create(business=env.biz, branch=env.branch, customer=c, name=f"R{i}", phone="1", party_size=2,
                                   starts_at=timezone.now() + timezone.timedelta(hours=i % 5), status="confirmed",
                                   table=Table.objects.filter(branch=env.branch).first(), created_by=env.manager)
        FinanceEntry.objects.create(business=env.biz, branch=env.branch, kind="expense", amount=10 + i,
                                    date=timezone.localdate(), user=env.manager)
        Printer.objects.create(business=env.biz, branch=env.branch, name=f"P{i}", connection="file")
    w = api(env.waiter)
    for t in list(Table.objects.filter(branch=env.branch).order_by("id")[:6]):
        tk = w.post(f"/api/tables/{t.id}/open", {}, format="json").json()
        w.post(f"/api/tickets/{tk['id']}/add_line", {"product": env.ayran.id, "qty": 1}, format="json")
        w.post(f"/api/tickets/{tk['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY=f"q{tk['id']}")


def test_read_endpoints_do_not_have_n_plus_one(api, env, open_cash):
    m = api(env.manager)
    small = {u: _count(m, u) for u in ENDPOINTS}
    _grow(env, api, n_tables=25, n_products=40)
    large = {u: _count(m, u) for u in ENDPOINTS}
    problems = []
    for u in ENDPOINTS:
        (c1, q1), (c2, q2) = small[u], large[u]
        assert c2 < 500, (u, c2)
        # veri ~5-10 kat büyüdü; sorgu sayısı en fazla küçük sabit kadar artabilir
        if q2 > q1 + 6:
            problems.append(f"{u}: {q1} -> {q2} sorgu")
    assert not problems, "N+1 şüphesi:\n" + "\n".join(problems)
    assert all(q <= 60 for _, q in large.values()), {u: q for u, (_, q) in large.items() if q > 60}
