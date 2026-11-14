# Data

What each directory under `data/` holds, its format, and what to watch for. All data covers one site:
the boxwork ridge field on Mount Sharp, Gale Crater, Mars.

Coordinates are planetocentric latitude and east-positive longitude in degrees, unless a section says otherwise.
Everything in `raw/` was retrieved on 14 November 2026.

```
data/
├── site.json            site definition: boxes, reference sol, storm window
├── curated/             values entered by hand, with citations (tracked in git)
│   └── rad_published_values.json
└── raw/                 fetched data (gitignored except SOURCE.json files)
    ├── trek/            map tiles from NASA Mars Trek, one folder per layer
    ├── usgs/            USGS Gale terrain and image mosaics, cropped to the site (GeoTIFF)
    ├── msl/             Curiosity rover: stops, track, weather, raw-image index
    └── donki/           space-weather records for the May 2024 solar storm
```

## Getting the data

`raw/` is not in git, except one `SOURCE.json` per folder. To rebuild it (about 450 MB, roughly half an hour):

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/data/requirements.txt
cd scripts/data && ../../.venv/bin/python fetch_all.py
```

Each `SOURCE.json` records the source URLs, retrieval time, file count, total bytes and notes for its folder.
See `scripts/data/README.md` for the individual scripts.

## `site.json`

The one site definition. Every fetch script reads it, and the app will too. To move the site, edit this
file and rerun the fetch scripts.

| Field | Value | Meaning |
|---|---|---|
| `center` | 137.381°E, 4.808°S | Middle of the boxwork ridge field |
| `site_bbox` | 137.3556 to 137.4064°E, 4.8333 to 4.7827°S | 3 x 3 km analysis box. Site tiles and all USGS crops use it. |
| `context_bbox` | 136.2768 to 139.3864°E, 7.2137 to 3.5805°S | Gale Crater and surroundings. Context tiles use it. |
| `reference_sol` | 4600 | Default day for weather and photos (15 July 2025) |
| `storm_window` | 2024-05-19 to 2024-05-22 | Date range for the DONKI records |
| `mars_radius_m` | 3396190 | Sphere radius used by the USGS products |

## `curated/`

### `rad_published_values.json`

Radiation figures from Curiosity's RAD instrument, taken from papers and NASA releases. Each value has a
unit, a source and a status. The app's radiation model uses these until a RAD time series is loaded.

| Key | Value | Source |
|---|---|---|
| `background_absorbed_dose` | 0.21 mGy/day | Hassler et al. 2014 |
| `background_dose_equivalent` | 0.64 mSv/day | Hassler et al. 2014 |
| `storm_2024_05_20_dose` | 8,100 µGy | NASA release, June 2024 |
| `typical_daily_dose_press` | 700 µGy/day | Press coverage of the same release |
| `terrain_shielding_murray_buttes` | 5% lower dose with 19% of sky hidden, against 10% | Guo et al. 2021 |
| `albedo_dose_fraction_flat_terrain` | 19% of total surface dose | Guo et al. 2021 |

Open issues, also recorded in the file:

- The two Hassler values were entered from memory. Check them against the paper.
- The press figure of 700 µGy/day is three times the Hassler absorbed dose. This changes the storm from
  39 quiet days of dose to 12. Resolve this before building the radiation model.

## `raw/trek/`

Map tiles from the NASA Mars Trek WMTS service.

| Folder | Instrument | Covers | Zoom levels | Tiles | Pixel size at top zoom | Size |
|---|---|---|---|---|---|---|
| `curiosity_hirise_mosaic/` | MRO HiRISE | site box | 12 to 16 | 533 | 0.64 m | 23 MB |
| `curiosity_ctx_mosaic/` | MRO CTX | context box | 6 to 10 | 562 | 41 m | 22 MB |
| `THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018/` | Mars Odyssey THEMIS, night infrared | context box | 5 to 9 | 168 | 81 m (source data 100 m) | 9 MB |

- **Path:** `<layer>/<z>/<row>/<col>.png`
- **Format:** 256 x 256 PNG, grayscale with alpha.
- **Grid:** Mars equirectangular (EPSG:104905), in degrees. At zoom 0, two tiles cover the planet.
  Row 0 is at the north pole and column 0 is at 180°W. Each tile spans `180 / 2^z` degrees.

  ```
  size = 180 / 2**z
  col  = floor((lon + 180) / size)
  row  = floor((90 - lat) / size)
  ```

- **Leaflet:** `L.CRS.EPSG4326` requests the same grid, so its `{z}/{y}/{x}` maps to `{z}/{row}/{col}` directly.
- **Night infrared:** bright means warm at night, which means rock or consolidated ground. Dark means loose,
  fine material. The site box is only about 40 pixels wide in this layer, so it shows Mount Sharp's units,
  not features inside the box.

## `raw/usgs/`

Crops of three USGS Astrogeology Gale mosaics, cut to the site box. Only the needed bytes were read from
the source files, which are 3.9 GB, 50 GB and 1 GB.

| File | Contents | Size in pixels | Pixel size | Data type | Size |
|---|---|---|---|---|---|
| `gale_dem_1m_site.tif` | Terrain heights (DEM) | 3011 x 2999 | 1 m | float32, metres, nodata −32767 | 14 MB |
| `gale_ortho_25cm_site.tif` | Grayscale orthophoto | 12045 x 11997 | 0.25 m | uint8, nodata 0 | 86 MB |
| `gale_hirise_color_25cm_site.tif` | HiRISE colour mosaic | 12045 x 11997 | 0.25 m | uint8 RGB, no nodata | 267 MB |

All three files:

- **Projection:** Mars equirectangular, center longitude 0, sphere radius 3,396,190 m. Coordinates are in
  metres. Convert with `lon = x / R * 180 / pi` and `lat = y / R * 180 / pi`.
- **Storage:** deflate compression, 512 x 512 internal tiles. Open them with rasterio or GDAL.
- **Extent:** 137.3556 to 137.4064°E, 4.8333 to 4.7827°S. The orthophoto and the colour mosaic share one pixel
  grid. One DEM cell covers 4 x 4 image pixels, and the DEM edges are within 1 m of the image edges.
- **Coverage:** no missing pixels inside the box.

**`gale_dem_1m_site.tif`**

- Heights run from −3,992 m to −3,310 m.
- They match Curiosity's `elev_geoid` within 0.07 m at all 194 rover stops in the box, so read them as heights
  above the Mars areoid. The rover heights were probably taken from this same DEM. The match proves the crop
  is in the right place; it does not prove the DEM is accurate.
- Built from HRSC, CTX and HiRISE terrain models tied to MOLA. USGS lists its status as "In Work".
- Slope, roughness, ridge/hollow and sky-view layers will be derived from this file.

**`gale_ortho_25cm_site.tif`**

- The sharpest image that covers the whole box. Use it as the detailed base map.
- Thin seam lines show where two HiRISE images meet.

**`gale_hirise_color_25cm_site.tif`**

- True-colour-like HiRISE mosaic, same grid as the orthophoto.
- A strip about 200 m wide near the west edge has no colour; the mosaic fills it with grayscale. It slants from
  about 137.358°E at the north edge to about 137.366°E at the south edge.
- It has the same seam lines as the orthophoto.

Citations: Calef, F.J. III and Parker, T., 2016, MSL Gale Merged DEM and MSL Gale Merged Orthophoto Mosaic,
PDS Annex, USGS. Colour mosaic: USGS Astrogeology Science Center.

## `raw/msl/`

Data from the Curiosity rover (Mars Science Laboratory).

| File | Contents | Records | Size |
|---|---|---|---|
| `waypoints.geojson` | Every rover stop, sol 3 to sol 5073 | 1,389 points | 650 KB |
| `traverse.geojson` | The rover's driven track | 1,317 lines | 1.3 MB |
| `rems_weather.json` | Daily weather from the REMS instrument | 4,745 sols | 1.7 MB |
| `raw_images_index.json` | Raw images taken while the rover was in the site box | 90,464 images | 17 MB |

### `waypoints.geojson`

One GeoJSON point per stop, verbatim from NASA's MMGIS map. Coordinates are `[lon, lat, elevation]`.

| Property | Meaning |
|---|---|
| `sol` | Mars day of the stop |
| `site`, `drive`, `RMC` | Rover location counters. `RMC` is `"<site>_<drive>"`. |
| `lon`, `lat` | Position in degrees |
| `easting`, `northing` | Position in metres, same equirectangular projection as the USGS files |
| `elev_geoid` | Height above the Mars areoid, metres |
| `roll`, `pitch`, `yaw`, `tilt` | Rover attitude, degrees. `yaw_rad` is yaw in radians. |
| `dist_m` | Distance driven since the previous stop, metres |
| `dist_total_m`, `dist_km`, `dist_mi` | Total distance driven since landing |
| `drive_type` | Always `"final"` |

194 stops fall inside the site box, in two visits: sols 4332 to 4752 and sols 4789 to 5073.

### `traverse.geojson`

One MultiLineString per drive, with 3D coordinates, covering the whole mission. The `Length` property is in
metres; all lengths add up to 38.3 km.

### `rems_weather.json`

Verbatim REMS feed. `descriptions` explains each field in English and Spanish. `soles` holds one record per
sol, newest first. Every value is a string, and `"--"` means missing. 250 sols between 1 and 4995 have no record.
The latest record is sol 4995 (25 August 2026).

| Field | Meaning |
|---|---|
| `sol`, `terrestrial_date` | Mars day and Earth date |
| `ls` | Solar longitude in degrees (Mars season) |
| `season` | `"Month 1"` to `"Month 12"` |
| `min_temp`, `max_temp` | Air temperature, °C |
| `min_gts_temp`, `max_gts_temp` | Ground surface temperature, °C |
| `pressure` | Air pressure, Pa. `pressure_string` is `"Higher"` or `"Lower"`, as given by the feed. |
| `atmo_opacity` | Sky condition, for example `"Sunny"` |
| `sunrise`, `sunset` | Local Mars time |
| `local_uv_irradiance_index` | UV level, for example `"Moderate"` |
| `abs_humidity`, `wind_speed`, `wind_direction` | Always `"--"` |

Example, the reference sol 4600: air −81 to −16 °C, ground −103 to −2 °C, 740 Pa, sunny, sunrise 05:47,
sunset 17:30, UV moderate.

The feed's disclaimer says its values are for outreach and that REMS science data is in the PDS. This is
fine for a simulation; say so if the numbers are presented.

### `raw_images_index.json`

An index of raw images for the sols the rover spent in the site box. The images themselves are not downloaded;
each row links to the JPEG on mars.nasa.gov.

The file holds `fields`, `excluded_sample_types`, `cameras`, `sol_ranges` and `rows`. Each row is an array in
`fields` order: `id`, `sol`, `instrument`, `sample_type`, `date_taken` (UTC), `url`, `imageid`.

| Camera (`instrument`) | What it is | Images |
|---|---|---|
| `MAST_LEFT`, `MAST_RIGHT` | Mastcam colour science cameras | 27,783 and 21,536 |
| `NAV_LEFT_B` | Navcam, black-and-white navigation views | 15,671 |
| `MAHLI` | Arm-mounted close-up camera | 14,672 |
| `CHEMCAM_RMI` | ChemCam telescopic close-ups | 9,040 |
| `FHAZ_LEFT_B` | Front hazard camera | 1,762 |

- **`sample_type`:** `full` is a whole frame and `subframe` is a full-resolution crop. Most Mastcam and MAHLI
  images are subframes. `downsampled` is reduced resolution, and `chemcam prc` and `mixed` are as labelled
  by the API. Thumbnails are excluded.
- **Location:** rows have no camera pointing and no site or drive. Join on `sol` with `waypoints.geojson`.
  On a sol with a drive, images come from both ends of the drive, so the position is approximate.
- **Credit:** NASA/JPL-Caltech/MSSS for Mastcam and MAHLI; NASA/JPL-Caltech for Navcam and Hazcam;
  NASA/JPL-Caltech/LANL for ChemCam.

## `raw/donki/`

Verbatim JSON arrays from NASA's DONKI space-weather database, for 19 to 22 May 2024. On 20 May 2024 an X12
flare reached Mars, and Curiosity's RAD recorded its largest dose since landing.

| File | Contents |
|---|---|
| `notifications.json` | 4 alerts: CME alerts issued 20 May 15:52 UTC, 20 May 18:17 UTC and 21 May 18:36 UTC, and a weekly report issued 22 May 20:00 UTC. The text is in `messageBody`. |
| `CME.json` | 19 coronal mass ejections, with analyses and linked events |
| `SEP.json` | Empty: DONKI lists no solar energetic particle events in this window |
| `IPS.json` | Empty: no interplanetary shocks listed |

- The flare endpoint (FLR) was not fetched; it returned HTTP 404 on 14 November 2026.
- The storm dose for the replay comes from `curated/rad_published_values.json`, not from DONKI.
- These were fetched with the rate-limited `DEMO_KEY`.

## Outside `data/`

| Directory | Contents |
|---|---|
| `docs/verification/` | Figures for checking the data by eye, `report.json` with numeric checks, and two full-size stitched site maps. Rebuild with `scripts/data/make_previews.py`. |
| `docs/reference/` | First stitched Trek HiRISE image of the site |
| `docs/` | `marswalk-planner-plan.pdf`, the project plan |
| `scripts/data/` | The fetch and preview scripts |
