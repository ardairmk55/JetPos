"""Kabul: Ödeme (bölünmüş/kısmi aynı adisyona bağlı, çift tahsilat engelli) ve Kasa (§6, §21)."""
from decimal import Decimal

from apps.pos.models import CashDay, Payment, Refund, Ticket


def _sent_ticket(api, env, items):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    for pid, qty in items:
        c.post(f"/api/tickets/{t['id']}/add_line", {"product": pid, "qty": qty}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY=f"s{t['id']}")
    return Ticket.objects.get(pk=t["id"])


def test_payment_requires_open_cash(api, env):
    t = _sent_ticket(api, env, [(env.ayran.id, 1)])
    r = api(env.cashier).post(f"/api/tickets/{t.id}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="a")
    assert r.status_code == 400 and r.json()["code"] == "cash_closed"


def test_split_payments_stay_on_same_ticket(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.tatli.id, 2), (env.ayran.id, 2)])  # 180 + 60 = 240
    c = api(env.cashier)
    prev = c.get(f"/api/tickets/{t.id}/split_preview?parts=3").json()
    assert [Decimal(str(s)) for s in prev["shares"]] == [Decimal("80.00")] * 3
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "card", "amount": "80.00", "split_mode": "equal"}, format="json",
               HTTP_IDEMPOTENCY_KEY="e1")
    assert r.status_code == 201 and Decimal(str(r.json()["remaining"])) == Decimal("160.00")
    ayran_line = t.lines.get(product=env.ayran)
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "meal_card", "lines": [ayran_line.id]}, format="json",
               HTTP_IDEMPOTENCY_KEY="e2")
    assert r.status_code == 201 and Decimal(str(r.json()["payment"]["amount"])) == Decimal("60.00")
    assert r.json()["payment"]["split_mode"] == "items"
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "cash", "tendered": "200"}, format="json", HTTP_IDEMPOTENCY_KEY="e3")
    p = r.json()["payment"]
    assert Decimal(str(p["amount"])) == Decimal("100.00") and Decimal(str(p["change"])) == Decimal("100.00")
    t.refresh_from_db()
    assert t.status == "paid" and t.paid_total == t.total == Decimal("240.00")
    assert Ticket.objects.filter(business=env.biz).count() == 1  # bölüştürme yeni adisyon yaratmaz
    assert Payment.objects.filter(ticket=t).count() == 3
    assert t.table.tickets.filter(status__in=("open", "bill_requested", "paid")).count() == 1


def test_duplicate_payment_is_blocked(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.tatli.id, 1)])
    c = api(env.cashier)
    r1 = c.post(f"/api/tickets/{t.id}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="same-key")
    r2 = c.post(f"/api/tickets/{t.id}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="same-key")
    assert r1.status_code == r2.status_code == 201
    assert r2["Idempotent-Replay"] == "true"
    assert Payment.objects.filter(ticket=t).count() == 1
    # Farklı anahtarla ikinci tahsilat: adisyon ödenmiş, reddedilir
    r3 = c.post(f"/api/tickets/{t.id}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="other")
    assert r3.status_code == 400 and Payment.objects.filter(ticket=t).count() == 1


def test_overpay_rejected_and_open_account_requires_customer(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.ayran.id, 1)])
    c = api(env.cashier)
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "card", "amount": "31"}, format="json", HTTP_IDEMPOTENCY_KEY="o1")
    assert r.status_code == 400 and r.json()["code"] == "overpay"
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "open_account"}, format="json", HTTP_IDEMPOTENCY_KEY="o2")
    assert r.json()["code"] == "customer_required"
    from apps.modules.models import Customer
    from apps.modules.services import customer_balance

    cust = Customer.objects.create(business=env.biz, name="Ali Veli", phone="5550000000")
    r = c.post(f"/api/tickets/{t.id}/pay", {"method": "open_account", "customer": cust.id}, format="json",
               HTTP_IDEMPOTENCY_KEY="o3")
    assert r.status_code == 201 and customer_balance(cust) == Decimal("30.00")


def test_drafts_block_payment(api, env, open_cash):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json")
    r = api(env.cashier).post(f"/api/tickets/{t['id']}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="d")
    assert r.json()["code"] == "drafts_pending"


def test_paid_and_physical_close_are_separate(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.ayran.id, 1)])
    c = api(env.cashier)
    c.post(f"/api/tickets/{t.id}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="z")
    t.refresh_from_db()
    assert t.status == "paid"
    floor = c.get("/api/floor").json()
    assert next(x for x in floor["tables"] if x["id"] == env.tables[0].id)["status"] == "paid"
    assert c.post(f"/api/tickets/{t.id}/close").status_code == 200
    t.refresh_from_db()
    assert t.status == "closed"
    floor = c.get("/api/floor").json()
    assert next(x for x in floor["tables"] if x["id"] == env.tables[0].id)["status"] == "empty"


def test_auto_close_setting(api, env, open_cash):
    s = env.branch.settings
    s.auto_close_on_payment = True
    s.save()
    t = _sent_ticket(api, env, [(env.ayran.id, 1)])
    api(env.cashier).post(f"/api/tickets/{t.id}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="ac")
    t.refresh_from_db()
    assert t.status == "closed"


def test_refund_is_reverse_record(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.tatli.id, 1)])
    c = api(env.cashier)
    pay = c.post(f"/api/tickets/{t.id}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="r0").json()["payment"]
    r = c.post(f"/api/payments/{pay['id']}/refund", {"amount": "40", "reason": "Soğuk geldi"}, format="json",
               HTTP_IDEMPOTENCY_KEY="r1")
    assert r.status_code == 403  # kasiyerin iade yetkisi yok
    r = c.post(f"/api/payments/{pay['id']}/refund", {"amount": "40", "reason": "Soğuk geldi",
                                                     "approver": {"user_id": env.manager.id, "pin": "8888"}},
               format="json", HTTP_IDEMPOTENCY_KEY="r2")
    assert r.status_code == 201
    p = Payment.objects.get(pk=pay["id"])
    assert p.amount == Decimal("90.00") and p.refunded_amount == Decimal("40.00") and p.status == "partially_refunded"
    rf = Refund.objects.get()
    assert rf.ticket_paid_before == Decimal("90.00") and rf.approved_by == env.manager
    r = api(env.manager).post(f"/api/payments/{pay['id']}/refund", {"amount": "60", "reason": "fazla"}, format="json",
                              HTTP_IDEMPOTENCY_KEY="r3")
    assert r.status_code == 400 and r.json()["code"] == "refund_amount"


def test_cash_day_close_flow(api, env, open_cash):
    t = _sent_ticket(api, env, [(env.tatli.id, 1)])
    c = api(env.cashier)
    c.post(f"/api/tickets/{t.id}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="c1")
    c.post("/api/cash", {"action": "movement", "kind": "expense", "amount": "25", "reason": "Ekmek alımı"}, format="json")
    data = c.get("/api/cash").json()
    assert Decimal(str(data["current"]["expected_now"])) == Decimal("565.00")  # 500 + 90 - 25
    r = c.post("/api/cash", {"action": "count", "counted": "560"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "difference_reason_required"
    r = c.post("/api/cash", {"action": "count", "counted": "560", "reason": "Bozuk para eksik"}, format="json")
    day = CashDay.objects.get()
    assert day.status == "pending_approval" and day.difference == Decimal("-5.00")
    assert day.report["cash"]["expected"] == "565.00" and day.report["payments"]["cash"]["amount"] == "90.00"
    assert c.post("/api/cash", {"action": "approve"}, format="json").status_code == 403  # kasiyer onaylayamaz
    assert api(env.manager).post("/api/cash", {"action": "approve"}, format="json").status_code == 200
    day.refresh_from_db()
    assert day.status == "closed" and day.approved_by == env.manager and day.report["approved_by"]
    r = c.post("/api/cash", {"action": "open", "opening_balance": 100}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "cash_day_exists"
