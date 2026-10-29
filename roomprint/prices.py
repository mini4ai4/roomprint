"""Today's price to replace an item with one of like kind and quality, found with Tavily, checked by code.

How a price is earned:
1. Tavily Search (advanced, a few chunks per page) for the item as a buyer would type it.
2. Code cuts the pages into sentences and keeps only those that name the item (enough of its words) and
   contain a dollar amount. Those are the candidates; the model never sees anything else.
3. Nemotron Super picks the candidates that are the price of a NEW item of the same kind and quality,
   quoting each one.
4. Code checks every pick: the quoted sentence is one of the candidates, the amount is in it, and it isn't a
   used, refurbished, "was", per-month or accessory price. Two or more good sources → the median. One → kept but
   flagged. None → "needs a price". Nothing is ever guessed.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import urllib.request

from .llm import nemotron

TAVILY = "https://api.tavily.com/search"
DOLLARS = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")
STOP = {"a", "an", "the", "with", "and", "of", "for", "in", "on", "to", "set", "large", "small", "new"}
# Anywhere in the sentence: it's about a second-hand item.
NOT_NEW = re.compile(r"(?i)\b(used|refurb\w*|restored|renewed|pre-?owned|open[- ]box|rental|second[- ]hand)\b")
# Right around the amount: not the price of the item itself.
BAD_CONTEXT = re.compile(r"(?i)(/mo\b|per month|a month|monthly|financ\w*|save \$|\boff\b|coupon|rebate|shipping|"
                         r"warranty|replacement part|filter|battery pack|\bremote\b|cover only|case for)")
WAS = re.compile(r"(?i)\b(was|reg\.?|regular|list|msrp|compare at)\s*:?\s*(us\s*)?$")


def query_for(item: dict) -> str:
    if item.get("shop_as"):
        q = item["shop_as"]
    else:
        q = " ".join(p for p in [item.get("brand") or "", item.get("model") or "", item["name"]] if p)
    q = re.sub(r"\s+", " ", q).strip()
    return q + " price"


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1}


CACHE = os.path.join(os.environ.get("ROOMPRINT_DATA", os.path.join(os.path.dirname(__file__), "..", "data")),
                     "tavily_cache.json")
_cache: dict | None = None
CREDITS = 0  # Tavily credits spent by this process (cache hits are free)


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.load(open(CACHE))
        except Exception:
            _cache = {}
    return _cache


def tavily(query: str, depth: str = "basic") -> list[dict]:
    """Tavily Search, US results. Answers are cached by query for a week: prices don't move by the hour, and the
    same "65 inch 4K TV" shows up in many homes."""
    import time
    c = _load_cache()
    key = f"{depth}|{query.lower()}"
    hit = c.get(key)
    if hit and time.time() - hit["t"] < 7 * 86400:
        return hit["results"]
    global CREDITS
    CREDITS += 2 if depth == "advanced" else 1
    body = {"api_key": os.environ.get("ROOMPRINT_TAVILY_API_KEY") or os.environ["TAVILY_API_KEY"], "query": query, "search_depth": depth, "max_results": 8,
            "country": "united states"}
    if depth == "advanced":
        body["chunks_per_source"] = 3
    req = urllib.request.Request(TAVILY, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    results = json.load(urllib.request.urlopen(req, timeout=45)).get("results", [])
    c[key] = {"t": time.time(), "results": results}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        tmp = CACHE + ".tmp"
        json.dump(c, open(tmp, "w"))
        os.replace(tmp, CACHE)
    except OSError:
        pass
    return results


def amounts(s: str) -> list[float]:
    out = []
    for whole, cents in DOLLARS.findall(s):
        v = float(whole.replace(",", "")) + (float(cents) / 100 if cents else 0)
        if v > 0:
            out.append(v)
    return out


# Places where a price is someone's opinion or a second-hand sale, not a store's price for a new item.
NOT_A_STORE = re.compile(r"(reddit|facebook|youtube|tiktok|instagram|pinterest|quora|craigslist|offerup|mercari|poshmark|"
                         r"pricecharting|camelcamelcamel|slickdeals|ebay)\.")
# News, reviews, magazines, blogs and publishing services: they mention prices, they don't sell the item. An
# adjuster asks "where can I buy it for that?", so only shops count.
EDITORIAL = re.compile(r"(theverge|runnersworld|cnet|wired|engadget|techradar|tomsguide|rtings|pcmag|zdnet|gizmodo|"
                       r"nytimes|wirecutter|consumerreports|bestreviews|goodhousekeeping|foodandwine|bonappetit|"
                       r"apartmenttherapy|thespruce|bobvila|forbes|businessinsider|cnn|usatoday|buzzfeed|wikipedia|"
                       r"digitaltrends|smartprix|pricespy|medium|substack|blogspot|wordpress|tumblr)\.|"
                       r"(blog|news|review|magazine|publishing|writing|writer|reading|printing|guide|digest)")
LOT_OF_BOOKS = re.compile(r"(?i)\b(stack|pile|shelf|shelves|row|collection|assorted|set)\b.*\bbooks?\b|\bbooks?\b.*\b(stack|pile)\b")


def is_store(host: str) -> bool:
    return not NOT_A_STORE.search(host + ".") and not EDITORIAL.search(host + ".")


def candidates(item: dict, results: list[dict]) -> list[dict]:
    """Sentences that name the item and hold a price. Numbered, so the model can only point at them."""
    key = words(" ".join(filter(None, [item.get("brand"), item.get("model"), item["name"], item.get("shop_as")])))
    need = 1 if len(key) <= 2 else 2
    out = []
    for r in results:
        host = r["url"].split("/")[2].replace("www.", "")
        if not is_store(host):
            continue
        for s in re.split(r"(?<=[.!?])\s+|\n+", r.get("content") or ""):
            s = s.strip(" #*-·|")
            if len(s) < 12 or not amounts(s):
                continue
            if len(key & words(s)) >= need:
                out.append({"n": len(out) + 1, "url": r["url"], "site": host, "text": s[:300]})
    return out[:24]


ASK = """You are pricing one household item for an insurance claim: what it costs today to buy a NEW one of like kind and
quality.

Item: {item}
{rule}

Numbered sentences from shop pages (only these exist):
{cands}

Pick the sentences that state a price for a NEW product that would be a fair like-kind replacement.
Skip used, refurbished, open-box and "was" prices, monthly payments, "save $X" amounts, bundles, accessories and parts,
and anything clearly bigger, smaller, cheaper-grade or luxury-grade than the item.
The claim lists {qty} of this item. If a sentence prices a set or pack (e.g. "set of 4 chairs"), give the set price and
set_of = how many units it holds; otherwise set_of = 1.
Reply JSON only: {{"picks": [{{"n": <sentence number>, "price": <number>, "set_of": <integer>, "why": "<few words>"}}],
"note": "<one short line: what you priced it as>"}}"""

RULE_EXACT = ("The family's item is this exact model. Pick prices for this model, or its current successor if the exact "
              "one is no longer sold (say so in the note).")
RULE_GENERIC = ("The brand isn't known, so any product of the same type, size and grade is a fair replacement. Brand, "
                "color and exact style don't matter. Prefer mainstream mid-range prices.")


def check_pick(p: dict, cands: dict[int, dict]) -> tuple[dict | None, str | None]:
    c = cands.get(int(p.get("n") or 0))
    if not c:
        return None, "points at a sentence that wasn't offered"
    try:
        price = float(p.get("price"))
    except (TypeError, ValueError):
        return None, "no number"
    text = c["text"]
    spots = [m for m in DOLLARS.finditer(text)
             if abs(float(m.group(1).replace(",", "")) + (float(m.group(2)) / 100 if m.group(2) else 0) - price) < 0.01]
    if not spots:
        return None, f"${price:g} isn't in sentence {c['n']}"
    m = spots[0]
    if NOT_NEW.search(text):
        return None, "a used or refurbished item"
    if WAS.search(text[max(0, m.start() - 16): m.start()]):
        return None, "an old 'was' price, not today's"
    context = text[max(0, m.start() - 30): m.end() + 25]
    if BAD_CONTEXT.search(context):
        return None, "a monthly, discount or accessory amount"
    if re.search(r"(?i)\b(starting|starts) at\b|\bfrom\s*$", text[max(0, m.start() - 20): m.start()]):
        return None, "a 'starting at' price, the cheapest of a range"
    try:
        n = max(1, min(int(p.get("set_of") or 1), 48))
    except (TypeError, ValueError):
        n = 1
    if n > 1 and not re.search(rf"(?i)\b({n}|{['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve'][n] if n <= 12 else n})\b", text):
        return None, f"says a set of {n}, but the sentence doesn't"
    return {"price": round(price / n, 2), "listed": price, "set_of": n, "url": c["url"], "site": c["site"],
            "quote": text[max(0, m.start() - 90): m.end() + 30].strip()}, None


def price(item: dict, results: list[dict] | None = None) -> dict:
    """Basic search first (1 Tavily credit). If it gives fewer than 6 priced sentences, add an advanced search
    (2 credits), which returns more of each page, and price from both together."""
    if results is not None:
        return _price(item, results, "given")
    q = query_for(item)
    results = tavily(q, "basic")
    depth = "basic"
    if len(candidates(item, results)) < 6:
        seen = {r["url"] for r in results}
        results = results + [r for r in tavily(q, "advanced") if r["url"] not in seen]
        depth = "basic+advanced"
    return _price(item, results, depth)


def _price(item: dict, results: list[dict] | None, depth: str) -> dict:
    q = query_for(item)
    if results is None:
        results = tavily(q, "basic")
    cands = candidates(item, results)
    out = {"query": q, "depth": depth, "candidates": len(cands), "sources": [], "rejected": [], "status": "needs a price",
           "price": None, "note": ""}
    if LOT_OF_BOOKS.search(item["name"]) and not item.get("model"):
        out["why"] = "a shelf of books is priced title by title: list the titles you remember"
        return out
    if not cands:
        out["why"] = "no page named this item next to a price"
        return out
    desc = ", ".join(filter(None, [item.get("brand"), item.get("model"), item["name"], item.get("detail")]))
    lines = "\n".join(f"{c['n']}. [{c['site']}] {c['text']}" for c in cands)
    rule = RULE_EXACT if (item.get("brand") and item.get("model")) else RULE_GENERIC
    a = nemotron("super", ASK.format(item=desc, rule=rule, cands=lines, qty=item.get("quantity", 1)), max_tokens=900, purpose=f"price {item['name']}")
    by_n = {c["n"]: c for c in cands}
    good = []
    for p in (a.json().get("picks") or []):
        ok, why = check_pick(p, by_n)
        if ok:
            good.append(ok)
        else:
            out["rejected"].append({"n": p.get("n"), "price": p.get("price"), "why": why})
    # one price per site: a page listing three bundles shouldn't outvote two other stores
    per_site: dict[str, dict] = {}
    for g in good:
        per_site.setdefault(g["site"], g)
    out["sources"] = list(per_site.values())
    out["note"] = a.json().get("note") or ""
    vals = sorted(s["price"] for s in out["sources"])
    if len(vals) >= 3:
        # sources that disagree wildly are different products; keep the ones near the middle
        mid = statistics.median(vals)
        keep = [s for s in out["sources"] if mid / 2 <= s["price"] <= mid * 2]
        out["set_aside"] = [s for s in out["sources"] if s not in keep]
        out["sources"] = keep
        vals = sorted(s["price"] for s in keep)
    if len(vals) == 2 and vals[1] > vals[0] * 2.5:
        out["sources"] = []
        out["set_aside"] = sorted(per_site.values(), key=lambda x: x["price"])
        out["why"] = f"two sources disagree too much (${vals[0]:,.2f} vs ${vals[1]:,.2f}); pick one by hand"
        vals = []
        out["status"] = "check"
        return out
    if len(vals) >= 2:
        out.update(price=round(statistics.median(vals), 2), status="priced")
    elif len(vals) == 1:
        out.update(price=vals[0], status="one source")
    else:
        out["why"] = "no new-item price survived the checks"
    return out
