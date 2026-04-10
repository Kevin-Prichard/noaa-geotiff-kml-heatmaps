#!/usr/bin/env python3

import json
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


def find_roads_by_type(map: gpd.GeoDataFrame,
                       road_types,
                       column: str | None = None,
                       exact: bool = True,
                       case_sensitive: bool = False) -> gpd.GeoDataFrame:
    """
    Filter an OSM-derived roads GeoDataFrame by road type.

    Typical values are things like ``trunk``, ``track``, ``motorway``,
    ``primary``, etc. If `column` is not provided, the function tries common
    OSM-style road type columns such as `highway`.
    """
    if isinstance(road_types, str):
        road_types = [road_types]

    wanted = [str(value) for value in road_types]
    if not wanted:
        raise ValueError("road_types must contain at least one value")

    if column is None:
        candidates = (
            "highway",
            "road_type",
            "fclass",
            "class",
            "type",
            "highway_type",
        )
        column = next((name for name in candidates if name in map.columns), None)

    if column is None or column not in map.columns:
        raise KeyError(
            "Could not determine a road type column. "
            f"Available columns: {list(map.columns)}"
        )

    values = map[column].fillna("").astype(str)
    if case_sensitive:
        compare_values = values
        compare_wanted = set(wanted)
    else:
        compare_values = values.str.casefold()
        compare_wanted = {value.casefold() for value in wanted}

    if exact:
        mask = compare_values.isin(compare_wanted)
    else:
        mask = compare_values.apply(
            lambda value: any(target in value for target in compare_wanted)
        )

    matches = map.loc[mask].copy()
    matches.attrs["road_type_column"] = column
    matches.attrs["road_types"] = wanted
    return matches


def _bounds_to_pydeck_view_state(bounds,
                                 width: int = 1280,
                                 height: int = 720,
                                 padding: int = 80,
                                 bearing: float = 0.0,
                                 pitch: float = 0.0,
                                 min_zoom: float = 1.0,
                                 max_zoom: float = 18.0):
    min_lon, min_lat, max_lon, max_lat = [float(value) for value in bounds]

    if min_lon == max_lon:
        min_lon -= 0.0005
        max_lon += 0.0005
    if min_lat == max_lat:
        min_lat -= 0.0005
        max_lat += 0.0005

    def lat_rad(lat_deg):
        sin_value = math.sin(math.radians(lat_deg))
        rad_x2 = math.log((1 + sin_value) / (1 - sin_value)) / 2
        return max(min(rad_x2, math.pi), -math.pi) / 2

    def zoom(map_pixels, world_pixels, fraction):
        fraction = max(fraction, 1e-9)
        return math.log(map_pixels / world_pixels / fraction, 2)

    usable_width = max(width - (2 * padding), int(width * 0.2))
    usable_height = max(height - (2 * padding), int(height * 0.2))

    lat_fraction = (lat_rad(max_lat) - lat_rad(min_lat)) / math.pi
    lon_diff = max_lon - min_lon
    if lon_diff < 0:
        lon_diff += 360
    lon_fraction = lon_diff / 360

    lat_zoom = zoom(usable_height, 512, lat_fraction)
    lon_zoom = zoom(usable_width, 512, lon_fraction)

    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2
    zoom_level = max(min(min(lat_zoom, lon_zoom), max_zoom), min_zoom)

    return {
        "longitude": center_lon,
        "latitude": center_lat,
        "zoom": zoom_level,
        "bearing": bearing,
        "pitch": pitch,
    }


def _geometry_to_path_records(geom):
    if geom is None or geom.is_empty:
        return []

    geom_type = geom.geom_type

    if geom_type == "LineString":
        return [{"path": [list(coord) for coord in geom.coords]}]

    if geom_type == "MultiLineString":
        return [
            {"path": [list(coord) for coord in part.coords]}
            for part in geom.geoms
            if not part.is_empty
        ]

    if geom_type == "GeometryCollection":
        records = []
        for part in geom.geoms:
            records.extend(_geometry_to_path_records(part))
        return records

    return []


def save_pydeck_road_type_animation(map: gpd.GeoDataFrame,
                                    roads: gpd.GeoDataFrame,
                                    output_path: str,
                                    geo_obj=None,
                                    fps: int = 30,
                                    zoom_in_frames: int = 45,
                                    linger_frames: int = 30,
                                    zoom_out_frames: int = 45,
                                    initial_frames: int = 30,
                                    width: int = 1280,
                                    height: int = 720,
                                    overview_padding: int = 80,
                                    focus_padding: int = 140,
                                    map_line_width: int = 1,
                                    highlight_line_width: int = 5,
                                    map_style=None):
    """
    Write a standalone pydeck/deck.gl HTML animation for road-type results.

    Animation sequence for each matched road:
      1. Show the full map extent.
      2. Multi-frame zoom into the highlighted road.
      3. Linger on that road for `linger_frames`.
      4. Zoom back out to the full-map extent.

    The output is an HTML file intended to be opened in a browser.
    """
    from pathlib import Path

    if roads is None or roads.empty:
        raise ValueError("`roads` is empty; nothing to animate.")

    map_wgs84 = map.to_crs("EPSG:4326")
    roads_wgs84 = roads.to_crs("EPSG:4326").copy()

    if geo_obj is not None:
        geo_wgs84 = geo_obj.to_crs("EPSG:4326")
        center_geom = geo_wgs84.geometry.iloc[0]
        center_point_data = [{"position": [center_geom.x, center_geom.y]}]
    else:
        center_point_data = []

    road_type_column = roads.attrs.get("road_type_column")
    if road_type_column is None:
        for candidate in ("highway", "road_type", "fclass", "class", "type"):
            if candidate in roads_wgs84.columns:
                road_type_column = candidate
                break

    overview_view_state = _bounds_to_pydeck_view_state(
        map_wgs84.total_bounds,
        width=width,
        height=height,
        padding=overview_padding,
    )

    road_animation_data = []
    for road_number, (_, row) in enumerate(roads_wgs84.iterrows(), start=1):
        path_records = _geometry_to_path_records(row.geometry)
        if not path_records:
            continue

        label_parts = [f"road {road_number}"]
        if road_type_column and road_type_column in row.index:
            label_parts.append(f"{road_type_column}={row[road_type_column]}")
        if "name" in row.index and row["name"] not in (None, ""):
            label_parts.append(f"name={row['name']}")
        elif "ref" in row.index and row["ref"] not in (None, ""):
            label_parts.append(f"ref={row['ref']}")

        if "distance_m" in row.index and row["distance_m"] == row["distance_m"]:
            label_parts.append(f"distance={float(row['distance_m']):.1f} m")

        road_animation_data.append({
            "label": " | ".join(label_parts),
            "paths": path_records,
            "view_state": _bounds_to_pydeck_view_state(
                row.geometry.bounds,
                width=width,
                height=height,
                padding=focus_padding,
                min_zoom=overview_view_state["zoom"],
                max_zoom=19.0,
            ),
        })

    if not road_animation_data:
        raise ValueError("No line geometries were available to animate.")

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Road type animation</title>
  <script src=\"https://unpkg.com/deck.gl@latest/dist.min.js\"></script>
  <style>
    html, body, #deck-container {{
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #ffffff;
      font-family: sans-serif;
    }}
    #status {{
      position: absolute;
      top: 14px;
      left: 14px;
      z-index: 10;
      background: rgba(255, 255, 255, 0.92);
      padding: 10px 12px;
      border-radius: 6px;
      box-shadow: 0 1px 6px rgba(0, 0, 0, 0.2);
      max-width: 38rem;
      line-height: 1.35;
    }}
    #status .subtitle {{
      color: #555;
      margin-top: 4px;
      font-size: 0.92rem;
    }}
  </style>
</head>
<body>
  <div id=\"deck-container\"></div>
  <div id=\"status\">
    <div><strong>Road type animation</strong></div>
    <div id=\"status-line\">Overview</div>
    <div class=\"subtitle\">Blue road = current match</div>
  </div>
  <script>
    const MAP_GEOJSON = {json.dumps(json.loads(map_wgs84.to_json()))};
    const CENTER_POINTS = {json.dumps(center_point_data)};
    const OVERVIEW_VIEW_STATE = {json.dumps(overview_view_state)};
    const ROADS = {json.dumps(road_animation_data)};
    const SETTINGS = {{
      fps: {int(fps)},
      zoomInFrames: {int(zoom_in_frames)},
      lingerFrames: {int(linger_frames)},
      zoomOutFrames: {int(zoom_out_frames)},
      initialFrames: {int(initial_frames)},
      mapStyle: {json.dumps(map_style)},
      mapLineWidth: {int(map_line_width)},
      highlightLineWidth: {int(highlight_line_width)},
      width: {int(width)},
      height: {int(height)}
    }};

    const statusLine = document.getElementById('status-line');

    function easeInOut(t) {{
      return t < 0.5
        ? 4 * t * t * t
        : 1 - Math.pow(-2 * t + 2, 3) / 2;
    }}

    function interpolateView(a, b, t) {{
      return {{
        longitude: a.longitude + ((b.longitude - a.longitude) * t),
        latitude: a.latitude + ((b.latitude - a.latitude) * t),
        zoom: a.zoom + ((b.zoom - a.zoom) * t),
        bearing: a.bearing + ((b.bearing - a.bearing) * t),
        pitch: a.pitch + ((b.pitch - a.pitch) * t)
      }};
    }}

    function buildLayers(currentRoad) {{
      const layers = [
        new deck.GeoJsonLayer({{
          id: 'base-map',
          data: MAP_GEOJSON,
          stroked: true,
          filled: false,
          pickable: true,
          getLineColor: [191, 191, 191],
          lineWidthMinPixels: SETTINGS.mapLineWidth,
          lineWidthScale: 1
        }})
      ];

      if (CENTER_POINTS.length) {{
        layers.push(new deck.ScatterplotLayer({{
          id: 'center-point',
          data: CENTER_POINTS,
          pickable: false,
          stroked: true,
          filled: true,
          radiusMinPixels: 7,
          lineWidthMinPixels: 1,
          getPosition: d => d.position,
          getFillColor: [255, 215, 0],
          getLineColor: [0, 0, 0]
        }}));
      }}

      if (currentRoad && currentRoad.paths.length) {{
        layers.push(new deck.PathLayer({{
          id: 'highlight-road',
          data: currentRoad.paths,
          pickable: false,
          widthUnits: 'pixels',
          getPath: d => d.path,
          getColor: [65, 105, 225],
          getWidth: SETTINGS.highlightLineWidth,
          widthMinPixels: SETTINGS.highlightLineWidth
        }}));
      }}

      return layers;
    }}

    const deckgl = new deck.DeckGL({{
      container: 'deck-container',
      controller: true,
      initialViewState: OVERVIEW_VIEW_STATE,
      viewState: OVERVIEW_VIEW_STATE,
      mapStyle: SETTINGS.mapStyle,
      layers: buildLayers(null)
    }});

    let phase = 'initial';
    let phaseFrame = 0;
    let roadIndex = 0;

    function stepAnimation() {{
      if (roadIndex >= ROADS.length) {{
        statusLine.textContent = `Done (${{ROADS.length}} roads)`;
        deckgl.setProps({{viewState: OVERVIEW_VIEW_STATE, layers: buildLayers(null)}});
        return;
      }}

      const road = ROADS[roadIndex];
      let viewState = OVERVIEW_VIEW_STATE;
      let currentRoad = null;

      if (phase === 'initial') {{
        statusLine.textContent = `Overview | road 1/${{ROADS.length}} coming up`;
      }} else if (phase === 'zoomIn') {{
        const t = easeInOut((phaseFrame + 1) / Math.max(SETTINGS.zoomInFrames, 1));
        viewState = interpolateView(OVERVIEW_VIEW_STATE, road.view_state, t);
        currentRoad = road;
        statusLine.textContent = `Zooming in | ${{road.label}}`;
      }} else if (phase === 'linger') {{
        viewState = road.view_state;
        currentRoad = road;
        statusLine.textContent = `Highlight | ${{road.label}}`;
      }} else if (phase === 'zoomOut') {{
        const t = easeInOut((phaseFrame + 1) / Math.max(SETTINGS.zoomOutFrames, 1));
        viewState = interpolateView(road.view_state, OVERVIEW_VIEW_STATE, t);
        currentRoad = road;
        statusLine.textContent = `Zooming out | ${{road.label}}`;
      }}

      deckgl.setProps({{
        viewState,
        layers: buildLayers(currentRoad)
      }});

      phaseFrame += 1;

      if (phase === 'initial' && phaseFrame >= SETTINGS.initialFrames) {{
        phase = 'zoomIn';
        phaseFrame = 0;
      }} else if (phase === 'zoomIn' && phaseFrame >= SETTINGS.zoomInFrames) {{
        phase = 'linger';
        phaseFrame = 0;
      }} else if (phase === 'linger' && phaseFrame >= SETTINGS.lingerFrames) {{
        phase = 'zoomOut';
        phaseFrame = 0;
      }} else if (phase === 'zoomOut' && phaseFrame >= SETTINGS.zoomOutFrames) {{
        roadIndex += 1;
        phase = 'zoomIn';
        phaseFrame = 0;
      }}

      window.setTimeout(() => window.requestAnimationFrame(stepAnimation), 1000 / SETTINGS.fps);
    }}

    stepAnimation();
  </script>
</body>
</html>
"""

    output = Path(output_path)
    output.write_text(html, encoding="utf-8")
    return str(output)


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
    main()
