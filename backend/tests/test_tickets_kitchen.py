"""Kabul: Masa/adisyon, Taslak, Mutfak (§21)."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.core.models import Notification
from apps.pos.models import KitchenOrder, Ticket


def _open(api, env, user=None, table=None):
    c = api(user or env.waiter)
    r = c.post(f"/api/tables/{(table or env.tables[0]).id}/open", {}, format="json")
    assert r.status_code in (200, 201), r.content
    return c, r.json()


def test_one_active_ticket_per_table(api, env):
    c, t1 = _open(api, env)
    _, t2 = _open(api, env, user=env.waiter2)
    assert t1["id"] == t2["id"]
    assert Ticket.objects.filter(table=env.tables[0]).count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        Ticket.objects.create(business=env.biz, branch=env.branch, table=env.tables[0], number=99,
                              business_date="2026-11-18", status="open")


def test_option_validation_and_price(api, env):
    c, t = _open(api, env)
    r = c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.kofte.id, "options": []}, format="json")
    assert r.status_code == 400 and "Pişirme" in r.json()["detail"]
    r = c.post(f"/api/tickets/{t['id']}/add_line",
               {"product": env.kofte.id, "options": [env.o_orta.id, env.o_peynir.id, env.o_sos.id], "qty": 2}, format="json")
    assert r.status_code == 201
    line = r.json()["lines"][0]
    assert Decimal(str(line["unit_price"])) == Decimal("225.00")
    assert Decimal(str(r.json()["total"])) == Decimal("450.00")
    assert {o["name"] for o in line["options"]} == {"Orta", "Peynir", "Sos"}


def test_draft_editable_and_send_requires_confirmation(api, env):
    c, t = _open(api, env)
    tid = t["id"]
    line = c.post(f"/api/tickets/{tid}/add_line", {"product": env.ayran.id}, format="json").json()["lines"][0]
    assert c.post(f"/api/tickets/{tid}/update_line", {"line": line["id"], "qty": 3, "note": "buzlu"}, format="json").status_code == 200
    assert c.post(f"/api/tickets/{tid}/delete_line", {"line": line["id"]}, format="json").json()["lines"] == []
    c.post(f"/api/tickets/{tid}/add_line", {"product": env.ayran.id}, format="json")
    r = c.post(f"/api/tickets/{tid}/send", {}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
    assert r.status_code == 409 and r.json()["code"] == "confirmation_required" and r.json()["summary"]
    r = c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="k2")
    assert r.status_code == 200 and r.json()["sent_batch"] == 1
    sent = r.json()["lines"][0]
    r = c.post(f"/api/tickets/{tid}/update_line", {"line": sent["id"], "qty": 5}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "line_sent"
    assert c.post(f"/api/tickets/{tid}/delete_line", {"line": sent["id"]}, format="json").status_code == 400
    # Sonraki parti hızlı gönderim (onay istemez) ve yeni parti numarası alır
    c.post(f"/api/tickets/{tid}/add_line", {"product": env.ayran.id}, format="json")
    r = c.post(f"/api/tickets/{tid}/send", {}, format="json", HTTP_IDEMPOTENCY_KEY="k3")
    assert r.status_code == 200 and r.json()["sent_batch"] == 2


def test_send_requires_idempotency_key(api, env):
    c, t = _open(api, env)
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json")
    r = c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"


def test_kitchen_routing_and_ready_notification(api, env):
    c, t = _open(api, env)
    tid = t["id"]
    c.post(f"/api/tickets/{tid}/add_line", {"product": env.kofte.id, "options": [env.o_az.id]}, format="json")
    c.post(f"/api/tickets/{tid}/add_line", {"product": env.ayran.id}, format="json")
    c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="s1")
    orders = KitchenOrder.objects.filter(batch__ticket_id=tid)
    assert {o.station.name for o in orders} == {"Ana Mutfak", "İçecek"}
    kc = api(env.cook)
    kitchen_list = kc.get(f"/api/kitchen?station={env.kitchen.id}").json()
    assert len(kitchen_list) == 1 and kitchen_list[0]["lines"][0]["name"] == "Köfte"
    assert kitchen_list[0]["lines"][0]["options"] == ["Az pişmiş"]
    assert kc.get(f"/api/kitchen?station={env.bar.id}").json()[0]["lines"][0]["name"] == "Ayran"
    # Tek istasyon hazır: parti henüz hazır değil, bildirim yok
    kc.post(f"/api/kitchen/{kitchen_list[0]['id']}/ready")
    assert Ticket.objects.get(pk=tid).batches.first().status == "pending"
    assert not Notification.objects.filter(user=env.waiter, event="order_ready").exists()
    bar_order = orders.get(station=env.bar)
    kc.post(f"/api/kitchen/{bar_order.id}/ready")
    batch = Ticket.objects.get(pk=tid).batches.first()
    assert batch.status == "ready"
    n = Notification.objects.get(user=env.waiter, event="order_ready")
    assert n.priority == "high" and n.data["ticket"] == tid
    # Masa kartında hazır işareti + hazır siparişler ekranı + teslim alma
    floor = c.get("/api/floor").json()
    card = next(x for x in floor["tables"] if x["id"] == env.tables[0].id)
    assert card["ticket"]["ready"] == 1
    ready = c.get("/api/ready-orders").json()
    assert ready[0]["batch" if "batch" in ready[0] else "id"] == batch.id
    assert c.post("/api/ready-orders", {"batch": batch.id}, format="json").status_code == 200
    assert Ticket.objects.get(pk=tid).batches.first().status == "picked_up"


def test_kds_station_staff_vs_manager_view(api, env):
    c, t = _open(api, env)
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="x")
    assert api(env.cook).get("/api/kitchen").json() == []  # istasyon seçmeden personel görmez
    assert len(api(env.manager).get("/api/kitchen").json()) == 1  # yönetici merkezi görünüm
    oid = api(env.manager).get("/api/kitchen").json()[0]["id"]
    assert api(env.cook).post(f"/api/kitchen/{oid}/priority", {"priority": 5}, format="json").status_code == 403
    assert api(env.manager).post(f"/api/kitchen/{oid}/priority", {"priority": 5}, format="json").status_code == 200


def test_table_move_and_merge(api, env):
    c, t = _open(api, env)
    mc = api(env.manager)
    r = mc.post(f"/api/tickets/{t['id']}/move", {"table": env.tables[1].id}, format="json")
    assert r.status_code == 200 and r.json()["table"] == env.tables[1].id
    _open(api, env, table=env.tables[2])
    r = mc.post(f"/api/tables/{env.tables[1].id}/merge", {"table": env.tables[2].id}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "ticket_merge_not_supported"
    assert mc.post(f"/api/tables/{env.tables[1].id}/merge", {"table": env.tables[3].id}, format="json").status_code == 200
    _, t3 = _open(api, env, table=env.tables[3])
    assert t3["id"] == t["id"]  # birleşik masa birincil masanın adisyonunu açar
    assert api(env.waiter).post(f"/api/tickets/{t['id']}/move", {"table": env.tables[4].id}, format="json").status_code == 403
