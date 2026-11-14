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
| `fetch_trek_tiles.py` | NASA Mars Trek WMTS | `data/raw/trek/<layer>/<z>/<row>/<col>.png` | about 55 MB |
| `fetch_usgs_rasters.py` | USGS Astrogeology Gale mosaics | `data/raw/usgs/*.tif` cropped to the site box | about 370 MB |
| `fetch_msl.py` | mars.nasa.gov MMGIS, REMS feed, raw-image API | `data/raw/msl/` | about 22 MB |
| `fetch_space_weather.py` | NASA CCMC DONKI | `data/raw/donki/*.json` | small |

Trek tiles skip files already on disk, so an interrupted run can be restarted.

What each output directory and file contains is described in `data/README.md`.

## Notes on fetching

- The 25 cm orthophoto is a 50 GB uncompressed file. `fetch_usgs_rasters.py` reads only the needed
  bytes of each row with HTTP range requests.
- DONKI's FLR endpoint returned 404 on 14 Nov 2026, so the script skips it.

## Verify

```sh
../../.venv/bin/python make_previews.py
```

Writes figures and `report.json` to `docs/verification/`. Every figure is in lon/lat with the rover
track on top, so a layer that is misregistered shows the track drifting off the terrain.
