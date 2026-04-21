import json
import os
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from utils.spatial import analyze_risk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)

def geocode(place_name):
    """Query Nominatim to convert a place name to coordinates + OSM class/type."""
    params = urllib.parse.urlencode({"q": place_name, "format": "json", "limit": 1})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "LandSafetyChecker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read().decode())
    except Exception as e:
        return None, None, str(e), None, None

    if not results:
        return None, None, "Location not found", None, None

    hit = results[0]
    return (
        float(hit["lat"]),
        float(hit["lon"]),
        hit.get("display_name", place_name),
        hit.get("class", "").lower(),   # e.g. "natural", "boundary", "water"
        hit.get("type",  "").lower(),   # e.g. "wood", "national_park", "lake"
    )


# ============================================================
# STEP 2 — Fast check: Nominatim tags from the search result
# ============================================================

# Tags that mean the searched thing IS a forest / protected area
FOREST_TYPES   = {"wood", "forest", "nature_reserve", "national_park",
                  "protected_area", "scrub", "heath", "wildlife_sanctuary",
                  "biosphere_reserve", "tree_row"}
FOREST_CLASSES = {"natural", "leisure"}

# Tags that mean the searched thing IS a water body
WATER_TYPES    = {"water", "river", "lake", "reservoir", "stream", "canal",
                  "waterway", "bay", "coastline", "wetland", "lagoon",
                  "pond", "oxbow", "tidal", "drain"}
WATER_CLASSES  = {"water", "waterway"}


def classify_from_nominatim(osm_class, osm_type):
    """
    Fast classification from Nominatim's class/type fields.
    Works when the user searches a named forest/lake directly.
    Returns 'forest' | 'water' | None
    """
    if osm_type in WATER_TYPES or osm_class in WATER_CLASSES:
        return "water"
    if osm_type in FOREST_TYPES:
        return "forest"
    if osm_class in FOREST_CLASSES and osm_type not in {"administrative", ""}:
        return "forest"
    if osm_class == "boundary" and osm_type in FOREST_TYPES:
        return "forest"
    return None


# ============================================================
# STEP 3 — Deep check: Overpass API (world-scale, any location)
# ============================================================

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Query 1: is_in — finds closed polygon areas containing the point
# Works for: lakes, national parks, protected areas, forest polygons
OVERPASS_IS_IN_QUERY = """
[out:json][timeout:20];
is_in({lat},{lon})->.a;
(
  way(pivot.a)["natural"~"^(wood|scrub|heath|wetland|water)$"];
  way(pivot.a)["landuse"~"^(forest|reservoir|basin)$"];
  way(pivot.a)["leisure"~"^(nature_reserve|park)$"];
  way(pivot.a)["boundary"~"^(national_park|protected_area)$"];
  relation(pivot.a)["natural"~"^(wood|scrub|heath|wetland|water)$"];
  relation(pivot.a)["landuse"~"^(forest|reservoir|basin)$"];
  relation(pivot.a)["leisure"~"^(nature_reserve|park)$"];
  relation(pivot.a)["boundary"~"^(national_park|protected_area)$"];
  relation(pivot.a)["protect_class"];
);
out tags;
"""

# Query 2: around — finds any OSM feature within 50m of the point
# Works for: rivers (mapped as ways/linestrings), streams, coastlines,
# large forest edges, and any feature is_in misses
OVERPASS_AROUND_QUERY = """
[out:json][timeout:20];
(
  way["natural"~"^(water|wetland|wood|scrub|heath)$"](around:50,{lat},{lon});
  way["waterway"~"^(river|stream|canal|drain|riverbank)$"](around:50,{lat},{lon});
  way["landuse"~"^(forest|reservoir|basin)$"](around:50,{lat},{lon});
  way["boundary"~"^(national_park|protected_area)$"](around:50,{lat},{lon});
  way["leisure"~"^(nature_reserve)$"](around:50,{lat},{lon});
  relation["natural"~"^(water|wetland|wood)$"](around:50,{lat},{lon});
  relation["waterway"~"^(river|riverbank)$"](around:50,{lat},{lon});
  relation["boundary"~"^(national_park|protected_area)$"](around:50,{lat},{lon});
  relation["leisure"~"^(nature_reserve)$"](around:50,{lat},{lon});
);
out tags;
"""

FOREST_KEYS = {
    "natural":  {"wood", "scrub", "heath"},
    "landuse":  {"forest"},
    "leisure":  {"nature_reserve"},        # exclude plain 'park' — catches urban parks
    "boundary": {"national_park", "protected_area"},
}

WATER_KEYS = {
    "natural":  {"water", "wetland"},
    "waterway": {"river", "stream", "canal", "drain"},
    "landuse":  {"reservoir", "basin"},
}


OVERPASS_IS_IN_SIMPLE = """
[out:json][timeout:25];
is_in({lat},{lon})->.a;
(
  way(pivot.a)["natural"~"^(wood|scrub|heath|wetland|water)$"];
  way(pivot.a)["landuse"~"^(forest|reservoir|basin)$"];
  way(pivot.a)["leisure"~"^(nature_reserve|park)$"];
  way(pivot.a)["boundary"~"^(national_park|protected_area)$"];
  relation(pivot.a)["natural"~"^(wood|scrub|heath|wetland|water)$"];
  relation(pivot.a)["landuse"~"^(forest|reservoir|basin)$"];
  relation(pivot.a)["leisure"~"^(nature_reserve|park)$"];
  relation(pivot.a)["boundary"~"^(national_park|protected_area)$"];
  relation(pivot.a)["protect_class"];
);
out tags;
"""

OVERPASS_AROUND_SIMPLE = """
[out:json][timeout:25];
(
  way["natural"~"^(water|wetland|wood|scrub|heath)$"](around:100,{lat},{lon});
  way["waterway"~"^(river|stream|canal|drain|riverbank)$"](around:100,{lat},{lon});
  way["landuse"~"^(forest|reservoir|basin)$"](around:100,{lat},{lon});
  way["boundary"~"^(national_park|protected_area)$"](around:100,{lat},{lon});
  way["leisure"="nature_reserve"](around:100,{lat},{lon});
  relation["natural"~"^(water|wetland|wood)$"](around:100,{lat},{lon});
  relation["waterway"~"^(river|riverbank)$"](around:100,{lat},{lon});
  relation["boundary"~"^(national_park|protected_area)$"](around:100,{lat},{lon});
  relation["leisure"="nature_reserve"](around:100,{lat},{lon});
);
out tags;
"""


def _run_overpass(query, retries=1):
    """
    Execute an Overpass query with a hard 5-second timeout.
    Returns elements list or [] on any failure.
    One retry on rate-limit (429) only.
    """
    import time as _t
    data = urllib.parse.urlencode({"data": query}).encode()
    req  = urllib.request.Request(
        OVERPASS_URL, data=data,
        headers={"User-Agent": "LandSafetyChecker/1.0",
                 "Content-Type": "application/x-www-form-urlencoded"}
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:  # hard 5s cap
                return json.loads(resp.read().decode()).get("elements", [])
        except Exception as e:
            code = getattr(e, "code", 0)
            if attempt < retries and code in (429, 503, 504):
                _t.sleep(3)
                continue
            return []   # graceful fallback — never crashes app
    return []


def _classify_elements(isin_elements, around_elements):
    """
    Classify Overpass results from two queries.

    is_in elements: the point is GEOMETRICALLY INSIDE this feature.
                    → trust all environmental tags → HIGH
    around elements: a feature exists within 100m.
                    → STRICT: only flag real rivers/wilderness (not drains,
                      decorative ponds, urban park trees).
    """
    # ── is_in: point is inside the feature → fully trust ──────────────────
    isin_tags = [el.get("tags", {}) for el in isin_elements]

    # Urban-park guard: if the point is inside a city park, ignore natural=wood
    has_urban_park_isin = any(
        t.get("leisure", "").lower() == "park" for t in isin_tags
    )

    for tags in isin_tags:
        # Water bodies: ponds, lakes, wetlands (but not just any waterway=drain)
        if tags.get("natural", "").lower() in {"water", "wetland"}:
            return "water"
        if tags.get("landuse", "").lower() in {"reservoir", "basin"}:
            return "water"
        # Protected/wilderness areas
        if (tags.get("boundary", "").lower() in {"national_park", "protected_area"}
                or tags.get("leisure", "").lower() == "nature_reserve"
                or "protect_class" in tags):
            return "forest"
        # Forest/wood: only if NOT inside a city park
        natural_val = tags.get("natural", "").lower()
        landuse_val = tags.get("landuse", "").lower()
        if natural_val in {"wood", "scrub", "heath"} or landuse_val == "forest":
            if not has_urban_park_isin:
                return "forest"

    # ── around: feature is within 100m → strict wilderness-only rules ──────
    # Exclude: drains, decorative ponds, urban park trees, minor streams
    # Include: rivers, major water bodies, national parks, nature reserves

    around_tags = [el.get("tags", {}) for el in around_elements]

    # If there's a city park in around results → urban area → skip wood/water
    has_urban_park_around = any(
        t.get("leisure", "").lower() == "park" for t in around_tags
    )

    for tags in around_tags:
        waterway = tags.get("waterway", "").lower()
        natural  = tags.get("natural",  "").lower()
        boundary = tags.get("boundary", "").lower()
        leisure  = tags.get("leisure",  "").lower()
        landuse  = tags.get("landuse",  "").lower()

        # STRICT WATER: only major named rivers (not drains, streams)
        if waterway == "river":
            return "water"
        # river mapped as polygon (riverbank)
        if waterway == "riverbank":
            return "water"

        # Protected/wilderness: always flag
        if boundary in {"national_park", "protected_area"} or leisure == "nature_reserve":
            return "forest"
        if "protect_class" in tags:
            return "forest"

        # Forest/wood: only if NOT in urban park context
        if natural in {"wood", "scrub", "heath"} or landuse == "forest":
            if not has_urban_park_around:
                return "forest"

        # Do NOT flag: natural=water (decorative pond), waterway=drain,
        # waterway=stream in cities — these are urban features

    return None


def check_via_overpass(lat, lon):
    """
    World-scale environmental zone check using two Overpass queries:

    1. is_in       → point is geometrically inside a closed polygon
                     (lakes, national parks, forest polygons)
    2. around:100  → features within 100m (major rivers, forest edges)
                     STRICT filtering to avoid urban false positives

    Returns 'forest' | 'water' | None.
    Graceful fallback to None if Overpass is unreachable.
    """
    q1 = OVERPASS_IS_IN_SIMPLE.format(lat=lat, lon=lon)
    q2 = OVERPASS_AROUND_SIMPLE.format(lat=lat, lon=lon)
    isin   = _run_overpass(q1)
    around = _run_overpass(q2)
    return _classify_elements(isin, around)




# ============================================================
# Shared override builder
# ============================================================

def apply_env_override(result, env_type, source):
    """Escalate risk to HIGH when an environmental zone is detected."""
    if env_type == "forest":
        result.update({
            "risk":             "HIGH",
            "forest_risk":      "HIGH",
            "forest_reason":    f"Inside a forest/protected area ({source})",
            "forest_distance_m": 0,
            "legal_risk":       "Not suitable for construction",
            "recommendation":   "Not recommended",
            "osm_override":     True,
        })
        result["flags"].append(f"Inside forest/protected zone ({source})")

    elif env_type == "water":
        result.update({
            "risk":            "HIGH",
            "water_risk":      "HIGH",
            "water_reason":    f"Inside a water body ({source})",
            "water_distance_m": 0,
            "legal_risk":      "Not suitable for construction",
            "recommendation":  "Not recommended",
            "osm_override":    True,
        })
        result["flags"].append(f"Inside water body ({source})")

    return result


# ============================================================
# API Routes
# ============================================================

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    Accept lat/lon OR location_name.
    Three-layer environmental detection:
      1. Local GeoJSON (fast, offline)
      2. Nominatim search tags (fast, no extra call)
      3. Overpass world-map spatial query (accurate, global)
    """
    body          = request.get_json(force=True)
    lat           = body.get("lat")
    lon           = body.get("lon")
    location_name = body.get("location_name")
    resolved_name = None
    nominatim_env = None

    # --- Geocode if needed ---
    if location_name and (lat is None or lon is None):
        lat, lon, resolved_name, osm_class, osm_type = geocode(location_name)
        if lat is None:
            return jsonify({"error": resolved_name or "Location not found"}), 404
        nominatim_env = classify_from_nominatim(osm_class, osm_type)

    if lat is None or lon is None:
        return jsonify({"error": "Provide lat/lon or location_name"}), 400

    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lon must be numbers"}), 400

    # Layer 1: local GeoJSON (always fast — 3-40ms)
    result = analyze_risk(lat, lon)
    result["lat"] = lat
    result["lon"] = lon
    if resolved_name:
        result["resolved_name"] = resolved_name

    if result["risk"] == "HIGH":
        return jsonify(result)   # early exit — no need for Overpass

    # Layer 2: fast Nominatim tag check (only for name-based searches)
    if nominatim_env:
        return jsonify(apply_env_override(result, nominatim_env, "OpenStreetMap search"))

    # Layer 3: Overpass world-map query
    # PERFORMANCE RULE: Only call Overpass when:
    #   (a) The request came from a location NAME search (not raw lat/lon click)
    #   (b) The local GeoJSON result is still LOW/MEDIUM
    # For raw lat/lon clicks, local data is the source of truth → instant response
    if location_name:   # name search → user typed a place name → check world map
        overpass_env = check_via_overpass(lat, lon)
        if overpass_env:
            apply_env_override(result, overpass_env, "OpenStreetMap world map")

    return jsonify(result)


@app.route("/api/layers/water")
def api_water():
    with open(os.path.join(BASE_DIR, "data", "water_bodies.geojson")) as f:
        return jsonify(json.load(f))


@app.route("/api/layers/forest")
def api_forest():
    with open(os.path.join(BASE_DIR, "data", "forest_zones.geojson")) as f:
        return jsonify(json.load(f))


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
