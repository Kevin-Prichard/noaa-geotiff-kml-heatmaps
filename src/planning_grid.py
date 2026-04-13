"""
planning_grid.py — Uniform grid graph builder and terrain-clearance helper.

PlanningGrid is the single authority for:

  - **Building** a ``networkx.MultiDiGraph`` with uniformly-spaced WGS84 nodes
    over a ``BoundingBox`` at a configurable resolution, capped at a maximum
    node count.  If the requested resolution would produce too many nodes the
    resolution is coarsened automatically.

  - **Terrain sampling** — the DEM elevation is looked up from ``LayerStore``
    *once per node at build time* and cached as the ``terrain_elev_m`` node
    attribute, so ``is_flyable`` never blocks on I/O during planning.

  - **O(1) nearest-node lookup** — ``nearest_node(lon, lat)`` projects the
    query point into the local AEQD frame and rounds to the nearest grid cell
    index, giving a constant-time answer regardless of grid size.

Lifecycle
---------
``PlanningSession.__init__`` calls ``PlanningGrid.build(...)`` and stores the
result as ``self.grid``.  Each ``RoutePlanner`` subclass receives a reference
to ``session.grid`` at construction and operates on it.

Usage::

    from src.layer_store import BoundingBox, LayerStore
    from src.planning_grid import PlanningGrid, LAYER_TERRAIN

    bbox   = BoundingBox(-122.37, 37.60, -121.55, 38.02)
    layers = LayerStore.load({LAYER_TERRAIN: ("srtm.tif", bbox)})
    grid   = PlanningGrid.build(
        bbox=bbox,
        resolution_m=500.0,
        max_grid_nodes=50_000,
        layers=layers,
    )
    # Quick sanity checks
    nid = grid.nearest_node(lon=-122.0, lat=37.8)   # O(1)
    ok  = grid.is_flyable(nid, alt_m=350.0)          # terrain check (no I/O)
    print(grid)
    # PlanningGrid(5712 nodes, res=500.0 m, bbox=(-122.370,37.600,-121.550,38.020))

    # From a PlanningSession (forward-compatible duck-type adapter):
    grid = PlanningGrid.from_session(session)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import networkx
import pyproj
from shapely.geometry import Point

if TYPE_CHECKING:
    from src.layer_store import BoundingBox, LayerStore

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
# Duplicated from src.cost_model to avoid a runtime circular-import dependency.
# Authoritative definitions live in src/cost_model.py — keep these in sync.
LAYER_TERRAIN: str = "terrain"
_DEFAULT_TERRAIN_CLEARANCE_M: float = 30.0


@dataclass
class PlanningGrid:
    """
    Uniform 8-connected grid graph over a WGS84 bounding box.

    Node attributes
    ~~~~~~~~~~~~~~~
    ``lon``, ``lat``          — WGS84 position (EPSG:4326).
    ``x_m``, ``y_m``          — Local AEQD projected position (metres).
    ``terrain_elev_m``         — DEM elevation sampled at build time (metres).
    ``col``, ``row``           — Integer grid indices (0-based).

    Edge attributes
    ~~~~~~~~~~~~~~~
    ``dist_m``  — Euclidean distance in the local AEQD frame.
                  Cardinal edges: ``resolution_m``.
                  Diagonal edges: ``resolution_m × √2``.

    Planners may annotate edges with additional attributes (``cost``, ``weight``,
    …) without invalidating the terrain data stored on nodes.

    Notes
    -----
    - Use ``PlanningGrid.build(...)`` or ``PlanningGrid.from_session(session)``
      rather than calling the dataclass constructor directly.
    - ``terrain_layer`` is a ``LayerStore`` string key, *not* a positional index.
      Use ``LAYER_TERRAIN`` (= ``"terrain"``) as the conventional value.
    """

    graph:         networkx.MultiDiGraph
    resolution_m:  float          # actual grid spacing (≥ requested; may be coarsened)
    bbox:          "BoundingBox"
    terrain_layer: str            # LayerStore key for the DEM (default: LAYER_TERRAIN)

    # ── Private grid geometry (stored for O(1) nearest-node lookup) ────────────
    _n_cols: int   = field(repr=False, compare=False)
    _n_rows: int   = field(repr=False, compare=False)
    _x_sw_m: float = field(repr=False, compare=False)  # SW corner x in local AEQD
    _y_sw_m: float = field(repr=False, compare=False)  # SW corner y in local AEQD
    _proj4:  str   = field(repr=False, compare=False)  # proj4 string for local AEQD

    # ── Factories ─────────────────────────────────────────────────────────────

    @classmethod
    def build(
        cls,
        bbox:            "BoundingBox",
        resolution_m:    float,
        max_grid_nodes:  int,
        layers:          "LayerStore",
        terrain_layer:   str = LAYER_TERRAIN,
    ) -> "PlanningGrid":
        """
        Build a grid graph over *bbox* at *resolution_m* node spacing.

        If the requested resolution would exceed *max_grid_nodes*, the resolution
        is coarsened to the minimum value that fits within the budget and a
        ``WARNING`` is logged.

        Terrain elevation is sampled from ``layers[terrain_layer]`` once per
        node at build time and stored as the ``terrain_elev_m`` node attribute.
        Nodes that fall outside the DEM extent (NaN / exception) receive
        ``terrain_elev_m = 0.0`` and a ``DEBUG`` log entry.

        Args:
            bbox:           WGS84 bounding box (BoundingBox NamedTuple).
            resolution_m:   Target node spacing in metres.
            max_grid_nodes: Hard upper limit on node count.
            layers:         LayerStore containing at least ``terrain_layer``.
            terrain_layer:  LayerStore key for the elevation band.

        Returns:
            Fully initialised PlanningGrid with terrain pre-sampled.

        Raises:
            ValueError: if ``resolution_m ≤ 0`` or ``max_grid_nodes < 4``.
        """
        if resolution_m <= 0:
            raise ValueError(f"resolution_m must be > 0, got {resolution_m}")
        if max_grid_nodes < 4:
            raise ValueError(f"max_grid_nodes must be ≥ 4, got {max_grid_nodes}")

        # ── Local AEQD projection centred on bbox ──────────────────────────────
        clon = (bbox.west  + bbox.east)  / 2.0
        clat = (bbox.south + bbox.north) / 2.0
        proj4_str = f"+proj=aeqd +lat_0={clat} +lon_0={clon} +units=m"
        aeqd = pyproj.CRS.from_proj4(proj4_str)
        fwd  = pyproj.Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
        inv  = pyproj.Transformer.from_crs(aeqd, "EPSG:4326", always_xy=True)

        x_sw, y_sw = fwd.transform(bbox.west,  bbox.south)
        x_ne, y_ne = fwd.transform(bbox.east,  bbox.north)
        width_m    = x_ne - x_sw
        height_m   = y_ne - y_sw

        # ── Determine actual resolution (coarsen if needed) ────────────────────
        actual_res   = float(resolution_m)
        n_cols       = max(2, math.ceil(width_m  / actual_res) + 1)
        n_rows       = max(2, math.ceil(height_m / actual_res) + 1)
        n_requested  = n_cols * n_rows

        if n_requested > max_grid_nodes:
            # Solve: ceil(w/r) * ceil(h/r) ≤ max_grid_nodes  →  r ≥ √(w·h / max)
            actual_res = math.sqrt(width_m * height_m / max_grid_nodes) * 1.05
            n_cols     = max(2, math.ceil(width_m  / actual_res) + 1)
            n_rows     = max(2, math.ceil(height_m / actual_res) + 1)
            logger.warning(
                "PlanningGrid.build: %.1f m resolution → %d nodes > max %d; "
                "coarsened to %.1f m → %d nodes (%d cols × %d rows)",
                resolution_m, n_requested, max_grid_nodes,
                actual_res, n_cols * n_rows, n_cols, n_rows,
            )

        logger.info(
            "PlanningGrid.build: %d cols × %d rows = %d nodes "
            "at %.1f m spacing over %s",
            n_cols, n_rows, n_cols * n_rows, actual_res, bbox,
        )

        G: networkx.MultiDiGraph = networkx.MultiDiGraph()

        # ── Add nodes ──────────────────────────────────────────────────────────
        node_idx: dict[tuple[int, int], int] = {}
        node_id = 0

        for r in range(n_rows):
            y_m = y_sw + r * actual_res
            for c in range(n_cols):
                x_m = x_sw + c * actual_res
                lon, lat = inv.transform(x_m, y_m)
                pt = Point(lon, lat)

                # Sample terrain DEM (failure → 0.0 with debug log)
                try:
                    elev_arr = layers.values_at(pt, layer=terrain_layer)
                    elev     = float(elev_arr[0])
                    if math.isnan(elev):
                        elev = 0.0
                        logger.debug(
                            "PlanningGrid: nodata terrain at (%.5f, %.5f) → 0.0 m",
                            lon, lat,
                        )
                except Exception as exc:
                    elev = 0.0
                    logger.debug(
                        "PlanningGrid: terrain lookup failed at "
                        "(%.5f, %.5f): %s → 0.0 m", lon, lat, exc,
                    )

                G.add_node(
                    node_id,
                    lon=lon,  lat=lat,
                    x_m=x_m, y_m=y_m,
                    terrain_elev_m=elev,
                    col=c, row=r,
                )
                node_idx[(c, r)] = node_id
                node_id += 1

        # ── Add 8-connected directed edges ─────────────────────────────────────
        # (u → v) for each of the 8 neighbours; planners add their own weights.
        _NEIGHBOURS = (
            ( 1,  0), ( 0,  1), ( 1,  1), ( 1, -1),  # E  N  NE  SE
            (-1,  0), ( 0, -1), (-1, -1), (-1,  1),   # W  S  SW  NW
        )
        diag_dist = actual_res * math.sqrt(2.0)

        for r in range(n_rows):
            for c in range(n_cols):
                u = node_idx[(c, r)]
                for dc, dr in _NEIGHBOURS:
                    nc_, nr_ = c + dc, r + dr
                    if 0 <= nc_ < n_cols and 0 <= nr_ < n_rows:
                        v      = node_idx[(nc_, nr_)]
                        dist_m = diag_dist if (dc != 0 and dr != 0) else actual_res
                        G.add_edge(u, v, dist_m=dist_m)

        return cls(
            graph=G,
            resolution_m=actual_res,
            bbox=bbox,
            terrain_layer=terrain_layer,
            _n_cols=n_cols,
            _n_rows=n_rows,
            _x_sw_m=x_sw,
            _y_sw_m=y_sw,
            _proj4=proj4_str,
        )

    @classmethod
    def from_session(cls, session: Any) -> "PlanningGrid":
        """
        Convenience factory that reads all grid parameters from a PlanningSession.

        The session object is accessed via duck typing — no hard import of
        ``PlanningSession`` at module load time (avoids circular imports).

        Expected session attributes::

            session.bbox               : BoundingBox
            session.grid_resolution_m  : float
            session.max_grid_nodes     : int
            session.layers             : LayerStore
            session.terrain_layer      : str   (optional; falls back to LAYER_TERRAIN)

        Args:
            session: A PlanningSession instance (or any object matching the
                     duck-type contract above).

        Returns:
            PlanningGrid built from the session's parameters.
        """
        return cls.build(
            bbox           = session.bbox,
            resolution_m   = session.grid_resolution_m,
            max_grid_nodes = session.max_grid_nodes,
            layers         = session.layers,
            terrain_layer  = getattr(session, "terrain_layer", LAYER_TERRAIN),
        )

    # ── Terrain-clearance hard check ───────────────────────────────────────────

    def is_flyable(
        self,
        node_id:     int,
        alt_m:       float,
        clearance_m: float = _DEFAULT_TERRAIN_CLEARANCE_M,
    ) -> bool:
        """
        Return ``True`` if *alt_m* clears the terrain at *node_id* by at
        least *clearance_m* metres.

        Uses the DEM elevation precomputed at build time — **no I/O**.
        This is the terrain half of the hard feasibility gate; battery and
        no-fly-zone checks are handled separately by ``CostModel.is_flyable``.

        Args:
            node_id:     Graph node identifier (integer key assigned by ``build``).
            alt_m:       Candidate flight altitude (metres; same vertical datum as DEM).
            clearance_m: Minimum vertical margin above DEM elevation.
                         Defaults to ``_DEFAULT_TERRAIN_CLEARANCE_M`` (30 m).

        Returns:
            ``True`` if the point is safe to fly at *alt_m*.
            ``False`` if *node_id* does not exist in the graph, or if the
            altitude is below the terrain hard-deck.
        """
        try:
            terrain_elev = self.graph.nodes[node_id]["terrain_elev_m"]
        except KeyError:
            logger.warning(
                "PlanningGrid.is_flyable: node_id %d not found in grid", node_id
            )
            return False
        return alt_m >= terrain_elev + clearance_m

    # ── Spatial helpers ────────────────────────────────────────────────────────

    def nearest_node(self, lon: float, lat: float) -> int:
        """
        Return the node_id whose grid position is nearest to *(lon, lat)*.

        **O(1)** implementation: projects the query point into the local AEQD
        frame, computes fractional grid indices, and rounds to the nearest
        integer cell — no iteration over nodes.

        The returned node is always within the grid (clamped to boundary cells
        if the query point is outside the bbox).

        Args:
            lon: WGS84 longitude (degrees east).
            lat: WGS84 latitude  (degrees north).

        Returns:
            Integer node ID of the nearest grid node.
        """
        aeqd = pyproj.CRS.from_proj4(self._proj4)
        fwd  = pyproj.Transformer.from_crs("EPSG:4326", aeqd, always_xy=True)
        qx, qy = fwd.transform(lon, lat)

        c = int(round((qx - self._x_sw_m) / self.resolution_m))
        r = int(round((qy - self._y_sw_m) / self.resolution_m))
        c = max(0, min(c, self._n_cols - 1))
        r = max(0, min(r, self._n_rows - 1))

        # node_id assignment matches the build() loop: row-major order
        return r * self._n_cols + c

    def node_point(self, node_id: int) -> Point:
        """
        Return the ``shapely.geometry.Point`` (WGS84) for *node_id*.

        Raises ``KeyError`` if *node_id* is not in the graph.
        """
        data = self.graph.nodes[node_id]
        return Point(data["lon"], data["lat"])

    def node_terrain_elev(self, node_id: int) -> float:
        """
        Return the precomputed DEM elevation (metres) at *node_id*.

        Raises ``KeyError`` if *node_id* is not in the graph.
        """
        return float(self.graph.nodes[node_id]["terrain_elev_m"])

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        """Total number of nodes in the grid graph."""
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        """Total number of directed edges (includes both directions of each pair)."""
        return self.graph.number_of_edges()

    @property
    def shape(self) -> tuple[int, int]:
        """Grid dimensions as ``(n_cols, n_rows)``."""
        return (self._n_cols, self._n_rows)

    def __repr__(self) -> str:
        bb = self.bbox
        return (
            f"PlanningGrid({self.node_count} nodes, "
            f"res={self.resolution_m:.1f} m, "
            f"bbox=({bb.west:.3f},{bb.south:.3f},{bb.east:.3f},{bb.north:.3f}))"
        )
