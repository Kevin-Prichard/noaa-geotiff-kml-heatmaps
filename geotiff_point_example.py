#!/usr/bin/env python3

import sys

import rasterio

# Open the dataset (can be .vrt or .tif)
ds = rasterio.open(sys.argv[1])

lat = float(sys.argv[2])  #  37.7749
lon = float(sys.argv[2])  # -122.4194

# Convert lat/lon → raster row/col
row, col = ds.index(lon, lat)

# Read pixel value
value = ds.read(1)[row, col]

print(value)
