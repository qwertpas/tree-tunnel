"""Download OpenStreetMap streets with roadway width and lane attributes."""

import json
from pathlib import Path
import re

import osmium
import requests

ROOT = Path(__file__).resolve().parents[1]
BOUNDS = [-119.93, 34.37, -119.52, 34.53]
URL = "https://download.geofabrik.de/north-america/us/california/socal-261012.osm.pbf"
CLASSES = {"primary", "secondary", "tertiary", "unclassified", "residential", "living_street", "service", "pedestrian"}


def width(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(m|ft|feet)?", value or "")
    if not match:
        return None
    meters = float(match[1]) * (.3048 if match[2] in {"ft", "feet"} else 1)
    return meters if meters > 0 else None


def download():
    folder = ROOT / "data/source"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "roads-socal.osm.pbf"
    region = folder / "roads-osm-region.json"
    west, south, east, north = BOUNDS
    if not region.exists():
        if not source.exists():
            temporary = source.with_suffix(".pbf.part")
            with requests.get(URL, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                with temporary.open("wb") as file:
                    for chunk in response.iter_content(4 * 1024 * 1024):
                        file.write(chunk)
            temporary.rename(source)
        with osmium.io.Reader(str(source), osmium.osm.NOTHING) as reader:
            timestamp = reader.header().get("osmosis_replication_timestamp")
        print("Caching Santa Barbara street inputs from the OSM snapshot", flush=True)
        streets = osmium.FileProcessor(source).with_locations().with_filter(
            osmium.filter.EntityFilter(osmium.osm.WAY)).with_filter(
            osmium.filter.TagFilter(*[("highway", road) for road in sorted(CLASSES)]))
        ways = []
        for item in streets:
            coordinates = [[node.location.lon, node.location.lat] for node in item.nodes]
            if len(coordinates) < 2:
                continue
            lon, lat = zip(*coordinates)
            if max(lon) < west or min(lon) > east or max(lat) < south or min(lat) > north:
                continue
            ways.append({"id": item.id, "tags": dict(item.tags), "coordinates": coordinates})
        region.write_text(json.dumps({"snapshot": timestamp, "bounds": BOUNDS,
                                      "classes": sorted(CLASSES), "ways": ways}, separators=(",", ":")))
    data = json.loads(region.read_text())
    if data["bounds"] != BOUNDS or data["classes"] != sorted(CLASSES):
        raise ValueError("Delete roads-osm-region.json to rebuild the cache for changed bounds or classes")
    roads = []
    for item in data["ways"]:
        tags = item["tags"]
        pedestrian = tags["highway"] == "pedestrian"
        if tags.get("access") == "no":
            continue
        access_keys = ("access", "foot") if pedestrian else ("access", "vehicle", "motor_vehicle", "motorcar")
        private = any(tags.get(key) == "private" for key in access_keys)
        if private and (not tags.get("name") or tags["highway"] not in {"residential", "service", "pedestrian"}):
            continue
        if pedestrian:
            if not tags.get("name") or tags.get("area") == "yes" or tags.get("foot") == "no":
                continue
        elif any(tags.get(key) == "no" for key in ("vehicle", "motor_vehicle", "motorcar")):
            continue
        if tags["highway"] == "service":
            if tags.get("service") in {"parking_aisle", "driveway", "drive-through", "emergency_access"}:
                continue
            if not tags.get("name") and tags.get("service") != "alley":
                continue
        lanes = tags.get("lanes", "")
        roads.append({
            "type": "Feature", "geometry": {"type": "LineString", "coordinates": item["coordinates"]},
            "properties": {
                "id": f'osm-{item["id"]}', "name": tags.get("name", "Unnamed road"),
                "highway": tags["highway"], "width": width(tags.get("width")),
                "access": "private" if private else tags.get("access"),
                "lanes": int(lanes) if lanes.isdigit() and int(lanes) > 0 else None,
                "oneway": tags.get("oneway") in {"yes", "1", "-1"}, "tags": tags,
            },
        })
    # Retain the nationwide Census baseline for the data-selection comparison.
    for extension in ("geojson", "json"):
        old = folder / f"roads.{extension}"
        census = folder / f"roads-tiger.{extension}"
        if old.exists() and not census.exists():
            census.write_bytes(old.read_bytes())
    result = folder / "roads-next.geojson"
    result.write_text(json.dumps({
        "type": "FeatureCollection", "features": roads,
    }, separators=(",", ":")))
    result.replace(folder / "roads.geojson")
    (folder / "roads.json").write_text(json.dumps({
        "name": "OpenStreetMap streets", "url": URL, "provider": "Geofabrik Southern California extract",
        "license": "Open Database License (ODbL)", "attribution": "© OpenStreetMap contributors",
        "license_url": "https://www.openstreetmap.org/copyright", "bounds": BOUNDS,
        "classes": sorted(CLASSES), "roads": len(roads), "snapshot": data["snapshot"],
        "exclusions": ["Access explicitly denied", "Unnamed private ways and private ways outside residential/service/pedestrian classes",
                       "Motor access denied on vehicle roads",
                       "Pedestrian areas, unnamed pedestrian ways, denied pedestrian foot access",
                       "Parking aisles, driveways, drive-throughs, emergency access",
                       "Unnamed service ways except explicit alleys"],
        "pedestrian_policy": "Named pedestrian street corridors remain eligible when cars are prohibited",
        "private_policy": "Named private residential, service and pedestrian streets remain eligible and are marked private",
        "private_streets": sum(r["properties"]["access"] == "private" for r in roads),
        "regional_cache": "data/source/roads-osm-region.json",
        "width_tagged": sum(r["properties"]["width"] is not None for r in roads),
        "lanes_tagged": sum(r["properties"]["lanes"] is not None for r in roads),
    }, indent=2))
    print(f"Downloaded {len(roads)} OpenStreetMap road sections", flush=True)


if __name__ == "__main__":
    download()
