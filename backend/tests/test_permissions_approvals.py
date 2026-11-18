"""Kabul: Yetki — garson indirim/iptal yapamaz; onay ve gerekçe kaydı zorunlu (§2.1, §6.2, §21)."""
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied

from apps.core.models import AuditLog
from apps.pos.models import ApprovalRequest, Ticket


def _ticket_with_sent(api, env):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.tatli.id, "qty": 2}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY=f"s{t['id']}")
    return c, Ticket.objects.get(pk=t["id"])


def test_waiter_cannot_discount_or_void(api, env):
    c, t = _ticket_with_sent(api, env)
    r = c.post(f"/api/tickets/{t.id}/discount", {"kind": "percent", "value": 10, "reason": "Müşteri memnuniyeti"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "approval_required"
    line = t.lines.first()
    r = c.post(f"/api/tickets/{t.id}/void_line", {"line": line.id, "reason": "Yanlış sipariş"}, format="json")
    assert r.status_code == 403
    t.refresh_from_db()
    assert t.discount_total == 0 and t.lines.filter(status="void").count() == 0


def test_reason_is_mandatory(api, env):
    _, t = _ticket_with_sent(api, env)
    r = api(env.manager).post(f"/api/tickets/{t.id}/discount", {"kind": "percent", "value": 10, "reason": ""}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "reason_required"


def test_approval_request_flow(api, env):
    c, t = _ticket_with_sent(api, env)
    r = c.post(f"/api/tickets/{t.id}/discount", {"kind": "percent", "value": 10, "reason": "Doğum günü",
                                                 "request_approval": True}, format="json")
    assert r.status_code == 202
    req_id = r.json()["approval"]["id"]
    # Garson kendi talebini onaylayamaz / yetkisi yok
    assert c.post(f"/api/approvals/{req_id}/approve").status_code in (403, 404)
    m = api(env.manager)
    assert m.post(f"/api/approvals/{req_id}/approve", {"note": "ok"}, format="json").status_code == 200
    t.refresh_from_db()
    assert t.discount_total == Decimal("18.00") and t.total == Decimal("162.00")
    d = t.discounts.get()
    assert d.created_by == env.waiter and d.approved_by == env.manager and d.reason == "Doğum günü"
    log = AuditLog.objects.get(action="ticket.discount")
    assert log.before["total"] == "180.00" and log.after["total"] == "162.00" and log.reason == "Doğum günü"


def test_void_with_manager_pin_and_kitchen_notice(api, env):
    c, t = _ticket_with_sent(api, env)
    line = t.lines.first()
    r = c.post(f"/api/tickets/{t.id}/void_line", {"line": line.id, "qty": 1, "reason": "Müşteri vazgeçti",
                                                  "approver": {"user_id": env.manager.id, "pin": "0000"}}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "approver_invalid"
    r = c.post(f"/api/tickets/{t.id}/void_line", {"line": line.id, "qty": 1, "reason": "Müşteri vazgeçti",
                                                  "approver": {"user_id": env.cashier.id, "pin": "7777"}}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "approver_forbidden"
    r = c.post(f"/api/tickets/{t.id}/void_line", {"line": line.id, "qty": 1, "reason": "Müşteri vazgeçti",
                                                  "approver": {"user_id": env.manager.id, "pin": "8888"}}, format="json")
    assert r.status_code == 200
    t.refresh_from_db()
    assert t.total == Decimal("90.00")
    void = t.lines.get(status="void")
    assert void.qty == 1 and void.voided_by == env.manager and void.void_reason == "Müşteri vazgeçti"
    assert t.lines.get(status="sent").qty == 1
    from apps.core.models import Notification

    assert Notification.objects.filter(user=env.cook, event="kitchen_void").exists()
    # Mutfak ekranında iptal görünür
    k = api(env.cook).get(f"/api/kitchen?station={env.kitchen.id}").json()[0]
    assert any(ln["void"] for ln in k["lines"])


def test_municipal_group_flow(api, env):
    c, t = _ticket_with_sent(api, env)
    r = c.post(f"/api/tickets/{t.id}/customer_group", {"group": env.belediye.id}, format="json")
    assert r.status_code == 202
    req = ApprovalRequest.objects.get(kind="group")
    assert req.required_perm == "approvals.municipal"
    # Kasiyer onayı (yönetici onayı gerekmez)
    assert api(env.cashier).post(f"/api/approvals/{req.id}/approve").status_code == 200
    t.refresh_from_db()
    assert t.customer_group == env.belediye and t.discount_total == Decimal("36.00")
    # Red akışı
    c2 = api(env.waiter2)
    t2 = c2.post(f"/api/tables/{env.tables[1].id}/open", {}, format="json").json()
    c2.post(f"/api/tickets/{t2['id']}/add_line", {"product": env.tatli.id}, format="json")
    c2.post(f"/api/tickets/{t2['id']}/customer_group", {"group": env.belediye.id}, format="json")
    req2 = ApprovalRequest.objects.filter(kind="group", status="pending").get()
    assert api(env.cashier).post(f"/api/approvals/{req2.id}/reject", {"note": "kimlik yok"}, format="json").status_code == 200
    assert Ticket.objects.get(pk=t2["id"]).discount_total == 0


def test_discount_limit(api, env):
    _, t = _ticket_with_sent(api, env)
    s = env.branch.settings
    s.max_discount_percent = 15
    s.save()
    r = api(env.manager).post(f"/api/tickets/{t.id}/discount", {"kind": "percent", "value": 20, "reason": "deneme"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "discount_limit"


def test_audit_log_is_immutable(env):
    log = AuditLog.objects.create(action="x.test")
    log.reason = "değiştir"
    with pytest.raises(PermissionDenied):
        log.save()
    with pytest.raises(PermissionDenied):
        log.delete()


def test_waiter_cannot_take_payment_or_manage_cash(api, env, open_cash):
    _, t = _ticket_with_sent(api, env)
    c = api(env.waiter)
    assert c.post(f"/api/tickets/{t.id}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="p").status_code == 403
    assert c.get("/api/cash").status_code == 403
    assert c.post("/api/products", {"name": "x", "category": env.food.id, "base_price": 1}, format="json").status_code == 403
