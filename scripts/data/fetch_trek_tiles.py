"""Download NASA Mars Trek WMTS tiles (equirectangular, EPSG:104905) for the site and its context.

Output: data/raw/trek/<layer>/<z>/<row>/<col>.png  (same layout Leaflet's EPSG4326 CRS requests as {z}/{y}/{x})
Re-runs skip tiles already on disk.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import RAW, BBox, human_bytes, load_site, session, write_source

TREK = "https://trek.nasa.gov/tiles/Mars/EQ/{layer}/1.0.0/default/default028mm/{z}/{row}/{col}.png"

# layer id -> (zoom range, which bbox, description)
LAYERS = {
    "curiosity_hirise_mosaic": ((12, 16), "site", "MRO HiRISE, Curiosity roving site mosaic. 0.64 m/px at z16."),
    "curiosity_ctx_mosaic": ((6, 10), "context", "MRO CTX, Curiosity roving site mosaic. About 41 m/px at z10."),
    "THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018": ((5, 9), "context",
                                                         "Mars Odyssey THEMIS night infrared, 100 m controlled mosaic."),
}


def tile_range(b: BBox, z: int) -> tuple[range, range]:
    size = 180 / 2 ** z
    cols = range(int((b.west + 180) // size), int((b.east + 180) // size) + 1)
    rows = range(int((90 - b.north) // size), int((90 - b.south) // size) + 1)
    return rows, cols


def fetch_layer(layer: str, zooms: tuple[int, int], bbox: BBox, description: str, workers: int) -> None:
    out = RAW / "trek" / layer
    http = session(workers)
    jobs = []
    for z in range(zooms[0], zooms[1] + 1):
        rows, cols = tile_range(bbox, z)
        jobs += [(z, r, c) for r in rows for c in cols]

    def get(job):
        z, r, c = job
        path = out / str(z) / str(r) / f"{c}.png"
        if path.exists() and path.stat().st_size > 0:
            return "cached"
        resp = http.get(TREK.format(layer=layer, z=z, row=r, col=c), timeout=(10, 30))
        if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("image/"):
            return f"http {resp.status_code}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
        return "ok"

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(workers) as pool:
        for fut in as_completed(pool.submit(get, j) for j in jobs):
            try:
                key = fut.result()
            except Exception as exc:  # network error after retries
                key = f"error {type(exc).__name__}"
            counts[key] = counts.get(key, 0) + 1

    write_source(out, {
        "dataset": layer,
        "description": description,
        "url_template": TREK.replace("{layer}", layer),
        "capabilities": f"https://trek.nasa.gov/tiles/Mars/EQ/{layer}/1.0.0/WMTSCapabilities.xml",
        "crs": "urn:ogc:def:crs:EPSG::104905 (Mars equirectangular, degrees)",
        "tile_size": 256,
        "zoom_min": zooms[0],
        "zoom_max": zooms[1],
        "bbox": bbox.__dict__,
        "layout": "{z}/{row}/{col}.png; row 0 at north pole, 2 x 1 tiles at zoom 0",
        "result_counts": counts,
    })
    size = sum(p.stat().st_size for p in out.rglob("*.png"))
    print(f"{layer}: {len(jobs)} tiles, {counts}, {human_bytes(size)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layers", nargs="*", default=list(LAYERS), choices=list(LAYERS))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    site = load_site()
    for layer in args.layers:
        zooms, which, desc = LAYERS[layer]
        bbox = site["site_bbox"] if which == "site" else site["context_bbox"]
        fetch_layer(layer, zooms, bbox, desc, args.workers)


if __name__ == "__main__":
    main()
