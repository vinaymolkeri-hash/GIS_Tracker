import json

import streamlit as st
import folium
import geopandas as gpd
from streamlit_folium import folium_static
from utils.spatial import analyze_risk

st.set_page_config(page_title="Land Safety Checker", layout="centered")

st.title("Land Safety Checker")
st.write("Enter location coordinates to check risk level")

lat = st.number_input("Latitude", value=9.85, format="%.6f")
lon = st.number_input("Longitude", value=76.2, format="%.6f")

# Load spatial data once
water = gpd.read_file("data/water_bodies.geojson")
forest = gpd.read_file("data/forest_zones.geojson")
water_geojson = json.loads(water.to_json())
forest_geojson = json.loads(forest.to_json())

if st.button("Check Safety"):
    result = analyze_risk(lat, lon)

    st.subheader(f"Risk Level: {result['risk']}")
    st.markdown("**Environmental Flags:**")
    if result["flags"]:
        for flag in result["flags"]:
            st.write(f"- {flag}")
    else:
        st.write("- None")

    st.markdown("**Water analysis:**")
    st.write(result["water_reason"])

    st.markdown("**Forest analysis:**")
    st.write(result["forest_reason"])

    st.markdown("**Legal Risk:**")
    st.write(result["legal_risk"])

    st.markdown("**Recommendation:**")
    st.write(result["recommendation"])

    m = folium.Map(location=[lat, lon], zoom_start=14)

    folium.Marker(
        [lat, lon],
        tooltip="Selected location",
        icon=folium.Icon(color="red")
    ).add_to(m)

    folium.GeoJson(
        water_geojson,
        name="Water Bodies",
        style_function=lambda feature: {
            "color": "blue",
            "fillColor": "blue",
            "fillOpacity": 0.5,
            "weight": 2,
        }
    ).add_to(m)

    folium.GeoJson(
        forest_geojson,
        name="Forest Zones",
        style_function=lambda feature: {
            "color": "green",
            "fillColor": "green",
            "fillOpacity": 0.4,
            "weight": 2,
        }
    ).add_to(m)

    folium.LayerControl().add_to(m)

    st.markdown("### Map")
    folium_static(m, width=700, height=500)

    st.markdown("### Legend")
    st.markdown("- 🔴 **Selected location**\n- 🟦 **Water Bodies**\n- 🟩 **Forest Zones**")
