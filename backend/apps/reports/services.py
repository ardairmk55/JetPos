"""Hazır raporlar, özel rapor oluşturucu, dışa aktarma ve otomatik gönderim (§10.1)."""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.core.mail import EmailMessage
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import ExtractHour, ExtractWeekDay, TruncDate
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.exceptions import BusinessError

ZERO = Decimal("0")

REPORT_TYPES = {
    "sales": "Satış özeti (günlük)",
    "products": "Ürün satışları",
    "categories": "Kategori satışları",
    "hourly": "Saatlik yoğunluk",
    "staff": "Personel satışları",
    "payments": "Kasa / ödeme yöntemleri",
    "discounts": "İndirim ve iptaller",
    "stock": "Stok durumu",
    "profit": "Maliyet / kâr (ürün)",
    "halls": "Salon bazlı satış",
    "channels": "Kanal bazlı satış",
    "cash_days": "Gün sonu kasa raporları",
    "custom": "Özel rapor",
}
DIMENSIONS = {"day": "Gün", "hour": "Saat", "weekday": "Haftanın günü", "product": "Ürün", "category": "Kategori",
              "staff": "Personel", "hall": "Salon", "channel": "Kanal"}
METRICS = {"revenue": "Ciro", "qty": "Adet", "tickets": "Adisyon sayısı", "avg_ticket": "Ortalama adisyon"}
WEEKDAYS = ["Pazar", "Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi"]


def _params(p):
    today = timezone.localdate()
    d1 = p.get("date_from")
    d2 = p.get("date_to")
    d1 = parse_date(d1) if isinstance(d1, str) and d1 else (d1 or today)
    d2 = parse_date(d2) if isinstance(d2, str) and d2 else (d2 or today)
    if d2 < d1:
        raise BusinessError("Bitiş tarihi başlangıçtan önce olamaz")
    return d1, d2


def _lines(branch, p):
    from apps.pos.models import TicketLine

    d1, d2 = _params(p)
    qs = TicketLine.objects.filter(ticket__branch=branch, ticket__status__in=("closed", "paid"), status="sent",
                                   ticket__business_date__gte=d1, ticket__business_date__lte=d2)
    if p.get("staff"):
        qs = qs.filter(ticket__waiter_id=p["staff"])
    if p.get("hall"):
        qs = qs.filter(ticket__table__hall_id=p["hall"])
    if p.get("product"):
        qs = qs.filter(product_id=p["product"])
    if p.get("category"):
        qs = qs.filter(product__category_id=p["category"])
    if p.get("channel"):
        qs = qs.filter(ticket__channel=p["channel"])
    return qs


def _tickets(branch, p):
    from apps.pos.models import Ticket

    d1, d2 = _params(p)
    qs = Ticket.objects.filter(branch=branch, status__in=("closed", "paid"), business_date__gte=d1, business_date__lte=d2)
    if p.get("staff"):
        qs = qs.filter(waiter_id=p["staff"])
    if p.get("hall"):
        qs = qs.filter(table__hall_id=p["hall"])
    if p.get("channel"):
        qs = qs.filter(channel=p["channel"])
    return qs


def _r(v):
    return float(round(v or 0, 2))


def run_report(report_type, branch, params=None):
    p = dict(params or {})
    fn = globals().get(f"_rep_{report_type}")
    if not fn:
        raise BusinessError("Bilinmeyen rapor türü")
    out = fn(branch, p)
    d1, d2 = _params(p)
    out.update({"type": report_type, "title": REPORT_TYPES[report_type], "date_from": str(d1), "date_to": str(d2),
                "branch": branch.name})
    if p.get("compare") and report_type in ("sales", "products", "categories", "staff", "custom", "channels", "halls"):
        span = (d2 - d1).days + 1
        prev = dict(p, date_from=str(d1 - timedelta(days=span)), date_to=str(d1 - timedelta(days=1)), compare=False)
        out["compare"] = fn(branch, prev).get("totals", {})
    return out


def _rep_sales(branch, p):
    rows = []
    t = _tickets(branch, p)
    for r in t.values("business_date").annotate(n=Count("id"), total=Sum("total"), disc=Sum("discount_total"),
                                                tax=Sum("tax_total")).order_by("business_date"):
        rows.append([str(r["business_date"]), r["n"], _r(r["total"]), _r(r["disc"]), _r(r["tax"]),
                     _r(r["total"] / r["n"]) if r["n"] else 0])
    tot = t.aggregate(n=Count("id"), total=Sum("total"), disc=Sum("discount_total"), tax=Sum("tax_total"))
    return {"columns": ["Tarih", "Adisyon", "Ciro", "İndirim", "KDV", "Ort. adisyon"], "rows": rows,
            "chart": {"type": "line", "labels": [r[0] for r in rows], "series": [{"name": "Ciro", "data": [r[2] for r in rows]}]},
            "totals": {"tickets": tot["n"], "revenue": _r(tot["total"]), "discount": _r(tot["disc"]), "tax": _r(tot["tax"]),
                       "avg_ticket": _r((tot["total"] or 0) / tot["n"]) if tot["n"] else 0}}


def _rep_products(branch, p):
    qs = _lines(branch, p).values("product__name", "product__category__name").annotate(
        qty=Sum("qty"), revenue=Sum("net_total")).order_by("-revenue")
    rows = [[r["product__name"], r["product__category__name"], _r(r["qty"]), _r(r["revenue"])] for r in qs]
    return {"columns": ["Ürün", "Kategori", "Adet", "Ciro"], "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in rows[:15]], "series": [{"name": "Ciro", "data": [r[3] for r in rows[:15]]}]},
            "totals": {"qty": _r(sum(r[2] for r in rows)), "revenue": _r(sum(r[3] for r in rows))}}


def _rep_categories(branch, p):
    qs = _lines(branch, p).values("product__category__name").annotate(qty=Sum("qty"), revenue=Sum("net_total")).order_by("-revenue")
    rows = [[r["product__category__name"], _r(r["qty"]), _r(r["revenue"])] for r in qs]
    return {"columns": ["Kategori", "Adet", "Ciro"], "rows": rows,
            "chart": {"type": "donut", "labels": [r[0] for r in rows], "series": [{"name": "Ciro", "data": [r[2] for r in rows]}]},
            "totals": {"revenue": _r(sum(r[2] for r in rows))}}


def _rep_hourly(branch, p):
    from apps.pos.models import Ticket

    t = _tickets(branch, p).annotate(h=ExtractHour("opened_at", tzinfo=timezone.get_current_timezone()))
    agg = {r["h"]: r for r in t.values("h").annotate(n=Count("id"), total=Sum("total"))}
    rows = [[f"{h:02d}:00", agg.get(h, {}).get("n", 0), _r(agg.get(h, {}).get("total"))] for h in range(24)]
    return {"columns": ["Saat", "Adisyon", "Ciro"], "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in rows], "series": [{"name": "Adisyon", "data": [r[1] for r in rows]}]},
            "totals": {"peak_hour": max(rows, key=lambda r: r[1])[0] if rows else None}}


def _rep_staff(branch, p):
    from apps.pos.models import TicketLine

    d1, d2 = _params(p)
    t = _tickets(branch, p)
    rows = []
    for r in t.values("waiter__username", "waiter__first_name", "waiter__last_name", "waiter_id").annotate(
            n=Count("id"), total=Sum("total")).order_by("-total"):
        voids = TicketLine.objects.filter(ticket__branch=branch, status="void", created_by_id=r["waiter_id"],
                                          voided_at__date__gte=d1, voided_at__date__lte=d2).count()
        name = f"{r['waiter__first_name'] or ''} {r['waiter__last_name'] or ''}".strip() or (r["waiter__username"] or "-")
        rows.append([name, r["n"], _r(r["total"]), _r(r["total"] / r["n"]) if r["n"] else 0, voids])
    return {"columns": ["Personel", "Adisyon", "Ciro", "Ort. adisyon", "İptal"], "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in rows], "series": [{"name": "Ciro", "data": [r[2] for r in rows]}]},
            "totals": {"revenue": _r(sum(r[2] for r in rows))}}


def _rep_payments(branch, p):
    from apps.pos.models import Payment, Refund

    d1, d2 = _params(p)
    pays = Payment.objects.filter(branch=branch, created_at__date__gte=d1, created_at__date__lte=d2)
    refs = Refund.objects.filter(branch=branch, created_at__date__gte=d1, created_at__date__lte=d2)
    labels = dict(Payment._meta.get_field("method").choices)
    rows = []
    for m, label in labels.items():
        a = pays.filter(method=m).aggregate(n=Count("id"), s=Sum("amount"))
        r = refs.filter(method=m).aggregate(s=Sum("amount"))["s"] or 0
        rows.append([label, a["n"], _r(a["s"]), _r(r), _r((a["s"] or 0) - r)])
    return {"columns": ["Yöntem", "İşlem", "Tahsilat", "İade", "Net"], "rows": rows,
            "chart": {"type": "donut", "labels": [r[0] for r in rows], "series": [{"name": "Net", "data": [r[4] for r in rows]}]},
            "totals": {"collections": _r(sum(r[2] for r in rows)), "refunds": _r(sum(r[3] for r in rows)),
                       "net": _r(sum(r[4] for r in rows))}}


def _rep_discounts(branch, p):
    from apps.pos.models import TicketDiscount, TicketLine

    d1, d2 = _params(p)
    rows = []
    for d in TicketDiscount.objects.filter(ticket__branch=branch, created_at__date__gte=d1, created_at__date__lte=d2,
                                           reversed_at__isnull=True).select_related("ticket", "created_by", "approved_by"):
        rows.append(["İndirim", str(timezone.localtime(d.created_at))[:16], f"#{d.ticket.number}", d.get_kind_display(),
                     _r(d.amount), d.reason, d.created_by.username if d.created_by else "",
                     d.approved_by.username if d.approved_by else ""])
    for ln in TicketLine.objects.filter(ticket__branch=branch, status="void", voided_at__date__gte=d1,
                                        voided_at__date__lte=d2).select_related("ticket", "voided_by", "created_by"):
        rows.append(["İptal", str(timezone.localtime(ln.voided_at))[:16], f"#{ln.ticket.number}",
                     f"{ln.qty.normalize()} x {ln.name}", _r(ln.unit_price * ln.qty), ln.void_reason,
                     ln.created_by.username if ln.created_by else "", ln.voided_by.username if ln.voided_by else ""])
    rows.sort(key=lambda r: r[1])
    return {"columns": ["Tür", "Zaman", "Adisyon", "Detay", "Tutar", "Gerekçe", "İşlemi yapan", "Onaylayan"], "rows": rows,
            "totals": {"discount": _r(sum(r[4] for r in rows if r[0] == "İndirim")),
                       "void": _r(sum(r[4] for r in rows if r[0] == "İptal")), "count": len(rows)}}


def _rep_stock(branch, p):
    from apps.inventory.models import StockItem, StockLevel
    from apps.inventory.services import default_warehouse

    wh = default_warehouse(branch)
    levels = {lv.item_id: lv.qty for lv in StockLevel.objects.filter(warehouse=wh)}
    rows = []
    for it in StockItem.objects.filter(business=branch.business, is_active=True):
        q = levels.get(it.id, ZERO)
        rows.append([it.name, it.unit, _r(q), _r(it.min_level), _r(it.cost), _r(q * it.cost if q > 0 else 0),
                     "Tükendi" if q <= 0 else ("Düşük" if q <= it.min_level else "Normal")])
    return {"columns": ["Malzeme", "Birim", "Miktar", "Min", "Birim maliyet", "Değer", "Durum"], "rows": rows,
            "totals": {"value": _r(sum(r[5] for r in rows)), "low": sum(1 for r in rows if r[6] != "Normal")}}


def _rep_profit(branch, p):
    from apps.inventory.services import product_cost

    rows = []
    for r in _lines(branch, p).values("product_id", "product__name").annotate(qty=Sum("qty"), revenue=Sum("net_total"),
                                                                                tax=Sum("tax_amount")):
        from apps.catalog.models import Product

        cost = product_cost(Product.objects.get(pk=r["product_id"])) * r["qty"]
        net = (r["revenue"] or 0) - (r["tax"] or 0)
        rows.append([r["product__name"], _r(r["qty"]), _r(net), _r(cost), _r(net - cost),
                     _r((net - cost) / net * 100) if net else 0])
    rows.sort(key=lambda x: -x[4])
    return {"columns": ["Ürün", "Adet", "Net satış (KDV hariç)", "Maliyet", "Brüt kâr", "Kâr %"], "rows": rows,
            "chart": {"type": "bar", "labels": [r[0] for r in rows[:15]], "series": [{"name": "Brüt kâr", "data": [r[4] for r in rows[:15]]}]},
            "totals": {"net": _r(sum(r[2] for r in rows)), "cost": _r(sum(r[3] for r in rows)),
                       "profit": _r(sum(r[4] for r in rows))}}


def _rep_halls(branch, p):
    qs = _tickets(branch, p).values("table__hall__name").annotate(n=Count("id"), total=Sum("total")).order_by("-total")
    rows = [[r["table__hall__name"] or "Masasız", r["n"], _r(r["total"])] for r in qs]
    return {"columns": ["Salon", "Adisyon", "Ciro"], "rows": rows,
            "chart": {"type": "donut", "labels": [r[0] for r in rows], "series": [{"name": "Ciro", "data": [r[2] for r in rows]}]},
            "totals": {"revenue": _r(sum(r[2] for r in rows))}}


def _rep_channels(branch, p):
    from apps.catalog.models import CHANNELS

    labels = dict(CHANNELS)
    qs = _tickets(branch, p).values("channel").annotate(n=Count("id"), total=Sum("total")).order_by("-total")
    rows = [[labels.get(r["channel"], r["channel"]), r["n"], _r(r["total"])] for r in qs]
    return {"columns": ["Kanal", "Adisyon", "Ciro"], "rows": rows,
            "chart": {"type": "donut", "labels": [r[0] for r in rows], "series": [{"name": "Ciro", "data": [r[2] for r in rows]}]},
            "totals": {"revenue": _r(sum(r[2] for r in rows))}}


def _rep_cash_days(branch, p):
    from apps.pos.models import CashDay

    d1, d2 = _params(p)
    rows = []
    for d in CashDay.objects.filter(branch=branch, business_date__gte=d1, business_date__lte=d2).order_by("business_date"):
        rows.append([str(d.business_date), d.get_status_display(), _r(d.opening_balance), _r(d.expected_cash),
                     _r(d.counted_cash), _r(d.difference), d.difference_reason])
    return {"columns": ["Tarih", "Durum", "Açılış", "Beklenen", "Sayılan", "Fark", "Fark nedeni"], "rows": rows,
            "totals": {"difference": _r(sum(r[5] for r in rows))}}


def _rep_custom(branch, p):
    dim = p.get("dimension", "day")
    metric = p.get("metric", "revenue")
    if dim not in DIMENSIONS or metric not in METRICS:
        raise BusinessError("Geçersiz boyut/ölçü")
    tz = timezone.get_current_timezone()
    if metric in ("tickets", "avg_ticket") and dim not in ("product", "category"):
        qs = _tickets(branch, p)
        key = {"day": "business_date", "hour": "h", "weekday": "wd", "staff": "waiter__username",
               "hall": "table__hall__name", "channel": "channel"}[dim]
        if dim == "hour":
            qs = qs.annotate(h=ExtractHour("opened_at", tzinfo=tz))
        if dim == "weekday":
            qs = qs.annotate(wd=ExtractWeekDay("opened_at", tzinfo=tz))
        agg = qs.values(key).annotate(n=Count("id"), total=Sum("total")).order_by(key)
        rows = [[_label(dim, r[key]), r["n"] if metric == "tickets" else _r(r["total"] / r["n"] if r["n"] else 0)] for r in agg]
    else:
        qs = _lines(branch, p)
        key = {"day": "ticket__business_date", "hour": "h", "weekday": "wd", "product": "product__name",
               "category": "product__category__name", "staff": "ticket__waiter__username",
               "hall": "ticket__table__hall__name", "channel": "ticket__channel"}[dim]
        if dim == "hour":
            qs = qs.annotate(h=ExtractHour("ticket__opened_at", tzinfo=tz))
        if dim == "weekday":
            qs = qs.annotate(wd=ExtractWeekDay("ticket__opened_at", tzinfo=tz))
        if metric in ("tickets", "avg_ticket"):
            agg = qs.values(key).annotate(n=Count("ticket", distinct=True), s=Sum("net_total")).order_by(key)
            rows = [[_label(dim, r[key]), r["n"] if metric == "tickets" else _r(r["s"] / r["n"] if r["n"] else 0)] for r in agg]
        else:
            agg = qs.values(key).annotate(v=Sum("net_total" if metric == "revenue" else "qty")).order_by(key)
            rows = [[_label(dim, r[key]), _r(r["v"])] for r in agg]
    if dim in ("product", "category", "staff"):
        rows.sort(key=lambda r: -r[1])
    return {"columns": [DIMENSIONS[dim], METRICS[metric]], "rows": rows,
            "chart": {"type": "bar" if dim != "day" else "line", "labels": [r[0] for r in rows],
                      "series": [{"name": METRICS[metric], "data": [r[1] for r in rows]}]},
            "totals": {"sum": _r(sum(r[1] for r in rows)) if metric != "avg_ticket" else None}}


def _label(dim, v):
    if v is None:
        return "-"
    if dim == "hour":
        return f"{int(v):02d}:00"
    if dim == "weekday":
        return WEEKDAYS[int(v) - 1]
    if dim == "channel":
        from apps.catalog.models import CHANNELS

        return dict(CHANNELS).get(v, v)
    return str(v)


# ------------------------------------------------------------------ dışa aktarma
def to_csv(rep):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([rep["title"], rep["branch"], f"{rep['date_from']} - {rep['date_to']}"])
    w.writerow(rep["columns"])
    for r in rep["rows"]:
        w.writerow(r)
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def to_xlsx(rep):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Rapor"
    ws.append([rep["title"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"{rep['branch']} — {rep['date_from']} / {rep['date_to']}"])
    ws.append([])
    ws.append(rep["columns"])
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="252936")
    for r in rep["rows"]:
        ws.append(r)
    if rep.get("totals"):
        ws.append([])
        for k, v in rep["totals"].items():
            ws.append([k, v])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(12, min(40, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if "JetSans" in pdfmetrics.getRegisteredFontNames():
        return "JetSans"
    for cand in (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf"):
        if Path(cand).exists():
            pdfmetrics.registerFont(TTFont("JetSans", cand))
            return "JetSans"
    return "Helvetica"


def to_pdf(rep):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font = _font()
    buf = io.BytesIO()
    wide = len(rep["columns"]) > 5
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4) if wide else A4, title=rep["title"])
    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        s.fontName = font
    story = [Paragraph(f"JETPOS — {rep['title']}", styles["Title"]),
             Paragraph(f"{rep['branch']} · {rep['date_from']} – {rep['date_to']}", styles["Normal"]), Spacer(1, 10)]
    data = [rep["columns"]] + [[str(c) for c in r] for r in rep["rows"]]
    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 8),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#252936")),
                           ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F6F8")])]))
    story.append(t)
    if rep.get("totals"):
        story.append(Spacer(1, 10))
        story.append(Paragraph(" · ".join(f"{k}: {v}" for k, v in rep["totals"].items() if v is not None), styles["Normal"]))
    doc.build(story)
    return buf.getvalue()


EXPORTERS = {"csv": (to_csv, "text/csv"), "xlsx": (to_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
             "pdf": (to_pdf, "application/pdf")}


# ------------------------------------------------------------------ zamanlanmış gönderim
def _period(schedule, now):
    local = timezone.localtime(now)
    if schedule.frequency == "daily":
        due = local.time() >= schedule.send_time
        key = str(local.date())
        rng = (local.date() - timedelta(days=1), local.date() - timedelta(days=1))
    elif schedule.frequency == "weekly":
        due = local.weekday() == schedule.weekday and local.time() >= schedule.send_time
        key = f"{local.isocalendar()[0]}-W{local.isocalendar()[1]}"
        rng = (local.date() - timedelta(days=7), local.date() - timedelta(days=1))
    else:
        due = local.day == schedule.month_day and local.time() >= schedule.send_time
        key = f"{local.year}-{local.month:02d}"
        last_month_end = local.date().replace(day=1) - timedelta(days=1)
        rng = (last_month_end.replace(day=1), last_month_end)
    return due, key, rng


def run_due_schedules(now=None, max_attempts=3):
    from .models import ReportDelivery, ReportSchedule

    now = now or timezone.now()
    sent = 0
    for s in ReportSchedule.objects.filter(is_active=True).select_related("branch"):
        due, key, (d1, d2) = _period(s, now)
        if not due:
            continue
        dl, _ = ReportDelivery.objects.get_or_create(schedule=s, period_key=key)
        if dl.ok or dl.attempts >= max_attempts:
            continue
        dl.attempts += 1
        try:
            if not s.recipients:
                raise BusinessError("Alıcı tanımlı değil")
            rep = run_report(s.report_type, s.branch, dict(s.params, date_from=str(d1), date_to=str(d2)))
            fn, mime = EXPORTERS[s.fmt]
            msg = EmailMessage(subject=f"[JETPOS] {s.name} ({d1} – {d2})",
                               body=f"{s.branch.name} için {rep['title']} raporu ektedir.", to=s.recipients)
            msg.attach(f"jetpos_{s.report_type}_{d1}_{d2}.{s.fmt}", fn(rep), mime)
            msg.send(fail_silently=False)
            dl.ok = True
            dl.error = ""
            s.last_run_at = now
            s.save(update_fields=["last_run_at"])
            sent += 1
        except Exception as e:
            dl.error = str(e)[:2000]
        dl.save()
    return sent


# ------------------------------------------------------------------ dashboard
def dashboard(branch, user):
    from apps.core import roles
    from apps.pos.models import ACTIVE_TICKET_STATES, CashDay, KitchenOrder, Payment, Ticket, TicketLine

    today = timezone.localdate()
    tz = timezone.get_current_timezone()
    cards = {}
    charts = {}
    closed = Ticket.objects.filter(branch=branch, business_date=today, status__in=("closed", "paid"))
    if roles.has_perm(user, roles.REPORTS_VIEW) or roles.has_perm(user, roles.CASH_MANAGE):
        agg = closed.aggregate(n=Count("id"), s=Sum("total"))
        y = Ticket.objects.filter(branch=branch, business_date=today - timedelta(days=1),
                                  status__in=("closed", "paid")).aggregate(s=Sum("total"))["s"] or 0
        cards["sales_today"] = {"value": _r(agg["s"]), "prev": _r(y)}
        cards["tickets_today"] = {"value": agg["n"]}
        cards["avg_ticket"] = {"value": _r((agg["s"] or 0) / agg["n"]) if agg["n"] else 0}
        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            week.append([d.strftime("%d.%m"), _r(Ticket.objects.filter(branch=branch, business_date=d,
                                                                       status__in=("closed", "paid")).aggregate(s=Sum("total"))["s"])])
        charts["week"] = {"type": "line", "labels": [w[0] for w in week], "series": [{"name": "Ciro", "data": [w[1] for w in week]}]}
        hourly = {r["h"]: r["n"] for r in Ticket.objects.filter(branch=branch, business_date=today).annotate(
            h=ExtractHour("opened_at", tzinfo=tz)).values("h").annotate(n=Count("id"))}
        charts["hourly"] = {"type": "bar", "labels": [f"{h:02d}" for h in range(8, 24)],
                            "series": [{"name": "Adisyon", "data": [hourly.get(h, 0) for h in range(8, 24)]}]}
        top = TicketLine.objects.filter(ticket__branch=branch, ticket__business_date=today, status="sent") \
            .values("product__name").annotate(q=Sum("qty")).order_by("-q")[:8]
        charts["top_products"] = {"type": "bar", "labels": [t["product__name"] for t in top],
                                  "series": [{"name": "Adet", "data": [_r(t["q"]) for t in top]}]}
        pm = Payment.objects.filter(branch=branch, created_at__date=today).values("method").annotate(s=Sum("amount"))
        labels = dict(Payment._meta.get_field("method").choices)
        charts["payments"] = {"type": "donut", "labels": [labels[p["method"]] for p in pm],
                              "series": [{"name": "Tahsilat", "data": [_r(p["s"]) for p in pm]}]}
    if roles.has_perm(user, roles.FLOOR_VIEW):
        active = Ticket.objects.filter(branch=branch, status__in=ACTIVE_TICKET_STATES)
        cards["open_tickets"] = {"value": active.count(), "amount": _r(active.aggregate(s=Sum("total"))["s"])}
        cards["bill_requested"] = {"value": active.filter(status="bill_requested").count()}
    if roles.has_perm(user, roles.KDS_VIEW) or roles.has_perm(user, roles.READY_VIEW):
        late = branch.settings.late_order_minutes
        pend = KitchenOrder.objects.filter(batch__ticket__branch=branch).exclude(status="ready")
        cards["kitchen_pending"] = {"value": pend.count(),
                                    "late": pend.filter(created_at__lt=timezone.now() - timedelta(minutes=late)).count()}
        from apps.pos.models import KitchenBatch

        cards["ready_orders"] = {"value": KitchenBatch.objects.filter(ticket__branch=branch, status="ready").count()}
    if roles.has_perm(user, roles.STOCK_VIEW):
        from apps.inventory.models import StockItem, StockLevel
        from apps.inventory.services import default_warehouse

        wh = default_warehouse(branch)
        levels = {lv.item_id: lv.qty for lv in StockLevel.objects.filter(warehouse=wh)}
        items = StockItem.objects.filter(business=branch.business, is_active=True)
        cards["low_stock"] = {"value": sum(1 for it in items if levels.get(it.id, 0) <= it.min_level)}
    if roles.has_perm(user, roles.CASH_MANAGE):
        day = CashDay.objects.filter(branch=branch, status__in=("open", "pending_approval")).first()
        from apps.pos.services import expected_cash

        cards["cash"] = {"status": day.status if day else "closed", "expected": _r(expected_cash(day)) if day else None}
    if roles.has_perm(user, roles.APPROVALS_DECIDE) or roles.has_perm(user, roles.APPROVALS_MUNICIPAL):
        from apps.pos.models import ApprovalRequest

        cards["approvals"] = {"value": ApprovalRequest.objects.filter(branch=branch, status="pending").count()}
    return {"cards": cards, "charts": charts, "date": str(today)}


__all__ = ["DecimalField", "ExpressionWrapper", "F", "Q", "TruncDate", "date"]
