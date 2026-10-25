"""Nemotron on Nebius Token Factory: one client, a price list, a spend log and a hard daily cap.

Every call goes through `nemotron()`. It records what each call cost, so the UI can show the price of a
whole inventory, and it refuses to start a call once the day's cap is spent.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import date

from openai import OpenAI

BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

# USD per 1M tokens (in, out), from the Token Factory model catalog.
# The VL price wasn't listed where we looked; we count it at Super's price so the cost shown is not lower than real.
MODELS = {
    "nano": ("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", 0.06, 0.24),
    "super": ("nvidia/nemotron-3-super-120b-a12b", 0.30, 0.90),
    "ultra": ("nvidia/Nemotron-3-Ultra-550b-a55b", 1.00, 3.00),
    "vision": ("nvidia/Nemotron-3.5-Super-VL", 0.30, 0.90),
}

DAILY_CAP_USD = float(os.environ.get("ROOMPRINT_DAILY_CAP_USD", "1.00"))


class OverBudget(RuntimeError):
    pass


@dataclass
class Answer:
    text: str
    model: str
    seconds: float
    usd: float
    tokens_in: int
    tokens_out: int

    def json(self) -> dict:
        return loads(self.text)


_lock = threading.Lock()
_spent: dict[str, float] = {}
_log: list[dict] = []
_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"], timeout=120)
    return _client


def spent_today() -> float:
    return _spent.get(date.today().isoformat(), 0.0)


def calls(since: int = 0) -> list[dict]:
    return _log[since:]


def nemotron(size: str, prompt: str, *, image_b64: str | None = None, json_mode: bool = True,
             think: bool = False, max_tokens: int = 1500, purpose: str = "") -> Answer:
    """One call. `think` turns Nemotron 3's reasoning on; it is off by default because these jobs are
    narrow and checked by code, and reasoning can spend the whole token budget before answering."""
    if spent_today() >= DAILY_CAP_USD:
        raise OverBudget(f"today's model budget (${DAILY_CAP_USD:.2f}) is spent")
    model, p_in, p_out = MODELS[size]
    content: list | str = prompt
    if image_b64:
        content = [{"type": "text", "text": prompt},
                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}}]
    kw = {"extra_body": {"chat_template_kwargs": {"enable_thinking": think}}}
    if json_mode:
        kw["response_format"] = {"type": "json_object"}
    t0 = time.time()
    r = client().chat.completions.create(model=model, messages=[{"role": "user", "content": content}],
                                         max_tokens=max_tokens, temperature=0, **kw)
    sec = time.time() - t0
    u = r.usage
    usd = (u.prompt_tokens * p_in + u.completion_tokens * p_out) / 1e6
    with _lock:
        day = date.today().isoformat()
        _spent[day] = _spent.get(day, 0.0) + usd
        _log.append({"size": size, "purpose": purpose, "seconds": round(sec, 2), "usd": round(usd, 5),
                     "in": u.prompt_tokens, "out": u.completion_tokens})
    return Answer(r.choices[0].message.content or "", model, sec, usd, u.prompt_tokens, u.completion_tokens)


def loads(text: str) -> dict:
    """JSON from a model reply, tolerating code fences or a sentence around it."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            raise
        return json.loads(m.group(0))
