"""
layer_store.py — Raster layer manager for PlanningSession.

Each raster source is independently either:
  - pre-loaded into RAM as an ndarray (joblib mmaps it zero-copy across workers), or
  - left on disk and streamed per access via rasterio.Dataset.sample()

The decision is made at construction time based on available system RAM.
The public interface (values_at) is identical in both cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import numpy as np
import psutil
import rasterio
import rasterio.windows
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.transform import Affine, rowcol
from shapely.geometry import Point

if TYPE_CHECKING:
    import geopandas as gpd

logger = logging.getLogger(__name__)

# Fraction of currently available RAM that LayerStore may consume.
# 0.60 leaves headroom for networkx graphs, GeoDataFrames, and the OS.
_DEFAULT_MEMORY_BUDGET_FRACTION: float = 0.60


class BoundingBox(NamedTuple):
    """
    WGS84 (EPSG:4326) bounding box used to clip raster sources on load.

    This is the canonical bbox type used internally throughout the project.
    Convert from the prompt's GeoSeries format at the boundary using
    ``BoundingBox.from_geoseries()``.
    """
    west: float    # min longitude
    south: float   # min latitude
    east: float    # max longitude
    north: float   # max latitude

    @classmethod
    def from_geoseries(cls, gs: "gpd.GeoSeries") -> "BoundingBox":
        """
        Convert a GeoSeries of two Points into a BoundingBox.

        Accepts the prompt's preferred bbox notation::

            gpd.GeoSeries([shapely.Point(lon0, lat0), shapely.Point(lon1, lat1)])

        The two points are treated as opposite corners; west/east and
        south/north are resolved from whichever corner is smaller/larger,
        so point order does not matter.

        Args:
            gs: GeoSeries with at least two Point geometries in WGS84.
        Returns:
            BoundingBox(west, south, east, north)
        Raises:
            ValueError: if gs has fewer than two geometries.
        """
        if len(gs) < 2:
            raise ValueError(
                f"BoundingBox.from_geoseries requires at least 2 points, got {len(gs)}"
            )
        total_bounds = gs.total_bounds  # [minx, miny, maxx, maxy]
        return cls(
            west=float(total_bounds[0]),
            south=float(total_bounds[1]),
            east=float(total_bounds[2]),
            north=float(total_bounds[3]),
        )

    @classmethod
    def from_points(cls, lon0: float, lat0: float, lon1: float, lat1: float) -> "BoundingBox":
        """
        Convenience constructor from two (lon, lat) corner pairs.
        Order of corners does not matter.
        """
        return cls(
            west=min(lon0, lon1),
            south=min(lat0, lat1),
            east=max(lon0, lon1),
            north=max(lat0, lat1),
        )

    def to_geoseries(self) -> "gpd.GeoSeries":
        """
        Round-trip back to the GeoSeries format used in the prompt.
        Returns a two-point GeoSeries (SW corner, NE corner) in WGS84.
        """
        import geopandas as gpd
        from shapely.geometry import Point
        return gpd.GeoSeries(
            [Point(self.west, self.south), Point(self.east, self.north)],
            crs="EPSG:4326",
        )


@dataclass
class _LayerEntry:
    """
    Internal representation of one raster file.

    If ``array`` is set the layer was loaded into RAM; if None it is streamed.
    ``values_at`` hides the difference from callers.
    """
    name: str
    path: Path
    bbox_wgs84: BoundingBox
    array: np.ndarray | None   # shape (bands, rows, cols) if loaded; None if streaming
    transform: Affine          # affine transform for the clipped/loaded window
    crs: CRS                   # native CRS of the dataset
    nodata: float | None
    bands: int
    _transformer: Transformer = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        epsg = self.crs.to_epsg()
        target = f"EPSG:{epsg}" if epsg else self.crs.to_wkt()
        self._transformer = Transformer.from_crs(
            "EPSG:4326", target, always_xy=True
        )

    # ── Public ────────────────────────────────────────────────────────────────

    @property
    def is_loaded(self) -> bool:
        return self.array is not None

    @property
    def memory_bytes(self) -> int:
        return self.array.nbytes if self.is_loaded else 0

    def values_at(self, pt: Point) -> np.ndarray:
        """
        Return shape ``(bands,)`` float array of raster values at WGS84 point.
        NaN is substituted for nodata pixels.
        """
        native_x, native_y = self._transformer.transform(pt.x, pt.y)
        if self.is_loaded:
            return self._sample_loaded(native_x, native_y)
        return self._sample_stream(native_x, native_y)

    # ── Private ───────────────────────────────────────────────────────────────

    def _sample_loaded(self, x: float, y: float) -> np.ndarray:
        row, col = rowcol(self.transform, x, y)
        _, nrows, ncols = self.array.shape
        if not (0 <= row < nrows and 0 <= col < ncols):
            logger.debug(
                "_LayerEntry._sample_loaded: (%f, %f) outside extent of %s",
                x, y, self.path.name,
            )
            return np.full(self.bands, np.nan)
        result = self.array[:, row, col].astype(float)
        if self.nodata is not None:
            result[result == self.nodata] = np.nan
        return result

    def _sample_stream(self, x: float, y: float) -> np.ndarray:
        """Open → sample → close on every call. Thread-safe (read-only file)."""
        with rasterio.open(self.path) as ds:
            vals = np.array(list(ds.sample([(x, y)]))[0], dtype=float)
        if self.nodata is not None:
            vals[vals == self.nodata] = np.nan
        return vals


@dataclass
class LayerStore:
    """
    Manages N raster layers (GeoTIFF, GRIB, GRIB2) for a PlanningSession.

    **Load-or-stream decision** is made per layer at construction time:

    1. Query ``psutil.virtual_memory().available`` once.
    2. Compute ``budget = available × memory_budget_fraction``.
    3. For each source in order, estimate its clipped byte footprint from
       rasterio metadata *before* reading any pixels.
    4. If ``committed + estimated ≤ budget``: load into RAM, increment counter.
    5. Otherwise: record path + metadata only; stream on every ``values_at`` call.

    **joblib compatibility**
    - Loaded layers: ``ndarray``\\s > ~1 MB are memory-mapped by joblib's ``loky``
      backend — zero-copy sharing across worker processes.
    - Streaming layers: only a ``Path`` string crosses the process boundary.

    Usage::

        bbox = BoundingBox(west=22.0, south=47.5, east=24.0, north=49.0)
        store = LayerStore.load([
            ("elevation.tif",        bbox),
            ("population.tif",       bbox),
            ("solar_luminance.tif",  bbox),
            ("weather_u10m.tif",     bbox),
        ])
        vals = store.values_at(Point(23.1, 48.3), layer=0)   # elevation bands
        all_vals = store.values_at(Point(23.1, 48.3))         # all layers concat
    """

    _entries: dict[str, _LayerEntry] = field(default_factory=dict)
    _bytes_committed: int = field(default=0, init=False)
    _memory_budget_bytes: int = field(default=0, init=False)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def load(
        cls,
        sources: dict[str, tuple[Path | str, BoundingBox]],
        memory_budget_fraction: float = _DEFAULT_MEMORY_BUDGET_FRACTION,
    ) -> "LayerStore":
        """
        Args:
            sources: dict of ``{key: (path, bbox)``, one per raster.
                     Nam
            memory_budget_fraction: fraction of currently available RAM to use
                                    for pre-loaded layers.  Default 0.60.
        Returns:
            Fully initialised LayerStore.
        Raises:
            rasterio.errors.RasterioIOError: if a source file cannot be opened.
        """
        store = cls()
        available = psutil.virtual_memory().available
        store._memory_budget_bytes = int(available * memory_budget_fraction)
        logger.info(
            "LayerStore.load: budget %.2f GB (%.0f%% of %.2f GB available)",
            store._memory_budget_bytes / 1e9,
            memory_budget_fraction * 100,
            available / 1e9,
        )

        for key, (path, bbox) in sources.items():
            try:
                entry = store._load_or_stream(key, Path(path), bbox)
            except Exception as exc:
                logger.error("LayerStore: failed to open %s — %s (%s)",
                             path, exc, key)
                raise
            store._entries[key] = entry

        n_loaded = sum(1 for e in store._entries.values() if e.is_loaded)
        logger.info(
            "LayerStore: %d/%d layer(s) loaded (%.2f GB), %d streaming",
            n_loaded, len(store._entries),
            store._bytes_committed / 1e9,
            len(store._entries) - n_loaded,
        )
        return store

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def layer_count(self) -> int:
        """Number of raster sources managed."""
        return len(self._entries)

    def values_at(self, pt: Point, layer: str | None = None) -> np.ndarray:
        """
        Sample raster value(s) at a WGS84 point.

        Args:
            pt:    ``shapely.geometry.Point`` in WGS84 / EPSG:4326.
            layer: index into the ``sources`` dict supplied to ``load()``.
                   ``None`` → concatenate values from *all* layers into a
                   single 1-D array of shape ``(sum_of_all_bands,)``.
        Returns:
            ``np.ndarray`` of shape ``(bands,)`` for a single layer, or
            ``(total_bands,)`` when ``layer=None``.
            Out-of-extent pixels are ``np.nan``.
        """
        if layer is not None:
            return self._entries[layer].values_at(pt)
        return np.concatenate(
            [e.values_at(pt) for e in self._entries.values()])

    def layer_info(self) -> dict[str, dict[str, str | int | float]]:
        """
        Summary of each layer — useful for logging and debugging.

        Returns dict of dicts with keys:
            path, mode ('loaded'|'streaming'), bands, crs_epsg, size_mb.
        """
        return {
            key: {
                "path": e.path.name,
                "mode": "loaded" if e.is_loaded else "streaming",
                "bands": e.bands,
                "crs_epsg": e.crs.to_epsg(),
                "size_mb": round(e.memory_bytes / 1e6, 1),
            }
            for key, e in self._entries.items()
        }


    def close(self) -> None:
        """Release all loaded arrays and clear internal state."""
        for entry in self._entries:
            entry.array = None
        self._entries.clear()
        self._bytes_committed = 0
        logger.debug("LayerStore closed.")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _load_or_stream(self, name: str, path: Path, bbox: BoundingBox) -> _LayerEntry:
        with rasterio.open(path) as ds:
            window = self._bbox_to_window(ds, bbox)
            transform = ds.window_transform(window)
            estimated = self._estimate_bytes(ds, window)

            fits = self._bytes_committed + estimated <= self._memory_budget_bytes
            if fits:
                array = ds.read(window=window)
                self._bytes_committed += array.nbytes
                logger.debug(
                    "  LOAD    %-40s  %.1f MB  (total: %.2f GB)",
                    path.name, array.nbytes / 1e6, self._bytes_committed / 1e9,
                )
                return _LayerEntry(
                    name=name, path=path, bbox_wgs84=bbox, array=array,
                    transform=transform, crs=ds.crs,
                    nodata=ds.nodata, bands=ds.count,
                )
            else:
                logger.info(
                    "  STREAM  %-40s  %.1f MB would exceed %.2f GB budget",
                    path.name, estimated / 1e6, self._memory_budget_bytes / 1e9,
                )
                return _LayerEntry(
                    name=name, path=path, bbox_wgs84=bbox, array=None,
                    transform=transform, crs=ds.crs,
                    nodata=ds.nodata, bands=ds.count,
                )

    @staticmethod
    def _bbox_to_window(
        ds: rasterio.DatasetReader, bbox: BoundingBox
    ) -> rasterio.windows.Window:
        """Convert a WGS84 BoundingBox to a rasterio Window in the dataset's CRS."""
        if ds.crs.to_epsg() == 4326:
            west, south, east, north = bbox
        else:
            t = Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True)
            west, south = t.transform(bbox.west, bbox.south)
            east, north = t.transform(bbox.east, bbox.north)
        return ds.window(west, south, east, north)

    @staticmethod
    def _estimate_bytes(
        ds: rasterio.DatasetReader, window: rasterio.windows.Window
    ) -> int:
        """
        Conservative upper-bound RAM estimate for reading ``window`` from ``ds``.
        Uses the largest itemsize across all bands.
        """
        rows = max(1, int(round(window.height)))
        cols = max(1, int(round(window.width)))
        itemsize = max(np.dtype(dt).itemsize for dt in ds.dtypes)
        return ds.count * rows * cols * itemsize
