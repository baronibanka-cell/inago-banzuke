"""Read a wallet's swaps from a Solana RPC node (free public node by default).

A transaction counts as a buy when the wallet gains a token while spending
SOL or a stablecoin, and as a sell in the opposite case. Plain transfers and
airdrops are ignored.
"""
from __future__ import annotations

from .common import env, http_post_json, log

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
WSOL = "So11111111111111111111111111111111111111112"
STABLES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}
MAX_TX_PER_RUN = 60


def rpc_url() -> str:
    return env("SOLANA_RPC_URL", PUBLIC_RPC)


def rpc(method: str, params: list):
    url = rpc_url()
    gap = 0.5 if url == PUBLIC_RPC else 0.12
    res = http_post_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                         min_interval=gap)
    if res is None:
        return None  # network trouble or rate limit: try again next run
    if "error" in res:
        msg = str(res["error"].get("message", ""))[:160]
        log(f"  ! rpc {method}: {msg}")
        return {"__error__": msg}
    return res.get("result")


def _amount(entry: dict) -> float:
    ui = entry.get("uiTokenAmount") or {}
    if ui.get("uiAmount") is not None:
        return float(ui["uiAmount"])
    try:
        return int(ui.get("amount", 0)) / (10 ** int(ui.get("decimals", 0)))
    except (TypeError, ValueError):
        return 0.0


def swaps_in_tx(tx: dict, wallet: str) -> list[dict]:
    """Classify one jsonParsed transaction into buy/sell legs for `wallet`."""
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return []
    deltas: dict[str, float] = {}
    for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(key) or []:
            if b.get("owner") != wallet:
                continue
            deltas[b["mint"]] = deltas.get(b["mint"], 0.0) + sign * _amount(b)

    keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
    pubkeys = [k["pubkey"] if isinstance(k, dict) else k for k in keys]
    sol = 0.0
    if wallet in pubkeys:
        i = pubkeys.index(wallet)
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i < len(pre) and i < len(post):
            sol = (post[i] - pre[i]) / 1e9
    sol += deltas.pop(WSOL, 0.0)
    stable = sum(deltas.pop(m, 0.0) for m in list(deltas) if m in STABLES)

    legs = []
    for mint, d in deltas.items():
        if abs(d) < 1e-12:
            continue
        paid = sol < -0.0005 or stable < -0.01
        received = sol > 0.0005 or stable > 0.01
        if d > 0 and paid:
            legs.append({"kind": "buy", "mint": mint, "sol": round(-sol, 4), "usd": round(-stable, 2)})
        elif d < 0 and received:
            legs.append({"kind": "sell", "mint": mint, "sol": round(sol, 4), "usd": round(stable, 2)})
    return legs


def collect(persons: list[dict], state: dict, backfill: int) -> list[dict]:
    events = []
    cursors = state.setdefault("wallets", {})
    for person in persons:
        for wallet in person.get("wallets", []) or []:
            wallet = wallet.strip()
            until = cursors.get(wallet)
            opts = {"limit": min(MAX_TX_PER_RUN, backfill) if not until else MAX_TX_PER_RUN}
            if until:
                opts["until"] = until
            sigs = rpc("getSignaturesForAddress", [wallet, opts])
            if sigs is None or (isinstance(sigs, dict) and "__error__" in sigs):
                log(f"  ! wallet {wallet[:6]}…: could not read history")
                continue
            sigs = [s for s in sigs if s.get("err") is None]
            found = 0
            # oldest first so a partial run still leaves a correct cursor
            for s in reversed(sigs):
                tx = rpc("getTransaction", [s["signature"], {
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
                if tx is None:
                    log(f"  ! wallet {wallet[:6]}…: RPC busy, will continue next run")
                    break
                if "__error__" in tx:  # this one transaction can't be read: skip it
                    cursors[wallet] = s["signature"]
                    continue
                for leg in swaps_in_tx(tx, wallet):
                    events.append({
                        "id": f"w:{s['signature']}:{leg['mint']}",
                        "kind": leg["kind"],
                        "person": person["name"],
                        "source": f"{wallet[:4]}…{wallet[-4:]}",
                        "wallet": wallet,
                        "ts": tx.get("blockTime") or s.get("blockTime") or 0,
                        "address": leg["mint"],
                        "link": f"https://solscan.io/tx/{s['signature']}",
                        "size_sol": leg["sol"],
                        "size_usd": leg["usd"],
                    })
                    found += 1
                cursors[wallet] = s["signature"]
            log(f"  wallet {wallet[:6]}…: {len(sigs)} new tx, {found} swaps")
    return events
