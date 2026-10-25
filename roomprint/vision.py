"""Read one old photo: which room it is, what belongs to the family in it, and where each thing is.

Nemotron 3.5 Super VL proposes items with boxes. Code then keeps only what it can stand behind:
a box inside the picture and big enough to see, a name that isn't a person or a party decoration, and
fixtures moved to the building list. Every kept item gets a crop of the photo as its evidence.
"""
from __future__ import annotations

import base64
import io
from datetime import datetime

from PIL import ExifTags, Image, ImageOps

from . import rules
from .llm import nemotron

MAX_SIDE = 1600

PROMPT = """This is an old phone photo taken inside someone's home. The home was later destroyed (fire, flood or earthquake)
and the family needs a list of their belongings for an insurance claim. The photo may be of a birthday, a holiday,
a pet, a child; look PAST the people at the room behind them.

List every distinct physical item of value you can see: furniture, electronics, appliances, lamps, decor, rugs,
plants, toys, instruments, sports gear, books or dishes as a group. Skip people, pets, food, balloons and party
decorations, wrapped presents, and the house itself (walls, windows, floors, built-in cabinets, counters, sinks):
those are claimed differently. Include things that are partly hidden if you can tell what they are.

For each item give:
- name: plain and specific ("65-inch flat-screen TV", "gray 3-seat sectional sofa with chaise")
- brand: if a logo is visible, or the design is unmistakable (a Peloton bike, an iPad, a Dyson stick vacuum, a
  KitchenAid mixer, a Herman Miller Aeron chair, an IKEA KALLAX), else null. Never guess a brand from color alone.
- model: ONLY if you can tell (e.g. "PlayStation 5", "KitchenAid Artisan"), else null
- category: one of electronics, appliances_small, appliances_large, furniture, decor, lighting, books_media,
  toys_games, kitchenware, clothing, plants, sports_outdoor, tools, musical, jewelry, linens, other
- quantity: integer (for a group like books, your count estimate)
- size_or_detail: what you can see that matters for price (size, material, color, number of seats)
- shop_as: how a shopper would search today for a NEW equivalent: type, size, material, grade, and the brand/model
  only if you named them above (e.g. "65 inch 4K LED smart TV", "Sony PlayStation 5 disc console",
  "gray fabric sectional sofa with chaise 3 seat", "white 4x4 cube bookcase", "brass floor lamp with linen shade")
- seen: one short phrase, what in the photo shows it
- confidence: 0 to 1
- box: [x0, y0, x1, y1] in 0-1000 coordinates of this image

Also say which room this is (living room, kitchen, bedroom, kid's room, bathroom, garage, dining room, office,
yard, other).

Reply with JSON only: {"room": "...", "items": [...]}"""


def load(raw: bytes) -> tuple[Image.Image, str | None]:
    """The photo upright and at most MAX_SIDE, and the date it was taken (EXIF) if the file has one."""
    im = Image.open(io.BytesIO(raw))
    taken = None
    try:
        ex = im.getexif()
        tags = {ExifTags.TAGS.get(k, k): v for k, v in ex.items()}
        sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
        when = sub.get(36867) or tags.get("DateTimeOriginal") or tags.get("DateTime")
        if when:
            taken = datetime.strptime(str(when)[:19], "%Y:%m:%d %H:%M:%S").date().isoformat()
    except Exception:
        taken = None
    im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im, taken


def jpeg_b64(im: Image.Image, quality: int = 88) -> str:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def check_box(box, w: int, h: int) -> tuple[list[int] | None, str | None]:
    """Model box (0-1000) → pixel box, or the reason it can't be used as evidence."""
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
    except Exception:
        return None, "no usable box"
    if not all(0 <= v <= 1000 for v in (x0, y0, x1, y1)):
        return None, "box outside the photo"
    if x1 <= x0 or y1 <= y0:
        return None, "box has no area"
    if (x1 - x0) * (y1 - y0) < 15 * 15:  # under ~1.5% of each side: too small to show anyone
        return None, "too small to show as evidence"
    return [round(x0 * w / 1000), round(y0 * h / 1000), round(x1 * w / 1000), round(y1 * h / 1000)], None


def crop(im: Image.Image, px: list[int], pad: float = 0.06) -> Image.Image:
    x0, y0, x1, y1 = px
    dx, dy = (x1 - x0) * pad, (y1 - y0) * pad
    return im.crop((max(0, x0 - dx), max(0, y0 - dy), min(im.width, x1 + dx), min(im.height, y1 + dy)))


def read_photo(im: Image.Image, photo_id: str) -> dict:
    a = nemotron("vision", PROMPT, image_b64=jpeg_b64(im), max_tokens=3500, purpose=f"read photo {photo_id}")
    data = a.json()
    kept, dropped, building = [], [], []
    for i, it in enumerate(data.get("items") or []):
        name = str(it.get("name") or "").strip()
        if not name:
            continue
        px, why = check_box(it.get("box"), im.width, im.height)
        row = {"id": f"{photo_id}.{i}", "photo": photo_id, "name": name,
               "brand": it.get("brand") or None, "model": it.get("model") or None,
               "category": rules.category(it.get("category")),
               "quantity": max(1, int(it.get("quantity") or 1)) if str(it.get("quantity") or "1").isdigit() else 1,
               "detail": it.get("size_or_detail") or "", "shop_as": str(it.get("shop_as") or "").strip(), "seen": it.get("seen") or "",
               "confidence": float(it.get("confidence") or 0), "box": px,
               "boxf": [round(v / d, 4) for v, d in zip(px, (im.width, im.height, im.width, im.height))] if px else None}
        if rules.is_not_an_item(name):
            dropped.append({**row, "why": "a person, pet, food or decoration, not property"})
        elif why:
            dropped.append({**row, "why": why})
        elif rules.is_dwelling(name):
            building.append({**row, "why": "part of the building (dwelling coverage), not contents"})
        else:
            kept.append(row)
    return {"room": (data.get("room") or "other").lower(), "items": kept, "dropped": dropped,
            "building": building, "seconds": round(a.seconds, 1), "usd": a.usd}
