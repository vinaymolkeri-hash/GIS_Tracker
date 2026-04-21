import geopandas as gpd


def main():
    gdf = gpd.read_file("data/water_bodies.geojson")
    print(gdf.head())
    print("Loaded successfully")


if __name__ == "__main__":
    main()
