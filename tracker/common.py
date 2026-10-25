"""Shared helpers: HTTP with polite throttling, JSON storage, time."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

USER_AGENT = "Mozilla/5.0 (compatible; kol-tracker/1.0; personal research)"

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
_last_call: dict[str, float] = {}


def http_get(url: str, *, params=None, min_interval: float = 0.0, host_key: str | None = None,
             retries: int = 3, timeout: int = 20) -> requests.Response | None:
    """GET with per-host spacing and simple backoff on 429/5xx. Returns None on failure."""
    key = host_key or url.split("/")[2]
    for attempt in range(retries):
        wait = _last_call.get(key, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[key] = time.time()
        try:
            r = _session.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            log(f"  ! {key}: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, 10 * (attempt + 1)))
            continue
        return r
    return None


def http_post_json(url: str, payload: dict, *, min_interval: float = 0.0, retries: int = 3,
                   timeout: int = 30) -> dict | None:
    key = url.split("/")[2]
    for attempt in range(retries):
        wait = _last_call.get(key, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call[key] = time.time()
        try:
            r = _session.post(url, json=payload, timeout=timeout)
        except requests.RequestException as e:
            log(f"  ! {key}: {e}")
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(60, 5 * (attempt + 1)))
            continue
        if r.status_code != 200:
            log(f"  ! {key}: HTTP {r.status_code}")
            return None
        return r.json()
    return None


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def now_ts() -> int:
    return int(time.time())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def log(msg: str) -> None:
    print(msg, flush=True)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default
