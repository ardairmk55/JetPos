"""Fiyat çözümleme ve kampanya motoru (§6.4). Deterministik kurallar."""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from .models import Campaign, ProductPrice

CENT = Decimal("0.01")


def money(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def resolve_price(product, *, branch=None, channel="table", customer_group=None, at=None):
    """En özel eşleşen fiyat kazanır: grup > şube > kanal; zamanlı fiyat geçerlilik aralığında olmalı."""
    at = at or timezone.now()
    qs = ProductPrice.objects.filter(product=product, is_active=True).filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=at), Q(valid_to__isnull=True) | Q(valid_to__gte=at),
        Q(branch__isnull=True) | Q(branch=branch), Q(channel="") | Q(channel=channel),
        Q(customer_group__isnull=True) | Q(customer_group=customer_group),
    )
    best, best_score = None, -1
    for p in qs:
        score = (4 if p.customer_group_id else 0) + (2 if p.branch_id else 0) + (1 if p.channel else 0)
        score = score * 10 + (1 if p.valid_from else 0)
        if score > best_score:
            best, best_score = p, score
    return money(best.price if best else product.base_price)


def split_tax(gross_or_net, rate, included):
    """(net, tax, gross) döner."""
    rate = Decimal(rate) / 100
    amount = Decimal(gross_or_net)
    if included:
        net = amount / (1 + rate) if rate else amount
        return money(net), money(amount - money(net)), money(amount)
    tax = amount * rate
    return money(amount), money(tax), money(amount + tax)


def _campaign_applies(c, *, branch, channel, customer_group, now):
    if not c.is_active:
        return False
    if c.usage_limit is not None and c.used_count >= c.usage_limit:
        return False
    local = timezone.localtime(now)
    if c.valid_from and local.date() < c.valid_from:
        return False
    if c.valid_to and local.date() > c.valid_to:
        return False
    if c.weekdays and local.weekday() not in c.weekdays:
        return False
    if c.start_time and local.time() < c.start_time:
        return False
    if c.end_time and local.time() > c.end_time:
        return False
    if c.channels and channel not in c.channels:
        return False
    branch_ids = [b.id for b in c.branches.all()]
    if branch_ids and (branch is None or branch.id not in branch_ids):
        return False
    group_ids = [g.id for g in c.customer_groups.all()]
    if group_ids and (customer_group is None or customer_group.id not in group_ids):
        return False
    return True


def _eligible(c, line):
    pids = {p.id for p in c.products.all()}
    cids = {x.id for x in c.categories.all()}
    if not pids and not cids:
        return True
    return line.product_id in pids or line.product.category_id in cids


def apply_campaigns(lines, *, business, branch, channel, customer_group=None, now=None):
    """Satır başına en yüksek öncelikli tek kampanya uygulanır (çakışma önceliği).

    `lines`: unit_price, qty, product, product_id özelliklerine sahip nesneler.
    Dönüş: {line_index: (campaign, discount_amount)}
    """
    now = now or timezone.now()
    campaigns = [c for c in Campaign.objects.filter(business=business, is_active=True).order_by("-priority", "id")
                 .prefetch_related("products", "categories", "branches", "customer_groups")
                 if _campaign_applies(c, branch=branch, channel=channel, customer_group=customer_group, now=now)]
    result = {}
    taken = set()
    for c in campaigns:
        idxs = [i for i, ln in enumerate(lines) if i not in taken and _eligible(c, ln)]
        if not idxs:
            continue
        if c.kind == "percent":
            for i in idxs:
                ln = lines[i]
                result[i] = (c, money(ln.unit_price * ln.qty * c.value / 100))
                taken.add(i)
        elif c.kind == "fixed":
            for i in idxs:
                ln = lines[i]
                result[i] = (c, min(money(ln.unit_price * ln.qty), money(c.value * ln.qty)))
                taken.add(i)
        elif c.kind == "buy_x_get_y":
            units = []
            for i in idxs:
                ln = lines[i]
                units += [(ln.unit_price, i)] * int(ln.qty)
            group = c.buy_qty + c.get_qty
            free_count = (len(units) // group) * c.get_qty if group else 0
            if free_count:
                units.sort(key=lambda u: u[0])  # en ucuz birimler bedava
                pct = c.value if c.value else Decimal(100)
                disc = {}
                for price, i in units[:free_count]:
                    disc[i] = disc.get(i, Decimal(0)) + money(price * pct / 100)
                for i in idxs:
                    result[i] = (c, disc.get(i, Decimal("0.00")))
                    taken.add(i)
        elif c.kind == "bundle_price":
            # Paket: kampanyadaki her ürün en az birer adet varsa, paket sayısı kadar sabit fiyat.
            pids = [p.id for p in c.products.all()]
            if not pids:
                continue
            by_pid = {}
            for i in idxs:
                by_pid.setdefault(lines[i].product_id, []).append(i)
            if not all(p in by_pid for p in pids):
                continue
            bundles = min(int(sum(lines[i].qty for i in by_pid[p])) for p in pids)
            if bundles <= 0:
                continue
            normal = sum(min(Decimal(lines[i].unit_price) for i in by_pid[p]) for p in pids) * bundles
            saving = money(normal - c.value * bundles)
            if saving <= 0:
                continue
            members = [i for p in pids for i in by_pid[p]]
            gross = sum(money(lines[i].unit_price * lines[i].qty) for i in members)
            remaining = saving
            for n, i in enumerate(members):
                share = remaining if n == len(members) - 1 else money(saving * money(lines[i].unit_price * lines[i].qty) / gross)
                remaining -= share
                result[i] = (c, share)
                taken.add(i)
    return result
