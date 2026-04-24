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


# ============================================================
# LAYER 0 — Ocean / Sea Detector (reverse geocode check)
# ============================================================

def is_on_land(lat, lon):
    """
    Check if a coordinate is on land or in ocean/sea.
    Uses Nominatim reverse geocoding:
      - If it returns an address with a country → on land
      - If it returns 'ocean', 'sea', or error → in water

    Returns:
        True  → point is on land
        False → point is in ocean/sea (HIGH risk)
        None  → could not determine (treat as land, let other layers handle)
    """
    params = urllib.parse.urlencode({
        "lat": lat, "lon": lon,
        "format": "json", "zoom": 5,
    })
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "LandSafetyChecker/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        # Nominatim returns {"error": "..."} for ocean points
        if "error" in data:
            return False   # ocean — not on land

        # Check if it's tagged as ocean/sea explicitly
        osm_type = data.get("type", "").lower()
        osm_class = data.get("class", "").lower()
        name = data.get("display_name", "").lower()

        ocean_keywords = {"ocean", "sea", "strait", "gulf", "bay"}
        if osm_type in ocean_keywords or osm_class in {"place", "natural"} and osm_type in ocean_keywords:
            return False

        # Check name for ocean/sea references
        for kw in ocean_keywords:
            if kw in name:
                return False

        # Has a country code → it's on land
        address = data.get("address", {})
        if address.get("country_code"):
            return True

        return None   # uncertain → treat as land
    except Exception:
        return None   # network error → treat as land, let other layers handle


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
            "inside_forest":    True,
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
            "inside_water":    True,
            "water_reason":    f"Inside a water body ({source})",
            "water_distance_m": 0,
            "legal_risk":      "Not suitable for construction",
            "recommendation":  "Not recommended",
            "osm_override":    True,
        })
        result["flags"].append(f"Inside water body ({source})")

    return result


# ============================================================
# PURPOSE-BASED INTERPRETATION LAYER
# ============================================================

VALID_PURPOSES = {"residential", "farming", "commercial"}

PURPOSE_LABELS = {
    "residential": "Residential",
    "farming":     "Farming (Agriculture)",
    "commercial":  "Commercial",
}

# Recommendation matrix: PURPOSE_RECOMMENDATIONS[risk][purpose]
PURPOSE_RECOMMENDATIONS = {
    "HIGH": {
        "residential": "Not suitable for housing",
        "farming":     "Not suitable for cultivation",
        "commercial":  "Not suitable for development",
    },
    "MEDIUM": {
        "residential": "Construction allowed with restrictions",
        "farming":     "Possible with caution (water proximity)",
        "commercial":  "Requires legal/environmental clearance",
    },
    "LOW": {
        "residential": "Suitable for housing",
        "farming":     "Suitable for agriculture",
        "commercial":  "Suitable for development",
    },
}


def apply_purpose_interpretation(result, purpose):
    """
    Add purpose-specific fields to the result dict.
    Does NOT modify risk calculation — only adds interpretation.
    """
    if purpose not in VALID_PURPOSES:
        return result

    risk = result.get("risk", "LOW")
    result["purpose"]                = purpose
    result["purpose_label"]          = PURPOSE_LABELS[purpose]
    result["purpose_recommendation"] = PURPOSE_RECOMMENDATIONS[risk][purpose]
    return result


# ============================================================
# STRUCTURED REASONING ENGINE
# ============================================================

def generate_explanation(result):
    """
    Build a structured, deterministic explanation from spatial results.
    Does NOT modify risk — only adds explanation fields.

    Adds:
      - triggered_factors  : list of short factor strings
      - explanation_reasons : list of detailed reason strings
      - detailed_explanation: single human-readable paragraph
    """
    risk          = result.get("risk", "LOW")
    water_dist    = result.get("water_distance_m")
    forest_dist   = result.get("forest_distance_m")
    inside_water  = bool(result.get("inside_water"))
    inside_forest = bool(result.get("inside_forest"))

    triggered = []
    reasons   = []

    # ── Inside water body ─────────────────────────────────────────
    if inside_water:
        triggered.append("Inside water body")
        reasons.append(
            "The location lies within a water body, making it "
            "physically unsuitable for land-based use."
        )

    # ── Inside forest / protected zone ────────────────────────────
    if inside_forest:
        triggered.append("Inside forest zone")
        reasons.append(
            "The location lies within a forest or eco-sensitive zone, "
            "where construction and development are legally restricted."
        )

    # ── Near water (distance < 100m but not inside) ──────────────
    if (not inside_water) and water_dist is not None and 0 < water_dist < 100:
        triggered.append(f"Near water body ({water_dist} m)")
        reasons.append(
            "The location is within close proximity to a water body, "
            "which may pose flood risk and regulatory restrictions."
        )

    # ── Near forest (distance < 100m but not inside) ─────────────
    if (not inside_forest) and forest_dist is not None and 0 < forest_dist < 100:
        triggered.append(f"Near forest boundary ({forest_dist} m)")
        reasons.append(
            "The location is near a forest boundary, which may have "
            "environmental buffer restrictions."
        )

    # ── Safe — no triggers ────────────────────────────────────────
    if not triggered:
        triggered.append("No restricted zone detected")
        reasons.append(
            "The location is at a safe distance from all mapped "
            "water bodies and forest zones."
        )

    # ── Build detailed paragraph ──────────────────────────────────
    if risk == "HIGH":
        # Combine factor descriptions into a cohesive paragraph
        factor_parts = []
        if inside_water:
            factor_parts.append(
                "falls within a water body (sea, lake, or river)"
            )
        if inside_forest:
            factor_parts.append(
                "lies within a protected forest or eco-sensitive region"
            )
        if (not inside_water) and water_dist is not None and 0 < water_dist < 100:
            factor_parts.append(f"is close to a water body ({water_dist} m away)")
        if (not inside_forest) and forest_dist is not None and 0 < forest_dist < 100:
            factor_parts.append(f"is near a forest boundary ({forest_dist} m away)")
        combined = " and ".join(factor_parts) if factor_parts else "intersects a restricted zone"
        detailed = (
            f"This location {combined}. "
            "Due to environmental regulations and ecological sensitivity, "
            "any form of construction or land development is not advisable "
            "without legal clearance."
        )
    elif risk == "MEDIUM":
        proximity_parts = []
        if water_dist is not None and 0 < water_dist < 100:
            proximity_parts.append(f"a water body ({water_dist} m away)")
        if forest_dist is not None and 0 < forest_dist < 100:
            proximity_parts.append(f"a forest boundary ({forest_dist} m away)")
        combined = " and ".join(proximity_parts) if proximity_parts else "a restricted zone"
        detailed = (
            f"This location is in close proximity to {combined}, "
            "placing it within the 100-meter environmental buffer zone. "
            "Development may require an Environmental Impact Assessment (EIA) "
            "and additional regulatory clearance before proceeding."
        )
    else:
        detailed = (
            "This location is at a safe distance from all mapped water bodies "
            "and forest zones. No environmental constraints were detected. "
            "Standard building permits and local regulations apply."
        )

    result["triggered_factors"]    = triggered
    result["explanation_reasons"]  = reasons
    result["detailed_explanation"] = detailed
    return result


# ============================================================
# API Routes
# ============================================================

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    Accept lat/lon OR location_name, plus optional "purpose".
    Three-layer environmental detection:
      1. Local GeoJSON (fast, offline)
      2. Nominatim search tags (fast, no extra call)
      3. Overpass world-map spatial query (accurate, global)
    After risk is computed, an optional purpose-interpretation layer
    adds user-friendly recommendations without altering risk logic.
    """
    body          = request.get_json(force=True)
    lat           = body.get("lat")
    lon           = body.get("lon")
    location_name = body.get("location_name")
    purpose       = (body.get("purpose") or "").strip().lower()
    resolved_name = None
    nominatim_env = None

    # Validate purpose (optional — ignored if invalid/missing)
    if purpose and purpose not in VALID_PURPOSES:
        return jsonify({"error": f"Invalid purpose. Allowed: {', '.join(sorted(VALID_PURPOSES))}"}), 400

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

    # ----- Layer 0: Ocean/Sea detection -----
    land_check = is_on_land(lat, lon)
    if land_check is False:
        # Point is in ocean/sea → HIGH risk directly
        result = {
            "risk": "HIGH",
            "water_risk": "HIGH",
            "forest_risk": "LOW",
            "inside_water": True,
            "inside_forest": False,
            "water_distance_m": 0,
            "forest_distance_m": None,
            "water_reason": "Location lies within a water body (sea/ocean)",
            "forest_reason": None,
            "lat": lat,
            "lon": lon,
        }
        if resolved_name:
            result["resolved_name"] = resolved_name
        generate_explanation(result)
        if purpose:
            apply_purpose_interpretation(result, purpose)
        return jsonify(result)
    # If land_check is True or None, continue with normal analysis

    # Layer 1: local GeoJSON (always fast — 3-40ms)
    result = analyze_risk(lat, lon)
    result["lat"] = lat
    result["lon"] = lon
    if resolved_name:
        result["resolved_name"] = resolved_name

    if result["risk"] == "HIGH":
        generate_explanation(result)
        if purpose:
            apply_purpose_interpretation(result, purpose)
        return jsonify(result)   # early exit — no need for Overpass

    # Layer 2: fast Nominatim tag check (only for name-based searches)
    if nominatim_env:
        apply_env_override(result, nominatim_env, "OpenStreetMap search")
        generate_explanation(result)
        if purpose:
            apply_purpose_interpretation(result, purpose)
        return jsonify(result)

    # Layer 3: Overpass world-map query (global coverage for any coordinate)
    # Called for BOTH name-based and coordinate-based requests when local data
    # does not already return HIGH. Hard 5s timeout ensures fast response.
    overpass_env = check_via_overpass(lat, lon)
    if overpass_env:
        apply_env_override(result, overpass_env, "OpenStreetMap world map")

    # Structured explanation (never changes risk)
    generate_explanation(result)

    # Purpose interpretation (final layer — never changes risk)
    if purpose:
        apply_purpose_interpretation(result, purpose)

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
