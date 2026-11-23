/* Yönetim ve platform ekranları. */
(function () {
  const { esc, h, qs, qsa, t, money } = J;
  const P = (J.pages = J.pages || {});
  const opt = (url, label = (x) => x.name, val = (x) => x.id) => async () => (await J.get(url)).map((x) => [val(x), label(x)]);
  const ROLES = [["branch_manager", "Şube yöneticisi"], ["cashier", "Kasiyer"], ["waiter", "Garson"], ["kitchen", "Mutfak personeli"], ["stock", "Stok personeli"], ["owner", "İşletme sahibi"]];
  const kv = (obj) => Object.entries(obj || {}).map(([k, v]) => `<div class="flex justify-between gap-3 py-1 border-b bd text-sm"><span class="muted">${esc(k)}</span><span class="text-right">${typeof v === "object" ? esc(JSON.stringify(v)) : esc(v)}</span></div>`).join("");

  // ================================================================== KULLANICILAR
  P.users = async (main) => {
    main.appendChild(J.pageHead("Kullanıcılar", "Personel hesapları, roller ve hızlı PIN. Ayrılan personel silinmez, devre dışı bırakılır."));
    J.crud(main, {
      title: "Kullanıcı", endpoint: "users", perm: "users.manage",
      columns: [{ key: "username", label: "Kullanıcı adı" }, { key: "first_name", label: "Ad", fmt: (v, r) => `${v} ${r.last_name}` }, { key: "role_label", label: "Rol" }, { key: "branch_name", label: "Şube" }, { key: "has_pin", label: "PIN", html: (r) => J.yes(r.has_pin) }, { key: "is_active", label: "Durum", html: (r) => (r.is_active ? J.badge("Aktif", "var(--ok)") : J.badge("Devre dışı", "var(--muted)")) }, { key: "last_login", label: "Son giriş", fmt: J.dt }],
      fields: (row) => [{ name: "username", label: "Kullanıcı adı", required: true }, { name: "first_name", label: "Ad" }, { name: "last_name", label: "Soyad" }, { name: "email", label: "E-posta", type: "email" }, { name: "phone", label: "Telefon" }, { name: "department", label: "Departman" },
        { name: "role", label: "Rol", type: "select", required: true, options: J.state.me.role === "owner" ? ROLES : ROLES.filter(([k]) => !["owner", "branch_manager"].includes(k)) },
        { name: "branch", label: "Şube", type: "select", options: opt("branches") },
        { name: "password", label: row ? "Yeni şifre (değişmeyecekse boş)" : "Şifre (en az 8 karakter)", type: "password", required: !row }, { name: "pin", label: "Hızlı PIN (4-8 rakam)", type: "password" }],
      deletable: false,
      actions: [{ label: "Devre dışı bırak", show: (r) => r.is_active && r.id !== J.state.me.id, run: async (r, reload) => { const v = await J.askReason(`${r.username} devre dışı bırakılsın`); if (v) { await J.post(`users/${r.id}/deactivate`, v).catch(J.err); reload(); } } },
        { label: "Etkinleştir", show: (r) => !r.is_active, run: async (r, reload) => { await J.post(`users/${r.id}/activate`).catch(J.err); reload(); } }],
    });
  };

  // ================================================================== AYARLAR
  P.settings = async (main) => {
    main.appendChild(J.pageHead("Ayarlar"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const canSet = J.can("settings.manage");
    J.tabs(c, [
      { key: "prefs", label: "Tercihlerim", render: (el) => {
        const me = J.state.me;
        const f = J.form([{ name: "theme", label: "Tema", type: "select", required: true, options: [["light", "Açık"], ["dark", "Koyu"]] }, { name: "language", label: "Dil", type: "select", required: true, options: [["tr", "Türkçe"], ["en", "English"]] }, { name: "font_scale", label: "Yazı boyutu (%)", type: "number", step: "10" }, { name: "high_contrast", label: "Yüksek kontrast", type: "checkbox" }], me);
        const save = h(`<button class="btn btn-primary mt-3">Kaydet</button>`);
        save.onclick = async () => { const v = f.value(); if (!v) return; await J.post("auth/preferences", v).catch(J.err); J.applyPrefs({ ...me, ...v }); J.toast("Tercihler kaydedildi", "ok"); };
        const sec = h(`<div class="card p-4 mt-4 space-y-3"><h3 class="font-semibold">Güvenlik</h3><div class="flex flex-wrap gap-2"><button class="btn btn-ghost" data-pw>Şifre değiştir</button><button class="btn btn-ghost" data-pin>PIN belirle</button><button class="btn btn-ghost" data-2fa>2FA (doğrulama uygulaması)</button></div></div>`);
        qs("[data-pw]", sec).onclick = async () => { const v = await J.promptForm("Şifre değiştir", [{ name: "old_password", label: "Mevcut şifre", type: "password", required: true }, { name: "new_password", label: "Yeni şifre", type: "password", required: true }]); if (v) { await J.post("auth/change-password", v).then(() => J.toast("Şifre değişti", "ok")).catch(J.err); } };
        qs("[data-pin]", sec).onclick = async () => { const v = await J.promptForm("Hızlı PIN", [{ name: "password", label: "Şifreniz", type: "password", required: true }, { name: "pin", label: "Yeni PIN (4-8 rakam)", type: "password", required: true }]); if (v) await J.post("auth/set-pin", v).then(() => J.toast("PIN kaydedildi", "ok")).catch(J.err); };
        qs("[data-2fa]", sec).onclick = async () => { const s = await J.get("auth/2fa"); const v = await J.promptForm("2FA kurulumu", [{ name: "otp", label: "Uygulamadaki 6 haneli kod", required: true, help: `Doğrulama uygulamasına bu anahtarı ekleyin: ${s.secret}` }]); if (v) await J.post("auth/2fa", v).then(() => J.toast("2FA etkin", "ok")).catch(J.err); };
        el.append(h(`<div class="card p-4"></div>`), sec);
        el.firstChild.append(f.el, save);
      } },
      { key: "branch", label: "Şube ayarları", show: canSet, render: async (el) => {
        const s = await J.get("branch-settings");
        const f = J.form([
          { name: "auto_close_on_payment", label: "Tam ödemede adisyonu otomatik kapat (kapalıysa masa boşaltılınca personel kapatır)", type: "checkbox", wide: true },
          { name: "confirm_first_send", label: "İlk mutfak gönderiminde özet onayı iste", type: "checkbox", wide: true },
          { name: "stock_deduction", label: "Stok düşüm zamanı", type: "select", required: true, options: [["send", "Mutfağa gönderimde"], ["prep", "Hazırlık başlangıcında"], ["payment", "Ödemede"]] },
          { name: "out_of_stock_policy", label: "Stok yoksa (genel)", type: "select", required: true, options: [["warn", "Uyar, satışa izin ver"], ["block", "Satışı engelle"]] },
          { name: "late_order_minutes", label: "Geciken sipariş eşiği (dk)", type: "number" }, { name: "inactivity_lock_minutes", label: "Hareketsizlikte otomatik kilit (dk, 0 = kapalı)", type: "number" },
          { name: "max_failed_logins", label: "Hesap kilidi için hatalı deneme", type: "number" }, { name: "lockout_minutes", label: "Hesap kilit süresi (dk)", type: "number" },
          { name: "max_discount_percent", label: "Azami indirim (%)", type: "money" }, { name: "default_channel", label: "Varsayılan kanal", type: "select", required: true, options: [["table", "Masa"], ["takeaway", "Gel-al"], ["delivery", "Teslimat"]] },
          { name: "receipt_header", label: "Fiş başlığı", type: "textarea" }, { name: "receipt_footer", label: "Fiş alt notu", type: "textarea" }], s);
        const b = h(`<button class="btn btn-primary mt-3">Kaydet</button>`);
        b.onclick = async () => { const v = f.value(); if (v) await J.patch("branch-settings", v).then(() => J.toast("Kaydedildi", "ok")).catch(J.err); };
        el.appendChild(h(`<div class="card p-4"></div>`)).append(f.el, b);
      } },
      { key: "business", label: "İşletme", show: canSet, render: async (el) => {
        const biz = await J.get("business");
        const f = J.form([{ name: "name", label: "İşletme adı", required: true }, { name: "phone", label: "Telefon" }, { name: "email", label: "E-posta", type: "email" }, { name: "tax_office", label: "Vergi dairesi" }, { name: "tax_number", label: "Vergi no" }], biz);
        const b = h(`<button class="btn btn-primary mt-3">Kaydet</button>`);
        b.onclick = async () => { const v = f.value(); if (v) await J.patch("business", v).then(() => J.toast("Kaydedildi", "ok")).catch(J.err); };
        el.appendChild(h(`<div class="card p-4 mb-4"></div>`)).append(f.el, b);
        J.crud(el, { title: "Şube", endpoint: "branches", perm: "settings.manage", columns: [{ key: "name", label: "Şube" }, { key: "code", label: "Kod" }, { key: "address", label: "Adres" }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }], fields: [{ name: "name", label: "Ad", required: true }, { name: "code", label: "Kod", required: true }, { name: "address", label: "Adres", type: "textarea" }, { name: "phone", label: "Telefon" }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }], deleteLabel: "Pasifleştir" });
      } },
      { key: "license", label: "Lisans ve cihazlar", show: canSet, render: async (el) => {
        const st = await J.get("license");
        const card = h(`<div class="card p-4 mb-4"><h3 class="font-semibold mb-2">Lisans</h3>${st.licensed ? kv({ Paket: st.package, Modüller: st.modules.join(", ") || "—", "Destek/güncelleme bitişi": st.support_until, "Destek aktif": st.support_active ? "Evet" : "Hayır", "Şube hakkı": st.max_branches ?? "tanımsız", "Sabit terminal": st.max_terminals ?? "tanımsız", "Mobil cihaz": st.max_mobile ?? "tanımsız", Sürüm: st.version }) : `<p style="color:var(--warn)">Lisans kurulu değil. Opsiyonel modüller kapalı; çekirdek POS çalışır.</p>`}
          <div class="flex flex-wrap gap-2 mt-3"><button class="btn btn-primary" data-key>Online anahtar ile etkinleştir</button><button class="btn btn-ghost" data-file>İmzalı lisans dosyası / QR metni</button></div></div>`);
        qs("[data-key]", card).onclick = async () => { const v = await J.promptForm("Lisans anahtarı", [{ name: "key", label: "Anahtar (XXXX-XXXX-…)", required: true }]); if (v) await J.post("license", v).then(() => { J.toast("Lisans etkinleştirildi", "ok"); location.reload(); }).catch(J.err); };
        qs("[data-file]", card).onclick = async () => { const v = await J.promptForm("İmzalı lisans (offline)", [{ name: "blob", label: "Lisans dosyası içeriği veya QR'dan okunan metin (JETLIC1.…)", type: "textarea", rows: 5, required: true }]); if (v) await J.post("license", v).then(() => { J.toast("Lisans kuruldu", "ok"); location.reload(); }).catch(J.err); };
        el.appendChild(card);
        const reg = h(`<button class="btn btn-ghost mb-2">Bu cihazı kaydet</button>`);
        reg.onclick = async () => { const v = await J.promptForm("Cihaz kaydı", [{ name: "name", label: "Cihaz adı", required: true, default: navigator.platform }, { name: "kind", label: "Tür", type: "select", required: true, options: [["terminal", "Sabit terminal"], ["mobile", "Mobil personel cihazı"], ["kds", "Mutfak ekranı"]] }]); if (v) await J.post("devices/register", { ...v, fingerprint: J.device }).then(() => J.toast("Cihaz kaydedildi", "ok")).catch(J.err); };
        el.appendChild(reg);
        J.crud(el, { title: "Cihaz", endpoint: "devices", columns: [{ key: "name", label: "Cihaz" }, { key: "kind", label: "Tür" }, { key: "branch_name", label: "Şube" }, { key: "fingerprint", label: "Kimlik", fmt: (v) => v.slice(0, 16) + "…" }, { key: "last_seen", label: "Son görülme", fmt: J.dt }, { key: "is_active", label: "Aktif", html: (r) => J.yes(r.is_active) }],
          actions: [{ label: "Transfer", show: (r) => r.is_active, run: async (r, reload) => { const v = await J.promptForm("Donanım değişimi — kontrollü transfer", [{ name: "name", label: "Yeni cihaz adı" }, { name: "fingerprint", label: "Yeni cihaz kimliği (yeni cihazda Ayarlar > bu cihaz)", required: true }, { name: "reason", label: "Gerekçe", required: true, minLength: 3 }]); if (v) { await J.post(`devices/${r.id}/transfer`, v).catch(J.err); reload(); } } },
            { label: "Pasifleştir", show: (r) => r.is_active, run: async (r, reload) => { await J.post(`devices/${r.id}/deactivate`, {}).catch(J.err); reload(); } }] });
        el.appendChild(h(`<p class="text-xs muted mt-2">Bu cihazın kimliği: <code>${esc(J.device)}</code></p>`));
      } },
      { key: "notify", label: "Bildirim kuralları", show: canSet, render: (el) => {
        el.appendChild(h(`<p class="text-sm muted mb-2">Rol/olay bazlı kanal ve öncelik. Uygulama içi ve ses yerel ağda internetsiz çalışır; e-posta internet + SMTP gerektirir. Mobil push için dış servis (VAPID/FCM) bilgisi gereklidir.</p>`));
        J.crud(el, { title: "Bildirim kuralı", endpoint: "notification-rules", perm: "settings.manage", columns: [{ key: "event", label: "Olay" }, { key: "role", label: "Rol" }, { key: "priority", label: "Öncelik" }, { key: "in_app", label: "Uygulama", html: (r) => J.yes(r.in_app) }, { key: "sound", label: "Ses", html: (r) => J.yes(r.sound) }, { key: "email", label: "E-posta", html: (r) => J.yes(r.email) }],
          fields: [{ name: "event", label: "Olay", type: "select", required: true, options: [["order_ready", "Sipariş hazır"], ["bill_requested", "Hesap istendi"], ["approval_request", "Onay talebi"], ["kitchen_void", "Mutfak iptal"], ["low_stock", "Düşük stok"], ["printer_error", "Yazıcı hatası"], ["day_end_pending", "Gün sonu onayı"], ["delivery_late", "Geciken teslimat"], ["reservation_reminder", "Rezervasyon hatırlatma"], ["qr_order", "QR sipariş"], ["health_alert", "Sistem uyarısı"]] },
            { name: "role", label: "Rol", type: "select", required: true, options: ROLES }, { name: "priority", label: "Öncelik", type: "select", required: true, options: [["low", "Düşük"], ["medium", "Orta"], ["high", "Yüksek"]] },
            { name: "in_app", label: "Uygulama içi", type: "checkbox", default: true }, { name: "sound", label: "Sesli", type: "checkbox" }, { name: "email", label: "E-posta", type: "checkbox" }] });
      } },
      { key: "jetmenu", label: "JET Menü", show: canSet && J.hasModule("jetmenu"), render: async (el) => {
        const d = await J.get("integrations/jetmenu");
        const f = J.form([{ name: "enabled", label: "Entegrasyon etkin", type: "checkbox" }, { name: "auto_accept_qr", label: "QR siparişlerini otomatik adisyona ekle (kapalı: garson onayı)", type: "checkbox", wide: true }, { name: "webhook_url", label: "JET Menü webhook adresi (değişiklik bildirimi)", wide: true }, { name: "qr_url_template", label: "Masa QR içeriği şablonu — {token} ve {branch} kullanılabilir (JET Menü'nün URL biçimine göre doldurun)", wide: true }], d.config);
        const b = h(`<div class="flex gap-2 mt-3"><button class="btn btn-primary">Kaydet</button><button class="btn btn-ghost">Kuyruğu gönder</button><button class="btn btn-ghost">Tüm kataloğu yeniden kuyruğa al</button></div>`);
        const [s1, s2, s3] = b.children;
        s1.onclick = async () => { const v = f.value(); if (v) await J.patch("integrations/jetmenu", v).then(() => J.toast("Kaydedildi", "ok")).catch(J.err); };
        s2.onclick = async () => { const r = await J.post("integrations/jetmenu", { action: "push" }).catch(J.err); if (r) J.toast(`${r.sent} mesaj gönderildi`, "ok"); };
        s3.onclick = async () => { const r = await J.post("integrations/jetmenu", { action: "resync" }).catch(J.err); if (r) J.toast(`${r.queued} ürün kuyruğa alındı`, "ok"); };
        el.appendChild(h(`<div class="card p-4"><p class="text-sm mb-3" style="color:var(--warn)">${esc(d.note)}</p>${kv({ "Gelen istek anahtarı (X-Integration-Token)": d.config.inbound_token, "Katalog ucu": "/api/integrations/jetmenu/catalog?branch=ŞUBE_KODU", "Sipariş ucu": "POST /api/integrations/jetmenu/orders", "Kuyruk": `${d.outbox.pending} bekleyen · ${d.outbox.failed} hatalı · ${d.outbox.sent} gönderildi` })}</div>`)).append(f.el, b);
      } },
    ]);
  };

  // ================================================================== YAZICILAR
  P.printers = async (main) => {
    main.appendChild(J.pageHead("Yazıcılar", "ESC/POS · 58/80 mm · ağ (TCP 9100), Windows sürücü veya dosya. Her model ayrıca test edilmelidir."));
    const c = h(`<div></div>`);
    main.appendChild(c);
    J.tabs(c, [
      { key: "printers", label: "Yazıcılar", render: (el) => J.crud(el, {
        title: "Yazıcı", endpoint: "printers", perm: "printers.manage", size: "max-w-3xl",
        columns: [{ key: "name", label: "Yazıcı" }, { key: "model_name", label: "Model" }, { key: "connection", label: "Bağlantı", fmt: (v, r) => `${v} ${r.address}${r.connection === "network" ? ":" + r.port : ""}` }, { key: "width_mm", label: "mm" }, { key: "target", label: "Hedef" }, { key: "queued", label: "Kuyruk", right: true }, { key: "failed", label: "Hata", right: true }, { key: "last_error", label: "Son hata", fmt: (v) => (v || "").slice(0, 60) }],
        fields: [{ name: "name", label: "Ad", required: true }, { name: "model_name", label: "Model (Epson TM, Xprinter, Bixolon, Star, HPRT, SNBC…)" },
          { name: "connection", label: "Bağlantı", type: "select", required: true, options: [["network", "Ethernet / Wi-Fi (TCP)"], ["windows", "Windows yazıcı (USB/sürücü)"], ["file", "Dosyaya yaz (sanal)"]] },
          { name: "address", label: "IP adresi / Windows yazıcı adı / klasör" }, { name: "port", label: "Port", type: "number", default: 9100 },
          { name: "width_mm", label: "Kâğıt", type: "select", required: true, options: [[80, "80 mm"], [58, "58 mm"]] }, { name: "target", label: "Hedef", type: "select", required: true, options: [["cashier", "Kasa"], ["kitchen", "Mutfak"], ["bar", "İçecek"], ["dessert", "Tatlı"], ["other", "Diğer"]] },
          { name: "stations", label: "İstasyon yönlendirme", type: "multiselect", options: opt("stations") }, { name: "categories", label: "Kategori yönlendirme", type: "multiselect", options: opt("categories") },
          { name: "print_receipts", label: "Hesap/ödeme fişlerini bas", type: "checkbox" }, { name: "backup", label: "Yedek yazıcı", type: "select", options: opt("printers") },
          { name: "codepage", label: "Kod sayfası", default: "cp857" }, { name: "escpos_codepage_id", label: "ESC t n değeri", type: "number", default: 13 },
          { name: "header", label: "Özel fiş başlığı", type: "textarea" }, { name: "footer", label: "Özel fiş altı", type: "textarea" }, { name: "cut", label: "Kâğıt kes", type: "checkbox", default: true }, { name: "is_active", label: "Aktif", type: "checkbox", default: true }],
        deleteLabel: "Pasifleştir",
        actions: [{ label: "Test baskısı", run: async (r, reload) => { const j = await J.post(`printers/${r.id}/test`).catch(J.err); if (!j) return; J.modal({ title: `Test — ${j.status === "done" ? "başarılı" : "BAŞARISIZ"}`, body: `<pre class="text-xs surface-2 p-3 rounded overflow-x-auto">${esc(j.preview)}</pre>${j.last_error ? `<p style="color:var(--bad)" class="mt-2">${esc(j.last_error)}</p>` : ""}` }); reload(); } },
          { label: "Bağlantı testi", show: (r) => r.connection === "network", run: async (r) => { const x = await J.post("printer-probe", { address: r.address, port: r.port }).catch(J.err); if (x) J.toast(x.ok ? "Yazıcıya ulaşıldı" : `Ulaşılamadı: ${x.error}`, x.ok ? "ok" : "bad"); } }],
      }) },
      { key: "jobs", label: "Yazdırma kuyruğu", render: (el) => J.crud(el, { title: "İş", endpoint: "print-jobs", columns: [{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "title", label: "İş" }, { key: "printer_name", label: "Yazıcı" }, { key: "printed_on_name", label: "Basılan" }, { key: "status", label: "Durum", html: (r) => J.badge(r.status, r.status === "done" ? "var(--ok)" : r.status === "failed" ? "var(--bad)" : "var(--warn)") }, { key: "attempts", label: "Deneme", right: true }, { key: "last_error", label: "Hata", fmt: (v) => (v || "").slice(0, 80) }],
        onRow: (r) => J.modal({ title: r.title, body: `<pre class="text-xs surface-2 p-3 rounded overflow-x-auto">${esc(r.preview)}</pre>` }),
        actions: [{ label: "Tekrar dene", show: (r) => r.status !== "done", run: async (r, reload) => { await J.post(`print-jobs/${r.id}/retry`).catch(J.err); reload(); } }] }) },
    ]);
  };

  // ================================================================== SİSTEM (OPS)
  P.ops = async (main) => {
    main.appendChild(J.pageHead("Sistem", "Yedekleme, sağlık izleme, güncelleme, yedeklilik ve senkronizasyon"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    J.tabs(c, [
      { key: "backups", label: "Yedekler", render: async (el) => {
        const load = async () => {
          const d = await J.get("ops/backups");
          el.innerHTML = "";
          const top = h(`<div class="flex flex-wrap gap-2 mb-3"><button class="btn btn-primary" data-new>Şimdi yedek al</button><button class="btn btn-ghost" data-pol>Saklama politikası</button><button class="btn btn-ghost" data-ret>Eski yedekleri temizle</button></div>`);
          qs("[data-new]", top).onclick = async () => { J.toast("Yedek alınıyor…"); await J.post("ops/backups", { action: "create" }).then(() => J.toast("Yedek alındı ve doğrulandı", "ok")).catch(J.err); load(); };
          qs("[data-pol]", top).onclick = async () => { const v = await J.promptForm("Yedek politikası", [{ name: "enabled", label: "Otomatik yedek", type: "checkbox" }, { name: "daily_time", label: "Günlük saat", type: "time" }, { name: "keep_daily", label: "Günlük saklama (adet)", type: "number" }, { name: "keep_weekly", label: "Haftalık saklama", type: "number" }, { name: "keep_monthly", label: "Aylık saklama", type: "number" }, { name: "restore_test_days", label: "Geri yükleme testi sıklığı (gün)", type: "number" }], { values: d.policy }); if (v) { await J.post("ops/backups", { action: "policy", policy: v }).catch(J.err); load(); } };
          qs("[data-ret]", top).onclick = async () => { const r = await J.post("ops/backups", { action: "retention" }).catch(J.err); if (r) J.toast(`${r.removed} yedek temizlendi (kritikler korundu)`, "ok"); load(); };
          el.appendChild(top);
          el.appendChild(h(`<div class="card p-3 mb-3 text-sm">${kv({ "Harici disk/NAS kopya klasörleri": d.mirrors.join("; ") || "tanımsız (JETPOS_BACKUP_MIRRORS)", "Bulut yedek": d.cloud })}</div>`));
          const box = h(`<div class="card"></div>`);
          box.appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "kind", label: "Tür" }, { key: "size", label: "Boyut", right: true, fmt: (v) => `${J.num(v / 1024, 0)} KB` }, { key: "verify_ok", label: "Bütünlük", html: (r) => r.verify_ok === null ? "—" : r.verify_ok ? J.badge("Geçerli", "var(--ok)", "check") : J.badge(r.error || "Hatalı", "var(--bad)", "circle-alert") }, { key: "restore_test_ok", label: "Geri yükleme testi", html: (r) => r.restore_test_ok === null ? "—" : r.restore_test_ok ? J.badge(J.dt(r.restore_tested_at), "var(--ok)", "check") : J.badge("Başarısız", "var(--bad)", "circle-alert") }, { key: "mirrors", label: "Kopyalar", fmt: (v) => v.map((m) => (m.ok ? "Tamam" : "Hata")).join(", ") || "—" }, { key: "critical", label: "Kritik", html: (r) => J.yes(r.critical) }], d.backups, {
            actions: [{ label: "Doğrula", run: async (r) => { await J.post("ops/backups", { action: "verify", id: r.id }).catch(J.err); load(); } },
              { label: "Geri yükleme testi", run: async (r) => { J.toast("Geçici veritabanına geri yükleniyor…"); const x = await J.post("ops/backups", { action: "restore_test", id: r.id }).catch(J.err); if (x) J.modal({ title: x.restore_test_ok ? "Geri yükleme testi başarılı" : "Geri yükleme testi BAŞARISIZ", body: `<pre class="text-xs whitespace-pre-wrap">${esc(x.restore_test_log)}</pre>`, size: "max-w-3xl" }); load(); } },
              { label: "Koru/kaldır", run: async (r) => { await J.post("ops/backups", { action: "protect", id: r.id }); load(); } },
              { label: "Geri yükle", show: () => ["owner", "platform_admin", "tech"].includes(J.state.me.role), run: async (r) => {
                const v = await J.promptForm("DİKKAT: Canlı veriyi geri yükle", [{ name: "confirm", label: `Mevcut tüm veriler bu yedekle değiştirilecek. Önce otomatik ön-yedek alınır. Onay için '${d.confirm_phrase}' yazın`, required: true }]);
                if (!v) return;
                const x = await J.post("ops/backups", { action: "restore", id: r.id, confirm: v.confirm }).catch(J.err);
                if (x) { alert(x.detail + "\nÖn-yedek: " + x.pre_restore_backup); location.href = "/login/"; }
              } }] }));
          el.appendChild(box);
        };
        await load();
      } },
      { key: "health", label: "Sağlık", render: async (el) => {
        const d = await J.get("ops/health");
        const n = d.now;
        el.appendChild(h(`<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-3">${[["CPU", `%${n.cpu}`], ["RAM", `%${n.ram}`], ["Disk", `%${n.disk}`], ["Veritabanı", n.db_ok ? `OK · ${n.db_latency_ms} ms` : "HATA"], ["Boş disk", `${n.details.disk_free_gb} GB`]].map(([l, v]) => `<div class="card p-4"><div class="text-xs muted">${l}</div><div class="text-xl font-bold">${v}</div></div>`).join("")}</div>`));
        el.appendChild(h(`<div class="card p-4 mb-3"><h3 class="font-semibold mb-2">Uyarılar</h3>${n.alerts.length ? n.alerts.map((a) => `<div>${J.badge(a.level, a.level === "critical" || a.level === "high" ? "var(--bad)" : "var(--warn)")} ${esc(a.message)}</div>`).join("") : '<div class="muted">Uyarı yok</div>'}<div class="mt-3 text-sm">${kv(n.details)}</div></div>`));
        const ch = h(`<div class="card p-4 mb-3"><h3 class="font-semibold mb-2">CPU geçmişi</h3><div></div></div>`);
        el.appendChild(ch);
        requestAnimationFrame(() => J.chart(ch.lastElementChild, { type: "line", labels: d.history.slice().reverse().map((x) => J.dt(x.created_at)), series: [{ name: "CPU", data: d.history.slice().reverse().map((x) => x.cpu) }] }));
        const diag = h(`<button class="btn btn-ghost">Otomatik tanılama çalıştır</button>`);
        diag.onclick = async () => { const r = await J.get("ops/health?diagnose=1"); J.modal({ title: "Tanılama", size: "max-w-2xl", body: r.checks.map((c2) => `<div class="flex gap-2 py-1 border-b bd"><span style="color:${c2.ok ? "var(--ok)" : "var(--bad)"}">${J.icon(c2.ok ? "circle-check" : "circle-alert", 16)}</span><span class="flex-1">${esc(c2.name)}</span><span class="muted text-sm">${c2.ok ? "" : esc(c2.hint)}</span></div>`).join("") }); };
        el.appendChild(diag);
        if (d.central) { const cb = h(`<div class="card mt-4"><h3 class="font-semibold p-3">Merkezi izleme — şubeler</h3></div>`); cb.appendChild(J.table([{ key: "business", label: "İşletme" }, { key: "branch", label: "Şube" }, { key: "received_at", label: "Son sinyal", fmt: J.dt }, { key: "cpu", label: "CPU" }, { key: "ram", label: "RAM" }, { key: "disk", label: "Disk" }, { key: "db_ok", label: "DB", html: (r) => J.yes(r.db_ok) }, { key: "alerts", label: "Uyarı", fmt: (v) => (v || []).length }], d.central)); el.appendChild(cb); }
      } },
      { key: "updates", label: "Güncelleme", render: async (el) => {
        const load = async () => {
          const d = await J.get("ops/updates");
          el.innerHTML = "";
          const up = h(`<div class="card p-4 mb-3"><div class="mb-2">Mevcut sürüm: <b>${esc(d.current)}</b> ${d.central ? "" : '<span class="muted text-sm">· merkezi güncelleme sunucusu tanımlı değil; USB/offline paket yükleyin</span>'}</div>
            <div class="grid md:grid-cols-3 gap-2 items-end"><div><label class="label">Paket (.zip)</label><input type="file" accept=".zip" class="input" data-p></div><div><label class="label">İmza (.sig)</label><input type="file" accept=".sig" class="input" data-s></div><button class="btn btn-primary" data-u>Yükle ve doğrula</button></div></div>`);
          qs("[data-u]", up).onclick = async () => { const fd = new FormData(); fd.append("package", qs("[data-p]", up).files[0]); fd.append("signature", qs("[data-s]", up).files[0]); fd.append("source", "usb"); await J.api("POST", "ops/updates", fd).then(() => J.toast("İmza ve bütünlük doğrulandı", "ok")).catch(J.err); load(); };
          el.appendChild(up);
          el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "from_version", label: "Önceki" }, { key: "version", label: "Sürüm" }, { key: "status", label: "Durum" }, { key: "signature_ok", label: "İmza", html: (r) => J.yes(r.signature_ok) }, { key: "health_ok", label: "Sağlık", html: (r) => r.health_ok === null ? "—" : J.yes(r.health_ok) }], d.history, {
            onRow: (r) => J.modal({ title: `Sürüm ${r.version}`, body: `<pre class="text-xs whitespace-pre-wrap">${esc(r.log || "")}</pre>`, size: "max-w-3xl" }),
            actions: [{ label: "Onayla", show: (r) => r.status === "verified", run: async (r) => { await J.post("ops/updates", { action: "approve", id: r.id }).catch(J.err); load(); } },
              { label: "Uygula", show: (r) => r.status === "approved", run: async (r) => { if (await J.confirm(`Sürüm ${r.version} uygulansın mı? Önce otomatik yedek alınır; sağlık testi başarısızsa geri alınır.`)) { await J.post("ops/updates", { action: "apply", id: r.id }).catch(J.err); load(); } } },
              { label: "Geri al", show: (r) => r.status === "applied", run: async (r) => { await J.post("ops/updates", { action: "rollback", id: r.id }).catch(J.err); load(); } }] }));
        };
        await load();
      } },
      { key: "failover", label: "Yedeklilik", render: async (el) => {
        const load = async () => {
          const d = await J.get("ops/failover");
          el.innerHTML = "";
          el.appendChild(h(`<div class="card p-4 mb-3 text-sm">${kv({ "Bu düğüm": d.node_id, "Yazma kilidi denetimi": d.enforced ? "Açık (JETPOS_ENFORCE_WRITER_FENCE)" : "Kapalı (tek sunucu)", "Lider": d.lease?.holder || "—", "Fencing token": d.lease?.token ?? "—", "Kilit bitişi": J.dt(d.lease?.expires_at) })}
            <p class="mt-2 muted">Eski sunucu izole edilmeden yeni sunucu yazmaya başlamaz (split-brain önleme). Güvenli koşullarda otomatik, riskli durumda yönetici onayıyla geçiş yapılır.</p>
            <div class="flex flex-wrap gap-2 mt-3"><button class="btn btn-ghost" data-a="fence">Düğümü izole et</button><button class="btn btn-ghost" data-a="assess">Geçiş değerlendir</button><button class="btn btn-primary" data-a="failover">Failover</button><button class="btn btn-ghost" data-a="failback">Failback</button><button class="btn btn-ghost" data-a="mode">Yedeklilik modu</button></div></div>`));
          qsa("[data-a]", el).forEach((b) => (b.onclick = async () => {
            const a = b.dataset.a;
            try {
              if (a === "fence") { const v = await J.promptForm("İzole et", [{ name: "node", label: "Düğüm", required: true }, { name: "reason", label: "Gerekçe (ör. ağdan çıkarıldı)", required: true }]); if (v) await J.post("ops/failover", { action: "fence", ...v }); }
              if (a === "assess") { const v = await J.promptForm("Değerlendir", [{ name: "target", label: "Hedef düğüm", required: true }]); if (v) { const r = await J.get(`ops/failover?target=${encodeURIComponent(v.target)}`); J.modal({ title: "Değerlendirme", body: kv(r.assessment.checks) + `<p class="mt-2 font-semibold">${r.assessment.possible ? (r.assessment.auto ? "Otomatik geçiş güvenli" : "Yönetici onayı gerekli") : "Geçiş mümkün değil: " + esc(r.assessment.reason)}</p>` }); } }
              if (a === "failover") { const v = await J.promptForm("Failover", [{ name: "target", label: "Hedef düğüm", required: true }, { name: "approve", label: "Riskli durumda yönetici onayı veriyorum", type: "checkbox" }]); if (v) await J.post("ops/failover", { action: "failover", ...v }); }
              if (a === "failback") { const v = await J.promptForm("Failback", [{ name: "node", label: "Ana düğüm", required: true }, { name: "data_synced", label: "Veriler eşitlendi", type: "checkbox" }, { name: "consistency_ok", label: "Tutarlılık doğrulandı", type: "checkbox" }]); if (v) await J.post("ops/failover", { action: "failback", ...v }); }
              if (a === "mode") { const v = await J.promptForm("Yedeklilik modu", [{ name: "node", label: "Düğüm", required: true, default: d.node_id }, { name: "mode", label: "Mod", type: "select", required: true, options: [["none", "Yedeksiz"], ["manual", "Manuel yedek"], ["hot", "Sıcak yedek"], ["auto", "Otomatik geçiş"]] }, { name: "address", label: "Adres" }]); if (v) await J.post("ops/failover", { action: "mode", ...v }); }
              load();
            } catch (e) { J.err(e); }
          }));
          el.appendChild(h(`<div class="card mb-3"><h3 class="font-semibold p-3">Düğümler</h3></div>`)).appendChild(J.table([{ key: "node_id", label: "Düğüm" }, { key: "role", label: "Rol" }, { key: "redundancy_mode", label: "Mod" }, { key: "last_heartbeat", label: "Son sinyal", fmt: J.dt }, { key: "healthy", label: "Sağlıklı", html: (r) => J.yes(r.healthy) }, { key: "fenced", label: "İzole", html: (r) => J.yes(r.fenced) }], d.nodes));
          el.appendChild(h(`<div class="card"><h3 class="font-semibold p-3">Olaylar</h3></div>`)).appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "kind", label: "Tür" }, { key: "from_node", label: "Kaynak" }, { key: "to_node", label: "Hedef" }, { key: "decision", label: "Karar" }], d.events));
        };
        await load();
      } },
      { key: "sync", label: "Senkronizasyon", render: async (el) => {
        const d = await J.get("ops/sync");
        el.appendChild(h(`<div class="card p-4 mb-3">${kv({ "Merkez adresi": d.central_url || "tanımsız (JETPOS_CENTRAL_URL) — olaylar yerelde kuyrukta bekler", Bekleyen: d.pending, Başarısız: d.failed, Gönderilen: d.sent })}<button class="btn btn-primary mt-3">Şimdi gönder</button></div>`));
        qs("button", el).onclick = async () => { const r = await J.post("ops/sync").catch(J.err); if (r) J.toast(r.skipped || r.error || `${r.sent} olay gönderildi`, r.error ? "bad" : "ok"); };
        el.appendChild(h(`<div class="card"></div>`)).appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "kind", label: "Olay" }, { key: "attempts", label: "Deneme", right: true }, { key: "last_error", label: "Hata" }], d.recent_failed));
      } },
    ]);
  };

  // ================================================================== DESTEK
  P.support = async (main) => {
    const isSupport = J.state.me.is_platform;
    main.appendChild(J.pageHead("Destek", isSupport ? "Destek kuyruğu" : "Talepler ve onaylı uzaktan destek erişimi. Destek mesaisi hafta içi 09.00–18.00; portal 7/24 talep alır."));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const openTicket = async (id) => {
      const d = await J.get(`support/tickets/${id}`);
      const body = h(`<div class="space-y-3"><div class="text-sm">${kv({ Durum: d.status_label, Öncelik: d.priority_label, Kategori: d.category, İşletme: d.business_name, "İlk yanıt SLA": `${d.sla.first_response}${d.first_response_due ? " · " + J.dt(d.first_response_due) : " (hedef tanımsız)"}`, "Çözüm SLA": `${d.sla.resolution}${d.resolution_due ? " · " + J.dt(d.resolution_due) : ""}`, "Yeniden açılma": d.reopen_count })}</div>
        <p class="whitespace-pre-wrap card p-3">${esc(d.description)}</p>
        <div class="space-y-2">${d.messages.map((m) => `<div class="card p-3 ${m.is_support ? "" : "ml-8"}" style="${m.internal ? "border-style:dashed" : ""}"><div class="text-xs muted">${esc(m.author)} · ${J.dt(m.created_at)}${m.internal ? " · iç not" : ""}</div><div class="whitespace-pre-wrap">${esc(m.body)}</div></div>`).join("")}</div>
        <div class="text-sm">${d.attachments.map((a) => `<button class="underline mr-3" data-att="${a.id}" ${a.purged ? "disabled" : ""}>${J.icon("file-text", 14)} ${esc(a.filename)}${a.purged ? " (imha edildi)" : ""}</button>`).join("")}</div>
        <textarea class="input" rows="3" placeholder="Mesaj yazın…" data-msg></textarea>
        <div class="flex flex-wrap gap-2">${isSupport ? `<label class="flex items-center gap-2 text-sm"><input type="checkbox" data-int> İç not</label>` : ""}<input type="file" data-file class="text-sm"></div>
        <details class="text-xs muted"><summary>Olay geçmişi</summary>${d.events.map((e) => `<div>${J.dt(e.created_at)} · ${esc(e.kind)} ${esc(e.note)}</div>`).join("")}</details></div>`);
      qsa("[data-att]", body).forEach((b) => (b.onclick = () => J.download(`support/tickets/${id}/attachment/${b.dataset.att}`)));
      const acts = [{ label: "Gönder", cls: "btn-primary", close: false, run: async () => {
        const msg = qs("[data-msg]", body).value, file = qs("[data-file]", body).files[0];
        if (file) { const fd = new FormData(); fd.append("file", file); await J.api("POST", `support/tickets/${id}/attach`, fd); }
        if (msg.trim()) await J.post(`support/tickets/${id}/message`, { body: msg, internal: qs("[data-int]", body)?.checked });
        m.close(); openTicket(id);
      } }];
      if (isSupport) ["in_review", "waiting_customer", "resolved", "closed"].forEach((s) => acts.push({ label: { in_review: "İncelemede", waiting_customer: "Yanıt bekle", resolved: "Çözüldü", closed: "Kapat" }[s], run: async () => { await J.post(`support/tickets/${id}/status`, { status: s, note: qs("[data-msg]", body).value }); } }));
      else if (["resolved", "closed"].includes(d.status)) acts.push({ label: "Sorun sürüyor — yeniden aç", run: async () => { await J.post(`support/tickets/${id}/reopen`, { note: qs("[data-msg]", body).value }); } });
      else acts.push({ label: "Talebi kapat", run: async () => { await J.post(`support/tickets/${id}/status`, { status: "closed" }); } });
      const m = J.modal({ title: `#${d.number} ${d.subject}`, body, size: "max-w-3xl", actions: acts });
    };
    J.tabs(c, [
      { key: "tickets", label: "Talepler", render: (el) => J.crud(el, {
        title: "Destek talebi", endpoint: "support/tickets", editable: false, deletable: false, creatable: !isSupport,
        columns: [{ key: "number", label: "No", fmt: (v) => "#" + v }, { key: "subject", label: "Konu" }, ...(isSupport ? [{ key: "business_name", label: "İşletme" }] : []), { key: "priority_label", label: "Öncelik", html: (r) => J.badge(r.priority_label, r.priority === "critical" ? "var(--bad)" : r.priority === "high" ? "var(--warn)" : "var(--info)") }, { key: "status_label", label: "Durum" }, { key: "sla", label: "SLA", html: (r) => J.badge(r.sla.first_response === "undefined" ? "hedef tanımsız" : `${r.sla.first_response}/${r.sla.resolution}`, Object.values(r.sla).includes("breached") ? "var(--bad)" : "var(--muted)") }, { key: "created_at", label: "Açılış", fmt: J.dt }],
        fields: [{ name: "subject", label: "Konu", required: true }, { name: "category", label: "Kategori", type: "select", required: true, options: [["pos", "POS / satış"], ["printer", "Yazıcı"], ["network", "Ağ / bağlantı"], ["payment", "Ödeme"], ["stock", "Stok"], ["report", "Rapor"], ["license", "Lisans"], ["update", "Güncelleme"], ["backup", "Yedek"], ["other", "Diğer"]] },
          { name: "operation_stopped", label: "Operasyon durdu (satış yapılamıyor)", type: "checkbox", wide: true }, { name: "business_impact", label: "İş etkisi", type: "select", required: true, options: [["low", "Düşük"], ["medium", "Orta"], ["high", "Yüksek"]], default: "medium" }, { name: "urgency", label: "Aciliyet", type: "select", required: true, options: [["low", "Düşük"], ["medium", "Orta"], ["high", "Yüksek"]], default: "medium" }, { name: "description", label: "Açıklama", type: "textarea", required: true, rows: 5 }],
        onRow: (r) => openTicket(r.id),
      }) },
      { key: "grants", label: "Uzaktan destek erişimi", render: (el) => {
        el.appendChild(h(`<p class="text-sm muted mb-2">${isSupport ? "Size verilen erişimler. 'Oturumu başlat' ile işletme verisine yalnızca onaylanan kapsam ve süre içinde erişirsiniz; her işlem kaydedilir." : "Müşteri onayı olmadan uzaktan erişim açılamaz. Süre, işlem kapsamı ve veri erişim düzeyi sizin onayınızla belirlenir; istediğiniz an sonlandırabilirsiniz."}</p>`));
        J.crud(el, { title: "Destek erişimi", endpoint: "support/grants", editable: false, deletable: false, creatable: !isSupport && J.can("settings.manage"),
          columns: [{ key: "support_user_name", label: "Destek personeli" }, { key: "business_name", label: "İşletme" }, { key: "scopes", label: "Kapsam", fmt: (v) => v.join(", ") }, { key: "data_access", label: "Veri" }, { key: "expires_at", label: "Bitiş", fmt: J.dt }, { key: "active", label: "Aktif", html: (r) => J.yes(r.active) }, { key: "action_count", label: "İşlem", right: true }],
          fields: [{ name: "support_username", label: "Destek kullanıcı adı", required: true }, { name: "minutes", label: "Süre (dk)", type: "number", default: 30, required: true }, { name: "scopes", label: "İzin verilen işlemler", type: "multiselect", required: true, options: [["read", "Görüntüleme"], ["settings", "Ayarlar"], ["catalog", "Katalog"], ["printers", "Yazıcı"], ["ops", "Yedek/sağlık"]] }, { name: "data_access", label: "Veri erişimi", type: "select", required: true, options: [["anonymized", "Anonimleştirilmiş (varsayılan)"], ["full", "Tam (ek onay)"]] }, { name: "recording_consent", label: "Ekran kaydına açık onay veriyorum", type: "checkbox" }, { name: "reason", label: "Gerekçe", required: true, minLength: 3 }],
          actions: [{ label: "Sonlandır", show: (r) => r.active && !isSupport, run: async (r, reload) => { await J.post(`support/grants/${r.id}/revoke`).catch(J.err); reload(); } },
            { label: "Oturumu başlat", show: (r) => r.active && isSupport, run: async (r) => { await J.post(`support/grants/${r.id}/use`).then((x) => { J.toast(`${x.business} için oturum açıldı`, "ok"); location.href = "/"; }).catch(J.err); } },
            { label: "Bitir", show: (r) => r.active && isSupport, run: async (r, reload) => { await J.post(`support/grants/${r.id}/end`).catch(J.err); reload(); } },
            { label: "İşlem kaydı", run: async (r) => { const a = await J.get(`support/grants/${r.id}/actions`); J.modal({ title: "Destek işlem kaydı", size: "max-w-3xl", body: J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "method", label: "Yöntem" }, { key: "path", label: "Yol" }, { key: "status_code", label: "Sonuç" }], a) }); } }] });
      } },
    ]);
  };

  // ================================================================== MÜŞTERİ PORTALI
  P.portal = async (main) => {
    const d = await J.get("portal/summary");
    main.appendChild(J.pageHead("Müşteri portalı", `${esc(d.business.name)} · POSHANE ${esc(d.version)}`));
    const L = d.license;
    main.appendChild(h(`<div class="grid md:grid-cols-3 gap-3">
      <div class="card p-4"><h3 class="font-semibold mb-2">Lisans ve paket</h3>${L.licensed ? kv({ Paket: L.package, Modüller: L.modules.join(", "), "Destek bitişi": L.support_until, "Şube hakkı": L.max_branches ?? "—", "Cihaz hakkı": `${L.max_terminals ?? "—"} terminal / ${L.max_mobile ?? "—"} mobil` }) : "Lisans kurulu değil"}<a class="btn btn-ghost btn-sm mt-2" href="/settings?tab=license" data-link>Lisans/cihaz yönetimi</a></div>
      <div class="card p-4"><h3 class="font-semibold mb-2">İşletme</h3>${kv({ Şube: d.branches.length, "Aktif kullanıcı": d.users, "Aktif cihaz": d.devices, "Açık destek talebi": d.tickets_open })}<a class="btn btn-ghost btn-sm mt-2" href="/support" data-link>Destek</a></div>
      <div class="card p-4"><h3 class="font-semibold mb-2">Bakım sözleşmesi</h3>${d.contracts.map((c2) => kv({ Başlangıç: c2.starts_on, Bitiş: c2.ends_on, Not: c2.note })).join("") || '<span class="muted">Kayıt yok</span>'}</div>
      <div class="card p-4"><h3 class="font-semibold mb-2">Son yedekler</h3>${d.last_backups.map((b) => `<div class="text-sm py-1 border-b bd">${J.dt(b.created_at)} · ${b.verified_at ? "doğrulandı" : "doğrulanmadı"}</div>`).join("") || '<span class="muted">Yedek yok</span>'}<a class="btn btn-ghost btn-sm mt-2" href="/ops" data-link>Yedek/geri yükleme</a></div>
      <div class="card p-4"><h3 class="font-semibold mb-2">Güncellemeler</h3>${d.updates.map((u) => `<div class="text-sm">${esc(u.version)} · ${esc(u.status)}</div>`).join("") || '<span class="muted">Kayıt yok</span>'}</div>
      <div class="card p-4"><h3 class="font-semibold mb-2">Ödeme geçmişi</h3>${d.payments.map((p) => `<div class="text-sm flex justify-between"><span>${esc(p.paid_on)} ${esc(p.description)}</span><b>${money(p.amount)}</b></div>`).join("") || '<span class="muted">Kayıt yok</span>'}</div>
      <div class="card p-4 md:col-span-3"><h3 class="font-semibold mb-2">Sürüm notları</h3>${d.release_notes.map((r) => `<details class="py-1"><summary><b>${esc(r.version)}</b> ${esc(r.title)} <span class="muted text-xs">${esc(r.published_at)}</span></summary><p class="text-sm whitespace-pre-wrap mt-1">${esc(r.body)}</p></details>`).join("") || '<span class="muted">Not yok</span>'}</div></div>`));
  };

  // ================================================================== PLATFORM
  P.platform = async (main) => {
    main.appendChild(J.pageHead("Platform yönetimi", "Müşteri/işletme, başvuru, lisans, SLA, ticari kayıtlar"));
    const c = h(`<div></div>`);
    main.appendChild(c);
    const MOD = [["stock", "Stok"], ["crm", "CRM"], ["delivery", "Kurye"], ["reservation", "Rezervasyon"], ["staff", "Personel"], ["finance", "Finans"], ["reports_advanced", "Gelişmiş rapor"], ["jetmenu", "JET Menü"], ["multi_branch", "Çok şube"]];
    J.tabs(c, [
      { key: "biz", label: "İşletmeler", show: J.can("platform.manage"), render: (el) => J.crud(el, { title: "İşletme", endpoint: "platform/businesses", perm: "platform.manage", deletable: false,
        columns: [{ key: "name", label: "İşletme" }, { key: "slug", label: "Kod" }, { key: "template", label: "Şablon" }, { key: "branch_count", label: "Şube", right: true }, { key: "license", label: "Lisans", fmt: (v) => (v ? `${v.package} (${v.status})` : "—") }, { key: "is_corporate", label: "Kurumsal", html: (r) => J.yes(r.is_corporate) }],
        fields: (row) => row ? [{ name: "name", label: "Ad", required: true }, { name: "is_active", label: "Aktif", type: "checkbox" }, { name: "is_corporate", label: "Kurumsal/belediye", type: "checkbox" }] : [{ name: "name", label: "İşletme adı", required: true }, { name: "template", label: "Şablon", type: "select", required: true, options: [["restaurant", "Restoran"], ["cafe", "Kafe"], ["breakfast", "Kahvaltı salonu"], ["municipal", "Belediye sosyal tesisi"], ["other", "Diğer"]] }, { name: "owner_username", label: "Sahip kullanıcı adı", required: true }, { name: "owner_email", label: "Sahip e-posta", type: "email" }, { name: "owner_name", label: "Sahip adı" }, { name: "is_corporate", label: "Kurumsal/belediye (manuel kayıt)", type: "checkbox" }],
        toApi: (v, row) => v }) },
      { key: "apps", label: "Başvurular", show: J.can("platform.manage"), render: (el) => J.crud(el, { title: "Başvuru", endpoint: "platform/applications",
        columns: [{ key: "created_at", label: "Tarih", fmt: J.dt }, { key: "business_name", label: "İşletme" }, { key: "contact_name", label: "Yetkili" }, { key: "phone", label: "Telefon" }, { key: "email", label: "E-posta" }, { key: "template", label: "Tür" }, { key: "status", label: "Durum" }],
        actions: [{ label: "Onayla", show: (r) => r.status === "new", run: async (r, reload) => { const v = await J.promptForm("Başvuruyu onayla", [{ name: "owner_username", label: "Sahip kullanıcı adı", required: true, default: r.email.split("@")[0] }]); if (!v) return; const x = await J.post(`platform/applications/${r.id}/approve`, v).catch(J.err); if (x) J.modal({ title: "İşletme oluşturuldu", body: `<p>Kullanıcı: <b>${esc(x.owner)}</b></p><p>Geçici şifre (yalnızca şimdi gösterilir): <code class="text-lg">${esc(x.temporary_password)}</code></p>` }); reload(); } },
          { label: "Reddet", show: (r) => r.status === "new", run: async (r, reload) => { await J.post(`platform/applications/${r.id}/reject`).catch(J.err); reload(); } }] }) },
      { key: "lic", label: "Lisanslar", show: J.can("license.manage"), render: (el) => J.crud(el, { title: "Lisans", endpoint: "platform/licenses", perm: "license.manage", editable: false, deletable: false,
        columns: [{ key: "business_name", label: "İşletme" }, { key: "package", label: "Paket" }, { key: "modules", label: "Modüller", fmt: (v) => v.join(", ") }, { key: "activation_key", label: "Anahtar" }, { key: "status", label: "Durum" }, { key: "support_until", label: "Destek bitişi" }, { key: "activated_at", label: "Aktivasyon", fmt: J.dt }],
        fields: [{ name: "business", label: "İşletme", type: "select", required: true, options: opt("platform/businesses") }, { name: "package", label: "Paket", type: "select", required: true, options: [["starter", "Starter"], ["professional", "Professional"], ["enterprise", "Enterprise"]] }, { name: "modules", label: "Opsiyonel modüller", type: "multiselect", options: MOD }, { name: "max_branches", label: "Şube hakkı (boş = tanımsız)", type: "number" }, { name: "max_users", label: "Eşzamanlı kullanıcı", type: "number" }, { name: "max_terminals", label: "Sabit terminal hakkı", type: "number" }, { name: "max_mobile", label: "Mobil cihaz hakkı", type: "number" }, { name: "support_until", label: "Destek/güncelleme bitişi", type: "date" }],
        actions: [{ label: "İndir (.jetlic)", run: (r) => J.download(`platform/licenses/${r.id}/download`) },
          { label: "QR", run: (r) => J.modal({ title: `${r.business_name} — lisans QR`, body: `<div class="text-center"><img src="/api/platform/licenses/${r.id}/qr" alt="Lisans QR kodu" class="mx-auto bg-white p-2 rounded max-w-full"><p class="text-xs muted mt-2">Şube sunucusunda Ayarlar &gt; Lisans &gt; "İmzalı lisans dosyası / QR metni" alanına okutulan metni girin. Anahtar: <b>${esc(r.activation_key)}</b></p></div>`, actions: [{ label: "Yazdır", run: () => { window.print(); return false; } }, { label: "Kapat" }] }) }, { label: "Askıya al", show: (r) => r.status === "active", run: async (r, reload) => { await J.post(`platform/licenses/${r.id}/set_status`, { status: "suspended" }).catch(J.err); reload(); } }] }) },
      { key: "sla", label: "SLA hedefleri", show: J.can("support.manage"), render: (el) => { el.appendChild(h(`<p class="text-sm muted mb-2">Sayısal SLA hedefleri açık karardır; burada paket ve öncelik bazında tanımlanır. Tanımsızsa talepte süre hesaplanmaz.</p>`)); J.crud(el, { title: "SLA", endpoint: "platform/sla-policies", columns: [{ key: "package", label: "Paket" }, { key: "priority", label: "Öncelik" }, { key: "first_response_minutes", label: "İlk yanıt (dk)", right: true }, { key: "resolution_minutes", label: "Çözüm (dk)", right: true }], fields: [{ name: "package", label: "Paket", type: "select", required: true, options: [["starter", "Starter"], ["professional", "Professional"], ["enterprise", "Enterprise"]] }, { name: "priority", label: "Öncelik", type: "select", required: true, options: [["critical", "Kritik (takvim saati)"], ["high", "Yüksek"], ["normal", "Normal"], ["low", "Düşük"]] }, { name: "first_response_minutes", label: "İlk yanıt (dk)", type: "number", required: true }, { name: "resolution_minutes", label: "Çözüm (dk)", type: "number", required: true }] }); } },
      { key: "pay", label: "Ticari kayıtlar", show: J.can("platform.finance"), render: (el) => J.crud(el, { title: "Ödeme", endpoint: "platform/payments", columns: [{ key: "paid_on", label: "Tarih" }, { key: "business_name", label: "İşletme" }, { key: "description", label: "Açıklama" }, { key: "amount", label: "Tutar", right: true, fmt: money }, { key: "reference", label: "Referans" }], fields: [{ name: "business", label: "İşletme", type: "select", required: true, options: opt("platform/businesses") }, { name: "description", label: "Açıklama", required: true }, { name: "amount", label: "Tutar", type: "money", required: true }, { name: "paid_on", label: "Tarih", type: "date", required: true }, { name: "reference", label: "Referans" }] }) },
      { key: "contracts", label: "Bakım sözleşmeleri", show: J.can("license.manage"), render: (el) => J.crud(el, { title: "Sözleşme", endpoint: "platform/contracts", columns: [{ key: "business", label: "İşletme" }, { key: "starts_on", label: "Başlangıç" }, { key: "ends_on", label: "Bitiş" }, { key: "note", label: "Not" }], fields: [{ name: "business", label: "İşletme", type: "select", required: true, options: opt("platform/businesses") }, { name: "starts_on", label: "Başlangıç", type: "date", required: true }, { name: "ends_on", label: "Bitiş", type: "date", required: true }, { name: "note", label: "Not" }] }) },
      { key: "notes", label: "Sürüm notları", show: J.can("platform.manage"), render: (el) => J.crud(el, { title: "Sürüm notu", endpoint: "platform/release-notes", columns: [{ key: "version", label: "Sürüm" }, { key: "title", label: "Başlık" }, { key: "published_at", label: "Tarih" }], fields: [{ name: "version", label: "Sürüm", required: true }, { name: "title", label: "Başlık", required: true }, { name: "published_at", label: "Tarih", type: "date", required: true }, { name: "body", label: "İçerik", type: "textarea", rows: 6, required: true }] }) },
      { key: "config", label: "Saklama süreleri", show: J.can("platform.manage"), render: async (el) => {
        const d = await J.get("platform/config");
        const f = J.form([{ name: "reopen_window_days", label: "Talep yeniden açma süresi (gün, boş = sınırsız)", type: "number" }, { name: "waiting_customer_reminder_hours", label: "Müşteri yanıtı hatırlatma (saat)", type: "number" }, { name: "action_log_retention_days", label: "Destek işlem kaydı saklama (gün)", type: "number" }, { name: "session_log_retention_days", label: "Oturum/dosya saklama (gün)", type: "number" }, { name: "recording_retention_days", label: "Ekran kaydı saklama (gün)", type: "number" }, { name: "max_support_session_minutes", label: "Azami destek oturumu (dk)", type: "number" }], d);
        const b = h(`<button class="btn btn-primary mt-3">Kaydet</button>`);
        b.onclick = async () => { const v = f.value(); if (v) await J.patch("platform/config", { ...v, reopen_window_days: v.reopen_window_days || null }).then(() => J.toast("Kaydedildi", "ok")).catch(J.err); };
        el.appendChild(h(`<div class="card p-4"></div>`)).append(f.el, b);
      } },
    ]);
  };

  // ================================================================== YARDIM MERKEZİ (AI yok)
  P.help = async (main) => {
    main.appendChild(J.pageHead("Yardım merkezi", "SSS, rehberler ve adım adım sorun giderme. Kural tabanlıdır; yapay zekâ kullanılmaz.", `<input class="input !w-72" type="search" placeholder="Yardımda ara…" data-q>`));
    const out = h(`<div class="grid lg:grid-cols-2 gap-4"></div>`);
    main.appendChild(out);
    const runTree = (tree) => {
      const body = h(`<div></div>`);
      const show = (key, path = []) => {
        const n = tree.nodes[key];
        body.innerHTML = `${path.length ? `<p class="text-xs muted mb-2">${path.map(esc).join(" → ")}</p>` : ""}`;
        if (n.end) { body.appendChild(h(`<div class="card p-4" style="border-color:var(--ok)"><b>Çözüm:</b> ${esc(n.end)}</div>`)); const r = h(`<button class="btn btn-ghost mt-3">Baştan başla</button>`); r.onclick = () => show("start"); body.appendChild(r); return; }
        body.appendChild(h(`<p class="text-lg font-semibold mb-3">${esc(n.q)}</p>`));
        const row = h(`<div class="flex gap-2"><button class="btn btn-primary btn-lg">Evet</button><button class="btn btn-ghost btn-lg">Hayır</button></div>`);
        row.children[0].onclick = () => show(n.yes, [...path, n.q + " Evet"]);
        row.children[1].onclick = () => show(n.no, [...path, n.q + " Hayır"]);
        body.appendChild(row);
      };
      show("start");
      J.modal({ title: tree.title, body, size: "max-w-xl" });
    };
    const load = async (q = "") => {
      const d = await J.get(`help?q=${encodeURIComponent(q)}`);
      out.innerHTML = "";
      const trees = h(`<section class="card p-4"><h2 class="font-semibold mb-3">Sorun giderme</h2></section>`);
      d.trees.forEach((tr) => { const b = h(`<button class="btn btn-ghost w-full justify-start mb-2">${J.icon("wrench", 16)}${esc(tr.title)}</button>`); b.onclick = () => runTree(tr); trees.appendChild(b); });
      const guides = h(`<section class="card p-4"><h2 class="font-semibold mb-3">Rehberler</h2>${d.guides.map((g) => `<details class="mb-2"><summary class="font-medium cursor-pointer">${esc(g.title)}</summary><ol class="list-decimal pl-6 text-sm mt-1 space-y-1">${g.steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>`).join("") || '<p class="muted">Sonuç yok</p>'}</section>`);
      const faq = h(`<section class="card p-4 lg:col-span-2"><h2 class="font-semibold mb-3">Sık sorulan sorular</h2>${d.faq.map((f) => `<details class="mb-2"><summary class="font-medium cursor-pointer">${esc(f.q)}</summary><p class="text-sm mt-1">${esc(f.a)}</p></details>`).join("") || '<p class="muted">Sonuç yok</p>'}</section>`);
      const kb = h(`<section class="card p-4 lg:col-span-2"><h2 class="font-semibold mb-2">Klavye kısayolları</h2><div class="grid sm:grid-cols-2 gap-1 text-sm">${[["/ veya Ctrl+K", "Global arama"], ["F2", "Masalar"], ["F3", "Mutfak"], ["F4", "Kasa"], ["Ctrl+Enter", "Adisyonda mutfağa gönder"], ["F9", "Adisyonda ödeme"], ["Ctrl+L", "Ekranı kilitle"], ["Esc", "Pencereyi kapat"]].map(([k, v]) => `<div><kbd class="badge surface-2">${k}</kbd> ${v}</div>`).join("")}</div></section>`);
      out.append(trees, guides, faq, kb);
    };
    qs("[data-q]", main).addEventListener("input", J.debounce((e) => load(e.target.value), 250));
    await load();
  };

  // ================================================================== DENETİM KAYDI
  P.audit = async (main) => {
    let action = "", d1 = J.today(), d2 = J.today();
    main.appendChild(J.pageHead("Denetim kaydı", "Değiştirilemez işlem kaydı: giriş, indirim, iptal, iade, ödeme, kasa, stok, fiyat, yetki, cihaz, güvenlik", `<input class="input !w-48" placeholder="İşlem (ör. ticket.void)" data-a><input type="date" class="input !w-auto" value="${d1}" data-d1><input type="date" class="input !w-auto" value="${d2}" data-d2>`));
    const box = h(`<div class="card"></div>`);
    main.appendChild(box);
    const load = async () => {
      const rows = await J.get(`audit?date_from=${d1}&date_to=${d2}${action ? "&action=" + encodeURIComponent(action) : ""}`);
      box.innerHTML = "";
      box.appendChild(J.table([{ key: "created_at", label: "Zaman", fmt: J.dt }, { key: "action", label: "İşlem" }, { key: "user_name", label: "Kullanıcı" }, { key: "entity", label: "Kayıt", fmt: (v, r) => `${v} ${r.entity_id}` }, { key: "reason", label: "Gerekçe" }, { key: "ip", label: "IP" }, { key: "support_session", label: "Destek", html: (r) => (r.support_session ? J.yes(true) : "") }], rows, {
        onRow: (r) => J.modal({ title: r.action, size: "max-w-3xl", body: `<div class="grid md:grid-cols-2 gap-3 text-xs"><div><b>Önce</b><pre class="surface-2 p-2 rounded overflow-x-auto">${esc(JSON.stringify(r.before, null, 2))}</pre></div><div><b>Sonra</b><pre class="surface-2 p-2 rounded overflow-x-auto">${esc(JSON.stringify(r.after, null, 2))}</pre></div></div>` }) }));
    };
    qs("[data-a]", main).addEventListener("input", J.debounce((e) => { action = e.target.value; load(); }, 300));
    qs("[data-d1]", main).onchange = (e) => { d1 = e.target.value; load(); };
    qs("[data-d2]", main).onchange = (e) => { d2 = e.target.value; load(); };
    await load();
  };
})();
