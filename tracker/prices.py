"""Price lookups through the free GeckoTerminal API (about 30 calls/minute).

For each event we record the price within 5 minutes of the event (what a
follower could realistically get), then the price 1 hour, 24 hours and 7 days
later, plus the highest and lowest price in the first 24 hours.
"""
from __future__ import annotations

from .common import http_get, log, now_ts

API = "https://api.geckoterminal.com/api/v2/networks/solana"
GAP = 2.1  # seconds between calls, keeps us under the free limit
H1, H24, D7 = 3600, 86400, 7 * 86400
RETRY_UNKNOWN_AFTER = 6 * 3600


class Budget:
    def __init__(self, calls: int):
        self.left = calls

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        return True


def _get(path: str, params=None, budget: Budget | None = None):
    if budget and not budget.take():
        return "budget"
    r = http_get(API + path, params=params, min_interval=GAP, host_key="geckoterminal")
    if r is None:
        return None
    if r.status_code == 404:
        return 404
    if r.status_code != 200:
        log(f"  ! geckoterminal {path}: HTTP {r.status_code}")
        return None
    return r.json()


def _strip(gid: str) -> str:
    return gid.split("_", 1)[1] if "_" in gid else gid


def resolve(address: str, tokens: dict, budget: Budget) -> dict | None:
    """Map a token (or pool) address to {token, pool, symbol}. Cached in `tokens`."""
    cached = tokens.get(address)
    if cached and cached.get("pool"):
        return cached
    if cached and now_ts() - cached.get("checked", 0) < RETRY_UNKNOWN_AFTER:
        return None
    if cached and cached.get("tries", 0) >= 4:
        return None

    info = None
    res = _get(f"/tokens/{address}/pools", {"page": 1}, budget)
    if res == "budget":
        return None
    if isinstance(res, dict) and res.get("data"):
        pools = sorted(res["data"], key=lambda p: float(p["attributes"].get("reserve_in_usd") or 0),
                       reverse=True)
        best = pools[0]
        base = _strip(best["relationships"]["base_token"]["data"]["id"])
        parts = best["attributes"]["name"].split(" / ")
        symbol = parts[0] if base == address or len(parts) < 2 else parts[1]
        info = {"token": address, "pool": best["attributes"]["address"], "symbol": symbol.strip()}
    elif res == 404:
        # Maybe the post linked a pool/pair address instead of the token.
        res = _get(f"/pools/{address}", None, budget)
        if isinstance(res, dict) and res.get("data"):
            p = res["data"]
            info = {"token": _strip(p["relationships"]["base_token"]["data"]["id"]),
                    "pool": address, "symbol": p["attributes"]["name"].split(" / ")[0].strip()}

    if info:
        tokens[address] = info
        if info["token"] != address:
            tokens.setdefault(info["token"], info)
        return info
    tokens[address] = {"checked": now_ts(), "tries": (cached or {}).get("tries", 0) + 1}
    return None


def _candles(pool: str, token: str, timeframe: str, aggregate: int, before: int, limit: int,
             budget: Budget):
    res = _get(f"/pools/{pool}/ohlcv/{timeframe}", {
        "aggregate": aggregate, "before_timestamp": before, "limit": limit,
        "currency": "usd", "token": token}, budget)
    if not isinstance(res, dict):
        return None if res != 404 else []
    rows = res.get("data", {}).get("attributes", {}).get("ohlcv_list", []) or []
    return sorted(rows, key=lambda c: c[0])  # [ts, open, high, low, close, volume]


def _price_at(candles: list, ts: int, step: int):
    """Close of the candle covering ts, or the last trade before it."""
    last = None
    for c in candles:
        if c[0] <= ts:
            last = c
        else:
            break
    return None if last is None else last[4]


def evaluate(event: dict, pool: str, token: str, budget: Budget) -> bool:
    """Fill event['r'] with whatever horizons have elapsed. Returns False if out of budget."""
    t0, now = event["ts"], now_ts()
    r = event.setdefault("r", {})
    age = now - t0

    need_short = ("h24" not in r and age >= H24) or ("h1" not in r and age >= H1) or "entry" not in r
    if need_short and age >= 300:
        before = min(now, t0 + H24 + 600)
        cs = _candles(pool, token, "minute", 5, before, 300, budget)
        if cs is None:
            return budget.left > 0
        if not cs:
            r["dead"] = True
            return True
        entry_candidates = [c for c in cs if c[0] <= t0 < c[0] + 300] or \
                           [c for c in cs if t0 < c[0] <= t0 + 1800]
        if not entry_candidates:
            r["no_entry"] = True
            return True
        r["entry"] = entry_candidates[0][4]
        window = [c for c in cs if t0 - 300 < c[0] <= t0 + H24]
        if age >= H1:
            r["h1"] = _price_at(cs, t0 + H1, 300)
        if age >= H24:
            r["h24"] = _price_at(cs, t0 + H24, 300)
            if window:
                r["peak24"] = max(c[2] for c in window)
                r["low24"] = min(c[3] for c in window)
                peak_c = max(window, key=lambda c: c[2])
                r["peak_after_min"] = max(0, (peak_c[0] - t0) // 60)
    if "d7" not in r and age >= D7 and r.get("entry"):
        cs = _candles(pool, token, "hour", 1, t0 + D7 + 3600, 3, budget)
        if cs is None:
            return budget.left > 0
        r["d7"] = _price_at(cs, t0 + D7, 3600) if cs else r.get("h24")
    return True


def is_complete(event: dict) -> bool:
    r = event.get("r") or {}
    return bool(r.get("dead") or r.get("no_entry") or "d7" in r)


def update(events: list[dict], tokens: dict, max_calls: int) -> None:
    budget = Budget(max_calls)
    pending = [e for e in events if e["kind"] in ("post", "buy")
               and not is_complete(e) and not e.get("unknown_token")]
    # Newest first: fresh calls are what you care about most.
    pending.sort(key=lambda e: e["ts"], reverse=True)
    done = 0
    for e in pending:
        if budget.left <= 0:
            break
        info = resolve(e["address"], tokens, budget)
        if not info:
            t = tokens.get(e["address"], {})
            if t.get("tries", 0) >= 4:
                e["unknown_token"] = True
            continue
        e["token"], e["symbol"] = info["token"], info["symbol"]
        if evaluate(e, info["pool"], info["token"], budget):
            done += 1
    log(f"  prices: updated {done} events, {budget.left} calls left, {len(pending) - done} waiting")
