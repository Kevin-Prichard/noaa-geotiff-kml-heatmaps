import json
import math


import geopandas as gpd


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

    column = get_road_type_column(map, column)

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


def find_and_save_pydeck_road_type_animation(map: gpd.GeoDataFrame,
                                             road_types,
                                             output_path: str,
                                             geo_obj=None,
                                             column: str | None = None,
                                             exact: bool = True,
                                             case_sensitive: bool = False,
                                             limit: int | None = None,
                                             **animation_kwargs):
    """
    Convenience wrapper that filters a map by road type and writes the pydeck
    HTML animation in one step.

    Returns ``(roads, output_pathname)``.
    """
    roads = find_roads_by_type(
        map,
        road_types,
        column=column,
        exact=exact,
        case_sensitive=case_sensitive,
    )

    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        roads = roads.head(limit).copy()
        roads.attrs["road_type_column"] = get_road_type_column(map, column)
        roads.attrs["road_types"] = [
            str(road_types)
        ] if isinstance(road_types, str) else [str(value) for value in road_types]

    output = save_pydeck_road_type_animation(
        map,
        roads,
        output_path,
        geo_obj=geo_obj,
        **animation_kwargs,
    )
    return roads, output


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
        road_type_column = get_road_type_column(roads_wgs84)

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


def get_road_type_column(map: gpd.GeoDataFrame, column: str | None = None) -> str:
    if column is not None:
        if column not in map.columns:
            raise KeyError(
                f"Requested road type column {column!r} not found. "
                f"Available columns: {list(map.columns)}"
            )
        return column

    candidates = (
        "highway",
        "road_type",
        "fclass",
        "class",
        "type",
        "highway_type",
    )
    detected = next((name for name in candidates if name in map.columns), None)
    if detected is None:
        raise KeyError(
            "Could not determine a road type column. "
            f"Available columns: {list(map.columns)}"
        )
    return detected
