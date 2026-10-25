"""Read public Telegram channels through their web preview (t.me/s/<channel>).

No login, no API key. Only public channels work. Each post that contains a
Solana token address becomes one "post" event per address.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .common import http_get, log, parse_iso

BASE58 = "1-9A-HJ-NP-Za-km-z"
ADDRESS_RE = re.compile(rf"(?<![{BASE58}])[{BASE58}]{{32,44}}(?![{BASE58}])")

# Addresses that show up in posts but are never "the coin being called".
IGNORE = {
    "So11111111111111111111111111111111111111112",   # wrapped SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}
MAX_ADDRESSES_PER_POST = 3


def extract_addresses(text: str) -> list[str]:
    seen: list[str] = []
    for m in ADDRESS_RE.findall(text):
        if m in IGNORE or m in seen:
            continue
        # Real addresses mix digits/case; filters out long plain words.
        if not any(c.isdigit() for c in m) and m.isalpha() and (m.islower() or m.isupper()):
            continue
        seen.append(m)
    return seen[:MAX_ADDRESSES_PER_POST]


def parse_page(html: str) -> list[dict]:
    """Return posts on one preview page: {post_id, channel, ts, text, addresses}."""
    soup = BeautifulSoup(html, "html.parser")
    posts = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        channel, _, num = msg["data-post"].rpartition("/")
        if not num.isdigit():
            continue
        t = msg.select_one("a.tgme_widget_message_date time[datetime]") or msg.select_one("time[datetime]")
        if t is None:
            continue
        body = msg.select_one("div.tgme_widget_message_text")
        text = body.get_text(" ", strip=True) if body else ""
        hrefs = " ".join(a.get("href", "") for a in msg.select("a[href]")
                         if "t.me/" not in a.get("href", ""))
        posts.append({
            "post_id": int(num),
            "channel": channel,
            "ts": parse_iso(t["datetime"]),
            "text": text,
            "addresses": extract_addresses(text + " " + hrefs),
        })
    return posts


def fetch_channel(channel: str, last_seen: int, backfill_pages: int) -> list[dict]:
    """Fetch posts newer than last_seen (or a backfill on the first run)."""
    channel = channel.lstrip("@").strip()
    collected: dict[int, dict] = {}
    before = None
    pages = backfill_pages if last_seen == 0 else 10
    for _ in range(pages):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
        r = http_get(url, min_interval=1.5, host_key="t.me")
        if r is None or r.status_code != 200:
            log(f"  ! telegram {channel}: could not load ({getattr(r, 'status_code', 'no response')})")
            break
        page = parse_page(r.text)
        if not page:
            if before is None:
                log(f"  ! telegram {channel}: no public posts (private channel or wrong name?)")
            break
        for p in page:
            if p["post_id"] > last_seen:
                collected[p["post_id"]] = p
        oldest = min(p["post_id"] for p in page)
        if oldest <= last_seen or oldest <= 1:
            break
        before = oldest
    return sorted(collected.values(), key=lambda p: p["post_id"])


def collect(persons: list[dict], state: dict, backfill_pages: int) -> list[dict]:
    """Return new post events for all configured channels and advance state."""
    events = []
    cursors = state.setdefault("telegram", {})
    for person in persons:
        for channel in person.get("telegram", []) or []:
            key = channel.lstrip("@").lower()
            last = cursors.get(key, 0)
            posts = fetch_channel(channel, last, backfill_pages)
            found = 0
            for p in posts:
                for addr in p["addresses"]:
                    events.append({
                        "id": f"tg:{p['channel']}/{p['post_id']}:{addr}",
                        "kind": "post",
                        "person": person["name"],
                        "source": f"@{p['channel']}",
                        "ts": p["ts"],
                        "address": addr,
                        "link": f"https://t.me/{p['channel']}/{p['post_id']}",
                        "note": p["text"][:120],
                    })
                    found += 1
            if posts:
                cursors[key] = max(last, posts[-1]["post_id"])
            log(f"  telegram @{key}: {len(posts)} new posts, {found} token mentions")
    return events
