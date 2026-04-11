#!/usr/bin/env python3

import argparse
import os
import re
import sys

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import from_bounds


ALL_SCHEMES = sorted(plt.colormaps(), key=lambda n: n.lower())

CLEAN_FLOAT_RX = re.compile(r"(?P<n>-?[0-9.]+)")
GET_EXT_RX = re.compile(r".*\.(?P<ext>[a-z0-9_+]{1,4})$")

PYPLOT_SCHEMES = "https://www.tutorialspoint.com/matplotlib/"\
                 "matplotlib_choosing_colormaps.htm"

def get_args(args):
    def clean_float(value: str) -> float:
        try:
            if cleaned := CLEAN_FLOAT_RX.match(value):
                return float(cleaned.group(1))
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"Invalid float value: '{value}'")

    def check_scheme(scheme: str) -> str:
        if scheme in ALL_SCHEMES:
            return scheme
        else:
            raise argparse.ArgumentTypeError(
                f"Invalid color scheme name: '{scheme}' -check capitalization: "
                f"{', '.join(ALL_SCHEMES)}"
            )

    parser = argparse.ArgumentParser(
        description='Produce heatmap based on a GeoTIFF')
    parser.add_argument('-i', '--input', action='store', dest='geotiff',
                        help='Input GeoTIFF file path', required=True)
    parser.add_argument('-o', '--outfile', action='store', dest='outfile',
                        help='Output filename or pathname, ending in one of'
                             '.png, .kml or .kmz',
                        required=True)
    parser.add_argument('-r', '--revscheme', action='store_true',
                        dest='revscheme', default=False,
                        help="Reverse color scheme order")
    parser.add_argument('-m', '--scheme', action='store', dest='scheme',
                        default='viridis', type=check_scheme,
                        help=("Select a color scheme from pyplot's "
                              "list of color schemes "
                              f"({', '.join(ALL_SCHEMES)}).  "
                              f"See {PYPLOT_SCHEMES} for examples")
                        )
    parser.add_argument('-s', '--scale', type=float, action='store',
                        dest='scale', default=1.0,
                        help="Scale incoming tiff, with this as denominator",
                        )
    parser.add_argument('-c', '--opacity', type=float, action='store',
                        dest='opacity', default=0.6,
                        help="Opacity",
                        )
    parser.add_argument('-t', '--title', type=str, action='store',
                        dest='title', required=True,
                        help='Name your KML/KMZ, so that it makes sense to viewers')

    parser.add_argument('lat0', type=clean_float)
    parser.add_argument('lon0', type=clean_float)
    parser.add_argument('lat1', type=clean_float)
    parser.add_argument('lon1', type=clean_float)

    return parser.parse_args(args)


def geotiff2matrix(vrt_file, outfile, scheme, revscheme, scale, opacity,
                   min_lon, min_lat, max_lon, max_lat):

    # Grab info about outfile to prepare for writing
    out_basename = os.path.basename(outfile)
    out_dir = os.path.dirname(outfile)
    if out_mat := GET_EXT_RX.match(out_basename):
        out_ext = out_mat.group(1).lower()
    else:
        raise ValueError(
            f"Did't recognize an extension on --outfile param: {outfile}")

    ds = rasterio.open(vrt_file)
    nodata_val = ds.nodata

    window = from_bounds(min_lon, min_lat, max_lon, max_lat, ds.transform)

    # Some GeoTIFFs are massive! We can scale them
    data = ds.read(1, window=window,
                   out_shape=(int(window.height / scale),
                              int(window.width / scale)),
                   resampling=Resampling.average
    ).astype(np.float32)

    # Check metadata's nodata, neg values (bad for log), and any existing NaNs
    invalid_mask = (data <= 0) | np.isnan(data)
    if nodata_val is not None:
        invalid_mask |= (data == nodata_val)

    data[invalid_mask] = np.nan

    # Use np.errstate to ignore warnings about log(NaN)
    with np.errstate(divide='ignore', invalid='ignore'):
        log_data = np.log10(data)

    # ignore holes/transparency when calculating the color scale
    if np.all(np.isnan(log_data)):
        # if window is entirely empty
        return None

    vmin = np.nanpercentile(log_data, 5)
    vmax = np.nanpercentile(log_data, 95)

    if vmax == vmin:
        norm = np.zeros_like(log_data)
    else:
        norm = (log_data - vmin) / (vmax - vmin)
        norm = np.clip(norm, 0, 1)

    cmap = plt.get_cmap(scheme)
    if revscheme:
        cmap = cmap.reversed()
    rgba = cmap(norm)

    rgba[..., 3] = np.where(np.isnan(norm), 0, opacity)

    if out_ext == 'kml' or out_ext == 'kmz':
        png_outfile = f"{out_basename}.png"
    else:
        png_outfile = out_basename

    png_outpath = os.path.join(out_dir, png_outfile)
    plt.imsave(png_outpath, rgba)

    if out_ext == 'kml' or out_ext == 'kmz':
        bounds = rasterio.windows.bounds(window, ds.transform)
        west, south, east, north = bounds

        print("Bounds", north, south, east, west)
        assert north > south and east > west

        kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Folder>
      <name>ground overlay ****************</name>
      <description>my ground overlay folder ################</description>
      <GroundOverlay>
        <name>Population Heatmap</name>
        <description>my ground overlay ^^^^^^^^^^^^^^^</description>
        <Icon>
          <href>heatmap.png</href>
        </Icon>
        <LatLonBox>
          <north>{north}</north>
          <south>{south}</south>
          <east>{east}</east>
          <west>{west}</west>
        </LatLonBox>
      </GroundOverlay>
    </Folder>
  </Document>
</kml>"""

        if out_ext == "kmz":
            kml_outfile = f"{out_basename}.kml"
            kmz_outfile = out_basename
        else:
            kml_outfile = out_basename
            kmz_outfile = f"{out_basename}.kmz"
        kml_outpath = os.path.join(out_dir, kml_outfile)
        with open(kml_outpath, "w") as f:
            f.write(kml_content)

        import zipfile

        kmz_outfile = os.path.join(out_dir, kmz_outfile)
        with zipfile.ZipFile(kmz_outfile, "w") as z:
            z.write(kml_outpath, "doc.kml")
            z.write(png_outpath, "heatmap.png")

    return data


def get_heatmap(args):
    mins = ((min_lon:=min(args.lon0, args.lon1)),
            (min_lat:=min(args.lat0, args.lat1)))
    maxs = ((max_lon:=max(args.lon0, args.lon1)),
            (max_lat:=max(args.lat0, args.lat1)))
    print(f"min_lon={min_lon}, min_lat={min_lat}"
          f"max_lon={max_lon}, max_lat={max_lat}")
    print(f"lon={min_lon} {max_lon}, lat={min_lat} {max_lat}")
    m = geotiff2matrix(args.geotiff, args.outfile, args.scheme, args.revscheme,
                       args.scale, args.opacity,
                       *mins, *maxs)


if __name__ == '__main__':
    print(sys.argv)
    # pu.db
    args = get_args(sys.argv[1:])
    get_heatmap(args)
