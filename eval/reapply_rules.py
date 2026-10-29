"""Re-apply today's rules to the sample home's finished run, without reading the photos again.

    python eval/reapply_rules.py            # writes demo/household.json, prints what changed

When a rule changes (what counts as property, which sites count as shops, which pairs are compared), the sample
home is brought up to date from the run it already has: the same photos, boxes and prices. Only lines the old
rules wrongly set aside are priced fresh (Tavily, then Nemotron Super), so the numbers move only where a rule did.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roomprint import dedupe, forgotten, prices, rules  # noqa: E402
from roomprint.household import age_years  # noqa: E402
from roomprint.llm import calls  # noqa: E402
from datetime import date  # noqa: E402

PATH = ROOT / "demo" / "household.json"


def restatus(p: dict, name: str, model: str | None) -> dict:
    """The same decisions as prices._price, on the sources a line already has."""
    p = dict(p)
    if prices.LOT_OF_BOOKS.search(name) and not model:
        return {**p, "sources": [], "status": "needs a price", "price": None,
                "why": "a shelf of books is priced title by title: list the titles you remember"}
    gone = [s for s in p.get("sources", []) if not prices.is_store(s["site"])]
    keep = [s for s in p.get("sources", []) if prices.is_store(s["site"])]
    if not gone:
        return p
    p["not_shops"] = gone
    p["sources"] = keep
    vals = sorted(s["price"] for s in keep)
    if len(vals) >= 2:
        p.update(price=round(statistics.median(vals), 2), status="priced")
    elif len(vals) == 1:
        p.update(price=vals[0], status="one source")
    else:
        p.update(price=None, status="needs a price", why="no shop page priced it (news, review and blog pages don't count)")
    return p


def main():
    h = json.loads(PATH.read_text())
    loss = date.fromisoformat(h["loss_date"])
    start = len(calls())
    before = {k: h["totals"][k] for k in ("items", "priced", "needs_price", "rcv", "acv")}
    changed = []

    # 1. lines the old filter set aside that are property after all
    still_dropped, back = [], []
    for d in h["dropped"]:
        if rules.is_not_an_item(d["name"]):
            still_dropped.append(d)
        else:
            back.append(d)
    h["dropped"] = still_dropped
    for d in back:
        it = {k: v for k, v in d.items() if k != "why"}
        it.setdefault("quantity", 1)
        it["room"] = d.get("room") or h["photos"][d["photo"]]["room"]
        it["category"] = rules.category(it.get("category"))
        it["sightings"] = [{"photo": d["photo"], "id": d["id"], "box": d["box"], "boxf": d.get("boxf")}]
        it["price"] = prices.price(it)
        h["items"].append(it)
        changed.append(f"back on the claim: {it['name']} ({it['price']['status']})")

    # 2. prices: shops only, shelves of books by title
    for it in h["items"]:
        old = it.get("price") or {}
        new = restatus(old, it["name"], it.get("model"))
        if new.get("status") != old.get("status") or new.get("price") != old.get("price"):
            changed.append(f"repriced: {it['name']}: {old.get('status')} {old.get('price')} -> {new['status']} {new.get('price')}")
        it["price"] = new

    # 3. pairs that today's rules would never send to the model
    kept_decisions = []
    for m in h["merges"]:
        if dedupe.kind(m["a_name"]) != dedupe.kind(m["b_name"]):
            changed.append(f"not compared any more: {m['a_name']} / {m['b_name']}")
        else:
            kept_decisions.append(m)
    h["merges"] = kept_decisions

    # 4. lines, totals
    lines = []
    for n, it in enumerate(h["items"], 1):
        dates = sorted(x for x in (h["photos"][s["photo"]].get("taken") for s in it["sightings"]) if x)
        earliest = dates[0] if dates else None
        age = age_years(earliest, loss)
        unit = it["price"].get("price")
        line = {k: v for k, v in it.items() if k not in ("rcv", "acv", "dep_pct", "life", "dep_why")}
        line.update(n=n, earliest_photo=earliest, age_years=age, condition=it.get("condition", "Average"), unit_rcv=unit)
        if unit:
            total = unit * line["quantity"]
            d = rules.acv(total, line["category"], age, line["condition"], line["name"])
            line.update(rcv=round(total, 2), acv=d["acv"], dep_pct=d["dep_pct"], life=d["life"], dep_why=d["why"])
        lines.append(line)
    h["items"] = lines
    h["forgotten"] = forgotten.suggestions(lines)
    priced = [l for l in lines if l.get("rcv")]
    h["totals"] = {"items": len(lines), "priced": len(priced), "needs_price": len(lines) - len(priced),
                   "rcv": round(sum(l["rcv"] for l in priced), 2), "acv": round(sum(l["acv"] for l in priced), 2)}
    log = calls(start)
    h["cost"]["calls"] += len(log)
    h["cost"]["usd"] = round(h["cost"]["usd"] + sum(c["usd"] for c in log), 4)
    for c in log:
        h["cost"]["by_model"][c["size"]] = h["cost"]["by_model"].get(c["size"], 0) + 1
    PATH.write_text(json.dumps(h, default=str, indent=1))
    print("\n".join(changed))
    print("before", before)
    print("after ", h["totals"], "| new calls", len(log), "| Tavily credits", prices.CREDITS)


if __name__ == "__main__":
    main()
