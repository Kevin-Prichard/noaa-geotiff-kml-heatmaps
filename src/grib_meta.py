#!/usr/bin/env python3

import os
import re
import sys
from datetime import date, datetime

from osgeo import gdal
import numpy as np
import pygrib
import pudb


FILENAME_SAFE_RX = re.compile(r"[^a-zA-Z0-9._-]+")


import xarray as xr
import numpy as np
import rasterio
from rasterio.transform import from_bounds


ALL_GRIB_BAND_KEYS = ['globalDomain', 'GRIBEditionNumber', 'tablesVersionLatestOfficial', 'tablesVersionLatest', 'grib2divider', 'angleSubdivisions', 'missingValue', 'ieeeFloats', 'isHindcast',
'section0Length', 'identifier', 'discipline', 'editionNumber', 'totalLength', 'sectionNumber', 'section1Length', 'numberOfSection', 'centre', 'centreDescription', 'subCentre',
'tablesVersion', 'masterDir', 'localTablesVersion', 'significanceOfReferenceTime', 'year', 'month', 'day', 'hour', 'minute', 'second', 'dataDate', 'julianDay', 'dataTime',
'productionStatusOfProcessedData', 'typeOfProcessedData', 'md5Section1', 'selectStepTemplateInterval', 'selectStepTemplateInstant', 'stepType', 'is_chemical',
'is_chemical_distfn', 'is_chemical_srcsink', 'is_aerosol', 'is_aerosol_optical', 'is_probability_fcst', 'is_wave_period_range', 'setCalendarId', 'deleteCalendarId',
'conceptsDir1', 'conceptsDir2', 'eps', 'sectionNumber', 'grib2LocalSectionPresent', 'deleteLocalDefinition', 'sectionNumber', 'gridDescriptionSectionPresent', 'section3Length',
'numberOfSection', 'sourceOfGridDefinition', 'numberOfDataPoints', 'numberOfOctectsForNumberOfPoints', 'interpretationOfNumberOfPoints', 'PLPresent',
'gridDefinitionTemplateNumber', 'gridDefinitionDescription', 'shapeOfTheEarth', 'scaleFactorOfRadiusOfSphericalEarth', 'scaledValueOfRadiusOfSphericalEarth',
'scaleFactorOfEarthMajorAxis', 'scaledValueOfEarthMajorAxis', 'scaleFactorOfEarthMinorAxis', 'scaledValueOfEarthMinorAxis', 'radius', 'isGridded', 'Ni', 'Nj',
'basicAngleOfTheInitialProductionDomain', 'mBasicAngle', 'angleMultiplier', 'mAngleMultiplier', 'subdivisionsOfBasicAngle', 'angleDivisor', 'latitudeOfFirstGridPoint',
'longitudeOfFirstGridPoint', 'resolutionAndComponentFlags', 'resolutionAndComponentFlags1', 'resolutionAndComponentFlags2', 'iDirectionIncrementGiven',
'jDirectionIncrementGiven', 'uvRelativeToGrid', 'resolutionAndComponentFlags6', 'resolutionAndComponentFlags7', 'resolutionAndComponentFlags8', 'ijDirectionIncrementGiven',
'latitudeOfLastGridPoint', 'longitudeOfLastGridPoint', 'iDirectionIncrement', 'jDirectionIncrement', 'scanningMode', 'iScansNegatively', 'jScansPositively',
'jPointsAreConsecutive', 'alternativeRowScanning', 'iScansPositively', 'jScansNegatively', 'scanningMode5', 'scanningMode6', 'scanningMode7', 'scanningMode8', 'g2grid',
'latitudeOfFirstGridPointInDegrees', 'longitudeOfFirstGridPointInDegrees', 'latitudeOfLastGridPointInDegrees', 'longitudeOfLastGridPointInDegrees',
'iDirectionIncrementInDegrees', 'jDirectionIncrementInDegrees', 'latLonValues', 'latitudes', 'longitudes', 'distinctLatitudes', 'distinctLongitudes', 'gridType', 'md5Section3',
'isSpectral', 'sectionNumber', 'section4Length', 'numberOfSection', 'NV', 'neitherPresent', 'datasetForLocal', 'productDefinitionTemplateNumber', 'genVertHeightCoords',
'parameterCategory', 'parameterNumber', 'parameterUnits', 'parameterName', 'typeOfGeneratingProcess', 'backgroundProcess', 'generatingProcessIdentifier',
'hoursAfterDataCutoff', 'minutesAfterDataCutoff', 'indicatorOfUnitForForecastTime', 'stepUnits', 'forecastTime', 'startStep', 'endStep', 'stepRange', 'stepTypeInternal',
'validityDate', 'validityTime', 'validityDateTime', 'typeOfFirstFixedSurface', 'unitsOfFirstFixedSurface', 'nameOfFirstFixedSurface', 'scaleFactorOfFirstFixedSurface',
'scaledValueOfFirstFixedSurface', 'typeOfSecondFixedSurface', 'unitsOfSecondFixedSurface', 'nameOfSecondFixedSurface', 'scaleFactorOfSecondFixedSurface',
'scaledValueOfSecondFixedSurface', 'pressureUnits', 'typeOfLevel', 'level', 'bottomLevel', 'topLevel', 'levtype', 'tempPressureUnits', 'productDefinitionTemplateName',
'enableChemSplit', 'paramIdECMF', 'paramId', 'shortNameECMF', 'shortName', 'unitsECMF', 'units', 'nameECMF', 'name', 'cfNameECMF', 'cfName', 'cfVarName', 'PVPresent',
'deletePV', 'timeSpan', 'md5Section4', 'lengthOfHeaders', 'md5Headers', 'sectionNumber', 'section5Length', 'numberOfSection', 'numberOfValues',
'dataRepresentationTemplateNumber', 'packingType', 'referenceValue', 'referenceValueError', 'binaryScaleFactor', 'decimalScaleFactor', 'optimizeScaleFactor', 'bitsPerValue',
'typeOfOriginalFieldValues', 'groupSplittingMethodUsed', 'missingValueManagementUsed', 'primaryMissingValueSubstitute', 'secondaryMissingValueSubstitute',
'numberOfGroupsOfDataValues', 'referenceForGroupWidths', 'numberOfBitsUsedForTheGroupWidths', 'referenceForGroupLengths', 'lengthIncrementForTheGroupLengths',
'trueLengthOfLastGroup', 'numberOfBitsForScaledGroupLengths', 'orderOfSpatialDifferencing', 'numberOfOctetsExtraDescriptors', 'md5Section5', 'sectionNumber', 'section6Length',
'numberOfSection', 'bitMapIndicator', 'bitmapPresent', 'missingValuesPresent', 'md5Section6', 'sectionNumber', 'section7Length', 'numberOfSection', 'codedValues', 'values',
'maximum', 'minimum', 'average', 'standardDeviation', 'skewness', 'kurtosis', 'isConstant', 'numberOfMissing', 'changeDecimalPrecision', 'decimalPrecision', 'setBitsPerValue',
'setPackingType', 'getNumberOfValues', 'scaleValuesBy', 'offsetValuesBy', 'productType', 'md5Section7', 'isMessageValid', 'section8Length', 'isTemplateDeprecated',
'isTemplateExperimental', 'paramIdForConversion', 'analDate', 'validDate']


def _json_safe_band_value(value, max_array_preview=32):
    """Convert pygrib/numpy values into JSON-safe Python primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, np.ndarray):
        flat = value.ravel()
        preview = [
            _json_safe_band_value(v, max_array_preview=max_array_preview)
            for v in flat[:max_array_preview]
        ]
        return {
            "type": "ndarray",
            "dtype": str(value.dtype),
            "shape": list(value.shape),
            "size": int(value.size),
            "preview": preview,
            "truncated": int(value.size) > max_array_preview,
        }

    if isinstance(value, (list, tuple)):
        return [_json_safe_band_value(v, max_array_preview=max_array_preview)
                for v in value]

    if isinstance(value, dict):
        return {
            str(k): _json_safe_band_value(v, max_array_preview=max_array_preview)
            for k, v in value.items()
        }

    if callable(value):
        return f"<callable {getattr(value, '__name__', type(value).__name__)}>"

    return str(value)


def build_grib_band_dicts(grib_pathname, keys=None):
    """Return GRIB band metadata as a list of JSON-serializable dicts."""
    records = []
    if keys is None:
        keys = ALL_GRIB_BAND_KEYS
    unique_keys = list(dict.fromkeys(keys))

    with pygrib.open(grib_pathname) as grib:
        for num, band in enumerate(grib):
            record = {"band_index": num + 1}
            for key in unique_keys:
                try:
                    raw_value = getattr(band, key)
                    print(f"{raw_value} = getattr({band}, {key})")
                except Exception:
                    # pu.db
                    raw_value = None
                record[key] = _json_safe_band_value(raw_value)
            records.append(record)

    return records


def search_grib_band_dicts(records, regex_pattern, flags=0, include_keys=False):
    """Search all band attributes with a regex and return matching fields."""
    regex = re.compile(regex_pattern, flags)
    matches = []

    for record in records:
        band_index = record.get("band_index")
        for key, value in record.items():
            if key == "band_index":
                continue
            text = f"{key}={value}" if include_keys else str(value)
            if regex.search(text):
                matches.append({
                    "band_index": band_index,
                    "key": key,
                    "value": value,
                })

    return matches


def test_build_and_search_grib_band_dicts(
        grib_pathname,
        regex_pattern,
        flags=re.IGNORECASE,
        include_keys=False,
        preview_limit=3):
    """Build metadata records and regex-search them for a given GRIB file."""
    if not os.path.isfile(grib_pathname):
        raise FileNotFoundError(f"GRIB file not found: {grib_pathname}")

    # pu.db
    records = build_grib_band_dicts(grib_pathname)
    matches = search_grib_band_dicts(
        records,
        regex_pattern,
        flags=flags,
        include_keys=include_keys,
    )

    result = {
        "grib_pathname": grib_pathname,
        "band_count": len(records),
        "match_count": len(matches),
        "records": records,
        "matches": matches,
    }

    sample_records = records[:preview_limit]
    sample_matches = matches[:preview_limit]
    print(
        f"Built {len(records)} band dicts from {grib_pathname}. "
        f"Regex matches: {len(matches)}"
    )
    if sample_records:
        print(f"Sample record keys: {list(sample_records[0].keys())[:10]}")
    if sample_matches:
        print(f"First match: {sample_matches[0]}")

    return result


def extract_wind_components(grib_pathname):

    grbs = pygrib.open(grib_file)



def extract_old():
    # --- LOAD GRIB (only 10m wind components) ---
    ds = xr.open_dataset(
        grib_file,
        engine="cfgrib",
        filter_by_keys={
            "typeOfLevel": "heightAboveGround",
            "level": 10
        }
    )

    # Extract U/V components
    u = ds["u10"]  # UGRD
    v = ds["v10"]  # VGRD

    # --- COMPUTE ---
    wind_speed = np.sqrt(u ** 2 + v ** 2)

    # Meteorological wind direction (degrees FROM which wind blows)
    wind_dir = (180 / np.pi) * np.arctan2(-u, -v)
    wind_dir = (wind_dir + 360) % 360  # normalize 0–360

    # --- GET GEOREFERENCING ---
    lats = ds.latitude.values
    lons = ds.longitude.values

    # Handle 0–360 → -180–180 if needed
    if lons.max() > 180:
        lons = ((lons + 180) % 360) - 180

    # Build affine transform
    transform = from_bounds(
        float(lons.min()), float(lats.min()),
        float(lons.max()), float(lats.max()),
        len(lons), len(lats)
    )

    # Flip latitude if needed (GFS is usually north→south)
    speed_data = wind_speed.values
    dir_data = wind_dir.values

    if lats[0] > lats[-1]:
        speed_data = np.flipud(speed_data)
        dir_data = np.flipud(dir_data)

    # --- WRITE GEOTIFFS ---
    def write_tif(filename, data):
        with rasterio.open(
                filename,
                "w",
                driver="GTiff",
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=transform,
                compress="deflate"
        ) as dst:
            dst.write(data.astype("float32"), 1)

    write_tif("wind_speed.tif", speed_data)
    write_tif("wind_direction.tif", dir_data)

"""
if "wind" in name:
    # --- SELECT WIND COMPONENTS ---
    u_msg = grbs.select(name="U component of wind", level=10)[0]
    v_msg = grbs.select(name="V component of wind", level=10)[0]

    # --- GET DATA + GRID ---
    u, lats, lons = u_msg.data()
    v, _, _ = v_msg.data()

    # --- COMPUTE ---
    wind_speed = np.sqrt(u ** 2 + v ** 2)

    # Meteorological direction (degrees FROM which wind blows)
    wind_dir = (180 / np.pi) * np.arctan2(-u, -v)
    wind_dir = (wind_dir + 360) % 360

    print(wind_speed.shape, wind_dir.shape)
"""


def build_geotiffs(grib_pathname):
    total = []
    with pygrib.open(grib_pathname) as grib:
        for num, band in enumerate(grib):
            import pudb; pu.db
            if not total:
                for n in dir(band):
                    if n.startswith("__"):
                        continue
                    v = getattr(band, n)
                    total.append(f"band.{n} = {str(v)} ({type(v)})")
                print("\n".join(total))

            var = band.cfVarName
            avg = band.average
            date = band.dataDate
            name = band.name
            short = band.shortName
            timeu = band.fcstimeunits
            level = band.level
            levtype = band.levtype
            valueCount = band.numberOfValues
            # string = band.tostring()
            units = band.units
            print(f"{var} = band.cfVarName\n"
                  f"{avg} = band.average\n"
                  f"{date} = band.dataDate\n"
                  f"{name} = band.name\n"
                  f"{short} = band.shortName\n"
                  f"{timeu} = band.fcstimeunits\n"
                  f"{level} = band.level\n"
                  f"{levtype} = band.levtype\n"
                  f"{valueCount} = band.numberOfValues\n"
                  # f"{string} = band.tostring\n"
                  f"{units} = band.units\n"
            )

            # pu.db
            name = FILENAME_SAFE_RX.sub("_", name)
            grib_basename = FILENAME_SAFE_RX.sub(
                "_", os.path.basename(grib_pathname))
            grib_path = os.path.dirname(grib_pathname)
            dst_filename = (f"{grib_path}/{grib_basename}"
                            f"_band{num+1}_{var}-{name}.tif")
            gdal.Translate(
                dst_filename,
                grib_pathname,
                format="GTiff",
                bandList=[num + 1]
            )



    # print("\n".join(a[i] for i in range(len(a)) if "unit" in n.lower()))

if __name__ == "__main__":
    # build_geotiffs(sys.argv[1])
    test_build_and_search_grib_band_dicts(
        sys.argv[1],
        sys.argv[2],
        flags=re.IGNORECASE,
        include_keys=False,
        preview_limit=3)

# pu.db
# x = 1
