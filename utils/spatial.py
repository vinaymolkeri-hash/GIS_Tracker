"""
spatial.py — Optimized GIS Risk Analysis Engine
================================================
Optimizations:
  - GeoJSON loaded ONCE at module startup (not per request)
  - Spatial index (STRtree) for fast candidate filtering
  - LineString geometries buffered to polygons (100m buffer in EPSG:3857)
  - .intersects() used instead of .contains() to catch boundary points
  - EPSG:3857 projection for accurate metric distances
  - Full debug logging for transparency and viva explainability

Risk Logic:
  HIGH   → point intersects geometry  (inside OR on boundary)
  MEDIUM → distance < 100m            (within buffer zone)
  LOW    → distance ≥ 100m            (safe distance)
"""

import os
import logging
import geopandas as gpd
from shapely.geometry import Point
from shapely.strtree import STRtree

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("spatial")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Load & project layers ONCE at startup ───────────────────────────────────
BUFFER_M = 100  # MEDIUM risk threshold in meters


def _load_and_project(path: str, label: str):
    """
    Load a GeoJSON file, convert to EPSG:3857, and buffer any LineString
    geometries by BUFFER_M meters so that .intersects() works correctly.
    Returns a GeoDataFrame with only Polygon/MultiPolygon geometries.
    """
    gdf = gpd.read_file(path)

    # Ensure we have a CRS; GeoJSON default is EPSG:4326
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    # Project to metric CRS for distance accuracy
    gdf = gdf.to_crs(epsg=3857)

    # Buffer LineString / Point geometries → Polygon so contains/intersects work
    def _fix_geom(geom):
        if geom is None:
            return geom
        gtype = geom.geom_type
        if gtype in ("LineString", "MultiLineString", "Point", "MultiPoint"):
            return geom.buffer(BUFFER_M)   # 100m buffer around rivers etc.
        return geom

    gdf["geometry"] = gdf["geometry"].apply(_fix_geom)
    gdf = gdf[gdf["geometry"].notnull() & gdf["geometry"].is_valid]

    log.info(f"Loaded '{label}': {len(gdf)} features | CRS: {gdf.crs}")
    return gdf


log.info("Loading spatial layers...")
_WATER  = _load_and_project(os.path.join(BASE_DIR, "data", "water_bodies.geojson"), "water")
_FOREST = _load_and_project(os.path.join(BASE_DIR, "data", "forest_zones.geojson"), "forest")
log.info("Spatial layers ready.")

# ── Spatial indexes (STRtree) for fast nearest-candidate lookup ─────────────
_WATER_IDX  = STRtree(_WATER.geometry.values)
_FOREST_IDX = STRtree(_FOREST.geometry.values)


# ── Core evaluation function ─────────────────────────────────────────────────

def _evaluate_layer(point_4326: Point, gdf: gpd.GeoDataFrame,
                    idx: STRtree, label: str) -> tuple:
    """
    Evaluate a WGS-84 point against a projected GeoDataFrame.

    Returns:
        (risk, reason, distance_m)
        risk     : "HIGH" | "MEDIUM" | "LOW"
        reason   : human-readable explanation
        distance : distance in meters (0 if inside)
    """
    # Project point to EPSG:3857 for metric calculations
    pt_series = gpd.GeoSeries([point_4326], crs="EPSG:4326").to_crs(epsg=3857)
    pt_proj   = pt_series.iloc[0]

    log.debug(f"Evaluating against {label} | point_proj={pt_proj.wkt[:60]}")

    # ── Fast filter via STRtree spatial index ────────────────────────────────
    # Query returns indices of geometries whose bounding boxes touch the point
    candidate_indices = list(idx.query(pt_proj))

    if not candidate_indices:
        # No bounding-box hits → no geometry nearby at all
        # Fall back to brute-force min distance across all features
        min_dist = float("inf")
        best_name = "unknown"
        for i, row in gdf.iterrows():
            d = pt_proj.distance(row.geometry)
            if d < min_dist:
                min_dist = d
                best_name = row.get("name", label)
        log.info(f"  [{label}] No candidates in index. Min dist={min_dist:.1f}m")
        if min_dist < BUFFER_M:
            return "MEDIUM", f"Near {label} — {best_name} ({int(min_dist)} meters)", int(min_dist)
        return "LOW", f"Safe distance from {label} ({int(min_dist)} meters away)", int(min_dist)

    # ── Check candidates precisely ────────────────────────────────────────────
    min_dist  = float("inf")
    best_name = label
    inside    = False

    # candidate_indices are positional indices into gdf.geometry.values
    geom_values = gdf.geometry.values
    names       = gdf.get("name", gdf.index).values

    for ci in candidate_indices:
        geom = geom_values[ci]
        name = names[ci] if ci < len(names) else label

        # Use intersects() — catches points exactly on boundaries
        if geom.intersects(pt_proj):
            log.info(f"  [{label}] ✅ INSIDE '{name}'")
            return "HIGH", f"Inside {label} — {name}", 0

        d = pt_proj.distance(geom)
        if d < min_dist:
            min_dist  = d
            best_name = name

    # Also check non-candidate geometries for min distance
    # (needed when bounding box misses a nearby but non-intersecting geom)
    for i, row in gdf.iterrows():
        pos = list(gdf.index).index(i) if i in gdf.index else None
        if pos is not None and pos in candidate_indices:
            continue
        d = pt_proj.distance(row.geometry)
        if d < min_dist:
            min_dist  = d
            best_name = row.get("name", label)

    log.info(f"  [{label}] Min dist={min_dist:.1f}m to '{best_name}'")

    if min_dist < BUFFER_M:
        return "MEDIUM", f"Near {label} — {best_name} ({int(min_dist)} meters)", int(min_dist)

    return "LOW", f"Safe distance from {label} ({int(min_dist)} meters away)", int(min_dist)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_risk(lat: float, lon: float) -> dict:
    """
    Main entry point. Accepts WGS-84 lat/lon.
    Returns a complete risk assessment dict.
    """
    point = Point(lon, lat)   # Shapely: (x=lon, y=lat)

    log.info(f"analyze_risk(lat={lat}, lon={lon})")

    water_risk, water_reason, water_dist   = _evaluate_layer(point, _WATER,  _WATER_IDX,  "water body")
    forest_risk, forest_reason, forest_dist = _evaluate_layer(point, _FOREST, _FOREST_IDX, "forest zone")

    # Overall risk: worst of water + forest
    if "HIGH" in (water_risk, forest_risk):
        overall = "HIGH"
    elif "MEDIUM" in (water_risk, forest_risk):
        overall = "MEDIUM"
    else:
        overall = "LOW"

    # Human-readable flags
    flags = []
    if water_risk  == "HIGH":   flags.append(f"Inside water body — {water_reason.split('—')[-1].strip()}")
    elif water_risk == "MEDIUM": flags.append(f"Near water body — {water_dist}m")
    if forest_risk == "HIGH":   flags.append(f"Inside forest zone — {forest_reason.split('—')[-1].strip()}")
    elif forest_risk == "MEDIUM": flags.append(f"Near forest zone — {forest_dist}m")

    legal_risk = {
        "HIGH":   "Not suitable for construction",
        "MEDIUM": "Use caution — possible buffer-zone restrictions",
        "LOW":    "Suitable for construction",
    }[overall]

    recommendation = {
        "HIGH":   "Not recommended — environmental violation risk",
        "MEDIUM": "Use caution — may require EIA clearance",
        "LOW":    "Safe to proceed",
    }[overall]

    log.info(f"  → OVERALL: {overall}")

    return {
        "risk":             overall,
        "water_risk":       water_risk,
        "water_reason":     water_reason,
        "water_distance_m": water_dist,
        "forest_risk":      forest_risk,
        "forest_reason":    forest_reason,
        "forest_distance_m": forest_dist,
        "flags":            flags,
        "legal_risk":       legal_risk,
        "recommendation":   recommendation,
    }
