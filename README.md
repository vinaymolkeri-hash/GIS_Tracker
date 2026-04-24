# GIS Tracker - Geospatial Land Safety & Compliance Analyzer

GIS Tracker is a geospatial decision-support system that analyzes land safety using GIS data and rule-based spatial intelligence. It enables users to evaluate whether a location is suitable for development by validating it against environmental constraints such as water bodies and forest zones.

The system provides risk classification (`HIGH` / `MEDIUM` / `LOW`), explainable reasoning, and purpose-based recommendations, making complex GIS analysis accessible to non-technical users.

## Project Overview

This project is designed to make land-risk analysis more transparent, practical, and demo-friendly. In addition to GIS-based classification, it includes reverse geocoding, structured reasoning, and an interactive map interface so users can understand both the result and the reason behind it.

## Features

- Location input using coordinates or place name
- Forward geocoding for place-name search
- Reverse geocoding for coordinate-based analysis
- Interactive map visualization with Leaflet
- Water body and forest validation using GeoJSON layers and OpenStreetMap integration
- Rule-based land risk classification
- Explainable reasoning engine for each risk result
- Purpose-based recommendations for residential, farming, and commercial use
- Fast backend response with spatial indexing and lightweight API integration

## Demo Preview

<img src="screenshots/demo.png" alt="GIS Tracker Demo" width="800"/>

- Interactive map with layer overlays
- Real-time risk classification
- Explainable reasoning and recommendations

## System Flow

```text
Input (Location / Coordinates)
→ Geocoding / Reverse Geocoding
→ Spatial Analysis (Water + Forest)
→ Feature Extraction (Inside / Distance)
→ Rule-Based Risk Classification
→ Explanation + Recommendation
→ Output + Map Visualization
```

## How It Works

1. The user enters a location as coordinates or a place name.
2. If a place name is provided, the system geocodes it to latitude and longitude.
3. If coordinates are provided, the system reverse geocodes them into a readable location name.
4. The spatial engine checks:
   - whether the point lies inside a water body
   - whether the point lies inside a forest zone
   - distance to nearby environmental layers
5. The rule engine classifies risk:
   - `HIGH` if the location is inside restricted zones
   - `MEDIUM` if the location is within 100 meters of restricted zones
   - `LOW` if the location is at a safe distance
6. The system returns:
   - risk level
   - triggered factors
   - detailed explanation
   - recommendation
   - map visualization context

## Tech Stack

- Backend: Python, Flask
- Geospatial Processing: GeoPandas, Shapely
- Frontend: HTML, CSS, JavaScript
- Mapping: Leaflet.js
- Data Format: GeoJSON
- External API: OpenStreetMap Nominatim, Overpass API

## Project Structure

```text
ML_GIS_Project/
├── server.py
├── utils/
│   └── spatial.py
├── data/
│   ├── water_bodies.geojson
│   └── forest_zones.geojson
├── static/
│   ├── index.html
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js
├── app.py
├── test_logic.py
├── check_data.py
├── METHODOLOGY.md
├── requirements.txt
└── README.md
```

## Risk Logic

- `HIGH`: The location lies inside a water body, sea/ocean, forest zone, or protected area
- `MEDIUM`: The location is within 100 meters of a sensitive environmental layer
- `LOW`: The location is outside all restricted and buffer zones

## Explainability

The system includes a deterministic reasoning engine that explains why a result was assigned. Explanations are based directly on spatial conditions such as:

- inside water body
- inside forest zone
- distance to water
- distance to forest

The response includes:

- triggered factors
- detailed explanation
- purpose-based recommendation
- legal suitability message

## Installation

```bash
git clone <your-repo-link>
cd ML_GIS_Project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python server.py
```

## Running the Project

By default, the Flask app runs on:

```text
http://127.0.0.1:5001
```

Open that URL in your browser after starting the server.

## API Input Options

The main analysis endpoint accepts:

- `lat` and `lon`
- `location_name`
- optional `purpose`

Supported purpose values:

- `residential`
- `farming`
- `commercial`

## Example Output

```text
Location: Nallamala Forest, Andhra Pradesh, India
Risk Level: HIGH

Triggered Factors:
- Inside forest zone

Explanation:
The selected location lies within a protected forest region, where construction and development are legally restricted.

Recommendation:
Not suitable for residential development.
```

## Use Cases

- Land safety analysis before construction
- Environmental compliance screening
- Academic GIS demonstration projects
- Rule-based land suitability evaluation
- Explainable geospatial decision support

## Future Improvements

- Add database-backed caching for location lookups
- Support more environmental layers
- Export downloadable reports
- Add user authentication and saved analyses
- Improve test coverage for API and UI flows

## Limitations

- Uses static GeoJSON datasets rather than real-time KGIS or live government feeds
- Limited environmental layers in the current version (water + forest)
- Intended for analysis and screening, not legal certification

## Design Principle

This system uses a deterministic rule-based geospatial engine instead of black-box machine learning to ensure transparency, explainability, and reliability for real-world decision-making.

## Author

Developed as a geospatial land safety and compliance analysis project using Python, GIS, and web mapping tools.
