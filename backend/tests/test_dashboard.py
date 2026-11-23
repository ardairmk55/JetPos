"""Dashboard: tarih seçimi, nakit/kart tahsilat, aktif masa, operasyon listeleri, rol bazlı kapsam."""
from datetime import timedelta

from django.utils import timezone

from apps.pos.models import Ticket


def _sale(api, env, pay="cash"):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.tatli.id, "qty": 2}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY=f"d{t['id']}")
    api(env.cashier).post(f"/api/tickets/{t['id']}/pay", {"method": pay}, format="json", HTTP_IDEMPOTENCY_KEY=f"p{t['id']}")
    api(env.cashier).post(f"/api/tickets/{t['id']}/close")
    return t["id"]


def test_dashboard_cards_lists_and_date(api, env, open_cash):
    _sale(api, env, "cash")
    m = api(env.manager)
    d = m.get("/api/dashboard").json()
    assert d["date"] == d["today"]
    assert d["cards"]["sales_today"]["value"] == 180.0 and d["cards"]["tickets_today"]["value"] == 1
    assert d["cards"]["payments_cash"]["value"] == 180.0 and d["cards"]["payments_card"]["value"] == 0
    assert d["cards"]["active_tables"] == {"value": 0, "total": 5}
    assert set(d["lists"]) >= {"open_tables", "kitchen", "ready", "low_stock"}
    assert d["charts"]["week"]["series"][0]["data"][-1] == 180.0 and len(d["charts"]["week"]["labels"]) == 7
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    past = m.get(f"/api/dashboard?date={yesterday}").json()
    assert past["date"] == yesterday and past["cards"]["sales_today"]["value"] == 0
    assert {"value", "prev", "last_week"} <= set(d["cards"]["sales_today"])


def test_dashboard_future_date_rejected(api, env):
    tomorrow = (timezone.localdate() + timedelta(days=1)).isoformat()
    r = api(env.manager).get(f"/api/dashboard?date={tomorrow}")
    assert r.status_code == 400


def test_dashboard_open_table_list_and_role_scope(api, env, open_cash):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[1].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json")
    d = api(env.manager).get("/api/dashboard").json()
    assert d["cards"]["active_tables"]["value"] == 1
    assert d["lists"]["open_tables"][0]["table"] == env.tables[1].name and d["lists"]["open_tables"][0]["total"] == 30.0
    w = c.get("/api/dashboard").json()
    assert "sales_today" not in w["cards"] and "payments_cash" not in w["cards"] and w["charts"] == {}
    k = api(env.cook).get("/api/dashboard").json()
    assert "open_tables" not in k["lists"] and "kitchen_pending" in k["cards"]
    assert Ticket.objects.filter(pk=t["id"]).exists()
