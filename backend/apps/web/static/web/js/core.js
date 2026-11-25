/* POSHANE istemci çekirdeği: API, i18n, offline kuyruk, WebSocket, ses. Harici kütüphane yok (LAN offline). */
(function () {
  const J = (window.J = {});
  J.state = { me: null, lang: "tr", ws: null, wsOk: false, online: navigator.onLine, listeners: {}, writes: 0 };

  // ------------------------------------------------------------------ yardımcılar
  J.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  J.money = (v) => new Intl.NumberFormat(J.state.lang === "en" ? "en-GB" : "tr-TR", { style: "currency", currency: "TRY" }).format(Number(v || 0));
  J.num = (v, d = 2) => new Intl.NumberFormat(J.state.lang === "en" ? "en-GB" : "tr-TR", { maximumFractionDigits: d }).format(Number(v || 0));
  J.dt = (v) => (v ? new Date(v).toLocaleString(J.state.lang === "en" ? "en-GB" : "tr-TR", { dateStyle: "short", timeStyle: "short" }) : "");
  J.d = (v) => (v ? new Date(v).toLocaleDateString(J.state.lang === "en" ? "en-GB" : "tr-TR") : "");
  J.today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  J.uid = () => (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
  J.debounce = (fn, ms = 250) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  J.qs = (s, r = document) => r.querySelector(s);
  J.qsa = (s, r = document) => Array.from(r.querySelectorAll(s));
  J.h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  J.can = (perm) => !!J.state.me && (J.state.me.permissions || []).includes(perm);
  J.hasModule = (m) => !!J.state.me?.license?.modules?.includes(m);
  J.device = (() => { try { let d = localStorage.getItem("jet.device"); if (!d) { d = "dev-" + J.uid(); localStorage.setItem("jet.device", d); } return d; } catch (e) { return "dev-anon"; } })();

  // ------------------------------------------------------------------ i18n (Türkçe varsayılan + İngilizce)
  J.dict = {
    en: {
      "Ana sayfa": "Dashboard", "Masalar": "Tables", "Mutfak": "Kitchen", "Hazır siparişler": "Ready orders", "Onaylar": "Approvals",
      "Kasa": "Cash", "Ödemeler": "Payments", "Adisyonlar": "Tickets", "Katalog": "Catalog", "Stok": "Stock", "Müşteriler": "Customers",
      "Kurye": "Delivery", "Rezervasyon": "Reservations", "Personel": "Staff", "Finans": "Finance", "Raporlar": "Reports",
      "Bildirimler": "Notifications", "Kullanıcılar": "Users", "Ayarlar": "Settings", "Yazıcılar": "Printers", "Sistem": "System",
      "Destek": "Support", "Portal": "Portal", "Platform": "Platform", "Yardım": "Help", "Denetim kaydı": "Audit log", "Garson": "Waiter",
      "Kaydet": "Save", "İptal": "Cancel", "Sil": "Delete", "Düzenle": "Edit", "Yeni": "New", "Ara": "Search", "Kapat": "Close",
      "Onayla": "Approve", "Reddet": "Reject", "Gönder": "Send", "Yenile": "Refresh", "Evet": "Yes", "Hayır": "No", "Tamam": "OK",
      "Mutfağa Gönder": "Send to kitchen", "Öde": "Pay", "Hesap iste": "Request bill", "İndirim": "Discount", "Toplam": "Total",
      "Kalan": "Remaining", "Ödenen": "Paid", "Boş": "Empty", "Dolu": "Occupied", "Sipariş bekliyor": "Waiting", "Rezerve": "Reserved",
      "Hesap bekliyor": "Bill requested", "Ödendi": "Paid", "Hazır": "Ready", "Başla": "Start", "Taslak": "Draft", "Gönderildi": "Sent",
      "Çıkış": "Log out", "Kilitle": "Lock", "Kullanıcı değiştir": "Switch user", "Tercihler": "Preferences", "Giriş/Çıkış": "Time clock",
      "Çevrimdışı": "Offline", "Kuyrukta": "Queued", "Bağlantı yok": "No connection", "Yükleniyor…": "Loading…", "Kayıt yok": "No records",
      "Gerekçe": "Reason", "Miktar": "Qty", "Not": "Note", "Fiyat": "Price", "Ürün": "Product", "Durum": "Status", "Tarih": "Date",
    },
  };
  J.t = (s) => (J.state.lang === "en" && J.dict.en[s]) || s;
  J.tt = (x) => (Array.isArray(x) ? (J.state.lang === "en" ? x[1] || x[0] : x[0]) : J.t(x));

  // ------------------------------------------------------------------ olay yayını
  J.on = (ev, fn) => { (J.state.listeners[ev] ||= new Set()).add(fn); return () => J.state.listeners[ev].delete(fn); };
  J.emit = (ev, data) => (J.state.listeners[ev] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } });

  // ------------------------------------------------------------------ API
  class ApiError extends Error { constructor(status, data) { super(data?.detail || "Hata"); this.status = status; this.data = data || {}; } }
  J.ApiError = ApiError;
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || "";

  J.api = async (method, url, body, opts = {}) => {
    const headers = { "X-CSRFToken": csrf(), "X-Device": J.device, Accept: "application/json" };
    if (J.state.branch) headers["X-Branch"] = String(J.state.branch);
    if (opts.idem) headers["Idempotency-Key"] = opts.idem === true ? J.uid() : opts.idem;
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    const path = url.replace(/^\/?(api\/)?/, "");
    // Masa/sipariş istekleri cevapsız kalırsa düğme sonsuza kadar "işlemde" kalmasın
    const signal = /^(floor|tables|tickets|kitchen|ready-orders|qr-orders)\b/.test(path) && AbortSignal.timeout ? AbortSignal.timeout(20000) : undefined;
    // Canlı yenileme, araya yazma işlemi girdiyse eski cevabı ekrana basmasın
    if (method !== "GET") J.state.writes++;
    let res;
    try { res = await fetch("/api/" + path, { method, headers, body: payload, credentials: "same-origin", signal }); }
    finally { if (method !== "GET") J.state.writes++; }
    if (opts.raw) { if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({}))); return res; }
    const data = res.status === 204 ? null : await res.json().catch(() => ({}));
    if (res.status === 401 && !url.includes("auth/")) { location.href = "/login/?next=" + encodeURIComponent(location.pathname); throw new ApiError(401, data); }
    if (res.status === 423 && data?.code === "locked") { J.emit("locked"); throw new ApiError(423, data); }
    if (!res.ok) throw new ApiError(res.status, data);
    return data;
  };
  J.get = (u) => J.api("GET", u);
  J.post = (u, b, o) => J.api("POST", u, b ?? {}, o);
  J.patch = (u, b) => J.api("PATCH", u, b);
  J.del = (u) => J.api("DELETE", u);

  // ------------------------------------------------------------------ offline kuyruk (IndexedDB) — NFR-12
  const DB = "jetpos", STORE = "queue";
  const idb = () => new Promise((ok, no) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "id" });
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
  });
  const tx = async (mode, fn) => { const db = await idb(); return new Promise((ok, no) => { const t = db.transaction(STORE, mode); const s = t.objectStore(STORE); const r = fn(s); t.oncomplete = () => ok(r?.result); t.onerror = () => no(t.error); }); };
  J.queue = {
    add: (e) => tx("readwrite", (s) => s.put({ ...e, id: e.id || J.uid(), ts: Date.now() })).then(J.queue.refresh),
    all: async () => { const items = (await tx("readonly", (s) => s.getAll())) || []; return items.sort((a, b) => a.ts - b.ts); },
    remove: (id) => tx("readwrite", (s) => s.delete(id)).then(J.queue.refresh),
    refresh: async () => { const n = (await J.queue.all()).length; J.emit("queue", n); return n; },
    flushing: false,
    flush: async () => {
      if (J.queue.flushing) return;
      J.queue.flushing = true;
      try {
        for (const item of await J.queue.all()) {
          try {
            await J.api(item.method, item.url, item.body, { idem: item.idem });
            await J.queue.remove(item.id);
            J.toast(`${item.label || "İşlem"} gönderildi`, "ok");
            J.emit("queue-sent", item);
          } catch (e) {
            if (e instanceof ApiError) {
              // Geçici durumlar (sunucu yeniden başlıyor, kilit, oturum, limit): sipariş silinmez, sıra korunur
              if ((e.status === 409 && e.data?.code === "in_progress") || [401, 408, 423, 429].includes(e.status)) break;
              if (e.status >= 500 && (item.tries || 0) < 40) { await tx("readwrite", (s) => s.put({ ...item, tries: (item.tries || 0) + 1 })); break; }
              await J.queue.remove(item.id);
              J.toast(`${item.label || "İşlem"} gönderilemedi: ${e.data?.detail || e.status}`, "bad", 10000);
              J.emit("queue-failed", { item, error: e });
            } else break; // hâlâ ağ yok
          }
        }
      } finally { J.queue.flushing = false; }
    },
  };
  /** Ağ hatasında işlemi kuyruğa alır. Tekrar gönderimde çift kayıt oluşmaz (idempotency anahtarı / client_uid). */
  J.apiQueued = async (method, url, body, { idem, label } = {}) => {
    const key = idem || J.uid();
    try { return await J.api(method, url, body, { idem: key }); }
    catch (e) {
      if (e instanceof ApiError) throw e;
      await J.queue.add({ method, url, body, idem: key, label });
      J.toast(`${label || "İşlem"} kuyruğa alındı — bağlantı gelince gönderilecek. Mutfağa HENÜZ ulaşmadı.`, "warn", 8000);
      return { queued: true };
    }
  };
  window.addEventListener("online", () => { J.state.online = true; J.emit("net"); J.queue.flush(); });
  window.addEventListener("offline", () => { J.state.online = false; J.emit("net"); });
  setInterval(() => J.queue.flush(), 15000);

  // ------------------------------------------------------------------ ses ve titreşim (garson bildirimleri)
  let actx;
  J.beep = (pattern = [880, 0.12, 1320, 0.18]) => {
    try {
      actx ||= new (window.AudioContext || window.webkitAudioContext)();
      let t = actx.currentTime;
      for (let i = 0; i < pattern.length; i += 2) {
        const o = actx.createOscillator(), g = actx.createGain();
        o.frequency.value = pattern[i]; o.connect(g); g.connect(actx.destination);
        g.gain.setValueAtTime(0.25, t); g.gain.exponentialRampToValueAtTime(0.001, t + pattern[i + 1]);
        o.start(t); o.stop(t + pattern[i + 1]); t += pattern[i + 1] + 0.05;
      }
      navigator.vibrate?.([120, 60, 120]);
    } catch (e) {}
  };

  // ------------------------------------------------------------------ WebSocket (yerel ağ canlı kanal)
  J.connectWS = () => {
    let delay = 1000, retry = null, pingedAt = 0, waitingSince = 0, syncedAt = Date.now();
    const resync = () => {
      if (J.qs("#lock")?.classList.contains("hidden") === false) return; // kilitliyken istek atılmaz
      syncedAt = Date.now(); J.emit("resync");
    };
    // Eski soketi olaylarıyla birlikte bırakıp yenisini planlar (yarı açık bağlantıda onclose çok geç gelir)
    const lost = (ws, wait = delay) => {
      if (J.state.ws !== ws || !ws) return;
      ws.onopen = ws.onclose = ws.onmessage = null;
      try { ws.close(); } catch (e) {}
      J.state.ws = null; J.state.wsOk = false; J.emit("net");
      clearTimeout(retry); retry = setTimeout(open, wait);
      delay = Math.min(delay * 2, 15000);
    };
    const ping = () => {
      const ws = J.state.ws;
      if (ws?.readyState !== 1) return;
      pingedAt = Date.now(); waitingSince ||= pingedAt;
      ws.send(JSON.stringify({ type: "ping" }));
    };
    const open = () => {
      clearTimeout(retry);
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/branch/?branch=${J.state.branch || ""}`);
      J.state.ws = ws; waitingSince = Date.now();
      // Her bağlanışta ekran yeniden okunur: kopukken kaçan olaylar böyle telafi edilir
      ws.onopen = () => { J.state.wsOk = true; delay = 1000; waitingSince = 0; J.emit("net"); resync(); J.queue.flush(); };
      ws.onclose = () => lost(ws);
      ws.onmessage = (m) => {
        waitingSince = 0;
        try { const d = JSON.parse(m.data); if (d.event === "pong") return; J.emit("ws:" + d.event, d.data); J.emit("ws", d); } catch (e) {}
      };
    };
    clearInterval(J.state.pingT);
    J.state.pingT = setInterval(() => {
      const now = Date.now();
      if (J.state.ws && waitingSince && now - waitingSince > 15000) lost(J.state.ws, 0); // cevap yok: bağlantı ölü
      else if (now - pingedAt >= 10000) ping();
      // Emniyet ağı: bağlantı yoksa sık, varsa seyrek olarak sunucudan tazele (süre/rezervasyon da güncellenir)
      if (!document.hidden && now - syncedAt > (J.state.wsOk ? 30000 : 10000)) resync();
    }, 3000);
    // Uyuyan telefon/tablet geri geldiğinde beklemeden tazele ve bağlantıyı sına
    const wake = () => {
      if (document.hidden) return;
      if (!J.state.ws) { delay = 1000; open(); }
      else if (J.state.ws.readyState === 1) { ping(); waitingSince = Date.now() - 10000; }
      resync();
    };
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    window.addEventListener("offline", () => lost(J.state.ws, 1000));
    open();
  };

  /** Ekranı canlı tutar: olay gelince ve yeniden bağlanınca load() çağırır. Çağrılar üst üste binmez;
   *  böylece geç gelen eski cevap yeni durumun üzerine yazamaz. */
  J.live = (events, load, ms = 300) => {
    let timer = null, running = false, again = false, alive = true;
    const run = async () => {
      timer = null;
      if (!alive) return;
      if (running) { again = true; return; }
      running = true;
      try { await load(); } catch (e) {} finally { running = false; if (again) { again = false; poke(); } }
    };
    const poke = () => { if (alive && !timer) timer = setTimeout(run, ms); };
    const offs = [...events, "resync"].map((ev) => {
      const [name, match] = Array.isArray(ev) ? ev : [ev, null];
      return J.on(name, (d) => (!match || match(d)) && poke());
    });
    const stop = () => { alive = false; clearTimeout(timer); offs.forEach((f) => f()); };
    stop.poke = poke;
    return stop;
  };

  // ------------------------------------------------------------------ toast
  J.toast = (msg, kind = "info", ms = 4000) => {
    const meta = { ok: ["circle-check", "var(--ok)"], bad: ["circle-alert", "var(--bad)"], warn: ["triangle-alert", "var(--warn)"], info: ["info", "var(--info)"] }[kind] || ["info", "var(--info)"];
    const el = J.h(`<div class="float p-3 text-sm flex gap-3 items-start" role="status"><span style="color:${meta[1]};margin-top:1px">${J.icon(meta[0], 18)}</span><div class="flex-1 font-medium">${J.esc(msg)}</div><button class="muted" aria-label="Kapat" type="button">${J.icon("x", 16)}</button></div>`);
    el.querySelector("button").onclick = () => el.remove();
    J.qs("#toasts")?.appendChild(el);
    setTimeout(() => el.remove(), ms);
  };
  J.err = (e) => {
    if (e?.status === 423) return;
    J.toast(e instanceof ApiError ? e.data?.detail || `Hata (${e.status})` : (navigator.onLine ? "Sunucuya ulaşılamadı" : "Bağlantı yok"), "bad", 6000);
  };
})();
