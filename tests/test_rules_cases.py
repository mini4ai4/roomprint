"""Case by case: every rule that decides what reaches the claim, one named case per line. No network, no models."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roomprint import dedupe, export, prices, rules  # noqa: E402


@pytest.mark.parametrize("name", [
    "children's toys", "child's bicycle", "children's books (stack of ~40)", "white child's desk and chair set",
    "food processor", "baby crib", "baby monitor", "dog bed", "cat tree", "cake stand", "pet carrier",
    "kids bunk bed", "stuffed dog", "gift card", "standing desk", "sleeping bag", "baking sheet with cookies",
    "plate of cookies", "dining table with food", "kitchen island with snacks", "bowl of food"])
def test_kept_on_the_claim(name):
    assert not rules.is_not_an_item(name)


@pytest.mark.parametrize("name", [
    "young boy", "woman", "sleeping cat", "cookies", "birthday cake", "cookies on a baking sheet", "Happy Birthday banner",
    "wrapped Christmas presents", "gold balloon arch", "reflection in window", "child standing on bed"])
def test_not_property(name):
    assert rules.is_not_an_item(name)


@pytest.mark.parametrize("name,line", [
    ("baking sheet with cookies", "baking sheet"), ("plate of cookies", "plate"), ("dining table with food", "dining table"),
    ("bowl full of fruit", "bowl"), ("plate with chocolate chip cookies", "plate"), ("cake stand", "cake stand"),
    ("food processor", "food processor"), ("glass mixing bowl", "glass mixing bowl")])
def test_the_container_stays_and_the_food_comes_off_its_name(name, line):
    assert rules.without_food(name) == line


@pytest.mark.parametrize("host,ok", [
    ("bestbuy.com", True), ("walmart.com", True), ("target.com", True), ("homedepot.com", True), ("wayfair.com", True),
    ("ikea.com", True), ("nintendo.com", True),
    ("theverge.com", False), ("runnersworld.com", False), ("ebookwritingexperts.com", False),
    ("heyimreading.com", False), ("thepublishingheaven.com", False), ("reddit.com", False), ("ebay.com", False),
    ("someones.blogspot.com", False)])
def test_only_shops_price_an_item(host, ok):
    assert prices.is_store(host) is ok


@pytest.mark.parametrize("name,lot", [
    ("stack of books", True), ("children's books (stack of ~40)", True), ("bookshelf with assorted books", True),
    ("Harry Potter box set", False), ("bookshelf", False)])
def test_a_shelf_of_books_is_priced_by_title(name, lot):
    assert bool(prices.LOT_OF_BOOKS.search(name)) is lot


def test_a_shelf_of_books_needs_titles_not_a_guess():
    out = prices._price({"name": "stack of children's books", "quantity": 1}, [
        {"url": "https://www.target.com/x", "content": "Children's books bundle of 20 books $59.99 at Target."}], "given")
    assert out["status"] == "needs a price" and "title" in out["why"]


@pytest.mark.parametrize("text,vals", [
    ("Now $1,299.99 at Best Buy", [1299.99]), ("$40 or $3.33/mo", [40.0, 3.33]), ("no price here", [])])
def test_amounts_are_read_exactly(text, vals):
    assert prices.amounts(text) == vals


@pytest.mark.parametrize("a,b,same", [
    ("stainless steel microwave", "stainless steel refrigerator", False),
    ("65 inch flat screen TV", "large flat screen television", True),
    ("gray sectional sofa", "gray fabric sectional with chaise", True),
    ("table lamp", "floor lamp", True),
    ("oak dining table", "oak coffee table", True),
    ("wooden bookshelf", "wooden desk", False),
    ("stainless steel microwave oven", "over-the-range microwave", True),
    ("stainless steel microwave oven", "gas stove and oven range", False)])
def test_kind_of_thing(a, b, same):
    assert (dedupe.kind(a) == dedupe.kind(b)) is same


def test_export_rows_carry_rcv_acv_and_the_store_link():
    lines = [{"n": 1, "room": "kitchen", "name": "microwave", "quantity": 1, "unit_rcv": 100.0, "rcv": 100.0,
              "acv": 60.0, "dep_pct": 40.0, "age_years": 2.5, "sightings": [{"photo": "a"}],
              "price": {"sources": [{"url": "https://www.target.com/microwave"}]}},
             {"n": 2, "room": "kitchen", "name": "toaster", "quantity": 1, "unit_rcv": None, "age_years": None,
              "sightings": [{"photo": "a"}], "price": {"sources": []}}]
    h = {"items": lines, "totals": {"rcv": 100.0, "needs_price": 1}}
    head, body = export.rows(h, "fema")
    assert len(body[0]) == len(head)
    assert body[0][8] == "100.00" and body[0][10] == "40.00" and body[0][11] == "60.00"
    assert "target.com/microwave" in body[0][2]
    assert body[1][8] == ""  # an unpriced line is left blank, never guessed
    csv_text = export.to_csv(h, "xact")
    assert "Total replacement cost (priced lines),100.00" in csv_text and "Lines still needing a price,1" in csv_text


# ---------------------------------------------------------------- like for like: a set as a set, one thing as one
DESK_SET = {"name": "white child's desk and chair set", "quantity": 1}


@pytest.mark.parametrize("item,text,set_of,bad", [
    (DESK_SET, "Child's desk chair, white $29.99Price.", 1, "one piece"),
    (DESK_SET, "Kids desk with hutch set, white $89.99", 1, "doesn't include the chair"),
    (DESK_SET, "Kids Desk and Chair Set, white $119.99", 1, None),
    ({"name": "measuring cups and spoons", "quantity": 1}, "16 Piece Measuring Cups and Spoons Set $29.99", 1, None),
    ({"name": "ceramic table lamp", "quantity": 1}, "Ceramic Table Lamps, Set of 2, $109.99", 1, "set of 2"),
    ({"name": "ceramic table lamp", "quantity": 1}, "Ceramic Table Lamps, Set of 2, $109.99", 2, None),
    ({"name": "wooden dining chair", "quantity": 1}, "Dining chairs 2-pack $149.12", 1, "set of 2"),
    ({"name": "wood bookcase filled with books and binders", "quantity": 1}, "5 shelf wood bookcase $170", 1, None),
    ({"name": "Christmas ornaments and decorations", "quantity": 30}, "Tree Ornaments, Boxed Set of 12 $59.95.", 12, None),
])
def test_a_price_is_for_the_same_quantity_or_set(item, text, set_of, bad):
    why = prices.like_for_like(item, text, set_of)
    assert (why is None) if bad is None else (bad in why)


def test_a_set_priced_from_one_piece_is_left_unpriced_with_the_reason(monkeypatch):
    from roomprint.llm import Answer
    reply = '{"picks": [{"n": 1, "price": 29.99, "set_of": 1}], "note": "a child desk chair"}'
    monkeypatch.setattr(prices, "nemotron", lambda *a, **k: Answer(reply, "m", 0.1, 0.0, 1, 1))
    out = prices._price(DESK_SET, [{"url": "https://www.ikea.com/x", "content": "Child's desk chair, white $29.99."}], "given")
    assert out["status"] == "needs a price" and out["price"] is None
    assert "one piece" in out["why"] and "desk and chair" in out["why"]


@pytest.mark.parametrize("name,by_title", [
    ("books on shelf", True), ("books", True), ("cookbooks", True), ("children's books", True),
    ("group of books and binders on bookcase", True), ("stack of books", True),
    ("bookshelf", False), ("wood bookcase filled with books and binders", False), ("notebook", False)])
def test_books_without_titles_are_never_priced_by_the_shelf(name, by_title):
    assert prices.books_without_titles({"name": name}) is by_title
    if by_title:
        out = prices._price({"name": name, "quantity": 12}, [
            {"url": "https://www.bookdepot.com/x", "content": "Cookbooks (Hardcover) $5.00 $3.75 List: $30.00 - Qty: 12."}], "given")
        assert out["status"] == "needs a price" and "titles" in out["why"]


def test_reapplying_rules_reprices_a_set_from_its_saved_sources_without_any_call(monkeypatch):
    from eval import reapply_rules
    line = {**DESK_SET, "price": {"status": "one source", "price": 29.99, "query": "white kids desk and chair set price",
                                  "sources": [{"price": 29.99, "listed": 29.99, "set_of": 1, "site": "ikea.com",
                                               "url": "https://www.ikea.com/x", "quote": "Child's desk chair, white $29.99Price."}]}}
    monkeypatch.setattr(prices, "_load_cache", lambda: {})
    p = reapply_rules.restatus(line)
    assert p["status"] == "needs a price" and p["sources"] == [] and "one piece" in p["why"]
    books = reapply_rules.restatus({"name": "books on shelf", "quantity": 12, "price": {"status": "one source", "price": 5.0,
                                    "sources": [{"price": 5.0, "site": "bookdepot.com", "url": "u", "quote": "$5.00"}]}})
    assert books["status"] == "needs a price" and "titles" in books["why"]


def test_only_the_words_about_the_picked_price_count():
    rocket = {"name": "model rocket", "quantity": 1}
    text = "Estes C6-3 Model Rocket Engines 3Pk, Price Now $13.50 Was $18.00 · Estes Model Rocket Launch Set, Price $33.50."
    assert prices.like_for_like(rocket, text, 1, 33.50) is None
    assert "set of 3" in prices.like_for_like(rocket, text, 1, 13.50)
    bed = {"name": "wooden platform bed frame with headboard", "quantity": 1}
    assert prices.like_for_like(bed, "Wood King Platform Bed with Headboard, $597.65 /set (4.3 / 6) Light Brown/set of 2 color", 1, 597.65) is None
