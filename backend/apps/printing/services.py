"""Yazdırma kuyruğu: yönlendirme, tekrar deneme, yedek yazıcı ve hata takibi (§7.3)."""
import logging
import threading

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import roles
from apps.core.notify import notify

from . import escpos
from .models import Printer, PrintJob

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
SYNC_PRINT = {"enabled": True}  # testlerde kapatılabilir


def _money(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _header(printer, title, ticket):
    t = timezone.localtime()
    lines = []
    head = printer.header or ticket.branch.settings.receipt_header
    for h in (head or "").splitlines():
        lines.append({"text": h, "align": "center"})
    lines.append({"text": title, "align": "center", "bold": True, "size": "double"})
    where = f"Masa {ticket.table.name}" if ticket.table else ticket.get_channel_display()
    lines.append({"text": f"{where}  #{ticket.number}", "bold": True, "size": "tall"})
    lines.append({"text": f"{t:%d.%m.%Y %H:%M}  {ticket.waiter.get_full_name() or ticket.waiter.username if ticket.waiter else ''}"})
    lines.append({"rule": True})
    return lines


def _enqueue(printer, *, kind, title, content, ref=""):
    job = PrintJob.objects.create(business=printer.business, branch=printer.branch, printer=printer, kind=kind,
                                  title=title[:120], content=content, ref=str(ref)[:60])
    if SYNC_PRINT["enabled"]:
        transaction.on_commit(lambda: _process_async(job.id))
    return job


def _process_async(job_id):
    def run():
        try:
            process_job(PrintJob.objects.get(pk=job_id))
        except Exception as e:  # kuyrukta kalır, worker tekrar dener
            log.warning("print job %s: %s", job_id, e)
        finally:
            close_old_connections()

    threading.Thread(target=run, daemon=True).start()


def printers_for_lines(branch, lines):
    """Kategori/istasyon yönlendirmesi: satır → yazıcı eşlemesi."""
    result = {}
    printers = list(Printer.objects.filter(branch=branch, is_active=True).prefetch_related("stations", "categories"))
    for p in printers:
        st_ids = {s.id for s in p.stations.all()}
        cat_ids = {c.id for c in p.categories.all()}
        for ln in lines:
            if (ln.station_id and ln.station_id in st_ids) or (ln.product.category_id in cat_ids):
                result.setdefault(p, []).append(ln)
    return result


def _line_rows(ln, cols):
    rows = [{"text": f"{ln.qty.normalize()} x {ln.name}", "bold": True, "size": "tall"}]
    for o in ln.options:
        rows.append({"text": f"   + {o['name']}"})
    if ln.note:
        rows.append({"text": f"   NOT: {ln.note}", "bold": True})
    return rows


def enqueue_kitchen(batch):
    ticket = batch.ticket
    lines = list(batch.lines.select_related("product"))
    jobs = []
    for printer, plines in printers_for_lines(ticket.branch, lines).items():
        content = _header(printer, f"SİPARİŞ {batch.number}. PARTİ", ticket)
        for ln in plines:
            content += _line_rows(ln, printer.columns)
        jobs.append(_enqueue(printer, kind="kitchen", title=f"#{ticket.number} parti {batch.number}", content=content,
                             ref=f"batch:{batch.id}"))
    return jobs


def enqueue_void(void_line):
    ticket = void_line.ticket
    jobs = []
    for printer, plines in printers_for_lines(ticket.branch, [void_line]).items():
        content = _header(printer, "*** İPTAL ***", ticket)
        content += [{"text": f"{void_line.qty.normalize()} x {void_line.name}", "bold": True, "size": "double"},
                    {"text": f"Gerekçe: {void_line.void_reason}"}]
        jobs.append(_enqueue(printer, kind="void", title=f"İptal #{ticket.number}", content=content,
                             ref=f"line:{void_line.id}"))
    return jobs


def _bill_content(printer, ticket, title):
    content = _header(printer, title, ticket)
    for ln in ticket.lines.exclude(status="void"):
        content.append({"text": f"{ln.qty.normalize()} x {ln.name}"[: printer.columns - 12], "right": _money(ln.unit_price * ln.qty)})
        for o in ln.options:
            content.append({"text": f"   + {o['name']}"})
        if ln.campaign_discount:
            content.append({"text": f"   {ln.campaign_name}", "right": f"-{_money(ln.campaign_discount)}"})
    content.append({"rule": True})
    content.append({"text": "Ara toplam", "right": _money(ticket.subtotal)})
    if ticket.discount_total:
        content.append({"text": "İndirim", "right": f"-{_money(ticket.discount_total)}"})
    content.append({"text": "KDV", "right": _money(ticket.tax_total)})
    content.append({"text": "TOPLAM", "right": _money(ticket.total), "bold": True, "size": "tall"})
    for p in ticket.payments.all():
        content.append({"text": p.get_method_display(), "right": _money(p.amount)})
    if ticket.paid_total:
        content.append({"text": "Kalan", "right": _money(ticket.remaining)})
    footer = printer.footer or ticket.branch.settings.receipt_footer
    content.append({"rule": True})
    for f in (footer or "").splitlines():
        content.append({"text": f, "align": "center"})
    return content


def _receipt_printers(branch):
    return Printer.objects.filter(branch=branch, is_active=True).filter(Q(print_receipts=True) | Q(target="cashier"))


def enqueue_bill(ticket):
    return [_enqueue(p, kind="bill", title=f"Hesap #{ticket.number}", content=_bill_content(p, ticket, "HESAP"),
                     ref=f"ticket:{ticket.id}") for p in _receipt_printers(ticket.branch)]


def enqueue_receipt(ticket):
    return [_enqueue(p, kind="receipt", title=f"Fiş #{ticket.number}", content=_bill_content(p, ticket, "BİLGİ FİŞİ"),
                     ref=f"ticket:{ticket.id}") for p in _receipt_printers(ticket.branch)]


def enqueue_test(printer):
    content = [{"text": "JETPOS TEST BASKISI", "align": "center", "bold": True, "size": "double"},
               {"text": printer.name, "align": "center"},
               {"text": f"{timezone.localtime():%d.%m.%Y %H:%M:%S}", "align": "center"},
               {"rule": True},
               {"text": "Türkçe: ÇçĞğİıÖöŞşÜü"},
               {"text": "Fiyat", "right": "123,45 TL"},
               {"text": f"Genişlik: {printer.width_mm} mm / {printer.columns} sütun"}]
    return _enqueue(printer, kind="test", title="Test baskısı", content=content)


def process_job(job):
    with transaction.atomic():
        job = PrintJob.objects.select_for_update().get(pk=job.pk)
        if job.status in ("done", "printing"):
            return job
        job.status = "printing"
        job.attempts += 1
        job.save(update_fields=["status", "attempts"])
    target = job.printer
    if job.attempts > MAX_ATTEMPTS and job.printer.backup_id:
        target = job.printer.backup
    data = escpos.render(job.content, columns=target.columns, codepage=target.codepage,
                         codepage_id=target.escpos_codepage_id, cut=target.cut)
    try:
        escpos.send(target, data, settings.JETPOS["PRINT_SPOOL_DIR"], job_id=job.id)
    except escpos.PrinterError as e:
        job.status = "queued" if job.attempts < MAX_ATTEMPTS + (1 if job.printer.backup_id else 0) else "failed"
        job.last_error = str(e)
        job.save(update_fields=["status", "last_error"])
        Printer.objects.filter(pk=target.pk).update(last_error=str(e))
        if job.status == "failed":
            notify(branch=job.branch, event="printer_error", title=f"Yazdırılamadı: {job.title}",
                   body=f"{job.printer.name}: {e}", priority="high",
                   roles=[roles.CASHIER, roles.BRANCH_MANAGER, roles.OWNER], data={"job": job.id}, sound=True)
        return job
    job.status = "done"
    job.printed_on = target
    job.printed_at = timezone.now()
    job.last_error = ""
    job.save(update_fields=["status", "printed_on", "printed_at", "last_error"])
    Printer.objects.filter(pk=target.pk).update(last_ok_at=job.printed_at, last_error="")
    return job


def retry_pending(limit=100):
    n = 0
    for job in PrintJob.objects.filter(status="queued").order_by("created_at")[:limit]:
        process_job(job)
        n += 1
    # 'printing' durumunda takılı kalanları (çöken thread) yeniden kuyruğa al
    stale = timezone.now() - timezone.timedelta(minutes=2)
    PrintJob.objects.filter(status="printing", created_at__lt=stale).update(status="queued")
    return n
