"""Fetch public NAIP aerial images for a reproducible filter spot-check."""

import json
from pathlib import Path

import numpy as np
import requests
from pyproj import Transformer
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
URL = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
PROJECT = Transformer.from_crs(4326, 3857, always_xy=True).transform
UNPROJECT = Transformer.from_crs(3857, 4326, always_xy=True).transform


def main():
    final = json.loads((ROOT / "data/candidates-tiger.geojson").read_text())["features"]
    initial = json.loads((ROOT / "data/candidates-tiger-nearby.geojson").read_text())["features"]
    samples = []
    for name in ["Mathilda Dr", "E Anapamu St", "Las Olas Dr", "Moore Rd"]:
        samples.append(next(f for f in final if f["properties"]["name"] == name))
    for name in ["N Hope Ave", "N Milpas St", "Pardall Rd", "Yaple Ave"]:
        choices = [f for f in initial if f["properties"]["name"] == name]
        samples.append(min(choices, key=lambda f: f["properties"]["score"]))
    records = []
    for i, feature in enumerate(samples):
        line = shape(feature["geometry"])
        point = line.interpolate(.5, normalized=True)
        x, y = PROJECT(point.x, point.y)
        size = 190 / np.cos(np.radians(point.y))
        bbox = [x - size, y - size, x + size, y + size]
        params = {"bbox": ",".join(map(str, bbox)), "bboxSR": 3857,
                  "imageSR": 3857, "size": "800,800", "format": "png", "f": "image"}
        filename = f"aerial-{i + 1}.png"
        path = ROOT / "data/photos" / filename
        response = requests.get(URL, params=params, timeout=40)
        response.raise_for_status()
        if not response.headers["content-type"].startswith("image/"):
            raise ValueError(response.text)
        path.write_bytes(response.content)
        records.append({
            "id": f"aerial-{i + 1}", "candidate_id": feature["properties"]["id"],
            "name": feature["properties"]["name"], "coordinates": [point.x, point.y],
            "file": f"data/photos/{filename}", "bbox_3857": bbox,
            "geometry": feature["geometry"], "score": feature["properties"]["score"],
            "retained": i < 4, "source_url": response.url,
            "credit": "USDA / USGS The National Map", "license": "Public domain · CONUS NAIP",
            "date": "2017–2021 imagery", "observation": "",
        })
        print(feature["properties"]["name"], feature["properties"]["score"], flush=True)
    (ROOT / "data/review-aerial.json").write_text(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
