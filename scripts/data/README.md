# Data pipeline

Scripts that fetch NASA and USGS data for the Marswalk Planner site. The site box, context box,
reference sol and storm window live in `data/site.json`; every script reads it from there.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/data/requirements.txt
```

## Run

```sh
cd scripts/data
../../.venv/bin/python fetch_all.py           # everything, in order
../../.venv/bin/python fetch_trek_tiles.py    # one step at a time
```

Set `NASA_API_KEY` (free at api.nasa.gov) before `fetch_space_weather.py` to avoid the DEMO_KEY rate limit.

| Script | Source | Output | Size |
|---|---|---|---|
| `fetch_trek_tiles.py` | NASA Mars Trek WMTS | `data/raw/trek/<layer>/<z>/<row>/<col>.png` | about 50 MB |
| `fetch_usgs_rasters.py` | USGS Astrogeology Gale mosaics | `data/raw/usgs/*.tif` cropped to the site box | about 450 MB |
| `fetch_msl.py` | mars.nasa.gov MMGIS, REMS feed, raw-image API | `data/raw/msl/` | about 22 MB |
| `fetch_space_weather.py` | NASA CCMC DONKI | `data/raw/donki/*.json` | small |

Trek tiles skip files already on disk, so an interrupted run can be restarted.

## Layout

```
data/
  site.json          site definition, shared with the app
  curated/           hand-entered values with citations (tracked in git)
  raw/               fetched data, verbatim or cropped; gitignored except SOURCE.json
    trek/            map tiles per layer
    usgs/            DEM, orthophoto and colour mosaic crops (GeoTIFF)
    msl/             rover stops, rover track, REMS weather, raw-image index
    donki/           space-weather records for the storm window
```

Every folder under `data/raw` has a `SOURCE.json` with the source URL, retrieval time, counts and notes.

## Notes on sources

- Trek tiles use Mars equirectangular (EPSG:104905). Two 256 px tiles cover the planet at zoom 0;
  row 0 is at the north pole. Leaflet's `L.CRS.EPSG4326` requests the same grid as `{z}/{y}/{x}`.
- The USGS GeoTIFFs use a Mars sphere (R = 3,396,190 m), equirectangular with center longitude 0.
  Metres convert to degrees as `deg = m / R * 180 / pi`.
- The 25 cm orthophoto is a 50 GB uncompressed file. `fetch_usgs_rasters.py` reads only the needed
  bytes of each row with HTTP range requests.
- The raw-image index has no camera pointing and no rover site or drive. Match images to places by sol,
  using the rover stops in `waypoints.geojson`.
- The REMS feed has blank wind and humidity fields.
- DONKI's FLR endpoint returned 404 on 14 Nov 2026, so the script skips it.

## Verify

```sh
../../.venv/bin/python make_previews.py
```

Writes figures and `report.json` to `docs/verification/`. Every figure is in lon/lat with the rover
track on top, so a layer that is misregistered shows the track drifting off the terrain.
