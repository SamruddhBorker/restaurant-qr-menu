(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  let items = [];
  let currency = "₹";
  let editingId = null;

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  async function api(method, path, body) {
    const opts = { method, headers: { "X-Staff": "1" } };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (r.status === 401 && path !== "/api/staff/login") showLogin();
    if (!r.ok) throw new Error(data.error || "Request failed (" + r.status + ")");
    return data;
  }

  function showLogin() {
    $("#loginCard").classList.remove("hidden");
    $("#app").classList.add("hidden");
    $("#logout").classList.add("hidden");
  }
  function showApp() {
    $("#loginCard").classList.add("hidden");
    $("#app").classList.remove("hidden");
    $("#logout").classList.remove("hidden");
    load();
  }

  const money = (p) => currency + (p / 100 % 1 === 0 ? p / 100 : (p / 100).toFixed(2));
  function say(id, text, ok) { const m = $(id); m.textContent = text || ""; m.className = "msg" + (ok ? " ok" : ""); }

  async function load() {
    const r = await fetch("/api/menu", { cache: "no-cache" });
    const d = await r.json();
    items = d.items; currency = d.currency;
    renderList();
  }

  function renderList() {
    const list = $("#list");
    list.textContent = "";
    for (const it of items) {
      const row = el("div", "srow");
      const status = it.status === "sold_out" ? "SOLD OUT" : it.stock === null ? "unlimited" : it.stock + " left";
      row.appendChild(el("div", "", it.name + " · " + money(it.price_paise)));
      row.appendChild(el("div", "meta", it.category + " · " + status));
      const ctl = el("div", "row");
      const stock = el("input"); stock.type = "number"; stock.min = "0"; stock.max = "9999";
      stock.placeholder = "∞"; stock.value = it.stock === null ? "" : it.stock;
      stock.setAttribute("aria-label", "Stock for " + it.name);
      const save = el("button", "ghost", "Set stock");
      save.onclick = () => act(() => api("PUT", "/api/staff/items/" + it.id,
        { stock: stock.value === "" ? null : Number(stock.value), available: 1 }));
      const sold = el("button", "", "−1 sold");
      sold.disabled = it.stock === null || it.stock === 0;
      sold.onclick = () => act(() => api("POST", "/api/staff/items/" + it.id + "/sold", {}));
      const sw = el("button", "ghost", it.available ? "Mark sold out" : "Back in stock");
      sw.onclick = () => act(() => api("PUT", "/api/staff/items/" + it.id, { available: it.available ? 0 : 1 }));
      const edit = el("button", "ghost", "Edit");
      edit.onclick = () => startEdit(it);
      const del = el("button", "danger", "Delete");
      del.onclick = () => { if (confirm('Delete "' + it.name + '"?')) act(() => api("DELETE", "/api/staff/items/" + it.id)); };
      ctl.append(stock, save, sold, sw, edit, del);
      row.appendChild(ctl);
      list.appendChild(row);
    }
    if (!items.length) list.appendChild(el("div", "sub", "No items yet. Add one below."));
  }

  async function act(fn) {
    try { say("#listMsg", ""); await fn(); await load(); }
    catch (e) { say("#listMsg", e.message); }
  }

  function startEdit(it) {
    editingId = it.id;
    $("#formTitle").textContent = "Edit item";
    $("#fSubmit").textContent = "Save changes";
    $("#fCancel").classList.remove("hidden");
    $("#fName").value = it.name; $("#fCat").value = it.category; $("#fDesc").value = it.description;
    $("#fPrice").value = it.price_paise / 100; $("#fStock").value = it.stock === null ? "" : it.stock;
    $("#fOrder").value = it.sort_order; $("#fVeg").checked = it.veg;
    $("#itemForm").scrollIntoView({ behavior: "smooth" });
  }
  function resetForm() {
    editingId = null;
    $("#itemForm").reset();
    $("#formTitle").textContent = "Add item";
    $("#fSubmit").textContent = "Add item";
    $("#fCancel").classList.add("hidden");
  }
  $("#fCancel").onclick = resetForm;

  $("#itemForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {
      name: $("#fName").value, category: $("#fCat").value, description: $("#fDesc").value,
      price_paise: Math.round(Number($("#fPrice").value) * 100),
      stock: $("#fStock").value === "" ? null : Number($("#fStock").value),
      sort_order: Number($("#fOrder").value || 0), veg: $("#fVeg").checked ? 1 : 0, available: 1,
    };
    try {
      if (editingId) await api("PUT", "/api/staff/items/" + editingId, body);
      else await api("POST", "/api/staff/items", body);
      say("#formMsg", editingId ? "Saved." : "Added.", true);
      resetForm(); await load();
    } catch (err) { say("#formMsg", err.message); }
  });

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/staff/login", { pin: $("#pin").value });
      $("#pin").value = ""; say("#loginMsg", ""); showApp();
    } catch (err) { say("#loginMsg", err.message); }
  });
  $("#logout").onclick = async () => { try { await api("POST", "/api/staff/logout", {}); } catch (e) {} showLogin(); };

  // QR codes
  $("#qBase").value = location.origin;
  function checkWarn() {
    $("#qWarn").classList.toggle("hidden", !/\/\/(localhost|127\.0\.0\.1|\[::1\])/i.test($("#qBase").value));
  }
  $("#qBase").addEventListener("input", checkWarn); checkWarn();
  $("#qGo").onclick = () => {
    const grid = $("#qGrid");
    grid.textContent = "";
    let base = $("#qBase").value.trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(base)) { say("#qMsg", "Address must start with http:// or https://"); return; }
    const n = Math.min(60, Math.max(1, Number($("#qTables").value) || 1));
    say("#qMsg", "Scan one with your phone before printing.", true);
    for (let t = 1; t <= n; t++) {
      const url = base + "/?t=" + t;
      const card = el("div", "qrcard");
      const img = el("img"); img.alt = "QR code for table " + t;
      img.src = "/api/staff/qr.svg?data=" + encodeURIComponent(url);
      card.append(img, el("strong", "", "Table " + t), el("div", "meta", "Scan for the menu"));
      grid.appendChild(card);
    }
  };
  $("#qPrint").onclick = () => window.print();

  // start
  fetch("/api/staff/session").then((r) => r.json()).then((d) => (d.signed_in ? showApp() : showLogin()));
  // refresh the list now and then, but never while staff are typing in a field
  setInterval(() => {
    const typing = document.activeElement && document.activeElement.tagName === "INPUT";
    if (!document.hidden && !typing && !$("#app").classList.contains("hidden")) load();
  }, 10000);
})();
