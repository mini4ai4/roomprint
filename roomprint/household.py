"""From a pile of old photos to a priced contents list: read, merge, price, depreciate, total.

Everything a person would want to check is kept on the item: the photos it was seen in (with boxes), the
earliest photo date, every price source with its words, what was set aside and why.
"""
from __future__ import annotations

import concurrent.futures as cf
from datetime import date

from PIL import Image

from . import dedupe, forgotten, prices, rules, vision
from .llm import OverBudget, calls

ROOMS = {"family room": "living room", "lounge": "living room", "den": "living room", "master bedroom": "bedroom",
         "primary bedroom": "bedroom", "child's room": "kid's room", "kids room": "kid's room", "nursery": "kid's room",
         "children's room": "kid's room", "home office": "office", "study": "office", "dining area": "dining room",
         "patio": "yard", "backyard": "yard", "porch": "yard", "laundry": "laundry room"}


def room_name(r: str) -> str:
    r = (r or "other").strip().lower()
    return ROOMS.get(r, r)


def read_all(raws: dict[str, bytes], workers: int = 4, on_done=None) -> tuple[dict, dict, dict]:
    """photo_id → bytes. Returns (results, images, taken_dates). A photo that fails is reported, not fatal."""
    images, taken, results = {}, {}, {}
    for pid, raw in raws.items():
        images[pid], taken[pid] = vision.load(raw)

    def one(pid):
        try:
            r = vision.read_photo(images[pid], pid)
            r["room"] = room_name(r["room"])
            r["taken"] = taken[pid]
            return pid, r
        except OverBudget:
            raise
        except Exception as e:  # one unreadable photo shouldn't sink the inventory
            return pid, {"room": "other", "items": [], "dropped": [], "building": [], "taken": taken[pid],
                         "error": f"couldn't read this photo ({type(e).__name__})"}
    with cf.ThreadPoolExecutor(workers) as ex:
        for pid, r in ex.map(one, list(raws)):
            results[pid] = r
            if on_done:
                on_done(pid, r)
    return results, images, taken


def age_years(earliest: str | None, loss: date) -> float | None:
    if not earliest:
        return None
    d = date.fromisoformat(earliest)
    return round(max((loss - d).days, 0) / 365.25, 1)


def build(raws: dict[str, bytes], loss_date: date | None = None, price_workers: int = 6, progress=None) -> dict:
    """progress(stage, done, total, detail) is called as work finishes, for a live view."""
    say = progress or (lambda *a: None)
    loss = loss_date or date.today()
    start = len(calls())
    say("reading", 0, len(raws), "")
    photos, images, taken = read_all(raws, on_done=lambda pid, r: say("read", 0, len(raws), {"photo": pid, **r}))
    say("merging", 0, 0, "")
    items, decisions = dedupe.merge(photos, images)
    say("pricing", 0, len(items), [{"id": i["id"], "name": i["name"], "room": i["room"]} for i in items])

    def priced(it):
        try:
            return prices.price(it)
        except OverBudget:
            raise
        except Exception as e:
            return {"status": "needs a price", "price": None, "sources": [], "rejected": [],
                    "why": f"price lookup failed ({type(e).__name__})", "query": prices.query_for(it)}
    found: list = [None] * len(items)
    with cf.ThreadPoolExecutor(price_workers) as ex:
        futs = {ex.submit(priced, it): k for k, it in enumerate(items)}
        for n, f in enumerate(cf.as_completed(futs), 1):
            k = futs[f]
            found[k] = f.result()
            say("priced", n, len(items), {"id": items[k]["id"], "price": found[k].get("price"),
                                          "status": found[k].get("status")})

    lines = []
    for n, (it, p) in enumerate(zip(items, found), 1):
        dates = sorted(d for d in (taken.get(s["photo"]) for s in it["sightings"]) if d)
        earliest = dates[0] if dates else None
        age = age_years(earliest, loss)
        unit = p.get("price")
        line = {"n": n, **it, "earliest_photo": earliest, "age_years": age, "condition": "Average",
                "price": p, "unit_rcv": unit}
        if unit:
            total = unit * it["quantity"]
            d = rules.acv(total, it["category"], age, "Average", it["name"])
            line.update(rcv=round(total, 2), **{"acv": d["acv"], "dep_pct": d["dep_pct"], "life": d["life"],
                                                 "dep_why": d["why"]})
        lines.append(line)

    priced_lines = [l for l in lines if l.get("rcv")]
    log = calls(start)
    return {
        "loss_date": loss.isoformat(),
        "photos": {pid: {k: v for k, v in r.items() if k != "items"} | {"n_items": len(r["items"])}
                   for pid, r in photos.items()},
        "items": lines,
        "merges": decisions,
        "forgotten": forgotten.suggestions(lines),
        "building": [b for r in photos.values() for b in r["building"]],
        "dropped": [d for r in photos.values() for d in r["dropped"]],
        "totals": {"items": len(lines), "priced": len(priced_lines),
                   "needs_price": len(lines) - len(priced_lines),
                   "rcv": round(sum(l["rcv"] for l in priced_lines), 2),
                   "acv": round(sum(l["acv"] for l in priced_lines), 2)},
        "cost": {"calls": len(log), "usd": round(sum(c["usd"] for c in log), 4),
                 "by_model": {s: sum(1 for c in log if c["size"] == s) for s in ("nano", "super", "ultra", "vision")}},
    }
