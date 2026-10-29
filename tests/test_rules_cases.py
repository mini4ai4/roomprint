"""Case by case: every rule that decides what reaches the claim, one named case per line. No network, no models."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from roomprint import dedupe, export, prices, rules  # noqa: E402


@pytest.mark.parametrize("name", [
    "children's toys", "child's bicycle", "children's books (stack of ~40)", "white child's desk and chair set",
    "food processor", "baby crib", "baby monitor", "dog bed", "cat tree", "cake stand", "pet carrier",
    "kids bunk bed", "stuffed dog", "gift card", "standing desk", "sleeping bag"])
def test_kept_on_the_claim(name):
    assert not rules.is_not_an_item(name)


@pytest.mark.parametrize("name", [
    "young boy", "woman", "sleeping cat", "baking sheet with cookies", "plate of cookies", "Happy Birthday banner",
    "wrapped Christmas presents", "gold balloon arch", "reflection in window", "child standing on bed"])
def test_not_property(name):
    assert rules.is_not_an_item(name)


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
