"""Things nobody photographs: the pots in the cupboard, the socks in the drawer.

Insurers in the UK found people's own estimate of their contents rose by about a third once they were walked
through a detailed checklist, and United Policyholders' inventory spreadsheet runs to hundreds of prompts per
room for the same reason. This is a short version of that idea: for each room the photos show, the common things
that aren't on the list yet. Plain lists, plain matching; nothing is added to the claim without the family.
"""
from __future__ import annotations

import re

CHECKLIST = {
    "kitchen": ["pots and pans", "baking sheets and pans", "flatware", "cooking utensils", "cutting boards",
                "toaster", "coffee maker", "food storage containers", "dish towels", "small appliances in cupboards",
                "pantry food", "cleaning supplies", "trash can"],
    "living room": ["curtains", "throw blankets", "side tables", "coffee table", "streaming device", "game controllers",
                    "video games", "DVDs and Blu-rays", "photo frames", "candles and decor"],
    "bedroom": ["clothing in closets", "shoes", "coats and jackets", "jewelry and watches", "sheets and pillows",
                "mattress", "hangers", "laundry basket", "phone chargers", "handbags", "toiletries"],
    "kid's room": ["children's clothing", "shoes", "toys in bins", "board books", "art supplies", "backpack",
                   "bedding", "night light", "baby monitor", "car seat"],
    "office": ["printer paper and supplies", "external drives", "keyboard and mouse", "desk lamp", "cables and chargers",
               "headphones", "filing cabinet contents", "webcam", "surge protector"],
    "dining room": ["tablecloths and linens", "serving dishes", "flatware set", "candlesticks", "rug"],
    "garage": ["hand tools", "power tools", "ladder", "garden tools", "hoses", "lawn mower", "car care supplies",
               "holiday decorations in storage", "sports equipment", "paint and supplies", "extension cords"],
    "bathroom": ["towels", "bath mats", "hair dryer", "electric toothbrush", "toiletries and cosmetics",
                 "medicines", "scale", "shower curtain"],
}

STOP = {"and", "in", "of", "the", "a", "set", "supplies", "contents"}


def _w(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}


def suggestions(items: list[dict]) -> dict[str, list[str]]:
    by_room: dict[str, set[str]] = {}
    for it in items:
        by_room.setdefault(it["room"], set()).update(_w(it["name"] + " " + (it.get("detail") or "")))
    out = {}
    for room, seen in by_room.items():
        missing = [c for c in CHECKLIST.get(room, []) if not (_w(c) & seen)]
        if missing:
            out[room] = missing
    return out
