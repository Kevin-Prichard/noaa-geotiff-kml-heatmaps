#!/usr/bin/env python3.13

import argparse
import math
import sys
from time import time

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point, box

# import pudb

def get_args(argv):
    parser = argparse.ArgumentParser(description="Find nearby roads from OSM map data")
    parser.add_argument(
        "-m",
        "--map",
        dest="map_path",
        required=True,
        help="Path to OSM map file (e.g. .fgb or .gpkg) containing road geometries",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        required=True,
        help="Path to save the nearest roads animation (GIF or MP4)",
    )
    parser.add_argument(
        "-b", "--bbox", dest="bbox", nargs=4, type=float,
        metavar=("LON0", "LAT0", "LON1", "LAT1"),
        help="Bounding box to load from the map "
             "(e.g. -b 38.14, -122.96, 37.30, -121.78)")
    parser.add_argument(
        "-p", "--point", dest="point", nargs=2, type=float,
        metavar=("LON", "LAT"),
        required=True,
        help="Longitude and latitude of the query point "
             "(e.g. -p 37.8830540094364, -121.91480703843266)")
    parser.add_argument(
        "-n",
        "--nearest",
        dest="nearest_n",
        type=int,
        default=10,
        help="Number of nearest roads to find and animate",
    )
    parser.add_argument(
        "-r",
        "--radius",
        dest="radius_m",
        type=float,
        default=50.0,
        help="Search radius in meters for finding nearby roads (used in find_roads)",
    )
    return parser.parse_args(argv)

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


def save_nearest_roads_animation(map: gpd.GeoDataFrame,
                                 geo_obj,
                                 nearest: gpd.GeoDataFrame,
                                 output_path: str,
                                 fps: int = 30,
                                 highlight_frames: int = 30,
                                 reset_frames: int = 1,
                                 initial_frames: int = 1,
                                 figsize=(10, 10),
                                 dpi: int = 200,
                                 pad_ratio: float = 0.10):
    """
    Save an animation of nearest roads to GIF or MP4.

    Animation sequence:
    - initial frame(s): gray map + yellow query point
    - for each road in `nearest`:
        - show that road in blue for `highlight_frames`
        - then hide it for `reset_frames`
        - move to the next road

    `output_path` suffix determines writer:
      - .gif -> PillowWriter
      - .mp4 -> FFMpegWriter
    """
    from pathlib import Path
    from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter
    from matplotlib.collections import LineCollection

    if nearest is None or nearest.empty:
        raise ValueError("`nearest` is empty; nothing to animate.")

    print("saving... 0")
    map_wgs84 = map.to_crs("EPSG:4326")
    geo_wgs84 = geo_obj.to_crs("EPSG:4326")
    nearest_wgs84 = nearest.to_crs("EPSG:4326").copy()

    if 'distance_m' in nearest_wgs84.columns:
        nearest_wgs84 = nearest_wgs84.sort_values('distance_m')
    print("saving... 1")

    def geometry_to_segments(geom):
        if geom is None or geom.is_empty:
            return []

        geom_type = geom.geom_type

        if geom_type == "LineString":
            return [list(geom.coords)]

        if geom_type == "MultiLineString":
            return [list(part.coords) for part in geom.geoms if not part.is_empty]

        if geom_type == "GeometryCollection":
            segments = []
            for part in geom.geoms:
                segments.extend(geometry_to_segments(part))
            return segments

        return []

    segments_by_index = {
        idx: geometry_to_segments(geom)
        for idx, geom in nearest_wgs84.geometry.items()
    }
    print("saving... 2")

    ordered_indices = list(nearest_wgs84.index)
    total_roads = len(ordered_indices)
    print("saving... 3")

    frame_plan = [None] * initial_frames
    for idx in ordered_indices:
        frame_plan.extend([idx] * highlight_frames)
        frame_plan.extend([None] * reset_frames)

    fig, ax = plt.subplots(figsize=figsize)
    print("saving... 4")

    # Static background
    map_wgs84.plot(
        ax=ax,
        edgecolor="#bfbfbf",
        linewidth=0.6,
        alpha=0.8,
        zorder=1,
    )

    center_geom = geo_wgs84.geometry.iloc[0]
    ax.scatter(
        [center_geom.x],
        [center_geom.y],
        s=100,
        c="gold",
        edgecolors="black",
        linewidths=1.0,
        zorder=5,
    )

    # Animated road highlight
    highlight = LineCollection(
        [],
        colors=["#4169E1"],
        linewidths=3.0,
        zorder=4,
    )
    ax.add_collection(highlight)

    status_text = ax.text(
        0.02,
        0.98,
        "",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=11,
        bbox=dict(facecolor="white", edgecolor="none", alpha=0.75),
        zorder=6,
    )
    print("saving... 5")

    # Zoom to query point + nearest roads rather than full map extent
    bounds_list = [geo_wgs84.total_bounds, nearest_wgs84.total_bounds]
    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)
    print("saving... 6")

    dx = maxx - minx
    dy = maxy - miny
    padx = max(dx * pad_ratio, 0.001)
    pady = max(dy * pad_ratio, 0.001)

    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - pady, maxy + pady)

    ax.set_title("Nearest roads animation")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    road_number_by_index = {
        idx: n for n, idx in enumerate(ordered_indices, start=1)
    }
    print("saving... 7")

    def update(frame_idx):
        current_idx = frame_plan[frame_idx]

        if current_idx is None:
            highlight.set_segments([])
            status_text.set_text("Base map")
        else:
            highlight.set_segments(segments_by_index[current_idx])
            road_num = road_number_by_index[current_idx]
            if 'distance_m' in nearest_wgs84.columns:
                dist = nearest_wgs84.loc[current_idx, 'distance_m']
                status_text.set_text(
                    f"Nearest road {road_num}/{total_roads}   distance={dist:.1f} m"
                )
            else:
                status_text.set_text(f"Nearest road {road_num}/{total_roads}")

        return highlight, status_text

    anim = FuncAnimation(
        fig,
        update,
        frames=len(frame_plan),
        interval=1000 / fps,
        blit=False,
        repeat=False,
    )
    print("saving... 8")

    output = Path(output_path)
    suffix = output.suffix.lower()

    if suffix == ".gif":
        writer = PillowWriter(fps=fps)
    elif suffix == ".mp4":
        writer = FFMpegWriter(fps=fps, codec="libx264", bitrate=12000)
    else:
        plt.close(fig)
        raise ValueError("output_path must end with .gif or .mp4")

    print("saving... 9")

    anim.save(str(output), writer=writer, dpi=dpi)
    plt.close(fig)
    print("saving... 10")
    return str(output)


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


def main(args):
    # pu.db
    local_area = bbox(*args.bbox)
    map = load_map(args.map_path, bbox=local_area)
    pt = point(*args.point)
    roads = find_roads(pt, map, 50)
    nearest = find_roads_nn(pt, map, nearest_n=10)
    print("roads found:", len(roads))
    print("nearest found:", len(nearest))
    fig, ax = plot_road_search(map, pt, roads=roads, nearest=nearest, radius_m=50)
    print(ax.collections[-1].get_edgecolor())
    # plt.show()
    save_nearest_roads_animation(
        map,
        pt,
        nearest,
        "/home/kev/projs/thucy/nav/nearest_roads.gif",
    )

    save_nearest_roads_animation(
        map,
        pt,
        nearest,
        "/home/kev/projs/thucy/nav/nearest_roads.mp4",
    )


if __name__ == '__main__':
    args = get_args(sys.argv[1:])
    main(args)
