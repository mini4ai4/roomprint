"""The web app: the demo family's finished inventory, and a live run on anyone's own photos."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import export, household, llm

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
WEB = ROOT / "web"
DATA = Path(os.environ.get("ROOMPRINT_DATA", ROOT / "data"))
UPLOADS = DATA / "uploads"
MAX_PHOTOS = 8
MAX_BYTES = 12 * 1024 * 1024

app = FastAPI(title="Roomprint")
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")

JOBS: dict[str, dict] = {}
_one_at_a_time = threading.Semaphore(2)


@app.exception_handler(llm.OverBudget)
def _over(_, e):
    return JSONResponse({"error": f"{e}. The live demo has a small daily model budget; the sample home still works."},
                        status_code=429)


@app.get("/")
def index():
    """The page, with the stylesheet and script stamped by their modification time so a new deploy is never
    hidden behind a cached old copy."""
    from fastapi.responses import HTMLResponse
    html = (WEB / "index.html").read_text()
    for name in ("app.css", "app.js"):
        v = int((WEB / "static" / name).stat().st_mtime)
        html = html.replace(f"/static/{name}", f"/static/{name}?v={v}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/demo")
def demo():
    return json.loads((DEMO / "household.json").read_text())


@app.get("/photos/demo/{name}")
def demo_photo(name: str):
    p = (DEMO / "photos" / name).resolve()
    if p.parent != (DEMO / "photos").resolve() or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/photos/{job}/{name}")
def job_photo(job: str, name: str):
    base = (UPLOADS / job).resolve()
    p = (base / name).resolve()
    if p.parent != base or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


def _run(job: str, raws: dict[str, bytes], loss: date):
    J = JOBS[job]

    def progress(stage, done, total, detail):
        J["stage"], J["done"], J["total"] = stage, done, total
        if stage == "read":
            J["photos"][detail["photo"]] = {"room": detail.get("room"), "items": detail.get("items", []),
                                            "error": detail.get("error")}
        elif stage == "pricing":
            J["items"] = detail
        elif stage == "priced":
            J["prices"][detail["id"]] = {"price": detail["price"], "status": detail["status"]}
    with _one_at_a_time:
        try:
            h = household.build(raws, loss, progress=progress)
            h["job"] = job
            (UPLOADS / job / "household.json").write_text(json.dumps(h, default=str))
            J.update(stage="done", result=h)
        except llm.OverBudget as e:
            J.update(stage="error", error=f"{e}. Please try again tomorrow; the sample home still works.")
        except Exception as e:
            J.update(stage="error", error=f"Something went wrong ({type(e).__name__}); nothing was saved.")


@app.post("/api/inventory")
async def start(photos: list[UploadFile] = File(...), loss_date: str = Form("")):
    if not photos:
        raise HTTPException(400, "add at least one photo")
    if len(photos) > MAX_PHOTOS:
        raise HTTPException(400, f"up to {MAX_PHOTOS} photos at a time in the live demo")
    if llm.spent_today() >= llm.DAILY_CAP_USD:
        raise llm.OverBudget(f"today's model budget (${llm.DAILY_CAP_USD:.2f}) is spent")
    job = uuid.uuid4().hex[:12]
    d = UPLOADS / job
    d.mkdir(parents=True, exist_ok=True)
    raws = {}
    for i, f in enumerate(photos, 1):
        raw = await f.read()
        if len(raw) > MAX_BYTES:
            raise HTTPException(400, f"{f.filename} is over 12 MB")
        pid = f"photo{i}"
        raws[pid] = raw
    # save the upright, resized copy the boxes refer to
    from .vision import load
    for pid, raw in raws.items():
        im, _ = load(raw)
        im.save(d / f"{pid}.jpg", "JPEG", quality=88)
    try:
        loss = date.fromisoformat(loss_date) if loss_date else date.today()
    except ValueError:
        loss = date.today()
    JOBS[job] = {"stage": "queued", "done": 0, "total": len(raws), "photos": {}, "items": [], "prices": {},
                 "started": time.time(), "photo_ids": list(raws)}
    threading.Thread(target=_run, args=(job, raws, loss), daemon=True).start()
    return {"job": job}


@app.get("/api/inventory/{job}")
def status(job: str):
    J = JOBS.get(job)
    if not J:
        p = UPLOADS / job / "household.json"
        if p.exists():
            return {"stage": "done", "result": json.loads(p.read_text())}
        raise HTTPException(404)
    return {k: v for k, v in J.items() if k != "result"} | ({"result": J["result"]} if "result" in J else {})


@app.get("/api/export/{which}.csv")
def export_csv(which: str, fmt: str = "xact"):
    if which == "demo":
        h = demo()
    else:
        p = UPLOADS / which / "household.json"
        if not p.exists():
            raise HTTPException(404)
        h = json.loads(p.read_text())
    if fmt not in ("xact", "fema"):
        raise HTTPException(400)
    name = f"inventory-{'state-farm-xactcontents' if fmt == 'xact' else 'fema-ff-206-fy-21-106'}.csv"
    return PlainTextResponse(export.to_csv(h, fmt), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/spend")
def spend():
    return {"today_usd": round(llm.spent_today(), 4), "cap_usd": llm.DAILY_CAP_USD}
