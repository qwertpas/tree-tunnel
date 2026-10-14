Build a minimal static browser map of candidate tree tunnels for [AREA]. Choose street data and high-resolution canopy data (or derive canopy from aerial imagery), considering coverage, age, resolution, licensing, and availability elsewhere. Intersect canopy with streets, estimate road widths, and score sustained canopy along and across the road; choose thresholds and minimum lengths that exclude nearby trees and planted medians. Study published tree-tunnel images, inspect a varied sample of candidates and rejected streets using available aerial and street-level imagery (vision models may assist), and iteratively improve datasets and filters based on observed errors. Preserve source details, image credits, and review results, distinguishing candidates from verified tunnels. Show candidates on a clean interactive map with coverage filtering, contrasting aerial-mode colors, Google Street View links, and hover photos where available. Use static assets and relative paths, and verify the data and browser interactions. Adapt the approach to local conditions; [Tree Tunnel](https://github.com/qwertpas/tree-tunnel) is an implementation example.

# Tree Tunnel

Static candidate map for Santa Barbara, Goleta, Isla Vista, and Montecito.

```sh
python3.11 -m http.server 8765 --bind 127.0.0.1
```

Open http://127.0.0.1:8765/. The browser loads local GeoJSON and photos. It needs internet access for Leaflet and map tiles. GitHub Pages can serve the same files.

Click a candidate street to open Google Street View near that point in a new tab. The hover popup also includes a Street View link. This uses public Maps URLs and requires no Google API key.

## Data

- [USFS / CAL FIRE California Urban Tree Canopy](https://urban-and-community-forestry-calfire-forestry.hub.arcgis.com/pages/california-urban-tree-canopy-data): binary canopy classified from 2022 NAIP aerial imagery at 0.6 m resolution. Covers Census-designated urban areas, including Santa Barbara and Goleta. Source details and the official county download are in `data/source/canopy.json`.
- [OpenStreetMap](https://www.openstreetmap.org/copyright): streets, named pedestrian streets, access restrictions, width and lane tags. Named private neighborhood streets are included and marked private. Unnamed parking access and driveways are excluded. ODbL attribution applies to the street-derived layer. Exact snapshot and tag availability are in `data/source/roads.json`.
- [KartaView](https://kartaview.org/): geotagged street photos, CC BY-SA 4.0, credited to Grab and KartaView Contributors. Capture dates, orientation, and inspection results are preserved.
- [USGS The National Map](https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer): public-domain CONUS NAIP aerial samples. The service describes 2017–2021 imagery; individual capture dates were not established.

The equivalent EarthDefine 0.6 m canopy product covers the contiguous US commercially. Public nationwide 30 m canopy products are too coarse for this filter. The processing approach transfers to other places with detailed canopy data.

## Rebuild

```sh
python3.11 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/roads.py
.venv/bin/python scripts/build.py --initial
.venv/bin/python scripts/photos.py
```

The map samples streets every 4 m and samples 11 locations across each estimated pavement width. Width comes from OSM, then lane count, then a street-class estimate. Candidate runs require at least 35% centre canopy, 20% canopy at both edges, and 40% canopy across the width in a nine-sample window. Gaps up to 8 m are joined; resulting stretches must be at least 40 m. Unavailable canopy data cannot bridge a candidate run. Coverage is sampled canopy fraction, not a probability of being a tunnel.

`scripts/review.py` acquired the original eight aerial spot-checks. Their observations are saved in `data/review-aerial.json`; street-level observations and published reference links are in `data/review.json`. The original Census street baseline is retained in the `*-tiger*` files. It exposed planted-median and phantom-road errors, leading to the OSM replacement and across-width filter.

These are candidates rather than current field-confirmed tunnels. Canopy classification, road geometry, estimated widths, and imagery age can introduce errors. Photos of adjacent trails and bridges are labeled accordingly. The prototype does not include real-estate listings yet.

For publication, serve `index.html`, `style.css`, `app.js`, `data/config.json`, `data/candidates.geojson`, `data/photos.geojson`, and `data/photos/`, preserving photo credits. Raw street snapshots, cached canopy tiles, review artifacts, and `.venv` are unnecessary. There is no application backend, API key, or runtime classification service.
