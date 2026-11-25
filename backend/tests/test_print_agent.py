"""Yazıcı köprüsü: bulut sunucudaki işleri restorandaki bilgisayar çeker ve basar."""
import base64
import os
import socket
import subprocess
import sys
import threading
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.printing import escpos, services
from apps.printing.models import PrintAgent, Printer, PrintJob

from .conftest import make_business


@pytest.fixture
def printer(env):
    return Printer.objects.create(business=env.biz, branch=env.branch, name="Kasa", connection="windows",
                                  address="POS80", target="cashier", via_agent=True)


@pytest.fixture
def token(env, api):
    r = api(env.owner).post("/api/printers/agent-token")
    assert r.status_code == 200, r.content
    return r.data["token"]


def agent_post(api, token, path, data=None):
    return api().post(f"/api/print-agent/{path}", data or {}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")


def test_server_never_prints_agent_jobs_itself(env, printer, api):
    r = api(env.owner).post(f"/api/printers/{printer.id}/test")
    assert r.status_code == 200
    assert r.data["status"] == "queued"
    assert r.data["last_error"] == ""
    services.retry_pending()
    job = PrintJob.objects.get(pk=r.data["id"])
    assert (job.status, job.attempts) == ("queued", 0)


def test_agent_claims_job_and_reports_success(env, printer, token, api):
    job = services.enqueue_test(printer)
    r = agent_post(api, token, "claim")
    assert r.status_code == 200, r.content
    got = r.data["job"]
    assert (got["id"], got["connection"], got["address"], got["port"]) == (job.id, "windows", "POS80", 9100)
    assert base64.b64decode(got["data"]).startswith(b"\x1b@")
    assert agent_post(api, token, "claim").data["job"] is None  # aynı iş iki kez verilmez
    assert agent_post(api, token, "result", {"job": job.id, "ok": True}).status_code == 200
    job.refresh_from_db()
    assert job.status == "done" and job.printed_on_id == printer.id
    printer.refresh_from_db()
    assert printer.last_ok_at is not None


def test_agent_failure_waits_then_retries_then_fails(env, printer, token, api):
    job = services.enqueue_test(printer)
    for attempt in range(1, services.MAX_ATTEMPTS + 1):
        assert agent_post(api, token, "claim").data["job"]["id"] == job.id
        agent_post(api, token, "result", {"job": job.id, "ok": False, "error": "Yazıcı kapalı"})
        assert agent_post(api, token, "claim").data["job"] is None  # hemen tekrar denenmez
        PrintJob.objects.filter(pk=job.pk).update(started_at=timezone.now() - timedelta(minutes=1))
        job.refresh_from_db()
        assert job.attempts == attempt
    assert job.status == "failed" and job.last_error == "Yazıcı kapalı"


def test_old_queued_jobs_are_not_printed_hours_later(env, printer, token, api):
    job = services.enqueue_test(printer)
    old = timezone.now() - services.AGENT_JOB_TTL - timedelta(minutes=1)
    PrintJob.objects.filter(pk=job.pk).update(created_at=old, queued_at=old)
    assert agent_post(api, token, "claim").data["job"] is None
    job.refresh_from_db()
    assert job.status == "failed"
    # Elle "tekrar dene" süreyi yeniler
    assert api(env.owner).post(f"/api/print-jobs/{job.id}/retry").status_code == 200
    assert agent_post(api, token, "claim").data["job"]["id"] == job.id


def test_freshly_claimed_old_job_is_not_requeued_by_scheduler(env, printer, token, api):
    job = services.enqueue_test(printer)
    PrintJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    assert agent_post(api, token, "claim").data["job"]["id"] == job.id
    services.retry_pending()
    job.refresh_from_db()
    assert job.status == "printing"  # yoksa aynı fiş iki kez basılır
    PrintJob.objects.filter(pk=job.pk).update(started_at=timezone.now() - timedelta(minutes=3))
    services.retry_pending()
    job.refresh_from_db()
    assert job.status == "queued"


def test_agent_sees_only_its_own_branch(env, printer, token, api):
    biz, branch = make_business("Diğer", "diger", "DGR")
    other = Printer.objects.create(business=biz, branch=branch, name="Y", connection="network", address="10.0.0.9",
                                   via_agent=True)
    foreign = services.enqueue_test(other)
    assert agent_post(api, token, "claim").data["job"] is None
    assert agent_post(api, token, "result", {"job": foreign.id, "ok": True}).status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == "queued"


def test_agent_does_not_get_non_agent_jobs(env, token, api):
    p = Printer.objects.create(business=env.biz, branch=env.branch, name="Sanal", connection="file")
    services.enqueue_test(p)
    assert agent_post(api, token, "claim").data["job"] is None


@pytest.mark.parametrize("header", [None, "Bearer ", "Bearer yanlis", "Basic abc"])
def test_agent_requires_valid_token(env, printer, token, api, header):
    services.enqueue_test(printer)
    kw = {"HTTP_AUTHORIZATION": header} if header else {}
    for path in ("claim", "result"):
        assert api().post(f"/api/print-agent/{path}", {}, format="json", **kw).status_code == 401
    # Oturum açmış kullanıcı da anahtar olmadan köprü gibi davranamaz
    assert api(env.owner).post("/api/print-agent/claim", {}, format="json").status_code == 401


def test_token_is_stored_hashed_and_rotation_revokes_old_one(env, token, api):
    assert PrintAgent.objects.get(branch=env.branch).token_hash != token
    new = api(env.owner).post("/api/printers/agent-token").data["token"]
    assert new != token
    assert agent_post(api, token, "claim").status_code == 401
    assert agent_post(api, new, "claim").status_code == 200


def test_only_printer_managers_get_token_and_script(env, api):
    for user in (env.waiter, env.cashier, env.cook):
        c = api(user)
        assert c.post("/api/printers/agent-token").status_code == 403
        assert c.get("/api/printers/agent-script").status_code == 403


def test_agent_status_and_script_download(env, token, api):
    c = api(env.owner)
    assert c.get("/api/printers/agent-status").data == {"configured": True, "online": False, "last_seen_at": None}
    agent_post(api, token, "claim")
    assert c.get("/api/printers/agent-status").data["online"] is True
    r = c.get("/api/printers/agent-script")
    assert r.status_code == 200
    assert r["Content-Disposition"] == 'attachment; filename="POSHANE-Yazici-Koprusu.cmd"'
    body = r.content
    assert b"http://testserver" in body and b"__SERVER_URL__" not in body
    assert not body.startswith(b"\xef\xbb\xbf")  # BOM cmd'nin ilk satırını bozar
    assert body.count(b"\r\n") == body.count(b"\n")
    assert token.encode() not in body


def test_via_agent_validation(env, printer, api):
    c = api(env.owner)
    r = c.post("/api/printers", {"name": "S", "connection": "file", "via_agent": True}, format="json")
    assert r.status_code == 400
    local = Printer.objects.create(business=env.biz, branch=env.branch, name="Yerel", connection="file")
    r = c.patch(f"/api/printers/{printer.id}", {"backup": local.id}, format="json")
    assert r.status_code == 400


@pytest.mark.skipif(sys.platform != "win32", reason="Köprü yalnızca Windows'ta çalışır")
def test_downloaded_bridge_really_prints_over_tcp(env, token, api, live_server, tmp_path):
    """İndirilen .cmd gerçekten çalışır: sunucudan işi çeker, sahte 9100 yazıcıya yollar, sonucu bildirir."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(60)
    received = bytearray()

    def fake_printer():
        conn, _ = listener.accept()
        with conn:
            while chunk := conn.recv(4096):
                received.extend(chunk)

    thread = threading.Thread(target=fake_printer, daemon=True)
    thread.start()

    ok = Printer.objects.create(business=env.biz, branch=env.branch, name="Mutfak Şöğüt", connection="network",
                                address="127.0.0.1", port=listener.getsockname()[1], via_agent=True)
    missing = Printer.objects.create(business=env.biz, branch=env.branch, name="Kasa", connection="windows",
                                     address="Olmayan Yazıcı Ş", via_agent=True)
    good, bad = services.enqueue_test(ok), services.enqueue_test(missing)

    script = tmp_path / "kopru.cmd"
    body = api(env.owner).get("/api/printers/agent-script").content
    script.write_bytes(body.replace(b"http://testserver", live_server.url.encode()))
    run = subprocess.run(["cmd", "/c", str(script)], stdin=subprocess.DEVNULL, capture_output=True, timeout=90,
                         env={**os.environ, "POSHANE_AGENT_HOME": str(tmp_path / "home"),
                              "POSHANE_AGENT_TOKEN": token, "POSHANE_AGENT_ONCE": "1"})
    output = run.stdout.decode("utf-8", "replace") + run.stderr.decode("utf-8", "replace")
    thread.join(10)
    listener.close()

    good.refresh_from_db()
    bad.refresh_from_db()
    assert good.status == "done", output
    assert bytes(received) == escpos.render(good.content, columns=48, codepage="cp857", codepage_id=13, cut=True)
    assert bad.status == "queued" and "Olmayan Yazıcı Ş" in bad.last_error, output


@pytest.mark.skipif(sys.platform != "win32", reason="Köprü yalnızca Windows'ta çalışır")
def test_downloaded_bridge_asks_key_once_and_stores_it_encrypted(token, env, api, live_server, tmp_path):
    script = tmp_path / "kopru.cmd"
    body = api(env.owner).get("/api/printers/agent-script").content
    script.write_bytes(body.replace(b"http://testserver", live_server.url.encode()))
    environ = {**os.environ, "POSHANE_AGENT_HOME": str(tmp_path / "home"), "POSHANE_AGENT_ONCE": "1"}
    environ.pop("POSHANE_AGENT_TOKEN", None)

    def run(typed):
        r = subprocess.run(["cmd", "/c", str(script)], input=typed.encode(), capture_output=True, timeout=90,
                           env=environ)
        return r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")

    first = run(f"yanlis-anahtar\r\n{token}\r\n\r\n")
    saved = (tmp_path / "home" / "anahtar.txt").read_text(encoding="utf-8-sig")
    assert "Anahtar yanlış" in first, first
    assert token not in saved and saved.strip()
    PrintAgent.objects.filter(branch=env.branch).update(last_seen_at=None)
    second = run("\r\n")
    assert "Köprü çalışıyor" in second and "Anahtar yanlış" not in second, second
    assert PrintAgent.objects.get(branch=env.branch).last_seen_at is not None
