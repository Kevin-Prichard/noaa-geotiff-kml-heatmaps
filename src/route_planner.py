"""route_planner.py — RoutePlanner ABC and Dijkstra / A* / ARA* / D* Lite implementations."""
from __future__ import annotations

import abc
import copy
import heapq
import logging
import math
from typing import TYPE_CHECKING

import networkx
import pyproj

from src.waypoints import NoPathFoundError, _bearing_deg

if TYPE_CHECKING:
    import geopandas as gpd
    from src.flight_point import FlightPoint
    from src.planning_session import PlanningSession

logging.getLogger("src.route_planner").setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

_CLEARANCE_M = 30.0   # default terrain AGL clearance for edge-weight computation


# ── Module-level helper for joblib Parallel ────────────────────────────────────

def _planner_plan(planner: "RoutePlanner") -> tuple[type, networkx.MultiDiGraph]:
    return type(planner), planner.plan()


# ── Abstract base ──────────────────────────────────────────────────────────────

class RoutePlanner(abc.ABC):

    def __init__(self, session: "PlanningSession") -> None:
        self.session   = session
        self._step_nr  = 0
        # Deep copy isolates each planner's node/edge annotations from siblings
        self._graph    = copy.deepcopy(session.grid.graph)
        self._path: list[int] = []
        self._done     = False
        self._geod     = pyproj.Geod(ellps="WGS84")
        # Nearest grid nodes to start / end
        sp = session.start().point;  ep = session.end().point
        self._start_id = session.grid.nearest_node(sp.x, sp.y)
        self._goal_id  = session.grid.nearest_node(ep.x, ep.y)

    def _increment_step(self) -> int:
        self._step_nr += 1
        return self._step_nr

    def to_gdfs(self) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        import geopandas as gpd
        from shapely.geometry import LineString, Point as SPoint

        nodes = [
            {"node_id": nid, "geometry": SPoint(nd["lon"], nd["lat"]),
             "cost": nd.get("cost", 0.0),
             "path_aggregate_cost": nd.get("path_aggregate_cost", 0.0),
             "terrain_elev_m": nd.get("terrain_elev_m", 0.0)}
            for nid, nd in self._graph.nodes(data=True)
            if "path_aggregate_cost" in nd
        ]
        edges = [
            {"u": u, "v": v,
             "geometry": LineString([(self._graph.nodes[u]["lon"], self._graph.nodes[u]["lat"]),
                                     (self._graph.nodes[v]["lon"], self._graph.nodes[v]["lat"])]),
             "dist_m": ed.get("dist_m", 0.0),
             "weight": ed.get("weight", float("nan"))}
            for u, v, ed in self._graph.edges(data=True)
            if "weight" in ed
        ]
        nodes_gdf = gpd.GeoDataFrame(nodes, crs="EPSG:4326") if nodes else gpd.GeoDataFrame()
        edges_gdf = gpd.GeoDataFrame(edges, crs="EPSG:4326") if edges else gpd.GeoDataFrame()
        return nodes_gdf, edges_gdf

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _node_alt(self, node_id: int) -> float:
        nd = self._graph.nodes[node_id]
        return max(nd.get("terrain_elev_m", 0.0) + _CLEARANCE_M,
                   self.session.uav_state.altitude_m)

    def _node_fp(self, node_id: int, toward: int | None = None) -> "FlightPoint":
        from src.flight_point import FlightPoint
        nd  = self._graph.nodes[node_id]
        alt = self._node_alt(node_id)
        if toward is not None and toward in self._graph.nodes:
            tnd = self._graph.nodes[toward]
            hdg = _bearing_deg(nd["lon"], nd["lat"], tnd["lon"], tnd["lat"])
        else:
            hdg = self.session.uav_state.heading_deg
        return FlightPoint.from_lonlat(nd["lon"], nd["lat"], alt, hdg,
                                       self.session.uav_spec.cruising_speed_mps)

    def _is_node_flyable(self, node_id: int) -> bool:
        if node_id not in self._graph.nodes:
            return False
        alt = self._node_alt(node_id)
        if not self.session.grid.is_flyable(node_id, alt):
            return False
        fp = self._node_fp(node_id)
        try:
            return self.session.cost_model.is_flyable(
                fp, self.session.uav_state, self.session.uav_spec,
                self.session.layers, self.session.no_fly_zones,
            )
        except Exception as exc:
            logger.debug("is_flyable(%d): %s", node_id, exc)
            return True   # assume flyable on error; terrain check already passed

    def _edge_weight(self, u: int, v: int) -> float:
        try:
            data = self._graph.edges[u, v, 0]
        except KeyError:
            return math.inf
        if "weight" not in data:
            if not self._is_node_flyable(v):
                data["weight"] = math.inf
                return math.inf
            fp_u = self._node_fp(u, toward=v)
            fp_v = self._node_fp(v)
            try:
                w = self.session.cost_model.edge_cost(
                    fp_u, fp_v,
                    self.session.uav_state, self.session.uav_spec,
                    self.session.layers,
                )
            except Exception as exc:
                logger.warning("_edge_weight(%d,%d): %s; falling back to dist proxy", u, v, exc)
                w = data.get("dist_m", 1000.0) * self.session.uav_spec.cruise_energy_wh_per_m(
                    self.session.uav_spec.cruising_speed_mps)
            data["weight"] = max(0.0, w) if not math.isinf(w) else math.inf
        return data["weight"]

    def _h(self, u: int, v: int) -> float:
        """Admissible lower-bound heuristic: straight-line energy (Wh)."""
        if u == v:
            return 0.0
        nu = self._graph.nodes.get(u)
        nv = self._graph.nodes.get(v)
        if nu is None or nv is None:
            return 0.0
        _, _, dist_m = self._geod.inv(nu["lon"], nu["lat"], nv["lon"], nv["lat"])
        return abs(dist_m) * self.session.uav_spec.cruise_energy_wh_per_m(
            self.session.uav_spec.cruising_speed_mps)

    def _reconstruct_path(self, goal: int, came_from: dict[int, int]) -> list[int]:
        path, cur = [], goal
        while cur is not None:
            path.append(cur)
            cur = came_from.get(cur)
        return list(reversed(path))

    def _annotate_path(self, path: list[int], g_scores: dict[int, float]) -> None:
        """Write cost / path_aggregate_cost into graph node attributes."""
        for i, nid in enumerate(path):
            nd   = self._graph.nodes[nid]
            pagg = g_scores.get(nid, math.inf)
            nd["path_aggregate_cost"] = pagg
            if i == 0:
                nd["cost"] = 0.0
            else:
                prev_pagg = g_scores.get(path[i - 1], 0.0)
                nd["cost"] = pagg - prev_pagg

    def get_path(self) -> list[int]:
        return list(self._path)

    @abc.abstractmethod
    def step(self) -> tuple[int, networkx.MultiDiGraph]: ...

    @abc.abstractmethod
    def plan(self) -> networkx.MultiDiGraph: ...


# ── Dijkstra ───────────────────────────────────────────────────────────────────

class RoutePlannerDijkstra(RoutePlanner):

    def __init__(self, session: "PlanningSession") -> None:
        super().__init__(session)
        self._dist: dict[int, float] = {self._start_id: 0.0}
        self._came_from: dict[int, int] = {}
        # heap entries: (cost, node_id)
        self._heap: list = [(0.0, self._start_id)]

    def step(self) -> tuple[int, networkx.MultiDiGraph]:
        if self._done:
            return self._step_nr, self._graph
        if not self._heap:
            self._done = True
            return self._increment_step(), self._graph

        d, u = heapq.heappop(self._heap)
        if d > self._dist.get(u, math.inf):
            return self._increment_step(), self._graph   # stale entry

        if u == self._goal_id:
            self._path = self._reconstruct_path(u, self._came_from)
            self._annotate_path(self._path, self._dist)
            self._done = True
            return self._increment_step(), self._graph

        for v in self._graph.successors(u):
            if not self._is_node_flyable(v):
                continue
            w = self._edge_weight(u, v)
            if math.isinf(w):
                continue
            nd = d + w
            if nd < self._dist.get(v, math.inf):
                self._dist[v] = nd
                self._came_from[v] = u
                heapq.heappush(self._heap, (nd, v))

        return self._increment_step(), self._graph

    def plan(self) -> networkx.MultiDiGraph:
        while not self._done:
            self.step()
        if not self._path:
            raise NoPathFoundError(
                f"Dijkstra found no path {self._start_id}→{self._goal_id}")
        return self._graph


# ── A* ─────────────────────────────────────────────────────────────────────────

class RoutePlannerAStar(RoutePlanner):

    def __init__(self, session: "PlanningSession") -> None:
        super().__init__(session)
        self._g: dict[int, float] = {self._start_id: 0.0}
        self._came_from: dict[int, int] = {}
        self._closed: set[int] = set()
        # heap entries: (f, g, node_id) — g stored for staleness check
        f0 = self._h(self._start_id, self._goal_id)
        self._heap: list = [(f0, 0.0, self._start_id)]

    def step(self) -> tuple[int, networkx.MultiDiGraph]:
        if self._done:
            return self._step_nr, self._graph

        # Drain stale/closed entries
        while self._heap:
            f, g_stored, s = self._heap[0]
            if g_stored == self._g.get(s, math.inf) and s not in self._closed:
                break
            heapq.heappop(self._heap)

        if not self._heap:
            self._done = True
            return self._increment_step(), self._graph

        f, g_cur, s = heapq.heappop(self._heap)
        self._closed.add(s)

        if s == self._goal_id:
            self._path = self._reconstruct_path(s, self._came_from)
            self._annotate_path(self._path, self._g)
            self._done = True
            return self._increment_step(), self._graph

        for t in self._graph.successors(s):
            if t in self._closed or not self._is_node_flyable(t):
                continue
            w = self._edge_weight(s, t)
            if math.isinf(w):
                continue
            ng = g_cur + w
            if ng < self._g.get(t, math.inf):
                self._g[t] = ng
                self._came_from[t] = s
                heapq.heappush(self._heap,
                               (ng + self._h(t, self._goal_id), ng, t))

        return self._increment_step(), self._graph

    def plan(self) -> networkx.MultiDiGraph:
        while not self._done:
            self.step()
        if not self._path:
            raise NoPathFoundError(
                f"A* found no path {self._start_id}→{self._goal_id}")
        return self._graph


# ── ARA* ────────────────────────────────────────────────────────────────────────

class RoutePlannerARAStar(RoutePlanner):
    """Anytime Repairing A*: produces a sequence of improving solutions."""

    def __init__(
        self,
        session:           "PlanningSession",
        epsilon_initial:   float = 3.0,
        epsilon_final:     float = 1.0,
        epsilon_decrement: float = 0.5,
    ) -> None:
        super().__init__(session)
        self.epsilon_initial   = epsilon_initial
        self.epsilon_final     = epsilon_final
        self.epsilon_decrement = epsilon_decrement
        self._epsilon  = float(epsilon_initial)
        self._g: dict[int, float] = {self._start_id: 0.0}
        self._came_from: dict[int, int] = {}
        self._OPEN:   set[int] = {self._start_id}
        self._CLOSED: set[int] = set()
        self._INCONS: set[int] = set()
        self._solutions: list[list[int]] = []
        # heap: (f, g, node_id)
        f0 = 0.0 + epsilon_initial * self._h(self._start_id, self._goal_id)
        self._heap: list = [(f0, 0.0, self._start_id)]

    def _g_val(self, s: int) -> float:
        return self._g.get(s, math.inf)

    def _f(self, s: int, eps: float) -> float:
        return self._g_val(s) + eps * self._h(s, self._goal_id)

    def _improve_path(self) -> list[int] | None:
        eps = self._epsilon
        while self._OPEN:
            # Find true minimum via heap (lazy deletion)
            while self._heap:
                f_top, g_stored, s = self._heap[0]
                if s in self._OPEN and g_stored == self._g_val(s):
                    break
                heapq.heappop(self._heap)
            else:
                break

            g_goal = self._g_val(self._goal_id)
            if f_top >= g_goal:
                break

            heapq.heappop(self._heap)
            self._OPEN.discard(s)
            self._CLOSED.add(s)

            for t in self._graph.successors(s):
                if not self._is_node_flyable(t):
                    continue
                w = self._edge_weight(s, t)
                if math.isinf(w):
                    continue
                ng = self._g_val(s) + w
                if ng < self._g_val(t):
                    self._g[t] = ng
                    self._came_from[t] = s
                    if t not in self._CLOSED:
                        self._OPEN.add(t)
                        heapq.heappush(self._heap, (self._f(t, eps), ng, t))
                    else:
                        self._INCONS.add(t)

        if self._g_val(self._goal_id) < math.inf:
            return self._reconstruct_path(self._goal_id, self._came_from)
        return None

    def step(self) -> tuple[int, networkx.MultiDiGraph]:
        if self._done:
            return self._step_nr, self._graph

        path = self._improve_path()
        if path:
            self._solutions.append(path)
            self._path = path
            self._annotate_path(path, self._g)
            logger.info("ARA* solution at ε=%.2f, cost=%.4f Wh",
                        self._epsilon, self._g_val(self._goal_id))

        self._epsilon = max(self.epsilon_final,
                            self._epsilon - self.epsilon_decrement)
        if self._epsilon <= self.epsilon_final:
            self._done = True
        else:
            self._OPEN.update(self._INCONS)
            self._INCONS.clear()
            self._CLOSED.clear()
            # Rebuild heap with updated ε
            self._heap = []
            for s in self._OPEN:
                heapq.heappush(self._heap, (self._f(s, self._epsilon),
                                            self._g_val(s), s))

        return self._increment_step(), self._graph

    def plan(self) -> networkx.MultiDiGraph:
        while not self._done:
            self.step()
        if not self._path:
            raise NoPathFoundError(
                f"ARA* found no path {self._start_id}→{self._goal_id}")
        return self._graph


# ── D* Lite ────────────────────────────────────────────────────────────────────

class RoutePlannerDStarLite(RoutePlanner):
    """
    D* Lite: optimal backward-search planner with dynamic edge-cost repair.

    Plans from goal → start so that update_edge_costs() can repair the
    priority queue incrementally when raster data changes mid-mission.
    """

    def __init__(self, session: "PlanningSession") -> None:
        super().__init__(session)
        self._s_start = self._start_id
        self._s_goal  = self._goal_id
        self._s_last  = self._s_start
        self._g:   dict[int, float] = {}    # default inf
        self._rhs: dict[int, float] = {}    # default inf
        self._km   = 0.0
        # Priority queue: heap of (k1, k2, node_id); _in_open is the authoritative set
        self._heap:    list[tuple[float, float, int]] = []
        self._in_open: dict[int, tuple[float, float]] = {}
        # Seed goal
        self._rhs[self._s_goal] = 0.0
        self._insert(self._s_goal, self._calc_key(self._s_goal))

    # ── D* Lite internals ──────────────────────────────────────────────────────

    def _g_val(self, s: int) -> float:   return self._g.get(s, math.inf)
    def _rhs_val(self, s: int) -> float: return self._rhs.get(s, math.inf)

    def _calc_key(self, s: int) -> tuple[float, float]:
        m = min(self._g_val(s), self._rhs_val(s))
        return (m + self._h(self._s_start, s) + self._km, m)

    def _insert(self, s: int, key: tuple[float, float]) -> None:
        self._in_open[s] = key
        heapq.heappush(self._heap, (key[0], key[1], s))

    def _remove(self, s: int) -> None:
        self._in_open.pop(s, None)

    def _top_key(self) -> tuple[float, float] | None:
        while self._heap:
            k1, k2, s = self._heap[0]
            if s in self._in_open and self._in_open[s] == (k1, k2):
                return (k1, k2)
            heapq.heappop(self._heap)
        return None

    def _pop_min(self) -> tuple[tuple[float, float], int] | None:
        while self._heap:
            k1, k2, s = heapq.heappop(self._heap)
            if s in self._in_open and self._in_open[s] == (k1, k2):
                del self._in_open[s]
                return (k1, k2), s
        return None

    def _update_vertex(self, u: int) -> None:
        if u != self._s_goal:
            # rhs(u) = min over forward-successors v of c(u,v) + g(v)
            best = math.inf
            for v in self._graph.successors(u):
                c = self._edge_weight(u, v) + self._g_val(v)
                if c < best:
                    best = c
            self._rhs[u] = best
        self._remove(u)
        if self._g_val(u) != self._rhs_val(u):
            self._insert(u, self._calc_key(u))

    def _process_one(self) -> bool:
        """One iteration of compute_shortest_path(). Returns True if still running."""
        top = self._top_key()
        if top is None:
            return False
        start_key = self._calc_key(self._s_start)
        if top >= start_key and self._rhs_val(self._s_start) == self._g_val(self._s_start):
            return False  # converged

        result = self._pop_min()
        if result is None:
            return False
        k_old, u = result
        k_new = self._calc_key(u)

        if k_old < k_new:
            self._insert(u, k_new)
        elif self._g_val(u) > self._rhs_val(u):
            # Overconsistent
            self._g[u] = self._rhs_val(u)
            for s in self._graph.predecessors(u):
                self._update_vertex(s)
        else:
            # Underconsistent
            g_old = self._g_val(u)
            self._g.pop(u, None)
            for s in list(self._graph.predecessors(u)) + [u]:
                if s != u and self._rhs_val(s) == self._edge_weight(s, u) + g_old:
                    # rhs(s) was computed through u; recompute
                    best = math.inf
                    for v in self._graph.successors(s):
                        c = self._edge_weight(s, v) + self._g_val(v)
                        if c < best:
                            best = c
                    self._rhs[s] = best
                self._update_vertex(s)
        return True

    def _extract_path(self) -> list[int]:
        if math.isinf(self._g_val(self._s_start)):
            return []
        path, cur, seen = [self._s_start], self._s_start, {self._s_start}
        while cur != self._s_goal:
            best_v, best_c = None, math.inf
            for v in self._graph.successors(cur):
                c = self._edge_weight(cur, v) + self._g_val(v)
                if c < best_c and v not in seen:
                    best_c, best_v = c, v
            if best_v is None or math.isinf(best_c):
                return []
            path.append(best_v)  # type: ignore[arg-type]
            seen.add(best_v)  # type: ignore[arg-type]
            cur = best_v  # type: ignore[assignment]
        return path

    def _annotate_dstar(self) -> None:
        total = self._g_val(self._s_start)
        for i, nid in enumerate(self._path):
            nd   = self._graph.nodes[nid]
            pagg = total - self._g_val(nid) if not math.isinf(total) else 0.0
            nd["g"]   = self._g_val(nid)
            nd["rhs"] = self._rhs_val(nid)
            nd["path_aggregate_cost"] = pagg
            nd["cost"] = (pagg - self._graph.nodes[self._path[i - 1]].get(
                "path_aggregate_cost", 0.0)) if i > 0 else 0.0

    # ── Public interface ───────────────────────────────────────────────────────

    def step(self) -> tuple[int, networkx.MultiDiGraph]:
        if not self._done:
            running = self._process_one()
            if not running:
                self._done = True
                self._path = self._extract_path()
                if self._path:
                    self._annotate_dstar()
        return self._increment_step(), self._graph

    def plan(self) -> networkx.MultiDiGraph:
        while self._process_one():
            pass
        self._done = True
        self._path = self._extract_path()
        if not self._path:
            raise NoPathFoundError(
                f"D* Lite found no path {self._s_start}→{self._s_goal}")
        self._annotate_dstar()
        return self._graph

    def update_edge_costs(self, changed_nodes: list[int]) -> None:
        """Invalidate cached edge weights around changed nodes and repair the plan."""
        for nid in changed_nodes:
            for v in list(self._graph.successors(nid)):
                try:
                    self._graph.edges[nid, v, 0].pop("weight", None)
                except KeyError:
                    pass
            for u in list(self._graph.predecessors(nid)):
                try:
                    self._graph.edges[u, nid, 0].pop("weight", None)
                except KeyError:
                    pass
        self._km += self._h(self._s_last, self._s_start)
        self._s_last = self._s_start
        for nid in changed_nodes:
            self._update_vertex(nid)
        # Re-converge
        while self._process_one():
            pass
        self._done = True
        self._path = self._extract_path()
        if self._path:
            self._annotate_dstar()
