"""Crop the USGS Astrogeology Gale mosaics to the site box without downloading whole files.

Products (all Mars equirectangular, center lon 0, sphere R = 3,396,190 m):
  dem     MSL Gale merged DEM, 1 m, float32, LZW row strips      -> data/raw/usgs/gale_dem_1m_site.tif
  ortho   MSL Gale merged orthophoto, 25 cm, uint8, uncompressed -> data/raw/usgs/gale_ortho_25cm_site.tif
  color   MSL Gale HiRISE LRGB quads, 25 cm, RGB COG             -> data/raw/usgs/gale_hirise_color_25cm_site.tif

dem and color use GDAL windowed reads over HTTP range requests.
ortho is a 50 GB uncompressed strip TIFF; GDAL would fetch whole 180 KB rows, so this script
reads only the needed bytes of each row in parallel (about 12 KB per row instead of 180 KB).
"""
from __future__ import annotations

import argparse
import math
import struct
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds

from common import RAW, human_bytes, load_site, session, write_source

PRODUCTS = {
    "dem": {
        "url": "https://planetarymaps.usgs.gov/mosaic/Mars/MSL/MSL_Gale_DEM_Mosaic_1m_v3.tif",
        "page": "https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_dem_1m",
        "out": "gale_dem_1m_site.tif",
        "description": "MSL Gale merged DEM v3, 1 m/px, heights in metres above the Mars areoid (they match Curiosity elev_geoid). "
                       "HRSC, CTX and HiRISE DEMs tied to MOLA. USGS lists status 'In Work'.",
        "citation": "Calef, F.J. III and Parker, T., 2016, MSL Gale Merged DEM, PDS Annex, USGS.",
    },
    "ortho": {
        "url": "https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif",
        "page": "https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_orthophoto_mosaic_25cm",
        "out": "gale_ortho_25cm_site.tif",
        "description": "MSL Gale merged orthophoto mosaic v3, 25 cm/px, grayscale. HiRISE where available.",
        "citation": "Calef, F.J. III and Parker, T., 2016, MSL Gale Merged Orthophoto Mosaic, PDS Annex, USGS.",
    },
    "color": {
        "url": "https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL/MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif",
        "page": "https://astrogeology.usgs.gov/search/map/mars_msl_gale_merged_orthophoto_mosaic_25cm",
        "out": "gale_hirise_color_25cm_site.tif",
        "description": "MSL Gale HiRISE LRGB colour mosaic (78 quads, sharpened), 25 cm/px, cloud-optimised GeoTIFF.",
        "citation": "USGS Astrogeology Science Center, MSL Gale HiRISE colour mosaic.",
    },
}

GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MAX_RETRY="5",
    GDAL_HTTP_RETRY_DELAY="2",
    VSI_CACHE="TRUE",
    VSI_CACHE_SIZE=str(256 * 1024 * 1024),
)


def site_window(ds, site) -> Window:
    b, r = site["site_bbox"], site["mars_radius_m"]
    x0, x1 = r * math.radians(b.west), r * math.radians(b.east)
    y0, y1 = r * math.radians(b.south), r * math.radians(b.north)
    win = from_bounds(x0, y0, x1, y1, ds.transform).round_offsets().round_lengths()
    full = Window(0, 0, ds.width, ds.height)
    return win.intersection(full)


def write_crop(path, ds, win, data, nodata=None) -> None:
    profile = dict(driver="GTiff", width=win.width, height=win.height, count=data.shape[0],
                   dtype=data.dtype, crs=ds.crs, transform=ds.window_transform(win),
                   nodata=ds.nodata if nodata is None else nodata,
                   compress="deflate", predictor=3 if data.dtype.kind == "f" else 2,
                   tiled=True, blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data)


def fetch_gdal(name: str, site) -> dict:
    p = PRODUCTS[name]
    out = RAW / "usgs" / p["out"]
    with rasterio.Env(**GDAL_ENV), rasterio.open("/vsicurl/" + p["url"]) as ds:
        win = site_window(ds, site)
        print(f"{name}: window {win} of {ds.width} x {ds.height}")
        t = time.time()
        rows = []
        step = 256
        for r in range(0, win.height, step):
            h = min(step, win.height - r)
            rows.append(ds.read(window=Window(win.col_off, win.row_off + r, win.width, h)))
            done = r + h
            rate = done / max(time.time() - t, 1e-6)
            print(f"  {name}: {done}/{win.height} rows, eta {(win.height - done) / rate:.0f}s", flush=True)
        data = np.concatenate(rows, axis=1)
        write_crop(out, ds, win, data)
        stats = summarise(data, ds.nodata)
    return {"file": out.name, "window": win.todict(), "source_size": [ds.width, ds.height], **stats}


def tiff_tag_offsets(http, url):
    """Parse a BigTIFF's first IFD; return (strip offsets pointer, byte counts pointer, width)."""
    head = http.get(url, headers={"Range": "bytes=0-15"}, timeout=60).content
    bo = "<" if head[:2] == b"II" else ">"
    assert struct.unpack(bo + "H", head[2:4])[0] == 43, "expected BigTIFF"
    ifd = struct.unpack(bo + "Q", head[8:16])[0]
    n = struct.unpack(bo + "Q", http.get(url, headers={"Range": f"bytes={ifd}-{ifd + 7}"}, timeout=60).content)[0]
    raw = http.get(url, headers={"Range": f"bytes={ifd + 8}-{ifd + 8 + n * 20 - 1}"}, timeout=60).content
    tags = {}
    for i in range(n):
        tag, typ, count, val = struct.unpack(bo + "HHQQ", raw[i * 20:(i + 1) * 20])
        tags[tag] = (typ, count, val)
    assert tags[259][2] == 1, "expected uncompressed"
    assert tags[278][2] == 1, "expected one row per strip"
    assert tags[273][0] == 16, "expected LONG8 strip offsets"
    return bo, tags[273][2], tags[256][2]


def fetch_ortho(site, workers: int) -> dict:
    p = PRODUCTS["ortho"]
    out = RAW / "usgs" / p["out"]
    http = session(workers)
    with rasterio.Env(**GDAL_ENV), rasterio.open("/vsicurl/" + p["url"]) as ds:
        win = site_window(ds, site)
        print(f"ortho: window {win} of {ds.width} x {ds.height}")
        bo, offsets_ptr, width = tiff_tag_offsets(http, p["url"])
        r0, nrows = win.row_off, win.height
        blob = http.get(p["url"], headers={"Range": f"bytes={offsets_ptr + 8 * r0}-{offsets_ptr + 8 * (r0 + nrows) - 1}"},
                        timeout=120).content
        offsets = struct.unpack(f"{bo}{nrows}Q", blob)
        data = np.zeros((1, nrows, win.width), dtype=np.uint8)
        c0, c1 = win.col_off, win.col_off + win.width - 1

        def get(i):
            start = offsets[i] + c0
            resp = http.get(p["url"], headers={"Range": f"bytes={start}-{offsets[i] + c1}"}, timeout=(10, 60))
            resp.raise_for_status()
            data[0, i, :] = np.frombuffer(resp.content, dtype=np.uint8)

        t = time.time()
        with ThreadPoolExecutor(workers) as pool:
            for k, _ in enumerate(pool.map(get, range(nrows)), 1):
                if k % 1000 == 0 or k == nrows:
                    rate = k / (time.time() - t)
                    print(f"  ortho: {k}/{nrows} rows, eta {(nrows - k) / rate:.0f}s", flush=True)
        write_crop(out, ds, win, data, nodata=0)
        stats = summarise(data, 0)
    return {"file": out.name, "window": win.todict(), "source_size": [ds.width, ds.height],
            "method": "per-row HTTP range reads of uncompressed strips", **stats}


def summarise(data, nodata) -> dict:
    valid = data != nodata if nodata is not None else np.ones_like(data, dtype=bool)
    v = data[valid]
    return {
        "shape": list(data.shape),
        "dtype": str(data.dtype),
        "valid_fraction": round(float(valid.mean()), 4),
        "min": float(v.min()) if v.size else None,
        "max": float(v.max()) if v.size else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("products", nargs="*", default=list(PRODUCTS), choices=list(PRODUCTS))
    ap.add_argument("--workers", type=int, default=16, help="parallel range requests for ortho")
    args = ap.parse_args()
    site = load_site()
    out_dir = RAW / "usgs"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    src = out_dir / "SOURCE.json"
    if src.exists():
        import json
        results = json.loads(src.read_text()).get("products", {})
    for name in args.products:
        t = time.time()
        info = fetch_ortho(site, args.workers) if name == "ortho" else fetch_gdal(name, site)
        info.update({k: PRODUCTS[name][k] for k in ("url", "page", "description", "citation")})
        info["seconds"] = round(time.time() - t)
        results[name] = info
        print(f"{name}: done in {info['seconds']}s -> {info['file']} "
              f"({human_bytes((out_dir / info['file']).stat().st_size)}), valid {info['valid_fraction']}")
    write_source(out_dir, {
        "dataset": "usgs_gale_mosaics_site_crop",
        "crs": "Mars equirectangular, center lon 0, sphere R 3396190 m (as source)",
        "site_bbox": site["site_bbox"].__dict__,
        "products": results,
    })


if __name__ == "__main__":
    main()
