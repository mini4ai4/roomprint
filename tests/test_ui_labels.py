"""What the page and the export show a person: no doubled brands, no file ids, no "1 photos"."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from roomprint import export  # noqa: E402

FMT = ROOT / "web" / "static" / "fmt.js"
node = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")


def js(expr: str):
    """Evaluate an expression against web/static/fmt.js in node and return its JSON value."""
    code = f"const f = require({json.dumps(str(FMT))}); console.log(JSON.stringify({expr}));"
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@node
def test_brand_is_not_repeated_when_the_model_already_names_it():
    assert js('f.brandModel("Nintendo", "Nintendo Switch")') == "Nintendo Switch"
    assert js('f.brandModel("Sony", "PlayStation 5")') == "Sony PlayStation 5"
    assert js('f.brandModel("Dyson", "")') == "Dyson"
    assert js('f.brandModel("", "V12")') == "V12"
    assert js('f.brandModel("Apple", "apple")') == "apple"
    assert js('f.brandModel("Nintendo", "Nintendogs")') == "Nintendo Nintendogs"


@node
def test_counts_are_pluralised():
    assert js('f.plural(1, "photo")') == "1 photo"
    assert js('f.plural(2, "photo")') == "2 photos"
    assert js('f.plural(0, "thing")') == "0 things"
    assert js('f.plural(136, "model call")') == "136 model calls"


@node
def test_a_photo_is_named_by_its_room_not_its_file_id():
    photos = {"living_xmas": {"room": "living room", "taken": "2023-12-25"}, "garage": {"room": "garage"}}
    p = json.dumps(photos)
    assert js(f'f.photoLabel({p}, "living_xmas")') == "Living room photo, 2023-12-25"
    assert js(f'f.photoLabel({p}, "garage")') == "Garage photo"
    assert "living_xmas" not in js(f'f.photoLabel({p}, "living_xmas")')
    assert js(f'f.photoLabel({p}, "nope")') == "another photo"


def test_export_says_1_photo_not_1_photos():
    line = {"n": 1, "room": "office", "name": "desk", "quantity": 1, "sightings": [{"photo": "a"}],
            "earliest_photo": None, "price": {}, "unit_rcv": None, "age_years": None}
    two = dict(line, sightings=[{"photo": "a"}, {"photo": "b"}])
    h = {"items": [line, two], "totals": {"rcv": 0, "needs_price": 2}}
    csv_text = export.to_csv(h, "xact")
    assert "seen in 1 photo;" in csv_text or csv_text.count("seen in 1 photo") == 1
    assert "1 photo(s)" not in csv_text and "1 photos" not in csv_text
    assert "seen in 2 photos" in csv_text


def test_export_file_name_carries_no_insurer_brand():
    from fastapi.testclient import TestClient
    from roomprint.web import app
    r = TestClient(app).get("/api/export/demo.csv?fmt=xact")
    assert r.status_code == 200
    cd = r.headers["content-disposition"].lower()
    assert "xactcontents" in cd and "state-farm" not in cd
    page = TestClient(app).get("/").text
    assert "/static/fmt.js?v=" in page and page.index("fmt.js") < page.index("app.js")


@node
def test_a_reason_reads_as_a_sentence_before_the_next_one():
    assert js('f.sentence("only second-hand listings found")') == "Only second-hand listings found."
    assert js('f.sentence("Two sources disagree.")') == "Two sources disagree."
    assert js('f.sentence("")') == ""
