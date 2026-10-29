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

from . import rules
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
LOT_OF_BOOKS = re.compile(r"(?i)\b(stack|pile|shelf|shelves|row|collection|assorted|set|group)\b.*\bbooks?\b|\bbooks?\b.*\b(stack|pile)\b")
BOOK_HEADS = {"book", "books", "cookbook", "cookbooks", "novel", "novels", "paperback", "paperbacks", "hardcover",
              "hardcovers", "textbook", "textbooks", "comic", "comics"}


def books_without_titles(item: dict) -> bool:
    """Books whose titles nobody knows yet. A shelf priced as "12 x one cheap book" is neither like kind nor what
    the family owned, so these lines aren't priced at all: the family lists the titles they remember."""
    if item.get("model"):
        return False
    name = item["name"]
    return bool(LOT_OF_BOOKS.search(name)) or rules.head_noun(name) in BOOK_HEADS


# Like for like: a set is priced as the whole set, a single thing as one thing.
COLOURS = r"(black|white|gray|grey|red|blue|green|brown|silver|gold|pink|navy|cream|beige|yellow|orange|purple)"
SET_SIGNAL = re.compile(r"(?i)\b(sets?|combo|bundle|kit|\d+[- ]?(piece|pc|pcs))\b|&|\band\b|\bwith\b")
SET_OF_N = re.compile(r"(?i)\b(?:set|pack|box|case) of (\d+)\b|\b(\d+)[- ]?(?:pack|pk|count|ct)\b")
WHERE = re.compile(r"(?i)\s+\b(on|in|under|at|by|near|from|with|filled|full|holding|containing)\b\s.*$")


def set_parts(name: str, quantity: int = 1) -> list[str] | None:
    """None if the line is one thing (or a count of pieces: "30 ornaments and decorations" is priced per piece).
    For one set, the things it must include: "white child's desk and chair set" -> ["desk", "chair"];
    "comforter set" -> []. What follows "with" describes the thing: "bookcase filled with books" is a bookcase."""
    if (quantity or 1) > 1:
        return None
    n = WHERE.sub("", re.sub(r"\([^)]*\)", " ", name.lower()))
    n = re.sub(rf"\b{COLOURS} and {COLOURS}\b", "colour", n)
    sides = re.split(r"\s+(?:and|&)\s+", n)
    if len(sides) < 2:
        return [] if re.search(r"\bset\b", n) else None
    parts = []
    for side in sides:
        side = re.sub(r"\s+(set|sets|combo|bundle|kit)\s*$", "", side.strip())
        w = re.findall(r"[a-z]+", side)
        if w:
            parts.append(w[-1])
    return parts


def _stem(w: str) -> str:
    return re.sub(r"(es|s)$", "", w) if len(w) > 3 and not w.endswith("ss") else w


def about_price(text: str, price: float | None) -> str:
    """The words that describe one price in a sentence that may list several products: from the amount before it
    (or the start) to a little after it. "Engines 3Pk $13.50 · Launch Set $33.50": $33.50 is the launch set."""
    if price is None:
        return text
    spots = list(DOLLARS.finditer(text))
    for k, m in enumerate(spots):
        v = float(m.group(1).replace(",", "")) + (float(m.group(2)) / 100 if m.group(2) else 0)
        if abs(v - price) < 0.01:
            start = spots[k - 1].end() if k else 0
            return text[start: m.end() + 25]
    return text


def like_for_like(item: dict, text: str, set_of: int = 1, price: float | None = None) -> str | None:
    """Why a shop sentence isn't the same quantity or set as the line, or None if it is. `price` is the amount
    picked from the sentence (the listed price, before any unit split)."""
    text = about_price(text, price)
    parts = set_parts(item["name"], item.get("quantity", 1))
    if parts is not None:
        if not SET_SIGNAL.search(text):
            what = " and ".join(parts) if parts else "set"
            return f"a price for one piece, not the whole {what} set" if parts else "a price for one piece, not the set"
        missing = [w for w in parts if not re.search(rf"(?i)\b{re.escape(_stem(w))}", text)]
        if missing:
            return f"the shop's set doesn't include the {' and '.join(missing)}"
        return None
    m = SET_OF_N.search(text)
    k = int(m.group(1) or m.group(2)) if m else 1
    if k > 1 and set_of == 1:
        return f"a price for a set of {k}, but the line is one item"
    return None


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

BOOKS_WHY = "books aren't priced by the shelf: list the titles you remember and each gets its own price"

RULE_EXACT = ("The family's item is this exact model. Pick prices for this model, or its current successor if the exact "
              "one is no longer sold (say so in the note).")
RULE_GENERIC = ("The brand isn't known, so any product of the same type, size and grade is a fair replacement. Brand, "
                "color and exact style don't matter. Prefer mainstream mid-range prices.")


def check_pick(p: dict, cands: dict[int, dict], item: dict | None = None) -> tuple[dict | None, str | None]:
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
    if item is not None:
        why = like_for_like(item, text, n, price)
        if why:
            return None, why
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
    if books_without_titles(item):
        out["why"] = BOOKS_WHY
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
        ok, why = check_pick(p, by_n, item)
        if ok:
            good.append(ok)
        else:
            out["rejected"].append({"n": p.get("n"), "price": p.get("price"), "why": why,
                                    **({"like_for_like": True} if why and why.startswith(LFL_REASONS) else {})})
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
        out["why"] = unpriced_why(out["rejected"])
    return out


LFL_REASONS = ("a price for one piece", "a price for a set of", "the shop's set doesn't")


def unpriced_why(rejected: list[dict]) -> str:
    """The reason a line has no price, naming a like-for-like mismatch when that's what stopped it."""
    lfl = [r["why"] for r in rejected if r.get("like_for_like")]
    if lfl:
        return f"no like-for-like shop price ({lfl[0]}); add the price of the same thing by hand"
    return "no new-item price survived the checks"
