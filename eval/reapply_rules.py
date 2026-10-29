"""Re-apply today's rules to a finished run, without reading the photos or searching again.

    python eval/reapply_rules.py                                   # the sample home: demo/household.json
    python eval/reapply_rules.py data/uploads/realset13/household.json --out eval/results/real-photos-reapplied.json

When a rule changes (what counts as property, which sites count as shops, set vs single, books), a finished run
is brought up to date from what it already has: the same photos, boxes, model answers and searches. It makes no
paid calls: Tavily and Nemotron are switched off for the whole run, and the full shop sentences behind each kept
price are read back from the local search cache. A line that only now comes back onto the list (it was wrongly
set aside) is marked "needs a price" with that reason, not priced from a guess.
"""
import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roomprint import dedupe, forgotten, llm, prices, rules  # noqa: E402
from roomprint.household import age_years  # noqa: E402

PATH = ROOT / "demo" / "household.json"
FILTERED = ("a person, pet, food or decoration", "a present or decoration")  # the name rules, not a bad box


def no_paid_calls(*a, **k):
    raise RuntimeError("re-applying rules never calls Tavily or Nemotron")


def full_text(item: dict, src: dict) -> str:
    """The whole shop sentence a kept price came from, read from the search cache (no request is made). The saved
    quote is a window around the amount; the check needs the sentence."""
    c = prices._load_cache()
    q = (item.get("price") or {}).get("query") or prices.query_for(item)
    results = []
    for depth in ("basic", "advanced"):
        results += (c.get(f"{depth}|{q.lower()}") or {}).get("results", [])
    quote = (src.get("quote") or "").strip()
    for cand in prices.candidates(item, results):
        if cand["url"] == src["url"] and quote and quote in cand["text"]:
            return cand["text"]
    return quote


def restatus(it: dict) -> dict:
    """The same decisions as prices._price, on the sources a line already has."""
    p = dict(it.get("price") or {})
    if prices.books_without_titles(it):
        return {**p, "sources": [], "set_aside": [], "status": "needs a price", "price": None, "why": prices.BOOKS_WHY}
    if p.get("status") not in ("priced", "one source"):
        return p
    keep, gone, mismatch = [], [], []
    for s in p.get("sources", []):
        if not prices.is_store(s["site"]):
            gone.append(s)
            continue
        why = prices.like_for_like(it, full_text(it, s), int(s.get("set_of") or 1), s.get("listed", s["price"]))
        if why:
            mismatch.append({"n": None, "price": s.get("listed", s["price"]), "why": why, "like_for_like": True,
                             "site": s["site"], "quote": s.get("quote")})
        else:
            keep.append(s)
    if not gone and not mismatch:
        return p
    if gone:
        p["not_shops"] = gone
    p["rejected"] = (p.get("rejected") or []) + mismatch
    p["sources"] = keep
    vals = sorted(s["price"] for s in keep)
    if len(vals) >= 2:
        p.update(price=round(statistics.median(vals), 2), status="priced")
    elif len(vals) == 1:
        p.update(price=vals[0], status="one source")
    else:
        why = (prices.unpriced_why(mismatch) if mismatch
               else "no shop page priced it (news, review and blog pages don't count)")
        p.update(price=None, status="needs a price", why=why)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(PATH))
    ap.add_argument("--out", default=None, help="where to write (default: in place)")
    a = ap.parse_args()
    prices.tavily = no_paid_calls
    prices.nemotron = no_paid_calls
    llm.nemotron = no_paid_calls

    src = Path(a.path)
    h = json.loads(src.read_text())
    loss = date.fromisoformat(h["loss_date"])
    before = {k: h["totals"][k] for k in ("items", "priced", "needs_price", "rcv", "acv")}
    changed = []

    # 1. lines the name rules set aside that are property after all ("baking sheet with cookies" is a baking sheet)
    still_dropped, back = [], []
    for d in h.get("dropped", []):
        if str(d.get("why", "")).startswith(FILTERED) and not rules.is_not_an_item(d["name"]):
            back.append(d)
        else:
            still_dropped.append(d)
    h["dropped"] = still_dropped
    for d in back:
        it = {k: v for k, v in d.items() if k != "why"}
        name = rules.without_food(d["name"])
        if name != d["name"]:
            it["as_read"], it["name"] = d["name"], name
        it.setdefault("quantity", 1)
        it["room"] = d.get("room") or h["photos"][d["photo"]]["room"]
        it["category"] = rules.category(it.get("category"))
        it["sightings"] = [{"photo": d["photo"], "id": d["id"], "box": d["box"], "boxf": d.get("boxf")}]
        it["price"] = {"query": prices.query_for(it), "status": "needs a price", "price": None, "sources": [],
                       "rejected": [], "why": "put back on the list after the recorded run, so it hasn't been searched yet"}
        h["items"].append(it)
        changed.append(f"back on the claim: {d['name']} -> {it['name']}")

    # 2. prices: shops only, books by title, a set priced as the set and a single thing as one thing
    for it in h["items"]:
        old = it.get("price") or {}
        new = restatus(it)
        if new.get("status") != old.get("status") or new.get("price") != old.get("price"):
            changed.append(f"repriced: {it['name']}: {old.get('status')} {old.get('price')} -> {new['status']} "
                           f"{new.get('price')} ({new.get('why', '')})")
        it["price"] = new

    # 3. pairs that today's rules would never send to the model
    kept_decisions = []
    for m in h.get("merges", []):
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
        line = {k: v for k, v in it.items() if k not in ("rcv", "acv", "dep_pct", "life", "dep_why", "unit_rcv")}
        line.update(n=n, earliest_photo=earliest, age_years=age, condition=it.get("condition", "Average"), unit_rcv=unit)
        if unit:
            total = unit * line["quantity"]
            d = rules.acv(total, line["category"], age, line["condition"], line["name"])
            line.update(rcv=round(total, 2), acv=d["acv"], dep_pct=d["dep_pct"], life=d["life"], dep_why=d["why"])
        lines.append(line)
    h["items"] = lines

    # 5. each photo's own record agrees with the list: what was set aside there, how many lines it proves
    for pid, ph in h["photos"].items():
        ph["dropped"] = [d for d in h["dropped"] if d.get("photo") == pid]
        ph["n_items"] = sum(1 for l in lines for s in l["sightings"] if s["photo"] == pid)

    h["forgotten"] = forgotten.suggestions(lines)
    priced = [l for l in lines if l.get("rcv")]
    h["totals"] = {"items": len(lines), "priced": len(priced), "needs_price": len(lines) - len(priced),
                   "rcv": round(sum(l["rcv"] for l in priced), 2), "acv": round(sum(l["acv"] for l in priced), 2)}
    out = Path(a.out) if a.out else src
    out.write_text(json.dumps(h, default=str, indent=1))
    print("\n".join(changed))
    print("before", before)
    print("after ", h["totals"], "| paid calls: none")


if __name__ == "__main__":
    main()
