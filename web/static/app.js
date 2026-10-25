// Roomprint front end: one household (the sample, or a live run on the visitor's photos) drawn as
// photos with boxes on the left and the insurer's list on the right, linked both ways.
const $ = (s, el = document) => el.querySelector(s);
const money = v => v == null ? "—" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
const money2 = v => v == null ? "—" : "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = { h: null, base: "", photo: null, room: "all", sizes: {}, job: null, live: false };

function photoUrl(pid) { return `${S.base}/${pid}.jpg`; }

// crop of a photo as a CSS background: boxf is [x0,y0,x1,y1] as fractions of the photo
function cropStyle(pid, boxf, w, h) {
  const z = S.sizes[pid];
  if (!z || !boxf) return `background-image:url(${photoUrl(pid)})`;
  const [x0, y0, x1, y1] = [boxf[0] * z.w, boxf[1] * z.h, boxf[2] * z.w, boxf[3] * z.h];
  const bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
  const k = Math.max(w / bw, h / bh);
  const cx = (x0 + x1) / 2 * k, cy = (y0 + y1) / 2 * k;
  return `background-image:url(${photoUrl(pid)});background-size:${z.w * k}px ${z.h * k}px;` +
         `background-position:${w / 2 - cx}px ${h / 2 - cy}px`;
}

function loadSizes(pids) {
  return Promise.all(pids.map(pid => new Promise(res => {
    const im = new Image();
    im.onload = () => { S.sizes[pid] = { w: im.naturalWidth, h: im.naturalHeight }; res(); };
    im.onerror = res;
    im.src = photoUrl(pid);
  })));
}

function chip(p) {
  if (!p || p.status === undefined) return `<span class="chip pending">pricing…</span>`;
  if (p.status === "priced") return `<span class="chip priced">${p.sources.length} stores</span>`;
  if (p.status === "one source") return `<span class="chip one">1 store</span>`;
  if (p.status === "check") return `<span class="chip one">check</span>`;
  return `<span class="chip none">needs a price</span>`;
}

function roomsOf(items) {
  const c = {};
  items.forEach(l => c[l.room] = (c[l.room] || 0) + 1);
  return Object.entries(c).sort((a, b) => b[1] - a[1]);
}

function countUp(el, to, ms = 1400) {
  const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 3);
    el.textContent = money(to * e);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function drawTotals(animate) {
  const t = S.h.totals;
  $("#totals").innerHTML = `
    <div class="tot main"><small>Replacement cost</small><b>${money(t.rcv)}</b></div>
    <div class="tot"><small>Actual cash value</small><b>${money(t.acv)}</b></div>
    <div class="tot"><small>Things</small><b>${t.items}</b></div>
    <div class="tot"><small>Need a price</small><b>${t.needs_price}</b></div>`;
  if (animate) { countUp($("#totals .tot.main b"), t.rcv); countUp($("#totals .tot:nth-child(2) b"), t.acv); }
}

function drawRoll() {
  const pids = Object.keys(S.h.photos);
  $("#roll").innerHTML = pids.map(pid => {
    const ph = S.h.photos[pid];
    return `<button data-p="${pid}" class="${pid === S.photo ? "on" : ""}" title="${esc(ph.room)}${ph.taken ? ", " + ph.taken : ""}">
      <img src="${photoUrl(pid)}" alt="${esc(ph.room)}" loading="lazy"><span class="n">${ph.n_items ?? ""}</span></button>`;
  }).join("");
  $("#roll").querySelectorAll("button").forEach(b => b.onclick = () => showPhoto(b.dataset.p));
}

function itemsInPhoto(pid) {
  const out = [];
  S.h.items.forEach(l => (l.sightings || []).forEach(s => { if (s.photo === pid) out.push({ l, s }); }));
  return out;
}

function showPhoto(pid, hot) {
  S.photo = pid;
  const ph = S.h.photos[pid];
  $("#big").src = photoUrl(pid);
  $("#caption").textContent = `${ph.room[0].toUpperCase() + ph.room.slice(1)}` +
    (ph.taken ? ` · photo taken ${new Date(ph.taken + "T12:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}` : " · no date in the file") +
    ` · ${itemsInPhoto(pid).length} things on the list` + (ph.error ? ` · ${ph.error}` : "");
  $("#boxes").innerHTML = itemsInPhoto(pid).map(({ l, s }) => {
    const [x0, y0, x1, y1] = s.boxf;
    return `<div class="box ${l.sightings.length > 1 ? "merged" : ""}" data-n="${l.n}"
      style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%">
      <span class="tag">${esc(l.name)}${l.unit_rcv ? " · " + money(l.rcv) : ""}</span></div>`;
  }).join("");
  const boxes = [...$("#boxes").children];
  boxes.forEach((b, i) => setTimeout(() => b.classList.add("on"), 40 * i));
  boxes.forEach(b => {
    b.onmouseenter = () => markLine(b.dataset.n, true);
    b.onmouseleave = () => markLine(b.dataset.n, false);
    b.onclick = () => openLine(b.dataset.n);
  });
  $("#roll").querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.p === pid));
  if (hot) markBox(hot, true);
}

function markBox(n, on) { $("#boxes").querySelectorAll(`.box[data-n="${n}"]`).forEach(b => b.classList.toggle("hot", on)); }
function markLine(n, on) { const li = $(`#lines .line[data-n="${n}"]`); if (li) li.classList.toggle("hot", on); }

function openLine(n) {
  const li = $(`#lines .line[data-n="${n}"]`);
  if (!li) { S.room = "all"; drawRooms(); drawLines(); return openLine(n); }
  li.scrollIntoView({ block: "center", behavior: "smooth" });
  toggleMore(li, true);
}

function drawRooms() {
  const rs = roomsOf(S.h.items);
  $("#rooms").innerHTML = `<button data-r="all" class="${S.room === "all" ? "on" : ""}">All<span>${S.h.items.length}</span></button>` +
    rs.map(([r, n]) => `<button data-r="${esc(r)}" class="${S.room === r ? "on" : ""}">${esc(r)}<span>${n}</span></button>`).join("");
  $("#rooms").querySelectorAll("button").forEach(b => b.onclick = () => {
    S.room = b.dataset.r; drawRooms(); drawLines();
    if (S.room !== "all") {
      const first = Object.keys(S.h.photos).find(p => S.h.photos[p].room === S.room);
      if (first) showPhoto(first);
    }
  });
}

function drawForgotten() {
  const f = S.h.forgotten || {};
  const rooms = S.room === "all" ? Object.keys(f) : [S.room].filter(r => f[r]);
  const el = $("#forgot");
  if (!rooms.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<div class="side-label" style="margin-top:16px">Not in any photo, but easy to forget</div>` +
    rooms.map(r => `<div class="fg"><b>${esc(r)}</b> ${f[r].map(x => `<span>${esc(x)}</span>`).join("")}</div>`).join("") +
    `<div class="fine">From the room checklists claims advisers use. Add what you had; a photo isn't required for these.</div>`;
}

function drawLines(animate) {
  drawForgotten();
  const ol = $("#lines");
  ol.innerHTML = "";
  const tpl = $("#line-tpl");
  S.h.items.filter(l => S.room === "all" || l.room === S.room).forEach(l => {
    const li = tpl.content.firstElementChild.cloneNode(true);
    li.dataset.n = l.n;
    const s0 = l.sightings[0];
    $(".thumb", li).setAttribute("style", cropStyle(s0.photo, s0.boxf, 56, 44));
    $(".name", li).textContent = (l.quantity > 1 ? l.quantity + " × " : "") + l.name;
    const bits = [l.room];
    if (l.brand) bits.push(l.brand + (l.model ? " " + l.model : ""));
    if (l.sightings.length > 1) bits.push(`in ${l.sightings.length} photos`);
    if (l.earliest_photo) bits.push(`since ${l.earliest_photo.slice(0, 4)} or earlier`);
    $(".sub", li).textContent = bits.join(" · ");
    $(".rcv", li).textContent = l.rcv ? money(l.rcv) : "";
    $(".chip", li).outerHTML = chip(l.price);
    $(".row", li).onclick = () => toggleMore(li);
    $(".row", li).onmouseenter = () => { if (l.sightings.some(s => s.photo === S.photo)) markBox(l.n, true); };
    $(".row", li).onmouseleave = () => markBox(l.n, false);
    if (animate) { li.classList.add("new"); li.style.animationDelay = Math.min(ol.children.length * 25, 1200) + "ms"; }
    ol.appendChild(li);
  });
}

function toggleMore(li, force) {
  const more = $(".more", li);
  const open = force ?? more.hidden;
  more.hidden = !open;
  if (!open) return;
  const l = S.h.items.find(x => String(x.n) === li.dataset.n);
  const p = l.price || {};
  const src = (p.sources || []).map(s => `<div class="src"><b>${money2(s.price)}</b>${s.set_of > 1 ? ` (${money2(s.listed)} for ${s.set_of})` : ""}
      at <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.site)}</a><q>“${esc(s.quote)}”</q></div>`).join("");
  const aside = (p.set_aside || []).map(s => `<div class="src">set aside: ${money2(s.price)} at ${esc(s.site)}</div>`).join("");
  const rej = (p.rejected || []).slice(0, 4).map(r => `<div class="src">not used: ${r.price ? money2(r.price) : ""} ${esc(r.why)}</div>`).join("");
  more.innerHTML = `
    <h4>Seen in</h4>
    <div class="sights">${l.sightings.map(s => `<span data-p="${s.photo}" style="${cropStyle(s.photo, s.boxf, 92, 70)}"><i>${esc((S.h.photos[s.photo] || {}).taken || s.photo)}</i></span>`).join("")}</div>
    <h4>Price today, new, like kind and quality</h4>
    ${l.unit_rcv ? `<div>${money2(l.unit_rcv)} each${p.status === "priced" ? ", the median of " + p.sources.length + " stores" : p.status === "one source" ? ", one store only: worth a second look" : ""}. ${esc(p.note || "")}</div>` :
      `<div>${esc(p.why || "Still looking.")} You can add a price from a receipt or a store page by hand.</div>`}
    ${src}${aside}${rej}
    <div style="font-size:12px;color:var(--ink-3);margin-top:4px">Searched: “${esc(p.query || "")}”</div>
    ${l.unit_rcv ? `<h4>Actual cash value</h4><div class="maths">${money2(l.rcv)} − ${l.dep_pct}% = ${money2(l.acv)} · ${esc(l.dep_why || "")}</div>` : ""}`;
  more.querySelectorAll(".sights span").forEach(s => s.onclick = () => showPhoto(s.dataset.p, l.n));
}

function drawAlso() {
  const h = S.h;
  $("#merged").innerHTML = (h.merges || []).map(m => `<div class="it"><b>${m.merged ? "One thing" : "Kept apart"}:</b>
      ${esc(m.a_name)} / ${esc(m.b_name)}<br><small>${esc(m.why)} (${Math.round(m.confidence * 100)}% sure)</small></div>`).join("") || "<div class='it'>Nothing seen twice.</div>";
  $("#building").innerHTML = (h.building || []).map(b => `<div class="it"><b>${esc(b.name)}</b> · ${esc(b.photo)}<br><small>${esc(b.why)}</small></div>`).join("") || "<div class='it'>None.</div>";
  $("#dropped").innerHTML = (h.dropped || []).map(b => `<div class="it"><b>${esc(b.name)}</b><br><small>${esc(b.why)}</small></div>`).join("") || "<div class='it'>None.</div>";
}

function drawClock() {
  $("#clock").innerHTML = `
    <h3>If this was a California disaster: your clock and your options</h3>
    <div>Since January 2026, after a declared state of emergency and a total loss of a furnished primary home, the
      insurer must offer at least <b>60% of your contents limit (up to $350,000) without an itemized list</b>, and can't
      require a detailed inventory for at least 100 days. A list like this one is how you claim the rest.</div>
    <div style="margin-top:10px">Your policy's contents (personal property) limit:
      <input id="limit" inputmode="numeric" value="${localStorage.getItem("rp.limit") || "150000"}"></div>
    <div class="grid" id="clock-grid"></div>
    <div class="fine">Cal. Ins. Code §10103.7 (SB 495) and §2061: an insurer can't insist on its own form if yours has
      the same information, and must accept grouped lines like "30 books". Not legal advice; your policy decides.</div>`;
  const upd = () => {
    const lim = Number(String($("#limit").value).replace(/[^\d.]/g, "")) || 0;
    try { localStorage.setItem("rp.limit", lim); } catch (e) {}
    const auto = Math.min(lim * 0.6, 350000), listed = S.h.totals.rcv;
    $("#clock-grid").innerHTML = `
      <div><b>${money(auto)}</b><span>offered with no list (60% of the limit)</span></div>
      <div><b>${money(Math.min(listed, lim))}</b><span>this list so far, at replacement cost (${S.h.totals.needs_price} lines still need a price)</span></div>
      <div><b>${money(Math.max(0, Math.min(listed, lim) - auto))}</b><span>more than the no-list offer, if the insurer accepts it</span></div>`;
  };
  $("#limit").oninput = upd; upd();
}

function drawExport(which) {
  $("#export").innerHTML = `
    <a class="btn primary" href="/api/export/${which}.csv?fmt=xact">Download for State Farm (XactContents)</a>
    <a class="btn ghost" href="/api/export/${which}.csv?fmt=fema">FEMA contents worksheet</a>
    <span class="note">Columns copied from the insurers' own worksheets. Each line keeps its store link.</span>`;
}

async function showHousehold(h, base, who) {
  S.h = h; S.base = base;
  await loadSizes(Object.keys(h.photos));
  $("#app").hidden = false;
  $("#who").innerHTML = who;
  drawTotals(true); drawRoll(); drawRooms(); drawLines(true); drawAlso(); drawClock();
  showPhoto(Object.keys(h.photos)[0]);
}

$("#show-sample").onclick = async () => {
  $("#show-sample").disabled = true;
  const h = await (await fetch("/api/demo")).json();
  await showHousehold(h, "/photos/demo",
    `<b>The Reyes family's list</b><span>A made-up family. Their home burned on ${new Date(h.loss_date + "T12:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}; these are ${Object.keys(h.photos).length} photos from their phones. Recorded on live Nemotron: ${h.cost.calls} model calls, $${h.cost.usd.toFixed(2)}.</span>`);
  drawExport("demo");
  $("#app").scrollIntoView({ behavior: "smooth" });
  $("#show-sample").disabled = false;
};

// live run on the visitor's own photos
$("#files").onchange = async e => {
  const files = [...e.target.files].slice(0, 8);
  if (!files.length) return;
  $("#app").hidden = false;
  $("#who").innerHTML = `<b>Your photos</b><span>Reading ${files.length} photo(s) on live Nemotron…</span>`;
  $("#totals").innerHTML = ""; $("#lines").innerHTML = ""; $("#roll").innerHTML = ""; $("#rooms").innerHTML = "";
  $("#export").innerHTML = ""; $("#boxes").innerHTML = ""; $("#big").removeAttribute("src");
  $("#lines").insertAdjacentHTML("beforebegin", `<div class="live" id="live">Uploading…<div class="bar2"><i></i></div></div>`);
  $("#app").scrollIntoView({ behavior: "smooth" });
  const fd = new FormData();
  files.forEach(f => fd.append("photos", f));
  let r;
  try { r = await fetch("/api/inventory", { method: "POST", body: fd }); } catch (err) { return liveError("The upload failed."); }
  const j = await r.json();
  if (!r.ok) return liveError(j.error || j.detail || "Couldn't start.");
  poll(j.job, files.length);
};

function liveError(msg) { const l = $("#live"); if (l) l.innerHTML = `<span class="err">${esc(msg)}</span>`; }

async function poll(job, n) {
  const r = await fetch(`/api/inventory/${job}`);
  const j = await r.json();
  const live = $("#live");
  if (j.stage === "error") return liveError(j.error);
  if (j.stage === "done") {
    live && live.remove();
    await showHousehold(j.result, `/photos/${job}`, `<b>Your list</b><span>${Object.keys(j.result.photos).length} photos · ${j.result.cost.calls} model calls · $${j.result.cost.usd.toFixed(3)}. Nothing here is saved to an account; keep the download.</span>`);
    drawExport(job);
    return;
  }
  const read = Object.keys(j.photos || {}).length, priced = Object.keys(j.prices || {}).length, total = (j.items || []).length;
  const pct = j.stage === "pricing" || j.stage === "priced" ? 40 + 60 * priced / Math.max(1, total) : 40 * read / n;
  live.innerHTML = (j.stage === "priced" || j.stage === "pricing" ? `Found ${total} things. Pricing each at real stores: ${priced} of ${total}…` :
    j.stage === "merging" ? "Checking which things appear in more than one photo…" : `Reading photos: ${read} of ${n}…`) +
    `<div class="bar2"><i style="width:${pct}%"></i></div>`;
  setTimeout(() => poll(job, n), 1500);
}

// the hero: the birthday photo, with what was found appearing on it one by one
(async () => {
  try {
    const h = await (await fetch("/api/demo")).json();
    const hits = [];
    h.items.forEach(l => l.sightings.forEach(s => { if (s.photo === "living" && s.boxf) hits.push({ l, s }); }));
    hits.sort((a, b) => (b.l.rcv || 0) - (a.l.rcv || 0));
    const hb = $(".hb");
    hb.innerHTML = hits.slice(0, 9).map(({ l, s }) => {
      const [x0, y0, x1, y1] = s.boxf;
      return `<div class="box" style="left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%">
        <span class="tag">${esc(l.name)}${l.rcv ? " · " + money(l.rcv) : ""}</span></div>`;
    }).join("");
    const bs = [...hb.children];
    let i = 0;
    const next = () => {
      bs.forEach(b => b.classList.remove("last"));
      const b = bs[i % bs.length];
      b.classList.add("on", "last");
      i++;
      setTimeout(next, i < bs.length ? 700 : 1600);
    };
    setTimeout(next, 500);
  } catch (e) {}
})();
