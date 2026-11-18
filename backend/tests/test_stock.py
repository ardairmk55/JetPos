"""Kabul: Stok — reçete tüketimi bir kez işlenir; iade/iptal kontrollü ters hareket (§8, §21)."""
from decimal import Decimal

from apps.core.models import Notification
from apps.inventory import services as inv
from apps.inventory.models import RecipeLine, StockItem, StockMovement, Warehouse
from apps.pos.models import Ticket


def _setup_recipe(env, qty="500"):
    wh = inv.default_warehouse(env.branch)
    kiyma = StockItem.objects.create(business=env.biz, name="Kıyma", unit="kg", min_level=Decimal("0.3"), cost=Decimal("400"))
    RecipeLine.objects.create(business=env.biz, product=env.kofte, item=kiyma, qty=Decimal("150"), unit="g")
    inv.manual_movement(warehouse=wh, item=kiyma, kind="opening", qty=Decimal(qty) / 1000, user=env.stocker, reason="Açılış")
    return wh, kiyma


def _order(api, env, qty=2):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.kofte.id, "qty": qty, "options": [env.o_orta.id]}, format="json")
    return c, t["id"]


def test_recipe_consumed_once(api, env):
    wh, kiyma = _setup_recipe(env)
    c, tid = _order(api, env)
    c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="k")
    c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="k")
    assert inv.level(wh, kiyma) == Decimal("0.2")  # 0.5 - 2*0.15
    lines = list(Ticket.objects.get(pk=tid).lines.all())
    inv.deduct_for_lines(lines, user=env.waiter)  # tekrar çağrı çift düşüm yapmaz
    assert inv.level(wh, kiyma) == Decimal("0.2")
    assert StockMovement.objects.filter(kind="sale").count() == 1
    mv = StockMovement.objects.get(kind="sale")
    assert mv.before == Decimal("0.5") and mv.after == Decimal("0.2")
    assert Notification.objects.filter(event="low_stock", user=env.stocker).exists()


def test_void_reverses_stock_once(api, env):
    wh, kiyma = _setup_recipe(env)
    c, tid = _order(api, env)
    c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="k")
    line = Ticket.objects.get(pk=tid).lines.get()
    m = api(env.manager)
    m.post(f"/api/tickets/{tid}/void_line", {"line": line.id, "qty": 1, "reason": "Vazgeçti"}, format="json")
    assert inv.level(wh, kiyma) == Decimal("0.35")
    m.post(f"/api/tickets/{tid}/void_line", {"line": line.id, "qty": 1, "reason": "Vazgeçti"}, format="json")
    assert inv.level(wh, kiyma) == Decimal("0.5")
    assert StockMovement.objects.filter(kind="sale_reversal").count() == 2


def test_block_policy_and_deduction_timing(api, env):
    wh, kiyma = _setup_recipe(env, qty="100")
    env.kofte.stock_policy = "block"
    env.kofte.save()
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    r = c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.kofte.id, "options": [env.o_orta.id]}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "out_of_stock"
    env.kofte.stock_policy = "warn"
    env.kofte.save()
    r = c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.kofte.id, "options": [env.o_orta.id]}, format="json")
    assert r.status_code == 201 and "warning" in r.json()


def test_deduction_on_payment_setting(api, env, open_cash):
    wh, kiyma = _setup_recipe(env)
    s = env.branch.settings
    s.stock_deduction = "payment"
    s.save()
    c, tid = _order(api, env, qty=1)
    c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="k")
    assert inv.level(wh, kiyma) == Decimal("0.5")
    api(env.cashier).post(f"/api/tickets/{tid}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="p")
    assert inv.level(wh, kiyma) == Decimal("0.35")


def test_purchase_transfer_count_and_manual_requires_reason(api, env):
    s = api(env.stocker)
    item = s.post("/api/stock/items", {"name": "Süt", "unit": "lt", "min_level": 2, "cost": 30}, format="json").json()
    wh = inv.default_warehouse(env.branch)
    r = s.post("/api/stock/purchases", {"lines": [{"item": item["id"], "qty": 10, "unit_cost": 40}], "document_no": "A1"},
               format="json")
    assert r.status_code == 201 and Decimal(str(r.json()["total"])) == Decimal("400.00")
    assert inv.level(wh, StockItem.objects.get(pk=item["id"])) == 10
    wh2 = Warehouse.objects.create(business=env.biz, branch=env.branch, name="Bar Depo")
    r = s.post("/api/stock/transfers", {"source": wh.id, "target": wh2.id, "lines": [{"item": item["id"], "qty": 4}]}, format="json")
    assert r.status_code == 201
    it = StockItem.objects.get(pk=item["id"])
    assert inv.level(wh, it) == 6 and inv.level(wh2, it) == 4
    r = s.post("/api/stock/transfers", {"source": wh.id, "target": wh2.id, "lines": [{"item": item["id"], "qty": 99}]}, format="json")
    assert r.status_code == 400
    r = s.post(f"/api/stock/items/{item['id']}/move", {"kind": "waste", "qty": 1, "reason": ""}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "reason_required"
    r = s.post(f"/api/stock/items/{item['id']}/move", {"kind": "waste", "qty": 1, "reason": "Döküldü"}, format="json")
    assert r.status_code == 201 and Decimal(str(r.json()["before"])) == 6 and Decimal(str(r.json()["after"])) == 5
    c = s.post("/api/stock/counts", {"lines": [{"item": item["id"], "counted": 4.5}]}, format="json").json()
    s.post("/api/stock/counts", {"apply_id": c["id"]}, format="json")
    assert inv.level(wh, it) == Decimal("4.5")
    ov = s.get("/api/stock/overview").json()
    assert ov["cards"]["items"] == 1 and ov["rows"][0]["qty"] == 4.5


def test_unit_conversion_validation(api, env):
    s = api(env.manager)
    item = StockItem.objects.create(business=env.biz, name="Un", unit="kg")
    r = s.post("/api/stock/recipes", {"product": env.tatli.id, "item": item.id, "qty": 2, "unit": "lt"}, format="json")
    assert r.status_code == 400
