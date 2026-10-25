"""The same TV shows up in the birthday photo, the Christmas photo and the Super Bowl photo. It is one TV.

Counting it three times would inflate the claim, and an adjuster who notices one inflated line stops trusting
the rest. Counting two real TVs as one cheats the family. So merging is careful:

1. Code proposes pairs only when two sightings could be the same thing: same room type, same category,
   names that share a word, and brands that don't contradict each other.
2. Nemotron Super VL looks at the two crops side by side and says whether it's the same physical object.
3. Code merges only on a confident "same", and never merges two sightings from the same photo (two lamps in
   one picture are two lamps). A merged item keeps every sighting as evidence.
"""
from __future__ import annotations

import re

from PIL import Image

from .llm import nemotron
from .vision import crop, jpeg_b64

STOP = {"a", "an", "the", "with", "and", "of", "set", "large", "small", "white", "black", "gray", "grey", "brown",
        "wood", "wooden", "big", "piece", "pieces"}

ASK = """Two crops from two different photos of the same family's home. LEFT and RIGHT are separated by a white bar.
Left is described as: {a}
Right is described as: {b}
Is this the SAME physical object (the one item the family owns, seen twice), or two different objects?
Look at shape, color, size, material, logos and details. Different angle or lighting is fine.
Reply JSON only: {{"same": true|false, "confidence": 0-1, "why": "<one short line>"}}"""


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 2}


def could_match(a: dict, b: dict, room_a: str, room_b: str) -> bool:
    if a["photo"] == b["photo"]:
        return False
    if room_a != room_b or a["category"] != b["category"]:
        return False
    if a.get("brand") and b.get("brand") and a["brand"].lower() != b["brand"].lower():
        return False
    return bool(_words(a["name"]) & _words(b["name"]))


def side_by_side(left: Image.Image, right: Image.Image, h: int = 360) -> Image.Image:
    ls = left.resize((max(1, round(left.width * h / left.height)), h))
    rs = right.resize((max(1, round(right.width * h / right.height)), h))
    out = Image.new("RGB", (ls.width + rs.width + 24, h), "white")
    out.paste(ls, (0, 0))
    out.paste(rs, (ls.width + 24, 0))
    return out


def same_object(a: dict, b: dict, img_a: Image.Image, img_b: Image.Image) -> dict:
    pair = side_by_side(crop(img_a, a["box"]), crop(img_b, b["box"]))
    desc = lambda x: ", ".join(filter(None, [x.get("brand"), x.get("model"), x["name"], x.get("detail")]))
    r = nemotron("vision", ASK.format(a=desc(a), b=desc(b)), image_b64=jpeg_b64(pair), max_tokens=200,
                 purpose=f"same object? {a['name']} / {b['name']}")
    d = r.json()
    return {"same": bool(d.get("same")), "confidence": float(d.get("confidence") or 0), "why": d.get("why") or ""}


def merge(photos: dict[str, dict], images: dict[str, Image.Image], min_conf: float = 0.7) -> tuple[list[dict], list[dict]]:
    """photos: {photo_id: read_photo result}. Returns (items, decisions). Each item has `sightings`."""
    groups: list[dict] = []
    decisions = []
    for pid, ph in photos.items():
        for it in ph["items"]:
            placed = False
            for g in groups:
                head = g["sightings"][0]
                if any(s["photo"] == it["photo"] for s in g["sightings"]):
                    continue
                if not could_match(head, it, g["room"], ph["room"]):
                    continue
                v = same_object(head, it, images[head["photo"]], images[it["photo"]])
                ok = v["same"] and v["confidence"] >= min_conf
                decisions.append({"a": head["id"], "b": it["id"], "a_name": head["name"], "b_name": it["name"],
                                  **v, "merged": ok})
                if ok:
                    g["sightings"].append(it)
                    placed = True
                    break
            if not placed:
                groups.append({"room": ph["room"], "sightings": [it]})
    items = []
    for g in groups:
        best = max(g["sightings"], key=lambda s: (bool(s.get("brand")) + bool(s.get("model")), s["confidence"]))
        items.append({**best, "room": g["room"], "quantity": max(s["quantity"] for s in g["sightings"]),
                      "sightings": [{"photo": s["photo"], "id": s["id"], "box": s["box"], "boxf": s.get("boxf")}
                                    for s in g["sightings"]]})
    return items, decisions
