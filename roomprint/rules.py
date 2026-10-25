"""Plain rules, no model: what counts as contents, how long things last, what a category is.

Homeowners policies split a loss in two: the building (Coverage A, "dwelling") and the things inside it
(Coverage C, "personal property"). A contents inventory that lists the kitchen sink is wrong, and an adjuster
will strike it. Items attached to the house go to a separate list instead of the claim.
"""
from __future__ import annotations

import re

CATEGORIES = ["electronics", "appliances_small", "appliances_large", "furniture", "decor", "lighting",
              "books_media", "toys_games", "kitchenware", "clothing", "plants", "sports_outdoor",
              "tools", "musical", "jewelry", "linens", "other"]

# Part of the building, not contents. Matched on the item name.
DWELLING = [r"\b(kitchen|upper|lower|base|wall|bathroom|vanity) cabinet(s|ry)?\b", r"^cabinets?$", r"\bcabinets with\b",
            r"\bsink\b", r"\bcounter ?tops?\b", r"\bfaucet\b", r"\bflooring\b", r"\bwall[- ]to[- ]wall carpet",
            r"\bhardwood floor", r"\btile(d)? (floor|wall|backsplash)\b", r"\bbacksplash\b", r"\bbuilt[- ]in\b",
            r"\bceiling (fan|light)\b", r"^windows?\b", r"\bwindow (frame|pane|glass)\b",
            r"^(front |interior |closet |garage |sliding |patio )?doors?$", r"\bgarage door\b", r"\bfireplace\b",
            r"\bstair", r"\bwater heater\b", r"\bfurnace\b", r"\bhvac\b", r"\brecessed light", r"\bbathtub\b",
            r"\btoilet\b", r"\bshower\b(?!.*curtain)", r"\bwall oven\b", r"\brange hood\b",
            r"^(built-in )?dishwasher$", r"\bshelving\b.*\bopen\b|\bopen shelving\b", r"\bmounted shelves\b",
            r"\bwindow blinds?\b|\bblinds\b"]

# Never items: people, the moment, the room itself.
NOT_ITEMS = [r"\bperson\b", r"\bpeople\b", r"\bchild(ren)?\b", r"\bkid(s)?\b", r"\bbaby\b", r"\bman\b", r"\bwoman\b",
             r"\bballoon", r"\bbanner\b", r"\bstreamer", r"\bconfetti\b", r"\bcake\b", r"\bcookies?\b", r"\bfood\b",
             r"\bwrapped\b", r"\bpresents?\b", r"\bgifts?\b(?! card)", r"\bpet\b", r"\bdog\b", r"\bcat\b", r"\bshadow\b", r"\bsunlight\b", r"\breflection\b"]

# Useful life in years, from United Policyholders' published depreciation schedule
# (uphelp.org/wp-content/uploads/2020/09/UP-Depreciation-Schedule.pdf). 0 = not depreciated (plants are
# replaced at cost; fine jewelry isn't depreciated). Insurers use their own tables, so the export always shows
# the life and the maths used, which California requires to be itemized (10 CCR 2695.9(f)).
USEFUL_LIFE = {"electronics": 10, "computing": 5, "video_games": 5, "appliances_small": 10, "appliances_large": 10,
               "furniture": 10, "decor": 10, "lighting": 10, "books_media": 10, "toys_games": 2,
               "kitchenware": 10, "clothing": 4, "plants": 0, "sports_outdoor": 10, "tools": 10, "musical": 20,
               "jewelry": 0, "linens": 5, "other": 10}
# State Farm's worksheet: effective age = age x 1.4 below average, x 0.6 above average; depreciation never
# exceeds 80% while the item still did its job.
CONDITION = {"New": 0.0, "Above Avg.": 0.6, "Average": 1.0, "Below Avg.": 1.4}
CAP = 0.8


# Furniture that only sounds like a fixture.
MOVABLE = r"\b(curio|display|china|filing|file|liquor|bar|storage|medicine|tv|media|freestanding|portable|rug|runner|mat|curtain|blind|shade)\b"


def is_dwelling(name: str) -> bool:
    n = name.lower()
    if re.search(MOVABLE, n):
        return False
    return any(re.search(p, n) for p in DWELLING)


def is_not_an_item(name: str) -> bool:
    n = name.lower()
    return any(re.search(p, n) for p in NOT_ITEMS)


def category(c: str | None) -> str:
    c = (c or "").strip().lower().replace(" ", "_")
    aliases = {"appliance": "appliances_small", "appliances": "appliances_small", "books": "books_media",
               "media": "books_media", "toys": "toys_games", "games": "toys_games", "plant": "plants",
               "kitchen": "kitchenware", "lamp": "lighting", "art": "decor"}
    c = aliases.get(c, c)
    return c if c in CATEGORIES else "other"


def life_for(cat: str, name: str = "") -> int:
    n = name.lower()
    if re.search(r"\b(laptop|computer|macbook|imac|monitor|tablet|ipad|printer|router)\b", n):
        return 5
    if re.search(r"\b(playstation|xbox|nintendo|switch|console|game controller)\b", n):
        return 5
    return USEFUL_LIFE.get(cat, 10)


def acv(replacement: float, cat: str, age_years: float | None, condition: str = "Average",
        name: str = "") -> dict:
    """Actual cash value the way the State Farm worksheet explains it: RCV minus straight-line depreciation on
    the effective age, capped at 80%. Unknown age: no depreciation is assumed here, and the line says so."""
    life = life_for(cat, name)
    if not life or age_years is None:
        why = "not depreciated (no useful life)" if not life else "age unknown: depreciation left to the adjuster"
        return {"acv": round(replacement, 2), "dep_pct": 0.0, "life": life, "effective_age": None, "why": why}
    eff = max(age_years, 0) * CONDITION.get(condition, 1.0)
    dep = min(eff / life, CAP)
    return {"acv": round(replacement * (1 - dep), 2), "dep_pct": round(dep * 100, 1), "life": life,
            "effective_age": round(eff, 1),
            "why": f"{age_years:g} yr x {CONDITION.get(condition, 1.0):g} ({condition}) / {life} yr life = {dep*100:.0f}%"
                   + (" (capped at 80%)" if dep >= CAP else "")}
