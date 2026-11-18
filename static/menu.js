(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const state = { items: [], currency: "₹", vegOnly: false, hideSold: false };

  const tableNo = (new URLSearchParams(location.search).get("t") || "").replace(/\D/g, "").slice(0, 3);
  if (tableNo) $("#table").textContent = "Table " + tableNo;

  function money(paise) {
    const r = paise / 100;
    return state.currency + (Number.isInteger(r) ? r : r.toFixed(2));
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;   // textContent only: item text is never parsed as HTML
    return n;
  }

  function render() {
    const root = $("#menu");
    root.textContent = "";
    const cats = [];
    const byCat = new Map();
    for (const it of state.items) {
      if (state.vegOnly && !it.veg) continue;
      if (state.hideSold && it.status === "sold_out") continue;
      if (!byCat.has(it.category)) { byCat.set(it.category, []); cats.push(it.category); }
      byCat.get(it.category).push(it);
    }
    if (!cats.length) { root.appendChild(el("div", "empty", "Nothing to show with these filters.")); return; }
    for (const c of cats) {
      root.appendChild(el("h2", "cat", c));
      for (const it of byCat.get(c)) {
        const row = el("div", "item" + (it.status === "sold_out" ? " sold" : ""));
        const left = el("div");
        const name = el("div", "name");
        name.appendChild(el("span", "dot" + (it.veg ? " veg" : "")));
        name.appendChild(document.createTextNode(it.name));
        left.appendChild(name);
        if (it.description) left.appendChild(el("div", "desc", it.description));
        const right = el("div", "right");
        right.appendChild(el("div", "price", money(it.price_paise)));
        if (it.status === "sold_out") right.appendChild(el("span", "badge sold", "Sold out"));
        else if (it.status === "low") right.appendChild(el("span", "badge low", "Only " + it.stock + " left"));
        row.append(left, right);
        root.appendChild(row);
      }
    }
  }

  async function poll() {
    try {
      const r = await fetch("/api/menu", { cache: "no-cache" });
      if (!r.ok) throw new Error(r.status);
      const d = await r.json();
      state.items = d.items;
      state.currency = d.currency;
      $("#name").textContent = d.name;
      document.title = d.name + " menu";
      render();
      $("#status").textContent = "Live · updated " + new Date().toLocaleTimeString();
    } catch (e) {
      $("#status").textContent = "Offline. Showing the last menu we loaded.";
    }
  }

  function toggle(id, key) {
    const b = $(id);
    b.addEventListener("click", () => {
      state[key] = !state[key];
      b.setAttribute("aria-pressed", String(state[key]));
      render();
    });
  }
  toggle("#vegOnly", "vegOnly");
  toggle("#hideSold", "hideSold");

  poll();
  setInterval(() => { if (!document.hidden) poll(); }, 5000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
