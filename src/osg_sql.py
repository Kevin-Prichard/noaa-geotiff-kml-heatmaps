#!/usr/bin/env python3.13

from time import time

from osgeo import ogr

import pudb

def _ogr_rows(result_layer, max_rows: int | None = None):
    rows = []
    for idx, feature in enumerate(result_layer):
        if max_rows is not None and idx >= max_rows:
            break
        row = {}
        for field_idx in range(feature.GetFieldCount()):
            name = feature.GetFieldDefnRef(field_idx).GetName()
            row[name] = feature.GetField(field_idx)
        rows.append(row)
    return rows


def _ogr_execute_sql(ds, sql: str, dialect: str = "OGRSQL", max_rows: int | None = None):
    result = ds.ExecuteSQL(sql, dialect=dialect)
    if result is None:
        raise RuntimeError(f"ExecuteSQL failed for query: {sql}")

    try:
        return _ogr_rows(result, max_rows=max_rows)
    finally:
        ds.ReleaseResultSet(result)


def explore_fgb_sql_examples(fgb_pathname: str,
                             line_layer: str = "lines",
                             polygon_layer: str = "multipolygons",
                             sample_rows: int = 20):
    """
    Run SQL-style exploratory queries on an OSM-derived FlatGeobuf file.

    This helps answer questions such as:
    - Are roads mostly stored in line layers vs polygon layers?
    - How many roads exist by road type (`highway`)?
    - How many line segments represent one named road?
    - How many farmland or residential-area polygons exist?
    """
    if ogr is None:
        raise ImportError("osgeo.ogr is required for explore_fgb_sql_examples")

    ds = ogr.Open(fgb_pathname, 0)
    if ds is None:
        raise RuntimeError(f"Could not open FlatGeobuf datasource: {fgb_pathname}")

    layer_names = [ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())]

    results = {
        "source": fgb_pathname,
        "layers": layer_names,
        "queries": {},
    }

    def run(name: str, sql: str, layer_required: str | None = None, max_rows: int | None = None):
        if layer_required is not None and layer_required not in layer_names:
            results["queries"][name] = {
                "sql": sql,
                "warning": f"Layer {layer_required!r} not found",
                "rows": [],
            }
            return

        start = time()
        rows = _ogr_execute_sql(ds, sql, max_rows=max_rows)
        print(sql)
        print("\n".join(str(r) for r in rows))
        results["queries"][name] = {
            "sql": sql,
            "row_count": len(rows),
            "elapsed_s": time() - start,
            "rows": rows,
        }

    # Example 1: how many features are in each layer (quick inventory).
    for layer_name in layer_names:
        run(
            name=f"layer_count__{layer_name}",
            sql=f'SELECT COUNT(*) AS n FROM "{layer_name}"',
            layer_required=layer_name,
            max_rows=1,
        )

    # Example 2.1: road objects by type in the lines layer.
    pu.db
    run(
        name="roads_by_highway_type",
        sql=(
            f'SELECT * '
            f'FROM "{line_layer}" '
            f'LIMIT {sample_rows}'
        ),
        layer_required=line_layer,
        max_rows=sample_rows,
    )

    # Example 2: road objects by type in the lines layer.
    run(
        name="roads_by_highway_type",
        sql=(
            f'SELECT highway, COUNT(*) AS n '
            f'FROM "{line_layer}" '
            f'WHERE highway IS NOT NULL '
            f'GROUP BY highway '
            f'ORDER BY n DESC'
        ),
        layer_required=line_layer,
        max_rows=sample_rows,
    )

    # Example 3: named road segmentation, i.e. one street name split into many lines.
    run(
        name="named_road_segment_counts",
        sql=(
            f'SELECT name, highway, COUNT(*) AS segment_count '
            f'FROM "{line_layer}" '
            f'WHERE highway IS NOT NULL AND name IS NOT NULL '
            f'GROUP BY name, highway '
            f'ORDER BY segment_count DESC'
        ),
        layer_required=line_layer,
        max_rows=sample_rows,
    )

    # Example 4: unnamed segments by road type.
    run(
        name="unnamed_segments_by_type",
        sql=(
            f'SELECT highway, COUNT(*) AS unnamed_count '
            f'FROM "{line_layer}" '
            f'WHERE highway IS NOT NULL AND name IS NULL '
            f'GROUP BY highway '
            f'ORDER BY unnamed_count DESC'
        ),
        layer_required=line_layer,
        max_rows=sample_rows,
    )

    # Example 5: roads represented as area polygons (if any in multipolygons layer).
    run(
        name="road_like_polygons",
        sql=(
            f'SELECT COUNT(*) AS n '
            f'FROM "{polygon_layer}" '
            f'WHERE highway IS NOT NULL'
        ),
        layer_required=polygon_layer,
        max_rows=1,
    )

    # Example 6: farmland polygons (proxy for farm fields).
    run(
        name="farmland_polygons",
        sql=(
            f'SELECT COUNT(*) AS n '
            f'FROM "{polygon_layer}" '
            f"WHERE landuse = 'farmland'"
        ),
        layer_required=polygon_layer,
        max_rows=1,
    )

    # Example 7: city-block-like proxy via residential landuse polygons.
    run(
        name="residential_polygons",
        sql=(
            f'SELECT COUNT(*) AS n '
            f'FROM "{polygon_layer}" '
            f"WHERE landuse = 'residential'"
        ),
        layer_required=polygon_layer,
        max_rows=1,
    )

    # Example 8: building polygon count.
    run(
        name="building_polygons",
        sql=(
            f'SELECT COUNT(*) AS n '
            f'FROM "{polygon_layer}" '
            f'WHERE building IS NOT NULL'
        ),
        layer_required=polygon_layer,
        max_rows=1,
    )

    return results


if __name__ == "__main__":
    import pudb; pu.db
    explore_fgb_sql_examples("osm/ru.fgb",
                             "lines",
                             "multipolygons")
