"""Build the static layer of reviewed KartaView and NAIP photos."""

import json
from pathlib import Path

import requests
from pyproj import Transformer
from shapely import transform
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parents[1]
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
USGS_LICENSE = "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits"
WORDS = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "st": "street", "rd": "road", "dr": "drive", "ave": "avenue",
    "blvd": "boulevard", "ln": "lane", "ct": "court", "pl": "place",
    "cir": "circle", "pkwy": "parkway", "ter": "terrace", "hwy": "highway",
    "cll": "calle", "cam": "camino",
}


def street_name(name):
    return " ".join(WORDS.get(word, word) for word in name.lower().replace(".", "").split())


def match(lines, point, name):
    matches = [(line.distance(point), feature) for feature, line in lines
               if street_name(feature["properties"]["name"]) == street_name(name)]
    if matches:
        distance, feature = min(matches, key=lambda item: item[0])
        if distance <= 20:
            return feature["properties"]["id"]
    return None


def build():
    samples = json.loads((ROOT / "data/source/photo-samples.json").read_text())
    review_data = json.loads((ROOT / "data/review.json").read_text())
    reviews = {p["photo_id"]: p for p in review_data["photos"]}
    project = Transformer.from_crs(4326, 32611, always_xy=True).transform
    candidates = json.loads((ROOT / "data/candidates.geojson").read_text())["features"]
    lines = [(p, transform(shape(p["geometry"]), project, interleaved=False)) for p in candidates]
    folder = ROOT / "data/photos"
    folder.mkdir(exist_ok=True)
    features = []
    for sample in samples:
        photo = sample["photo"]
        review = reviews[photo["id"]]
        path = folder / f'{photo["id"]}.jpg'
        if not path.exists():
            response = requests.get(photo["imageLthUrl"], timeout=40)
            response.raise_for_status()
            path.write_bytes(response.content)
        coordinates = [float(photo["lng"]), float(photo["lat"])]
        point = Point(*project(*coordinates))
        candidate_id = None
        if review["context"] == "road" and review.get("road_name"):
            candidate_id = match(lines, point, review["road_name"])
        url = path.relative_to(ROOT).as_posix()
        sequence = photo["sequence"]["id"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coordinates},
            "properties": {
                "id": f'kartaview-{photo["id"]}', "title": review["title"],
                "url": url, "thumbnail": url,
                "source": "KartaView", "source_url": f'https://kartaview.org/details/{sequence}/{photo["sequenceIndex"]}',
                "credit": "© Grab and KartaView Contributors",
                "license": "CC BY-SA 4.0", "license_url": LICENSE,
                "date": photo["shotDate"][:10], "rotation": review.get("rotation", 0),
                "classification": review["classification"], "context": review["context"],
                "reviewed": True,
                "verified": False,
                "candidate_id": candidate_id,
                "baseline_candidate_id": review.get("baseline_candidate_id"),
                "historical_road_name": review.get("historical_road_name"),
                "outside_candidates": min(line.distance(point) for _, line in lines) > 20,
            },
        })
    for review in json.loads((ROOT / "data/review-aerial.json").read_text()):
        coordinates = review["coordinates"]
        point = Point(*project(*coordinates))
        candidate_id = match(lines, point, review["name"])
        classification = "canopy above road" if review["retained"] else "open road"
        if street_name(review["name"]) == "mathilda drive":
            classification = "beyond dead end"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": coordinates},
            "properties": {
                "id": review["id"], "title": review["name"],
                "url": review["file"], "thumbnail": review["file"],
                "source": "USGS NAIP", "source_url": review["source_url"],
                "credit": review["credit"], "license": review["license"],
                "license_url": USGS_LICENSE, "date": review["date"],
                "classification": classification, "context": "aerial",
                "verified": False, "reviewed": True, "candidate_id": candidate_id,
                "baseline_candidate_id": review["candidate_id"],
                "outside_candidates": min(line.distance(point) for _, line in lines) > 20,
            },
        })
    (ROOT / "data/photos.geojson").write_text(json.dumps({
        "type": "FeatureCollection", "features": features,
    }, separators=(",", ":")))
    review_data["final_matches"] = {
        "street_source": json.loads((ROOT / "data/source/roads.json").read_text())["name"],
        "criterion": "Exact normalized street name and image position within 20 m of a candidate; KartaView matches also require roadway context. This associates historical imagery with a candidate and does not verify current tunnel conditions.",
        "photo_count": len(features),
        "photos": [{"id": p["properties"]["id"],
                    "candidate_id": p["properties"]["candidate_id"],
                    "baseline_candidate_id": p["properties"]["baseline_candidate_id"],
                    "outside_candidates": p["properties"]["outside_candidates"]}
                   for p in features],
    }
    (ROOT / "data/review.json").write_text(json.dumps(review_data, indent=2, ensure_ascii=False) + "\n")
    print(f"Built {len(features)} photo markers")


if __name__ == "__main__":
    build()
