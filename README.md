# Roomprint

**Your home is still in your photos.**

After a fire, flood or earthquake, the insurance company asks for a list of everything you owned: what it was,
how old, what it costs to replace. Most families never made one (59% in an NAIC survey; 44% in a Farmers survey).
After the 2025 Los Angeles fires, 57% of surveyed survivors said their insurer wanted every single item listed and
described (United Policyholders, 6-month survey). People write these lists from memory, in a motel, for weeks, and
they forget most of what they had.

But the birthday photos, the Christmas mornings and the first-day-of-school pictures show the rooms behind the people.
Roomprint reads those photos, finds the things in them, prices each one at a real store, and hands back a list in the
columns the insurer already uses, with proof on every line: the crop of the photo it was seen in, the date of that
photo, and the store page the price came from.

- **Live demo:** https://roomprint.onrender.com
- **Video (3 min):** _link after upload_

## What it does

1. **Reads each photo.** NVIDIA Nemotron 3.5 Super VL looks past the people at the room and lists the things in it,
   each with a box on the photo. The crop becomes that line's evidence.
2. **Keeps the claim clean.** Code drops people, pets, food and party decorations, and moves the house itself
   (kitchen cabinets, sinks, counters, flooring) to a separate list: policies pay for those under the building, not the
   contents, and an adjuster strikes them from a contents list.
3. **Counts each thing once.** The same TV is in the birthday photo and the Christmas photo. Code proposes a pair only
   when two sightings could be the same thing (same room, same kind, no clashing brand, never two from one photo);
   Nemotron VL then compares the two crops side by side. A merged item keeps every sighting.
4. **Prices it at a real store.** Tavily searches for a new like-kind replacement. Code keeps only sentences that name
   the item next to a dollar amount; Nemotron 3 Super picks the fair ones; code checks every pick (the amount is in
   that sentence; not used, refurbished, "was", "starting at", per-month or an accessory; a "set of 4" becomes a unit
   price). Two stores or more → the median. One store → flagged. None → "needs a price". Nothing is guessed.
5. **Shows the maths.** Age comes from the earliest photo the item appears in. Actual cash value uses the rules State
   Farm publishes on its own worksheet (effective age ×1.4 below average, ×0.6 above average, depreciation capped at
   80%) with useful lives from United Policyholders' schedule, and each line shows its calculation. California requires
   depreciation to be itemized and measurable (10 CCR 2695.9(f)).
6. **Reminds you of what no photo shows.** For each room, the common things not yet on the list (pots and pans,
   clothes in the closet, tools in the garage).
7. **Exports in the insurer's columns.** State Farm's Personal Property Customer Worksheet is Xactware's
   "XactContents Import Template", the system adjusters price claims in; FEMA's flood contents worksheet
   (FF-206-FY-21-106) asks for a web link per item. Both are one click, columns copied verbatim.
8. **Knows the California clock.** Since SB 495 (2026), after a declared disaster and a total loss, the insurer must
   offer 60% of the contents limit (up to $350,000) with no list, and can't require one for 100 days. The app shows what
   an itemized list adds on top.

## Propose, check, or leave it blank

| A model proposes | Code checks |
|---|---|
| an item and its box | box inside the photo and big enough to show; not a person, pet, food or decoration; fixtures go to the building list |
| "same object as in that photo" | only asked for plausible pairs; never two sightings from one photo; merged only on a confident yes |
| a price | the amount is in a sentence Tavily returned, next to the item's name; new, not "was" or monthly; median of stores |
| an age | from the photo's own date, not from the model |
| the export | totals recomputed; every line carries its photo and its store link |

## Models (NVIDIA Nemotron on Nebius Token Factory)

| Job | Model | Why |
|---|---|---|
| read a photo: items, boxes, room | Nemotron 3.5 Super VL (reasoning off) | a vision model that returns usable boxes; about 7 s a photo |
| same object in two crops? | Nemotron 3.5 Super VL | a yes/no on two crops side by side |
| pick fair store prices | Nemotron 3 Super | reading many messy shop sentences and judging like-kind |

Reading nine photos and pricing about a hundred things costs about $0.05 in model calls. A daily cap stops calls
before they happen.

## Run it

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
export NEBIUS_API_KEY=...   # Token Factory
export TAVILY_API_KEY=...
.venv/bin/uvicorn roomprint.web:app --port 8000
.venv/bin/python -m pytest -q tests
```

The sample family, their home and photos are made up (the photos were generated). Nothing here is legal or insurance
advice; the policy decides.

## License

MIT
