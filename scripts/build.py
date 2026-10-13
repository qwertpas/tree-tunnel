"""Intersect street corridors with 2022 canopy and write static map data."""

import argparse
import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely import normalize, transform
from shapely.geometry import box, mapping, shape
from shapely.ops import substring

from canopy import Canopy, NODATA
from roads import BOUNDS

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Transformer.from_crs(4326, 32611, always_xy=True).transform
UNPROJECT = Transformer.from_crs(32611, 4326, always_xy=True).transform
OFFSETS = np.linspace(-1, 1, 11)
STEP = 4


def road_width(properties):
    if properties.get("width"):
        return properties["width"]
    if properties.get("lanes"):
        return properties["lanes"] * 3.3 + 2
    return {"residential": 10, "living_street": 6, "unclassified": 8,
            "tertiary": 14, "secondary": 18, "primary": 24, "service": 7,
            "pedestrian": 8}[properties["highway"]]


def write(path, data):
    path.write_text(json.dumps(data, separators=(",", ":")))


def prepare():
    source = json.loads((ROOT / "data/source/roads.geojson").read_text())
    coverage = shape(json.loads((ROOT / "data/source/canopy_coverage.geojson").read_text())["features"][0]["geometry"])
    region = box(*BOUNDS).intersection(coverage)
    roads, points, seen = [], [], set()
    for feature in source["features"]:
        line = shape(feature["geometry"]).intersection(region)
        parts = list(line.geoms) if line.geom_type in {"MultiLineString", "GeometryCollection"} else [line]
        for part, line in enumerate(parts):
            if line.is_empty or line.geom_type != "LineString":
                continue
            key = normalize(line).wkb
            if key in seen:
                continue
            seen.add(key)
            line = transform(line, PROJECT, interleaved=False)
            if line.length < 35:
                continue
            distances = np.linspace(0, line.length, int(np.ceil(line.length / STEP)) + 1)
            centers = np.array([line.interpolate(d).coords[0] for d in distances])
            before = np.array([line.interpolate(max(0, d - 2)).coords[0] for d in distances])
            after = np.array([line.interpolate(min(line.length, d + 2)).coords[0] for d in distances])
            direction = after - before
            normals = np.column_stack((-direction[:, 1], direction[:, 0]))
            normals /= np.linalg.norm(normals, axis=1)[:, None]
            width = road_width(feature["properties"])
            samples = (centers[:, None, :] + normals[:, None, :] * (OFFSETS * width / 2)[None, :, None]).reshape(-1, 2)
            lon, lat = UNPROJECT(samples[:, 0], samples[:, 1])
            points.append(np.column_stack((lon, lat)))
            roads.append((feature["properties"], part, line, distances))
    points = np.concatenate(points)
    print(f"Sampling {len(roads)} road sections at {len(points):,} points", flush=True)
    canopy = Canopy()
    print(canopy.ensure(points), flush=True)
    values = canopy.sample_many(points)
    print(f"Missing samples: {np.count_nonzero(values == NODATA):,}", flush=True)
    return roads, values


def smooth(values, width=9):
    weights = np.ones(width)
    return np.convolve(values, weights, "same") / np.convolve(np.ones(len(values)), weights, "same")


def runs(selected, known):
    selected = selected.copy()
    start = None
    for i, good in enumerate(selected):
        if not good and start is None:
            start = i
        elif good and start is not None:
            if start > 0 and i - start <= 2 and known[start:i].all():
                selected[start:i] = True
            start = None
    edges = np.diff(np.r_[False, selected, False].astype(int))
    return zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))


def build(roads, values, nearby=False):
    features = []
    offset = 0
    for properties, part, line, distances in roads:
        count = len(distances)
        mask = values[offset:offset + count * len(OFFSETS)].reshape(count, -1)
        offset += mask.size
        known = (mask != NODATA).all(axis=1)
        trees = (mask == 1).astype(float)
        center = trees[:, 4:7].mean(axis=1)
        left = trees[:, :3].mean(axis=1)
        right = trees[:, -3:].mean(axis=1)
        sides = np.minimum(left, right)
        across = trees.mean(axis=1)
        if nearby:
            selected = known & (smooth(trees.mean(axis=1)) >= .30)
        else:
            selected = known & (smooth(center) >= .35) & (smooth(sides) >= .20) & (smooth(across) >= .40)
        for start, end in runs(selected, known):
            # Half a sample interval gives each observation a finite street length.
            first = max(0, distances[start] - STEP / 2)
            last = min(line.length, distances[end - 1] + STEP / 2)
            if last - first < 40:
                continue
            geometry = transform(substring(line, first, last), UNPROJECT, interleaved=False)
            canopy = float(center[start:end].mean())
            both_sides = float(sides[start:end].mean())
            road_canopy = float(across[start:end].mean())
            name = properties.get("name", "Unnamed road")
            features.append({
                "type": "Feature", "geometry": mapping(geometry),
                "properties": {
                    "id": f'{properties["id"]}-{part}-{start}', "name": name,
                    "road_id": properties["id"], "highway": properties["highway"],
                    "access": properties.get("access"),
                    "score": round(road_canopy, 3),
                    "coverage": round(canopy, 3), "side_coverage": round(both_sides, 3),
                    "road_coverage": round(road_canopy, 3), "road_width_m": round(road_width(properties), 1),
                    "length_m": round(last - first), "sample_count": int(end - start),
                    "status": "candidate", "area": "Santa Barbara area",
                },
            })
    features.sort(key=lambda f: f["properties"]["score"], reverse=True)
    return {"type": "FeatureCollection", "features": features}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", action="store_true", help="Also save the broad nearby-canopy baseline")
    args = parser.parse_args()
    roads, values = prepare()
    candidates = build(roads, values)
    write(ROOT / "data/candidates.geojson", candidates)
    if args.initial:
        initial = build(roads, values, nearby=True)
        write(ROOT / "data/candidates-initial.geojson", initial)
        print(f'Nearby-canopy baseline: {len(initial["features"])} segments', flush=True)
    print(f'Overhead-canopy candidates: {len(candidates["features"])} segments', flush=True)
    write(ROOT / "data/config.json", {
        "bounds": [[BOUNDS[1], BOUNDS[0]], [BOUNDS[3], BOUNDS[2]]],
        "canopy_url": "https://tiles.arcgis.com/tiles/gGHDlz6USftL5Pau/arcgis/rest/services/UrbanTreeCanopy_CA2022/MapServer/tile/{z}/{y}/{x}",
        "canopy_zoom": 18,
        "canopy_attribution": "Canopy © USFS, CAL FIRE, EarthDefine · 2022 NAIP",
    })
    write(ROOT / "data/build.json", {
        "date": "2026-10-12", "street_sections": len(roads), "samples": len(values),
        "missing_samples": int(np.count_nonzero(values == NODATA)),
        "candidates": len(candidates["features"]),
        "length_km": round(sum(f["properties"]["length_m"] for f in candidates["features"]) / 1000, 1),
        "spacing_m": STEP, "cross_samples": len(OFFSETS),
        "road_width": "OSM width; else lane count * 3.3 + 2m; else estimated by street class",
        "window_samples": 9, "center_min": .35, "side_min": .20,
        "across_min": .40,
        "gap_max_m": 8, "length_min_m": 40,
        "score": "Canopy fraction sampled across the estimated pavement width",
    })


if __name__ == "__main__":
    main()
