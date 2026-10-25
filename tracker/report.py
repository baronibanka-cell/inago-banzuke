"""Turn raw events into per-person rankings for the dashboard."""
from __future__ import annotations

from statistics import median

from .common import iso, now_ts

PRE_WINDOW = 72 * 3600   # bought this long before posting = "pre-positioned"
POST_WINDOW = 48 * 3600  # sold this soon after posting = "sold into followers"
MIN_SAMPLE = 3


def _ret(r: dict, key: str):
    e, x = r.get("entry"), r.get(key)
    if not e or x is None:
        return None
    return x / e - 1


def enrich(events: list[dict]) -> None:
    """Add returns and wallet cross-checks to each event (in place)."""
    by_person_token: dict[tuple, list[dict]] = {}
    for e in events:
        if e["kind"] in ("buy", "sell"):
            key = (e["person"], e.get("token") or e["address"])
            by_person_token.setdefault(key, []).append(e)
    has_wallet = {e["person"] for e in events if e["kind"] in ("buy", "sell")}

    for e in events:
        r = e.get("r") or {}
        e["ret"] = {k: _ret(r, k) for k in ("h1", "h24", "d7", "peak24", "low24")}
        tok = e.get("token") or e["address"]
        trades = by_person_token.get((e["person"], tok), [])
        if e["kind"] == "post":
            e["checked_wallet"] = e["person"] in has_wallet
            e["pre_buy"] = any(t["kind"] == "buy" and e["ts"] - PRE_WINDOW <= t["ts"] < e["ts"]
                               for t in trades)
            e["sold_after"] = any(t["kind"] == "sell" and e["ts"] <= t["ts"] <= e["ts"] + POST_WINDOW
                                  for t in trades)
        elif e["kind"] == "buy":
            sells = sorted(t["ts"] for t in trades if t["kind"] == "sell" and t["ts"] > e["ts"])
            e["held_hours"] = round((sells[0] - e["ts"]) / 3600, 1) if sells else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(median(xs), 4) if xs else None


def _rate(flags):
    flags = list(flags)
    return round(sum(flags) / len(flags), 3) if flags else None


def summarize(evs: list[dict]) -> dict:
    ev = [e for e in evs if e["ret"]["h1"] is not None or e["ret"]["h24"] is not None]
    r7 = [e["ret"]["d7"] for e in ev if e["ret"]["d7"] is not None]
    r24 = [e["ret"]["h24"] for e in ev if e["ret"]["h24"] is not None]
    return {
        "count": len(evs),
        "evaluated": len(ev),
        "n24": len(r24),
        "n7": len(r7),
        "h1": _med(e["ret"]["h1"] for e in ev),
        "h24": _med(r24),
        "d7": _med(r7),
        "peak24": _med(e["ret"]["peak24"] for e in ev),
        "low24": _med(e["ret"]["low24"] for e in ev),
        "win24": _rate(x > 0 for x in r24),
        "win7": _rate(x > 0 for x in r7),
    }


def badges(s: dict, pre: float | None, sold: float | None) -> list[str]:
    out = []
    if s["n24"] < MIN_SAMPLE:
        return ["データ不足"]
    if s["n7"] >= MIN_SAMPLE and s["d7"] is not None:
        if s["d7"] > 0 and (s["win7"] or 0) >= 0.5:
            out.append("持続型")
        if (s["peak24"] or 0) >= 0.3 and s["d7"] <= -0.3:
            out.append("一瞬だけ型")
    elif s["h24"] is not None and s["h24"] <= -0.3:
        out.append("24hで下落")
    if pre is not None and pre >= 0.3:
        out.append("投稿前に購入多め")
    if sold is not None and sold >= 0.3:
        out.append("投稿後に売却多め")
    return out or ["目立った傾向なし"]


def score(s: dict):
    if s["n7"] >= MIN_SAMPLE:
        return s["d7"], "7日"
    if s["n24"] >= MIN_SAMPLE:
        return s["h24"], "24時間"
    return None, None


def first_per_token(evs: list[dict], window: int = 86400) -> list[dict]:
    """Count a token once per person per day: split buys and repeat posts are one call."""
    out, last = [], {}
    for e in sorted(evs, key=lambda e: e["ts"]):
        key = e.get("token") or e["address"]
        if key in last and e["ts"] - last[key] < window:
            continue
        last[key] = e["ts"]
        out.append(e)
    return out


def build(events: list[dict], persons_cfg: list[dict]) -> dict:
    enrich(events)
    persons, shown = [], []
    for p in persons_cfg:
        name = p["name"]
        posts = first_per_token([e for e in events if e["person"] == name and e["kind"] == "post"])
        buys = first_per_token([e for e in events if e["person"] == name and e["kind"] == "buy"])
        shown += posts + buys
        ps, bs = summarize(posts), summarize(buys)
        checked = [e for e in posts if e.get("checked_wallet") and e.get("r", {}).get("entry")]
        pre = _rate(e["pre_buy"] for e in checked)
        sold = _rate(e["sold_after"] for e in checked)
        held = [e["held_hours"] for e in buys if e.get("held_hours") is not None]
        sc, basis = score(ps if ps["n24"] >= MIN_SAMPLE or not buys else bs)
        persons.append({
            "name": name,
            "telegram": p.get("telegram") or [],
            "wallets": p.get("wallets") or [],
            "posts": ps,
            "buys": bs,
            "pre_buy_rate": pre,
            "sold_after_rate": sold,
            "median_hold_h": _med(held),
            "score": sc,
            "score_basis": basis,
            "badges": badges(ps if ps["n24"] >= MIN_SAMPLE or not buys else bs, pre, sold),
            "last_seen": iso(max((e["ts"] for e in posts + buys), default=0)) if posts or buys else None,
        })
    persons.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0)))

    recent = sorted(shown,
                    key=lambda e: e["ts"], reverse=True)[:80]
    slim = [{
        "kind": e["kind"], "person": e["person"], "source": e["source"], "ts": e["ts"],
        "symbol": e.get("symbol"), "token": e.get("token") or e["address"], "link": e["link"],
        "ret": e["ret"], "pre_buy": e.get("pre_buy"), "sold_after": e.get("sold_after"),
        "checked_wallet": e.get("checked_wallet"), "held_hours": e.get("held_hours"),
        "unknown": e.get("unknown_token", False), "dead": (e.get("r") or {}).get("dead", False),
    } for e in recent]
    return {
        "generated": iso(now_ts()),
        "persons": persons,
        "recent": slim,
        "totals": {
            "posts": sum(1 for e in events if e["kind"] == "post"),
            "trades": sum(1 for e in events if e["kind"] in ("buy", "sell")),
        },
    }
