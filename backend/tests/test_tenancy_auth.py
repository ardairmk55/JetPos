"""NFR-03 tenant/şube izolasyonu; §15.1 kimlik doğrulama, PIN, kilit; NFR-02 offline idempotency."""
import time

from apps.catalog.models import Category
from apps.core import roles
from apps.core.models import LoginAttempt
from apps.pos.models import Ticket, TicketLine

from .conftest import make_business, make_user


def test_tenant_isolation(api, env):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    biz2, br2 = make_business("Başka İşletme", "baska", code="B2")
    other_owner = make_user(biz2, None, "baskasahip", roles.OWNER)
    o = api(other_owner)
    assert o.get(f"/api/tickets/{t['id']}").status_code == 404
    assert o.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json").status_code == 404
    assert o.get("/api/products").json() == []
    assert o.get("/api/users").json() == [] or all(u["username"] != "garson" for u in o.get("/api/users").json())
    # Başka işletmenin kategorisiyle ürün oluşturulamaz
    cat2 = Category.objects.create(business=biz2, name="Diğer")
    r = api(env.manager).post("/api/products", {"name": "Hile", "category": cat2.id, "base_price": 10}, format="json")
    assert r.status_code == 400
    # Başka işletmenin ürünü adisyona eklenemez
    from apps.catalog.models import Product

    p2 = Product.objects.create(business=biz2, category=cat2, name="Yabancı", base_price=1)
    r = c.post(f"/api/tickets/{t['id']}/add_line", {"product": p2.id}, format="json")
    assert r.status_code == 400


def test_branch_scope(api, env):
    from apps.core.models import Branch, BranchSettings
    from apps.pos.models import Hall, Table

    b2 = Branch.objects.create(business=env.biz, name="Şube 2", code="S2")
    BranchSettings.objects.create(branch=b2)
    h2 = Hall.objects.create(business=env.biz, branch=b2, name="Salon")
    t2 = Table.objects.create(business=env.biz, branch=b2, hall=h2, name="A1")
    # Şube yöneticisi yalnızca atanmış şubeyi görür; başlıkla başka şubeye geçemez
    m = api(env.manager)
    assert all(x["id"] != t2.id for x in m.get("/api/floor", HTTP_X_BRANCH=str(b2.id)).json()["tables"])
    assert m.post(f"/api/tables/{t2.id}/open", {}, format="json").status_code == 404
    # İşletme sahibi şube seçebilir
    o = api(env.owner)
    assert any(x["id"] == t2.id for x in o.get("/api/floor", HTTP_X_BRANCH=str(b2.id)).json()["tables"])


def test_login_lockout_and_attempt_log(api, env):
    c = api()
    for _ in range(5):
        r = c.post("/api/auth/login", {"username": "garson", "password": "yanlis"}, format="json")
        assert r.status_code == 401
    r = c.post("/api/auth/login", {"username": "garson", "password": "Test-Pass-2026!"}, format="json")
    assert r.status_code == 423
    assert LoginAttempt.objects.filter(username="garson", success=False).count() == 5
    env.waiter.refresh_from_db()
    env.waiter.locked_until = None
    env.waiter.failed_attempts = 0
    env.waiter.save()
    assert c.post("/api/auth/login", {"username": "garson", "password": "Test-Pass-2026!"}, format="json").status_code == 200
    me = c.get("/api/auth/me").json()
    assert me["role"] == "waiter" and "ticket.discount" not in me["permissions"]


def test_pin_switch_and_lock(api, env):
    c = api()
    c.post("/api/auth/login", {"username": "kasiyer", "password": "Test-Pass-2026!"}, format="json")
    users = c.get("/api/auth/pin-users").json()
    assert any(u["id"] == env.waiter.id for u in users)
    assert c.post("/api/auth/pin-switch", {"user_id": env.waiter.id, "pin": "0000"}, format="json").status_code == 401
    r = c.post("/api/auth/pin-switch", {"user_id": env.waiter.id, "pin": "1111"}, format="json")
    assert r.status_code == 200 and c.get("/api/auth/me").json()["username"] == "garson"
    c.post("/api/auth/lock")
    assert c.get("/api/floor").status_code == 423
    assert c.post("/api/auth/unlock", {"pin": "9"}, format="json").status_code == 401
    assert c.post("/api/auth/unlock", {"pin": "1111"}, format="json").status_code == 200
    assert c.get("/api/floor").status_code == 200


def test_inactivity_auto_lock(api, env):
    c = api()
    c.post("/api/auth/login", {"username": "garson", "password": "Test-Pass-2026!"}, format="json")
    s = c.session
    s["last_activity"] = time.time() - 6 * 60
    s.save()
    r = c.get("/api/floor")
    assert r.status_code == 423 and r.json()["code"] == "locked"


def test_deactivated_user_cannot_login(api, env):
    m = api(env.manager)
    assert m.post(f"/api/users/{env.waiter2.id}/deactivate", {"reason": "işten ayrıldı"}, format="json").status_code == 200
    r = api().post("/api/auth/login", {"username": "garson2", "password": "Test-Pass-2026!"}, format="json")
    assert r.status_code == 401
    # Şube yöneticisi sahip rolü atayamaz
    r = m.post("/api/users", {"username": "yeni", "password": "Guclu-Sifre-99", "role": "owner"}, format="json")
    assert r.status_code == 400


def test_offline_queue_replay_is_idempotent(api, env):
    """Garson PWA offline kuyruğu aynı işlemi tekrar gönderdiğinde çift kayıt oluşmaz."""
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    for _ in range(3):
        c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id, "client_uid": "dev1-abc"}, format="json")
    assert TicketLine.objects.filter(ticket_id=t["id"]).count() == 1
    for _ in range(3):
        r = c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="dev1-send-1",
                   HTTP_X_DEVICE="garson-tel-1")
        assert r.status_code == 200
    assert Ticket.objects.get(pk=t["id"]).batches.count() == 1
    from apps.core.models import IdempotencyRecord

    rec = IdempotencyRecord.objects.get(key="dev1-send-1")
    assert rec.device == "garson-tel-1" and rec.user == env.waiter
