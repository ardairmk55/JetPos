"""Raporlama/dışa aktarma/zamanlanmış gönderim, JET Menü entegrasyonu, kurulum sihirbazı, global arama, yazıcı kuyruğu."""
from decimal import Decimal

from django.core import mail

from apps.core.models import Business, User
from apps.integrations.models import IntegrationConfig, OutboxMessage, QrOrder
from apps.pos.models import Ticket
from apps.reports.services import REPORT_TYPES, run_due_schedules


def _sale(api, env, open_cash):
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.tatli.id, "qty": 2}, format="json")
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="s")
    api(env.cashier).post(f"/api/tickets/{t['id']}/pay", {"method": "cash"}, format="json", HTTP_IDEMPOTENCY_KEY="p")
    api(env.cashier).post(f"/api/tickets/{t['id']}/close")
    return t["id"]


def test_all_reports_and_exports(api, env, open_cash):
    _sale(api, env, open_cash)
    m = api(env.manager)
    for rtype in REPORT_TYPES:
        params = "&dimension=product&metric=revenue" if rtype == "custom" else ""
        r = m.get(f"/api/reports/run/{rtype}?compare=1{params}")
        assert r.status_code == 200, (rtype, r.content)
        assert "columns" in r.json()
    rep = m.get("/api/reports/run/sales").json()
    assert rep["totals"]["revenue"] == 210.0 and rep["totals"]["tickets"] == 1
    prods = m.get("/api/reports/run/products").json()
    assert prods["rows"][0][0] == "Sütlaç"
    for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
        r = m.get(f"/api/reports/run/products?export={fmt}")
        assert r.status_code == 200 and r.content.startswith(magic), fmt
    assert api(env.waiter).get("/api/reports/run/sales").status_code == 403
    d = m.get("/api/dashboard").json()
    assert d["cards"]["sales_today"]["value"] == 210.0
    assert "low_stock" not in api(env.waiter).get("/api/dashboard").json()["cards"]


def test_scheduled_report_delivery_and_retry(api, env, open_cash):
    m = api(env.manager)
    r = m.post("/api/reports/schedules", {"name": "Günlük satış", "report_type": "sales", "frequency": "daily",
                                          "send_time": "00:00", "recipients": ["rapor@example.com"], "fmt": "xlsx"},
               format="json")
    assert r.status_code == 201, r.content
    assert run_due_schedules() == 1
    assert len(mail.outbox) == 1 and mail.outbox[0].attachments[0][0].endswith(".xlsx")
    assert run_due_schedules() == 0  # aynı dönem tekrar gönderilmez
    bad = m.post("/api/reports/schedules", {"name": "Hatalı", "report_type": "nope", "recipients": ["a@b.co"]}, format="json")
    assert bad.status_code == 400


def test_custom_report_template_saved(api, env):
    m = api(env.manager)
    r = m.post("/api/reports/templates", {"name": "Saatlik ciro", "report_type": "custom",
                                          "params": {"dimension": "hour", "metric": "revenue"}}, format="json")
    assert r.status_code == 201
    assert m.get("/api/reports/templates").json()[0]["name"] == "Saatlik ciro"


def test_jetmenu_catalog_and_qr_order(api, env):
    cfg = IntegrationConfig.objects.create(business=env.biz, enabled=True, webhook_url="https://example.invalid/hook")
    c = api()
    assert c.get("/api/integrations/jetmenu/catalog?branch=MRK").status_code == 401
    cat = c.get("/api/integrations/jetmenu/catalog?branch=MRK", HTTP_X_INTEGRATION_TOKEN=cfg.inbound_token).json()
    assert any(p["name"] == "Köfte" and p["option_groups"] for p in cat["products"])
    body = {"external_id": "jm-1", "table_token": str(env.tables[0].qr_token),
            "items": [{"product_uid": str(env.ayran.uid), "qty": 2}]}
    r1 = c.post("/api/integrations/jetmenu/orders", body, format="json", HTTP_X_INTEGRATION_TOKEN=cfg.inbound_token)
    r2 = c.post("/api/integrations/jetmenu/orders", body, format="json", HTTP_X_INTEGRATION_TOKEN=cfg.inbound_token)
    assert r1.status_code == 201 and r2.json()["duplicate"] is True and QrOrder.objects.count() == 1
    w = api(env.waiter)
    pending = w.get("/api/qr-orders").json()
    assert pending[0]["status"] == "received"
    assert w.post("/api/qr-orders", {"id": pending[0]["id"], "action": "accept"}, format="json").status_code == 200
    t = Ticket.objects.get(table=env.tables[0], status="open")
    assert t.source == "pos" or t.source == "qr"
    assert t.lines.get().status == "draft"  # garson kontrol edip mutfağa gönderir
    # Katalog değişikliği kuyruğa girer; bağlantı yoksa kuyrukta bekler
    env.ayran.base_price = Decimal("35")
    env.ayran.save()
    assert OutboxMessage.objects.filter(kind="product.upsert", status="pending").exists()
    from apps.integrations.services import push_outbox

    def down(url, body, sig):
        raise OSError("offline")

    assert push_outbox(transport=down) == 0
    assert OutboxMessage.objects.filter(status="failed").exists()
    sent = []
    assert push_outbox(transport=lambda url, body, sig: sent.append(sig)) >= 1 and sent


def test_setup_wizard(api, db):
    c = api()
    assert c.get("/api/setup").json()["needed"] is True
    payload = {"business": {"name": "Deneme Kahvaltı", "template": "breakfast"}, "branch": {"name": "Merkez"},
               "owner": {"username": "patron", "password": "Kurulum-Sifre-42", "pin": "4321"},
               "taxes": [{"name": "KDV", "rate": "10"}],
               "halls": [{"name": "Salon", "tables": 4}], "users": [{"username": "g1", "role": "waiter", "pin": "1212", "password": "Garson-Sifre-42"}],
               "printers": [{"name": "Mutfak", "connection": "file", "target": "kitchen", "station": "Mutfak"}],
               "security": {"inactivity_lock_minutes": 3}, "backup": {"time": "02:30"}}
    r = c.post("/api/setup", payload, format="json")
    assert r.status_code == 201, r.content
    biz = Business.objects.get()
    assert biz.template == "breakfast" and biz.branches.first().tables.count() == 4
    assert User.objects.get(username="g1").role == "waiter"
    assert c.post("/api/setup", payload, format="json").status_code == 403  # ikinci kez kurulamaz
    assert c.post("/api/auth/login", {"username": "g1", "password": "Garson-Sifre-42"}, format="json").status_code == 200
    assert c.post("/api/auth/login", {"username": "patron", "password": "Kurulum-Sifre-42"}, format="json").status_code == 200


def test_setup_wizard_rejects_duplicate_usernames_without_500(api, db):
    c = api()
    c.raise_request_exception = False
    base = {"business": {"name": "Cift Ad"}, "branch": {"name": "Merkez"},
            "owner": {"username": "patron", "password": "Kurulum-Sifre-42"}}
    for users in ([{"username": "patron", "role": "waiter"}],
                  [{"username": "g1", "role": "waiter"}, {"username": "G1", "role": "cashier"}]):
        r = c.post("/api/setup", {**base, "users": users}, format="json")
        assert r.status_code == 400, (users, r.status_code, r.content)
        assert "kullanıcı adı" in r.json()["detail"]
    assert not Business.objects.exists() and not User.objects.exists()  # hiçbir şey yarım kalmaz


def test_global_search_respects_roles(api, env, open_cash):
    tid = _sale(api, env, open_cash)
    num = Ticket.objects.get(pk=tid).number
    m = api(env.manager).get(f"/api/search?q={num}").json()
    assert any(r["kind"] == "ticket" for r in m["results"])
    assert any(r["kind"] == "product" for r in api(env.manager).get("/api/search?q=Köf").json()["results"])
    k = api(env.cook).get("/api/search?q=Köf").json()
    assert k["results"] == []  # mutfak personeli ürün/ödeme aramaz
    assert any(r["kind"] == "staff" for r in api(env.manager).get("/api/search?q=garson").json()["results"])
    assert api(env.manager).get("/api/search?q=").json()["recent"]


def test_printer_queue_routing_retry_and_backup(api, env, tmp_path):
    from apps.printing import escpos, services
    from apps.printing.models import Printer, PrintJob

    backup_p = Printer.objects.create(business=env.biz, branch=env.branch, name="Yedek", connection="file",
                                      address=str(tmp_path / "yedek"))
    main = Printer.objects.create(business=env.biz, branch=env.branch, name="Mutfak", connection="network",
                                  address="127.0.0.1", port=1, backup=backup_p)
    main.stations.add(env.kitchen)
    bar = Printer.objects.create(business=env.biz, branch=env.branch, name="Bar", connection="file", address=str(tmp_path / "bar"))
    bar.stations.add(env.bar)
    c = api(env.waiter)
    t = c.post(f"/api/tables/{env.tables[0].id}/open", {}, format="json").json()
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.kofte.id, "options": [env.o_az.id]}, format="json")
    c.post(f"/api/tickets/{t['id']}/add_line", {"product": env.ayran.id, "note": "buzsuz"}, format="json")
    c.post(f"/api/tickets/{t['id']}/send", {"confirmed": True}, format="json", HTTP_IDEMPOTENCY_KEY="pp")
    jobs = PrintJob.objects.filter(kind="kitchen")
    assert {j.printer.name for j in jobs} == {"Mutfak", "Bar"}
    bar_job = jobs.get(printer=bar)
    services.process_job(bar_job)
    bar_job.refresh_from_db()
    assert bar_job.status == "done"
    data = next((tmp_path / "bar").iterdir()).read_bytes()
    assert "Ayran".encode("cp857") in data and "buzsuz".encode("cp857") in data
    main_job = jobs.get(printer=main)
    for _ in range(3):
        services.process_job(main_job)
    main_job.refresh_from_db()
    assert main_job.status == "queued" and "bağlanılamadı" in main_job.last_error
    services.process_job(main_job)
    main_job.refresh_from_db()
    assert main_job.status == "done" and main_job.printed_on == backup_p
    assert "ÇçĞğİıÖöŞşÜü".encode("cp857") in escpos.render([{"text": "ÇçĞğİıÖöŞşÜü"}])
    r = api(env.manager).post(f"/api/printers/{bar.id}/test")
    assert r.json()["status"] == "done" and "TEST" in r.json()["preview"]


def test_crm_kvkk_and_reservation_to_ticket(api, env):
    m = api(env.manager)
    cust = m.post("/api/customers", {"name": "Zeynep Kaya", "phone": "5321112233", "kvkk_consent": True}, format="json").json()
    assert cust["consent_at"]
    exp = m.get(f"/api/customers/{cust['id']}/kvkk_export").json()
    assert exp["customer"]["phone"] == "5321112233"
    from django.utils import timezone

    r = m.post("/api/reservations", {"name": "Zeynep", "phone": "5321112233", "party_size": 8,
                                     "starts_at": (timezone.now() + timezone.timedelta(minutes=30)).isoformat(),
                                     "table": env.tables[1].id}, format="json")
    assert r.status_code == 400  # kapasite (4 kişilik masa)
    r = m.post("/api/reservations", {"name": "Zeynep", "phone": "5321112233", "party_size": 3, "customer": cust["id"],
                                     "starts_at": (timezone.now() + timezone.timedelta(minutes=30)).isoformat(),
                                     "table": env.tables[1].id}, format="json")
    assert r.status_code == 201
    floor = m.get("/api/floor").json()
    assert next(x for x in floor["tables"] if x["id"] == env.tables[1].id)["status"] == "reserved"
    r2 = m.post("/api/reservations", {"name": "Çakışan", "phone": "1", "party_size": 2,
                                      "starts_at": (timezone.now() + timezone.timedelta(minutes=60)).isoformat(),
                                      "table": env.tables[1].id}, format="json")
    assert r2.status_code == 400
    s = m.post(f"/api/reservations/{r.json()['id']}/seat")
    assert s.status_code == 200
    t = Ticket.objects.get(pk=s.json()["ticket"])
    assert t.reservation_id == r.json()["id"] and t.guest_count == 3
    a = m.post(f"/api/customers/{cust['id']}/anonymize", {"reason": "Müşteri silme talebi"}, format="json").json()
    assert a["name"].startswith("Anonim") and a["phone"] == ""


def test_delivery_flow(api, env):
    m = api(env.manager)
    courier = m.post("/api/couriers", {"name": "Mehmet", "phone": "1"}, format="json").json()
    d = m.post("/api/deliveries", {"contact_name": "Ali", "phone": "555", "address": "Cadde 1", "fee": "15"}, format="json")
    assert d.status_code == 201
    d = d.json()
    assert Decimal(str(d["ticket_total"])) == Decimal("15.00")
    r = m.post(f"/api/deliveries/{d['id']}/status", {"status": "on_the_way"}, format="json")
    assert r.status_code == 400
    m.post(f"/api/deliveries/{d['id']}/status", {"status": "waiting_courier", "courier": courier["id"]}, format="json")
    m.post(f"/api/deliveries/{d['id']}/status", {"status": "on_the_way"}, format="json")
    r = m.post(f"/api/deliveries/{d['id']}/status", {"status": "delivered"}, format="json")
    assert r.json()["status"] == "delivered"


def test_staff_timeclock_and_finance(api, env):
    w = api(env.waiter)
    assert w.post("/api/staff/timeclock", {"action": "in"}, format="json").status_code == 200
    assert w.post("/api/staff/timeclock", {"action": "in"}, format="json").status_code == 400
    w.post("/api/staff/timeclock", {"action": "break"}, format="json")
    w.post("/api/staff/timeclock", {"action": "break"}, format="json")
    assert w.post("/api/staff/timeclock", {"action": "out"}, format="json").status_code == 200
    m = api(env.manager)
    assert len(m.get("/api/staff/attendance").json()) == 1
    acc = m.post("/api/finance/accounts", {"name": "Toptancı", "kind": "supplier"}, format="json").json()
    e = m.post("/api/finance/entries", {"kind": "payable", "amount": "1000", "date": "2026-11-18", "account": acc["id"]},
               format="json")
    assert e.status_code == 201
    m.post("/api/finance/entries", {"kind": "settle_payable", "amount": "400", "date": "2026-11-18", "account": acc["id"]}, format="json")
    bal = m.get(f"/api/finance/accounts/{acc['id']}").json()["balance"]
    assert bal["payable"] == "600.00"
    rev = m.post(f"/api/finance/entries/{e.json()['id']}/reverse", {"reason": "Yanlış kayıt"}, format="json")
    assert rev.status_code == 201
    assert m.get(f"/api/finance/accounts/{acc['id']}").json()["balance"]["payable"] == "-400.00"
    assert m.get("/api/finance/entries/profitability").status_code == 200


def test_qr_codes(api, env):
    from apps.integrations.models import IntegrationConfig
    from apps.licensing.models import LicenseRecord

    from .conftest import make_user
    from apps.core import roles

    r = api(env.manager).get(f"/api/tables/{env.tables[0].id}/qr")
    assert r.status_code == 200 and r["Content-Type"] == "image/png" and r.content[1:4] == b"PNG"
    assert api(env.waiter).get(f"/api/tables/{env.tables[0].id}/qr").status_code == 403
    IntegrationConfig.objects.create(business=env.biz, qr_url_template="https://menu.example/{branch}?t={token}")
    assert api(env.manager).get(f"/api/tables/{env.tables[0].id}/qr").status_code == 200
    admin = make_user(None, None, "lisansci", roles.LICENSE_ADMIN)
    rec = LicenseRecord.objects.filter(business=env.biz).first()
    r = api(admin).get(f"/api/platform/licenses/{rec.id}/qr")
    assert r.status_code == 200 and r.content[1:4] == b"PNG"
    assert api(env.owner).get(f"/api/platform/licenses/{rec.id}/qr").status_code == 403
