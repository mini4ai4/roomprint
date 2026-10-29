// Small text helpers for what the page shows. Kept apart from app.js so they can be tested without a browser.
(function (root) {
  // "Nintendo" + "Nintendo Switch" -> "Nintendo Switch", not "Nintendo Nintendo Switch"
  function brandModel(brand, model) {
    brand = String(brand || "").trim(); model = String(model || "").trim();
    if (!brand) return model;
    if (!model) return brand;
    const b = brand.toLowerCase(), m = model.toLowerCase();
    if (m === b || m.startsWith(b + " ")) return model;
    if (b.endsWith(" " + m) || b === m) return brand;
    return brand + " " + model;
  }

  // 1 photo, 2 photos
  function plural(n, word, many) {
    return `${n} ${n === 1 ? word : (many || word + "s")}`;
  }

  // what a person calls a photo: its room and date, never its file id ("living_xmas")
  function photoLabel(photos, pid) {
    const ph = (photos || {})[pid];
    if (!ph) return "another photo";
    const room = ph.room ? ph.room[0].toUpperCase() + ph.room.slice(1) : "Photo";
    return ph.taken ? `${room} photo, ${ph.taken}` : `${room} photo`;
  }

  // "only second-hand listings found" -> "Only second-hand listings found." so the next sentence doesn't run on
  function sentence(t) {
    t = String(t || "").trim();
    if (!t) return "";
    t = t[0].toUpperCase() + t.slice(1);
    return /[.!?]$/.test(t) ? t : t + ".";
  }

  // what kind of work an unpriced line leaves for the family, from the reason the pricing step gave
  function turnKind(p) {
    const why = String((p || {}).why || "").toLowerCase();
    if ((p || {}).status === "check" || why.includes("disagree")) return "shops disagree: pick one";
    if (why.includes("titles")) return "books: list the titles";
    if (why.includes("like-for-like")) return "only a different set or size found";
    if (why.includes("searched yet")) return "not searched yet";
    return "no shop price found";
  }

  // a shop search for the line, so the family can start from the same words the app searched with
  function shopSearch(l) {
    const q = String(((l.price || {}).query) || l.name || "").replace(/\s+price$/i, "");
    return "https://www.google.com/search?tbm=shop&q=" + encodeURIComponent(q);
  }

  // "Your turn": every line still without a price, with the reason in a sentence, and how many of each kind
  function yourTurn(items) {
    const lines = (items || []).filter(l => !l.rcv).map(l => ({
      n: l.n, name: l.name, room: l.room, quantity: l.quantity || 1, kind: turnKind(l.price),
      why: sentence((l.price || {}).why || "no shop price found"), search: shopSearch(l) }));
    const c = {};
    lines.forEach(t => c[t.kind] = (c[t.kind] || 0) + 1);
    const oneStore = (items || []).filter(l => l.rcv && (l.price || {}).status === "one source").length;
    return { lines, kinds: Object.entries(c).sort((a, b) => b[1] - a[1]), oneStore };
  }

  const api = { brandModel, plural, photoLabel, sentence, turnKind, shopSearch, yourTurn };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else Object.assign(root, api);
})(this);
