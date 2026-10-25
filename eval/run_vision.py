"""How well the photo reading works, graded by code against a hand-made list of what each sample photo shows.

    python eval/run_vision.py --runs 3

Per photo: recall of the things a person can clearly see, building parts that leaked into contents, people/food
that leaked in, and boxes that couldn't be used. Live Nemotron calls; about $0.02 a run.
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from roomprint import llm, rules, vision  # noqa: E402
from roomprint.household import room_name  # noqa: E402

GT = json.loads((ROOT / "eval" / "ground_truth.json").read_text())


def text(it):
    return " ".join(filter(None, [it["name"], it.get("brand"), it.get("model"), it.get("detail")])).lower()


def found(alt, items):
    words = [w for w in alt.split("|")]
    return any(any(re.search(r"\b" + re.escape(w), text(it)) for w in words) for it in items)


def grade(pid, r):
    g = GT[pid]
    hits = [m[0] for m in g["must"] if found(m[0], r["items"])]
    miss = [m[0] for m in g["must"] if m[0] not in hits]
    leak_fixture = [it["name"] for it in r["items"] if any(w in it["name"].lower() for w in g["not_contents"])]
    leak_people = [it["name"] for it in r["items"] if rules.is_not_an_item(it["name"])]
    return {"photo": pid, "room_ok": room_name(r["room"]) == g["room"], "room": r["room"], "found": len(hits),
            "of": len(g["must"]), "missed": miss, "fixtures_in_contents": leak_fixture, "people_in_contents": leak_people,
            "items": len(r["items"]), "dropped": len(r["dropped"]), "building": len(r["building"]),
            "seconds": r["seconds"]}


def one_run():
    def go(pid):
        im, _ = vision.load((ROOT / "demo" / "photos" / f"{pid}.jpg").read_bytes())
        return grade(pid, vision.read_photo(im, pid))
    with cf.ThreadPoolExecutor(5) as ex:
        return list(ex.map(go, [k for k in GT if not k.startswith("_")]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    out, start = [], time.time()
    for n in range(a.runs):
        res = one_run()
        out.append(res)
        f = sum(r["found"] for r in res); o = sum(r["of"] for r in res)
        print(f"run {n+1}: {f}/{o} visible things found; rooms right {sum(r['room_ok'] for r in res)}/{len(res)}; "
              f"fixtures leaked {sum(len(r['fixtures_in_contents']) for r in res)}; people leaked {sum(len(r['people_in_contents']) for r in res)}")
        for r in res:
            if r["missed"] or r["fixtures_in_contents"] or not r["room_ok"]:
                print(f"   {r['photo']:12} missed {r['missed']} fixtures {r['fixtures_in_contents']} room {r['room']}")
    usd = sum(c["usd"] for c in llm.calls())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (ROOT / "eval" / "results").mkdir(exist_ok=True)
    (ROOT / "eval" / "results" / f"vision-{stamp}.json").write_text(json.dumps({"runs": out, "usd": usd}, indent=1))
    print(f"total ${usd:.4f}, {time.time()-start:.0f} s")
