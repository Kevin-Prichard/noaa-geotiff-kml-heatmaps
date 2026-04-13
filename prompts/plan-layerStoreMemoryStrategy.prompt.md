## LayerStore: stream-vs-load decision per raster layer

### Decision criteria

The best practice is to query **available system RAM at construction time** via `psutil`,
estimate each layer's footprint from rasterio metadata *before* reading any pixels, and
keep a running committed-bytes counter. Each layer is independently loaded or demoted to
streaming as the budget fills.

```
available  = psutil.virtual_memory().available
budget     = available × budget_fraction          # e.g. 0.60
estimated  = bands × clipped_rows × clipped_cols × max_itemsize

if committed + estimated ≤ budget:
    array = ds.read(window=clip_window)     # load
    committed += array.nbytes
else:
    array = None                             # stream on every access
```

Key points:

- **`psutil.virtual_memory().available`** — already accounts for OS file-cache and other
  processes; safer than `.free` (which ignores reclaimable cache).
- **Estimate before reading** — avoids OOM from optimistically starting a large read.
- **`max_itemsize` across bands** — conservative upper bound when bands have mixed dtypes.
- **Budget fraction < 1.0** — leaves headroom for the networkx graph, GeoDataFrames, and OS.
- **joblib compatibility** — loaded `ndarray`s are automatically memory-mapped by joblib's
  `loky` backend (arrays > ~1 MB). Streaming entries contain only a `Path` — negligible
  serialization cost.

### Uniform interface

`LayerStore.values_at(pt, layer=None) -> np.ndarray` works identically whether the layer
was loaded or is being streamed. Callers (RoutePlanner subclasses, cost functions) never
need to know which mode is active.

---

### Implementation → `src/layer_store.py`
