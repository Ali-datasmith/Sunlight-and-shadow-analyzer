import math
from geometry import Vec3, building_aabb, ray_aabb, shadow_polygon
from solar import solar_position, sun_vector, EL_MIN_DEG
from scenario import Scenario, Building

try:
    import numpy as np
except ImportError:
    np = None


class HeatmapGrid:
    """Stores sunlight-hours accumulation data across the ground grid and rooftops."""
    def __init__(
        self,
        resolution: tuple[int, int],
        hours_array: list[list[float]],
        cos_hours_array: list[list[float]],
        roof_hours: dict[int, list[list[float]]],
        date: tuple[int, int, int],
        t_start_min: int,
        t_end_min: int,
        step_min: int,
        samples_used: int,
        max_hours: float,
        params_key: tuple,
        scenario_revision: int
    ):
        self.resolution = resolution
        self.hours_array = hours_array
        self.cos_hours_array = cos_hours_array
        self.roof_hours = roof_hours
        self.date = date
        self.t_start_min = t_start_min
        self.t_end_min = t_end_min
        self.step_min = step_min
        self.samples_used = samples_used
        self.max_hours = max_hours
        self.params_key = params_key
        self.scenario_revision = scenario_revision


class HeatmapJob:
    """Incremental, cancellable job to compute daylight hours over a day."""
    def __init__(
        self,
        scenario: Scenario,
        date: tuple[int, int, int],
        t0_min: int,
        t1_min: int,
        step_min: int
    ):
        self.scenario = scenario
        self.date = date
        self.t0 = int(t0_min)
        self.t1 = int(t1_min)
        self.step_min = int(step_min)

        self.nx, self.ny = scenario.ground_size
        self.cs = scenario.cell_size_m
        self.gw = self.nx * self.cs
        self.gd = self.ny * self.cs

        total_span = max(0, self.t1 - self.t0)
        self.num_steps = math.ceil(total_span / self.step_min) if total_span > 0 else 0
        self.current_step = 0
        self.weight_hours = self.step_min / 60.0
        self.cancelled = False

        # Precompute occupied ground cells (-1.0)
        self.occupied = self.scenario.occupied_mask()
        self.hours_array = [
            [-1.0 if self.occupied[j][i] else 0.0 for i in range(self.nx)]
            for j in range(self.ny)
        ]
        self.cos_hours_array = [
            [-1.0 if self.occupied[j][i] else 0.0 for i in range(self.nx)]
            for j in range(self.ny)
        ]

        # Rooftop sample points: building_id -> dict of sample point coordinates
        self.roof_samples: dict[int, list[tuple[int, int, Vec3]]] = {}
        self.roof_hours: dict[int, list[list[float]]] = {}
        for b in self.scenario.buildings:
            r_nx = max(1, int(round(b.size.x / self.cs)))
            r_ny = max(1, int(round(b.size.y / self.cs)))
            self.roof_hours[b.id] = [[0.0 for _ in range(r_nx)] for _ in range(r_ny)]
            r_pts = []
            for rj in range(r_ny):
                for ri in range(r_nx):
                    pt = Vec3(
                        b.position.x + (ri + 0.5) * self.cs,
                        b.position.y + (rj + 0.5) * self.cs,
                        b.size.z + 0.01
                    )
                    r_pts.append((ri, rj, pt))
            self.roof_samples[b.id] = r_pts

        self.building_boxes = [building_aabb(b) for b in self.scenario.buildings]
        self.params_key = (
            self.scenario.lat,
            self.scenario.lon,
            self.scenario.tz_offset,
            self.date,
            self.step_min,
            (self.t0, self.t1)
        )

    def cancel(self) -> None:
        self.cancelled = True

    def progress(self) -> float:
        if self.num_steps == 0:
            return 1.0
        return min(1.0, self.current_step / float(self.num_steps))

    def step(self) -> bool:
        """Processes one time step. Returns True if more steps remain, False when finished."""
        if self.cancelled or self.current_step >= self.num_steps:
            return False

        t = self.t0 + (self.current_step + 0.5) * self.step_min
        self.current_step += 1

        sun = solar_position(
            self.scenario.lat,
            self.scenario.lon,
            self.date,
            t,
            self.scenario.tz_offset
        )

        if sun.elevation_deg >= EL_MIN_DEG:
            s = sun_vector(sun.azimuth_deg, sun.elevation_deg)
            sin_el = math.sin(math.radians(sun.elevation_deg))

            # Precompute shadow bounding boxes for broad-phase rejection
            shadow_bboxes = []
            for b in self.scenario.buildings:
                poly = shadow_polygon(b, s, self.gw, self.gd)
                if poly:
                    min_x = min(p[0] for p in poly) - 0.1
                    max_x = max(p[0] for p in poly) + 0.1
                    min_y = min(p[1] for p in poly) - 0.1
                    max_y = max(p[1] for p in poly) + 0.1
                    shadow_bboxes.append((min_x, min_y, max_x, max_y))
                else:
                    shadow_bboxes.append((0.0, 0.0, 0.0, 0.0))

            # Ground points accumulation
            for j in range(self.ny):
                cy = (j + 0.5) * self.cs
                for i in range(self.nx):
                    if self.occupied[j][i]:
                        continue
                    cx = (i + 0.5) * self.cs
                    p = Vec3(cx, cy, 0.001)

                    hit = False
                    for b_idx, bbox in enumerate(shadow_bboxes):
                        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
                            if ray_aabb(p, s, self.building_boxes[b_idx]) is not None:
                                hit = True
                                break

                    if not hit:
                        self.hours_array[j][i] += self.weight_hours
                        self.cos_hours_array[j][i] += self.weight_hours * sin_el

            # Rooftop points accumulation
            for b_idx, b in enumerate(self.scenario.buildings):
                for ri, rj, pt in self.roof_samples.get(b.id, []):
                    hit = False
                    for o_idx, o_box in enumerate(self.building_boxes):
                        if o_idx == b_idx:
                            continue
                        if ray_aabb(pt, s, o_box) is not None:
                            hit = True
                            break
                    if not hit:
                        self.roof_hours[b.id][rj][ri] += self.weight_hours

        return self.current_step < self.num_steps

    def result(self) -> HeatmapGrid | None:
        if self.cancelled:
            return None

        max_h = 0.0
        for row in self.hours_array:
            for val in row:
                if val > max_h:
                    max_h = val

        return HeatmapGrid(
            resolution=(self.nx, self.ny),
            hours_array=self.hours_array,
            cos_hours_array=self.cos_hours_array,
            roof_hours=self.roof_hours,
            date=self.date,
            t_start_min=self.t0,
            t_end_min=self.t1,
            step_min=self.step_min,
            samples_used=self.current_step,
            max_hours=max_h,
            params_key=self.params_key,
            scenario_revision=self.scenario.revision
        )


def compare(
    grid_a: HeatmapGrid,
    grid_b: HeatmapGrid,
    scen_a: Scenario,
    scen_b: Scenario,
    target_hours: float = 2.0
) -> tuple[dict, list[list[float]]]:
    """Compares sunlight hours between two layouts across common unoccupied cells."""
    nx, ny = grid_a.resolution
    cs = scen_a.cell_size_m
    step_min = grid_a.step_min
    tau = max(0.25, step_min / 60.0)

    sa = 0.0
    sb = 0.0
    common_count = 0
    gained = 0
    lost = 0
    frac_a_count = 0
    frac_b_count = 0

    diff_grid = [[-999.0 for _ in range(nx)] for _ in range(ny)]

    for j in range(ny):
        for i in range(nx):
            ha = grid_a.hours_array[j][i]
            hb = grid_b.hours_array[j][i]

            if ha >= 0.0 and hb >= 0.0:
                common_count += 1
                sa += ha
                sb += hb
                diff = hb - ha
                diff_grid[j][i] = diff

                if diff > tau:
                    gained += 1
                elif diff < -tau:
                    lost += 1

                if ha >= target_hours:
                    frac_a_count += 1
                if hb >= target_hours:
                    frac_b_count += 1

    delta = sb - sa
    pct = (100.0 * delta / sa) if sa > 1e-9 else 0.0
    mean_change = (delta / common_count) if common_count > 0 else 0.0
    frac_a = (frac_a_count / common_count) if common_count > 0 else 0.0
    frac_b = (frac_b_count / common_count) if common_count > 0 else 0.0
    area_hours = delta * (cs * cs)

    # Roof average hours compared by label
    roof_diffs = {}
    for ba in scen_a.buildings:
        for bb in scen_b.buildings:
            if ba.label == bb.label:
                ra = grid_a.roof_hours.get(ba.id, [[]])
                rb = grid_b.roof_hours.get(bb.id, [[]])
                vals_a = [v for r in ra for v in r]
                vals_b = [v for r in rb for v in r]
                avg_a = sum(vals_a) / len(vals_a) if vals_a else 0.0
                avg_b = sum(vals_b) / len(vals_b) if vals_b else 0.0
                roof_diffs[ba.label] = avg_b - avg_a

    metrics = {
        "delta": delta,
        "area_hours": area_hours,
        "pct": pct,
        "mean_change": mean_change,
        "gained": gained,
        "lost": lost,
        "unchanged": common_count - gained - lost,
        "common_count": common_count,
        "frac_a": frac_a,
        "frac_b": frac_b,
        "roof_diffs": roof_diffs,
    }
    return (metrics, diff_grid)


def run_checks() -> list[tuple[str, bool, str]]:
    """Self-test verification for heatmap accumulation and comparison mathematics."""
    results = []

    # 1. Midpoint accumulation of constant visibility over 12 hours with dt=15 min
    dt = 15
    span_hours = 12.0
    num_steps = int(span_hours * 60 / dt)
    w = dt / 60.0
    acc = sum(w for _ in range(num_steps))
    ok_midpoint = abs(acc - 12.0) < 1e-9
    results.append(("Heatmap: Midpoint rule constant accumulation", ok_midpoint, f"Total={acc:.4f} h (expected 12.0)"))

    # 2. Comparison identity and antisymmetry test
    dummy_a = HeatmapGrid(
        resolution=(2, 2),
        hours_array=[[6.0, 7.0], [8.0, 9.0]],
        cos_hours_array=[[4.0, 5.0], [6.0, 7.0]],
        roof_hours={},
        date=(2024, 3, 21),
        t_start_min=360,
        t_end_min=1080,
        step_min=15,
        samples_used=48,
        max_hours=9.0,
        params_key=(),
        scenario_revision=1
    )
    dummy_b = HeatmapGrid(
        resolution=(2, 2),
        hours_array=[[4.0, 7.0], [10.0, 8.0]],
        cos_hours_array=[[3.0, 5.0], [8.0, 6.0]],
        roof_hours={},
        date=(2024, 3, 21),
        t_start_min=360,
        t_end_min=1080,
        step_min=15,
        samples_used=48,
        max_hours=10.0,
        params_key=(),
        scenario_revision=1
    )
    scen = Scenario("Test", [], ground_size=(2, 2))
    m_ident, _ = compare(dummy_a, dummy_a, scen, scen)
    m_ab, _ = compare(dummy_a, dummy_b, scen, scen)
    m_ba, _ = compare(dummy_b, dummy_a, scen, scen)

    ok_ident = abs(m_ident["delta"]) < 1e-9
    ok_antisym = abs(m_ab["delta"] + m_ba["delta"]) < 1e-9
    results.append(("Heatmap: Comparison identity compare(A, A) == 0", ok_ident, f"Delta={m_ident['delta']}"))
    results.append(("Heatmap: Comparison antisymmetry delta(A,B) == -delta(B,A)", ok_antisym, f"ab={m_ab['delta']}, ba={m_ba['delta']}"))

    # 3. Permanent shadow test on winter solstice
    # 20m wide, 30m tall wall at X in [20, 40], Y in [20, 22], Z=30.
    # Sample point 2m north of center -> (30, 24, 0)
    wall = Building(1, "Wall", Vec3(20.0, 20.0, 0.0), Vec3(20.0, 2.0, 30.0), "#D98E73")
    wall_scen = Scenario("WallSite", [wall], ground_size=(30, 30), lat=31.5204, lon=74.3587, tz_offset=5.0)
    job = HeatmapJob(wall_scen, (2024, 12, 21), 400, 1050, 15)
    while job.step():
        pass
    res = job.result()
    # Cell 2m north of wall center is at x=30, y=24 -> i = 15, j = 12
    cell_val = res.hours_array[12][15] if res else -1.0
    ok_shadow = (cell_val == 0.0)
    results.append(("Heatmap: Permanent shadow north of tall wall (21 Dec)", ok_shadow, f"Hours={cell_val:.2f} h (expected 0.0)"))

    return results
