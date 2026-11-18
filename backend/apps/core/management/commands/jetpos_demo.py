"""Değerlendirme/demo verisi. ÜRETİMDE KULLANMAYIN.

Ürün adları ve fiyatlar örnektir (DEMO); gerçek menü/fiyat bilgisi değildir.
Demo hesapları (yalnızca yerel değerlendirme için):
  sahip / Demo-Sahip-2026  (PIN 9999)   — işletme sahibi
  mudur / Demo-Mudur-2026  (PIN 8888)   — şube yöneticisi
  kasiyer / Demo-Kasa-2026 (PIN 7777)   — kasiyer
  garson / Demo-Garson-2026 (PIN 1111)  — garson
  asci / Demo-Mutfak-2026  (PIN 3333)   — mutfak
  depo / Demo-Depo-2026    (PIN 4444)   — stok
  platform / Demo-Platform-2026          — platform yöneticisi
  destek / Demo-Destek-2026              — teknik destek
"""
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core import roles
from apps.core.models import Branch, BranchSettings, Business, User

DEMO_USERS = [
    ("sahip", "Demo-Sahip-2026", "9999", roles.OWNER, "Ayşe", "Demir"),
    ("mudur", "Demo-Mudur-2026", "8888", roles.BRANCH_MANAGER, "Mehmet", "Kaya"),
    ("kasiyer", "Demo-Kasa-2026", "7777", roles.CASHIER, "Elif", "Şahin"),
    ("garson", "Demo-Garson-2026", "1111", roles.WAITER, "Can", "Yılmaz"),
    ("garson2", "Demo-Garson-2026", "2222", roles.WAITER, "Zeynep", "Arslan"),
    ("asci", "Demo-Mutfak-2026", "3333", roles.KITCHEN, "Hasan", "Çelik"),
    ("depo", "Demo-Depo-2026", "4444", roles.STOCK, "Murat", "Öztürk"),
]


class Command(BaseCommand):
    help = "Demo işletme, menü, masa, kullanıcı ve lisans oluşturur (yalnızca değerlendirme)"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="İşletme varken de çalıştır")

    @transaction.atomic
    def handle(self, *args, **o):
        from apps.catalog.models import Category, CustomerGroup, Option, OptionGroup, Product, Station, TaxRate
        from apps.inventory.models import RecipeLine, StockItem
        from apps.inventory.services import default_warehouse, manual_movement
        from apps.licensing.services import ensure_platform_keys, install_license, issue_license
        from apps.pos.models import Hall, Table
        from apps.printing.models import Printer

        if Business.objects.exists() and not o["force"]:
            raise CommandError("Veritabanında işletme var. Demo verisi yalnızca boş kurulumda oluşturulur (--force).")
        biz = Business.objects.create(name="DEMO Lokanta", slug="demo-lokanta", template="restaurant")
        branch = Branch.objects.create(business=biz, name="Merkez", code="MRK")
        BranchSettings.objects.create(branch=branch, receipt_header="DEMO Lokanta")
        users = {}
        for un, pw, pin, role, fn, ln in DEMO_USERS:
            u = User(username=un, first_name=fn, last_name=ln, business=biz, role=role,
                     branch=branch if role in roles.BRANCH_SCOPED_ROLES else None)
            u.set_password(pw)
            u.set_pin(pin)
            u.save()
            users[un] = u
        for un, pw, role in (("platform", "Demo-Platform-2026", roles.PLATFORM_ADMIN), ("destek", "Demo-Destek-2026", roles.SUPPORT)):
            u = User(username=un, role=role, first_name=un.title())
            u.set_password(pw)
            u.save()
        tax = TaxRate.objects.create(business=biz, name="KDV (DEMO oran)", rate=Decimal("10"))
        st = {n: Station.objects.create(business=biz, branch=branch, name=n, sort=i) for i, n in enumerate(["Ana Mutfak", "İçecek", "Tatlı"])}
        cats = {}
        for i, (n, s) in enumerate([("Çorbalar", "Ana Mutfak"), ("Ana Yemekler", "Ana Mutfak"), ("Salatalar", "Ana Mutfak"), ("Tatlılar", "Tatlı"), ("İçecekler", "İçecek")]):
            cats[n] = Category.objects.create(business=biz, name=n, station=st[s], tax_rate=tax, sort=i)
        size = OptionGroup.objects.create(business=biz, name="Porsiyon", kind="size", required=True, min_select=1, max_select=1)
        Option.objects.create(group=size, name="Normal", is_default=True)
        Option.objects.create(group=size, name="1,5 porsiyon", price_delta=Decimal("60"))
        cook = OptionGroup.objects.create(business=biz, name="Pişirme", kind="cooking", required=True, min_select=1, max_select=1)
        for n in ("Az", "Orta", "İyi"):
            Option.objects.create(group=cook, name=n, is_default=n == "Orta")
        extra = OptionGroup.objects.create(business=biz, name="Ekstralar", kind="extra", max_select=3)
        Option.objects.create(group=extra, name="Kaşar", price_delta=Decimal("25"))
        Option.objects.create(group=extra, name="Ekstra sos", price_delta=Decimal("10"))
        Option.objects.create(group=extra, name="Soğansız")
        demo = [("Mercimek Çorbası", "Çorbalar", 90, [], True), ("Ezogelin", "Çorbalar", 90, [], False),
                ("Izgara Köfte", "Ana Yemekler", 320, [size, cook, extra], True), ("Tavuk Şiş", "Ana Yemekler", 280, [size, extra], True),
                ("Kuru Fasulye", "Ana Yemekler", 190, [size], False), ("Çoban Salata", "Salatalar", 110, [extra], False),
                ("Sütlaç", "Tatlılar", 120, [], True), ("Künefe", "Tatlılar", 180, [], False),
                ("Ayran", "İçecekler", 45, [], True), ("Çay", "İçecekler", 25, [], True), ("Su", "İçecekler", 20, [], False)]
        products = {}
        for name, cat, price, groups, fav in demo:
            p = Product.objects.create(business=biz, category=cats[cat], name=name, base_price=Decimal(price), is_favorite=fav)
            p.option_groups.set(groups)
            products[name] = p
        wh = default_warehouse(branch)
        kiyma = StockItem.objects.create(business=biz, name="Kıyma (DEMO)", unit="kg", min_level=Decimal("2"), cost=Decimal("450"))
        sut = StockItem.objects.create(business=biz, name="Süt (DEMO)", unit="lt", min_level=Decimal("5"), cost=Decimal("35"))
        ayran = StockItem.objects.create(business=biz, name="Ayran şişe (DEMO)", unit="adet", min_level=Decimal("24"), cost=Decimal("15"),
                                         product=products["Ayran"])
        RecipeLine.objects.create(business=biz, product=products["Izgara Köfte"], item=kiyma, qty=Decimal("180"), unit="g")
        RecipeLine.objects.create(business=biz, product=products["Sütlaç"], item=sut, qty=Decimal("250"), unit="ml")
        for item, q in ((kiyma, 10), (sut, 20), (ayran, 60)):
            manual_movement(warehouse=wh, item=item, kind="opening", qty=q, user=users["depo"], reason="DEMO açılış stoku")
        CustomerGroup.objects.create(business=biz, name="Belediye personeli (DEMO)", discount_type="percent",
                                     discount_value=Decimal("20"), approver="cashier")
        for hi, (hn, n) in enumerate((("İç Salon", 12), ("Bahçe", 8))):
            hall = Hall.objects.create(business=biz, branch=branch, name=hn, sort=hi)
            for i in range(n):
                Table.objects.create(business=biz, branch=branch, hall=hall, name=f"{'B' if hi else ''}{i + 1}",
                                     x=20 + (i % 6) * 150, y=20 + (i // 6) * 150, seats=4 if i % 3 else 2)
        p = Printer.objects.create(business=biz, branch=branch, name="Mutfak (sanal)", connection="file", target="kitchen")
        p.stations.set([st["Ana Mutfak"], st["Tatlı"]])
        b = Printer.objects.create(business=biz, branch=branch, name="Bar (sanal)", connection="file", target="bar")
        b.stations.set([st["İçecek"]])
        Printer.objects.create(business=biz, branch=branch, name="Kasa (sanal)", connection="file", target="cashier", print_receipts=True)
        ensure_platform_keys()
        rec = issue_license(business=biz, package="enterprise", modules=[
            "stock", "crm", "delivery", "reservation", "staff", "finance", "reports_advanced", "jetmenu", "multi_branch"])
        install_license(biz, rec.signed_blob)
        self.stdout.write(self.style.SUCCESS("DEMO verisi oluşturuldu. Hesaplar bu komut dosyasının başındaki açıklamada."))
