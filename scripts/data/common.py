"""Shared paths, site config, HTTP session and provenance records for the data scripts."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
SITE_FILE = DATA / "site.json"

USER_AGENT = "marswalk-planner-data/0.1"


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    @classmethod
    def from_dict(cls, d: dict) -> "BBox":
        return cls(d["west"], d["south"], d["east"], d["north"])

    def contains(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north


def load_site() -> dict:
    site = json.loads(SITE_FILE.read_text())
    site["site_bbox"] = BBox.from_dict(site["site_bbox"])
    site["context_bbox"] = BBox.from_dict(site["context_bbox"])
    return site


def session(pool: int = 16) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=5, backoff_factor=0.8,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool, pool_maxsize=pool)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = USER_AGENT
    return s


def lonlat_to_equirect(lon: float, lat: float, radius: float) -> tuple[float, float]:
    """Simple cylindrical (center lon 0, center lat 0) metres, as used by the USGS Gale mosaics."""
    return radius * math.radians(lon), radius * math.radians(lat)


def write_source(directory: Path, record: dict) -> None:
    """Write a SOURCE.json provenance record next to the files it describes."""
    directory.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in directory.rglob("*") if p.is_file() and p.name != "SOURCE.json")
    record = {
        **record,
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_bytes": sum(p.stat().st_size for p in files),
    }
    (directory / "SOURCE.json").write_text(json.dumps(record, indent=2) + "\n")


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
