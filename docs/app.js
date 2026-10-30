/* Addis Events Radar dashboard: reads the JSON the monitor writes to data/. */
(() => {
  "use strict";

  const REPO = "carlosopitz/addis-events-radar";
  const PAGE = 80;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  const store = {
    get(k, d) { try { const v = localStorage.getItem("aer." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("aer." + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  const state = {
    items: [], sources: [], byId: {}, status: { channels: {} }, discovered: { sources: {} },
    mode: store.get("mode", "events"), shown: PAGE,
    lastSeen: store.get("lastSeen", null),
  };

  const TYPE_LABEL = { web: "Website", rss: "Feed", telegram: "Telegram", gnews: "Press", json: "Website" };
  const KIND_LABEL = { cultural: "Cultural institute", embassy: "Embassy", eu: "European Union", aggregator: "Listings & press" };
  const LINK_LABEL = { x: "X", facebook: "Facebook", instagram: "Instagram", telegram: "Telegram", youtube: "YouTube",
    linkedin: "LinkedIn", tiktok: "TikTok", bluesky: "Bluesky", flickr: "Flickr", newsletter: "Newsletter", social: "Social media", pressroom: "Press room" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const flag = (cc) => {
    if (!cc || cc.length !== 2 || cc === "XX") return "📰";
    return String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
  };
  const ago = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 90) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : d < 45 ? `${d} days ago` : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };
  const dayLabel = (iso) => {
    const d = new Date(iso); const t = new Date();
    const key = (x) => x.toDateString();
    const y = new Date(t); y.setDate(t.getDate() - 1);
    if (key(d) === key(t)) return "Today";
    if (key(d) === key(y)) return "Yesterday";
    return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  };
  const fmtDate = (ymd) => ymd ? new Date(ymd + "T12:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";

  async function getJSON(path, fallback) {
    try {
      const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } catch { return fallback; }
  }

  async function load() {
    const [items, sources, status, discovered] = await Promise.all([
      getJSON("data/items.json", []),
      getJSON("data/sources.json", { sources: [] }),
      getJSON("data/status.json", { channels: {} }),
      getJSON("data/discovered.json", { sources: {} }),
    ]);
    state.items = items;
    state.sources = sources.sources || [];
    state.byId = Object.fromEntries(state.sources.map((s) => [s.id, s]));
    state.status = status;
    state.discovered = discovered;
    if (state.lastSeen === null) { // first visit: treat everything up to now as seen
      state.lastSeen = status.checked || new Date().toISOString();
      store.set("lastSeen", state.lastSeen);
    }
    fillSourceSelect();
    renderMeta();
    renderAll();
  }

  function renderMeta() {
    const ch = Object.values(state.status.channels || {});
    const ok = ch.filter((c) => c.ok).length;
    $("#meta").innerHTML = state.status.checked
      ? `Checked ${esc(ago(state.status.checked))} · ${state.sources.length} sources · ${ok}/${ch.length} channels OK`
      : "Waiting for the first check to run";
    const n = state.items.filter((i) => !i.baseline && i.first_seen > state.lastSeen).length;
    const badge = $("#newCount");
    badge.hidden = !n; badge.textContent = n;
    document.title = n ? `(${n}) Addis Events Radar` : "Addis Events Radar";
  }

  function fillSourceSelect() {
    const sel = $("#source");
    const opts = [...state.sources].sort((a, b) => a.name.localeCompare(b.name))
      .map((s) => `<option value="${esc(s.id)}">${flag(s.country)} ${esc(s.name)}</option>`).join("");
    sel.innerHTML = `<option value="">All sources</option>${opts}`;
  }

  // ------------------------------------------------------------- latest
  function filteredItems() {
    const q = $("#q").value.trim().toLowerCase();
    const kind = $("#kind").value, region = $("#region").value, src = $("#source").value;
    const withBase = $("#baseline").checked;
    return state.items.filter((i) => {
      const s = state.byId[i.source]; if (!s) return false;
      if (!withBase && i.baseline) return false;
      if (state.mode === "events" && !i.event) return false;
      if (kind && s.kind !== kind) return false;
      if (region && s.region !== region) return false;
      if (src && i.source !== src) return false;
      if (q && !(`${i.title} ${i.summary} ${s.name}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }

  function renderLatest() {
    const list = filteredItems();
    const feed = $("#feed");
    if (!list.length) {
      const anyReal = state.items.some((i) => !i.baseline);
      feed.innerHTML = `<div class="empty">${
        !state.items.length ? "No data yet. The first check runs right after setup; refresh in a few minutes."
        : !anyReal && !$("#baseline").checked ? "Nothing new since monitoring began. Tick <b>Include posts from before monitoring began</b> to browse what is already on their sites."
        : state.mode === "events" ? "No event posts match. Try <b>All posts</b>." : "Nothing matches these filters."}</div>`;
      return;
    }
    const real = list.filter((i) => !i.baseline);
    const base = list.filter((i) => i.baseline)
      .sort((a, b) => (b.published || "").localeCompare(a.published || ""));
    let html = "", lastDay = null, n = 0;
    for (const i of real) {
      if (n++ >= state.shown) break;
      const d = dayLabel(i.first_seen);
      if (d !== lastDay) { html += `<h2 class="day">${esc(d)}</h2>`; lastDay = d; }
      html += itemHTML(i);
    }
    if (base.length && n < state.shown) {
      html += `<h2 class="day">Already on their sites when monitoring began</h2>`;
      for (const i of base) { if (n++ >= state.shown) break; html += itemHTML(i); }
    }
    if (list.length > state.shown) html += `<button class="ghost more" id="moreBtn">Show more (${list.length - state.shown} left)</button>`;
    feed.innerHTML = html;
    const more = $("#moreBtn");
    if (more) more.onclick = () => { state.shown += PAGE; renderLatest(); };
  }

  function itemHTML(i) {
    const s = state.byId[i.source];
    const isNew = !i.baseline && i.first_seen > state.lastSeen;
    const when = i.published ? fmtDate(i.published) : `seen ${ago(i.first_seen)}`;
    return `<article class="item${isNew ? " is-new" : ""}">
      <div class="flag" title="${esc(s.country)}">${flag(s.country)}</div>
      <div>
        <div class="item-head">
          <a class="src" href="#sources" data-src="${esc(s.id)}">${esc(s.name)}</a>
          <span class="chip">${esc(TYPE_LABEL[i.type] || i.type)}</span>
          ${i.event ? '<span class="chip event">Event</span>' : ""}
          ${isNew ? '<span class="chip new">New</span>' : ""}
          <span>${esc(when)}</span>
        </div>
        <h3><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a></h3>
        ${i.summary ? `<p>${esc(i.summary)}</p>` : ""}
      </div>
    </article>`;
  }

  // ------------------------------------------------------------ sources
  function mergedLinks(s) {
    const out = [];
    const seen = new Set();
    const norm = (u) => u.toLowerCase().replace(/^https?:\/\/(www\.|web\.|m\.)?/, "").replace(/^twitter\.com/, "x.com")
      .replace(/[?#].*$/, "").replace(/\/$/, "");
    const add = (kind, url, found) => {
      const k = norm(url);
      if (seen.has(k)) return; seen.add(k); out.push({ kind, url, found });
    };
    const curated = s.links || {};
    for (const [k, v] of Object.entries(curated)) add(k, v, false);
    const d = (state.discovered.sources || {})[s.id];
    if (d) { // links found on their website, unless a hand-checked link of that kind exists
      for (const [k, arr] of Object.entries(d.links || {})) if (!curated[k]) arr.slice(0, 1).forEach((u) => add(k, u, true));
      if (!curated.newsletter) (d.newsletter || []).slice(0, 1).forEach((u) => add("newsletter", u, true));
    }
    return out;
  }

  function sourceActivity(id) {
    let last = null;
    for (const i of state.items) if (i.source === id && !i.baseline && (!last || i.first_seen > last)) last = i.first_seen;
    return last;
  }

  function renderSources() {
    const q = $("#sq").value.trim().toLowerCase(), kind = $("#skind").value, sort = $("#ssort").value;
    let list = state.sources.filter((s) => (!kind || s.kind === kind) && (!q || `${s.name} ${s.id} ${s.notes || ""}`.toLowerCase().includes(q)));
    list = list.map((s) => ({ s, last: sourceActivity(s.id) }));
    list.sort(sort === "name" ? (a, b) => a.s.name.localeCompare(b.s.name)
      : (a, b) => (b.last || "").localeCompare(a.last || "") || a.s.name.localeCompare(b.s.name));
    $("#grid").innerHTML = list.map(({ s, last }) => {
      const links = mergedLinks(s);
      const chans = (s.channels || []).map((c) => {
        const st = (state.status.channels || {})[c.key];
        const cls = !st ? "idle" : st.ok ? "" : "bad";
        const href = c.type === "telegram" ? `https://t.me/s/${c.url.replace(/^@/, "")}`
          : c.type === "gnews" ? `https://news.google.com/search?q=${encodeURIComponent(c.url)}` : c.url;
        const tip = !st ? "not checked yet" : st.ok ? `OK, ${st.found} posts readable` : st.error;
        return `<a href="${esc(href)}" target="_blank" rel="noopener" title="${esc(tip)}"><span class="dot ${cls}"></span>${esc(c.label || TYPE_LABEL[c.type] || c.type)}</a>`;
      }).join("");
      return `<div class="card" id="src-${esc(s.id)}">
        <div class="card-head"><span class="flag">${flag(s.country)}</span>
          <div><h3>${esc(s.name)}</h3><div class="kind">${esc(KIND_LABEL[s.kind] || s.kind)} · ${esc(s.region || "")}</div></div></div>
        ${(s.channels || []).length ? `<div class="last">Last new post: ${esc(last ? ago(last) : "none since monitoring began")}</div>` : ""}
        <div class="links">
          ${s.homepage ? `<a href="${esc(s.homepage)}" target="_blank" rel="noopener">Website</a>` : ""}
          ${links.map((l) => `<a class="${l.found ? "found" : ""}" href="${esc(l.url)}" target="_blank" rel="noopener" title="${l.found ? "Linked from their website" : "Curated"}">${esc(LINK_LABEL[l.kind] || l.kind)}</a>`).join("")}
        </div>
        ${chans ? `<div class="channels"><span class="watch">Watching:</span>${chans}</div>` : ""}
        ${s.manual ? `<p class="note manual">Not checked automatically. ${esc(s.manual)}</p>` : ""}
        ${s.notes ? `<p class="note">${esc(s.notes)}</p>` : ""}
      </div>`;
    }).join("") || `<div class="empty">No sources match.</div>`;
  }

  // ------------------------------------------------------------- health
  function renderHealth() {
    const rows = Object.entries(state.status.channels || {}).map(([key, c]) => ({ key, ...c }))
      .sort((a, b) => (a.ok - b.ok) || (a.found - b.found) || a.source.localeCompare(b.source));
    $("#health").innerHTML = `<thead><tr><th>Source</th><th>Channel</th><th>Status</th><th class="num">Found</th><th>Last new</th><th>URL / query</th></tr></thead><tbody>${
      rows.map((c) => {
        const s = state.byId[c.source] || { name: c.source, country: "XX" };
        const status = c.ok ? (c.found ? "OK" : "OK, no posts read") : esc(c.error || "error");
        return `<tr class="${c.ok ? "" : "bad"}"><td>${flag(s.country)} ${esc(s.name)}</td><td>${esc(c.label || TYPE_LABEL[c.type] || c.type)}</td>
          <td>${status}</td><td class="num">${c.found}</td><td>${esc(c.last_new ? ago(c.last_new) : "none yet")}</td><td class="url">${esc(c.url)}</td></tr>`;
      }).join("")}</tbody>`;
  }

  // -------------------------------------------------------------- wiring
  function renderAll() { renderLatest(); renderSources(); renderHealth(); }

  function showTab(name) {
    $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    $$(".tab").forEach((t) => { t.hidden = t.id !== `tab-${name}`; });
    if (location.hash.slice(1) !== name) history.replaceState(null, "", `#${name}`);
  }

  function init() {
    $("#editLink").href = `https://github.com/${REPO}/edit/main/sources.yaml`;
    $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
    $$(".seg button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode));
      b.addEventListener("click", () => {
        state.mode = b.dataset.mode; store.set("mode", state.mode); state.shown = PAGE;
        $$(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        renderLatest();
      });
    });
    ["#q", "#kind", "#region", "#source", "#baseline"].forEach((s) =>
      $(s).addEventListener("input", () => { state.shown = PAGE; renderLatest(); }));
    ["#sq", "#skind", "#ssort"].forEach((s) => $(s).addEventListener("input", renderSources));
    $("#markSeen").addEventListener("click", () => {
      state.lastSeen = new Date().toISOString(); store.set("lastSeen", state.lastSeen); renderMeta(); renderLatest();
    });
    document.addEventListener("click", (e) => {
      const a = e.target.closest("a[data-src]"); if (!a) return;
      e.preventDefault(); showTab("sources");
      const card = document.getElementById(`src-${a.dataset.src}`);
      if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.style.outline = "2px solid var(--accent)"; setTimeout(() => (card.style.outline = ""), 1600); }
    });
    const h = location.hash.slice(1);
    showTab(["latest", "sources", "health"].includes(h) ? h : "latest");
    load();
    setInterval(async () => { // refresh data every 10 minutes while open
      const st = await getJSON("data/status.json", null);
      if (st && st.checked !== state.status.checked) load(); else renderMeta();
    }, 600000);
  }

  init();
})();
