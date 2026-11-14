"""Render verification images of the fetched data into docs/verification/.

Each figure is plotted in lon/lat with the rover track on top, so misregistration between
layers shows up as the track drifting off the imagery. Also writes report.json with numeric checks.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.colors import LightSource, ListedColormap, BoundaryNorm  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

from common import RAW, ROOT, BBox, load_site  # noqa: E402

OUT = ROOT / "docs" / "verification"
SITE = load_site()
BOX: BBox = SITE["site_bbox"]
CTX_BOX: BBox = SITE["context_bbox"]
R = SITE["mars_radius_m"]
REF_SOL = SITE["reference_sol"]


# ---------------------------------------------------------------- loaders
def stitch_trek(layer: str, z: int, b: BBox) -> tuple[np.ndarray, list[float]]:
    """Stitch cached Trek tiles at zoom z and crop to bbox. Returns image and lon/lat extent."""
    size = 180 / 2 ** z
    c0, c1 = int((b.west + 180) // size), int((b.east + 180) // size)
    r0, r1 = int((90 - b.north) // size), int((90 - b.south) // size)
    canvas = Image.new("RGB", ((c1 - c0 + 1) * 256, (r1 - r0 + 1) * 256))
    missing = 0
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            p = RAW / "trek" / layer / str(z) / str(r) / f"{c}.png"
            if not p.exists():
                missing += 1
                continue
            canvas.paste(Image.open(p).convert("RGB"), ((c - c0) * 256, (r - r0) * 256))
    px = 256 / size  # pixels per degree
    left, top = (b.west + 180 - c0 * size) * px, ((90 - b.north) - r0 * size) * px
    right, bottom = left + (b.east - b.west) * px, top + (b.north - b.south) * px
    img = canvas.crop((round(left), round(top), round(right), round(bottom)))
    if missing:
        print(f"  {layer} z{z}: {missing} tiles missing")
    return np.asarray(img), [b.west, b.east, b.south, b.north]


def read_crop(name: str, max_px: int = 2400):
    """Read a USGS crop downsampled to about max_px wide. Returns array (bands, h, w), extent, scale."""
    with rasterio.open(RAW / "usgs" / name) as d:
        f = max(1, math.ceil(d.width / max_px))
        a = d.read(out_shape=(d.count, d.height // f, d.width // f), resampling=Resampling.average,
                   masked=True)
        b = d.bounds
        ext = [math.degrees(b.left / R), math.degrees(b.right / R),
               math.degrees(b.bottom / R), math.degrees(b.top / R)]
        return a, ext, d


def rover():
    wp = json.loads((RAW / "msl" / "waypoints.geojson").read_text())["features"]
    pts = np.array([[f["properties"]["lon"], f["properties"]["lat"], f["properties"]["sol"],
                     f["properties"]["elev_geoid"]] for f in wp])
    return pts


def traverse_lines():
    tr = json.loads((RAW / "msl" / "traverse.geojson").read_text())["features"]
    lines = []
    for f in tr:
        g = f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
        lines += [np.array(p)[:, :2] for p in parts]
    return lines


# ---------------------------------------------------------------- drawing helpers
def new_ax(title: str, size=(10, 10)):
    fig, ax = plt.subplots(figsize=size, dpi=150)
    ax.set_title(title, fontsize=11, loc="left")
    ax.set_xlabel("Longitude (deg E)")
    ax.set_ylabel("Latitude (deg)")
    ax.ticklabel_format(useOffset=False)
    return fig, ax


def draw_track(ax, lines, pts, box: BBox | None = None, stops=True):
    for ln in lines:
        ax.plot(ln[:, 0], ln[:, 1], color="#ffd400", lw=1.0, alpha=0.9)
    if stops:
        sel = pts if box is None else pts[[box.contains(x, y) for x, y in pts[:, :2]]]
        sc = ax.scatter(sel[:, 0], sel[:, 1], c=sel[:, 2], cmap="cool", s=10, edgecolors="black",
                        linewidths=0.3, zorder=5)
        ref = pts[np.argmin(np.abs(pts[:, 2] - REF_SOL))]
        ax.scatter([ref[0]], [ref[1]], marker="*", s=180, color="white", edgecolors="black", zorder=6)
        ax.annotate(f"sol {int(ref[2])}", (ref[0], ref[1]), xytext=(8, 8), textcoords="offset points",
                    color="white", fontsize=9, weight="bold")
        return sc
    return None


def draw_box(ax, b: BBox, label="site box"):
    ax.add_patch(Rectangle((b.west, b.south), b.east - b.west, b.north - b.south,
                           fill=False, ec="red", lw=1.6))
    ax.annotate(label, (b.west, b.north), xytext=(2, 4), textcoords="offset points", color="red", fontsize=9)


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("wrote", OUT / name)


def scalebar(ax, b: BBox, metres: float):
    deg = metres / (R * math.pi / 180 * math.cos(math.radians((b.south + b.north) / 2)))
    x0 = b.west + (b.east - b.west) * 0.05
    y0 = b.south + (b.north - b.south) * 0.04
    ax.plot([x0, x0 + deg], [y0, y0], color="white", lw=4, solid_capstyle="butt")
    ax.plot([x0, x0 + deg], [y0, y0], color="black", lw=1.5, solid_capstyle="butt")
    ax.text(x0 + deg / 2, y0 + (b.north - b.south) * 0.012, f"{metres:g} m", ha="center", color="white",
            fontsize=9, weight="bold")


# ---------------------------------------------------------------- figures
def main():
    pts, lines = rover(), traverse_lines()
    report = {}

    # 1. context: CTX
    img, ext = stitch_trek("curiosity_ctx_mosaic", 10, CTX_BOX)
    fig, ax = new_ax("CTX context mosaic (Trek z10, ~41 m/px) with Curiosity track and site box")
    ax.imshow(img, extent=ext)
    draw_track(ax, lines, pts, stops=False)
    draw_box(ax, BOX)
    save(fig, "01_context_ctx.jpg")

    # 2. context: THEMIS night IR
    img, ext = stitch_trek("THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018", 9, CTX_BOX)
    fig, ax = new_ax("THEMIS night infrared (Trek z9, ~81 m/px). Bright = warm at night = rock")
    ax.imshow(img, extent=ext)
    draw_track(ax, lines, pts, stops=False)
    draw_box(ax, BOX)
    save(fig, "02_context_themis_night_ir.jpg")

    # 3. site: Trek HiRISE z16 stitched
    img, ext = stitch_trek("curiosity_hirise_mosaic", 16, BOX)
    Image.fromarray(img).save(OUT / "site_trek_hirise_z16_full.png")
    fig, ax = new_ax(f"Trek HiRISE stitched (z16, 0.64 m/px, {img.shape[1]} x {img.shape[0]} px). "
                     "Rover stops coloured by sol")
    ax.imshow(img, extent=ext)
    sc = draw_track(ax, lines, pts, BOX)
    fig.colorbar(sc, ax=ax, shrink=0.6, label="sol")
    ax.set_xlim(BOX.west, BOX.east), ax.set_ylim(BOX.south, BOX.north)
    scalebar(ax, BOX, 500)
    save(fig, "03_site_trek_hirise.jpg")

    # 4. site: USGS colour 25 cm
    a, ext, _ = read_crop("gale_hirise_color_25cm_site.tif", max_px=6100)
    rgb = np.moveaxis(a.filled(0), 0, -1).astype(np.uint8)
    Image.fromarray(rgb).save(OUT / "site_usgs_color_50cm_full.jpg", quality=88)
    fig, ax = new_ax("USGS HiRISE colour mosaic crop (25 cm/px source, shown downsampled)")
    ax.imshow(rgb, extent=ext)
    draw_track(ax, lines, pts, BOX)
    ax.set_xlim(BOX.west, BOX.east), ax.set_ylim(BOX.south, BOX.north)
    scalebar(ax, BOX, 500)
    save(fig, "04_site_usgs_color.jpg")

    # 5. site: USGS ortho 25 cm grayscale
    ortho_path = RAW / "usgs" / "gale_ortho_25cm_site.tif"
    if ortho_path.exists():
        a, ext, _ = read_crop("gale_ortho_25cm_site.tif")
        fig, ax = new_ax("USGS merged orthophoto crop (25 cm/px source, shown downsampled)")
        ax.imshow(a[0].filled(0), extent=ext, cmap="gray")
        draw_track(ax, lines, pts, BOX)
        ax.set_xlim(BOX.west, BOX.east), ax.set_ylim(BOX.south, BOX.north)
        scalebar(ax, BOX, 500)
        save(fig, "05_site_usgs_ortho.jpg")
        report["ortho_nodata_fraction"] = round(float(a.mask.mean()) if np.ndim(a.mask) else 0.0, 4)

    # 6/7. DEM: elevation + hillshade, slope classes
    with rasterio.open(RAW / "usgs" / "gale_dem_1m_site.tif") as d:
        dem = d.read(1, masked=True)
        tr = d.transform
        b = d.bounds
        dem_ext = [math.degrees(b.left / R), math.degrees(b.right / R),
                   math.degrees(b.bottom / R), math.degrees(b.top / R)]
        # sample DEM at rover stops inside box: residual vs rover-reported elevation
        inside = pts[[BOX.contains(x, y) for x, y in pts[:, :2]]]
        xs, ys = R * np.radians(inside[:, 0]), R * np.radians(inside[:, 1])
        cols = ((xs - tr.c) / tr.a).astype(int)
        rows = ((ys - tr.f) / tr.e).astype(int)
        ok = (rows >= 0) & (rows < d.height) & (cols >= 0) & (cols < d.width)
        samp = dem[rows[ok], cols[ok]]
        resid = (samp - inside[ok, 3]).compressed() if np.ma.isMaskedArray(samp) else samp - inside[ok, 3]
    fill = dem.filled(np.nan).astype("float64")
    report["dem"] = {
        "shape": list(dem.shape),
        "nodata_fraction": round(float(np.isnan(fill).mean()), 5),
        "elevation_min_m": round(float(np.nanmin(fill)), 1),
        "elevation_max_m": round(float(np.nanmax(fill)), 1),
        "rover_stops_compared": int(resid.size),
        "dem_minus_rover_elev_mean_m": round(float(np.mean(resid)), 2),
        "dem_minus_rover_elev_std_m": round(float(np.std(resid)), 2),
        "dem_minus_rover_elev_abs_max_m": round(float(np.max(np.abs(resid))), 2),
    }
    filled = np.where(np.isnan(fill), np.nanmean(fill), fill)
    ls = LightSource(azdeg=315, altdeg=40)
    shade = ls.hillshade(filled, vert_exag=2, dx=1, dy=1)

    fig, ax = new_ax("DEM 1 m: elevation over hillshade, rover track on top")
    ax.imshow(shade, extent=dem_ext, cmap="gray")
    im = ax.imshow(fill, extent=dem_ext, cmap="terrain", alpha=0.55)
    fig.colorbar(im, ax=ax, shrink=0.6, label="elevation (m)")
    draw_track(ax, lines, pts, BOX)
    ax.set_xlim(BOX.west, BOX.east), ax.set_ylim(BOX.south, BOX.north)
    scalebar(ax, BOX, 500)
    save(fig, "06_site_dem_elevation.jpg")

    # slope on a 2 m grid (block mean), the resolution the route planner will use
    h2, w2 = filled.shape[0] // 2 * 2, filled.shape[1] // 2 * 2
    g2 = filled[:h2, :w2].reshape(h2 // 2, 2, w2 // 2, 2).mean(axis=(1, 3))
    dzdy, dzdx = np.gradient(g2, 2.0)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    bounds = [0, 10, 15, 20, 30, 90]
    cmap = ListedColormap(["#2e8b57", "#f2d43d", "#f28c28", "#d7301f", "#5b0a0a"])
    fig, ax = new_ax("Slope on 2 m grid. Route planner closes cells above 20 deg")
    ax.imshow(ls.hillshade(g2, vert_exag=2, dx=2, dy=2), extent=dem_ext, cmap="gray")
    im = ax.imshow(slope, extent=dem_ext, cmap=cmap, norm=BoundaryNorm(bounds, cmap.N), alpha=0.55)
    cb = fig.colorbar(im, ax=ax, shrink=0.6, label="slope (deg)")
    cb.set_ticks(bounds)
    draw_track(ax, lines, pts, BOX)
    ax.set_xlim(BOX.west, BOX.east), ax.set_ylim(BOX.south, BOX.north)
    scalebar(ax, BOX, 500)
    save(fig, "07_site_slope.jpg")
    report["slope_2m"] = {f"{lo}-{hi}_deg_fraction": round(float(((slope >= lo) & (slope < hi)).mean()), 4)
                          for lo, hi in zip(bounds[:-1], bounds[1:])}

    # 8. detail: same 300 m patch around the reference-sol stop in each optical source
    ref = pts[np.argmin(np.abs(pts[:, 2] - REF_SOL))]
    half_m = 150
    dlon = half_m / (R * math.pi / 180 * math.cos(math.radians(ref[1])))
    dlat = half_m / (R * math.pi / 180)
    patch = BBox(ref[0] - dlon, ref[1] - dlat, ref[0] + dlon, ref[1] + dlat)
    panels = [("Trek HiRISE z16 (0.64 m)", stitch_trek("curiosity_hirise_mosaic", 16, patch), None)]
    for name, label in [("gale_hirise_color_25cm_site.tif", "USGS colour (25 cm)"),
                        ("gale_ortho_25cm_site.tif", "USGS ortho (25 cm)")]:
        if not (RAW / "usgs" / name).exists():
            continue
        with rasterio.open(RAW / "usgs" / name) as d:
            win = rasterio.windows.from_bounds(R * math.radians(patch.west), R * math.radians(patch.south),
                                               R * math.radians(patch.east), R * math.radians(patch.north),
                                               d.transform).round_offsets().round_lengths()
            arr = d.read(window=win)
        img = np.moveaxis(arr, 0, -1) if arr.shape[0] == 3 else arr[0]
        panels.append((label, (img, [patch.west, patch.east, patch.south, patch.north]),
                       None if arr.shape[0] == 3 else "gray"))
    fig, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 6.4), dpi=150)
    for ax, (label, (img, ext), cm) in zip(np.atleast_1d(axes), panels):
        ax.imshow(img, extent=ext, cmap=cm, interpolation="nearest")
        ax.scatter([ref[0]], [ref[1]], marker="+", s=200, color="cyan")
        ax.set_title(f"{label}", fontsize=10)
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(f"Same 300 x 300 m patch at the sol {int(ref[2])} rover stop (cyan cross)", fontsize=12)
    save(fig, "08_detail_resolution_compare.jpg")

    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
