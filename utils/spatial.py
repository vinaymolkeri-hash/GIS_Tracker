import os
import geopandas as gpd
from shapely.geometry import Point

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

water = gpd.read_file(os.path.join(BASE_DIR, "data", "water_bodies.geojson"))
forest = gpd.read_file(os.path.join(BASE_DIR, "data", "forest_zones.geojson"))


def _evaluate_layer(point, layer, label):
    """Evaluate a point against a spatial layer and return risk, reason, and distance in meters."""
    layer_proj = layer.to_crs(epsg=3857)
    point_proj = gpd.GeoSeries([point], crs="EPSG:4326").to_crs(epsg=3857)[0]

    min_distance = float("inf")

    for _, row in layer_proj.iterrows():
        geom = row.geometry

        if geom.contains(point_proj):
            return "HIGH", f"Inside {label}", 0

        dist = point_proj.distance(geom)
        min_distance = min(min_distance, dist)

    if min_distance < 100:
        return "MEDIUM", f"Near {label} ({int(min_distance)} meters)", int(min_distance)

    return "LOW", f"Safe distance from {label} ({int(min_distance)} meters away)", int(min_distance)


def check_water_risk(lat, lon):
    point = Point(lon, lat)
    risk, reason, distance = _evaluate_layer(point, water, "water body")
    return risk, reason


def analyze_risk(lat, lon):
    point = Point(lon, lat)

    water_risk, water_reason, water_dist = _evaluate_layer(point, water, "water body")
    forest_risk, forest_reason, forest_dist = _evaluate_layer(point, forest, "forest zone")

    if "HIGH" in (water_risk, forest_risk):
        overall_risk = "HIGH"
    elif "MEDIUM" in (water_risk, forest_risk):
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    flags = []
    if water_risk == "HIGH":
        flags.append("Inside water body")
    elif water_risk == "MEDIUM":
        flags.append("Near water body")

    if forest_risk == "HIGH":
        flags.append("Inside forest zone")
    elif forest_risk == "MEDIUM":
        flags.append("Near forest zone")

    legal_risk = (
        "Not suitable for construction"
        if overall_risk == "HIGH"
        else "Use caution - possible restrictions"
        if overall_risk == "MEDIUM"
        else "Suitable for construction"
    )

    recommendation = (
        "Not recommended"
        if overall_risk == "HIGH"
        else "Use caution"
        if overall_risk == "MEDIUM"
        else "Safe to proceed"
    )

    return {
        "risk": overall_risk,
        "water_risk": water_risk,
        "water_reason": water_reason,
        "water_distance_m": water_dist,
        "forest_risk": forest_risk,
        "forest_reason": forest_reason,
        "forest_distance_m": forest_dist,
        "flags": flags,
        "legal_risk": legal_risk,
        "recommendation": recommendation,
    }
