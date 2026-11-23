/* Yönetim ekranları: katalog, stok, CRM, kurye, rezervasyon, personel, finans, raporlar, bildirimler. */
(function () {
  const { esc, h, qs, qsa, t, money } = J;
  const P = (J.pages = J.pages || {});
  const opt = (url, label = (x) => x.name, val = (x) => x.id) => async () => (await J.get(url)).map((x) => [val(x), label(x)]);
  const CHANNELS = [["table", "Masa"], ["delivery", "Teslimat"], ["takeaway", "Gel-al"], ["qr", "QR"]];

  // ================================================================== KATALOG
  P.catalog = async (main) => {
    main.appendChild(J.pageHead("Katalog", "Ürün, kategori, seçenek, fiyat, vergi ve kampanyalar"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const perm = "catalog.manage";
    J.tabs(c, [
      { key: "products", label: "Ürünler", render: (el) => J.crud(el, {
        title: "Ürün", endpoint: "products?all=1", perm, size: "max-w-3xl",
        columns: [{ key: "name", label: "Ürün", html: (r) => `<b>${esc(r.name)}</b>${r.is_favorite ? ` <span style="color:var(--accent-text)" title="Favori">${J.icon("star", 14)}</span>` : ""}${!r.is_active ? " " + J.badge("pasif", "var(--muted)") : ""}<div class="text-xs muted">${esc(r.sku || "")} ${esc(r.barcode || "")}</div>` },
          { key: "category_name", label: "Kategori" }, { key: "base_price", label: "Fiyat", right: true, fmt: money },
          { key: "effective_tax", label: "KDV %", right: true }, { key: "tax_included", label: "KDV dahil", html: (r) => J.yes(r.tax_included) }],
        fields: [{ name: "name", label: "Ad (TR)", required: true }, { name: "name_en", label: "Ad (EN)" },
          { name: "category", label: "Kategori", type: "select", required: true, options: opt("categories?all=1") },
          { name: "base_price", label: "Temel fiyat (TL)", type: "money", required: true },
          { name: "tax_rate", label: "KDV oranı (boşsa kategoriden)", type: "select", options: opt("tax-rates", (x) => `${x.name} %${x.rate}`) },
          { name: "tax_included", label: "Fiyata KDV dahil", type: "checkbox", default: true },
          { name: "station", label: "Mutfak istasyonu (boşsa kategoriden)", type: "select", options: opt("stations") },
          { name: "option_groups", label: "Seçenek grupları", type: "multiselect", options: opt("option-groups") },
          { name: "sku", label: "Ürün kodu" }, { name: "barcode", label: "Barkod" },
          { name: "stock_policy", label: "Stok yoksa", type: "select", required: true, options: [["inherit", "Şube ayarı"], ["warn", "Uyar, sat"], ["block", "Satışı engelle"]], default: "inherit" },
          { name: "sort", label: "Sıra", type: "number", default: 0 }, { name: "is_favorite", label: "Favori (hızlı erişim)", type: "checkbox" },
          { name: "is_active", label: "Aktif", type: "checkbox", default: true }, { name: "description", label: "Açıklama", type: "textarea" }],
        deleteLabel: "Pasifleştir",
        actions: [{ label: "Fiyat geçmişi", run: async (r) => { const hist = await J.get(`products/${r.id}/history`); J.modal({ title: `${r.name} — fiyat geçmişi`, size: "max-w-2xl", body: J.table([{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "scope", label: "Kapsam" }, { key: "old_price", label: "Eski", right: true, fmt: (v) => (v === null ? "—" : money(v)) }, { key: "new_price", label: "Yeni", right: true, fmt: money }, { key: "user_name", label: "Kullanıcı" }], hist) }); } },
          { label: "Görsel", show: () => J.can(perm), run: async (r, reload) => {
            const inp = h(`<input type="file" accept="image/*">`);
            inp.onchange = async () => { const fd = new FormData(); fd.append("image", inp.files[0]); try { await J.api("PATCH", `products/${r.id}`, fd); J.toast("Görsel yüklendi", "ok"); reload(); } catch (e) { J.err(e); } };
            inp.click();
          } }],
      }) },
      { key: "categories", label: "Kategoriler", render: (el) => J.crud(el, {
        title: "Kategori", endpoint: "categories?all=1", perm,
        columns: [{ key: "name", label: "Kategori" }, { key: "product_count", label: "Ürün", right: true }, { key: "sort", label: "Sıra", right: true }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }],
        fields: [{ name: "name", label: "Ad (TR)", required: true }, { name: "name_en", label: "Ad (EN)" }, { name: "parent", label: "Üst kategori", type: "select", options: opt("categories?all=1") },
          { name: "tax_rate", label: "KDV oranı", type: "select", options: opt("tax-rates", (x) => `${x.name} %${x.rate}`) }, { name: "station", label: "Mutfak istasyonu (KDS yönlendirme)", type: "select", options: opt("stations") },
          { name: "color", label: "Renk", type: "color" }, { name: "sort", label: "Sıra", type: "number", default: 0 }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }],
        deleteLabel: "Pasifleştir",
      }) },
      { key: "options", label: "Seçenek grupları", render: (el) => J.crud(el, {
        title: "Seçenek grubu", endpoint: "option-groups", perm, size: "max-w-2xl",
        columns: [{ key: "name", label: "Grup" }, { key: "kind", label: "Tür" }, { key: "required", label: "Zorunlu", html: (r) => J.yes(r.required) }, { key: "min_select", label: "Min", right: true }, { key: "max_select", label: "Max", right: true }, { key: "options", label: "Seçenekler", fmt: (v) => v.map((o) => `${o.name}${Number(o.price_delta) ? ` (+${o.price_delta})` : ""}`).join(", ") }],
        fields: [{ name: "name", label: "Grup adı", required: true }, { name: "kind", label: "Tür", type: "select", required: true, options: [["size", "Boyut"], ["cooking", "Pişirme"], ["sauce", "Sos"], ["extra", "Ekstra"], ["side", "Ek ürün"], ["other", "Diğer"]] },
          { name: "required", label: "Zorunlu", type: "checkbox" }, { name: "min_select", label: "En az seçim", type: "number", default: 0 }, { name: "max_select", label: "En fazla seçim", type: "number", default: 1 },
          { name: "options_text", label: "Seçenekler — her satır: Ad;ek fiyat;varsayılan(1/0)  ör. 'Büyük;15;0'", type: "textarea", rows: 6, wide: true }],
        toForm: (r) => ({ ...r, options_text: r.options.map((o) => `${o.name};${o.price_delta};${o.is_default ? 1 : 0}`).join("\n") }),
        toApi: (v, row) => {
          const lines = (v.options_text || "").split("\n").map((s) => s.trim()).filter(Boolean);
          const prev = row?.options || [];
          v.options = lines.map((s, i) => { const [name, price, def] = s.split(";"); const old = prev.find((o) => o.name === name.trim()); return { ...(old ? { id: old.id } : {}), name: name.trim(), price_delta: Number(price || 0), is_default: def === "1", sort: i }; });
          delete v.options_text; return v;
        },
      }) },
      { key: "prices", label: "Kanal/şube fiyatları", render: (el) => J.crud(el, {
        title: "Özel fiyat", endpoint: "product-prices", perm,
        columns: [{ key: "product_name", label: "Ürün" }, { key: "channel", label: "Kanal", fmt: (v) => (CHANNELS.find((c) => c[0] === v) || [, "Tümü"])[1] }, { key: "branch", label: "Şube", fmt: (v) => v || "Tümü" }, { key: "customer_group", label: "Müşteri grubu", fmt: (v) => v || "—" }, { key: "price", label: "Fiyat", right: true, fmt: money }, { key: "valid_from", label: "Başlangıç", fmt: J.dt }, { key: "valid_to", label: "Bitiş", fmt: J.dt }],
        fields: [{ name: "product", label: "Ürün", type: "select", required: true, options: opt("products?all=1") }, { name: "channel", label: "Kanal", type: "select", options: CHANNELS },
          { name: "branch", label: "Şube", type: "select", options: opt("branches") }, { name: "customer_group", label: "Müşteri grubu", type: "select", options: opt("customer-groups") },
          { name: "price", label: "Fiyat", type: "money", required: true }, { name: "valid_from", label: "Geçerlilik başlangıcı (zamanlanmış fiyat)", type: "datetime" }, { name: "valid_to", label: "Geçerlilik bitişi", type: "datetime" }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }],
        toApi: (v) => ({ ...v, channel: v.channel || "" }),
      }) },
      { key: "campaigns", label: "Kampanyalar", render: (el) => J.crud(el, {
        title: "Kampanya", endpoint: "campaigns", perm, size: "max-w-3xl",
        columns: [{ key: "name", label: "Kampanya" }, { key: "kind", label: "Tür" }, { key: "value", label: "Değer", right: true }, { key: "priority", label: "Öncelik", right: true }, { key: "used_count", label: "Kullanım", right: true, fmt: (v, r) => `${v}${r.usage_limit ? "/" + r.usage_limit : ""}` }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }],
        fields: [{ name: "name", label: "Ad", required: true }, { name: "kind", label: "Tür", type: "select", required: true, options: [["percent", "Yüzde indirim"], ["fixed", "Sabit indirim (birim)"], ["buy_x_get_y", "X al Y bedava / 2. ürün"], ["bundle_price", "Combo/menü paketi fiyatı"]] },
          { name: "value", label: "Değer (% / TL / bedava ürün indirim %)", type: "money", required: true }, { name: "buy_qty", label: "Al (X)", type: "number", default: 1 }, { name: "get_qty", label: "Bedava (Y)", type: "number", default: 1 },
          { name: "products", label: "Ürünler", type: "multiselect", options: opt("products") }, { name: "categories", label: "Kategoriler", type: "multiselect", options: opt("categories") },
          { name: "customer_groups", label: "Müşteri grupları", type: "multiselect", options: opt("customer-groups") },
          { name: "channels", label: "Kanallar", type: "multiselect", options: CHANNELS },
          { name: "weekdays", label: "Günler (boş = her gün)", type: "multiselect", options: [[0, "Pazartesi"], [1, "Salı"], [2, "Çarşamba"], [3, "Perşembe"], [4, "Cuma"], [5, "Cumartesi"], [6, "Pazar"]] },
          { name: "start_time", label: "Başlangıç saati", type: "time" }, { name: "end_time", label: "Bitiş saati", type: "time" },
          { name: "valid_from", label: "Başlangıç tarihi", type: "date" }, { name: "valid_to", label: "Bitiş tarihi", type: "date" },
          { name: "usage_limit", label: "Kullanım limiti", type: "number" }, { name: "priority", label: "Çakışma önceliği (büyük kazanır)", type: "number", default: 0 }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }],
        toApi: (v) => { ["start_time", "end_time", "valid_from", "valid_to", "usage_limit"].forEach((k) => { if (v[k] === "") v[k] = null; }); return v; },
      }) },
      { key: "taxes", label: "Vergi oranları", render: (el) => J.crud(el, { title: "Vergi oranı", endpoint: "tax-rates", perm, columns: [{ key: "name", label: "Ad" }, { key: "rate", label: "Oran %", right: true }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }], fields: [{ name: "name", label: "Ad", required: true }, { name: "rate", label: "Oran (%)", type: "money", required: true }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
      { key: "stations", label: "Mutfak istasyonları", render: (el) => J.crud(el, { title: "İstasyon", endpoint: "stations", perm, columns: [{ key: "name", label: "İstasyon" }, { key: "sort", label: "Sıra", right: true }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }], fields: [{ name: "name", label: "Ad (ana mutfak, içecek, tatlı…)", required: true }, { name: "sort", label: "Sıra", type: "number", default: 0 }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
      { key: "groups", label: "Müşteri grupları", render: (el) => J.crud(el, { title: "Müşteri grubu", endpoint: "customer-groups", perm, columns: [{ key: "name", label: "Grup" }, { key: "discount_type", label: "Tür" }, { key: "discount_value", label: "Değer", right: true }, { key: "max_discount", label: "Üst limit", right: true }, { key: "approver", label: "Onaylayan" }], fields: [{ name: "name", label: "Ad", required: true }, { name: "discount_type", label: "İndirim türü", type: "select", required: true, options: [["percent", "Yüzde"], ["fixed", "Sabit"]] }, { name: "discount_value", label: "Değer", type: "money", required: true }, { name: "max_discount", label: "Üst limit (TL)", type: "money" }, { name: "approver", label: "Onay", type: "select", required: true, options: [["cashier", "Kasiyer onayı"], ["manager", "Yönetici onayı"]] }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
    ]);
  };

  // ================================================================== STOK
  P.stock = async (main) => {
    if (!J.hasModule("stock")) return main.appendChild(h(`<div class="card p-8">Stok modülü lisansınızda etkin değil.</div>`));
    main.appendChild(J.pageHead("Stok ve depo", "Reçete, satın alma, transfer, sayım ve fire"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const perm = "stock.manage";
    const items = opt("stock/items", (x) => `${x.name} (${x.unit})`);
    J.tabs(c, [
      { key: "overview", label: "Genel bakış", render: async (el) => {
        const d = await J.get("stock/overview");
        const cards = [["Kalem", d.cards.items], ["Düşük stok", d.cards.low], ["Tükenen", d.cards.out], ["Stok değeri", money(d.cards.value)], ["Bugünkü hareket", d.cards.movements_today], ["Haftalık fire", money(d.cards.waste_week)]];
        el.appendChild(h(`<div class="grid grid-cols-2 md:grid-cols-6 gap-3 mb-4">${cards.map(([l, v]) => `<div class="card p-4"><div class="text-xs muted">${l}</div><div class="text-xl font-bold">${v}</div></div>`).join("")}</div>`));
        const box = h(`<div class="card"><div class="p-3 border-b bd font-semibold">${esc(d.warehouse.name)}</div></div>`);
        box.appendChild(J.table([{ key: "name", label: "Malzeme" }, { key: "qty", label: "Miktar", right: true, fmt: (v, r) => `${J.num(v, 3)} ${r.unit}` }, { key: "min_level", label: "Min", right: true, fmt: (v) => J.num(v, 3) }, { key: "cost", label: "Birim maliyet", right: true, fmt: money }, { key: "value", label: "Değer", right: true, fmt: money }, { key: "state", label: "Durum", html: (r) => r.state === "ok" ? J.badge("Normal", "var(--ok)") : r.state === "low" ? J.badge("Düşük", "var(--warn)") : J.badge("Tükendi", "var(--bad)") }, { key: "supplier", label: "Tedarikçi" }], d.rows, {
          actions: J.can(perm) ? [{ label: "Hareket", run: async (r) => {
            const v = await J.promptForm(`${r.name} — stok hareketi`, [{ name: "kind", label: "Tür", type: "select", required: true, options: [["waste", "Fire (düşüş)"], ["adjust", "Düzeltme (+/−)"], ["opening", "Açılış stoku"]] }, { name: "qty", label: `Miktar (${r.unit})`, type: "number", step: "0.001", required: true }, { name: "reason", label: "Gerekçe", required: true, minLength: 3 }]);
            if (v) { await J.post(`stock/items/${r.id}/move`, v).catch(J.err); J.toast("Hareket kaydedildi", "ok"); }
          } }] : null }));
        el.appendChild(box);
      } },
      { key: "items", label: "Malzemeler", render: (el) => J.crud(el, { title: "Malzeme", endpoint: "stock/items", perm, columns: [{ key: "name", label: "Ad" }, { key: "unit", label: "Birim" }, { key: "min_level", label: "Min", right: true }, { key: "cost", label: "Maliyet", right: true, fmt: money }], fields: [{ name: "name", label: "Ad", required: true }, { name: "unit", label: "Birim", type: "select", required: true, options: [["adet", "Adet"], ["kg", "Kilogram"], ["g", "Gram"], ["lt", "Litre"], ["ml", "Mililitre"], ["porsiyon", "Porsiyon"]] }, { name: "min_level", label: "Minimum seviye (uyarı)", type: "number", step: "0.001", default: 0 }, { name: "cost", label: "Birim maliyet", type: "money", default: 0 }, { name: "product", label: "Doğrudan stoklu ürün (ör. şişe içecek)", type: "select", options: opt("products") }, { name: "supplier", label: "Tedarikçi", type: "select", options: opt("stock/suppliers") }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
      { key: "recipes", label: "Reçeteler", render: (el) => J.crud(el, { title: "Reçete satırı", endpoint: "stock/recipes", perm: "stock.manage", columns: [{ key: "product", label: "Ürün", fmt: (v) => "#" + v }, { key: "item_name", label: "Malzeme" }, { key: "qty", label: "Miktar", right: true, fmt: (v, r) => `${J.num(v, 4)} ${r.unit}` }], fields: [{ name: "product", label: "Ürün", type: "select", required: true, options: opt("products") }, { name: "item", label: "Malzeme", type: "select", required: true, options: items }, { name: "qty", label: "Porsiyon başı miktar", type: "number", step: "0.0001", required: true }, { name: "unit", label: "Birim (otomatik dönüşüm g↔kg, ml↔lt)", type: "select", required: true, options: [["adet", "Adet"], ["kg", "kg"], ["g", "g"], ["lt", "lt"], ["ml", "ml"], ["porsiyon", "Porsiyon"]] }] }) },
      { key: "purchases", label: "Mal kabul", render: async (el) => {
        if (J.can(perm)) {
          const b = h(`<button class="btn btn-primary mb-3">+ Mal kabul (satın alma girişi)</button>`);
          b.onclick = async () => {
            const v = await J.promptForm("Mal kabul", [{ name: "supplier", label: "Tedarikçi", type: "select", options: opt("stock/suppliers") }, { name: "document_no", label: "İrsaliye/fatura no" },
              { name: "lines_text", label: "Satırlar — her satır: malzeme ID;miktar;birim maliyet", type: "textarea", rows: 5, required: true, help: "Malzeme ID'leri Malzemeler sekmesinde. Ör: 3;10;42,50" }, { name: "note", label: "Not" }], { size: "max-w-2xl" });
            if (!v) return;
            const lines = v.lines_text.split("\n").filter(Boolean).map((s) => { const [item, qty, cost] = s.split(";"); return { item: Number(item), qty: qty.replace(",", "."), unit_cost: (cost || "0").replace(",", ".") }; });
            await J.post("stock/purchases", { supplier: v.supplier, document_no: v.document_no, note: v.note, lines }).then(() => J.toast("Stok girişi yapıldı", "ok")).catch(J.err);
          };
          el.appendChild(b);
        }
        const rows = await J.get("stock/purchases");
        el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "supplier", label: "Tedarikçi" }, { key: "document_no", label: "Belge" }, { key: "lines", label: "Satırlar", fmt: (v) => v.map((l) => `${l.item} ${J.num(l.qty, 3)}`).join(", ") }, { key: "total", label: "Toplam", right: true, fmt: money }, { key: "user", label: "Kullanıcı" }], rows));
      } },
      { key: "transfers", label: "Transfer", render: async (el) => {
        if (J.can(perm)) {
          const b = h(`<button class="btn btn-primary mb-3">+ Depolar arası transfer</button>`);
          b.onclick = async () => {
            const wh = opt("stock/warehouses");
            const v = await J.promptForm("Transfer", [{ name: "source", label: "Kaynak depo", type: "select", required: true, options: wh }, { name: "target", label: "Hedef depo", type: "select", required: true, options: wh }, { name: "item", label: "Malzeme", type: "select", required: true, options: items }, { name: "qty", label: "Miktar", type: "number", step: "0.001", required: true }, { name: "note", label: "Not" }]);
            if (v) await J.post("stock/transfers", { source: v.source, target: v.target, note: v.note, lines: [{ item: v.item, qty: v.qty }] }).then(() => J.toast("Transfer yapıldı", "ok")).catch(J.err);
          };
          el.appendChild(b);
        }
        el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "source", label: "Kaynak" }, { key: "target", label: "Hedef" }, { key: "lines", label: "Satırlar", fmt: (v) => v.map((l) => `${l.item} ${J.num(l.qty, 3)}`).join(", ") }, { key: "user", label: "Kullanıcı" }], await J.get("stock/transfers")));
      } },
      { key: "counts", label: "Sayım", render: async (el) => {
        const render = async () => {
          el.innerHTML = "";
          if (J.can(perm)) {
            const b = h(`<button class="btn btn-primary mb-3">+ Yeni sayım</button>`);
            b.onclick = async () => {
              const ov = await J.get("stock/overview");
              const form = h(`<div class="space-y-2 max-h-[60vh] overflow-y-auto">${ov.rows.map((r) => `<label class="flex items-center gap-2"><span class="flex-1">${esc(r.name)} <span class="muted text-xs">sistem: ${J.num(r.qty, 3)} ${r.unit}</span></span><input class="input !w-32" type="number" step="0.001" data-i="${r.id}" placeholder="sayılan"></label>`).join("")}</div>`);
              J.modal({ title: "Stok sayımı", body: form, size: "max-w-2xl", actions: [{ label: "İptal" }, { label: "Taslak kaydet", cls: "btn-primary", run: async () => {
                const lines = qsa("[data-i]", form).filter((i) => i.value !== "").map((i) => ({ item: Number(i.dataset.i), counted: i.value }));
                await J.post("stock/counts", { lines }); render();
              } }] });
            };
            el.appendChild(b);
          }
          const rows = await J.get("stock/counts");
          el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "warehouse", label: "Depo" }, { key: "status", label: "Durum" }, { key: "lines", label: "Farklar", fmt: (v) => v.filter((l) => Number(l.diff)).map((l) => `${l.item}: ${J.num(l.diff, 3)}`).join(", ") || "—" }], rows, {
            actions: J.can(perm) ? [{ label: "Uygula", show: (r) => r.status === "draft", run: async (r) => { if (await J.confirm("Sayım farkları stoğa işlensin mi?")) { await J.post("stock/counts", { apply_id: r.id }).catch(J.err); render(); } } }] : null }));
        };
        render();
      } },
      { key: "movements", label: "Hareketler", render: (el) => J.crud(el, { title: "Hareket", endpoint: "stock/movements", columns: [{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "item_name", label: "Malzeme" }, { key: "kind_label", label: "Tür" }, { key: "qty", label: "Miktar", right: true, fmt: (v) => J.num(v, 4) }, { key: "before", label: "Önceki", right: true, fmt: (v) => J.num(v, 3) }, { key: "after", label: "Sonraki", right: true, fmt: (v) => J.num(v, 3) }, { key: "reason", label: "Gerekçe" }, { key: "user_name", label: "Kullanıcı" }] }) },
      { key: "warehouses", label: "Depolar", render: (el) => J.crud(el, { title: "Depo", endpoint: "stock/warehouses", perm, columns: [{ key: "name", label: "Depo" }, { key: "is_default", label: "Varsayılan", html: (r) => J.yes(r.is_default) }], fields: [{ name: "name", label: "Ad", required: true }, { name: "is_default", label: "Varsayılan (satış düşümü)", type: "checkbox" }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
      { key: "suppliers", label: "Tedarikçiler", render: (el) => J.crud(el, { title: "Tedarikçi", endpoint: "stock/suppliers", perm, columns: [{ key: "name", label: "Ad" }, { key: "phone", label: "Telefon" }, { key: "email", label: "E-posta" }, { key: "tax_number", label: "Vergi no" }], fields: [{ name: "name", label: "Ad", required: true }, { name: "phone", label: "Telefon" }, { name: "email", label: "E-posta", type: "email" }, { name: "tax_number", label: "Vergi no" }, { name: "address", label: "Adres", type: "textarea" }, { name: "note", label: "Not", type: "textarea" }], deleteLabel: "Pasifleştir" }) },
    ]);
  };

  // ================================================================== CRM
  P.customers = async (main) => {
    if (!J.hasModule("crm")) return main.appendChild(h(`<div class="card p-8">CRM modülü lisansınızda etkin değil.</div>`));
    main.appendChild(J.pageHead("Müşteriler", "Temel müşteri kaydı, sipariş geçmişi, açık hesap. Kişisel veri erişimi denetim kaydına yazılır (KVKK)."));
    J.crud(main, {
      title: "Müşteri", endpoint: "customers", perm: "crm.manage",
      columns: [{ key: "name", label: "Ad" }, { key: "phone", label: "Telefon" }, { key: "visit_count", label: "Ziyaret", right: true }, { key: "total_spent", label: "Harcama", right: true, fmt: money }, { key: "balance", label: "Açık hesap", right: true, html: (r) => Number(r.balance) ? `<b style="color:var(--bad)">${money(r.balance)}</b>` : "—" }, { key: "kvkk_consent", label: "KVKK rıza", html: (r) => J.yes(r.kvkk_consent) }],
      fields: [{ name: "name", label: "Ad soyad", required: true }, { name: "phone", label: "Telefon", required: true }, { name: "email", label: "E-posta", type: "email" }, { name: "address", label: "Adres", type: "textarea" }, { name: "note", label: "Not", type: "textarea" }, { name: "kvkk_consent", label: "Kişisel veri işleme açık rızası alındı", type: "checkbox" }],
      deletable: false,
      actions: [
        { label: "Geçmiş", run: async (r) => { const d = await J.get(`customers/${r.id}/history`); const b = h(`<div><div class="grid grid-cols-3 gap-3 mb-3 text-sm"><div class="card p-3">Ziyaret <b>${d.visits}</b></div><div class="card p-3">Harcama <b>${money(d.total_spent)}</b></div><div class="card p-3">Bakiye <b>${money(d.balance)}</b></div></div></div>`); b.appendChild(J.table([{ key: "date", label: "Tarih", fmt: J.dt }, { key: "number", label: "No" }, { key: "items", label: "Ürünler", fmt: (v) => v.join(", ") }, { key: "total", label: "Tutar", right: true, fmt: money }], d.tickets)); J.modal({ title: r.name, body: b, size: "max-w-3xl" }); } },
        { label: "Tahsilat", show: (r) => Number(r.balance) > 0, run: async (r, reload) => { const v = await J.promptForm(`Açık hesap tahsilatı — ${r.name}`, [{ name: "amount", label: "Tutar", type: "money", required: true, default: r.balance }, { name: "method", label: "Yöntem", type: "select", required: true, options: [["cash", "Nakit"], ["card", "Kart"]] }, { name: "note", label: "Not" }]); if (v) { await J.post(`customers/${r.id}/collect`, v).catch(J.err); reload(); } } },
        { label: "KVKK dışa aktar", run: async (r) => { const d = await J.get(`customers/${r.id}/kvkk_export`); const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `kvkk_${r.id}.json`; a.click(); } },
        { label: "Anonimleştir (sil)", run: async (r, reload) => { const v = await J.askReason(`${r.name} — kişisel verileri anonimleştir`); if (v) { await J.post(`customers/${r.id}/anonymize`, v).catch(J.err); reload(); } } },
      ],
    });
  };

  // ================================================================== KURYE
  P.deliveries = async (main) => {
    if (!J.hasModule("delivery")) return main.appendChild(h(`<div class="card p-8">Kurye modülü lisansınızda etkin değil.</div>`));
    main.appendChild(J.pageHead("Kurye ve teslimat", "Atama, durum takibi, gecikme uyarısı ve performans. Canlı GPS takibi kapsam dışıdır."));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const FLOW = { preparing: "waiting_courier", waiting_courier: "on_the_way", on_the_way: "delivered" };
    J.tabs(c, [
      { key: "active", label: "Aktif teslimatlar", render: async (el) => {
        const nb = h(`<button class="btn btn-primary mb-3">+ Yeni teslimat siparişi</button>`);
        nb.onclick = async () => {
          const v = await J.promptForm("Teslimat", [{ name: "customer", label: "Kayıtlı müşteri", type: "select", options: J.hasModule("crm") ? opt("customers", (x) => `${x.name} · ${x.phone}`) : [] }, { name: "contact_name", label: "Ad" }, { name: "phone", label: "Telefon" }, { name: "address", label: "Adres", type: "textarea" }, { name: "fee", label: "Teslimat ücreti", type: "money", default: 0 }, { name: "payment_note", label: "Ödeme (kapıda nakit/kart…)" }, { name: "promised_minutes", label: "Söz verilen süre (dk)", type: "number", default: 45 }]);
          if (!v) return;
          const d = await J.post("deliveries", v).catch(J.err);
          if (d) J.go(`/ticket/${d.ticket}`);
        };
        el.appendChild(nb);
        const couriers = await J.get("couriers").catch(() => []);
        const rows = await J.get("deliveries?active=1");
        el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "ticket_number", label: "No", html: (r) => `<a class="underline" data-link href="/ticket/${r.ticket}">#${r.ticket_number}</a>` }, { key: "contact_name", label: "Müşteri" }, { key: "address", label: "Adres" }, { key: "courier_name", label: "Kurye" }, { key: "status_label", label: "Durum", html: (r) => J.badge(r.status_label, r.late ? "var(--bad)" : "var(--info)") }, { key: "minutes", label: "Süre", right: true, fmt: (v, r) => `${v}/${r.promised_minutes} dk` }, { key: "ticket_total", label: "Tutar", right: true, fmt: money }], rows, {
          actions: [
            { label: "Kurye ata", run: async (r) => { const v = await J.promptForm("Kurye ata / değiştir", [{ name: "courier", label: "Kurye", type: "select", required: true, options: couriers.filter((x) => x.is_active).map((x) => [x.id, x.name]) }]); if (v) { await J.post(`deliveries/${r.id}/status`, v).catch(J.err); J.go("/deliveries"); } } },
            { label: "Sonraki adım →", show: (r) => FLOW[r.status], run: async (r) => { await J.post(`deliveries/${r.id}/status`, { status: FLOW[r.status] }).catch(J.err); J.go("/deliveries"); } },
            { label: "İptal", show: (r) => ["preparing", "waiting_courier"].includes(r.status), run: async (r) => { if (await J.confirm("Teslimat iptal edilsin mi?", { danger: true })) { await J.post(`deliveries/${r.id}/status`, { status: "cancelled" }).catch(J.err); J.go("/deliveries"); } } }] }));
      } },
      { key: "couriers", label: "Kuryeler", render: (el) => J.crud(el, { title: "Kurye", endpoint: "couriers", perm: "delivery.manage", columns: [{ key: "name", label: "Ad" }, { key: "phone", label: "Telefon" }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }], fields: [{ name: "name", label: "Ad", required: true }, { name: "phone", label: "Telefon" }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" }) },
      { key: "perf", label: "Performans", render: async (el) => el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "courier", label: "Kurye" }, { key: "count", label: "Teslimat", right: true }, { key: "avg_minutes", label: "Ort. süre (dk)", right: true }, { key: "late", label: "Geciken", right: true }, { key: "fees", label: "Ücret", right: true, fmt: money }], await J.get("deliveries/performance"))) },
    ]);
  };

  // ================================================================== REZERVASYON
  P.reservations = async (main) => {
    if (!J.hasModule("reservation")) return main.appendChild(h(`<div class="card p-8">Rezervasyon modülü lisansınızda etkin değil.</div>`));
    let date = J.today();
    main.appendChild(J.pageHead("Rezervasyonlar", "Kapasite, bekleme listesi, masa eşleme ve adisyona dönüştürme", `<input type="date" class="input !w-auto" value="${date}" data-d>`));
    const box = h(`<div></div>`);
    main.appendChild(box);
    const tables = async () => (await J.get("tables")).map((x) => [x.id, `${x.name} (${x.seats} kişi)`]);
    const load = () => { box.innerHTML = ""; J.crud(box, {
      title: "Rezervasyon", endpoint: `reservations?date=${date}`, perm: "reservation.manage",
      columns: [{ key: "starts_at", label: "Saat", fmt: J.dt }, { key: "name", label: "Ad" }, { key: "phone", label: "Telefon" }, { key: "party_size", label: "Kişi", right: true }, { key: "table_name", label: "Masa" }, { key: "status_label", label: "Durum", html: (r) => J.badge(r.status_label, r.status === "waitlist" ? "var(--warn)" : r.status === "seated" ? "var(--ok)" : "var(--info)") }, { key: "note", label: "Not" }],
      fields: [{ name: "name", label: "Müşteri adı", required: true }, { name: "phone", label: "Telefon", required: true }, { name: "starts_at", label: "Tarih-saat", type: "datetime", required: true }, { name: "party_size", label: "Kişi sayısı", type: "number", required: true, default: 2 }, { name: "duration_minutes", label: "Süre (dk)", type: "number", default: 120 }, { name: "table", label: "Masa", type: "select", options: tables }, { name: "status", label: "Durum", type: "select", required: true, options: [["pending", "Beklemede"], ["confirmed", "Onaylandı"], ["waitlist", "Bekleme listesi"]], default: "confirmed" }, { name: "remind_minutes_before", label: "Hatırlatma (dk önce)", type: "number", default: 60 }, { name: "note", label: "Not", type: "textarea" }],
      deletable: false,
      actions: [{ label: "Masaya al → adisyon", show: (r) => ["pending", "confirmed", "waitlist"].includes(r.status), run: async (r) => { const d = await J.post(`reservations/${r.id}/seat`).catch(J.err); if (d) J.go(`/ticket/${d.ticket}`); } },
        { label: "Gelmedi", show: (r) => ["pending", "confirmed"].includes(r.status), run: async (r, reload) => { await J.post(`reservations/${r.id}/set_status`, { status: "no_show" }).catch(J.err); reload(); } },
        { label: "İptal", show: (r) => ["pending", "confirmed", "waitlist"].includes(r.status), run: async (r, reload) => { await J.post(`reservations/${r.id}/set_status`, { status: "cancelled" }).catch(J.err); reload(); } }],
    }); };
    qs("[data-d]", main).onchange = (e) => { date = e.target.value; load(); };
    load();
  };

  // ================================================================== PERSONEL
  P.staff = async (main) => {
    if (!J.hasModule("staff")) return main.appendChild(h(`<div class="card p-8">Personel modülü lisansınızda etkin değil.</div>`));
    main.appendChild(J.pageHead("Personel", "Vardiya, giriş-çıkış, mola, geç kalma, devamsızlık, fazla mesai, izin ve performans"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const users = opt("users?active=1", (x) => `${x.first_name || x.username} ${x.last_name || ""} (${x.role_label})`);
    J.tabs(c, [
      { key: "shifts", label: "Vardiyalar", render: (el) => J.crud(el, { title: "Vardiya", endpoint: "staff/shifts", perm: "staff.manage", columns: [{ key: "user_name", label: "Personel" }, { key: "starts_at", label: "Başlangıç", fmt: J.dt }, { key: "ends_at", label: "Bitiş", fmt: J.dt }, { key: "break_minutes", label: "Mola", right: true }, { key: "note", label: "Not" }], fields: [{ name: "user", label: "Personel", type: "select", required: true, options: users }, { name: "starts_at", label: "Başlangıç", type: "datetime", required: true }, { name: "ends_at", label: "Bitiş", type: "datetime", required: true }, { name: "break_minutes", label: "Mola (dk)", type: "number", default: 30 }, { name: "note", label: "Not" }] }) },
      { key: "attendance", label: "Giriş-çıkış", render: async (el) => {
        el.appendChild(h(`<div class="card mb-3"></div>`)).appendChild(J.table([{ key: "user_name", label: "Personel" }, { key: "clock_in", label: "Giriş", fmt: J.dt }, { key: "clock_out", label: "Çıkış", fmt: J.dt }, { key: "break_minutes", label: "Mola", right: true }, { key: "late_minutes", label: "Geç kalma", right: true }, { key: "overtime_minutes", label: "Fazla mesai", right: true }], await J.get("staff/attendance")));
        const abs = await J.get("staff/attendance/absences");
        el.appendChild(h(`<div class="card p-3"><h3 class="font-semibold mb-2">Bugün devamsız</h3>${abs.length ? abs.map((a) => `<div>${esc(a.user)} — vardiya ${J.dt(a.shift_start)}</div>`).join("") : '<div class="muted">Yok</div>'}</div>`));
      } },
      { key: "leaves", label: "İzinler", render: (el) => J.crud(el, { title: "İzin", endpoint: "staff/leaves", perm: "staff.manage", columns: [{ key: "user_name", label: "Personel" }, { key: "kind", label: "Tür" }, { key: "start_date", label: "Başlangıç", fmt: J.d }, { key: "end_date", label: "Bitiş", fmt: J.d }, { key: "status_label", label: "Durum" }, { key: "note", label: "Not" }], fields: [{ name: "user", label: "Personel", type: "select", required: true, options: users }, { name: "kind", label: "Tür", type: "select", required: true, options: [["annual", "Yıllık"], ["sick", "Rapor"], ["unpaid", "Ücretsiz"], ["other", "Diğer"]] }, { name: "start_date", label: "Başlangıç", type: "date", required: true }, { name: "end_date", label: "Bitiş", type: "date", required: true }, { name: "note", label: "Not" }], actions: [{ label: "Onayla", show: (r) => r.status === "pending", run: async (r, reload) => { await J.post(`staff/leaves/${r.id}/decide`, { approve: true }); reload(); } }, { label: "Reddet", show: (r) => r.status === "pending", run: async (r, reload) => { await J.post(`staff/leaves/${r.id}/decide`, { approve: false }); reload(); } }] }) },
      { key: "perf", label: "Performans", render: async (el) => el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "user", label: "Personel" }, { key: "tickets", label: "Adisyon", right: true }, { key: "sales", label: "Satış", right: true, fmt: money }, { key: "avg_ticket", label: "Ortalama", right: true, fmt: money }, { key: "voids", label: "İptal", right: true }, { key: "hours", label: "Çalışma (sa)", right: true }, { key: "late_minutes", label: "Geç (dk)", right: true }, { key: "overtime_minutes", label: "Fazla mesai (dk)", right: true }], await J.get("staff/attendance/performance"))) },
    ]);
  };

  P.timeclock = async (main) => {
    main.appendChild(J.pageHead("Giriş/Çıkış", "Vardiya giriş, mola ve çıkış kaydınız"));
    const box = h(`<div class="card p-6 max-w-md"></div>`);
    main.appendChild(box);
    const load = async () => {
      const a = await J.get("staff/timeclock");
      box.innerHTML = a ? `<p class="mb-1">Giriş: <b>${J.dt(a.clock_in)}</b></p><p class="mb-4 muted text-sm">${a.break_started_at ? "Moladasınız" : "Çalışıyorsunuz"} · geç kalma ${a.late_minutes} dk · mola ${a.break_minutes} dk</p>` : `<p class="mb-4">Şu an giriş yapılmamış.</p>`;
      const acts = a ? [["break", a.break_started_at ? "Moladan dön" : "Molaya çık", "btn-ghost"], ["out", "Çıkış yap", "btn-danger"]] : [["in", "Giriş yap", "btn-primary"]];
      acts.forEach(([k, l, c]) => { const b = h(`<button class="btn ${c} btn-lg mr-2">${l}</button>`); b.onclick = () => J.post("staff/timeclock", { action: k }).then(load).catch(J.err); box.appendChild(b); });
    };
    await load();
  };

  // ================================================================== FİNANS
  P.finance = async (main) => {
    if (!J.hasModule("finance")) return main.appendChild(h(`<div class="card p-8">Finans modülü lisansınızda etkin değil.</div>`));
    main.appendChild(J.pageHead("Finans", "Gelir-gider, cari borç/alacak ve kârlılık. Kayıtlar silinmez; ters kayıtla düzeltilir."));
    const c = h(`<div></div>`);
    main.appendChild(c);
    J.tabs(c, [
      { key: "entries", label: "Kayıtlar", render: (el) => J.crud(el, { title: "Finans kaydı", endpoint: "finance/entries", perm: "finance.manage", editable: false, deletable: false,
        columns: [{ key: "date", label: "Tarih", fmt: J.d }, { key: "kind_label", label: "Tür" }, { key: "category", label: "Kategori" }, { key: "account_name", label: "Cari" }, { key: "description", label: "Açıklama" }, { key: "amount", label: "Tutar", right: true, fmt: money }, { key: "reversed", label: "Düzeltildi", html: (r) => J.yes(r.reversed) }],
        fields: [{ name: "kind", label: "Tür", type: "select", required: true, options: [["income", "Gelir"], ["expense", "Gider"], ["payable", "Borç (cari)"], ["receivable", "Alacak (cari)"], ["settle_payable", "Borç ödemesi"], ["settle_receivable", "Alacak tahsilatı"]] }, { name: "amount", label: "Tutar", type: "money", required: true }, { name: "date", label: "Tarih", type: "date", required: true, default: J.today() }, { name: "category", label: "Kategori (kira, elektrik…)" }, { name: "account", label: "Cari hesap", type: "select", options: opt("finance/accounts") }, { name: "description", label: "Açıklama" }],
        actions: [{ label: "Ters kayıt", show: (r) => !r.reversed && Number(r.amount) > 0, run: async (r, reload) => { const v = await J.askReason("Ters kayıtla düzelt"); if (v) { await J.post(`finance/entries/${r.id}/reverse`, v).catch(J.err); reload(); } } }] }) },
      { key: "accounts", label: "Cari hesaplar", render: (el) => J.crud(el, { title: "Cari hesap", endpoint: "finance/accounts", perm: "finance.manage", columns: [{ key: "name", label: "Ad" }, { key: "kind", label: "Tür" }, { key: "balance", label: "Borç", right: true, fmt: (v) => money(v.payable) }, { key: "balance", label: "Alacak", right: true, fmt: (v) => money(v.receivable) }], fields: [{ name: "name", label: "Ad", required: true }, { name: "kind", label: "Tür", type: "select", required: true, options: [["supplier", "Tedarikçi"], ["customer", "Müşteri"], ["other", "Diğer"]] }, { name: "phone", label: "Telefon" }, { name: "note", label: "Not", type: "textarea" }], deleteLabel: "Pasifleştir" }) },
      { key: "profit", label: "Kârlılık", render: async (el) => {
        const d1 = h(`<input type="date" class="input !w-auto">`), d2 = h(`<input type="date" class="input !w-auto">`);
        const now = new Date(); d2.value = J.today(); d1.value = new Date(now.getFullYear(), now.getMonth(), 1, 12).toISOString().slice(0, 10);
        const out = h(`<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3"></div>`);
        const load = async () => { const p = await J.get(`finance/entries/profitability?date_from=${d1.value}&date_to=${d2.value}`); out.innerHTML = [["Net satış (KDV hariç)", p.revenue_net], ["Satılan malın maliyeti", p.cogs], ["Brüt kâr", p.gross_profit], ["Diğer gelir", p.other_income], ["Giderler", p.expenses], ["Net kâr", p.net_profit], ["Tahsilat", p.collections], ["İade", p.refunds]].map(([l, v]) => `<div class="card p-4"><div class="text-xs muted">${l}</div><div class="text-xl font-bold">${money(v)}</div></div>`).join(""); };
        d1.onchange = load; d2.onchange = load;
        el.append(h(`<div class="flex gap-2"></div>`), out);
        el.firstChild.append(d1, d2);
        load();
      } },
    ]);
  };

  // ================================================================== RAPORLAR
  P.reports = async (main) => {
    const meta = await J.get("reports/meta");
    main.appendChild(J.pageHead("Raporlar", "Hazır raporlar, gelişmiş filtre, özel rapor oluşturucu, dışa aktarma ve otomatik gönderim"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    J.tabs(c, [
      { key: "run", label: "Rapor", render: async (el) => {
        const [users, halls] = await Promise.all([J.get("users?active=1").catch(() => []), J.get("halls").catch(() => [])]);
        const f = h(`<div class="card p-3 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2 items-end mb-3">
          <div class="col-span-2"><label class="label">Rapor</label><select class="input" data-k="type">${Object.entries(meta.types).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
          <div><label class="label">Başlangıç</label><input type="date" class="input" data-k="date_from" value="${J.today()}"></div>
          <div><label class="label">Bitiş</label><input type="date" class="input" data-k="date_to" value="${J.today()}"></div>
          <div><label class="label">Personel</label><select class="input" data-k="staff"><option value="">Tümü</option>${users.map((u) => `<option value="${u.id}">${esc(u.first_name || u.username)}</option>`).join("")}</select></div>
          <div><label class="label">Salon</label><select class="input" data-k="hall"><option value="">Tümü</option>${halls.map((x) => `<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></div>
          <div><label class="label">Kanal</label><select class="input" data-k="channel"><option value="">Tümü</option>${CHANNELS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></div>
          <label class="flex items-center gap-2 min-h-[44px]"><input type="checkbox" data-k="compare" class="w-5 h-5"> Önceki dönemle karşılaştır</label>
          <div class="hidden col-span-2 md:col-span-4 grid grid-cols-2 gap-2" data-custom><div><label class="label">Boyut</label><select class="input" data-k="dimension">${Object.entries(meta.dimensions).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div><div><label class="label">Ölçü</label><select class="input" data-k="metric">${Object.entries(meta.metrics).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div></div>
          <div class="col-span-2 md:col-span-4 xl:col-span-8 flex flex-wrap gap-2"><button class="btn btn-primary" data-run>Raporu getir</button>
            <button class="btn btn-ghost" data-x="pdf">PDF</button><button class="btn btn-ghost" data-x="xlsx">Excel</button><button class="btn btn-ghost" data-x="csv">CSV</button><button class="btn btn-ghost" data-print>Yazdır</button>
            <div class="flex-1"></div><select class="input !w-auto" data-tpl><option value="">Kayıtlı şablon…</option></select><button class="btn btn-ghost" data-save>Şablon kaydet</button></div></div>`);
        const out = h(`<div></div>`);
        el.append(f, out);
        const params = () => { const p = {}; qsa("[data-k]", f).forEach((i) => { if (i.type === "checkbox") { if (i.checked) p[i.dataset.k] = 1; } else if (i.value) p[i.dataset.k] = i.value; }); if (p.type !== "custom") { delete p.dimension; delete p.metric; } return p; };
        const query = (p) => Object.entries(p).filter(([k]) => k !== "type").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
        qs("[data-k=type]", f).onchange = (e) => qs("[data-custom]", f).classList.toggle("hidden", e.target.value !== "custom");
        const run = async () => {
          const p = params();
          out.innerHTML = `<div class="muted p-4">${t("Yükleniyor…")}</div>`;
          try {
            const r = await J.get(`reports/run/${p.type}?${query(p)}`);
            out.innerHTML = "";
            const totals = Object.entries(r.totals || {}).filter(([, v]) => v !== null);
            out.appendChild(h(`<div class="flex flex-wrap gap-3 mb-3">${totals.map(([k, v]) => `<div class="card p-3 min-w-[140px]"><div class="text-xs muted">${esc(k)}</div><div class="text-lg font-bold">${typeof v === "number" ? J.num(v) : esc(v)}</div>${r.compare && r.compare[k] !== undefined ? `<div class="text-xs muted">önceki: ${J.num(r.compare[k])}</div>` : ""}</div>`).join("")}</div>`));
            if (r.chart) { const cb = h(`<div class="card p-4 mb-3"><h2 class="font-semibold mb-2">${esc(r.title)}</h2><div></div></div>`); out.appendChild(cb); requestAnimationFrame(() => J.chart(cb.lastElementChild, r.chart, { height: 260 })); }
            const tb = h(`<div class="card"></div>`);
            tb.appendChild(J.table(r.columns.map((c2, i) => ({ label: c2, key: i, right: typeof r.rows[0]?.[i] === "number", fmt: (v) => (typeof v === "number" ? J.num(v) : v) })), r.rows));
            out.appendChild(tb);
          } catch (e) { out.innerHTML = ""; J.err(e); }
        };
        qs("[data-run]", f).onclick = run;
        qsa("[data-x]", f).forEach((b) => (b.onclick = () => { const p = params(); J.download(`reports/run/${p.type}?${query(p)}&export=${b.dataset.x}`); }));
        qs("[data-print]", f).onclick = () => window.print();
        const tplSel = qs("[data-tpl]", f);
        const loadTpl = async () => { const list = await J.get("reports/templates"); tplSel.innerHTML = `<option value="">Kayıtlı şablon…</option>` + list.map((x) => `<option value='${esc(JSON.stringify({ t: x.report_type, p: x.params }))}'>${esc(x.name)}</option>`).join(""); };
        tplSel.onchange = () => { if (!tplSel.value) return; const { t: tp, p } = JSON.parse(tplSel.value); qs("[data-k=type]", f).value = tp; qs("[data-custom]", f).classList.toggle("hidden", tp !== "custom"); Object.entries(p).forEach(([k, v]) => { const i = qs(`[data-k=${k}]`, f); if (i) i.type === "checkbox" ? (i.checked = !!v) : (i.value = v); }); run(); };
        qs("[data-save]", f).onclick = async () => { const v = await J.promptForm("Şablon kaydet", [{ name: "name", label: "Şablon adı", required: true }]); if (!v) return; const p = params(); const type = p.type; delete p.type; delete p.date_from; delete p.date_to; await J.post("reports/templates", { name: v.name, report_type: type, params: p }).catch(J.err); loadTpl(); };
        loadTpl().catch(() => {});
        run();
      } },
      { key: "schedules", label: "Otomatik gönderim", render: (el) => {
        el.appendChild(h(`<p class="text-sm muted mb-2">Raporlar seçilen saatte e-posta ile gönderilir. SMTP sunucu bilgisi (JETPOS_SMTP_HOST) tanımlı değilse e-postalar sunucudaki outbox_mail klasörüne yazılır. Başarısız gönderim 3 kez denenir ve kaydedilir.</p>`));
        J.crud(el, { title: "Otomatik rapor", endpoint: "reports/schedules", perm: "reports.view",
          columns: [{ key: "name", label: "Ad" }, { key: "report_type", label: "Rapor", fmt: (v) => meta.types[v] }, { key: "frequency", label: "Sıklık" }, { key: "send_time", label: "Saat" }, { key: "recipients", label: "Alıcılar", fmt: (v) => v.join(", ") }, { key: "fmt", label: "Format" }, { key: "last_delivery", label: "Son gönderim", html: (r) => r.last_delivery ? (r.last_delivery.ok ? J.badge(r.last_delivery.period, "var(--ok)", "check") : J.badge(`${r.last_delivery.attempts} deneme: ${r.last_delivery.error.slice(0, 60)}`, "var(--bad)", "circle-alert")) : "—" }],
          fields: [{ name: "name", label: "Ad", required: true }, { name: "report_type", label: "Rapor", type: "select", required: true, options: Object.entries(meta.types).filter(([k]) => k !== "custom") }, { name: "frequency", label: "Sıklık", type: "select", required: true, options: [["daily", "Günlük (önceki gün)"], ["weekly", "Haftalık (önceki 7 gün)"], ["monthly", "Aylık (önceki ay)"]] }, { name: "send_time", label: "Saat", type: "time", required: true, default: "08:00" }, { name: "weekday", label: "Haftalık gün (0=Pzt)", type: "number", default: 0 }, { name: "month_day", label: "Aylık gün", type: "number", default: 1 }, { name: "recipients_text", label: "Alıcılar (virgülle)", required: true }, { name: "fmt", label: "Format", type: "select", required: true, options: [["pdf", "PDF"], ["xlsx", "Excel"], ["csv", "CSV"]] }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }],
          toForm: (r) => ({ ...r, recipients_text: r.recipients.join(", ") }),
          toApi: (v) => { v.recipients = v.recipients_text.split(",").map((s) => s.trim()).filter(Boolean); delete v.recipients_text; return v; } });
      } },
    ]);
  };

  // ================================================================== BİLDİRİMLER
  P.notifications = async (main) => {
    let all = false;
    main.appendChild(J.pageHead("Bildirimler", "Varsayılan görünüm son 24 saat", `<button class="chip" data-all>Tüm geçmiş</button><button class="btn btn-ghost btn-sm" data-read>Tümünü okundu yap</button>`));
    const box = h(`<div class="card"></div>`);
    main.appendChild(box);
    const prio = { low: ["Düşük", "var(--muted)"], medium: ["Orta", "var(--warn)"], high: ["Yüksek", "var(--bad)"] };
    const load = async () => {
      const rows = await J.get(`notifications${all ? "?all=1" : ""}`);
      box.innerHTML = "";
      box.appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "priority", label: "Öncelik", html: (r) => J.badge(prio[r.priority][0], prio[r.priority][1]) }, { key: "title", label: "Başlık", html: (r) => `${r.read_at ? "" : `<span class="dot" style="--st:var(--accent);margin-right:.4rem" aria-label="Okunmadı"></span>`}<b>${esc(r.title)}</b><div class="text-xs muted">${esc(r.body)}</div>` }], rows, {
        onRow: async (r) => { await J.post(`notifications/${r.id}/read`).catch(() => {}); if (r.data?.ticket) J.go(`/ticket/${r.data.ticket}`); else load(); } }));
      J.emit("notif-refresh");
    };
    qs("[data-all]", main).onclick = (e) => { all = !all; e.target.classList.toggle("active", all); load(); };
    qs("[data-read]", main).onclick = () => J.post("notifications/read_all").then(load);
    await load();
  };
})();
