from pathlib import Path
import importlib.util

import pytest


MODULE_PATH = Path("/home/kev/projs/thucy/nav/roads_near_me.py")
TEST_BBOX = (37.655640, 55.755713, 37.5640, 55.5713)
ROAD_TYPE_CANDIDATES = [
    "trunk",
    "track",
    "motorway",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
]


@pytest.fixture(scope="module")
def roads_near_me_module():
    spec = importlib.util.spec_from_file_location("roads_near_me", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def small_map(roads_near_me_module):
    bbox = roads_near_me_module.bbox(*TEST_BBOX)
    map_gdf = roads_near_me_module.load_map(roads_near_me_module.RUSSIA_MAP, bbox=bbox)
    assert not map_gdf.empty
    return map_gdf


@pytest.fixture(scope="module")
def detected_road_type(roads_near_me_module, small_map):
    column = roads_near_me_module.get_road_type_column(small_map)
    values = [
        str(value)
        for value in small_map[column].dropna().astype(str).unique()
        if str(value)
    ]
    assert values, f"No non-empty values found in {column!r}"

    for candidate in ROAD_TYPE_CANDIDATES:
        if candidate in values:
            return column, candidate
    return column, values[0]


def test_module_exports_expected_helpers(roads_near_me_module):
    assert hasattr(roads_near_me_module, "get_road_type_column")
    assert hasattr(roads_near_me_module, "find_roads_by_type")
    assert hasattr(roads_near_me_module, "find_and_save_pydeck_road_type_animation")
    assert hasattr(roads_near_me_module, "save_pydeck_road_type_animation")


def test_find_roads_by_type_finds_real_values(roads_near_me_module, small_map, detected_road_type):
    column, road_type = detected_road_type
    roads = roads_near_me_module.find_roads_by_type(small_map, road_type, column=column)

    assert not roads.empty
    assert roads.attrs["road_type_column"] == column
    assert road_type in roads.attrs["road_types"]
    assert column in roads.columns
    assert set(roads[column].dropna().astype(str).str.casefold()) == {road_type.casefold()}


def test_find_and_save_pydeck_road_type_animation_creates_html(
    roads_near_me_module,
    small_map,
    detected_road_type,
    tmp_path,
):
    column, road_type = detected_road_type
    pt = roads_near_me_module.point(37.6556, 55.7557)
    output_path = tmp_path / "road_type_animation.html"

    roads, returned_output = roads_near_me_module.find_and_save_pydeck_road_type_animation(
        small_map,
        road_type,
        str(output_path),
        geo_obj=pt,
        column=column,
        limit=5,
        fps=10,
        zoom_in_frames=5,
        linger_frames=3,
        zoom_out_frames=5,
        initial_frames=2,
        width=800,
        height=600,
    )

    assert not roads.empty
    assert Path(returned_output) == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    html = output_path.read_text(encoding="utf-8")
    assert "Road type animation" in html
    assert "const ROADS =" in html
    assert road_type in html


def test_main_like_smoke_workflow(roads_near_me_module, small_map):
    pt = roads_near_me_module.point(37.6556, 55.7557)

    roads = roads_near_me_module.find_roads(pt, small_map, 50)
    nearest = roads_near_me_module.find_roads_nn(pt, small_map, nearest_n=10)

    assert pt.crs.to_string() == "EPSG:4326"
    assert "geometry" in small_map.columns

    assert hasattr(roads, "geometry")
    assert hasattr(nearest, "geometry")
    assert "distance_m" in nearest.columns
    assert not nearest.empty
    assert len(nearest) <= 10
    assert nearest.geometry.notna().all()
    assert nearest["distance_m"].notna().all()
    assert (nearest["distance_m"] >= 0).all()
    assert nearest["distance_m"].is_monotonic_increasing
    assert set(nearest.index).issubset(set(small_map.index))

    if not roads.empty:
        assert roads.geometry.notna().all()
        assert set(roads.index).issubset(set(small_map.index))
