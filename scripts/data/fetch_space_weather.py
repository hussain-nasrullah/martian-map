"""Download NASA CCMC DONKI space-weather records for the storm replay window in data/site.json.

Output: data/raw/donki/<endpoint>.json, verbatim API responses.
Set NASA_API_KEY for a personal key (free at api.nasa.gov); DEMO_KEY allows about 30 requests per hour.
"""
from __future__ import annotations

import json
import os

from common import RAW, load_site, session, write_source

OUT = RAW / "donki"
BASE = "https://api.nasa.gov/DONKI/"
# notifications carry the human-readable alert text the app shows; the rest are structured events.
# FLR (flares) is omitted: it returned HTTP 404 on 14 Nov 2026. Flare details appear in notifications.
ENDPOINTS = {
    "notifications": {"type": "all"},
    "CME": {},  # coronal mass ejections
    "SEP": {},  # solar energetic particle events
    "IPS": {},  # interplanetary shocks
}


def main() -> None:
    site = load_site()
    win = site["storm_window"]
    key = os.environ.get("NASA_API_KEY", "DEMO_KEY")
    http = session(2)
    status = {}
    for name, extra in ENDPOINTS.items():
        params = {"startDate": win["start"], "endDate": win["end"], "api_key": key, **extra}
        resp = http.get(BASE + name, params=params, timeout=(10, 60))
        ok = resp.status_code == 200
        if ok:
            data = resp.json()
            (OUT / f"{name}.json").parent.mkdir(parents=True, exist_ok=True)
            (OUT / f"{name}.json").write_text(json.dumps(data, indent=1))
            status[name] = {"http": 200, "records": len(data)}
        else:
            status[name] = {"http": resp.status_code}
        print(name, status[name])
    write_source(OUT, {
        "dataset": "nasa_ccmc_donki",
        "base_url": BASE,
        "window": win,
        "api_key": "personal" if key != "DEMO_KEY" else "DEMO_KEY",
        "endpoints": status,
        "context": "20 May 2024: X12 flare and SEP event; Curiosity RAD recorded its largest dose since landing.",
    })


if __name__ == "__main__":
    main()
