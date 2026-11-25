"""Masa durumu tutarlılığı: gerçekte işlem yoksa masa "dolu / işlemde" görünmemeli."""
import time
from datetime import timedelta
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.utils import timezone

from apps.core.models import IdempotencyRecord
from apps.pos import services
from apps.pos.models import ApprovalRequest, KitchenBatch, KitchenOrder, Table, Ticket, TicketLine


def _open(c, table):
    r = c.post(f"/api/tables/{table.id}/open", {}, format="json")
    assert r.status_code in (200, 201), r.content
    return r.json()


def _add(c, tid, product, **extra):
    r = c.post(f"/api/tickets/{tid}/add_line", {"product": product.id, **extra}, format="json")
    assert r.status_code in (200, 201), r.content
    return r.json()


def _send(c, tid, key):
    r = c.post(f"/api/tickets/{tid}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert r.status_code == 200, r.content
    return r.json()


def _table(c, table):
    data = c.get("/api/floor").json()
    return next(t for t in data["tables"] if t["id"] == table.id)


# ------------------------------------------------------------------ boş adisyon
def test_tapping_a_table_without_ordering_keeps_it_empty(api, env):
    c = api(env.waiter)
    _open(c, env.tables[0])
    assert _table(c, env.tables[0])["status"] == "empty"
    assert c.get("/api/floor").json()["summary"]["occupied"] == 0
    cards = api(env.owner).get("/api/dashboard").json()["cards"]
    assert cards["open_tickets"]["value"] == 0
    assert cards["active_tables"]["value"] == 0


def test_deleting_the_last_draft_frees_the_table(api, env):
    c = api(env.waiter)
    t = _open(c, env.tables[0])
    line = _add(c, t["id"], env.ayran)["lines"][0]
    assert _table(c, env.tables[0])["status"] == "waiting"
    c.post(f"/api/tickets/{t['id']}/delete_line", {"line": line["id"]}, format="json")
    assert _table(c, env.tables[0])["status"] == "empty"


def test_leftover_empty_ticket_starts_fresh_on_first_order(api, env):
    c = api(env.waiter)
    t = _open(c, env.tables[0])
    old = timezone.now() - timedelta(days=2)
    Ticket.objects.filter(pk=t["id"]).update(opened_at=old, business_date=timezone.localdate() - timedelta(days=2))
    c2 = api(env.waiter2)
    assert _open(c2, env.tables[0])["id"] == t["id"]
    _add(c2, t["id"], env.ayran)
    ticket = Ticket.objects.get(pk=t["id"])
    assert ticket.waiter_id == env.waiter2.id
    assert ticket.business_date == timezone.localdate()
    assert _table(c2, env.tables[0])["ticket"]["minutes"] == 0


def test_empty_takeaway_is_hidden_and_reused(api, env):
    c = api(env.cashier)
    a = c.post("/api/tickets", {"channel": "takeaway"}, format="json").json()
    assert c.get("/api/floor").json()["other_tickets"] == []
    b = c.post("/api/tickets", {"channel": "takeaway"}, format="json").json()
    assert a["id"] == b["id"]


def test_empty_ticket_never_blocks_move_or_merge(api, env):
    c = api(env.manager)
    t = _open(c, env.tables[0])
    _add(c, t["id"], env.ayran)
    _open(c, env.tables[1])
    _open(c, env.tables[2])
    r = c.post(f"/api/tickets/{t['id']}/move", {"table": env.tables[1].id}, format="json")
    assert r.status_code == 200, r.content
    r = c.post(f"/api/tables/{env.tables[1].id}/merge", {"table": env.tables[2].id}, format="json")
    assert r.status_code == 200, r.content


def test_empty_ticket_never_blocks_seating_a_reservation(api, env):
    from apps.modules.models import Reservation

    c = api(env.manager)
    _open(c, env.tables[0])
    res = Reservation.objects.create(business=env.biz, branch=env.branch, name="Ali", phone="5", party_size=2,
                                     table=env.tables[0], starts_at=timezone.now())
    r = c.post(f"/api/reservations/{res.id}/seat", {}, format="json")
    assert r.status_code in (200, 201), r.content
    assert _table(c, env.tables[0])["status"] == "occupied"  # misafir oturdu: dolu


def test_closing_a_seated_reservation_completes_it(api, env):
    from apps.modules.models import Reservation
    from apps.modules.services import seat_reservation

    res = Reservation.objects.create(business=env.biz, branch=env.branch, name="Ali", phone="5", party_size=2,
                                     table=env.tables[0], starts_at=timezone.now())
    ticket = seat_reservation(res, user=env.manager)
    services.cancel_empty_ticket(ticket, user=env.manager)
    res.refresh_from_db()
    assert res.status == "completed"


def test_bill_cannot_be_requested_for_an_empty_ticket(api, env):
    c = api(env.waiter)
    t = _open(c, env.tables[0])
    r = c.post(f"/api/tickets/{t['id']}/request_bill", {}, format="json")
    assert r.status_code == 400
    assert _table(c, env.tables[0])["status"] == "empty"


# ------------------------------------------------------------------ mutfak partileri
def _food_and_drink(api, env):
    c = api(env.manager)
    t = _open(c, env.tables[0])
    _add(c, t["id"], env.tatli)
    _add(c, t["id"], env.ayran)
    _send(c, t["id"], "k-food")
    batch = KitchenBatch.objects.get(ticket_id=t["id"])
    return c, t, batch


def test_voiding_the_unready_station_makes_batch_ready(api, env):
    c, t, batch = _food_and_drink(api, env)
    bar = KitchenOrder.objects.get(batch=batch, station=env.bar)
    c.post(f"/api/kitchen/{bar.id}/ready", {}, format="json")
    food = TicketLine.objects.get(ticket_id=t["id"], product=env.tatli)
    r = c.post(f"/api/tickets/{t['id']}/void_line", {"line": food.id, "reason": "vazgeçti"}, format="json")
    assert r.status_code == 200, r.content
    batch.refresh_from_db()
    assert batch.status == "ready"
    assert _table(c, env.tables[0])["status"] == "occupied"


def test_voiding_everything_in_a_ready_batch_clears_ready_flag(api, env):
    c, t, batch = _food_and_drink(api, env)
    c.post(f"/api/kitchen/{batch.orders.first().id}/ready_all", {}, format="json")
    for ln in TicketLine.objects.filter(ticket_id=t["id"], status="sent"):
        c.post(f"/api/tickets/{t['id']}/void_line", {"line": ln.id, "reason": "vazgeçti"}, format="json")
    assert c.get("/api/ready-orders").json() == []
    assert _table(c, env.tables[0])["ticket"]["ready"] == 0


def test_manual_close_clears_waiting_pickups_and_approvals(api, env):
    env.branch.settings.auto_close_on_payment = False
    env.branch.settings.save()
    c, t, batch = _food_and_drink(api, env)
    c.post(f"/api/kitchen/{batch.orders.first().id}/ready_all", {}, format="json")
    ticket = Ticket.objects.get(pk=t["id"])
    approval = ApprovalRequest.objects.create(
        business=env.biz, branch=env.branch, ticket=ticket, kind="discount", payload={"kind": "percent", "value": "5"},
        reason="deneme", required_perm="ticket.discount", requested_by=env.waiter)
    cashier = api(env.cashier)
    assert cashier.post("/api/cash", {"action": "open", "opening_balance": 0}, format="json").status_code < 300
    r = cashier.post(f"/api/tickets/{t['id']}/pay", {"method": "card"}, format="json", HTTP_IDEMPOTENCY_KEY="pay-1")
    assert r.status_code == 201, r.content
    assert cashier.post(f"/api/tickets/{t['id']}/close", {}, format="json").status_code == 200
    assert c.get("/api/ready-orders").json() == []
    approval.refresh_from_db()
    assert approval.status == "rejected"


def test_fully_discounted_ticket_can_be_closed(api, env):
    env.branch.settings.max_discount_percent = 100
    env.branch.settings.save()
    c, t, _ = _food_and_drink(api, env)
    r = c.post(f"/api/tickets/{t['id']}/discount", {"kind": "percent", "value": 100, "reason": "ikram"}, format="json")
    assert r.status_code == 200, r.content
    assert c.post(f"/api/tickets/{t['id']}/close", {}, format="json").status_code == 200
    assert _table(c, env.tables[0])["status"] == "empty"


# ------------------------------------------------------------------ eski nesne / eşzamanlı işlem
def test_stale_draft_edit_cannot_undo_a_kitchen_send(api, env):
    c = api(env.waiter)
    t = _open(c, env.tables[0])
    _add(c, t["id"], env.ayran)
    stale = TicketLine.objects.select_related("ticket").get(ticket_id=t["id"])
    _send(c, t["id"], "k-stale")
    for attempt in (lambda: services.update_line(stale, user=env.waiter, qty=5),
                    lambda: services.delete_draft_line(stale, user=env.waiter)):
        try:
            attempt()
        except Exception:
            pass
    line = TicketLine.objects.get(ticket_id=t["id"])
    assert line.status == "sent" and line.qty == Decimal("1")


def test_stale_bill_request_cannot_reopen_a_closed_ticket(api, env):
    c, t, _ = _food_and_drink(api, env)
    stale = Ticket.objects.get(pk=t["id"])
    Ticket.objects.filter(pk=t["id"]).update(status="closed")
    try:
        services.request_bill(stale, user=env.waiter)
    except Exception:
        pass
    assert Ticket.objects.get(pk=t["id"]).status == "closed"


# ------------------------------------------------------------------ masa yönetimi
def test_merging_a_primary_into_its_own_child_is_rejected(api, env):
    c = api(env.manager)
    a, b = env.tables[0], env.tables[1]
    assert c.post(f"/api/tables/{a.id}/merge", {"table": b.id}, format="json").status_code == 200
    r = c.post(f"/api/tables/{b.id}/merge", {"table": a.id}, format="json")
    assert r.status_code == 400
    assert Table.objects.get(pk=a.id).merged_into_id is None


def test_table_with_live_ticket_cannot_be_removed(api, env):
    c = api(env.manager)
    t = _open(c, env.tables[0])
    _add(c, t["id"], env.ayran)
    assert c.delete(f"/api/tables/{env.tables[0].id}").status_code == 400
    assert Table.objects.get(pk=env.tables[0].id).is_active
    assert c.delete(f"/api/halls/{env.hall.id}").status_code == 400
    _open(c, env.tables[1])  # yalnızca boş adisyon: silinebilir
    assert c.delete(f"/api/tables/{env.tables[1].id}").status_code == 204


# ------------------------------------------------------------------ takılı kalan istek ve canlı yayın
def test_abandoned_in_progress_request_can_be_retried(api, env):
    c = api(env.waiter)
    t = _open(c, env.tables[0])
    _add(c, t["id"], env.ayran)
    rec = IdempotencyRecord.objects.create(business=env.biz, key="dead", scope=f"ticket.send:{t['id']}",
                                           user=env.waiter, status_code=0)

    def send():
        return c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="dead")

    r = send()
    assert r.status_code == 409 and r.json()["code"] == "in_progress"  # henüz taze: bekle
    IdempotencyRecord.objects.filter(pk=rec.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    r = send()
    assert r.status_code == 200, r.content


def test_heartbeat_keeps_long_lived_screens_subscribed():
    """Kanal katmanı grup üyeliğini 24 saat sonra düşürür; ping üyeliği yenilemeli."""
    from channels.layers import get_channel_layer

    from apps.core.consumers import BranchConsumer

    layer = get_channel_layer()

    async def run():
        consumer = BranchConsumer()
        consumer.channel_layer = layer
        consumer.channel_name = await layer.new_channel()
        consumer.groups_joined = ["b999"]
        sent = []

        async def send_json(payload, close=False):
            sent.append(payload)

        consumer.send_json = send_json
        await layer.group_add("b999", consumer.channel_name)
        layer.groups["b999"][consumer.channel_name] = time.time() - layer.group_expiry + 5
        await consumer.receive_json({"type": "ping"})
        stamp = layer.groups["b999"][consumer.channel_name]
        await layer.group_discard("b999", consumer.channel_name)
        return sent, stamp

    sent, stamp = async_to_sync(run)()
    assert sent == [{"event": "pong"}]
    assert time.time() - stamp < 5
