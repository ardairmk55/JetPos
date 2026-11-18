"""Stok hareketleri (§8). Her hareket öncesi/sonrası miktar, aktör ve gerekçeyle kaydedilir."""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core import audit, roles
from apps.core.exceptions import BusinessError
from apps.core.notify import notify

from .models import (PurchaseLine, PurchaseReceipt, RecipeLine, SaleDeduction, StockCount, StockCountLine, StockItem,
                     StockLevel, StockMovement, Transfer, TransferLine, Warehouse)

ZERO = Decimal("0")
_FACTORS = {("g", "kg"): Decimal("0.001"), ("kg", "g"): Decimal("1000"), ("ml", "lt"): Decimal("0.001"),
            ("lt", "ml"): Decimal("1000")}


def convert(qty, from_unit, to_unit):
    if from_unit == to_unit:
        return Decimal(qty)
    f = _FACTORS.get((from_unit, to_unit))
    if f is None:
        raise BusinessError(f"Birim dönüşümü tanımsız: {from_unit} → {to_unit}", code="unit_conversion")
    return Decimal(qty) * f


def default_warehouse(branch):
    wh = Warehouse.objects.filter(branch=branch, is_active=True).order_by("-is_default", "id").first()
    if wh is None:
        wh = Warehouse.objects.create(business=branch.business, branch=branch, name="Ana Depo", is_default=True)
    return wh


def consumption(product, qty):
    """[(item, qty_in_item_unit)] — reçete varsa reçete, yoksa doğrudan stoklu ürün."""
    out = []
    for rl in RecipeLine.objects.filter(product=product).select_related("item"):
        out.append((rl.item, convert(rl.qty, rl.unit, rl.item.unit) * Decimal(qty)))
    if not out:
        item = StockItem.objects.filter(product=product, is_active=True).first()
        if item:
            out.append((item, Decimal(qty)))
    return out


def level(warehouse, item):
    return StockLevel.objects.filter(warehouse=warehouse, item=item).values_list("qty", flat=True).first() or ZERO


def check_availability(branch, product, qty):
    """'ok' | 'warn' | 'block' — stok politikası genel (şube) veya ürün bazlı (§8)."""
    needs = consumption(product, qty)
    if not needs:
        return "ok"
    wh = default_warehouse(branch)
    short = any(level(wh, item) < need for item, need in needs)
    if not short:
        return "ok"
    policy = product.stock_policy if product.stock_policy != "inherit" else branch.settings.out_of_stock_policy
    return "block" if policy == "block" else "warn"


def availability_map(branch, product_ids):
    from apps.catalog.models import Product

    wh = default_warehouse(branch)
    levels = {lv.item_id: lv.qty for lv in StockLevel.objects.filter(warehouse=wh)}
    result = {}
    for p in Product.objects.filter(pk__in=product_ids):
        needs = consumption(p, 1)
        if not needs:
            continue
        if any(levels.get(item.id, ZERO) < need for item, need in needs):
            result[p.id] = "out"
        elif any(levels.get(item.id, ZERO) <= item.min_level for item, _ in needs):
            result[p.id] = "low"
    return result


def apply_movement(*, warehouse, item, delta, kind, user, reason="", ref_type="", ref_id="", unit_cost=None):
    with transaction.atomic():
        lv, _ = StockLevel.objects.select_for_update().get_or_create(warehouse=warehouse, item=item)
        before = lv.qty
        lv.qty = before + Decimal(delta)
        lv.save(update_fields=["qty"])
        mv = StockMovement.objects.create(
            business=warehouse.business, branch=warehouse.branch, warehouse=warehouse, item=item, kind=kind,
            qty=Decimal(delta), before=before, after=lv.qty, unit_cost=unit_cost if unit_cost is not None else item.cost,
            reason=reason[:300], ref_type=ref_type, ref_id=str(ref_id), user=user)
    if before > item.min_level >= lv.qty and item.min_level > 0:
        notify(branch=warehouse.branch, event="low_stock", title=f"Düşük stok: {item.name}",
               body=f"{warehouse.name}: {lv.qty.normalize()} {item.unit} (min {item.min_level.normalize()})",
               priority="medium", roles=[roles.STOCK, roles.BRANCH_MANAGER, roles.OWNER],
               data={"item": item.id, "warehouse": warehouse.id})
    return mv


def deduct_for_lines(lines, *, user):
    """Satış/reçete tüketimi otomatik ve bir kez işlenir."""
    for ln in lines:
        if ln.status == "void":
            continue
        branch = ln.ticket.branch
        wh = default_warehouse(branch)
        for item, need in consumption(ln.product, ln.qty):
            try:
                with transaction.atomic():
                    SaleDeduction.objects.create(line=ln, item=item, warehouse=wh, line_qty=ln.qty, qty=need)
            except IntegrityError:
                continue  # zaten düşülmüş
            apply_movement(warehouse=wh, item=item, delta=-need, kind="sale", user=user,
                           reason=f"Adisyon #{ln.ticket.number}", ref_type="TicketLine", ref_id=ln.id)


def reverse_for_line(line, *, qty, user, kind="void"):
    """İptal/iade kontrollü ters hareket; düşülmemiş stok geri alınmaz."""
    for d in SaleDeduction.objects.select_for_update().filter(line__in=[line.id, line.voided_from_id or 0]):
        remaining = d.qty - d.reversed_qty
        if remaining <= 0:
            continue
        back = min(remaining, (d.qty / Decimal(d.line_qty)) * Decimal(qty))
        if back <= 0:
            continue
        d.reversed_qty += back
        d.save(update_fields=["reversed_qty"])
        apply_movement(warehouse=d.warehouse, item=d.item, delta=back, kind="sale_reversal", user=user,
                       reason=f"{'İptal' if kind == 'void' else 'İade'} — adisyon #{line.ticket.number}",
                       ref_type="TicketLine", ref_id=line.id)


def manual_movement(*, warehouse, item, kind, qty, user, reason, request=None):
    if not reason or len(reason.strip()) < 3:
        raise BusinessError("Manuel stok hareketi için gerekçe zorunludur", code="reason_required")
    qty = Decimal(str(qty))
    if kind == "waste":
        if qty <= 0:
            raise BusinessError("Fire miktarı pozitif olmalı")
        delta = -qty
    elif kind == "adjust":
        delta = qty
        if delta == 0:
            raise BusinessError("Düzeltme miktarı sıfır olamaz")
    elif kind == "opening":
        delta = qty
    else:
        raise BusinessError("Geçersiz hareket türü")
    mv = apply_movement(warehouse=warehouse, item=item, delta=delta, kind=kind, user=user, reason=reason)
    audit.log(f"stock.{kind}", request=request, user=user, business=warehouse.business, branch=warehouse.branch,
              entity="StockMovement", entity_id=mv.pk, before={"qty": str(mv.before)}, after={"qty": str(mv.after)},
              reason=reason)
    return mv


def receive_purchase(*, warehouse, supplier, lines, user, document_no="", note=""):
    if not lines:
        raise BusinessError("Mal kabul satırı yok")
    with transaction.atomic():
        r = PurchaseReceipt.objects.create(business=warehouse.business, branch=warehouse.branch, warehouse=warehouse,
                                           supplier=supplier, document_no=document_no, note=note, user=user)
        total = ZERO
        for ln in lines:
            item = StockItem.objects.get(pk=ln["item"], business=warehouse.business)
            qty = Decimal(str(ln["qty"]))
            cost = Decimal(str(ln.get("unit_cost", item.cost)))
            if qty <= 0 or cost < 0:
                raise BusinessError("Geçersiz miktar/maliyet")
            PurchaseLine.objects.create(receipt=r, item=item, qty=qty, unit_cost=cost)
            # Ağırlıklı ortalama maliyet
            current = StockLevel.objects.filter(item=item).aggregate(s=Sum("qty"))["s"] or ZERO
            if current + qty > 0:
                item.cost = ((max(current, ZERO) * item.cost) + qty * cost) / (max(current, ZERO) + qty)
                item.save(update_fields=["cost"])
            apply_movement(warehouse=warehouse, item=item, delta=qty, kind="purchase", user=user, unit_cost=cost,
                           reason=f"Mal kabul {document_no}".strip(), ref_type="PurchaseReceipt", ref_id=r.id)
            total += qty * cost
        r.total = total.quantize(Decimal("0.01"))
        r.save(update_fields=["total"])
        audit.log("stock.purchase", user=user, business=warehouse.business, branch=warehouse.branch,
                  entity="PurchaseReceipt", entity_id=r.pk, after={"total": str(r.total), "lines": len(lines)})
    return r


def transfer_stock(*, source, target, lines, user, note=""):
    if source.id == target.id:
        raise BusinessError("Kaynak ve hedef depo aynı olamaz")
    if source.business_id != target.business_id:
        raise BusinessError("Depolar farklı işletmeye ait")
    with transaction.atomic():
        t = Transfer.objects.create(business=source.business, source=source, target=target, note=note, user=user)
        for ln in lines:
            item = StockItem.objects.get(pk=ln["item"], business=source.business)
            qty = Decimal(str(ln["qty"]))
            if qty <= 0:
                raise BusinessError("Transfer miktarı pozitif olmalı")
            if level(source, item) < qty:
                raise BusinessError(f"Kaynak depoda yetersiz stok: {item.name}", code="insufficient_stock")
            TransferLine.objects.create(transfer=t, item=item, qty=qty)
            apply_movement(warehouse=source, item=item, delta=-qty, kind="transfer_out", user=user,
                           reason=f"Transfer → {target.name}", ref_type="Transfer", ref_id=t.id)
            apply_movement(warehouse=target, item=item, delta=qty, kind="transfer_in", user=user,
                           reason=f"Transfer ← {source.name}", ref_type="Transfer", ref_id=t.id)
        audit.log("stock.transfer", user=user, business=source.business, branch=source.branch, entity="Transfer",
                  entity_id=t.pk, after={"from": source.name, "to": target.name, "lines": len(lines)})
    return t


def create_count(*, warehouse, user, counts, note=""):
    with transaction.atomic():
        c = StockCount.objects.create(business=warehouse.business, warehouse=warehouse, user=user, note=note)
        for ln in counts:
            item = StockItem.objects.get(pk=ln["item"], business=warehouse.business)
            StockCountLine.objects.create(count=c, item=item, expected=level(warehouse, item),
                                          counted=Decimal(str(ln["counted"])))
    return c


def apply_count(count, *, user):
    if count.status != "draft":
        raise BusinessError("Sayım zaten uygulanmış")
    with transaction.atomic():
        for ln in count.lines.select_related("item"):
            current = level(count.warehouse, ln.item)
            diff = ln.counted - current
            if diff != 0:
                apply_movement(warehouse=count.warehouse, item=ln.item, delta=diff, kind="count", user=user,
                               reason=f"Sayım #{count.id}", ref_type="StockCount", ref_id=count.id)
        count.status = "applied"
        count.applied_at = timezone.now()
        count.save(update_fields=["status", "applied_at"])
        audit.log("stock.count_apply", user=user, business=count.business, branch=count.warehouse.branch,
                  entity="StockCount", entity_id=count.pk)
    return count


def product_cost(product):
    total = ZERO
    for item, need in consumption(product, 1):
        total += need * item.cost
    return total.quantize(Decimal("0.0001"))
