"""The inventory in the columns insurers already use, so nobody has to retype it.

- "xact": State Farm's Personal Property Customer Worksheet, whose file is Xactware's "XactContents Import
  Template" (the pricing system adjusters use). Columns copied verbatim from the California version.
- "fema": FEMA / NFIP Personal Property (Contents) Worksheet FF-206-FY-21-106, 14 columns verbatim. Its
  description column asks for a web link, which is where each price's source goes.

In a California declared disaster, an insurer can't insist on its own form if ours carries substantially the
same information (Cal. Ins. Code 2061(a)(2)), and must accept grouped lines like "30 paperback books".
"""
from __future__ import annotations

import csv
import io

XACT = ["Item #", "Room", "Brand or Manufacturer", "Model#", "Item Description", "Quantity Lost",
        "Item Age (Years)", "Item Age (Months)", "Condition", "Cost to Replace Pre-Tax (each)", "Total Cost"]

FEMA = ["Item No.", "Room/Area of Item (e.g. Bedroom, Hall, Living Room)",
        "Description of Item (e.g. manufacturer, color, size, dimensions) (include Web link, if available)",
        "Item Model Number (if applicable)", "Item Serial Number (if applicable)", "Item Age (years)", "Qty. of Item #",
        "Unit Cost to Repair or Replace Each Item (Includes Tax)", "Total Cost to Repair or Replace (RCV)",
        "Percentage of Depreciation (if replacing) %", "Amount of Depreciation (calculated)",
        "Depreciated Amount of Item (ACV)", "Amount of Salvage (Buy Back)", "Net ACV Amount of Loss"]


def _desc(l: dict) -> str:
    bits = [l["name"]]
    if l.get("detail"):
        bits.append(l["detail"])
    k = len(l['sightings'])
    seen = f"seen in {k} photo{'' if k == 1 else 's'}" + (f", earliest {l['earliest_photo']}" if l.get("earliest_photo") else "")
    bits.append(seen)
    return "; ".join(bits)


def _link(l: dict) -> str:
    src = (l.get("price") or {}).get("sources") or []
    return src[0]["url"] if src else ""


def rows(h: dict, fmt: str) -> tuple[list[str], list[list]]:
    out = []
    for l in h["items"]:
        unit = l.get("unit_rcv")
        age = l.get("age_years")
        if fmt == "xact":
            out.append([l["n"], l["room"].title(), l.get("brand") or "", l.get("model") or "", _desc(l), l["quantity"],
                        int(age) if age is not None else "", round((age % 1) * 12) if age is not None else "",
                        l.get("condition", "Average"), f"{unit:.2f}" if unit else "", f"{l['rcv']:.2f}" if unit else ""])
        else:
            dep = (l.get("rcv") or 0) - (l.get("acv") or 0)
            out.append([l["n"], l["room"].title(), (_desc(l) + (f" | {_link(l)}" if _link(l) else "")),
                        l.get("model") or "", "", age if age is not None else "", l["quantity"],
                        f"{unit:.2f}" if unit else "", f"{l['rcv']:.2f}" if unit else "",
                        l.get("dep_pct", "") if unit else "", f"{dep:.2f}" if unit else "",
                        f"{l['acv']:.2f}" if unit else "", "", f"{l['acv']:.2f}" if unit else ""])
    return (XACT if fmt == "xact" else FEMA), out


def to_csv(h: dict, fmt: str = "xact") -> str:
    head, body = rows(h, fmt)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    w.writerows(body)
    t = h["totals"]
    w.writerow([])
    w.writerow(["Total replacement cost (priced lines)", f"{t['rcv']:.2f}"])
    w.writerow(["Lines still needing a price", t["needs_price"]])
    w.writerow(["Prices: today's cost of a new like-kind item, each from public store pages (links in the app). "
                "Age: at least the time since the earliest photo the item appears in."])
    return buf.getvalue()
