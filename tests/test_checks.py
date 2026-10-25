"""The code that stands between a model's answer and the family's claim. No network, no models."""
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roomprint import dedupe, export, prices, rules, vision  # noqa: E402


# ---------------------------------------------------------------- what counts as contents
def test_fixtures_go_to_the_building_not_the_claim():
    for n in ["white kitchen cabinets", "kitchen sink", "wooden countertop", "hardwood flooring", "dishwasher",
              "window with blinds", "garage door opener light"]:
        assert rules.is_dwelling(n), n
    for n in ["stainless steel French door refrigerator", "glass display cabinet", "wooden sideboard or buffet cabinet",
              "area rug", "portable dishwasher", "TV media cabinet", "black printer on small cabinet", "framed wall art",
              "shower curtain"]:
        assert not rules.is_dwelling(n), n


def test_people_food_and_party_things_are_not_property():
    for n in ["child", "birthday cake", "balloons", "plate of cookies", "golden retriever dog"]:
        assert rules.is_not_an_item(n), n
    assert not rules.is_not_an_item("Peloton bike")


# ---------------------------------------------------------------- depreciation, shown and capped
def test_acv_follows_the_published_rules():
    d = rules.acv(649.99, "electronics", 2, "Average", "PlayStation 5")
    assert d["life"] == 5 and d["dep_pct"] == 40.0 and d["acv"] == 389.99
    d = rules.acv(1000, "furniture", 12, "Below Avg.")
    assert d["dep_pct"] == 80.0 and d["acv"] == 200.0 and "capped" in d["why"]
    assert rules.acv(80, "plants", 3)["dep_pct"] == 0
    assert rules.acv(300, "furniture", None)["why"].startswith("age unknown")


# ---------------------------------------------------------------- boxes that can be shown as evidence
def test_box_checks():
    assert vision.check_box([100, 100, 400, 500], 1600, 1200)[0] == [160, 120, 640, 600]
    assert vision.check_box([500, 500, 400, 600], 1600, 1200)[1] == "box has no area"
    assert vision.check_box([0, 0, 1200, 10], 1600, 1200)[1] == "box outside the photo"
    assert vision.check_box([10, 10, 20, 20], 1600, 1200)[1].startswith("too small")
    assert vision.check_box("nope", 10, 10)[1] == "no usable box"


# ---------------------------------------------------------------- the same thing in two photos
def test_only_plausible_pairs_are_compared():
    a = {"photo": "p1", "name": "gray sectional sofa", "category": "furniture", "brand": None}
    b = {"photo": "p2", "name": "gray fabric sectional with chaise", "category": "furniture", "brand": None}
    assert dedupe.could_match(a, b, "living room", "living room")
    assert not dedupe.could_match(a, {**b, "photo": "p1"}, "living room", "living room")  # same photo: two sofas
    assert not dedupe.could_match(a, b, "living room", "bedroom")
    assert not dedupe.could_match({**a, "brand": "IKEA"}, {**b, "brand": "West Elm"}, "living room", "living room")
    assert not dedupe.could_match(a, {**b, "name": "floor lamp", "category": "lighting"}, "living room", "living room")


# ---------------------------------------------------------------- a price has to be where the model says it is
CANDS = {1: {"n": 1, "text": "Dyson V8 Origin Cordless Stick Vacuum $299.99 reg $439.99 Sale.", "url": "https://t.example/v8", "site": "target.com"},
         2: {"n": 2, "text": "Restored Premium Dyson V8 Cordless Vacuum | Silver $179.99 Was $299.99", "url": "https://w.example", "site": "walmart.com"},
         3: {"n": 3, "text": "Set of 4 upholstered dining chairs $599.00 at Target", "url": "u", "site": "target.com"},
         4: {"n": 4, "text": "Sectional Sofas with Chaise 679 items starting at $395 ($650 - $1550)", "url": "u", "site": "livingspaces.com"},
         5: {"n": 5, "text": "Dyson V8 cordless vacuum, $449.99 or $37.50/mo with financing", "url": "u", "site": "dyson.com"}}


def test_price_picks_are_checked():
    ok, why = prices.check_pick({"n": 1, "price": 299.99}, CANDS)
    assert ok and ok["price"] == 299.99 and ok["site"] == "target.com"
    assert prices.check_pick({"n": 1, "price": 349.0}, CANDS)[1].startswith("$349")       # not in the sentence
    assert prices.check_pick({"n": 9, "price": 299.99}, CANDS)[1].startswith("points at")  # not offered
    assert "used" in prices.check_pick({"n": 2, "price": 179.99}, CANDS)[1]                # refurbished
    assert "was" in prices.check_pick({"n": 1, "price": 439.99}, CANDS)[1]                # the "reg" price
    assert "starting at" in prices.check_pick({"n": 4, "price": 395}, CANDS)[1]
    assert prices.check_pick({"n": 5, "price": 37.50}, CANDS)[1]                         # per month
    ok, _ = prices.check_pick({"n": 3, "price": 599, "set_of": 4}, CANDS)
    assert ok["price"] == 149.75 and ok["set_of"] == 4
    assert "set of 6" in prices.check_pick({"n": 1, "price": 299.99, "set_of": 6}, CANDS)[1]


def test_candidates_need_the_item_named_next_to_a_price():
    item = {"name": "cordless stick vacuum", "brand": "Dyson", "model": "V8"}
    results = [{"url": "https://www.target.com/p/1", "content": "Dyson V8 Origin Cordless Stick Vacuum $299.99. Free returns."},
               {"url": "https://www.reddit.com/r/x", "content": "I paid $250 for my Dyson V8 cordless last year."},
               {"url": "https://www.example.com/a", "content": "Our best blender is $99. The Dyson V8 is great."}]
    c = prices.candidates(item, results)
    assert [x["site"] for x in c] == ["target.com"]


# ---------------------------------------------------------------- the export is in the insurers' own columns
def test_export_columns_are_the_insurers():
    h = {"items": [{"n": 1, "room": "living room", "brand": "Sony", "model": "PlayStation 5", "name": "PlayStation 5 console",
                    "detail": "white", "quantity": 1, "sightings": [{"photo": "p1"}], "earliest_photo": "2023-12-25",
                    "age_years": 1.7, "unit_rcv": 649.99, "rcv": 649.99, "acv": 428.99, "dep_pct": 34.0,
                    "price": {"sources": [{"url": "https://www.gamestop.example/ps5"}]}}],
         "totals": {"rcv": 649.99, "needs_price": 0}}
    rows = list(csv.reader(io.StringIO(export.to_csv(h, "xact"))))
    assert rows[0] == export.XACT and rows[1][4].startswith("PlayStation 5 console") and rows[1][10] == "649.99"
    rows = list(csv.reader(io.StringIO(export.to_csv(h, "fema"))))
    assert rows[0] == export.FEMA and "gamestop.example" in rows[1][2] and rows[1][11] == "428.99"
