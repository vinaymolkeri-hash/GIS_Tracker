from utils.spatial import check_water_risk

# Try different coordinates
tests = [
    (9.85, 76.2),   # maybe inside
    (9.9, 76.3),    # near
    (10.5, 77.0)    # far
]

for lat, lon in tests:
    risk, reason = check_water_risk(lat, lon)
    print(f"{lat}, {lon} → {risk} ({reason})")
