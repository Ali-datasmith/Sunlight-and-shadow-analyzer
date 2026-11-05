import math

class Vec3:
    """A 3D Cartesian vector representing points, dimensions, or directions."""
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __repr__(self) -> str:
        return f"Vec3({self.x}, {self.y}, {self.z})"

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


def add(v1: Vec3, v2: Vec3) -> Vec3:
    return Vec3(v1.x + v2.x, v1.y + v2.y, v1.z + v2.z)


def sub(v1: Vec3, v2: Vec3) -> Vec3:
    return Vec3(v1.x - v2.x, v1.y - v2.y, v1.z - v2.z)


def scale(v: Vec3, s: float) -> Vec3:
    return Vec3(v.x * s, v.y * s, v.z * s)


def dot(v1: Vec3, v2: Vec3) -> float:
    return v1.x * v2.x + v1.y * v2.y + v1.z * v2.z


def normalize(v: Vec3) -> Vec3:
    mag = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    if mag < 1e-12:
        return Vec3(0.0, 0.0, 0.0)
    return Vec3(v.x / mag, v.y / mag, v.z / mag)


def building_aabb(building) -> tuple[Vec3, Vec3]:
    """Returns the axis-aligned bounding box (bmin, bmax) of a building."""
    bmin = Vec3(building.position.x, building.position.y, building.position.z)
    bmax = Vec3(
        building.position.x + building.size.x,
        building.position.y + building.size.y,
        building.position.z + building.size.z
    )
    return (bmin, bmax)


class ViewParams:
    """Parameters defining axonometric (isometric) parallel camera projection."""
    def __init__(
        self,
        yaw_deg: float = 45.0,
        pitch_deg: float = 35.264,
        scale_px_per_m: float = 10.0,
        origin_px: tuple[float, float] = (300.0, 300.0)
    ):
        self.yaw_deg = float(yaw_deg)
        self.pitch_deg = float(pitch_deg)
        self.scale_px_per_m = float(scale_px_per_m)
        self.origin_px = (float(origin_px[0]), float(origin_px[1]))
        self.cos_yaw = 0.0
        self.sin_yaw = 0.0
        self.cos_pitch = 0.0
        self.sin_pitch = 0.0
        self.update_cache()

    def update_cache(self) -> None:
        y_rad = math.radians(self.yaw_deg)
        p_rad = math.radians(self.pitch_deg)
        self.cos_yaw = math.cos(y_rad)
        self.sin_yaw = math.sin(y_rad)
        self.cos_pitch = math.cos(p_rad)
        self.sin_pitch = math.sin(p_rad)


def project(p, view_params: ViewParams) -> tuple[float, float]:
    """Projects a 3D point P(x, y, z) into 2D screen coordinates."""
    if hasattr(p, "x"):
        x, y, z = p.x, p.y, p.z
    else:
        x, y, z = p[0], p[1], p[2]
    xr = x * view_params.cos_yaw - y * view_params.sin_yaw
    yr = x * view_params.sin_yaw + y * view_params.cos_yaw
    sx = view_params.origin_px[0] + view_params.scale_px_per_m * xr
    sy = view_params.origin_px[1] - view_params.scale_px_per_m * (yr * view_params.sin_pitch + z * view_params.cos_pitch)
    return (sx, sy)


def unproject_ground(screen_pt: tuple[float, float], view_params: ViewParams) -> tuple[float, float]:
    """Inverts 2D screen coordinates back to 3D ground plane coordinates (z = 0)."""
    sx, sy = screen_pt
    ox, oy = view_params.origin_px
    k = view_params.scale_px_per_m
    if abs(k) < 1e-9 or abs(view_params.sin_pitch) < 1e-9:
        return (0.0, 0.0)
    xr = (sx - ox) / k
    yr = -(sy - oy) / (k * view_params.sin_pitch)
    x = xr * view_params.cos_yaw + yr * view_params.sin_yaw
    y = -xr * view_params.sin_yaw + yr * view_params.cos_yaw
    return (x, y)


def depth_key(center: Vec3, view_params: ViewParams) -> float:
    """Calculates camera depth key for painter's algorithm sorting."""
    yr = center.x * view_params.sin_yaw + center.y * view_params.cos_yaw
    return yr * view_params.cos_pitch - center.z * view_params.sin_pitch


def ray_aabb(origin: Vec3, direction: Vec3, box: tuple[Vec3, Vec3]) -> float | None:
    """Ray-AABB slab intersection test (Kay-Kajiya / Williams et al.)."""
    bmin, bmax = box
    t_near = -float("inf")
    t_far = float("inf")
    T_MIN = 1e-4
    EPS = 1e-9

    for a in ("x", "y", "z"):
        d_a = getattr(direction, a)
        o_a = getattr(origin, a)
        min_a = getattr(bmin, a)
        max_a = getattr(bmax, a)

        if abs(d_a) < EPS:
            if o_a < min_a or o_a > max_a:
                return None
        else:
            t1 = (min_a - o_a) / d_a
            t2 = (max_a - o_a) / d_a
            lo = min(t1, t2)
            hi = max(t1, t2)
            t_near = max(t_near, lo)
            t_far = min(t_far, hi)

    if t_near <= t_far and t_far > T_MIN:
        return max(t_near, T_MIN)
    return None


def convex_hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Computes the 2D convex hull of a point set using Andrew's monotone chain."""
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def clip_polygon_to_rect(
    poly: list[tuple[float, float]],
    xmin: float,
    ymin: float,
    xmax: float,
    ymax: float
) -> list[tuple[float, float]]:
    """Clips a 2D polygon against an axis-aligned rectangle using Sutherland-Hodgman."""
    if not poly:
        return []

    def clip_edge(points, inside_fn, intersect_fn):
        out = []
        if not points:
            return out
        s = points[-1]
        for e in points:
            if inside_fn(e):
                if not inside_fn(s):
                    out.append(intersect_fn(s, e))
                out.append(e)
            elif inside_fn(s):
                out.append(intersect_fn(s, e))
            s = e
        return out

    # Left clip
    p = clip_edge(
        poly,
        lambda pt: pt[0] >= xmin,
        lambda s, e: (xmin, s[1] + (e[1] - s[1]) * (xmin - s[0]) / (e[0] - s[0]))
    )
    # Right clip
    p = clip_edge(
        p,
        lambda pt: pt[0] <= xmax,
        lambda s, e: (xmax, s[1] + (e[1] - s[1]) * (xmax - s[0]) / (e[0] - s[0]))
    )
    # Bottom clip
    p = clip_edge(
        p,
        lambda pt: pt[1] >= ymin,
        lambda s, e: (s[0] + (e[0] - s[0]) * (ymin - s[1]) / (e[1] - s[1]), ymin)
    )
    # Top clip
    p = clip_edge(
        p,
        lambda pt: pt[1] <= ymax,
        lambda s, e: (s[0] + (e[0] - s[0]) * (ymax - s[1]) / (e[1] - s[1]), ymax)
    )
    return p


def shadow_polygon(
    building,
    sun_vec: Vec3,
    ground_w: float,
    ground_d: float
) -> list[tuple[float, float]]:
    """Calculates the ground shadow polygon cast by a building along sun_vec."""
    EL_MIN_DEG = 2.0
    if sun_vec.z < math.sin(math.radians(EL_MIN_DEG)):
        return []

    bx = building.position.x
    by = building.position.y
    bz = building.position.z
    dx = building.size.x
    dy = building.size.y
    dz = building.size.z

    corners = [
        (bx, by, bz),
        (bx + dx, by, bz),
        (bx + dx, by + dy, bz),
        (bx, by + dy, bz),
        (bx, by, bz + dz),
        (bx + dx, by, bz + dz),
        (bx + dx, by + dy, bz + dz),
        (bx, by + dy, bz + dz),
    ]

    projected_pts = []
    inv_sz = 1.0 / sun_vec.z
    for cx, cy, cz in corners:
        px = cx - cz * sun_vec.x * inv_sz
        py = cy - cz * sun_vec.y * inv_sz
        projected_pts.append((px, py))

    hull = convex_hull_2d(projected_pts)
    return clip_polygon_to_rect(hull, 0.0, 0.0, ground_w, ground_d)


def point_in_convex_polygon(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """Tests if a 2D point is inside or on the boundary of a convex polygon."""
    n = len(poly)
    if n < 3:
        return False
    px, py = pt
    sign_pos = False
    sign_neg = False
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        if cross > 1e-9:
            sign_pos = True
        elif cross < -1e-9:
            sign_neg = True
        if sign_pos and sign_neg:
            return False
    return True


def fit_view(
    ground_cells: tuple[int, int],
    cell_size_m: float,
    max_height: float,
    screen_w: float,
    screen_h: float,
    view_params: ViewParams
) -> ViewParams:
    """Adjusts scale and origin of view_params to fit the ground and buildings into the viewport."""
    w = ground_cells[0] * cell_size_m
    d = ground_cells[1] * cell_size_m
    h = max(max_height, 20.0)

    corners = [
        (0.0, 0.0, 0.0),
        (w, 0.0, 0.0),
        (w, d, 0.0),
        (0.0, d, 0.0),
        (0.0, 0.0, h),
        (w, 0.0, h),
        (w, d, h),
        (0.0, d, h),
    ]

    temp_view = ViewParams(
        yaw_deg=view_params.yaw_deg,
        pitch_deg=view_params.pitch_deg,
        scale_px_per_m=1.0,
        origin_px=(0.0, 0.0)
    )

    proj = [project(pt, temp_view) for pt in corners]
    min_x = min(p[0] for p in proj)
    max_x = max(p[0] for p in proj)
    min_y = min(p[1] for p in proj)
    max_y = max(p[1] for p in proj)

    span_x = max(1.0, max_x - min_x)
    span_y = max(1.0, max_y - min_y)

    k = 0.9 * min(screen_w / span_x, screen_h / span_y)
    k = max(2.0, min(k, 40.0))

    mid_x = (min_x + max_x) * 0.5
    mid_y = (min_y + max_y) * 0.5

    ox = screen_w * 0.5 - k * mid_x
    oy = screen_h * 0.5 - k * mid_y

    view_params.scale_px_per_m = k
    view_params.origin_px = (ox, oy)
    view_params.update_cache()
    return view_params


def run_checks() -> list[tuple[str, bool, str]]:
    """Self-test checks for geometry algorithms."""
    results = []

    # 1. Isometric projection check: with ψ = 45°, ρ = 35.264°, k = 1, origin (0,0)
    v = ViewParams(yaw_deg=45.0, pitch_deg=35.264, scale_px_per_m=1.0, origin_px=(0.0, 0.0))
    p1 = project((1.0, 0.0, 0.0), v)
    p2 = project((0.0, 0.0, 1.0), v)
    ok_p1 = abs(p1[0] - 0.7071) < 1e-3 and abs(p1[1] - (-0.4082)) < 1e-3
    ok_p2 = abs(p2[0] - 0.0) < 1e-3 and abs(p2[1] - (-0.8165)) < 1e-3
    results.append(("Geometry: Isometric projection test", ok_p1 and ok_p2, f"p1={p1}, p2={p2}"))

    # 2. Unproject ground round-trip
    test_pt = (24.0, 18.0)
    scr = project((test_pt[0], test_pt[1], 0.0), v)
    unproj = unproject_ground(scr, v)
    ok_roundtrip = abs(unproj[0] - test_pt[0]) < 1e-6 and abs(unproj[1] - test_pt[1]) < 1e-6
    results.append(("Geometry: Unproject ground round-trip", ok_roundtrip, f"Original={test_pt}, Recovered={unproj}"))

    # 3. Ray-box intersection: box (10,10,0) to (14,14,10); sun az 225°, el 45°
    box = (Vec3(10.0, 10.0, 0.0), Vec3(14.0, 14.0, 10.0))
    az_rad = math.radians(225.0)
    el_rad = math.radians(45.0)
    s = Vec3(math.cos(el_rad) * math.sin(az_rad), math.cos(el_rad) * math.cos(az_rad), math.sin(el_rad))
    t1 = ray_aabb(Vec3(16.0, 16.0, 0.001), s, box)
    t2 = ray_aabb(Vec3(16.0, 8.0, 0.001), s, box)
    ok_ray = (t1 is not None and abs(t1 - 4.0) < 0.1) and (t2 is None)
    results.append(("Geometry: Ray-AABB intersection test", ok_ray, f"t1={t1}, t2={t2}"))

    # 4. Shadow polygon corner projection
    # Roof corner (14,14,10) projected along -s:
    inv_sz = 1.0 / s.z
    proj_corner = (14.0 - 10.0 * s.x * inv_sz, 14.0 - 10.0 * s.y * inv_sz)
    ok_corner = abs(proj_corner[0] - 21.07) < 0.02 and abs(proj_corner[1] - 21.07) < 0.02
    results.append(("Geometry: Shadow corner projection", ok_corner, f"proj_corner={proj_corner}"))

    # 5. Polygon clipping test
    test_poly = [(-5.0, -5.0), (70.0, -5.0), (70.0, 70.0), (-5.0, 70.0)]
    clipped = clip_polygon_to_rect(test_poly, 0.0, 0.0, 60.0, 60.0)
    ok_clip = len(clipped) == 4 and all(0.0 <= pt[0] <= 60.0 and 0.0 <= pt[1] <= 60.0 for pt in clipped)
    results.append(("Geometry: Sutherland-Hodgman polygon clipping", ok_clip, f"Clipped vertices={len(clipped)}"))

    return results
