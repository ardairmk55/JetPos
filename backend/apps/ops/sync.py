"""Şube → merkez kontrollü senkronizasyon (§12, §14). İnternet gerektirir; kesintide kuyrukta bekler."""
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from apps.core.models import Business, CentralInbox, SyncEvent

BATCH = 200


def push_pending(transport=None):
    url = settings.JETPOS["CENTRAL_URL"]
    if not url and transport is None:
        return {"sent": 0, "skipped": "JETPOS_CENTRAL_URL tanımlı değil"}
    events = list(SyncEvent.objects.filter(status__in=("pending", "failed"), attempts__lt=20).order_by("created_at")[:BATCH])
    if not events:
        return {"sent": 0}
    payload = [{"event_id": str(e.event_id), "business": e.business.slug, "branch": e.branch.code if e.branch else "",
                "kind": e.kind, "payload": e.payload, "node_id": e.node_id, "created_at": e.created_at.isoformat()}
               for e in events]
    try:
        if transport:
            result = transport(payload)
        else:
            req = urllib.request.Request(url.rstrip("/") + "/api/central/ingest", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "X-Central-Token": settings.JETPOS["CENTRAL_TOKEN"]})
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        for ev in events:
            ev.attempts += 1
            ev.status = "failed"
            ev.last_error = str(e)[:500]
        SyncEvent.objects.bulk_update(events, ["attempts", "status", "last_error"])
        return {"sent": 0, "error": str(e)}
    accepted = set(result.get("accepted", []))
    now = timezone.now()
    for ev in events:
        if str(ev.event_id) in accepted:
            ev.status = "sent"
            ev.sent_at = now
        else:
            ev.attempts += 1
            ev.status = "failed"
            ev.last_error = "Merkez kabul etmedi"
    SyncEvent.objects.bulk_update(events, ["attempts", "status", "last_error", "sent_at"])
    return {"sent": len(accepted)}


def ingest(items):
    """Merkez tarafı: olay kimliğiyle idempotent kabul."""
    accepted = []
    for it in items:
        biz = Business.objects.filter(slug=it.get("business")).first()
        if not biz:
            continue
        try:
            CentralInbox.objects.get_or_create(event_id=it["event_id"], defaults={
                "business": biz, "branch_code": it.get("branch", ""), "kind": it["kind"], "payload": it["payload"]})
            accepted.append(it["event_id"])
        except IntegrityError:
            accepted.append(it["event_id"])
    return accepted
