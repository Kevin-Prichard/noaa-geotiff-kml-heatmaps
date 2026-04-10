#!/usr/bin/env python3

import math
from time import time

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point, LineString, box
from shapely.ops import transform

import pudb


def bbox(lon0, lat0, lon1, lat1):
    return gpd.GeoSeries([Point(lon0, lat0), Point(lon1, lat1)],
                         crs="EPSG:4326")


def load_map(path, bbox: box=None) -> gpd.GeoDataFrame:
    start = time()
    map = gpd.read_file(path, bbox=bbox, layer='lines')
    print('load_map', time()-start)
    return map


def point(lon, lat) -> gpd.GeoSeries:
    pt = Point(lon, lat)
    return gpd.GeoSeries([pt], crs="EPSG:4326")


def get_centroid(obj):
    obj_wgs84 = obj.to_crs("EPSG:4326")
    bounds = obj_wgs84.total_bounds
    center_lon = (bounds[0] + bounds[2]) / 2
    center_lat = (bounds[1] + bounds[3]) / 2
    return center_lon, center_lat


def get_gdf_epsg(gdf):
    c = get_centroid(gdf)
    zone = math.floor((c[0] + 180) / 6) + 1

    # northern hemisphere prefix is 326xx, Southern is 327xx
    epsg = zone + (32600 if c[1] >= 0 else 32700)
    return f"EPSG:{epsg}"


def proj_m(thing, target_crs=None):
    if target_crs is None:
        target_crs = get_gdf_epsg(thing)
    return thing.to_crs(target_crs)


def find_roads(geo_obj, map: gpd.GeoDataFrame, radius_m: float):
    start = time()
    target_crs = get_gdf_epsg(geo_obj)
    geo_obj_m = proj_m(geo_obj, target_crs)
    map_m = proj_m(map, target_crs)
    area = geo_obj_m.union_all().buffer(radius_m)
    mask = map_m.intersects(area)
    matches = map.loc[mask].copy()
    print('find_roads', time()-start)
    return matches


def find_roads_nn(geo_obj, map: gpd.GeoDataFrame, nearest_n: int=10):
    start = time()
    target_crs = get_gdf_epsg(geo_obj)
    geo_obj_m = proj_m(geo_obj, target_crs)
    map_m = proj_m(map, target_crs)
    distances_m = map_m.distance(geo_obj_m.union_all())
    nearest_idx = distances_m.sort_values().head(nearest_n).index
    nearest = map.loc[nearest_idx].copy()
    nearest['distance_m'] = distances_m.loc[nearest_idx]
    print('find_roads_nn', time()-start)
    return nearest


def plot_road_search(map: gpd.GeoDataFrame,
                     geo_obj,
                     roads: gpd.GeoDataFrame | None = None,
                     nearest: gpd.GeoDataFrame | None = None,
                     radius_m: float | None = None,
                     figsize=(10, 10)):
    import matplotlib.pyplot as plt

    map_wgs84 = map.to_crs("EPSG:4326")
    geo_wgs84 = geo_obj.to_crs("EPSG:4326")
    pu.db

    target_crs = get_gdf_epsg(geo_wgs84)
    query_buffer = None
    if radius_m is not None:
        query_buffer = (
            proj_m(geo_wgs84, target_crs)
            .union_all()
            .buffer(radius_m)
        )
        query_buffer = gpd.GeoSeries([query_buffer], crs=target_crs).to_crs("EPSG:4326")

    roads_wgs84 = None if roads is None else roads.to_crs("EPSG:4326")
    nearest_wgs84 = None if nearest is None else nearest.to_crs("EPSG:4326")

    fig, ax = plt.subplots(figsize=figsize)

#    map_wgs84.plot(ax=ax, color="lightgray", linewidth=0.6, alpha=0.7)
    map_wgs84.plot(ax=ax, edgecolor="#bfbfbf", linewidth=0.6, alpha=0.7, zorder=1,)

    if query_buffer is not None:
        start = len(ax.collections)
        query_buffer.boundary.plot(
            ax=ax,
            color="deepskyblue",
            linewidth=1.5,
            linestyle="--",
            label=f"search radius ({radius_m} m)",
        )
        debug_new_collections(ax, "buffer", start)

    if roads_wgs84 is not None and not roads_wgs84.empty:
        start = len(ax.collections)
        roads_wgs84.plot(
            ax=ax,
            # color="royalblue",
            edgecolor="#4169E1",
            linewidth=2.0,
            alpha=1.0,
            zorder=3,
            label="find_roads",
        )
        debug_new_collections(ax, "roads", start)

    if nearest_wgs84 is not None and not nearest_wgs84.empty:
        start = len(ax.collections)
        nearest_wgs84.plot(
            ax=ax,
            #color="crimson",
            edgecolor="#DC143C",
            linewidth=2.5,
            zorder=4,
            label="find_roads_nn",
        )
        debug_new_collections(ax, "nearest", start)

    start = len(ax.collections)
    geo_wgs84.plot(
        ax=ax,
        color="gold",
        edgecolor="black",
        markersize=80,
        label="query point",
        zorder=5,
    )
    debug_new_collections(ax, "query_point", start)

    ax.set_title("Nearby roads search")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend()
    return fig, ax


def debug_new_collections(ax, label: str, start_idx: int):
    for i, col in enumerate(ax.collections[start_idx:], start=start_idx):
        edge = col.get_edgecolor()
        face = col.get_facecolor()
        lw = col.get_linewidth()
        alpha = col.get_alpha()
        z = col.get_zorder()

        edge0 = edge[0].tolist() if len(edge) else []
        face0 = face[0].tolist() if len(face) else []
        lw0 = float(lw[0]) if len(lw) else None

        print(
            f"[{label}] collection #{i} {type(col).__name__} "
            f"edge={edge0} face={face0} lw={lw0} alpha={alpha} zorder={z}"
        )


RUSSIA_MAP = "/home/kev/projs/thucy/nav/osm/ru.fgb"
def main():
    moscow_area = bbox(37.655640, 55.755713, 37.5640, 55.5713)
    map = load_map(RUSSIA_MAP, bbox=moscow_area)
    pt = point(37.6556, 55.7557)
    roads = find_roads(pt, map, 50)
    nearest = find_roads_nn(pt, map, nearest_n=10)
    print("roads found:", len(roads))
    print("nearest found:", len(nearest))
    fig, ax = plot_road_search(map, pt, roads=roads, nearest=nearest, radius_m=50)
    print(ax.collections[-1].get_edgecolor())
    plt.show()

if __name__ == '__main__':
    main()
