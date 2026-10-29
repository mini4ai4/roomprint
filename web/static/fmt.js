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

  const api = { brandModel, plural, photoLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else Object.assign(root, api);
})(this);
