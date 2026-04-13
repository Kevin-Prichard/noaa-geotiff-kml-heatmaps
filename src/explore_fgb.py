#!/usr/bin/env python3.13

import sys

import pudb
from osgeo import ogr


def show_contents(fgb_path):
    ds = ogr.Open(fgb_path, 0)
    pu.db

    for i in range(ds.GetLayerCount()):
        layer = ds.GetLayerByIndex(i)
        print("Layer:", layer.GetName())

        layer_defn = layer.GetLayerDefn()
        for j in range(layer_defn.GetFieldCount()):
            field_defn = layer_defn.GetFieldDefn(j)
            print("  Field:", field_defn.GetName(), field_defn.GetTypeName())


def explore_layers(fgb_path):
    ds = ogr.Open(fgb_path, 0)
    layer = ds.GetLayer(0)  # FlatGeobuf usually has one layer

    for feature in layer:
        geom = feature.GetGeometryRef()

        if geom is None:
            continue

        geom_type = geom.GetGeometryName()
        # print("Geometry type:", geom_type)

        if geom_type == "LINESTRING":
            for i in range(geom.GetPointCount()):
                x, y, z = geom.GetPoint(i)
                print(f"  Point {i}: ({x}, {y}, {z})")

        if geom_type == "POLYGON":
            pu.db
            ring = geom.GetGeometryRef(0)  # outer ring
            for i in range(ring.GetPointCount()):
                x, y, z = ring.GetPoint(i)
                print(f"  Vertex {i}: ({x}, {y}, {z})")

def main(path):
    explore_layers(path)


if __name__ == "__main__":
    main(sys.argv[1])
