"""Sample the public USFS California 2022 canopy cache at its native zoom."""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
import argparse
import json

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
URL = "https://tiles.arcgis.com/tiles/gGHDlz6USftL5Pau/arcgis/rest/services/UrbanTreeCanopy_CA2022/MapServer"
ZOOM = 18
NODATA = 255


def pixels(points):
    points = np.asarray(points, dtype=float).reshape(-1, 2)
    if not np.isfinite(points).all() or (np.abs(points[:, 1]) >= 85).any():
        raise ValueError("Points must be finite longitude/latitude pairs below 85° latitude")
    size = 256 * 2**ZOOM
    lon, lat = points.T
    x = (lon + 180) / 360 * size
    y = (1 - np.arcsinh(np.tan(np.radians(lat))) / np.pi) / 2 * size
    return np.floor(np.column_stack((x, y))).astype(np.int64)


@lru_cache(maxsize=768)
def read_mask(path):
    with Image.open(path) as image:
        if image.mode != "P" or image.size != (256, 256):
            raise ValueError(f"Unexpected canopy image: {path}")
        mask = np.array(image, dtype=np.uint8)
        if not np.isin(mask, (0, 1)).all() or image.info.get("transparency") != 0:
            raise ValueError(f"Unexpected canopy palette: {path}")
        return mask


class Canopy:
    def __init__(self, cache=ROOT / "data/source/canopy", workers=8):
        self.cache = Path(cache)
        self.workers = workers

    def path(self, x, y):
        return self.cache / str(ZOOM) / str(y) / f"{x}.png"

    def fetch(self, tile):
        x, y = map(int, tile)
        path = self.path(x, y)
        absent = path.with_suffix(".missing.json")
        if path.exists():
            return "cached"
        if absent.exists():
            return "missing"
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{URL}/tile/{ZOOM}/{y}/{x}"
        try:
            with urlopen(url, timeout=30) as response:
                data = response.read()
        except HTTPError as error:
            if error.code != 404:
                raise
            absent.write_text(json.dumps({"status": 404, "url": url}))
            return "missing"
        with Image.open(BytesIO(data)) as image:
            if image.mode != "P" or image.size != (256, 256):
                raise ValueError(f"Unexpected canopy tile from {url}")
            if not np.isin(np.asarray(image), (0, 1)).all():
                raise ValueError(f"Unexpected canopy classes from {url}")
        path.write_bytes(data)
        return "downloaded"

    def ensure(self, points):
        tiles = np.unique(pixels(points) // 256, axis=0)
        stats = {"tiles": len(tiles), "cached": 0, "downloaded": 0, "missing": 0}
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for result in pool.map(self.fetch, tiles):
                stats[result] += 1
        return stats

    def sample_many(self, points):
        positions = pixels(points)
        tiles, groups = np.unique(positions // 256, axis=0, return_inverse=True)
        values = np.full(len(positions), NODATA, dtype=np.uint8)
        order = np.argsort(groups)
        counts = np.bincount(groups)
        start = 0
        for (x, y), count in zip(tiles, counts):
            selected = order[start : start + count]
            start += count
            path = self.path(x, y)
            if not path.exists():
                if not path.with_suffix(".missing.json").exists():
                    raise FileNotFoundError(f"Call ensure(points) before sampling: {path}")
                continue
            mask = read_mask(path)
            local = positions[selected] % 256
            values[selected] = mask[local[:, 1], local[:, 0]]
        return values

    def sample(self, lon, lat):
        return int(self.sample_many([[lon, lat]])[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("roads", type=Path, help="LineString road GeoJSON; download canopy at road vertices")
    args = parser.parse_args()
    roads = json.loads(args.roads.read_text())
    points = [point for feature in roads["features"] for point in feature["geometry"]["coordinates"]]
    canopy = Canopy()
    print(json.dumps(canopy.ensure(points)))
    values, counts = np.unique(canopy.sample_many(points), return_counts=True)
    print(json.dumps({int(value): int(count) for value, count in zip(values, counts)}))
