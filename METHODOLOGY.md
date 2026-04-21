# Land Safety Checker — Methodology & Risk Classification

## 1. System Overview

The **Land Safety Checker** is a geospatial risk analysis tool that evaluates whether a given location is safe for construction or development. It uses **GIS (Geographic Information System)** data to assess proximity to environmentally sensitive zones — specifically **water bodies** and **forest zones**.

The system accepts a geographic coordinate (latitude, longitude) or a place name, and produces a risk classification with supporting evidence.

---

## 2. Data Sources

| Layer | Format | Description | Example |
|-------|--------|-------------|---------|
| Water Bodies | GeoJSON (Polygon, LineString) | Lakes, rivers, reservoirs, and other water features | Lake Vembanad, River Ganges Segment |
| Forest Zones | GeoJSON (Polygon) | Protected forest areas and forest reserves | Forest Zone A (Kerala) |

All spatial data is stored in the **EPSG:4326** (WGS 84) coordinate reference system and projected to **EPSG:3857** (Web Mercator) for accurate distance calculations in meters.

---

## 3. Feature Extraction

For each input location, the system extracts four spatial features by comparing the point against each GIS layer:

| # | Feature | Type | Unit | Description |
|---|---------|------|------|-------------|
| F1 | `inside_water` | Boolean | — | Whether the point falls inside any water body polygon |
| F2 | `distance_to_water` | Continuous | Meters | Euclidean distance to the nearest water body boundary |
| F3 | `inside_forest` | Boolean | — | Whether the point falls inside any forest zone polygon |
| F4 | `distance_to_forest` | Continuous | Meters | Euclidean distance to the nearest forest zone boundary |

### Feature Extraction Process

```
Input: Point P = (latitude, longitude)

For each GIS layer L ∈ {Water Bodies, Forest Zones}:
    1. Project P and L from EPSG:4326 → EPSG:3857
    2. For each geometry G in L:
        a. If G.contains(P) → inside = True, distance = 0
        b. Else → compute Euclidean distance(P, G)
    3. Record minimum distance across all geometries
```

> **Why EPSG:3857?** Distance calculations in EPSG:4326 (degrees) are not meaningful for real-world measurements. By projecting to EPSG:3857 (meters), we get accurate distance values suitable for threshold comparisons.

---

## 4. Risk Classification Rules

The system uses a **rule-based classification** approach with three risk levels. No machine learning model is involved — the rules are deterministic and transparent.

### Decision Logic

```
IF (inside_water = TRUE) OR (inside_forest = TRUE):
    risk_level = HIGH

ELSE IF (distance_to_water < 100m) OR (distance_to_forest < 100m):
    risk_level = MEDIUM

ELSE:
    risk_level = LOW
```

### Decision Flowchart

```
            ┌─────────────────────┐
            │ Input: (lat, lon)   │
            └──────────┬──────────┘
                       │
              ┌────────▼────────┐
              │ Inside water OR │
              │ inside forest?  │
              └───┬─────────┬───┘
                  │YES      │NO
           ┌──────▼──┐  ┌───▼──────────────┐
           │🔴 HIGH  │  │ Distance < 100m  │
           │  RISK   │  │ to water/forest? │
           └─────────┘  └──┬────────────┬──┘
                           │YES         │NO
                    ┌──────▼──┐   ┌─────▼────┐
                    │🟡 MEDIUM│   │🟢 LOW    │
                    │  RISK   │   │  RISK    │
                    └─────────┘   └──────────┘
```

### Classification Summary

| Risk Level | Condition | Threshold |
|------------|-----------|-----------|
| 🔴 **HIGH** | Point is **inside** a water body or forest zone | distance = 0 m |
| 🟡 **MEDIUM** | Point is **within 100 meters** of a water body or forest zone | 0 < distance < 100 m |
| 🟢 **LOW** | Point is **more than 100 meters** from all sensitive zones | distance ≥ 100 m |

---

## 5. Risk Level Explanations

### 🔴 HIGH Risk

**Environmental Reasoning:**
The selected location falls directly inside a protected water body (lake, river, reservoir) or a designated forest zone. Construction at this location would cause direct environmental damage — destroying aquatic ecosystems, disrupting water flow patterns, or resulting in deforestation.

**Legal Implications:**
- Violates the **Water (Prevention and Control of Pollution) Act**
- Violates the **Forest Conservation Act**
- Construction permits will be **denied** by environmental regulatory authorities
- Subject to legal penalties and mandatory demolition orders

**Recommendation:** ❌ **Not suitable for construction.** Do not proceed.

---

### 🟡 MEDIUM Risk

**Environmental Reasoning:**
The location is within a 100-meter buffer zone of a water body or forest zone. While not directly inside a protected area, construction this close can cause indirect damage — soil erosion, water pollution from runoff, disruption of wildlife corridors, and degradation of riparian buffer zones.

**Legal Implications:**
- May fall under **Coastal Regulation Zone (CRZ)** or buffer zone restrictions
- Construction may require **Environmental Impact Assessment (EIA)** clearance
- Additional permits and environmental conditions may apply
- Risk of future regulatory changes restricting the property

**Recommendation:** ⚠️ **Use caution.** Proceed only with proper environmental clearances and expert consultation.

---

### 🟢 LOW Risk

**Environmental Reasoning:**
The location is at a safe distance (more than 100 meters) from all mapped water bodies and forest zones. No direct or indirect environmental impact is anticipated from construction activities at this location.

**Legal Implications:**
- No environmental zone violations detected
- Standard construction permits should be obtainable
- No special environmental clearances anticipated
- Normal building regulations apply

**Recommendation:** ✅ **Safe to proceed** with standard construction permits and approvals.

---

## 6. Example Scenarios

### Scenario 1: Inside a Lake — 🔴 HIGH Risk

| Parameter | Value |
|-----------|-------|
| Location | Latitude: 9.8500, Longitude: 76.2000 |
| Water body | Inside Lake Vembanad |
| Forest zone | 9,039 meters away |
| **Overall Risk** | **HIGH** |
| Reason | Point falls directly inside a major lake |
| Legal status | Not suitable for construction |

---

### Scenario 2: Near a Forest — 🟡 MEDIUM Risk

| Parameter | Value |
|-----------|-------|
| Location | Latitude: 9.9250, Longitude: 76.1480 |
| Water body | 1,200 meters away |
| Forest zone | 45 meters away |
| **Overall Risk** | **MEDIUM** |
| Reason | Within 100m buffer zone of Forest Zone A |
| Legal status | Environmental clearance required |

---

### Scenario 3: Open Land — 🟢 LOW Risk

| Parameter | Value |
|-----------|-------|
| Location | Latitude: 12.9768, Longitude: 77.5901 (Bangalore) |
| Water body | 377,848 meters away |
| Forest zone | 371,700 meters away |
| **Overall Risk** | **LOW** |
| Reason | Safe distance from all environmental zones |
| Legal status | Suitable for construction |

---

## 7. System Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Frontend (Browser)                  │
│  ┌──────────┐  ┌───────────┐  ┌───────────────────────┐ │
│  │ Leaflet  │  │ Location  │  │ Risk Analysis Results │ │
│  │ Map      │  │ Search    │  │ & Explanations        │ │
│  └──────────┘  └───────────┘  └───────────────────────┘ │
└───────────────────────┬──────────────────────────────────┘
                        │ REST API (JSON)
┌───────────────────────▼──────────────────────────────────┐
│                    Backend (Flask)                        │
│  ┌───────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │ Geocoding │  │ Spatial      │  │ GeoJSON Data      │ │
│  │ (Nominatim│  │ Analysis     │  │ Files             │ │
│  │  API)     │  │ Engine       │  │                   │ │
│  └───────────┘  └──────────────┘  └───────────────────┘ │
└──────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology |
|-----------|------------|
| Backend | Python, Flask, GeoPandas, Shapely |
| Frontend | HTML5, CSS3, JavaScript, Leaflet.js |
| Geocoding | OpenStreetMap Nominatim API |
| Spatial Data | GeoJSON (EPSG:4326) |
| Distance Calculation | Projected coordinates (EPSG:3857) |

---

## 8. Limitations

1. **Data Coverage**: Risk assessment is limited to mapped water bodies and forest zones in the GeoJSON data files. Areas not covered in the dataset will show as LOW risk even if real-world hazards exist.

2. **Buffer Threshold**: The 100-meter threshold for MEDIUM risk is a simplified approximation. Real-world buffer zones vary by regulation, zone type, and jurisdiction.

3. **2D Analysis**: The system performs 2D distance calculations. Elevation, slope, and terrain are not considered.

4. **Static Data**: GeoJSON data is not updated in real-time. Changes to water body boundaries or forest zone designations are not automatically reflected.

5. **Rule-Based**: The system uses deterministic rules rather than probabilistic ML models. It does not account for cumulative risk from multiple nearby zones beyond the simple HIGH/MEDIUM/LOW classification.
