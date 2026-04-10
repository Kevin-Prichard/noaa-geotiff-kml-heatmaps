#!/usr/bin/env python3

import math
from time import time

import geopandas as gpd
from pyproj import Transformer, CRS
from shapely.geometry import Point, LineString, box
from shapely.ops import transform

import pudb


def bbox(lon0, lat0, lon1, lat1):
    return gpd.GeoSeries([Point(lon0, lat0), Point(lon1, lat1)],
                         crs="EPSG:4326")


def load_map(path, bbox: box=None) -> gpd.GeoDataFrame:
    start = time()
    # pu.db
    map = gpd.read_file(path, bbox=bbox, layer='lines')
    print('load_map', time()-start)
    return map


def point(lon, lat) -> gpd.GeoSeries:
    pt = Point(lon, lat)
    zone = math.floor((pt.x + 180) / 6) + 1

    # northern hemisphere prefix is 326xx, Southern is 327xx
    epsg = zone + (32600 if pt.y >= 0 else 32700)
    epsg = f"EPSG:{epsg}"

    # always_xy=True ensures it stays in (Lon, Lat) / (X, Y) order
    transformer = Transformer.from_crs("EPSG:4326", epsg, always_xy=True)
    pt_m = transform(transformer.transform, pt)
    return gpd.GeoSeries([pt_m], crs="EPSG:4326")


def get_centroid(obj):
    pu.db
    if isinstance(obj, gpd.GeoDataFrame):
        bounds = obj.total_bounds
        center_lon = (bounds[0] + bounds[2]) / 2
        center_lat = (bounds[1] + bounds[3]) / 2
        return center_lon, center_lat
    else:
        c = obj.centroid[0]
        return c.x, c.y


def get_gdf_epsg(gdf):
    c = get_centroid(gdf)
    zone = math.floor((c[0] + 180) / 6) + 1

    # northern hemisphere prefix is 326xx, Southern is 327xx
    epsg = zone + (32600 if c[1] >= 0 else 32700)
    return f"EPSG:{epsg}"


def proj_m(thing):
    return thing.to_crs(epsg=get_gdf_epsg(thing))


def find_roads(geo_obj, map: gpd.GeoDataFrame, radius: float):
    start = time()
    area = proj_m(geo_obj).union_all().buffer(radius)
    mask = map.intersects(area)
    matches = map[mask]  # Returns only rows where intersection is True
    print('find_roads', time()-start)
    return matches


def find_roads_nn(geo_obj, map: gpd.GeoDataFrame, nearest_n: int=10):
    start = time()
    sort_col = 'temp_dist'
    map[sort_col] = map.distance(proj_m(geo_obj).union_all())
    nearest = map.sort_values(by=sort_col).head(nearest_n)
    nearest = nearest.drop(columns=[sort_col])
    print('find_roads_nn', time()-start)
    pu.db
    return nearest
    # min_dist = distances.min()
    # closest_road = map.iloc[distances.idxmin()]


RUSSIA_MAP = "/home/kev/projs/thucy/nav/osm/ru.fgb"
def main():
    pu.db
    moscow_area = bbox(37.655640, 55.755713, 37.5640, 55.5713)
    map = load_map(RUSSIA_MAP, bbox=moscow_area)
    pt = point(37.6556, 55.7557)
    roads = find_roads(pt, map, 0.0005)

if __name__ == '__main__':
    main()
