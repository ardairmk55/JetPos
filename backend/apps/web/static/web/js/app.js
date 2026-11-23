/* JETPOS uygulama kabuğu: gruplu rol bazlı menü, yönlendirme, arama, bildirim, kilit, kısayollar. */
(function () {
  const { esc, h, qs, qsa, t, tt } = J;

  // ------------------------------------------------------------------ menü yapısı (yalnızca gerçek modüller)
  // tab: aynı sayfanın belirli sekmesi · exclude: bu sekmeler başka bir menü öğesine ait
  const NAV = [
    { title: "Genel", items: [
      { path: "/", label: "Ana Sayfa", icon: "layout-dashboard", page: "dashboard" },
      { action: "search", label: "Arama", icon: "search", key: "/" },
      { path: "/notifications", label: "Bildirimler", icon: "bell", page: "notifications", badge: true },
    ] },
    { title: "Operasyon", items: [
      { path: "/floor", label: "Masalar", icon: "layout-grid", page: "floor", perm: "floor.view", key: "F2" },
      { path: "/waiter", label: "Garson", icon: "smartphone", page: "waiter", perm: "ticket.open" },
      { path: "/kds", label: "Mutfak", icon: "chef-hat", page: "kds", perm: "kds.view", key: "F3" },
      { path: "/ready", label: "Hazır Siparişler", icon: "bell-ring", page: "ready", perm: "ready.view" },
      { path: "/approvals", label: "Onaylar", icon: "circle-check", page: "approvals", any: ["approvals.decide", "approvals.municipal"] },
      { path: "/tickets", label: "Adisyonlar", icon: "receipt", page: "tickets", perm: "floor.view" },
    ] },
    { title: "Satış ve Finans", items: [
      { path: "/cash", label: "Kasa", icon: "wallet", page: "cash", perm: "cash.manage", key: "F4" },
      { path: "/payments", label: "Ödemeler", icon: "credit-card", page: "payments", perm: "payment.take" },
      { path: "/finance", label: "Finans", icon: "trending-up", page: "finance", perm: "finance.manage", module: "finance" },
      { path: "/reports", label: "Raporlar", icon: "chart-column", page: "reports", perm: "reports.view" },
    ] },
    { title: "İşletme Yönetimi", items: [
      { path: "/catalog", label: "Katalog", icon: "book-open", page: "catalog", perm: "catalog.manage", exclude: ["products", "categories"], children: [
        { path: "/catalog?tab=products", label: "Ürünler" },
        { path: "/catalog?tab=categories", label: "Kategoriler" },
      ] },
      { path: "/stock", label: "Stok", icon: "package", page: "stock", perm: "stock.view", module: "stock" },
      { path: "/customers", label: "Müşteriler", icon: "users", page: "customers", perm: "crm.manage", module: "crm" },
      { path: "/deliveries", label: "Kurye", icon: "bike", page: "deliveries", perm: "delivery.manage", module: "delivery" },
      { path: "/reservations", label: "Rezervasyonlar", icon: "calendar-days", page: "reservations", perm: "reservation.manage", module: "reservation" },
    ] },
    { title: "Organizasyon", items: [
      { path: "/staff", label: "Personel", icon: "id-card", page: "staff", perm: "staff.manage", module: "staff" },
      { path: "/settings?tab=business", label: "Şubeler", icon: "building-2", page: "settings", perm: "settings.manage" },
      { path: "/users", label: "Kullanıcılar", icon: "key-round", page: "users", perm: "users.manage" },
    ] },
    { title: "Sistem", items: [
      { path: "/settings?tab=jetmenu", label: "Entegrasyonlar", icon: "plug", page: "settings", perm: "settings.manage", module: "jetmenu" },
      { path: "/printers", label: "Yazıcılar", icon: "printer", page: "printers", perm: "printers.manage" },
      { path: "/ops?tab=backups", label: "Yedekleme", icon: "database-backup", page: "ops", any: ["ops.manage", "health.view"] },
      { path: "/ops", label: "Sistem Durumu", icon: "activity", page: "ops", any: ["ops.manage", "health.view"], exclude: ["backups"] },
      { path: "/settings", label: "Ayarlar", icon: "settings", page: "settings", exclude: ["business", "jetmenu"] },
      { path: "/audit", label: "Denetim Kaydı", icon: "scroll-text", page: "audit", perm: "audit.view" },
      { path: "/portal", label: "Müşteri Portalı", icon: "shield-check", page: "portal", perm: "settings.manage", business: true },
      { path: "/platform", label: "Platform", icon: "globe", page: "platform", any: ["platform.manage", "license.manage", "platform.finance"] },
      { path: "/support", label: "Destek", icon: "life-buoy", page: "support", any: ["support.request", "support.manage"] },
      { path: "/help", label: "Yardım", icon: "circle-help", page: "help" },
    ] },
  ];
  const EXTRA_PAGES = [{ path: "/timeclock", label: "Giriş / Çıkış", page: "timeclock" }];
  const ALL_ITEMS = NAV.flatMap((g) => g.items).filter((i) => i.path);
  const ROUTES = [[/^\/ticket\/(\d+)$/, "ticket", (m) => ({ id: m[1] })],
    ...[...ALL_ITEMS, ...EXTRA_PAGES].map((n) => [new RegExp(`^${n.path.split("?")[0].replace(/\//g, "\\/")}$`), n.page, () => ({})])];
  const pageLabel = (page) => (ALL_ITEMS.find((n) => n.page === page) || EXTRA_PAGES.find((n) => n.page === page) || { label: "Adisyon" }).label;

  const visible = (n) => (!n.perm || J.can(n.perm)) && (!n.any || n.any.some(J.can)) && (!n.module || J.hasModule(n.module)) && (!n.business || J.state.me.business);
  const canView = (page) => { const items = ALL_ITEMS.filter((n) => n.page === page); return !items.length || items.some(visible); };

  // ------------------------------------------------------------------ tercihler
  const updateThemeIcon = () => { const dark = document.documentElement.classList.contains("dark"); qs("#theme-btn").innerHTML = J.icon(dark ? "sun" : "moon", 18); qs("#theme-btn").setAttribute("aria-label", dark ? "Açık temaya geç" : "Koyu temaya geç"); };
  J.applyPrefs = (me) => {
    const root = document.documentElement;
    root.classList.toggle("dark", me.theme === "dark");
    root.classList.toggle("hc", !!me.high_contrast);
    root.style.setProperty("--font-scale", (me.font_scale || 100) / 100);
    root.lang = me.language || "tr";
    J.state.lang = me.language || "tr";
    try { localStorage.setItem("jet.theme", me.theme); } catch (e) {}
    qs("#lang-btn").textContent = (me.language || "tr").toUpperCase();
    qs("#gsearch").placeholder = me.language === "en" ? "Search tables, tickets, products, customers" : "Masa, adisyon, ürün, müşteri ara";
    updateThemeIcon();
  };

  // ------------------------------------------------------------------ menü
  const curTab = () => new URLSearchParams(location.search).get("tab");
  const isActive = (it) => {
    const u = new URL(it.path, location.origin);
    const p = location.pathname.replace(/\/$/, "") || "/";
    const here = u.pathname === "/" ? p === "/" : p === u.pathname || p.startsWith(u.pathname + "/");
    if (!here) return false;
    const tab = u.searchParams.get("tab");
    if (tab) return curTab() === tab;
    if (it.exclude) return !it.exclude.includes(curTab());
    return true;
  };
  const collapsed = () => qs("#app").classList.contains("side-collapsed");
  const navItem = (it, sub) => {
    if (it.action === "search") return `<button type="button" class="nav-item" data-action="search" title="${esc(t(it.label))}">${J.icon(it.icon, 18)}<span class="nav-label">${esc(t(it.label))}</span><kbd class="nav-kbd text-[10px] opacity-60">${it.key}</kbd></button>`;
    return `<a href="${it.path}" data-link class="nav-item${sub ? " sub" : ""}" data-nav="${esc(it.path)}" title="${esc(t(it.label))}">${sub ? "" : J.icon(it.icon, 18)}<span class="nav-label">${esc(t(it.label))}</span>${it.badge ? `<span class="nav-badge" id="nav-notif-badge" style="display:none">0</span>` : ""}${it.key ? `<kbd class="nav-kbd text-[10px] opacity-60">${it.key}</kbd>` : ""}</a>`;
  };
  let refreshBadge = null;
  const renderNav = () => {
    const groups = NAV.map((g) => ({ ...g, items: g.items.filter((i) => i.action || visible(i)) })).filter((g) => g.items.length);
    qs("#nav").innerHTML = groups.map((g) => `<div class="nav-group" role="group" aria-label="${esc(t(g.title))}"><div class="nav-title">${esc(t(g.title))}</div>${g.items.map((it) => navItem(it) + (it.children ? `<div data-children="${esc(it.path)}" hidden>${it.children.map((c) => navItem(c, true)).join("")}</div>` : "")).join("")}</div>`).join("");
    qsa("[data-action=search]").forEach((b) => (b.onclick = () => { closeDrawer(); qs("#gsearch").focus(); }));
    markActive();
    refreshBadge?.();
  };
  const markActive = () => {
    qsa("[data-nav]").forEach((a) => {
      const it = ALL_ITEMS.find((n) => n.path === a.dataset.nav) || NAV.flatMap((g) => g.items).flatMap((i) => i.children || []).find((c) => c.path === a.dataset.nav);
      if (it && isActive(it)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    qsa("[data-children]").forEach((c) => { c.hidden = !(c.querySelector("[aria-current]") || location.pathname.startsWith(c.dataset.children.split("?")[0])); });
  };
  window.addEventListener("jet:tab", markActive);

  const closeDrawer = () => { qs("#app").classList.remove("nav-open"); qs("#scrim").classList.add("hidden"); };
  const openDrawer = () => { qs("#app").classList.add("nav-open"); qs("#scrim").classList.remove("hidden"); };
  const setCollapsed = (c, persist = true) => {
    qs("#app").classList.toggle("side-collapsed", c);
    const b = qs("#collapse-btn");
    b.innerHTML = `${J.icon(c ? "chevrons-right" : "chevrons-left", 18)}<span class="nav-label">${t("Menüyü daralt")}</span>`;
    b.setAttribute("aria-label", c ? t("Menüyü genişlet") : t("Menüyü daralt"));
    b.title = c ? t("Menüyü genişlet") : t("Menüyü daralt");
    if (persist) try { localStorage.setItem("jet.side", c ? "1" : "0"); } catch (e) {}
  };

  // ------------------------------------------------------------------ yönlendirme
  let cleanup = null;
  J.go = (path, replace = false) => { (replace ? history.replaceState : history.pushState).call(history, null, "", path); route(); };
  const stateBox = (icon, title, text, action = "") => `<div class="card"><div class="empty"><div class="empty-ic">${J.icon(icon, 22)}</div><div class="empty-title">${esc(title)}</div><p>${esc(text)}</p>${action}</div></div>`;
  const route = async () => {
    const path = location.pathname.replace(/\/$/, "") || "/";
    const main = qs("#main");
    try { cleanup?.(); } catch (e) {}
    cleanup = null;
    main.innerHTML = "";
    main.className = "page";
    closeDrawer();
    let hit = null;
    for (const [re, page, args] of ROUTES) { const m = path.match(re); if (m) { hit = [page, args(m)]; break; } }
    markActive();
    if (!hit || !J.pages[hit[0]]) { main.innerHTML = stateBox("circle-alert", "Sayfa bulunamadı", "Adres hatalı veya sayfa kaldırılmış olabilir.", `<a class="btn btn-primary mt-2" href="/" data-link>Ana sayfaya dön</a>`); return; }
    if (!canView(hit[0])) { main.innerHTML = stateBox("lock", "Bu ekran için yetkiniz yok", "Menüler rolünüze göre gösterilir. Erişim gerekiyorsa yöneticinizle görüşün."); return; }
    document.title = `${tt(pageLabel(hit[0]))} — JETPOS`;
    main.innerHTML = `<div class="space-y-3" aria-busy="true"><div class="skeleton" style="height:28px;width:220px"></div><div class="skeleton" style="height:120px"></div><div class="skeleton" style="height:220px"></div></div>`;
    try {
      main.innerHTML = "";
      cleanup = (await J.pages[hit[0]](main, hit[1])) || null;
    } catch (e) {
      main.innerHTML = stateBox("triangle-alert", "Ekran yüklenemedi", e?.data?.detail || (navigator.onLine ? "Sunucuya ulaşılamadı. Bağlantıyı kontrol edip yeniden deneyin." : "İnternet/yerel ağ bağlantısı yok."), `<button class="btn btn-primary mt-2" onclick="location.reload()">Yeniden dene</button>`);
      if (!(e instanceof J.ApiError)) console.error(e);
    }
    main.focus({ preventScroll: true });
  };
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-link]");
    if (a && a.origin === location.origin && !e.ctrlKey && !e.metaKey && !e.shiftKey) { e.preventDefault(); J.go(a.pathname + a.search); }
  });
  window.addEventListener("popstate", route);

  // ------------------------------------------------------------------ global arama
  const setupSearch = () => {
    const inp = qs("#gsearch"), box = qs("#gsearch-res");
    qs("#search-ic").innerHTML = J.icon("search", 16);
    const icons = { table: "layout-grid", ticket: "receipt", product: "utensils", category: "book-open", staff: "user-round", customer: "users", payment: "credit-card", reservation: "calendar-days", stock: "package", history: "scroll-text" };
    const kinds = { table: "Masa", ticket: "Adisyon", product: "Ürün", category: "Kategori", staff: "Personel", customer: "Müşteri", payment: "Ödeme", reservation: "Rezervasyon", stock: "Stok", history: "Kayıt" };
    const show = (html) => { box.innerHTML = html; box.classList.toggle("hidden", !html); };
    const run = J.debounce(async () => {
      const q = inp.value.trim();
      try {
        const d = await J.get(`search?q=${encodeURIComponent(q)}`);
        if (!q) return show(d.recent?.length ? `<div class="px-3 py-1 text-xs muted">Son aramalar</div>${d.recent.map((r) => `<button class="menu-item" data-q="${esc(r)}">${J.icon("history", 16)}${esc(r)}</button>`).join("")}` : "");
        const rows = d.results.map((r) => `<a href="${esc(r.url)}" data-link class="menu-item" role="option">${J.icon(icons[r.kind] || "file-text", 16)}<span class="flex-1 min-w-0"><span class="block truncate font-medium">${esc(r.label)}</span><span class="block truncate text-xs muted">${esc(r.sub)}</span></span><span class="text-xs muted">${esc(t(kinds[r.kind] || r.kind))}</span></a>`).join("");
        const sug = d.suggestions?.length ? `<div class="px-3 py-2 text-xs muted border-t bd">Öneri: ${d.suggestions.map((s) => `<button class="underline mr-2" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : "";
        show(rows ? rows + sug : `<div class="px-3 py-4 text-sm muted">Sonuç bulunamadı. Aramanız rolünüzün yetkileriyle sınırlıdır.</div>${sug}`);
      } catch (e) { show(""); }
    }, 200);
    inp.addEventListener("input", run);
    inp.addEventListener("focus", run);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { const a = box.querySelector("a"); if (a) { e.preventDefault(); a.click(); } } if (e.key === "Escape") { show(""); inp.blur(); } });
    box.addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) { inp.value = b.dataset.q; run(); return; } if (e.target.closest("a")) { show(""); inp.value = ""; } });
    document.addEventListener("click", (e) => { if (!e.target.closest("#gsearch, #gsearch-res")) show(""); });
  };

  // ------------------------------------------------------------------ bildirimler
  const setupNotifications = () => {
    const btn = qs("#notif-btn"), panel = qs("#notif-panel"), count = qs("#notif-count");
    qs("#notif-ic").innerHTML = J.icon("bell", 18);
    refreshBadge = () => J.get("notifications/unread_count").then(({ count: n }) => {
      count.textContent = n > 99 ? "99+" : n; count.style.display = n ? "grid" : "none";
      const nb = qs("#nav-notif-badge"); if (nb) { nb.textContent = n > 99 ? "99+" : n; nb.style.display = n ? "inline-grid" : "none"; }
    }).catch(() => {});
    const refresh = () => refreshBadge();
    btn.onclick = async () => {
      if (!panel.classList.contains("hidden")) return panel.classList.add("hidden");
      const list = await J.get("notifications").catch(() => []);
      panel.innerHTML = `<div class="flex items-center px-3 py-2"><b class="flex-1 text-sm">${t("Bildirimler")}</b><button class="btn btn-quiet btn-sm" data-all>Tümünü okundu yap</button></div>` +
        (list.slice(0, 30).map((n) => `<button class="menu-item" style="align-items:flex-start;padding-top:.5rem;padding-bottom:.5rem" data-id="${n.id}" data-ticket="${n.data?.ticket || ""}"><span class="dot" style="--st:${n.read_at ? "var(--border-strong)" : "var(--accent)"};margin-top:.4rem"></span><span class="flex-1 min-w-0"><b class="block text-sm font-medium">${esc(n.title)}</b><span class="block text-xs muted">${esc(n.body)} · ${J.dt(n.created_at)}</span></span></button>`).join("") || `<div class="empty" style="padding:1.5rem 1rem"><div class="empty-ic">${J.icon("inbox", 20)}</div><p>Son 24 saatte bildirim yok.</p></div>`) +
        `<a href="/notifications" data-link class="block text-center text-sm p-2 underline muted">Tüm geçmiş</a>`;
      panel.classList.remove("hidden");
      qs("[data-all]", panel)?.addEventListener("click", async () => { await J.post("notifications/read_all"); panel.classList.add("hidden"); refresh(); });
      qsa("[data-id]", panel).forEach((b) => (b.onclick = async () => { await J.post(`notifications/${b.dataset.id}/read`).catch(() => {}); panel.classList.add("hidden"); refresh(); if (b.dataset.ticket) J.go(`/ticket/${b.dataset.ticket}`); }));
    };
    document.addEventListener("click", (e) => { if (!e.target.closest("#notif-btn, #notif-panel")) panel.classList.add("hidden"); });
    J.on("ws:notification", (n) => {
      refresh();
      J.toast(`${n.title}${n.body ? " — " + n.body : ""}`, n.priority === "high" ? "warn" : "info", n.priority === "high" ? 9000 : 5000);
      if (n.sound || n.priority === "high") J.beep(n.event === "order_ready" ? [880, 0.15, 1175, 0.15, 1568, 0.25] : undefined);
      if (document.hidden && "Notification" in window && Notification.permission === "granted") { try { new Notification(n.title, { body: n.body, tag: String(n.id), icon: "/static/web/img/icon.svg" }); } catch (e) {} }
    });
    J.on("notif-refresh", refresh);
    refresh();
    setInterval(refresh, 60000);
  };

  // ------------------------------------------------------------------ kilit ekranı ve PIN ile personel değişimi
  let lastAct = Date.now();
  const lockScreen = async (switchMode = false) => {
    const lock = qs("#lock");
    if (!switchMode) await J.post("auth/lock").catch(() => {});
    const users = await J.get("auth/pin-users").catch(() => []);
    let selected = switchMode ? null : J.state.me.id;
    lock.innerHTML = "";
    const box = h(`<div class="card p-6 w-full text-center" style="max-width:420px"><div class="flex items-center justify-center gap-2 mb-1"><span style="width:28px;height:28px;border-radius:6px;background:var(--accent);color:#1E222D;display:grid;place-items:center;font-weight:700;font-size:.8rem">J</span><b class="text-lg">JETPOS</b></div><p class="muted text-sm mb-4">${switchMode ? "Personel seçin ve PIN girin" : "Ekran kilitlendi. PIN ile devam edin."}</p>
      <div class="flex flex-wrap gap-2 justify-center mb-4" data-users></div><div data-pad></div><p class="mt-3 text-sm font-medium" style="color:var(--bad);min-height:1.25rem" data-err role="alert"></p>
      <div class="mt-3 flex justify-center gap-2"><button class="btn btn-ghost btn-sm" data-pw>Şifre ile aç</button><button class="btn btn-ghost btn-sm" data-out>Çıkış yap</button></div></div>`);
    const ul = qs("[data-users]", box);
    const drawUsers = () => { ul.innerHTML = ""; users.forEach((u) => { const b = h(`<button class="chip ${u.id === selected ? "active" : ""}">${esc(u.name)}</button>`); b.onclick = () => { selected = u.id; drawUsers(); }; ul.appendChild(b); }); };
    drawUsers();
    const pad = J.pinPad(async (pin) => {
      try {
        if (selected === J.state.me.id && !switchMode) await J.post("auth/unlock", { pin });
        else { if (!selected) throw new J.ApiError(400, { detail: "Önce personel seçin" }); await J.post("auth/pin-switch", { user_id: selected, pin }); location.reload(); return; }
        lock.classList.add("hidden"); lock.innerHTML = ""; lastAct = Date.now();
      } catch (e) { qs("[data-err]", box).textContent = e.data?.detail || "Hata"; pad.reset(); }
    }, { title: "PIN" });
    qs("[data-pad]", box).appendChild(pad);
    qs("[data-pw]", box).onclick = async () => { const v = await J.promptForm("Şifre ile kilidi aç", [{ name: "password", label: "Şifre", type: "password", required: true }]); if (v) { try { await J.post("auth/unlock", v); lock.classList.add("hidden"); lastAct = Date.now(); } catch (e) { J.err(e); } } };
    qs("[data-out]", box).onclick = async () => { await J.post("auth/logout").catch(() => {}); location.href = "/login/"; };
    lock.appendChild(box);
    lock.classList.remove("hidden");
    setTimeout(() => pad.focus(), 50);
  };
  J.lockScreen = lockScreen;
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, () => (lastAct = Date.now()), { passive: true }));
  J.on("locked", () => qs("#lock").classList.contains("hidden") && lockScreen());

  // ------------------------------------------------------------------ yan menü alt alanı, üst çubuk
  const initials = (me) => (((me.first_name || me.username || "?")[0] || "") + ((me.last_name || "")[0] || "")).toUpperCase();
  const setupHeader = () => {
    const me = J.state.me;
    const full = [me.first_name, me.last_name].filter(Boolean).join(" ") || me.username;
    qs("#user-avatar").textContent = initials(me);
    qs("#user-name").textContent = full;
    qs("#user-ctx").textContent = [me.business_name, me.branch_name].filter(Boolean).join(" · ") || me.role_label;
    qs("#user-chev").innerHTML = J.icon("chevron-down", 16);
    qs("#ctx").innerHTML = me.business_name ? `${J.icon("store", 16)}<span class="truncate font-medium" style="color:var(--text)">${esc(me.business_name)}</span>${me.branch_name ? `<span class="faint">/</span><span class="truncate">${esc(me.branch_name)}</span>` : ""}` : `<span>Platform yönetimi</span>`;
    qs("#menu-btn").innerHTML = J.icon("menu", 20);
    qs("#menu-btn").onclick = openDrawer;
    qs("#scrim").onclick = closeDrawer;
    qs("#nav").addEventListener("click", (e) => { if (e.target.closest("a")) closeDrawer(); });
    qs("#collapse-btn").onclick = () => setCollapsed(!collapsed());
    let stored = null; try { stored = localStorage.getItem("jet.side"); } catch (e) {}
    setCollapsed(stored === null ? innerWidth >= 1024 && innerWidth < 1280 : stored === "1", false);
    qs("#theme-btn").onclick = async () => { me.theme = me.theme === "dark" ? "light" : "dark"; J.applyPrefs(me); await J.post("auth/preferences", { theme: me.theme }).catch(() => {}); J.emit("theme"); };
    qs("#lang-btn").onclick = async () => { me.language = me.language === "en" ? "tr" : "en"; await J.post("auth/preferences", { language: me.language }).catch(() => {}); J.applyPrefs(me); renderNav(); setCollapsed(collapsed(), false); route(); };

    const um = qs("#user-menu"), ub = qs("#user-btn");
    const items = [["Tercihler", "sliders-horizontal", () => J.go("/settings?tab=prefs")], ...(J.hasModule("staff") ? [["Giriş / Çıkış", "clock", () => J.go("/timeclock")]] : []), ["Kullanıcı değiştir", "users", () => lockScreen(true)], ["Ekranı kilitle", "lock", () => lockScreen()], ["Çıkış yap", "log-out", async () => { await J.post("auth/logout").catch(() => {}); location.href = "/login/"; }]];
    um.innerHTML = `<div class="px-3 py-2"><div class="text-sm font-medium">${esc(full)}</div><div class="text-xs muted">${esc(me.role_label)} · v${esc(window.JET_VERSION)}</div></div><div class="border-t bd my-1"></div>`;
    items.forEach(([l, ic, fn]) => { const b = h(`<button class="menu-item" role="menuitem">${J.icon(ic, 16)}${esc(t(l))}</button>`); b.onclick = () => { um.classList.add("hidden"); ub.setAttribute("aria-expanded", "false"); fn(); }; um.appendChild(b); });
    ub.onclick = () => { const o = um.classList.toggle("hidden"); ub.setAttribute("aria-expanded", String(!o)); };
    document.addEventListener("click", (e) => { if (!e.target.closest("#user-btn, #user-menu")) { um.classList.add("hidden"); ub.setAttribute("aria-expanded", "false"); } });

    if (me.branches?.length > 1) {
      const sel = qs("#branch-sel");
      sel.innerHTML = me.branches.map((b) => `<option value="${b.id}" ${b.id === me.branch ? "selected" : ""}>${esc(b.name)}</option>`).join("");
      sel.classList.remove("hidden");
      sel.onchange = async () => { await J.post("auth/branch", { branch_id: Number(sel.value) }).catch(J.err); location.reload(); };
    }
    const net = qs("#net"), qb = qs("#queue-badge");
    const paintNet = () => {
      const ok = navigator.onLine && J.state.wsOk;
      net.classList.toggle("hidden", ok);
      net.innerHTML = `${J.icon("wifi-off", 14)}${!navigator.onLine ? t("Bağlantı yok") : "Canlı bağlantı kuruluyor"}`;
      net.style.background = "var(--bad-soft)"; net.style.color = "var(--bad)";
    };
    J.on("net", paintNet);
    J.on("queue", (n) => { qb.classList.toggle("hidden", !n); qb.innerHTML = `${J.icon("clock", 14)}${n} ${t("Kuyrukta")}`; qb.style.background = "var(--warn-soft)"; qb.style.color = "var(--warn)"; qb.title = "Bu işlemler sunucuya/mutfağa henüz ulaşmadı"; });
    J.queue.refresh().catch(() => {});
    setTimeout(paintNet, 3000);
  };

  // ------------------------------------------------------------------ kısayollar
  const setupKeys = () => {
    document.addEventListener("keydown", (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
      if ((e.key === "/" && !typing) || (e.ctrlKey && e.key.toLowerCase() === "k")) { e.preventDefault(); qs("#gsearch").focus(); }
      if (e.ctrlKey && e.key.toLowerCase() === "l") { e.preventDefault(); lockScreen(); }
      if (e.key === "Escape") closeDrawer();
      const nav = ALL_ITEMS.find((n) => n.key === e.key);
      if (nav && visible(nav)) { e.preventDefault(); J.go(nav.path); }
    });
  };

  // ------------------------------------------------------------------ başlat
  const boot = async () => {
    try { J.state.me = await J.get("auth/me"); }
    catch (e) { if (e instanceof J.ApiError) return; const cached = localStorage.getItem("jet.me"); if (!cached) { qs("#main").innerHTML = stateBox("wifi-off", "Sunucuya ulaşılamıyor", "Yerel ağ bağlantısını kontrol edip yeniden deneyin.", `<button class="btn btn-primary mt-2" onclick="location.reload()">Yeniden dene</button>`); return; } J.state.me = JSON.parse(cached); J.toast("Çevrimdışı mod — son bilinen oturum", "warn"); }
    localStorage.setItem("jet.me", JSON.stringify(J.state.me));
    J.state.branch = J.state.me.branch;
    setupHeader();
    J.applyPrefs(J.state.me);
    renderNav(); setCollapsed(collapsed(), false); setupSearch(); setupNotifications(); setupKeys();
    if (J.state.me.locked) lockScreen();
    J.connectWS();
    J.queue.flush();
    const lockMin = J.state.me.settings?.inactivity_lock_minutes || 0;
    if (lockMin) setInterval(() => { if (Date.now() - lastAct > lockMin * 60000 && qs("#lock").classList.contains("hidden")) lockScreen(); }, 15000);
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    if ("Notification" in window && Notification.permission === "default" && J.can("ready.view")) document.addEventListener("pointerdown", () => Notification.requestPermission().catch(() => {}), { once: true });
    if (location.pathname === "/" && J.state.me.role === "waiter" && innerWidth < 768) return J.go("/waiter", true);
    if (location.pathname === "/" && J.state.me.role === "kitchen") return J.go("/kds", true);
    route();
  };
  boot();
})();
