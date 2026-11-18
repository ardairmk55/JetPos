/* POS ekranları: dashboard, masalar, adisyon, ödeme, KDS, hazır siparişler, onaylar, kasa, ödemeler, garson PWA. */
(function () {
  const { esc, h, qs, qsa, t, tt, money } = J;
  const P = (J.pages = J.pages || {});
  const natural = (a, b) => a.name.localeCompare(b.name, "tr", { numeric: true });
  const STATUS = {
    empty: ["Boş", "○"], occupied: ["Dolu", "●"], waiting: ["Sipariş bekliyor", "◔"], reserved: ["Rezerve", "◷"],
    bill: ["Hesap bekliyor", "₺"], paid: ["Ödendi", "✓"],
  };

  // ================================================================== DASHBOARD
  P.dashboard = async (main) => {
    main.appendChild(J.pageHead("Ana sayfa", `${esc(J.state.me.business_name)} · ${esc(J.state.me.branch_name)}`, `<button class="btn btn-ghost btn-sm" data-r>↻ ${t("Yenile")}</button>`));
    const grid = h(`<div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4"></div>`);
    const charts = h(`<div class="grid lg:grid-cols-2 gap-3"></div>`);
    main.append(grid, charts);
    const card = (label, value, sub = "", href = "", tone = "") => `<a ${href ? `href="${href}" data-link` : ""} class="card p-4 block ${href ? "hover:border-jet" : ""}"><div class="text-xs font-semibold muted uppercase tracking-wide">${esc(t(label))}</div><div class="text-2xl font-bold mt-1 tabular-nums" style="${tone}">${value}</div><div class="text-xs muted mt-1">${sub}</div></a>`;
    const load = async () => {
      const d = await J.get("dashboard");
      const c = d.cards;
      let html = "";
      if (c.sales_today) {
        const diff = c.sales_today.prev ? Math.round(((c.sales_today.value - c.sales_today.prev) / c.sales_today.prev) * 100) : null;
        html += card("Bugünkü ciro", money(c.sales_today.value), diff === null ? "Dün: —" : `Dün: ${money(c.sales_today.prev)} (${diff >= 0 ? "+" : ""}${diff}%)`, "/reports");
        html += card("Adisyon", c.tickets_today.value, `Ortalama ${money(c.avg_ticket.value)}`, "/tickets");
      }
      if (c.open_tickets) html += card("Açık adisyon", c.open_tickets.value, `${money(c.open_tickets.amount)} · ${c.bill_requested.value} hesap bekliyor`, "/floor");
      if (c.kitchen_pending) html += card("Mutfakta bekleyen", c.kitchen_pending.value, `${c.kitchen_pending.late} geciken · ${c.ready_orders.value} hazır`, J.can("kds.view") ? "/kds" : "/ready", c.kitchen_pending.late ? "color:var(--bad)" : "");
      if (c.cash) html += card("Kasa", c.cash.status === "open" ? "Açık" : c.cash.status === "pending_approval" ? "Onay bekliyor" : "Kapalı", c.cash.expected !== null ? `Beklenen nakit ${money(c.cash.expected)}` : "Gün başı açılış gerekli", "/cash");
      if (c.low_stock) html += card("Düşük stok", c.low_stock.value, "kalem minimum seviyede", "/stock", c.low_stock.value ? "color:var(--warn)" : "");
      if (c.approvals) html += card("Onay bekleyen", c.approvals.value, "indirim / iptal / iade", "/approvals", c.approvals.value ? "color:var(--accent)" : "");
      grid.innerHTML = html || card("Hoş geldiniz", esc(J.state.me.first_name || J.state.me.username), esc(J.state.me.role_label));
      charts.innerHTML = "";
      const titles = { week: "Son 7 gün ciro", hourly: "Bugün saatlik yoğunluk", top_products: "Bugün en çok satanlar", payments: "Bugün ödeme dağılımı" };
      Object.entries(d.charts).forEach(([k, spec]) => {
        const box = h(`<section class="card p-4"><h2 class="font-semibold mb-3">${esc(t(titles[k] || k))}</h2><div data-c></div></section>`);
        charts.appendChild(box);
        requestAnimationFrame(() => J.chart(box.querySelector("[data-c]"), spec));
      });
    };
    qs("[data-r]", main).onclick = () => load().catch(J.err);
    await load();
    const off = J.on("ws:table", J.debounce(() => load().catch(() => {}), 1500));
    return off;
  };

  // ================================================================== MASALAR
  P.floor = async (main) => {
    const head = J.pageHead("Masalar", "", `
      ${J.can("ticket.open") ? `<button class="btn btn-ghost btn-sm" data-takeaway>+ Gel-al</button>` : ""}
      <button class="btn btn-ghost btn-sm" data-view>▦ Plan</button>
      ${J.can("floor.manage") ? `<button class="btn btn-ghost btn-sm" data-edit>✎ Düzenle</button><button class="btn btn-ghost btn-sm" data-addhall>+ Salon</button><button class="btn btn-ghost btn-sm" data-addtable>+ Masa</button>` : ""}`);
    main.appendChild(head);
    const legend = h(`<div class="flex flex-wrap gap-3 text-xs mb-3">${Object.entries(STATUS).map(([k, [l, i]]) => `<span class="st-${k} inline-flex items-center gap-1"><span class="dot"></span>${i} ${esc(t(l))} <b data-n="${k}"></b></span>`).join("")}</div>`);
    const halls = h(`<div class="flex gap-2 overflow-x-auto pb-2 mb-2" role="tablist"></div>`);
    const qr = h(`<div></div>`);
    const area = h(`<div></div>`);
    const others = h(`<div class="mt-6"></div>`);
    main.append(legend, qr, halls, area, others);
    let data, hall = Number(localStorage.getItem("jet.hall")) || null, plan = localStorage.getItem("jet.floorView") === "plan", editing = false;
    const focusTable = Number(new URLSearchParams(location.search).get("table")) || null;

    const openTable = async (tb) => {
      if (editing) return;
      try {
        if (tb.ticket) return J.go(`/ticket/${tb.ticket.id}`);
        if (!J.can("ticket.open")) return J.toast("Adisyon açma yetkiniz yok", "warn");
        const tk = await J.post(`tables/${tb.id}/open`, {});
        J.go(`/ticket/${tk.id}`);
      } catch (e) { J.err(e); }
    };
    const tableMenu = async (tb) => {
      const acts = [];
      if (tb.ticket && J.can("ticket.move")) acts.push({ label: "Adisyonu taşı", run: async () => {
        const v = await J.promptForm("Taşınacak masa", [{ name: "table", label: "Hedef masa", type: "select", required: true, options: data.tables.filter((x) => !x.ticket && x.id !== tb.id && !x.merged_into).map((x) => [x.id, x.name]) }]);
        if (v) { await J.post(`tickets/${tb.ticket.id}/move`, v); load(); }
      } });
      if (J.can("floor.manage") || J.can("ticket.move")) {
        acts.push({ label: "Masa birleştir", run: async () => {
          const v = await J.promptForm(`${tb.name} ile birleştir`, [{ name: "table", label: "Bağlanacak masa (boş olmalı)", type: "select", required: true, options: data.tables.filter((x) => x.id !== tb.id && !x.merged_into).map((x) => [x.id, x.name]) }]);
          if (v) { await J.post(`tables/${tb.id}/merge`, v); J.toast("Masalar birleştirildi", "ok"); load(); }
        } });
        if (J.can("floor.manage")) acts.push({ label: "Masa QR kodu", run: async () => {
          const m = J.modal({ title: `Masa ${tb.name} — QR`, body: `<div class="text-center"><img src="/api/tables/${tb.id}/qr" alt="Masa ${esc(tb.name)} QR kodu" class="mx-auto bg-white p-2 rounded"><div class="text-2xl font-black mt-2">Masa ${esc(tb.name)}</div><p class="text-xs muted no-print">İçerik Ayarlar &gt; JET Menü &gt; QR şablonundan üretilir.</p></div>`,
            actions: [{ label: "Yazdır", run: () => { window.print(); return false; } }, { label: "Kapat" }] });
          void m;
        } });
        if (tb.merged_into) acts.push({ label: "Birleştirmeyi ayır", run: async () => { await J.post(`tables/${tb.id}/unmerge`); load(); } });
      }
      if (!acts.length) return;
      const body = h(`<div class="grid gap-2"></div>`);
      const m = J.modal({ title: `Masa ${tb.name}`, body });
      acts.forEach((a) => { const b = h(`<button class="btn btn-ghost btn-lg w-full">${esc(t(a.label))}</button>`); b.onclick = async () => { m.close(); try { await a.run(); } catch (e) { J.err(e); } }; body.appendChild(b); });
    };
    const cardHtml = (tb) => {
      const [label, icon] = STATUS[tb.status];
      const tk = tb.ticket;
      return `<div class="flex items-start gap-2"><div class="text-xl font-black flex-1">${esc(tb.name)}</div>${tk?.ready ? `<span class="badge pulse" style="background:var(--accent);color:var(--accent-ink)">🔔 ${t("Hazır")} ${tk.ready}</span>` : ""}<span role="button" tabindex="0" class="muted px-2 -mr-1 rounded hover:surface-2" data-menu aria-label="Masa işlemleri">⋯</span></div>
        <div class="text-xs font-semibold mt-1" style="color:var(--st)">${icon} ${esc(t(label))}${tb.merged_into ? " · birleşik" : ""}</div>
        ${tk ? `<div class="mt-auto pt-2"><div class="text-lg font-bold tabular-nums">${money(tk.total)}</div><div class="text-xs muted truncate">${esc(tk.waiter)} · ${tk.items} ürün · ${tk.minutes} dk${tk.drafts ? ` · ${tk.drafts} taslak` : ""}</div></div>` : `<div class="mt-auto text-xs muted">${tb.seats} kişilik</div>`}`;
    };
    const render = () => {
      halls.innerHTML = "";
      if (!data.halls.find((x) => x.id === hall)) hall = data.halls[0]?.id;
      data.halls.forEach((hh) => {
        const n = data.tables.filter((x) => x.hall === hh.id && x.status !== "empty").length;
        const b = h(`<button class="chip ${hh.id === hall ? "active" : ""}" role="tab">${esc(hh.name)} <span class="ml-1 opacity-70">${n}</span></button>`);
        b.onclick = () => { hall = hh.id; localStorage.setItem("jet.hall", hall); render(); };
        halls.appendChild(b);
      });
      Object.keys(STATUS).forEach((k) => (qs(`[data-n="${k}"]`, legend).textContent = data.summary[k] || 0));
      const tables = data.tables.filter((x) => x.hall === hall).sort(natural);
      area.innerHTML = "";
      if (!data.halls.length) { area.innerHTML = `<div class="card p-8 text-center muted">Salon tanımlı değil. ${J.can("floor.manage") ? "“+ Salon” ile ekleyin." : ""}</div>`; return; }
      if (plan) {
        const hh = data.halls.find((x) => x.id === hall);
        const canvas = h(`<div class="relative card overflow-auto" style="height:min(75vh, ${hh.height}px)"><div class="relative" style="width:${hh.width}px;height:${hh.height}px"></div></div>`);
        const inner = canvas.firstElementChild;
        tables.forEach((tb) => {
          const el = h(`<button class="tile table-card st-${tb.status} p-3 absolute ${tb.id === focusTable ? "ring-4" : ""}" style="left:${tb.x}px;top:${tb.y}px;width:${tb.w}px;height:${tb.h}px;${tb.shape === "round" ? "border-radius:999px" : ""}" aria-label="Masa ${esc(tb.name)} ${esc(t(STATUS[tb.status][0]))}">${cardHtml(tb)}</button>`);
          el.onclick = (e) => { if (e.target.closest("[data-menu]")) return tableMenu(tb); openTable(tb); };
          if (editing) {
            el.style.cursor = "move";
            el.onpointerdown = (e) => {
              e.preventDefault(); el.setPointerCapture(e.pointerId);
              const sx = e.clientX - tb.x, sy = e.clientY - tb.y;
              el.onpointermove = (m) => { tb.x = Math.max(0, Math.round((m.clientX - sx) / 10) * 10); tb.y = Math.max(0, Math.round((m.clientY - sy) / 10) * 10); el.style.left = tb.x + "px"; el.style.top = tb.y + "px"; };
              el.onpointerup = () => { el.onpointermove = null; tb._moved = true; };
            };
          }
          inner.appendChild(el);
        });
        area.appendChild(canvas);
        if (editing) {
          const save = h(`<div class="mt-3 flex gap-2"><button class="btn btn-primary">Yerleşimi kaydet</button><button class="btn btn-ghost">Vazgeç</button></div>`);
          save.children[0].onclick = async () => { await J.post("tables/layout", { tables: tables.filter((x) => x._moved).map(({ id, x, y, w, h }) => ({ id, x, y, w, h })) }); editing = false; J.toast("Yerleşim kaydedildi", "ok"); load(); };
          save.children[1].onclick = () => { editing = false; load(); };
          area.appendChild(save);
        }
      } else {
        const grid = h(`<div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-3"></div>`);
        tables.forEach((tb) => {
          const el = h(`<button class="tile table-card st-${tb.status} p-3 min-h-[128px] ${tb.id === focusTable ? "ring-4" : ""}" aria-label="Masa ${esc(tb.name)} ${esc(t(STATUS[tb.status][0]))}">${cardHtml(tb)}</button>`);
          el.onclick = (e) => { if (e.target.closest("[data-menu]")) return tableMenu(tb); openTable(tb); };
          el.oncontextmenu = (e) => { e.preventDefault(); tableMenu(tb); };
          grid.appendChild(el);
        });
        area.appendChild(grid);
      }
      others.innerHTML = data.other_tickets.length ? `<h2 class="font-semibold mb-2">Masasız adisyonlar (gel-al / teslimat / QR)</h2>` : "";
      if (data.other_tickets.length) others.appendChild(J.table([
        { key: "number", label: "No", fmt: (v) => "#" + v }, { key: "channel", label: "Kanal" }, { key: "status_label", label: "Durum" },
        { key: "waiter_name", label: "Personel" }, { key: "total", label: "Toplam", right: true, fmt: money }], data.other_tickets, { onRow: (r) => J.go(`/ticket/${r.id}`) }));
    };
    const loadQr = async () => {
      if (!J.can("ticket.add")) return;
      const list = await J.get("qr-orders").catch(() => []);
      qr.innerHTML = "";
      if (!list.length) return;
      const box = h(`<div class="card p-3 mb-3" style="border-color:var(--accent)"><h2 class="font-semibold mb-2">📱 QR siparişleri onay bekliyor (${list.length})</h2></div>`);
      list.forEach((o) => {
        const row = h(`<div class="flex flex-wrap items-center gap-2 py-2 border-t bd"><b>Masa ${esc(o.table_name)}</b><span class="flex-1 text-sm">${o.items.map((i) => `${esc(i.qty)} × ${esc(i.name)}`).join(", ")}</span><button class="btn btn-ok btn-sm">Adisyona ekle</button><button class="btn btn-ghost btn-sm">Reddet</button></div>`);
        const [ok, no] = row.querySelectorAll("button");
        ok.onclick = async () => { try { await J.post("qr-orders", { id: o.id, action: "accept" }); J.toast("Taslak olarak eklendi; kontrol edip mutfağa gönderin", "ok"); load(); } catch (e) { J.err(e); } };
        no.onclick = async () => { const v = await J.askReason("QR siparişini reddet"); if (v) { await J.post("qr-orders", { id: o.id, action: "reject", reason: v.reason }); load(); } };
        box.appendChild(row);
      });
      qr.appendChild(box);
    };
    const load = async () => { data = await J.get("floor"); render(); loadQr(); };
    qs("[data-view]", head).onclick = () => { plan = !plan; localStorage.setItem("jet.floorView", plan ? "plan" : "grid"); render(); };
    qs("[data-edit]", head)?.addEventListener("click", () => { editing = !editing; plan = true; render(); });
    qs("[data-addhall]", head)?.addEventListener("click", async () => {
      const v = await J.promptForm("Yeni salon", [{ name: "name", label: "Salon adı (iç salon, bahçe, teras…)", required: true }, { name: "sort", label: "Sıra", type: "number", default: data.halls.length }]);
      if (v) { await J.post("halls", v).catch(J.err); load(); }
    });
    qs("[data-addtable]", head)?.addEventListener("click", async () => {
      const v = await J.promptForm("Yeni masa", [
        { name: "hall", label: "Salon", type: "select", required: true, options: data.halls.map((x) => [x.id, x.name]), default: hall },
        { name: "name", label: "Masa no/adı", required: true }, { name: "seats", label: "Kişi", type: "number", default: 4 },
        { name: "shape", label: "Şekil", type: "select", required: true, options: [["square", "Kare"], ["round", "Yuvarlak"], ["rect", "Dikdörtgen"]], default: "square" }]);
      if (v) { await J.post("tables", v).catch(J.err); load(); }
    });
    qs("[data-takeaway]", head)?.addEventListener("click", async () => { try { const tk = await J.post("tickets", { channel: "takeaway" }); J.go(`/ticket/${tk.id}`); } catch (e) { J.err(e); } });
    await load();
    const offs = [J.on("ws:table", J.debounce(() => !editing && load().catch(() => {}), 400)),
      J.on("ws:ready", J.debounce(() => !editing && load().catch(() => {}), 400))];
    return () => offs.forEach((f) => f());
  };

  // ================================================================== ADİSYON
  P.ticket = async (main, { id }) => {
    main.classList.add("!p-0");
    const layout = h(`<div class="flex flex-col lg:flex-row h-[calc(100vh-4rem)]">
      <section class="flex-1 min-w-0 flex flex-col" data-menu-col>
        <div class="flex items-center gap-2 p-3 border-b bd" style="background:var(--surface)">
          <button class="btn btn-ghost btn-sm" data-back aria-label="Masalara dön">←</button>
          <input class="input" type="search" placeholder="Ürün ara (adı, kodu, barkod)…" data-search aria-label="Ürün ara">
          <button class="btn btn-ghost btn-sm lg:hidden" data-show-ticket>Adisyon</button>
        </div>
        <div class="flex gap-2 overflow-x-auto p-3 pb-1" data-cats role="tablist" aria-label="Kategoriler"></div>
        <div class="flex-1 overflow-y-auto p-3"><div class="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-2" data-products></div></div>
      </section>
      <aside class="w-full lg:w-[420px] xl:w-[460px] border-l bd flex flex-col hidden lg:flex" style="background:var(--surface)" data-ticket-col aria-label="Adisyon"></aside>
    </div>`);
    main.appendChild(layout);
    const tcol = qs("[data-ticket-col]", layout);
    const mcol = qs("[data-menu-col]", layout);
    let tk, menu, cat = "fav", search = "";
    const queuedFor = async () => (await J.queue.all()).filter((q) => q.url.startsWith(`tickets/${id}/`));
    qs("[data-back]", layout).onclick = () => J.go(J.state.isWaiterMode ? "/waiter" : "/floor");
    qs("[data-show-ticket]", layout).onclick = () => { tcol.classList.remove("hidden"); tcol.classList.add("flex"); mcol.classList.add("hidden"); };

    const loadMenu = async () => {
      try { menu = await J.get(`products/menu?channel=${tk?.channel || "table"}`); localStorage.setItem("jet.menu", JSON.stringify(menu)); }
      catch (e) { if (e instanceof J.ApiError) throw e; menu = JSON.parse(localStorage.getItem("jet.menu") || "null"); if (!menu) throw e; }
      menu.cats = [];
      menu.products.forEach((p) => { if (!menu.cats.find((c) => c.id === p.category)) menu.cats.push({ id: p.category, name: p.category_name }); });
      renderCats(); renderProducts();
    };
    const renderCats = () => {
      const c = qs("[data-cats]", layout);
      const items = [["fav", "★ Favoriler"], ["recent", "⟲ Son kullanılan"], ["popular", "🔥 Popüler"], ...menu.cats.map((x) => [x.id, x.name])];
      c.innerHTML = "";
      items.forEach(([k, l]) => { const b = h(`<button class="chip ${cat === k ? "active" : ""}" role="tab">${esc(l)}</button>`); b.onclick = () => { cat = k; renderCats(); renderProducts(); }; c.appendChild(b); });
    };
    const renderProducts = () => {
      const g = qs("[data-products]", layout);
      let list = menu.products;
      if (search) { const s = search.toLocaleLowerCase("tr"); list = list.filter((p) => p.name.toLocaleLowerCase("tr").includes(s) || (p.sku || "").toLowerCase() === s || p.barcode === search); }
      else if (cat === "fav") { list = list.filter((p) => p.is_favorite); if (!list.length) list = menu.products.filter((p) => menu.popular.includes(p.id)); }
      else if (cat === "recent") list = menu.recent.map((i) => menu.products.find((p) => p.id === i)).filter(Boolean);
      else if (cat === "popular") list = menu.popular.map((i) => menu.products.find((p) => p.id === i)).filter(Boolean);
      else list = list.filter((p) => p.category === cat);
      g.innerHTML = list.length ? "" : `<div class="col-span-full p-8 text-center muted">Ürün yok${cat === "fav" ? " — kategorilerden seçin" : ""}</div>`;
      list.forEach((p) => {
        const st = p.stock_state === "out" ? `<span class="badge" style="background:var(--bad);color:#fff">Stok yok</span>` : p.stock_state === "low" ? `<span class="badge" style="background:var(--warn);color:#fff">Az</span>` : "";
        const tile = h(`<button class="tile" aria-label="${esc(p.name)} ${money(p.price)}">
          <div class="h-16 surface-2 flex items-center justify-center text-2xl overflow-hidden">${p.image_url ? `<img src="${esc(p.image_url)}" alt="" class="w-full h-full object-cover" loading="lazy">` : "🍽"}</div>
          <div class="p-2 flex-1 flex flex-col"><div class="text-sm font-semibold leading-tight line-clamp-2">${esc(p.name)}</div><div class="mt-auto flex items-center justify-between pt-1"><b class="tabular-nums text-sm">${money(p.price)}</b>${st}</div></div></button>`);
        tile.onclick = () => addProduct(p);
        g.appendChild(tile);
      });
    };
    qs("[data-search]", layout).addEventListener("input", J.debounce((e) => { search = e.target.value.trim(); renderProducts(); }, 120));
    qs("[data-search]", layout).addEventListener("keydown", (e) => {
      if (e.key === "Enter" && search) { const p = menu.products.find((x) => x.barcode === search || (x.sku || "").toLowerCase() === search.toLowerCase()); if (p) { addProduct(p); e.target.value = ""; search = ""; renderProducts(); } }
    });

    const addProduct = async (p, qty = 1) => {
      if (!J.can("ticket.add")) return J.toast("Ürün ekleme yetkiniz yok", "warn");
      if (p.option_groups_detail?.length) return optionsModal(p);
      return addLine({ product: p.id, qty, options: [], note: "" }, p.name);
    };
    const addLine = async (body, label) => {
      const r = await J.apiQueued("POST", `tickets/${id}/add_line`, { ...body, client_uid: `${J.device}-${J.uid()}` }, { label: `${label} ekleme` }).catch(J.err);
      if (!r) return;
      if (r.queued) return renderTicket();
      tk = r;
      if (r.warning) J.toast(r.warning, "warn");
      renderTicket();
    };
    const optionsModal = (p, line = null) => {
      const chosen = new Set((line?.options || []).map((o) => o.id));
      if (!line) p.option_groups_detail.forEach((g) => g.options.filter((o) => o.is_default).forEach((o) => chosen.add(o.id)));
      let qty = Number(line?.qty || 1);
      const body = h(`<div class="space-y-4"></div>`);
      const price = h(`<div class="text-xl font-bold tabular-nums"></div>`);
      const upd = () => {
        const extra = p.option_groups_detail.flatMap((g) => g.options).filter((o) => chosen.has(o.id)).reduce((a, o) => a + Number(o.price_delta), 0);
        price.textContent = money((Number(p.price) + extra) * qty);
      };
      p.option_groups_detail.forEach((g) => {
        const mn = Math.max(g.min_select, g.required ? 1 : 0);
        const sec = h(`<fieldset><legend class="font-semibold mb-2">${esc(g.name)} <span class="text-xs muted">${mn ? `zorunlu, en az ${mn}` : "opsiyonel"}${g.max_select ? ` · en fazla ${g.max_select}` : ""}</span></legend><div class="grid grid-cols-2 gap-2"></div></fieldset>`);
        const paint = () => qsa("[data-oid]", sec).forEach((b) => {
          const on = chosen.has(Number(b.dataset.oid));
          b.style.borderColor = on ? "var(--accent)" : "";
          b.style.background = on ? "color-mix(in srgb,var(--accent) 14%,transparent)" : "";
          b.setAttribute("aria-pressed", on);
        });
        g.options.forEach((o) => {
          const b = h(`<button type="button" class="btn btn-ghost justify-between" data-oid="${o.id}"><span>${esc(o.name)}</span><span class="text-xs muted">${Number(o.price_delta) ? "+" + money(o.price_delta) : "ücretsiz"}</span></button>`);
          b.onclick = () => {
            const inGroup = g.options.filter((x) => chosen.has(x.id));
            if (chosen.has(o.id)) chosen.delete(o.id);
            else {
              if (g.max_select === 1) inGroup.forEach((x) => chosen.delete(x.id));
              else if (g.max_select && inGroup.length >= g.max_select) return J.toast(`En fazla ${g.max_select} seçim`, "warn");
              chosen.add(o.id);
            }
            paint(); upd();
          };
          sec.querySelector(".grid").appendChild(b);
        });
        paint();
        body.appendChild(sec);
      });
      const note = h(`<div><label class="label">Not</label><input class="input" maxlength="300" placeholder="Örn. soğansız" value="${esc(line?.note || "")}"></div>`);
      const qtyEl = h(`<div class="flex items-center gap-3"><span class="label !mb-0">Miktar</span><button class="btn btn-ghost" type="button" aria-label="Azalt">−</button><b class="text-xl w-10 text-center tabular-nums">${qty}</b><button class="btn btn-ghost" type="button" aria-label="Artır">+</button><div class="flex-1"></div></div>`);
      qtyEl.appendChild(price);
      const [minus, plus] = qtyEl.querySelectorAll("button");
      minus.onclick = () => { qty = Math.max(1, qty - 1); qtyEl.querySelector("b").textContent = qty; upd(); };
      plus.onclick = () => { qty += 1; qtyEl.querySelector("b").textContent = qty; upd(); };
      body.append(note, qtyEl);
      upd();
      J.modal({ title: p.name, body, size: "max-w-xl", actions: [{ label: "İptal" }, { label: line?.id ? "Güncelle" : "Adisyona ekle", cls: "btn-primary", run: async () => {
        for (const g of p.option_groups_detail) {
          const n = g.options.filter((o) => chosen.has(o.id)).length;
          const mn = Math.max(g.min_select, g.required ? 1 : 0);
          if (n < mn) { J.toast(`'${g.name}' için en az ${mn} seçim yapın`, "warn"); return false; }
        }
        const noteV = note.querySelector("input").value;
        if (line?.id) { tk = await J.post(`tickets/${id}/update_line`, { line: line.id, qty, note: noteV, options: [...chosen] }); renderTicket(); }
        else await addLine({ product: p.id, qty, options: [...chosen], note: noteV }, p.name);
      } }] });
    };

    const lineRow = (ln) => {
      const isDraft = ln.status === "draft", isVoid = ln.status === "void";
      const el = h(`<div class="py-2 border-b bd ${isVoid ? "opacity-50" : ""}">
        <div class="flex items-start gap-2">
          <div class="flex-1 min-w-0"><div class="font-semibold ${isVoid ? "line-through" : ""}">${esc(J.num(ln.qty, 2))} × ${esc(ln.name)}</div>
          ${ln.options.length ? `<div class="text-xs muted">${ln.options.map((o) => esc(o.name)).join(", ")}</div>` : ""}
          ${ln.note ? `<div class="text-xs" style="color:var(--warn)">Not: ${esc(ln.note)}</div>` : ""}
          ${ln.campaign_name ? `<div class="text-xs" style="color:var(--ok)">🏷 ${esc(ln.campaign_name)} −${money(ln.campaign_discount)}</div>` : ""}
          ${isVoid ? `<div class="text-xs" style="color:var(--bad)">İptal: ${esc(ln.void_reason)}</div>` : ""}
          <div class="text-xs mt-0.5">${ln._queued ? J.badge("⏳ Kuyrukta — sunucuya ulaşmadı", "var(--warn)") : isDraft ? J.badge(t("Taslak"), "var(--muted)") : isVoid ? "" : J.badge(`${t("Gönderildi")} · P${ln.batch_number || ""}`, "var(--info)")}${ln.paid ? " " + J.badge("Ödendi", "var(--ok)") : ""}${ln.seat ? ` <span class="muted">Kişi ${ln.seat}</span>` : ""}</div></div>
          <div class="text-right"><div class="font-bold tabular-nums">${money(ln.unit_price * ln.qty)}</div></div>
        </div>
        <div class="flex gap-1 mt-1 justify-end" data-acts></div></div>`);
      const acts = qs("[data-acts]", el);
      const btn = (label, fn, cls = "btn-ghost") => { const b = h(`<button class="btn ${cls} btn-sm">${label}</button>`); b.onclick = () => fn().catch(J.err); acts.appendChild(b); };
      if (ln._queued) return el;
      if (isDraft && tk.status !== "paid") {
        btn("−", async () => { tk = ln.qty > 1 ? await J.post(`tickets/${id}/update_line`, { line: ln.id, qty: Number(ln.qty) - 1 }) : await J.post(`tickets/${id}/delete_line`, { line: ln.id }); renderTicket(); });
        btn("+", async () => { tk = await J.post(`tickets/${id}/update_line`, { line: ln.id, qty: Number(ln.qty) + 1 }); renderTicket(); });
        btn("✎", async () => {
          const p = menu.products.find((x) => x.id === ln.product);
          if (p?.option_groups_detail?.length) return optionsModal(p, ln);
          const v = await J.promptForm("Satırı düzenle", [{ name: "qty", label: "Miktar", type: "number", step: "0.5", default: ln.qty }, { name: "note", label: "Not", default: ln.note }]);
          if (v) { tk = await J.post(`tickets/${id}/update_line`, { line: ln.id, ...v }); renderTicket(); }
        });
        btn("🗑", async () => { tk = await J.post(`tickets/${id}/delete_line`, { line: ln.id }); renderTicket(); });
      }
      if (ln.status === "sent" && !ln.paid && ["open", "bill_requested"].includes(tk.status)) {
        btn("Kişi", async () => { const v = await J.promptForm("Ürün bazlı kişi ataması", [{ name: "seat", label: "Kişi no (hesap bölme için)", type: "number", default: ln.seat || 1 }]); if (v) { tk = await J.post(`tickets/${id}/update_line`, { line: ln.id, seat: Number(v.seat) || null }); renderTicket(); } });
        btn("İptal", async () => {
          const v = await J.askReason(`İptal: ${ln.name}`, Number(ln.qty) > 1 ? [{ name: "qty", label: "İptal miktarı", type: "number", default: ln.qty }] : []);
          if (!v) return;
          const r = await J.withApproval((extra) => J.post(`tickets/${id}/void_line`, { line: ln.id, reason: v.reason, qty: v.qty, ...extra }));
          if (r && !r.pending) { tk = r; J.toast("İptal edildi; mutfağa bildirildi", "ok"); renderTicket(); }
        }, "btn-ghost");
      }
      return el;
    };

    const renderTicket = async () => {
      const queued = await queuedFor();
      const pseudo = queued.filter((q) => q.url.endsWith("add_line")).map((q) => {
        const p = menu?.products.find((x) => x.id === q.body.product) || { name: "Ürün", price: 0 };
        return { id: q.id, name: p.name, qty: q.body.qty, unit_price: p.price, options: [], note: q.body.note, status: "draft", _queued: true };
      });
      const sendQueued = queued.some((q) => q.url.endsWith("/send"));
      const lines = [...tk.lines.filter((l) => l.status === "draft"), ...pseudo, ...tk.lines.filter((l) => l.status !== "draft")];
      const drafts = tk.lines.filter((l) => l.status === "draft").length;
      const st = tk.status;
      tcol.innerHTML = "";
      tcol.appendChild(h(`<div class="p-3 border-b bd flex items-start gap-2">
        <button class="btn btn-ghost btn-sm lg:hidden" data-back2>←</button>
        <div class="flex-1"><div class="text-lg font-black">${tk.table_name ? "Masa " + esc(tk.table_name) : esc(tk.channel === "takeaway" ? "Gel-al" : tk.channel === "delivery" ? "Teslimat" : tk.channel)} <span class="muted font-semibold">#${tk.number}</span></div>
        <div class="text-xs muted">${esc(tk.waiter_name)} · ${J.dt(tk.opened_at)} · ${esc(tk.status_label)}${tk.customer_name ? " · 👤 " + esc(tk.customer_name) : ""}${tk.customer_group_name ? " · " + esc(tk.customer_group_name) : ""}</div></div>
        <button class="btn btn-ghost btn-sm" data-more aria-label="Diğer işlemler">⋯</button></div>`));
      qs("[data-back2]", tcol).onclick = () => { tcol.classList.add("hidden"); mcol.classList.remove("hidden"); };
      if (sendQueued) tcol.appendChild(h(`<div class="p-3 text-sm font-semibold" style="background:var(--warn);color:#fff" role="alert">⏳ Mutfağa gönderim kuyrukta. Bağlantı gelince gönderilecek — mutfağa HENÜZ ulaşmadı.</div>`));
      if (tk.pending_approvals?.length) tcol.appendChild(h(`<div class="px-3 py-2 text-xs" style="background:color-mix(in srgb,var(--accent) 18%,transparent)">⏳ ${tk.pending_approvals.length} onay bekleyen talep</div>`));
      const list = h(`<div class="flex-1 overflow-y-auto px-3"></div>`);
      lines.forEach((ln) => list.appendChild(lineRow(ln)));
      if (!lines.length) list.innerHTML = `<div class="p-8 text-center muted">Soldan ürün seçin</div>`;
      tcol.appendChild(list);
      const row = (l, v, b = "") => `<div class="flex justify-between ${b}"><span>${l}</span><span class="tabular-nums">${v}</span></div>`;
      tcol.appendChild(h(`<div class="p-3 border-t bd text-sm space-y-0.5">
        ${row("Ara toplam", money(tk.subtotal))}${Number(tk.campaign_discount) ? row("Kampanya", "−" + money(tk.campaign_discount)) : ""}
        ${tk.discounts.filter((d) => !d.reversed_at).map((d) => row(`İndirim (${esc(d.reason)})`, "−" + money(d.amount))).join("")}
        ${row("KDV", money(tk.tax_total), "muted text-xs")}
        ${row(`<b class="text-base">${t("Toplam")}</b>`, `<b class="text-xl">${money(tk.total)}</b>`)}
        ${Number(tk.paid_total) ? row(t("Ödenen"), money(tk.paid_total)) + row(`<b>${t("Kalan")}</b>`, `<b style="color:var(--accent)">${money(tk.remaining)}</b>`) : ""}</div>`));
      const bar = h(`<div class="p-3 grid grid-cols-2 gap-2 border-t bd"></div>`);
      const B = (label, cls, fn, cond = true, span = false) => { if (!cond) return; const b = h(`<button class="btn ${cls} ${span ? "col-span-2" : ""}">${label}</button>`); b.onclick = () => fn().catch(J.err); bar.appendChild(b); };
      const editable = ["open", "bill_requested"].includes(st);
      B(`${t("Mutfağa Gönder")} ${drafts ? `(${drafts})` : ""} <span class="text-xs opacity-60">Ctrl+↵</span>`, "btn-primary btn-lg", () => send(), editable && J.can("ticket.send") && (drafts > 0), true);
      B(t("Hesap iste"), "btn-ghost", async () => { tk = await J.post(`tickets/${id}/request_bill`); J.toast("Hesap istendi; kasaya bildirildi", "ok"); renderTicket(); }, st === "open" && J.can("ticket.request_bill") && !drafts);
      B(`${t("Öde")} <span class="text-xs opacity-60">F9</span>`, "btn-dark", () => payModal(), editable && J.can("payment.take") && Number(tk.remaining) > 0);
      B("Masayı kapat", "btn-ok", async () => { tk = await J.post(`tickets/${id}/close`); J.toast("Adisyon kapatıldı", "ok"); J.go("/floor"); }, (st === "paid" || (Number(tk.total) === 0 && tk.lines.some((l) => l.status === "void") && !drafts)) && (J.can("payment.take") || J.can("floor.manage")), true);
      tcol.appendChild(bar);
      qs("[data-more]", tcol).onclick = moreMenu;
    };

    const send = async () => {
      const go = async (confirmed) => {
        const r = await J.apiQueued("POST", `tickets/${id}/send`, { confirmed }, { label: `#${tk.number} mutfağa gönderim` }).catch(async (e) => {
          if (e instanceof J.ApiError && e.data?.code === "confirmation_required") {
            const ok = await new Promise((res) => J.modal({ title: "Mutfağa gönderim özeti", onClose: (v) => res(v === true),
              body: `<ul class="space-y-2">${e.data.summary.map((s) => `<li class="flex gap-2"><b class="w-10 tabular-nums">${esc(J.num(s.qty))}×</b><div><div class="font-semibold">${esc(s.name)}</div>${s.options.length ? `<div class="text-xs muted">${s.options.map(esc).join(", ")}</div>` : ""}${s.note ? `<div class="text-xs" style="color:var(--warn)">Not: ${esc(s.note)}</div>` : ""}</div></li>`).join("")}</ul>`,
              actions: [{ label: "Düzenle", run: () => false }, { label: "Onayla ve gönder", cls: "btn-primary", run: () => true }] }));
            if (ok) return go(true);
            return null;
          }
          J.err(e); return null;
        });
        if (!r) return;
        if (r.queued) return renderTicket();
        tk = r;
        J.toast(`Parti ${r.sent_batch} mutfağa ulaştı ✓`, "ok");
        renderTicket();
      };
      await go(false);
    };

    const moreMenu = () => {
      const editable = ["open", "bill_requested"].includes(tk.status);
      const items = [];
      if (editable && J.can("ticket.add")) items.push(["İndirim uygula", async () => {
        const v = await J.promptForm("İndirim", [{ name: "kind", label: "Tür", type: "select", required: true, options: [["percent", "Yüzde (%)"], ["fixed", "Sabit tutar (TL)"]], default: "percent" },
          { name: "value", label: "Değer", type: "money", required: true }, { name: "reason", label: "Gerekçe", type: "textarea", required: true, minLength: 3 }]);
        if (!v) return;
        const r = await J.withApproval((extra) => J.post(`tickets/${id}/discount`, { ...v, ...extra }));
        if (r && !r.pending) { tk = r; renderTicket(); J.toast("İndirim uygulandı", "ok"); }
      }]);
      if (editable && tk.discounts.some((d) => !d.reversed_at) && J.can("ticket.add")) items.push(["İndirimi geri al", async () => {
        const d = tk.discounts.find((x) => !x.reversed_at);
        const v = await J.askReason(`İndirimi geri al: ${d.reason}`);
        if (!v) return;
        const r = await J.withApproval((extra) => J.post(`tickets/${id}/reverse_discount`, { discount: d.id, reason: v.reason, ...extra }));
        if (r) { tk = r; renderTicket(); }
      }]);
      if (editable && J.can("ticket.add")) items.push(["Müşteri grubu (ör. belediye personeli)", async () => {
        const groups = await J.get("customer-groups");
        const v = await J.promptForm("Müşteri grubu indirimi", [{ name: "group", label: "Grup", type: "select", required: true, options: groups.filter((g) => g.is_active).map((g) => [g.id, `${g.name} (${g.discount_type === "percent" ? "%" : ""}${g.discount_value}${g.discount_type === "fixed" ? " TL" : ""})`]) }, { name: "reason", label: "Not (ör. personel sicil no)" }]);
        if (!v) return;
        const r = await J.post(`tickets/${id}/customer_group`, v);
        if (r.pending) J.toast("Onay talebi kasiyere gönderildi", "info"); else { tk = r; renderTicket(); }
      }]);
      if (J.hasModule("crm") && J.can("ticket.add")) items.push(["Müşteri seç", async () => {
        const list = await J.get("customers");
        const v = await J.promptForm("Müşteri", [{ name: "customer", label: "Müşteri", type: "select", options: list.map((c) => [c.id, `${c.name} · ${c.phone}`]) }]);
        if (v) { tk = await J.post(`tickets/${id}/set_customer`, v); renderTicket(); }
      }]);
      if (J.can("printers.manage") || J.can("payment.take")) items.push(["Hesap fişi yazdır", async () => { const r = await J.post("print-jobs/reprint", { ticket: tk.id }); J.toast(r.jobs ? "Yazıcı kuyruğuna gönderildi" : "Kasa yazıcısı tanımlı değil", r.jobs ? "ok" : "warn"); }]);
      items.push(["Ekranda hesap dökümü", async () => printBill()]);
      if (J.can("audit.view") || J.can("floor.manage")) items.push(["İşlem geçmişi", async () => {
        const hist = await J.get(`tickets/${id}/history`);
        J.modal({ title: `Adisyon #${tk.number} geçmişi`, size: "max-w-3xl", body: J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "action", label: "İşlem" }, { key: "user", label: "Kullanıcı" }, { key: "reason", label: "Gerekçe" }, { key: "after", label: "Detay", fmt: (v) => v ? Object.entries(v).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join(" · ") : "" }], hist) });
      }]);
      if (tk.status === "open" && !tk.lines.some((l) => l.status !== "draft") && !tk.payments.length) items.push(["Boş adisyonu iptal et", async () => { if (await J.confirm("Adisyon iptal edilsin mi?", { danger: true })) { await J.post(`tickets/${id}/cancel`); J.go("/floor"); } }]);
      const body = h(`<div class="grid gap-2"></div>`);
      const m = J.modal({ title: `Adisyon #${tk.number}`, body });
      items.forEach(([l, fn]) => { const b = h(`<button class="btn btn-ghost btn-lg w-full justify-start">${esc(l)}</button>`); b.onclick = async () => { m.close(); try { await fn(); } catch (e) { J.err(e); } }; body.appendChild(b); });
    };

    const printBill = () => {
      const w = window.open("", "_blank", "width=420,height=700");
      if (!w) return J.toast("Açılır pencere engellendi", "warn");
      w.document.write(`<html><head><title>Adisyon #${tk.number}</title><style>body{font:13px monospace;padding:12px;max-width:340px}td{padding:2px 0}td:last-child{text-align:right}hr{border:0;border-top:1px dashed #000}</style></head><body>
        <h3 style="text-align:center;margin:0">${esc(J.state.me.business_name)}</h3><p style="text-align:center">${tk.table_name ? "Masa " + esc(tk.table_name) : ""} #${tk.number}<br>${J.dt(new Date())}</p><hr><table width="100%">
        ${tk.lines.filter((l) => l.status !== "void").map((l) => `<tr><td>${J.num(l.qty)} x ${esc(l.name)}</td><td>${money(l.unit_price * l.qty)}</td></tr>`).join("")}</table><hr>
        <table width="100%"><tr><td>Ara toplam</td><td>${money(tk.subtotal)}</td></tr><tr><td>İndirim</td><td>-${money(Number(tk.discount_total) + Number(tk.campaign_discount))}</td></tr><tr><td>KDV</td><td>${money(tk.tax_total)}</td></tr><tr><td><b>TOPLAM</b></td><td><b>${money(tk.total)}</b></td></tr></table>
        <hr><p style="text-align:center;font-size:11px">Bu belge mali değeri olmayan bilgi fişidir.</p><script>print()<\/script></body></html>`);
    };

    const payModal = async () => {
      const prev = await J.get(`tickets/${id}/split_preview`);
      let method = "cash", mode = "full";
      const body = h(`<div class="grid md:grid-cols-2 gap-5">
        <div><h3 class="font-semibold mb-2">Hesap özeti</h3><div class="text-sm space-y-1 max-h-64 overflow-y-auto">${tk.lines.filter((l) => l.status === "sent").map((l) => `<div class="flex justify-between"><span>${J.num(l.qty)} × ${esc(l.name)} ${l.paid ? J.badge("ödendi", "var(--ok)") : ""}</span><span class="tabular-nums">${money(l.net_total)}</span></div>`).join("")}</div>
          <div class="mt-3 pt-3 border-t bd space-y-1 text-sm"><div class="flex justify-between"><span>Toplam</span><b class="tabular-nums">${money(tk.total)}</b></div><div class="flex justify-between"><span>Ödenen</span><span class="tabular-nums">${money(tk.paid_total)}</span></div>
          <div class="flex justify-between text-lg"><b>Kalan</b><b class="tabular-nums" style="color:var(--accent)">${money(prev.remaining)}</b></div></div>
          ${tk.payments.length ? `<h3 class="font-semibold mt-4 mb-1">Alınan ödemeler</h3>${tk.payments.map((p) => `<div class="flex justify-between text-sm"><span>${esc(p.method_label)} · ${J.dt(p.created_at)}</span><span>${money(p.amount)}${Number(p.refunded_amount) ? ` (iade ${money(p.refunded_amount)})` : ""}</span></div>`).join("")}` : ""}</div>
        <div class="space-y-3">
          <div><div class="label">Ödeme yöntemi</div><div class="grid grid-cols-2 gap-2" data-methods>${[["cash", "💵 Nakit"], ["card", "💳 Kart"], ["meal_card", "🍽 Yemek kartı"], ["open_account", "📒 Açık hesap"]].map(([k, l]) => `<button class="btn btn-ghost btn-lg" data-m="${k}">${l}</button>`).join("")}</div></div>
          <div><div class="label">Bölüştürme</div><div class="flex flex-wrap gap-2" data-modes>${[["full", "Tamamı"], ["partial", "Özel tutar"], ["equal", "Eşit böl"], ["items", "Ürün bazlı"]].map(([k, l]) => `<button class="chip" data-md="${k}">${l}</button>`).join("")}</div></div>
          <div data-mode-ui></div>
          <div><label class="label">Tahsil edilecek tutar</label><input class="input text-xl font-bold" data-amount type="number" step="0.01" inputmode="decimal"></div>
          <div data-cash><label class="label">Alınan nakit</label><input class="input" data-tendered type="number" step="0.01" inputmode="decimal"><div class="flex gap-2 mt-2 flex-wrap" data-quick></div><div class="mt-2 font-semibold" data-change></div></div>
          <div data-ref class="hidden"><label class="label">POS slip / provizyon no (isteğe bağlı)</label><input class="input" data-reference></div>
          <div data-cust class="hidden"><label class="label">Müşteri (açık hesap)</label><select class="input" data-customer></select></div>
        </div></div>`);
      const amount = qs("[data-amount]", body), tendered = qs("[data-tendered]", body);
      const selectedLines = new Set();
      const setAmount = (v) => { amount.value = Number(v).toFixed(2); calcChange(); };
      const calcChange = () => { const ch = Number(tendered.value || 0) - Number(amount.value || 0); qs("[data-change]", body).innerHTML = method === "cash" && tendered.value ? (ch >= 0 ? `Para üstü: <span style="color:var(--ok)">${money(ch)}</span>` : `<span style="color:var(--bad)">Eksik: ${money(-ch)}</span>`) : ""; };
      const renderMode = async () => {
        qsa("[data-md]", body).forEach((b) => b.classList.toggle("active", b.dataset.md === mode));
        const ui = qs("[data-mode-ui]", body);
        ui.innerHTML = "";
        amount.readOnly = mode === "items" || mode === "full";
        if (mode === "full") setAmount(prev.remaining);
        if (mode === "partial") { amount.readOnly = false; amount.focus(); }
        if (mode === "equal") {
          ui.innerHTML = `<div class="flex items-center gap-2"><span class="label !mb-0">Kişi sayısı</span>${[2, 3, 4, 5, 6].map((n) => `<button class="chip" data-n="${n}">${n}</button>`).join("")}</div>`;
          qsa("[data-n]", ui).forEach((b) => (b.onclick = async () => { qsa("[data-n]", ui).forEach((x) => x.classList.remove("active")); b.classList.add("active"); const r = await J.get(`tickets/${id}/split_preview?parts=${b.dataset.n}`); setAmount(r.shares[0]); }));
        }
        if (mode === "items") {
          const lines = prev.by_seat.flatMap((s) => s.lines.map((l) => ({ ...l, seat: s.seat })));
          ui.innerHTML = `<div class="max-h-48 overflow-y-auto space-y-1 card p-2">${lines.map((l) => `<label class="flex items-center gap-2 text-sm min-h-[36px]"><input type="checkbox" class="w-5 h-5" value="${l.id}" data-due="${l.due}"><span class="flex-1">${l.seat ? `<span class="muted">K${l.seat}</span> ` : ""}${J.num(l.qty)} × ${esc(l.name)}</span><b class="tabular-nums">${money(l.due)}</b></label>`).join("") || '<div class="muted text-sm">Ödenmemiş ürün yok</div>'}</div>
            ${prev.by_seat.filter((s) => s.seat).length ? `<div class="flex gap-2 mt-2 flex-wrap">${prev.by_seat.filter((s) => s.seat).map((s) => `<button class="chip" data-seat="${s.seat}">Kişi ${s.seat}: ${money(s.amount)}</button>`).join("")}</div>` : ""}`;
          const sync = () => { selectedLines.clear(); let sum = 0; qsa("input[type=checkbox]", ui).forEach((c) => { if (c.checked) { selectedLines.add(Number(c.value)); sum += Number(c.dataset.due); } }); setAmount(sum); };
          qsa("input[type=checkbox]", ui).forEach((c) => (c.onchange = sync));
          qsa("[data-seat]", ui).forEach((b) => (b.onclick = () => { const ids = prev.by_seat.find((s) => String(s.seat) === b.dataset.seat).lines.map((l) => String(l.id)); qsa("input[type=checkbox]", ui).forEach((c) => (c.checked = ids.includes(c.value))); sync(); }));
          setAmount(0);
        }
      };
      const renderMethod = async () => {
        qsa("[data-m]", body).forEach((b) => { const a = b.dataset.m === method; b.style.borderColor = a ? "var(--accent)" : ""; b.style.background = a ? "color-mix(in srgb,var(--accent) 16%,transparent)" : ""; b.setAttribute("aria-pressed", a); });
        qs("[data-cash]", body).classList.toggle("hidden", method !== "cash");
        qs("[data-ref]", body).classList.toggle("hidden", !["card", "meal_card"].includes(method));
        const cust = qs("[data-cust]", body);
        cust.classList.toggle("hidden", method !== "open_account");
        if (method === "open_account" && !qs("[data-customer]", body).options.length) {
          if (!J.hasModule("crm")) { cust.innerHTML = `<p class="text-sm" style="color:var(--bad)">Açık hesap için CRM modülü gerekli.</p>`; return; }
          const list = await J.get("customers").catch(() => []);
          qs("[data-customer]", body).innerHTML = list.map((c) => `<option value="${c.id}" ${tk.customer === c.id ? "selected" : ""}>${esc(c.name)} · ${esc(c.phone)} (bakiye ${money(c.balance)})</option>`).join("");
        }
      };
      qsa("[data-m]", body).forEach((b) => (b.onclick = () => { method = b.dataset.m; renderMethod(); calcChange(); }));
      qsa("[data-md]", body).forEach((b) => (b.onclick = () => { mode = b.dataset.md; renderMode(); }));
      tendered.oninput = calcChange; amount.oninput = calcChange;
      const quick = qs("[data-quick]", body);
      [50, 100, 200, 500, 1000].forEach((v) => { const b = h(`<button class="chip">${v}</button>`); b.onclick = () => { tendered.value = v; calcChange(); }; quick.appendChild(b); });
      const exact = h(`<button class="chip">Tam</button>`); exact.onclick = () => { tendered.value = amount.value; calcChange(); }; quick.prepend(exact);
      renderMethod(); renderMode();
      const idem = J.uid();
      J.modal({ title: `Ödeme — #${tk.number}`, body, size: "max-w-4xl", actions: [{ label: "İptal" }, { label: "Ödemeyi al", cls: "btn-primary btn-lg", run: async () => {
        const payload = { method, amount: amount.value, split_mode: mode === "full" ? "full" : mode, tendered: method === "cash" ? tendered.value || amount.value : undefined,
          reference: qs("[data-reference]", body).value, customer: method === "open_account" ? Number(qs("[data-customer]", body).value) : undefined };
        if (mode === "items") { payload.lines = [...selectedLines]; delete payload.amount; if (!payload.lines.length) { J.toast("Ürün seçin", "warn"); return false; } }
        const r = await J.post(`tickets/${id}/pay`, payload, { idem });
        tk = r;
        const ch = Number(r.payment.change);
        J.toast(`Ödeme alındı: ${money(r.payment.amount)}${ch ? ` · Para üstü ${money(ch)}` : ""}`, "ok", 7000);
        renderTicket();
        if (r.status === "closed") J.go("/floor");
      } }] });
    };

    try {
      tk = await J.get(`tickets/${id}`);
      localStorage.setItem(`jet.ticket.${id}`, JSON.stringify(tk));
    } catch (e) {
      if (e instanceof J.ApiError) throw e;
      tk = JSON.parse(localStorage.getItem(`jet.ticket.${id}`) || "null");
      if (!tk) throw e;
      J.toast("Çevrimdışı: son bilinen adisyon gösteriliyor", "warn");
    }
    await loadMenu();
    renderTicket();
    if (innerWidth >= 1024) { tcol.classList.remove("hidden"); }
    const reload = J.debounce(async () => { try { tk = await J.get(`tickets/${id}`); renderTicket(); } catch (e) {} }, 300);
    const key = (e) => {
      if (qs("#modal-root").children.length) return;
      if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); send().catch(J.err); }
      if (e.key === "F9") { e.preventDefault(); if (J.can("payment.take")) payModal().catch(J.err); }
    };
    document.addEventListener("keydown", key);
    const offs = [J.on("ws:table", (d) => d.ticket === Number(id) && reload()), J.on("queue-sent", reload), J.on("queue-failed", reload), J.on("queue", () => renderTicket())];
    return () => { document.removeEventListener("keydown", key); offs.forEach((f) => f()); main.classList.remove("!p-0"); };
  };

  // ================================================================== KDS
  P.kds = async (main) => {
    const stations = await J.get("stations");
    let station = localStorage.getItem("jet.station") || (J.can("kds.manage") ? "" : String(stations[0]?.id || ""));
    let done = false;
    const head = h(`<div class="flex flex-wrap items-center gap-2 mb-3"><h1 class="text-2xl font-bold mr-2">${t("Mutfak")}</h1><div class="flex gap-2 flex-wrap" data-st></div><div class="flex-1"></div>
      <button class="chip" data-done>Son hazırlananlar</button><button class="btn btn-ghost btn-sm" data-fs>⛶ Tam ekran</button></div>`);
    const grid = h(`<div class="grid sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-3"></div>`);
    main.append(head, grid);
    const renderSt = () => {
      const c = qs("[data-st]", head);
      c.innerHTML = "";
      const opts = [...(J.can("kds.manage") ? [["", "Tümü (merkezi)"]] : []), ...stations.map((s) => [String(s.id), s.name])];
      opts.forEach(([k, l]) => { const b = h(`<button class="chip ${station === k ? "active" : ""}">${esc(l)}</button>`); b.onclick = () => { station = k; localStorage.setItem("jet.station", k); renderSt(); load(); }; c.appendChild(b); });
    };
    let orders = [];
    const render = () => {
      grid.innerHTML = orders.length ? "" : `<div class="col-span-full card p-10 text-center muted text-lg">${done ? "Son 2 saatte hazırlanan yok" : "Bekleyen sipariş yok ✓"}</div>`;
      orders.forEach((o) => {
        const late = o.late, prep = o.status === "preparing";
        const card = h(`<article class="card flex flex-col ${late ? "ring-4" : ""}" style="${late ? "--tw-ring-color:var(--bad);" : ""}border-top:6px solid ${late ? "var(--bad)" : prep ? "var(--warn)" : "var(--info)"}" aria-label="Sipariş ${o.ticket_number}">
          <header class="p-3 flex items-start gap-2 border-b bd"><div class="flex-1"><div class="text-2xl font-black">${o.table_name ? "Masa " + esc(o.table_name) : esc(o.channel)} </div><div class="text-xs muted">#${o.ticket_number} · Parti ${o.batch_number} · ${esc(o.waiter)} · ${esc(o.station_name)}</div></div>
          <div class="text-right"><div class="text-2xl font-bold tabular-nums" style="color:${late ? "var(--bad)" : "inherit"}">${o.elapsed}′</div>${o.priority ? J.badge("Öncelik " + o.priority, "var(--accent)") : ""}</div></header>
          <ul class="p-3 space-y-2 flex-1 text-lg">${o.lines.map((l) => `<li class="${l.void ? "line-through opacity-60" : ""}"><b>${J.num(l.qty)}×</b> ${esc(l.name)}${l.void ? ` <span class="badge" style="background:var(--bad);color:#fff">İPTAL</span>` : ""}${l.options.length ? `<div class="text-sm muted pl-6">${l.options.map(esc).join(", ")}</div>` : ""}${l.note ? `<div class="text-sm pl-6 font-semibold" style="color:var(--warn)">⚠ ${esc(l.note)}</div>` : ""}</li>`).join("")}</ul>
          <footer class="p-3 grid grid-cols-2 gap-2 border-t bd" data-f></footer></article>`);
        const f = qs("[data-f]", card);
        if (!done) {
          if (o.status === "new") { const b = h(`<button class="btn btn-ghost btn-lg">${t("Başla")}</button>`); b.onclick = () => J.post(`kitchen/${o.id}/start`).then(load).catch(J.err); f.appendChild(b); }
          const r = h(`<button class="btn btn-ok btn-lg ${o.status === "new" ? "" : "col-span-2"}">✓ ${t("Hazır")}</button>`);
          r.onclick = () => J.post(`kitchen/${o.id}/ready`).then(() => { J.toast(`Masa ${o.table_name || o.ticket_number} hazır işaretlendi`, "ok"); load(); }).catch(J.err);
          f.appendChild(r);
          if (J.can("kds.manage")) {
            const up = h(`<button class="btn btn-ghost btn-sm">▲ Öncelik</button>`); up.onclick = () => J.post(`kitchen/${o.id}/priority`, { priority: o.priority + 1 }).then(load).catch(J.err);
            const all = h(`<button class="btn btn-ghost btn-sm">Tüm partiyi hazırla</button>`); all.onclick = () => J.post(`kitchen/${o.id}/ready_all`).then(load).catch(J.err);
            f.append(up, all);
          }
        } else f.innerHTML = `<div class="col-span-2 text-sm muted">Hazır: ${J.dt(o.ready_at)}</div>`;
        grid.appendChild(card);
      });
    };
    const load = async () => { orders = await J.get(`kitchen?${station ? "station=" + station : ""}${done ? "&done=1" : ""}`); render(); };
    qs("[data-done]", head).onclick = (e) => { done = !done; e.target.classList.toggle("active", done); load(); };
    qs("[data-fs]", head).onclick = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen?.());
    renderSt();
    await load();
    const tick = setInterval(() => { orders.forEach((o) => (o.elapsed += 0)); load().catch(() => {}); }, 30000);
    const offs = [J.on("ws:kitchen", (d) => { if (d.action === "new" || d.action === "void") J.beep(d.action === "void" ? [440, 0.3, 330, 0.3] : [660, 0.12, 990, 0.12]); load().catch(() => {}); })];
    return () => { clearInterval(tick); offs.forEach((f) => f()); };
  };

  // ================================================================== HAZIR SİPARİŞLER
  P.ready = async (main) => {
    let mine = J.state.me.role === "waiter";
    main.appendChild(J.pageHead("Hazır siparişler", "Mutfaktan çıkan siparişler; teslim aldığınızda işaretleyin.", `<button class="chip ${mine ? "active" : ""}" data-mine>Yalnızca benimkiler</button>`));
    const list = h(`<div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-3"></div>`);
    main.appendChild(list);
    const load = async () => {
      const rows = await J.get(`ready-orders${mine ? "?mine=1" : ""}`);
      list.innerHTML = rows.length ? "" : `<div class="col-span-full card p-10 text-center muted">Hazır sipariş yok</div>`;
      rows.forEach((b) => {
        const c = h(`<div class="card p-4 flex flex-col gap-2" style="border-left:6px solid var(--accent)"><div class="flex items-center"><div class="text-2xl font-black flex-1">${esc(b.table)}</div><span class="text-sm muted">${b.minutes} dk önce</span></div><div class="text-xs muted">#${b.ticket_number} · Parti ${b.number} · ${esc(b.waiter)}</div><ul class="text-sm">${b.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul><button class="btn btn-ok btn-lg mt-auto">✓ Teslim aldım</button></div>`);
        qs("button", c).onclick = () => J.post("ready-orders", { batch: b.id }).then(load).catch(J.err);
        list.appendChild(c);
      });
    };
    qs("[data-mine]", main).onclick = (e) => { mine = !mine; e.target.classList.toggle("active", mine); load(); };
    await load();
    return J.on("ws:ready", () => load().catch(() => {}));
  };

  // ================================================================== ONAYLAR
  P.approvals = async (main) => {
    let status = "pending";
    main.appendChild(J.pageHead("Onaylar", "İndirim, iptal, müşteri grubu ve iade talepleri", `<select class="input !w-auto" data-s><option value="pending">Bekleyen</option><option value="all">Tümü</option></select>`));
    const box = h(`<div class="card"></div>`);
    main.appendChild(box);
    const load = async () => {
      const rows = await J.get(`approvals?status=${status}`);
      box.innerHTML = "";
      box.appendChild(J.table([
        { key: "created_at", label: "Zaman", fmt: J.dt }, { key: "kind_label", label: "Tür" },
        { key: "ticket_number", label: "Adisyon", html: (r) => r.ticket ? `<a href="/ticket/${r.ticket}" data-link class="underline">#${r.ticket_number}</a> ${r.table_name ? "· Masa " + esc(r.table_name) : ""}` : "" },
        { key: "payload", label: "Detay", fmt: (v) => Object.entries(v || {}).map(([k, x]) => `${k}: ${x}`).join(" · ") },
        { key: "reason", label: "Gerekçe" }, { key: "requested_by_name", label: "Talep eden" },
        { key: "status", label: "Durum", html: (r) => r.status === "pending" ? J.badge("Bekliyor", "var(--warn)") : r.status === "approved" ? J.badge("Onaylandı · " + r.decided_by_name, "var(--ok)") : J.badge("Reddedildi · " + r.decided_by_name, "var(--bad)") }],
        rows, { actions: [
          { label: "Onayla", show: (r) => r.status === "pending" && r.requested_by !== J.state.me.id, run: async (r) => { await J.post(`approvals/${r.id}/approve`).catch(J.err); load(); } },
          { label: "Reddet", show: (r) => r.status === "pending" && r.requested_by !== J.state.me.id, run: async (r) => { const v = await J.promptForm("Reddet", [{ name: "note", label: "Not" }]); if (v) { await J.post(`approvals/${r.id}/reject`, v).catch(J.err); load(); } } }] }));
    };
    qs("[data-s]", main).onchange = (e) => { status = e.target.value; load(); };
    await load();
    return J.on("ws:notification", (n) => n.event === "approval_request" && load().catch(() => {}));
  };

  // ================================================================== KASA / GÜN SONU
  P.cash = async (main) => {
    main.appendChild(J.pageHead("Kasa", "Günlük tek kasa çekmecesi · açılış, hareketler, sayım ve gün sonu"));
    const body = h(`<div></div>`);
    main.appendChild(body);
    const reportHtml = (r) => `<div class="grid md:grid-cols-2 gap-4 text-sm">
      <div class="card p-4"><h3 class="font-semibold mb-2">Ödeme türleri</h3>${Object.values(r.payments).map((p) => `<div class="flex justify-between py-1 border-b bd"><span>${esc(p.label)} <span class="muted">(${p.count})</span></span><span class="tabular-nums">${money(p.amount)}${Number(p.refunds) ? ` <span style="color:var(--bad)">−${money(p.refunds)}</span>` : ""}</span></div>`).join("")}
        <div class="flex justify-between pt-2 font-bold"><span>Net tahsilat</span><span>${money(r.net_collections)}</span></div></div>
      <div class="card p-4"><h3 class="font-semibold mb-2">Nakit</h3>${[["Açılış", r.cash.opening], ["Nakit satış", r.cash.sales], ["Nakit iade", r.cash.refunds], ["Gider", r.cash.expenses], ["Kasadan çıkış", r.cash.withdrawals], ["Kasaya giriş", r.cash.deposits]].map(([l, v]) => `<div class="flex justify-between py-1 border-b bd"><span>${l}</span><span class="tabular-nums">${money(v)}</span></div>`).join("")}
        <div class="flex justify-between pt-2 font-bold"><span>Beklenen</span><span>${money(r.cash.expected)}</span></div>
        ${r.cash.counted !== null ? `<div class="flex justify-between"><span>Sayılan</span><span>${money(r.cash.counted)}</span></div><div class="flex justify-between font-bold" style="color:${Number(r.cash.difference) ? "var(--bad)" : "var(--ok)"}"><span>Fark</span><span>${money(r.cash.difference)}</span></div>${r.cash.difference_reason ? `<div class="muted">Neden: ${esc(r.cash.difference_reason)}</div>` : ""}` : ""}</div>
      <div class="card p-4 md:col-span-2 grid grid-cols-2 md:grid-cols-5 gap-3">${[["Kapanan adisyon", r.tickets_closed], ["Açık adisyon", r.tickets_open], ["İptal adisyon", r.tickets_cancelled], ["İndirim", money(r.discount_total)], ["Ürün iptali", `${r.void_count} · ${money(r.void_amount)}`]].map(([l, v]) => `<div><div class="text-xs muted">${l}</div><div class="font-bold">${v}</div></div>`).join("")}</div></div>`;
    const load = async () => {
      const d = await J.get("cash");
      body.innerHTML = "";
      const cur = d.current;
      if (!cur) {
        const f = h(`<div class="card p-6 max-w-md"><h2 class="text-lg font-bold mb-1">Gün başı kasa açılışı</h2><p class="text-sm muted mb-4">Ödeme almak için kasanın açık olması gerekir.</p><label class="label">Açılış bakiyesi (nakit)</label><input class="input text-xl" type="number" step="0.01" min="0" value="0"><button class="btn btn-primary btn-lg w-full mt-4">Kasayı aç</button></div>`);
        qs("button", f).onclick = () => J.post("cash", { action: "open", opening_balance: qs("input", f).value }).then(load).catch(J.err);
        body.appendChild(f);
      } else {
        const top = h(`<div class="flex flex-wrap gap-3 mb-4">
          <div class="card p-4 flex-1 min-w-[180px]"><div class="text-xs muted">Durum</div><div class="text-xl font-bold">${esc(cur.status_label)}</div><div class="text-xs muted">${J.d(cur.business_date)} · açan ${esc(cur.opened_by_name)}</div></div>
          <div class="card p-4 flex-1 min-w-[180px]"><div class="text-xs muted">Beklenen nakit</div><div class="text-2xl font-bold tabular-nums">${money(cur.expected_now)}</div></div>
          <div class="flex flex-wrap gap-2 items-center" data-acts></div></div>`);
        const acts = qs("[data-acts]", top);
        const B = (l, cls, fn) => { const b = h(`<button class="btn ${cls}">${l}</button>`); b.onclick = () => fn().catch(J.err); acts.appendChild(b); };
        if (cur.status === "open") {
          B("+ Kasa hareketi", "btn-ghost", async () => {
            const v = await J.promptForm("Kasa hareketi", [{ name: "kind", label: "Tür", type: "select", required: true, options: [["expense", "Gider"], ["withdrawal", "Kasadan çıkış"], ["deposit", "Kasaya giriş"]] }, { name: "amount", label: "Tutar", type: "money", required: true }, { name: "reason", label: "Açıklama/gerekçe", required: true, minLength: 3 }]);
            if (v) { await J.post("cash", { action: "movement", ...v }); load(); }
          });
          B("Kasa sayımı / gün sonu", "btn-primary", async () => {
            const v = await J.promptForm("Kasa sayımı", [{ name: "counted", label: "Sayılan nakit", type: "money", required: true }, { name: "reason", label: "Fark nedeni (fark varsa zorunlu)", type: "textarea" }]);
            if (!v) return;
            try { await J.post("cash", { action: "count", ...v }); J.toast("Gün sonu raporu oluşturuldu; yönetici onayı bekleniyor", "ok"); load(); }
            catch (e) { J.err(e); }
          });
        }
        if (cur.status === "pending_approval" && J.can("cash.approve")) {
          B("✓ Gün sonunu onayla ve kapat", "btn-ok", async () => { if (await J.confirm("Gün sonu onaylanıp kasa kapatılsın mı?")) { await J.post("cash", { action: "approve" }); J.toast("Gün kapatıldı; rapor arşivlendi", "ok"); load(); } });
          B("Sayımı reddet", "btn-ghost", async () => { const v = await J.askReason("Sayımı reddet (yeniden sayım)"); if (v) { await J.post("cash", { action: "reject", ...v }); load(); } });
        }
        body.appendChild(top);
        body.appendChild(h(`<h2 class="font-semibold mb-2">${cur.status === "open" ? "Anlık gün raporu" : "Gün sonu raporu"}</h2>`));
        body.appendChild(h(`<div>${reportHtml(cur.status === "open" ? d.live_report : cur.report)}</div>`));
        const mv = h(`<div class="card mt-4"><h2 class="font-semibold p-3 border-b bd">Kasa hareketleri (kullanıcı bazında)</h2></div>`);
        mv.appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "kind_label", label: "Tür" }, { key: "amount", label: "Tutar", right: true, fmt: money }, { key: "reason", label: "Açıklama" }, { key: "user_name", label: "Kullanıcı" }], d.movements));
        body.appendChild(mv);
      }
      const hist = h(`<div class="card mt-4"><h2 class="font-semibold p-3 border-b bd">Arşiv — kapanmış günler</h2></div>`);
      hist.appendChild(J.table([{ key: "business_date", label: "Tarih", fmt: J.d }, { key: "opening_balance", label: "Açılış", right: true, fmt: money }, { key: "expected_cash", label: "Beklenen", right: true, fmt: money }, { key: "counted_cash", label: "Sayılan", right: true, fmt: money }, { key: "difference", label: "Fark", right: true, fmt: money }, { key: "approved_by_name", label: "Onaylayan" }], d.history, {
        onRow: async (r) => { const rep = await J.get(`cash/days/${r.id}`); const m = J.modal({ title: `Gün sonu — ${J.d(r.business_date)}`, size: "max-w-4xl", body: reportHtml(rep.report), actions: [{ label: "Yazdır", run: () => { window.print(); return false; } }, { label: "Kapat" }] }); void m; } }));
      body.appendChild(hist);
    };
    await load();
  };

  // ================================================================== ÖDEMELER
  P.payments = async (main) => {
    let date = J.today();
    main.appendChild(J.pageHead("Ödemeler", "Tahsilatlar ve yöntem bazlı iade", `<input type="date" class="input !w-auto" value="${date}" data-d>`));
    const box = h(`<div class="card"></div>`);
    main.appendChild(box);
    const load = async () => {
      const rows = await J.get(`payments?date=${date}`);
      box.innerHTML = "";
      box.appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "ticket_number", label: "Adisyon", html: (r) => `<a class="underline" data-link href="/ticket/${r.ticket}">#${r.ticket_number}</a>` }, { key: "method_label", label: "Yöntem" }, { key: "split_mode", label: "Bölme" }, { key: "amount", label: "Tutar", right: true, fmt: money }, { key: "refunded_amount", label: "İade", right: true, fmt: money }, { key: "user_name", label: "Kasiyer" }, { key: "reference", label: "Referans" }], rows, {
        actions: [{ label: "İade", show: (r) => Number(r.refundable) > 0, run: async (r) => {
          const v = await J.promptForm(`İade — ${r.method_label} ${money(r.amount)}`, [{ name: "amount", label: `Tutar (en fazla ${money(r.refundable)})`, type: "money", required: true, default: r.refundable }, { name: "restock", label: "Ürünleri stoğa geri al (iptal edilen ürün varsa)", type: "checkbox" }, { name: "reason", label: "Gerekçe", type: "textarea", required: true, minLength: 3 }]);
          if (!v) return;
          const idem = J.uid();
          const res = await J.withApproval((extra) => J.post(`payments/${r.id}/refund`, { ...v, ...extra }, { idem: extra.request_approval ? J.uid() : idem })).catch(J.err);
          if (res) { J.toast(res.pending ? "İade onaya gönderildi" : "İade kaydedildi (ters kayıt)", "ok"); load(); }
        } }] }));
    };
    qs("[data-d]", main).onchange = (e) => { date = e.target.value; load(); };
    await load();
  };

  // ================================================================== ADİSYON GEÇMİŞİ
  P.tickets = async (main) => {
    let date = J.today(), status = "";
    main.appendChild(J.pageHead("Adisyonlar", "Geçmiş ve açık adisyonlar", `<input type="date" class="input !w-auto" value="${date}" data-d><select class="input !w-auto" data-s><option value="">Tümü</option><option value="open">Açık</option><option value="bill_requested">Hesap istendi</option><option value="paid">Ödendi</option><option value="closed">Kapandı</option><option value="cancelled">İptal</option></select>`));
    const box = h(`<div class="card"></div>`);
    main.appendChild(box);
    const load = async () => {
      const rows = await J.get(`tickets?date=${date}${status ? "&status=" + status : ""}`);
      box.innerHTML = "";
      box.appendChild(J.table([{ key: "number", label: "No", fmt: (v) => "#" + v }, { key: "table_name", label: "Masa" }, { key: "channel", label: "Kanal" }, { key: "waiter_name", label: "Garson" }, { key: "status_label", label: "Durum" }, { key: "opened_at", label: "Açılış", fmt: J.dt }, { key: "discount_total", label: "İndirim", right: true, fmt: money }, { key: "total", label: "Toplam", right: true, fmt: money }], rows, { onRow: (r) => J.go(`/ticket/${r.id}`) }));
    };
    qs("[data-d]", main).onchange = (e) => { date = e.target.value; load(); };
    qs("[data-s]", main).onchange = (e) => { status = e.target.value; load(); };
    await load();
  };

  // ================================================================== GARSON PWA
  P.waiter = async (main) => {
    J.state.isWaiterMode = true;
    const head = h(`<div class="flex items-center gap-2 mb-3"><h1 class="text-xl font-bold flex-1">Garson</h1><a href="/ready" data-link class="btn btn-ghost btn-sm" data-ready>🔔 Hazır <b data-rc>0</b></a></div>`);
    const halls = h(`<div class="flex gap-2 overflow-x-auto pb-2"></div>`);
    const grid = h(`<div class="grid grid-cols-3 sm:grid-cols-4 gap-2"></div>`);
    main.append(head, halls, grid);
    let data, hall = Number(localStorage.getItem("jet.hall")) || null;
    const render = () => {
      halls.innerHTML = "";
      if (!data.halls.find((x) => x.id === hall)) hall = data.halls[0]?.id;
      data.halls.forEach((x) => { const b = h(`<button class="chip ${x.id === hall ? "active" : ""}">${esc(x.name)}</button>`); b.onclick = () => { hall = x.id; localStorage.setItem("jet.hall", hall); render(); }; halls.appendChild(b); });
      grid.innerHTML = "";
      data.tables.filter((x) => x.hall === hall).sort(natural).forEach((tb) => {
        const [label] = STATUS[tb.status];
        const b = h(`<button class="tile table-card st-${tb.status} p-2 min-h-[92px]"><div class="text-2xl font-black">${esc(tb.name)}</div><div class="text-[11px] font-semibold" style="color:var(--st)">${esc(t(label))}</div>${tb.ticket ? `<div class="mt-auto text-sm font-bold">${money(tb.ticket.total)}</div>${tb.ticket.ready ? `<span class="badge pulse" style="background:var(--accent);color:var(--accent-ink)">Hazır</span>` : ""}` : ""}</button>`);
        b.onclick = async () => {
          try { if (tb.ticket) return J.go(`/ticket/${tb.ticket.id}`); const tk = await J.post(`tables/${tb.id}/open`, {}); J.go(`/ticket/${tk.id}`); }
          catch (e) { J.err(e); }
        };
        grid.appendChild(b);
      });
      qs("[data-rc]", head).textContent = data.tables.reduce((a, x) => a + (x.ticket?.ready || 0), 0);
    };
    const load = async () => {
      try { data = await J.get("floor"); localStorage.setItem("jet.floor", JSON.stringify(data)); }
      catch (e) { if (e instanceof J.ApiError) throw e; data = JSON.parse(localStorage.getItem("jet.floor") || "null"); if (!data) throw e; J.toast("Çevrimdışı: son bilinen masa durumu", "warn"); }
      render();
    };
    await load();
    const offs = [J.on("ws:table", J.debounce(() => load().catch(() => {}), 400)), J.on("ws:ready", () => load().catch(() => {}))];
    return () => { offs.forEach((f) => f()); };
  };
})();
