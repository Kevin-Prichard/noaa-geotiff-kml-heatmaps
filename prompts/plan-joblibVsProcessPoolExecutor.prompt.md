**Answer briefly: Given the current context of a route planner that relies upon rasterio files/objects (grib, grib2, geotiff) and geopandas map files/objects (fgb), how does joblib manage such objects across process and cpu core boundaries? Is it possible to share say a fgb or geotiff in memory between joblib multicore processes? Or are those files/objects not entirely loaded into memory and accessed more like a database or disk-based arrays? In other words, for the current project does joblib offer any benefits over ProcessPoolExecutor, like avoiding serialization of such large file/object types as I mentioned?**

## joblib vs. ProcessPoolExecutor for rasterio + geopandas objects

### rasterio datasets (GeoTIFF, GRIB, GRIB2)

**Cannot be pickled at all.** A `rasterio.DatasetReader` holds a C-level file handle; both joblib and `ProcessPoolExecutor` will raise `TypeError` if you try to pass one directly. The standard pattern for either executor is identical:

- Pass the **file path** to the worker, reopen `rasterio.open(path)` inside the worker process
- Or pre-read into a **numpy array** before spawning workers, then pass the array

So joblib offers no advantage over `ProcessPoolExecutor` for rasterio objects themselves — the constraint is the same.

---

### numpy arrays read *from* rasterio

This is where joblib's `loky` backend **does** help. If you pre-read large raster tiles into `np.ndarray` and pass them as arguments:

- `ProcessPoolExecutor` pickles → serialises → copies the full array into each worker
- joblib automatically uses **memory-mapped temp files** for large arrays, so workers get a read-only view of the same memory pages — no copy, no serialisation overhead

**Verdict:** If workers share large pre-loaded elevation or weather grids, joblib wins here.

---

### geopandas GeoDataFrames (FGB)

**Partial benefit.** A `GeoDataFrame` is a pandas DataFrame with a geometry column:

| Column type | joblib mmap? |
|---|---|
| Numeric columns (`float64`, `int32`, etc.) | ✅ Yes — underlying numpy arrays are memory-mapped |
| Geometry column (shapely objects) | ❌ No — shapely objects pickle individually; no mmap |

For a typical FGB with many geometry rows, the geometry column still serialises the old way. For attribute-heavy frames with few geometries (e.g., a land-use raster converted to polygons), joblib helps more.

---

### Practical recommendation for this project

| Scenario | Use |
|---|---|
| Workers open rasterio files themselves (pass path only) | `ProcessPoolExecutor` — no difference |
| Workers share a large pre-read numpy elevation/weather array | `joblib` — avoids copying the array |
| Workers share a large GeoDataFrame with complex geometry | Marginal joblib benefit; consider passing the FGB path and reloading per worker with a bbox clip instead |
| Long-lived planner objects that need replanning / D\* Lite graph repair | `ray` — actors keep state between calls; neither joblib nor ProcessPoolExecutor handle stateful objects across calls cleanly |

**Bottom line:** For this project, the natural access pattern (pass file paths, open inside worker, clip to local bbox) neutralises most of joblib's advantage. `ProcessPoolExecutor` is the right starting point unless profiling shows numpy array serialisation as a bottleneck — at which point joblib is a one-line swap. Adopt `ray` if distributed or stateful replanning is on the roadmap.
