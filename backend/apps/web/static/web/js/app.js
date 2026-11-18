/* JETPOS uygulama kabuğu: rol bazlı menü, yönlendirme, arama, bildirim, kilit, kısayollar. */
(function () {
  const { esc, h, qs, qsa, t, tt } = J;
  const NAV = [
    { path: "/", label: "Ana sayfa", icon: "▣", page: "dashboard" },
    { path: "/floor", label: "Masalar", icon: "▦", page: "floor", perm: "floor.view", key: "F2" },
    { path: "/waiter", label: "Garson", icon: "📱", page: "waiter", perm: "ticket.open", mobileOnly: true },
    { path: "/kds", label: "Mutfak", icon: "🍳", page: "kds", perm: "kds.view", key: "F3" },
    { path: "/ready", label: "Hazır siparişler", icon: "🔔", page: "ready", perm: "ready.view" },
    { path: "/approvals", label: "Onaylar", icon: "✔", page: "approvals", any: ["approvals.decide", "approvals.municipal"] },
    { path: "/cash", label: "Kasa", icon: "₺", page: "cash", perm: "cash.manage", key: "F4" },
    { path: "/payments", label: "Ödemeler", icon: "💳", page: "payments", perm: "payment.take" },
    { path: "/tickets", label: "Adisyonlar", icon: "🧾", page: "tickets", perm: "floor.view" },
    { sep: "Yönetim" },
    { path: "/catalog", label: "Katalog", icon: "📋", page: "catalog", perm: "catalog.manage" },
    { path: "/stock", label: "Stok", icon: "📦", page: "stock", perm: "stock.view", module: "stock" },
    { path: "/customers", label: "Müşteriler", icon: "👤", page: "customers", perm: "crm.manage", module: "crm" },
    { path: "/deliveries", label: "Kurye", icon: "🛵", page: "deliveries", perm: "delivery.manage", module: "delivery" },
    { path: "/reservations", label: "Rezervasyon", icon: "📅", page: "reservations", perm: "reservation.manage", module: "reservation" },
    { path: "/staff", label: "Personel", icon: "👥", page: "staff", perm: "staff.manage", module: "staff" },
    { path: "/finance", label: "Finans", icon: "📈", page: "finance", perm: "finance.manage", module: "finance" },
    { path: "/reports", label: "Raporlar", icon: "📊", page: "reports", perm: "reports.view" },
    { sep: "Sistem" },
    { path: "/users", label: "Kullanıcılar", icon: "🔑", page: "users", perm: "users.manage" },
    { path: "/printers", label: "Yazıcılar", icon: "🖨", page: "printers", perm: "printers.manage" },
    { path: "/settings", label: "Ayarlar", icon: "⚙", page: "settings" },
    { path: "/ops", label: "Sistem", icon: "🛡", page: "ops", any: ["ops.manage", "health.view"] },
    { path: "/portal", label: "Portal", icon: "🏢", page: "portal", perm: "settings.manage", business: true },
    { path: "/support", label: "Destek", icon: "💬", page: "support", any: ["support.request", "support.manage"] },
    { path: "/platform", label: "Platform", icon: "🌐", page: "platform", any: ["platform.manage", "license.manage", "platform.finance"] },
    { path: "/audit", label: "Denetim kaydı", icon: "📜", page: "audit", perm: "audit.view" },
    { path: "/notifications", label: "Bildirimler", icon: "🔔", page: "notifications", hidden: true },
    { path: "/timeclock", label: "Giriş/Çıkış", icon: "⏱", page: "timeclock", hidden: true },
    { path: "/help", label: "Yardım", icon: "?", page: "help" },
  ];
  const ROUTES = [[/^\/ticket\/(\d+)$/, "ticket", (m) => ({ id: m[1] })], ...NAV.filter((n) => n.path).map((n) => [new RegExp(`^${n.path.replace(/\//g, "\\/")}$`), n.page, () => ({})])];
  const visible = (n) => !n.sep && !n.hidden && (!n.perm || J.can(n.perm)) && (!n.any || n.any.some(J.can)) && (!n.module || J.hasModule(n.module)) && (!n.business || J.state.me.business);

  // ------------------------------------------------------------------ tercihler
  J.applyPrefs = (me) => {
    const root = document.documentElement;
    root.classList.toggle("dark", me.theme === "dark");
    root.classList.toggle("hc", !!me.high_contrast);
    root.style.setProperty("--font-scale", (me.font_scale || 100) / 100);
    root.lang = me.language || "tr";
    J.state.lang = me.language || "tr";
    try { localStorage.setItem("jet.theme", me.theme); } catch (e) {}
    qs("#lang-btn").textContent = (me.language || "tr").toUpperCase();
    qs("#gsearch").placeholder = me.language === "en" ? "Search: table, ticket, product, customer…  ( / )" : "Ara: masa, adisyon, ürün, müşteri…  ( / )";
  };

  // ------------------------------------------------------------------ menü
  const renderNav = () => {
    const html = NAV.filter((n) => n.sep || visible(n)).map((n) => (n.sep ? `<div class="px-3 pt-4 pb-1 text-[11px] uppercase tracking-wider text-ink-300">${esc(t(n.sep))}</div>` : `<a href="${n.path}" data-link class="nav-item" data-path="${n.path}"><span class="w-5 text-center" aria-hidden="true">${n.icon}</span><span class="flex-1">${esc(t(n.label))}</span>${n.key ? `<kbd class="text-[10px] opacity-60">${n.key}</kbd>` : ""}</a>`)).join("");
    qs("#nav").innerHTML = html;
    qs("#drawer-nav").innerHTML = `<div class="text-2xl font-black px-2 py-3">JET<span class="text-jet">POS</span></div>` + html;
    qs("#side-foot").innerHTML = `${esc(J.state.me.business_name || "Platform")}<br>${esc(J.state.me.branch_name || "")} · v${esc(window.JET_VERSION)}`;
    markActive();
  };
  const markActive = () => qsa("[data-path]").forEach((a) => a.classList.toggle("active", a.dataset.path === location.pathname || (a.dataset.path !== "/" && location.pathname.startsWith(a.dataset.path))));

  // ------------------------------------------------------------------ yönlendirme
  let cleanup = null;
  J.go = (path, replace = false) => { (replace ? history.replaceState : history.pushState).call(history, null, "", path); route(); };
  const route = async () => {
    const path = location.pathname.replace(/\/$/, "") || "/";
    const main = qs("#main");
    try { cleanup?.(); } catch (e) {}
    cleanup = null;
    main.innerHTML = "";
    main.className = "flex-1 p-3 md:p-5";
    qs("#drawer").classList.add("hidden");
    let hit = null;
    for (const [re, page, args] of ROUTES) { const m = path.match(re); if (m) { hit = [page, args(m)]; break; } }
    markActive();
    if (!hit || !J.pages[hit[0]]) { main.innerHTML = `<div class="card p-10 text-center"><h1 class="text-2xl font-bold">Sayfa bulunamadı</h1><a class="btn btn-primary mt-4" href="/" data-link>Ana sayfa</a></div>`; return; }
    const nav = NAV.find((n) => n.page === hit[0]);
    if (nav && nav.path && !visible(nav) && !nav.hidden && hit[0] !== "waiter") { main.innerHTML = `<div class="card p-10 text-center"><h1 class="text-xl font-bold">Bu ekran için yetkiniz yok</h1><p class="muted mt-2">Menüler rolünüze göre gösterilir.</p></div>`; return; }
    document.title = `${tt(nav?.label || "Adisyon")} — JETPOS`;
    main.innerHTML = `<div class="muted p-6">${t("Yükleniyor…")}</div>`;
    try {
      main.innerHTML = "";
      cleanup = (await J.pages[hit[0]](main, hit[1])) || null;
    } catch (e) {
      main.innerHTML = `<div class="card p-8"><h2 class="font-bold text-lg mb-2">Ekran yüklenemedi</h2><p class="muted">${esc(e?.data?.detail || e?.message || "Bağlantı hatası")}</p><button class="btn btn-primary mt-4" onclick="location.reload()">Yeniden dene</button></div>`;
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
    const icons = { table: "▦", ticket: "🧾", product: "🍽", category: "📋", staff: "👤", customer: "🙍", payment: "💳", reservation: "📅", stock: "📦", history: "📜" };
    const show = (html) => { box.innerHTML = html; box.classList.toggle("hidden", !html); };
    const run = J.debounce(async () => {
      const q = inp.value.trim();
      try {
        const d = await J.get(`search?q=${encodeURIComponent(q)}`);
        if (!q) return show(d.recent?.length ? `<div class="p-2 text-xs muted">Son aramalar</div>${d.recent.map((r) => `<button class="w-full text-left px-3 py-2 hover:surface-2" data-q="${esc(r)}">⟲ ${esc(r)}</button>`).join("")}` : "");
        const rows = d.results.map((r, i) => `<a href="${esc(r.url)}" data-link class="flex gap-3 px-3 py-2 hover:surface-2 ${i === 0 ? "surface-2" : ""}" role="option"><span>${icons[r.kind] || "•"}</span><span class="flex-1"><b>${esc(r.label)}</b><span class="block text-xs muted">${esc(r.sub)}</span></span><span class="text-xs muted">${esc(r.kind)}</span></a>`).join("");
        const sug = d.suggestions?.length ? `<div class="p-2 text-xs muted border-t bd">Öneriler: ${d.suggestions.map((s) => `<button class="underline mr-2" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : "";
        show(rows || `<div class="p-4 muted text-sm">Sonuç yok (arama yetkilerinize göre filtrelenir)</div>` + sug);
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
    const refresh = async () => { try { const { count: n } = await J.get("notifications/unread_count"); count.textContent = n; count.classList.toggle("hidden", !n); } catch (e) {} };
    btn.onclick = async () => {
      if (!panel.classList.contains("hidden")) return panel.classList.add("hidden");
      const list = await J.get("notifications").catch(() => []);
      panel.innerHTML = `<div class="flex items-center p-2"><b class="flex-1">${t("Bildirimler")}</b><button class="btn btn-ghost btn-sm" data-all>Tümünü okundu yap</button></div>` +
        (list.slice(0, 30).map((n) => `<button class="w-full text-left p-2 rounded hover:surface-2 flex gap-2" data-id="${n.id}" data-ticket="${n.data?.ticket || ""}"><span>${n.read_at ? "○" : "●"}</span><span class="flex-1"><b class="text-sm">${esc(n.title)}</b><span class="block text-xs muted">${esc(n.body)} · ${J.dt(n.created_at)}</span></span></button>`).join("") || `<div class="p-4 muted text-sm">Son 24 saatte bildirim yok</div>`) +
        `<a href="/notifications" data-link class="block text-center text-sm p-2 underline">Tüm geçmiş</a>`;
      panel.classList.remove("hidden");
      qs("[data-all]", panel).onclick = async () => { await J.post("notifications/read_all"); panel.classList.add("hidden"); refresh(); };
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
  const lockScreen = async (switchMode = false) => {
    const lock = qs("#lock");
    if (!switchMode) await J.post("auth/lock").catch(() => {});
    const users = await J.get("auth/pin-users").catch(() => []);
    let selected = switchMode ? null : J.state.me.id;
    lock.innerHTML = "";
    const box = h(`<div class="card p-6 w-full max-w-md text-center"><div class="text-3xl font-black mb-1">JET<span class="text-jet">POS</span></div><p class="muted text-sm mb-4">${switchMode ? "Personel seçin ve PIN girin" : "Ekran kilitlendi"}</p>
      <div class="flex flex-wrap gap-2 justify-center mb-4" data-users></div><div data-pad></div><p class="mt-3 text-sm font-semibold" style="color:var(--bad)" data-err role="alert"></p>
      <div class="mt-4 flex justify-center gap-2"><button class="btn btn-ghost btn-sm" data-pw>Şifre ile aç</button><button class="btn btn-ghost btn-sm" data-out>Çıkış</button></div></div>`);
    const ul = qs("[data-users]", box);
    const drawUsers = () => { ul.innerHTML = ""; users.forEach((u) => { const b = h(`<button class="chip ${u.id === selected ? "active" : ""}">${esc(u.name)}</button>`); b.onclick = () => { selected = u.id; drawUsers(); }; ul.appendChild(b); }); };
    drawUsers();
    const pad = J.pinPad(async (pin) => {
      try {
        if (selected === J.state.me.id && !switchMode) await J.post("auth/unlock", { pin });
        else { if (!selected) throw new J.ApiError(400, { detail: "Personel seçin" }); await J.post("auth/pin-switch", { user_id: selected, pin }); location.reload(); return; }
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
  let lastAct = Date.now();
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, () => (lastAct = Date.now()), { passive: true }));
  J.on("locked", () => qs("#lock").classList.contains("hidden") && lockScreen());

  // ------------------------------------------------------------------ üst çubuk
  const setupHeader = () => {
    const me = J.state.me;
    qs("#user-name").textContent = me.first_name || me.username;
    qs("#theme-btn").onclick = async () => { me.theme = me.theme === "dark" ? "light" : "dark"; J.applyPrefs(me); await J.post("auth/preferences", { theme: me.theme }).catch(() => {}); J.emit("theme"); };
    qs("#lang-btn").onclick = async () => { me.language = me.language === "en" ? "tr" : "en"; await J.post("auth/preferences", { language: me.language }).catch(() => {}); J.applyPrefs(me); renderNav(); route(); };
    const um = qs("#user-menu");
    const items = [["Tercihler", () => J.go("/settings?tab=prefs")], ...(J.hasModule("staff") ? [["Giriş/Çıkış", () => J.go("/timeclock")]] : []), ["Kullanıcı değiştir", () => lockScreen(true)], ["Kilitle", () => lockScreen()], ["Çıkış", async () => { await J.post("auth/logout").catch(() => {}); location.href = "/login/"; }]];
    um.innerHTML = `<div class="px-3 py-2 text-xs muted">${esc(me.role_label)}</div>`;
    items.forEach(([l, fn]) => { const b = h(`<button class="w-full text-left px-3 py-2 rounded hover:surface-2 text-sm" role="menuitem">${esc(t(l))}</button>`); b.onclick = () => { um.classList.add("hidden"); fn(); }; um.appendChild(b); });
    qs("#user-btn").onclick = () => um.classList.toggle("hidden");
    document.addEventListener("click", (e) => { if (!e.target.closest("#user-btn, #user-menu")) um.classList.add("hidden"); });
    qs("#menu-btn").onclick = () => qs("#drawer").classList.remove("hidden");
    qs("#drawer").addEventListener("click", (e) => { if (e.target.dataset.close !== undefined || e.target.closest("a")) qs("#drawer").classList.add("hidden"); });
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
      net.textContent = !navigator.onLine ? `⚠ ${t("Bağlantı yok")}` : "⚠ Canlı bağlantı yeniden kuruluyor";
      net.style.background = "var(--bad)"; net.style.color = "#fff";
    };
    J.on("net", paintNet);
    J.on("queue", (n) => { qb.classList.toggle("hidden", !n); qb.textContent = `⏳ ${n} ${t("Kuyrukta")} — gönderilmedi`; qb.title = "Bu işlemler sunucuya/mutfağa henüz ulaşmadı"; });
    J.queue.refresh().catch(() => {});
    setTimeout(paintNet, 3000);
  };

  // ------------------------------------------------------------------ kısayollar
  const setupKeys = () => {
    document.addEventListener("keydown", (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName);
      if ((e.key === "/" && !typing) || (e.ctrlKey && e.key.toLowerCase() === "k")) { e.preventDefault(); qs("#gsearch").focus(); }
      if (e.ctrlKey && e.key.toLowerCase() === "l") { e.preventDefault(); lockScreen(); }
      const nav = NAV.find((n) => n.key === e.key);
      if (nav && visible(nav)) { e.preventDefault(); J.go(nav.path); }
    });
  };

  // ------------------------------------------------------------------ başlat
  const boot = async () => {
    try { J.state.me = await J.get("auth/me"); }
    catch (e) { if (e instanceof J.ApiError) return; const cached = localStorage.getItem("jet.me"); if (!cached) { qs("#main").innerHTML = `<div class="card p-8">Sunucuya ulaşılamıyor.</div>`; return; } J.state.me = JSON.parse(cached); J.toast("Çevrimdışı mod — son bilinen oturum", "warn"); }
    localStorage.setItem("jet.me", JSON.stringify(J.state.me));
    J.state.branch = J.state.me.branch;
    J.applyPrefs(J.state.me);
    renderNav(); setupHeader(); setupSearch(); setupNotifications(); setupKeys();
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
