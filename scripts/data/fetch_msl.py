"""Download Curiosity (MSL) mission data: rover track, REMS weather, raw-image index for the site.

Output: data/raw/msl/
  waypoints.geojson      every rover stop (MMGIS), verbatim
  traverse.geojson       rover track lines (MMGIS), verbatim
  rems_weather.json      REMS daily weather feed, verbatim
  raw_images_index.json  compact index of raw images (thumbnails excluded) taken while the rover was inside the site box
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from common import RAW, human_bytes, load_site, session, write_source

OUT = RAW / "msl"
WAYPOINTS = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_waypoints.json"
TRAVERSE = "https://mars.nasa.gov/mmgis-maps/MSL/Layers/json/MSL_traverse.json"
REMS = "https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json"
RAW_API = "https://mars.nasa.gov/api/v1/raw_image_items/"

# Cameras useful for "what will I see here": navigation context, colour science views, close-ups.
CAMERAS = ["NAV_LEFT_B", "MAST_LEFT", "MAST_RIGHT", "MAHLI", "CHEMCAM_RMI", "FHAZ_LEFT_B"]
INDEX_FIELDS = ["id", "sol", "instrument", "sample_type", "date_taken", "url", "imageid"]


def download(http, url: str, path) -> int:
    resp = http.get(url, timeout=(10, 180))
    resp.raise_for_status()
    json.loads(resp.content)  # fail loudly on a non-JSON error page
    path.write_bytes(resp.content)
    return len(resp.content)


def site_sol_ranges(waypoints: dict, site) -> list[tuple[int, int]]:
    """Contiguous sol ranges with rover stops inside the site box (gap > 30 sols splits a range)."""
    box = site["site_bbox"]
    sols = sorted({int(f["properties"]["sol"]) for f in waypoints["features"]
                   if box.contains(f["properties"]["lon"], f["properties"]["lat"])})
    ranges, start, prev = [], sols[0], sols[0]
    for s in sols[1:]:
        if s - prev > 30:
            ranges.append((start, prev))
            start = s
        prev = s
    ranges.append((start, prev))
    return ranges


def image_index(http, ranges, workers: int) -> tuple[list, dict]:
    def query(cam, lo, hi, page):
        params = {"order": "sol asc", "per_page": 500, "page": page,
                  "condition_1": "msl:mission", "condition_2": f"{lo}:sol:gte",
                  "condition_3": f"{hi}:sol:lte", "condition_4": f"{cam}:instrument:in"}
        resp = http.get(RAW_API, params=params, timeout=(10, 120))
        resp.raise_for_status()
        return resp.json()

    first = {(cam, lo, hi): query(cam, lo, hi, 0) for cam in CAMERAS for lo, hi in ranges}
    jobs = []
    for (cam, lo, hi), d in first.items():
        pages = -(-d["total"] // 500)
        jobs += [(cam, lo, hi, p) for p in range(1, pages)]
    with ThreadPoolExecutor(workers) as pool:
        rest = list(pool.map(lambda j: query(*j), jobs))

    rows, totals = {}, {}
    for d in list(first.values()) + rest:
        for it in d["items"]:
            sample = it.get("extended", {}).get("sample_type")
            if sample == "thumbnail":
                continue
            rows[it["id"]] = [it["id"], it["sol"], it["instrument"], sample, it["date_taken"],
                              it.get("https_url") or it["url"], it["imageid"]]
    for (cam, lo, hi), d in first.items():
        totals[f"{cam} {lo}-{hi}"] = d["total"]
    out = sorted(rows.values(), key=lambda r: (r[1], r[2], r[4]))
    return out, totals


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-images", action="store_true")
    args = ap.parse_args()
    site = load_site()
    OUT.mkdir(parents=True, exist_ok=True)
    http = session(args.workers)

    sizes = {
        "waypoints.geojson": download(http, WAYPOINTS, OUT / "waypoints.geojson"),
        "traverse.geojson": download(http, TRAVERSE, OUT / "traverse.geojson"),
        "rems_weather.json": download(http, REMS, OUT / "rems_weather.json"),
    }
    for k, v in sizes.items():
        print(f"{k}: {human_bytes(v)}")

    waypoints = json.loads((OUT / "waypoints.geojson").read_text())
    ranges = site_sol_ranges(waypoints, site)
    last = waypoints["features"][-1]["properties"]
    rems = json.loads((OUT / "rems_weather.json").read_text())["soles"]
    record = {
        "dataset": "msl_curiosity",
        "sources": {"waypoints.geojson": WAYPOINTS, "traverse.geojson": TRAVERSE,
                    "rems_weather.json": REMS, "raw_images_index.json": RAW_API},
        "credit": "NASA/JPL-Caltech; raw images NASA/JPL-Caltech/MSSS and NASA/JPL-Caltech/LANL",
        "waypoints_count": len(waypoints["features"]),
        "waypoints_last_sol": last["sol"],
        "rems_sols": len(rems),
        "rems_latest": {"sol": rems[0]["sol"], "earth_date": rems[0]["terrestrial_date"]},
        "site_sol_ranges": ranges,
        "notes": "REMS feed has blank wind and humidity fields. Raw-image items carry no camera "
                 "pointing or rover site/drive, so photos are matched to places by sol.",
    }

    if not args.skip_images:
        rows, totals = image_index(http, ranges, args.workers)
        (OUT / "raw_images_index.json").write_text(json.dumps(
            {"fields": INDEX_FIELDS, "excluded_sample_types": ["thumbnail"], "cameras": CAMERAS,
             "sol_ranges": ranges, "rows": rows}, separators=(",", ":")))
        record["raw_images"] = {"rows": len(rows), "api_totals_all_sample_types": totals}
        print(f"raw_images_index.json: {len(rows)} images (no thumbnails) over sols {ranges}")

    write_source(OUT, record)


if __name__ == "__main__":
    main()
