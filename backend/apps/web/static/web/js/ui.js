/* POSHANE UI bileşenleri: modal, form, tablo, CRUD sayfası, grafik, PIN, onay akışı. */
(function () {
  const { esc, h, qs, qsa, t, tt } = J;

  // ------------------------------------------------------------------ modal
  J.modal = ({ title, body, actions = [], size = "max-w-lg", onClose, full = false }) => {
    const root = qs("#modal-root");
    const prev = document.activeElement;
    const el = h(`<div class="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" role="dialog" aria-modal="true" aria-label="${esc(title || "")}">
      <div class="absolute inset-0 bg-black/50" data-x></div>
      <div class="relative float w-full ${full ? "h-full sm:h-[92vh] max-w-6xl" : size} max-h-[94vh] flex flex-col rounded-b-none sm:rounded-xl">
        <div class="flex items-center gap-3 px-5 py-3 border-b bd"><h2 class="h2 flex-1" style="font-size:1.0625rem">${esc(title || "")}</h2><button class="btn btn-quiet btn-icon btn-sm" data-x aria-label="Kapat" type="button">${J.icon("x", 18)}</button></div>
        <div class="p-5 overflow-y-auto flex-1" data-body></div>
        <div class="flex flex-wrap gap-2 justify-end px-5 py-3 border-t bd empty:hidden" data-actions></div>
      </div></div>`);
    const b = el.querySelector("[data-body]");
    if (typeof body === "string") b.innerHTML = body; else if (body) b.appendChild(body);
    const close = (v) => { el.remove(); document.removeEventListener("keydown", key); prev?.focus?.(); onClose?.(v); };
    const key = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", key);
    el.querySelectorAll("[data-x]").forEach((x) => (x.onclick = () => close()));
    const acts = el.querySelector("[data-actions]");
    actions.forEach((a) => {
      const btn = h(`<button class="btn ${a.cls || "btn-ghost"}">${esc(tt(a.label))}</button>`);
      btn.onclick = async () => {
        btn.disabled = true;
        try { const r = await a.run?.(close, b); if (r !== false && a.close !== false) close(r); }
        catch (e) { J.err(e); } finally { btn.disabled = false; }
      };
      acts.appendChild(btn);
    });
    root.appendChild(el);
    setTimeout(() => (el.querySelector("[autofocus], input, select, textarea, button.btn-primary") || el.querySelector("button"))?.focus(), 30);
    return { el, body: b, close };
  };

  J.confirm = (msg, { ok = "Evet", danger = false } = {}) => new Promise((resolve) => {
    J.modal({ title: t("Onay"), body: `<p>${esc(msg)}</p>`, onClose: (v) => resolve(v === true),
      actions: [{ label: "Hayır", run: () => false }, { label: ok, cls: danger ? "btn-danger" : "btn-primary", run: () => true }] });
  });

  J.promptForm = (title, fields, { okLabel = "Kaydet", values = {}, size } = {}) => new Promise((resolve) => {
    const form = J.form(fields, values);
    let done = false;
    J.modal({ title, body: form.el, size, onClose: (v) => { if (!done) resolve(v ?? null); },
      actions: [{ label: "İptal", run: () => null }, { label: okLabel, cls: "btn-primary", run: () => {
        const v = form.value();
        if (!v) return false;
        done = true; resolve(v); return v;
      } }] });
  });

  J.askReason = (title, extraFields = []) => J.promptForm(title, [...extraFields, { name: "reason", label: "Gerekçe", type: "textarea", required: true, minLength: 3 }]);

  // ------------------------------------------------------------------ form
  J.form = (fields, values = {}) => {
    const el = h(`<form class="grid grid-cols-1 sm:grid-cols-2 gap-3" novalidate></form>`);
    const inputs = {};
    fields.forEach((f) => {
      if (f.show === false) return;
      const id = "f_" + f.name + "_" + Math.random().toString(36).slice(2, 6);
      const v = values[f.name] ?? f.default ?? (f.type === "checkbox" ? false : f.type === "multiselect" ? [] : "");
      const wrap = h(`<div class="${f.wide || ["textarea", "multiselect", "json"].includes(f.type) ? "sm:col-span-2" : ""}"></div>`);
      let inp;
      if (f.type === "checkbox") {
        wrap.innerHTML = `<label class="flex items-center gap-3 min-h-[44px] cursor-pointer"><input id="${id}" type="checkbox" class="w-5 h-5 accent-[var(--accent)]" ${v ? "checked" : ""}> <span class="text-sm font-medium">${esc(tt(f.label))}</span></label>`;
        inp = wrap.querySelector("input");
      } else {
        wrap.innerHTML = `<label class="label" for="${id}">${esc(tt(f.label))}${f.required ? " *" : ""}</label>`;
        if (f.type === "select" || f.type === "multiselect") {
          inp = h(`<select id="${id}" class="input" ${f.type === "multiselect" ? 'multiple size="5"' : ""}></select>`);
          const opts = typeof f.options === "function" ? [] : f.options || [];
          const fill = (list) => {
            inp.innerHTML = (f.type === "select" && !f.required ? `<option value="">—</option>` : "") +
              list.map(([val, lab]) => `<option value="${esc(val)}">${esc(tt(lab))}</option>`).join("");
            if (f.type === "multiselect") Array.from(inp.options).forEach((o) => (o.selected = (v || []).map(String).includes(o.value)));
            else inp.value = v === null ? "" : String(v);
          };
          fill(opts);
          if (typeof f.options === "function") Promise.resolve(f.options()).then(fill).catch(J.err);
        } else if (f.type === "textarea" || f.type === "json") {
          inp = h(`<textarea id="${id}" class="input" rows="${f.rows || 3}"></textarea>`);
          inp.value = f.type === "json" ? JSON.stringify(v ?? (f.default ?? {}), null, 2) : v ?? "";
        } else {
          const type = { money: "number", number: "number", datetime: "datetime-local", password: "password", email: "email", date: "date", time: "time", color: "color" }[f.type] || "text";
          inp = h(`<input id="${id}" class="input" type="${type}" ${f.type === "money" ? 'step="0.01" min="0" inputmode="decimal"' : f.step ? `step="${f.step}"` : ""} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""} autocomplete="${f.type === "password" ? "new-password" : "off"}">`);
          inp.value = f.type === "datetime" && v ? String(v).slice(0, 16) : v ?? "";
        }
        wrap.appendChild(inp);
        if (f.help) wrap.appendChild(h(`<p class="text-xs muted mt-1">${esc(tt(f.help))}</p>`));
      }
      inputs[f.name] = { f, inp };
      el.appendChild(wrap);
    });
    const value = () => {
      const out = {};
      let ok = true;
      Object.values(inputs).forEach(({ f, inp }) => {
        let v;
        if (f.type === "checkbox") v = inp.checked;
        else if (f.type === "multiselect") v = Array.from(inp.selectedOptions).map((o) => (isNaN(o.value) ? o.value : Number(o.value)));
        else if (f.type === "json") { try { v = JSON.parse(inp.value || "null"); } catch (e) { ok = false; inp.setCustomValidity("Geçersiz JSON"); inp.reportValidity(); return; } }
        else if (f.type === "number" || f.type === "money") v = inp.value === "" ? null : inp.value;
        else if (f.type === "datetime") v = inp.value ? new Date(inp.value).toISOString() : null;
        else if (f.type === "select") v = inp.value === "" ? null : (f.numeric !== false && /^\d+$/.test(inp.value) ? Number(inp.value) : inp.value);
        else v = inp.value;
        if (f.required && (v === null || v === "" || (Array.isArray(v) && !v.length)) || (f.minLength && String(v || "").trim().length < f.minLength)) {
          ok = false; inp.classList.add("ring-2"); inp.style.borderColor = "var(--bad)"; inp.focus();
        } else { inp.style.borderColor = ""; }
        if (f.type === "password" && !v) return;
        out[f.name] = v;
      });
      return ok ? out : null;
    };
    el.addEventListener("submit", (e) => e.preventDefault());
    return { el, value, inputs };
  };

  // ------------------------------------------------------------------ tablo
  J.table = (cols, rows, { empty = "Kayıt yok", onRow, actions } = {}) => {
    if (!rows || !rows.length) return h(J.empty("inbox", empty, ""));
    const el = h(`<div class="overflow-x-auto"><table class="tbl"><thead><tr>${cols.map((c) => `<th scope="col" class="${c.right ? "text-right" : ""}">${esc(tt(c.label))}</th>`).join("")}${actions ? "<th></th>" : ""}</tr></thead><tbody></tbody></table></div>`);
    const tb = el.querySelector("tbody");
    rows.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = cols.map((c) => `<td class="${c.right ? "text-right tabular-nums" : ""}">${c.html ? c.html(r) : esc(c.fmt ? c.fmt(r[c.key], r) : r[c.key])}</td>`).join("");
      if (onRow) { tr.classList.add("cursor-pointer"); tr.tabIndex = 0; tr.onclick = () => onRow(r); tr.onkeydown = (e) => e.key === "Enter" && onRow(r); }
      if (actions) {
        const td = document.createElement("td");
        td.className = "text-right whitespace-nowrap";
        actions.filter((a) => !a.show || a.show(r)).forEach((a) => {
          const b = h(`<button class="btn btn-ghost btn-sm ml-1">${esc(tt(a.label))}</button>`);
          b.onclick = (e) => { e.stopPropagation(); a.run(r); };
          td.appendChild(b);
        });
        tr.appendChild(td);
      }
      tb.appendChild(tr);
    });
    return el;
  };

  /** Durum rozeti: renk yalnızca anlam taşır (ok/warn/bad/info); isteğe bağlı ikon adı. */
  J.badge = (text, color = "var(--info)", icon = "") => `<span class="badge" style="background:color-mix(in srgb, ${color} 14%, var(--surface));color:${color}">${icon ? J.icon(icon, 12) : ""}${esc(text)}</span>`;
  J.yes = (v) => (v ? `<span style="color:var(--ok)" title="Evet">${J.icon("check", 16)}<span class="sr-only-focusable">Evet</span></span>` : `<span class="faint" aria-label="Hayır">—</span>`);
  /** Boş durum: ikon + başlık + açıklama (+ eylem). */
  J.empty = (icon, title, text = "", action = "") => `<div class="empty"><div class="empty-ic">${J.icon(icon, 22)}</div><div class="empty-title">${esc(J.t(title))}</div>${text ? `<p>${esc(J.t(text))}</p>` : ""}${action}</div>`;

  J.pageHead = (title, sub = "", right = "") => h(`<div class="page-head"><div class="flex-1 min-w-[200px]"><h1 class="h1">${esc(tt(title))}</h1>${sub ? `<p class="sub">${J.t(sub)}</p>` : ""}</div><div class="flex flex-wrap items-center gap-2" data-right>${right}</div></div>`);

  J.tabs = (container, tabs, initial) => {
    const bar = h(`<div class="tabbar" role="tablist"></div>`);
    const body = h(`<div></div>`);
    container.append(bar, body);
    const visible = tabs.filter((x) => x.show !== false);
    const select = (key) => {
      qsa("[role=tab]", bar).forEach((b) => { b.setAttribute("aria-selected", String(b.dataset.k === key)); });
      body.innerHTML = "";
      const tab = visible.find((x) => x.key === key) || visible[0];
      Promise.resolve(tab.render(body)).catch(J.err);
      try { history.replaceState(null, "", location.pathname + "?tab=" + tab.key); window.dispatchEvent(new Event("jet:tab")); } catch (e) {}
    };
    visible.forEach((x) => { const b = h(`<button class="tab" role="tab" data-k="${x.key}" aria-selected="false">${esc(tt(x.label))}</button>`); b.onclick = () => select(x.key); bar.appendChild(b); });
    select(new URLSearchParams(location.search).get("tab") || initial || visible[0]?.key);
    return { select };
  };

  // ------------------------------------------------------------------ genel CRUD sayfası
  J.crud = (container, o) => {
    const wrap = h(`<div class="card"><div class="flex flex-wrap items-center gap-2 p-3 border-b bd"><input class="input !w-64" type="search" placeholder="${esc(t("Ara"))}…" data-q aria-label="Ara"><div class="flex-1"></div><span data-extra></span></div><div data-list><div class="p-3 space-y-2" aria-busy="true">${'<div class="skeleton h-9"></div>'.repeat(4)}</div></div></div>`);
    container.appendChild(wrap);
    const list = wrap.querySelector("[data-list]");
    let rows = [];
    const canWrite = o.perm ? J.can(o.perm) : true;
    const edit = async (row) => {
      const fields = typeof o.fields === "function" ? o.fields(row) : o.fields;
      const v = await J.promptForm(row ? `${tt(o.title)} — ${t("Düzenle")}` : `${tt(o.title)} — ${t("Yeni")}`, fields, { values: row ? (o.toForm ? o.toForm(row) : row) : {}, size: o.size || "max-w-2xl" });
      if (!v) return;
      const body = o.toApi ? o.toApi(v, row) : v;
      try {
        const base = o.endpoint.split("?")[0];
        if (row) await J.patch(`${base}/${row.id}`, body); else await J.post(base, body);
        J.toast("Kaydedildi", "ok"); load();
      } catch (e) { J.err(e); }
    };
    const actions = [];
    if (canWrite && o.fields && o.editable !== false) actions.push({ label: "Düzenle", run: edit });
    (o.actions || []).forEach((a) => actions.push({ ...a, run: (r) => a.run(r, load) }));
    if (canWrite && o.deletable !== false && o.fields) actions.push({ label: o.deleteLabel || "Sil", run: async (r) => {
      if (!(await J.confirm(`${o.deleteLabel || t("Sil")}: ${r.name || r.username || r.id}?`, { danger: true }))) return;
      try { await J.del(`${o.endpoint.split("?")[0]}/${r.id}`); J.toast("Tamamlandı", "ok"); load(); } catch (e) { J.err(e); }
    } });
    if (canWrite && o.fields && o.creatable !== false) {
      const nb = h(`<button class="btn btn-primary btn-sm">${J.icon("plus", 16)}${t("Yeni")}</button>`);
      nb.onclick = () => edit(null);
      wrap.querySelector("[data-extra]").appendChild(nb);
    }
    const render = () => {
      const q = wrap.querySelector("[data-q]").value.toLowerCase();
      const filtered = q ? rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q)) : rows;
      list.innerHTML = "";
      list.appendChild(J.table(o.columns, filtered, { actions: actions.length ? actions : null, onRow: o.onRow }));
    };
    const load = async () => {
      try { const d = await J.get(o.endpoint + (o.query ? (o.endpoint.includes("?") ? "&" : "?") + o.query() : "")); rows = o.rows ? o.rows(d) : d; render(); }
      catch (e) { list.innerHTML = J.empty("circle-alert", "Yüklenemedi", e.data?.detail || "Bağlantıyı kontrol edip yeniden deneyin."); }
    };
    wrap.querySelector("[data-q]").addEventListener("input", J.debounce(render, 150));
    load();
    return { reload: load, edit, el: wrap };
  };

  // ------------------------------------------------------------------ grafikler (tema uyumlu SVG)
  const palette = () => [1, 2, 3, 4, 5, 6].map((i) => getComputedStyle(document.documentElement).getPropertyValue(`--chart-${i}`).trim());
  J.chart = (el, spec, { height = 220 } = {}) => {
    el.innerHTML = "";
    if (!spec || !spec.labels || !spec.labels.length) { el.innerHTML = `<div class="muted text-sm p-6 text-center">${t("Kayıt yok")}</div>`; return; }
    const colors = palette();
    const W = Math.max(el.clientWidth || 600, 280), H = height, P = { l: 48, r: 12, t: 12, b: 40 };
    const data = spec.series[0].data.map(Number);
    if (spec.type === "donut") {
      const total = data.reduce((a, b) => a + b, 0) || 1;
      let ang = -Math.PI / 2;
      const R = Math.min(H / 2 - 10, 90), cx = R + 20, cy = H / 2;
      const arcs = data.map((v, i) => {
        const a2 = ang + (v / total) * Math.PI * 2;
        const large = a2 - ang > Math.PI ? 1 : 0;
        const p = (a) => [cx + R * Math.cos(a), cy + R * Math.sin(a)];
        const [x1, y1] = p(ang), [x2, y2] = p(a2 - 0.0001);
        ang = a2;
        return `<path d="M${x1},${y1} A${R},${R} 0 ${large} 1 ${x2},${y2}" stroke="${colors[i % 6]}" stroke-width="26" fill="none"><title>${esc(spec.labels[i])}: ${J.num(v)}</title></path>`;
      }).join("");
      const legend = spec.labels.map((l, i) => `<div class="flex items-center gap-2 text-sm"><span class="dot" style="--st:${colors[i % 6]}"></span><span class="flex-1 truncate">${esc(l)}</span><b class="tabular-nums">${J.num(data[i])}</b><span class="muted text-xs w-10 text-right">%${Math.round((data[i] / total) * 100)}</span></div>`).join("");
      el.innerHTML = `<div class="flex flex-wrap items-center gap-4"><svg width="${2 * R + 40}" height="${H}" role="img" aria-label="${esc(spec.series[0].name)}">${arcs}<text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="14" font-weight="700" fill="var(--text)">${J.num(total, 0)}</text></svg><div class="flex-1 min-w-[160px] space-y-1">${legend}</div></div>`;
      return;
    }
    const max = Math.max(...data, 1);
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const x = (i) => P.l + (spec.type === "bar" ? (i + 0.5) * (iw / data.length) : data.length === 1 ? iw / 2 : (i * iw) / (data.length - 1));
    const y = (v) => P.t + ih - (v / max) * ih;
    const grid = [0, 0.25, 0.5, 0.75, 1].map((g) => `<line x1="${P.l}" x2="${W - P.r}" y1="${y(max * g)}" y2="${y(max * g)}" stroke="var(--border)"/><text x="${P.l - 6}" y="${y(max * g) + 4}" text-anchor="end" font-size="10" fill="var(--muted)">${J.num(max * g, 0)}</text>`).join("");
    const step = Math.ceil(data.length / Math.floor(iw / 48));
    const xl = spec.labels.map((l, i) => (i % step ? "" : `<text x="${x(i)}" y="${H - P.b + 16}" text-anchor="middle" font-size="10" fill="var(--muted)">${esc(String(l).slice(0, 10))}</text>`)).join("");
    let marks;
    if (spec.type === "bar") {
      const bw = Math.max(4, (iw / data.length) * 0.66);
      marks = data.map((v, i) => `<rect x="${x(i) - bw / 2}" y="${y(v)}" width="${bw}" height="${P.t + ih - y(v)}" rx="3" fill="${colors[0]}"><title>${esc(spec.labels[i])}: ${J.num(v)}</title></rect>`).join("");
    } else {
      const pts = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
      marks = `<polygon points="${P.l},${P.t + ih} ${pts} ${x(data.length - 1)},${P.t + ih}" fill="${colors[0]}" opacity=".12"/><polyline points="${pts}" fill="none" stroke="${colors[0]}" stroke-width="2.5"/>` +
        data.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="3.5" fill="${colors[0]}"><title>${esc(spec.labels[i])}: ${J.num(v)}</title></circle>`).join("");
    }
    el.innerHTML = `<svg width="100%" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(spec.series[0].name)}">${grid}${marks}${xl}</svg>`;
  };

  // ------------------------------------------------------------------ PIN pad ve yetkili onayı
  J.pinPad = (onDone, { title = "PIN" } = {}) => {
    const el = h(`<div class="max-w-xs mx-auto"><div class="text-center text-sm muted mb-2">${esc(title)}</div><div class="text-center text-3xl tracking-[.5em] h-12 font-bold" data-d aria-live="polite"></div><div class="grid grid-cols-3 gap-2 mt-2">${[1, 2, 3, 4, 5, 6, 7, 8, 9, "back", 0, "ok"].map((k) => `<button type="button" class="btn ${k === "ok" ? "btn-primary" : "btn-ghost"} btn-lg" style="font-size:1.25rem" data-k="${k}" aria-label="${k === "back" ? "Sil" : k === "ok" ? "Onayla" : k}">${k === "back" ? J.icon("undo-2", 22) : k === "ok" ? J.icon("check", 24) : k}</button>`).join("")}</div></div>`);
    let pin = "";
    const d = el.querySelector("[data-d]");
    const upd = () => (d.innerHTML = Array.from(pin, () => `<span class="dot" style="--st:var(--text);width:.8rem;height:.8rem;margin:0 .3rem"></span>`).join(""));
    const press = (k) => { if (k === "back") pin = pin.slice(0, -1); else if (k === "ok") { if (pin.length >= 4) onDone(pin); } else if (pin.length < 8) pin += k; upd(); };
    el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => press(b.dataset.k)));
    el.tabIndex = 0;
    el.addEventListener("keydown", (e) => { if (/^\d$/.test(e.key)) press(e.key); if (e.key === "Backspace") press("back"); if (e.key === "Enter") press("ok"); });
    el.reset = () => { pin = ""; upd(); };
    return el;
  };

  /** Yetkisiz hassas işlem: yetkili PIN ile anında onay veya onay talebi (§2.1, §15.1). */
  J.withApproval = async (run) => {
    try { return await run({}); }
    catch (e) {
      if (!(e instanceof J.ApiError) || e.data?.code !== "approval_required") throw e;
      const users = await J.get("auth/pin-users").catch(() => []);
      return new Promise((resolve, reject) => {
        const body = h(`<div class="space-y-4"><p class="text-sm">${esc("Bu işlem için yetkili onayı gerekiyor.")}</p>
          <div><label class="label">Onaylayan yetkili</label><select class="input" data-u>${users.map((u) => `<option value="${u.id}">${esc(u.name)} — ${esc(u.role)}</option>`).join("")}</select></div><div data-pin></div></div>`);
        const m = J.modal({ title: "Yetkili onayı", body, actions: [
          { label: "Onay iste (bildirim gönder)", cls: "btn-ghost", run: async () => { const r = await run({ request_approval: true }); J.toast("Onay talebi gönderildi", "info"); resolve(r); } },
        ], onClose: () => resolve(null) });
        body.querySelector("[data-pin]").appendChild(J.pinPad(async (pin) => {
          try { const r = await run({ approver: { user_id: Number(body.querySelector("[data-u]").value), pin } }); m.close(); resolve(r); }
          catch (x) { J.err(x); body.querySelector("[data-pin] > div").reset?.(); }
        }, { title: "Yetkili PIN" }));
      });
    }
  };

  J.download = async (url, filename) => {
    try {
      const res = await J.api("GET", url, undefined, { raw: true });
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = filename || (res.headers.get("Content-Disposition") || "").split("filename=")[1]?.replace(/"/g, "") || "jetpos";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { J.err(e); }
  };
})();
