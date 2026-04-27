import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from functools import lru_cache

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from utils.spatial import analyze_risk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder="static", static_url_path="/static")
CORS(app)


UNKNOWN_LOCATION = "Unknown Location"
SAFE_FALLBACK_MESSAGE = "No restricted zones detected within available dataset coverage"


def _read_json_response(req, timeout):
    """Read JSON safely with explicit UTF-8 handling."""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _normalize_text(value):
    """Normalize text and remove broken/control characters."""
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\ufffd", " ")
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = re.sub(r"\s+", " ", text).strip(" ,;-")
    return text


def _clean_location_text(value):
    """Return a human-readable location label or empty string."""
    text = _normalize_text(value)
    return text if text else ""


def _is_demo_safe_location(text):
    """Prefer labels that are readable in common Latin-script UIs."""
    cleaned = _clean_location_text(text)
    return bool(cleaned and re.search(r"[A-Za-z0-9]", cleaned))


@lru_cache(maxsize=512)
def fetch_reverse_data_cached(lat_key, lon_key, zoom):
    """Cached reverse geocode payload for location labeling and water checks."""
    params = urllib.parse.urlencode({
        "lat": lat_key,
        "lon": lon_key,
        "format": "json",
        "zoom": zoom,
        "addressdetails": 1,
        "accept-language": "en",
    })
    url = f"https://nominatim.openstreetmap.org/reverse?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LandSafetyChecker/1.0",
            "Accept-Language": "en",
        },
    )
    try:
        return _read_json_response(req, timeout=5)
    except Exception:
        return {}


def fetch_reverse_data(lat, lon, zoom=14):
    """Reverse geocode data with coordinate normalization for cache stability."""
    return fetch_reverse_data_cached(round(float(lat), 6), round(float(lon), 6), int(zoom))


def _reverse_indicates_water(data):
    """Return True when reverse-geocode metadata clearly indicates water."""
    if not data:
        return False
    if data.get("error"):
        return True

    osm_type = _normalize_text(data.get("type", "")).lower()
    osm_class = _normalize_text(data.get("class", "")).lower()
    display_name = _normalize_text(data.get("display_name", "")).lower()
    address = data.get("address") or {}

    water_types = {
        "ocean", "sea", "strait", "gulf", "bay", "coastline",
        "water", "lake", "reservoir", "river", "riverbank",
        "lagoon", "wetland",
    }
    water_classes = {"water", "waterway"}

    if osm_type in water_types or osm_class in water_classes:
        return True
    if any(keyword in display_name for keyword in water_types):
        return True
    if not address.get("country_code") and osm_type in water_types:
        return True
    return False


# ============================================================
# LAYER 0 — Ocean / Sea Detector (reverse geocode check)
# ============================================================

def is_on_land(lat, lon, reverse_data=None):
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
    try:
        data = reverse_data or fetch_reverse_data(lat, lon, zoom=5)
        if _reverse_indicates_water(data):
            return False

        address = (data or {}).get("address", {})
        if address.get("country_code"):
            return True

        return None   # uncertain → treat as land
    except Exception:
        return None   # network error → treat as land, let other layers handle


def geocode(place_name):
    """Query Nominatim to convert a place name to coordinates + OSM class/type."""
    params = urllib.parse.urlencode({
        "q": place_name,
        "format": "json",
        "limit": 1,
        "accept-language": "en",
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LandSafetyChecker/1.0",
            "Accept-Language": "en",
        },
    )
    try:
        results = _read_json_response(req, timeout=10)
    except Exception as e:
        return None, None, str(e), None, None

    if not results:
        return None, None, "Location not found", None, None

    hit = results[0]
    return (
        float(hit["lat"]),
        float(hit["lon"]),
        _clean_location_text(hit.get("display_name", place_name)) or _clean_location_text(place_name) or UNKNOWN_LOCATION,
        _normalize_text(hit.get("class", "")).lower(),   # e.g. "natural", "boundary", "water"
        _normalize_text(hit.get("type",  "")).lower(),   # e.g. "wood", "national_park", "lake"
    )


def _best_reverse_name(data, fallback=UNKNOWN_LOCATION):
    """Build a human-readable place label from Nominatim reverse-geocode data."""
    display_name = _clean_location_text(data.get("display_name"))
    if _is_demo_safe_location(display_name):
        return display_name

    address = data.get("address", {})
    locality = (
        _clean_location_text(address.get("city"))
        or _clean_location_text(address.get("town"))
        or _clean_location_text(address.get("village"))
        or _clean_location_text(address.get("hamlet"))
    )
    state = _clean_location_text(address.get("state"))
    country = _clean_location_text(address.get("country"))
    parts = [locality, state, country]

    deduped = []
    seen = set()
    for part in parts:
        clean = _clean_location_text(part)
        if clean and clean not in seen:
            deduped.append(clean)
            seen.add(clean)

    fallback_name = ", ".join(deduped) if deduped else fallback
    return _clean_location_text(fallback_name) or fallback


@lru_cache(maxsize=256)
def reverse_geocode_cached(lat_key, lon_key):
    """
    Reverse geocode rounded coordinates to a readable place name.
    Cached to avoid repeated calls for the same clicked/input location.
    """
    try:
        data = fetch_reverse_data_cached(lat_key, lon_key, 14)
        if data.get("error"):
            return UNKNOWN_LOCATION
        return _best_reverse_name(data)
    except Exception:
        return UNKNOWN_LOCATION


def reverse_geocode(lat, lon):
    """Reverse geocode lat/lon with lightweight coordinate normalization."""
    return reverse_geocode_cached(round(float(lat), 6), round(float(lon), 6))


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
        if tags.get("waterway", "").lower() in {"river", "riverbank", "canal", "stream"}:
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
            "distance_to_forest": 0,
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
            "distance_to_water": 0,
            "legal_risk":      "Not suitable for construction",
            "recommendation":  "Not recommended",
            "osm_override":    True,
        })
        result["flags"].append(f"Inside water body ({source})")

    return result


def enforce_water_high_risk(result, source="Water detection"):
    """Ensure any inside-water detection is always surfaced as HIGH risk."""
    inside_water = bool(result.get("inside_water"))
    water_distance = result.get("water_distance_m")
    if inside_water or water_distance == 0:
        result.update({
            "risk": "HIGH",
            "water_risk": "HIGH",
            "inside_water": True,
            "water_distance_m": 0,
            "distance_to_water": 0,
            "legal_risk": "Not suitable for construction",
            "recommendation": "Not recommended",
        })
        if not result.get("water_reason"):
            result["water_reason"] = f"Inside a water body ({source})"
        flags = result.setdefault("flags", [])
        if not any("Inside water body" in flag for flag in flags):
            flags.append(f"Inside water body ({source})")
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
        triggered.append(f"Near forest zone ({forest_dist} m)")
        reasons.append(
            "The location is near a forest boundary, which may have "
            "environmental buffer restrictions."
        )

    # ── Safe — no triggers ────────────────────────────────────────
    if not triggered:
        triggered.append("No water or forest zones detected within threshold distance")
        reasons.append(
            SAFE_FALLBACK_MESSAGE
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
            factor_parts.append(f"is near a forest zone ({forest_dist} m away)")
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
            proximity_parts.append(f"a forest zone ({forest_dist} m away)")
        combined = " and ".join(proximity_parts) if proximity_parts else "a restricted zone"
        detailed = (
            f"This location is in close proximity to {combined}, "
            "placing it within the 100-meter environmental buffer zone. "
            "Development may require an Environmental Impact Assessment (EIA) "
            "and additional regulatory clearance before proceeding."
        )
    else:
        detailed = (
            f"{SAFE_FALLBACK_MESSAGE}. "
            "Based on the currently available mapped layers, the location appears "
            "to be outside water and forest restriction thresholds."
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
    reverse_data  = None

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

    reverse_data = fetch_reverse_data(lat, lon, zoom=14)

    # Reverse geocode only for coordinate-driven analysis that did not
    # already resolve a place name via forward geocoding.
    if not resolved_name:
        resolved_name = _best_reverse_name(reverse_data)
    resolved_name = _clean_location_text(resolved_name) or UNKNOWN_LOCATION

    # ----- Layer 0: Ocean/Sea detection -----
    land_check = is_on_land(lat, lon, reverse_data=reverse_data)
    if land_check is False:
        # Point is in ocean/sea → HIGH risk directly
        result = {
            "risk": "HIGH",
            "water_risk": "HIGH",
            "forest_risk": "LOW",
            "inside_water": True,
            "inside_forest": False,
            "water_distance_m": 0,
            "distance_to_water": 0,
            "forest_distance_m": None,
            "distance_to_forest": None,
            "water_reason": "Location lies within a water body (sea/ocean)",
            "forest_reason": None,
            "lat": lat,
            "lon": lon,
            "flags": ["Inside water body"],
            "legal_risk": "Not suitable for construction",
            "recommendation": "Not recommended",
        }
        result["resolved_name"] = resolved_name
        result["location_name"] = result["resolved_name"]
        enforce_water_high_risk(result, source="Ocean/sea detection")
        generate_explanation(result)
        if purpose:
            apply_purpose_interpretation(result, purpose)
        return jsonify(result)
    # If land_check is True or None, continue with normal analysis

    # Layer 1: local GeoJSON (always fast — 3-40ms)
    result = analyze_risk(lat, lon)
    result["lat"] = lat
    result["lon"] = lon
    result["resolved_name"] = resolved_name
    result["location_name"] = result["resolved_name"]
    result["distance_to_water"] = result.get("water_distance_m")
    result["distance_to_forest"] = result.get("forest_distance_m")
    if result.get("water_distance_m") == 0:
        result["inside_water"] = True
        enforce_water_high_risk(result, source="Local GIS layer")

    if result["risk"] == "HIGH":
        enforce_water_high_risk(result, source="Local GIS layer")
        generate_explanation(result)
        if purpose:
            apply_purpose_interpretation(result, purpose)
        return jsonify(result)   # early exit — no need for Overpass

    # Layer 2: fast Nominatim tag check (only for name-based searches)
    if nominatim_env:
        apply_env_override(result, nominatim_env, "OpenStreetMap search")
        enforce_water_high_risk(result, source="OpenStreetMap search")
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
        enforce_water_high_risk(result, source="OpenStreetMap world map")

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
