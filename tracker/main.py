"""One tracking run: collect new posts and trades, update prices, rebuild the dashboard data.

    python -m tracker.main            # normal run
    python -m tracker.main --report   # only rebuild docs/data.json
"""
from __future__ import annotations

import argparse

import yaml

from . import prices, report, solana, telegram
from .common import DATA_DIR, DOCS_DIR, ROOT, RUN_LOG, load_json, log, save_json

EVENTS = DATA_DIR / "events.json"
STATE = DATA_DIR / "state.json"


def load_config() -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    persons = []
    for p in cfg.get("people") or []:
        if not p or not p.get("name"):
            continue
        persons.append({
            "name": str(p["name"]),
            "telegram": [str(c) for c in (p.get("telegram") or [])],
            "wallets": [str(w) for w in (p.get("wallets") or [])],
        })
    cfg["people"] = persons
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="skip collection, rebuild report only")
    args = ap.parse_args()

    cfg = load_config()
    opts = cfg.get("options") or {}
    events: list[dict] = load_json(EVENTS, [])
    state: dict = load_json(STATE, {})
    known = {e["id"] for e in events}

    if not args.report:
        log("collecting Telegram posts")
        new = telegram.collect(cfg["people"], state, int(opts.get("telegram_backfill_pages", 5)))
        log("collecting wallet trades")
        new += solana.collect(cfg["people"], state, int(opts.get("wallet_backfill_tx", 60)))
        added = [e for e in new if e["id"] not in known]
        events.extend(added)
        log(f"{len(added)} new events")

        log("updating prices")
        prices.update(events, state.setdefault("tokens", {}), int(opts.get("price_calls_per_run", 120)))
        save_json(STATE, state)
        save_json(EVENTS, events)

    out = report.build(events, cfg["people"])
    save_json(DOCS_DIR / "data.json", out)
    log(f"report: {len(out['persons'])} people, {out['totals']['posts']} posts, "
        f"{out['totals']['trades']} trades")
    if not args.report:
        (DATA_DIR / "last_run.log").write_text("\n".join(RUN_LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
