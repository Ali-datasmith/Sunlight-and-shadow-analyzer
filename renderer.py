import math
try:
    import tkinter as tk
except ImportError:
    tk = None
from geometry import (
    Vec3,
    ViewParams,
    project,
    unproject_ground,
    depth_key,
    convex_hull_2d,
    point_in_convex_polygon,
    shadow_polygon,
)
from solar import SunState, sun_vector
from scenario import Scenario, Building
from heatmap import HeatmapGrid

GROUND_COLOR = "#E8EDE3"
GRIDLINE_COLOR = "#C9D1C3"
SHADOW_COLOR = "#7F8CA0"
DAY_BG = "#F5F6F7"
NIGHT_BG = "#D5D9E3"
TEXT_COLOR = "#1B1F23"
OCCUPIED_COLOR = "#B0B0B0"

BUILDING_COLORS = ["#D98E73", "#8FB8DE", "#E6C65C", "#9CC59A", "#B7A1D1", "#C9C9C9"]
HEAT_COLORS = ["#440154", "#443983", "#31688E", "#21908C", "#35B779", "#8FD744", "#FDE725"]
DIFF_COLORS = ["#B35806", "#E08214", "#FDB863", "#F7F7F7", "#92C5DE", "#4393C3", "#2166AC"]


def hours_to_color(h: float) -> str:
    """Maps direct sunlight hours into 7 sequential viridis bins."""
    if h < 0.0:
        return OCCUPIED_COLOR
    bin_idx = min(6, max(0, int(h // 2.0)))
    return HEAT_COLORS[bin_idx]


def diff_to_color(diff: float, tau: float = 0.25) -> str:
    """Maps hour difference into 7 diverging blue/orange classes."""
    if diff < -900.0:
        return OCCUPIED_COLOR
    if diff < -3.0:
        return DIFF_COLORS[0]
    elif diff < -1.5:
        return DIFF_COLORS[1]
    elif diff < -tau:
        return DIFF_COLORS[2]
    elif diff <= tau:
        return DIFF_COLORS[3]
    elif diff <= 1.5:
        return DIFF_COLORS[4]
    elif diff <= 3.0:
        return DIFF_COLORS[5]
    else:
        return DIFF_COLORS[6]


def relative_luminance(hex_str: str) -> float:
    """Computes WCAG relative luminance of an sRGB hex colour."""
    h = hex_str.lstrip("#")
    r, g, b = [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)]

    def to_linear(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * to_linear(r) + 0.7152 * to_linear(g) + 0.0722 * to_linear(b)


def contrast_ratio(c1_hex: str, c2_hex: str) -> float:
    """Computes WCAG 2.2 contrast ratio between two hex colours."""
    l1 = relative_luminance(c1_hex)
    l2 = relative_luminance(c2_hex)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def apply_brightness(color_hex: str, brightness: float) -> str:
    """Multiplies an RGB hex colour by brightness factor."""
    h = color_hex.lstrip("#")
    r, g, b = [int(h[i:i+2], 16) for i in (0, 2, 4)]
    b_clamped = max(0.0, min(1.0, brightness))
    nr = int(r * b_clamped)
    ng = int(g * b_clamped)
    nb = int(b * b_clamped)
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def draw_legend(
    canvas,
    mode: str,
    is_stale: bool,
    width: int = 280,
    height: int = 190
) -> None:
    """Renders the legend canvas with color swatches and uncertainty notes."""
    canvas.delete("all")
    canvas.configure(bg=DAY_BG)

    if mode == "diff":
        title = "Change in Sun Hours (B − A)"
        labels = [
            "< -3.0 h", "-3 to -1.5 h", "-1.5 to -0.25 h", "Unchanged (±0.25)",
            "+0.25 to +1.5 h", "+1.5 to +3.0 h", "> +3.0 h"
        ]
        colors = DIFF_COLORS
    else:
        title = "Direct Sunlight (Clear-Sky Upper Bound)"
        labels = [
            "0 – 2 h", "2 – 4 h", "4 – 6 h", "6 – 8 h",
            "8 – 10 h", "10 – 12 h", "12+ h"
        ]
        colors = HEAT_COLORS

    canvas.create_text(
        10, 14,
        anchor="w",
        text=title,
        font=("TkDefaultFont", 9, "bold"),
        fill=TEXT_COLOR
    )

    y_start = 34
    swatch_h = 16
    swatch_w = 26

    for idx, (col, lbl) in enumerate(zip(colors, labels)):
        y = y_start + idx * (swatch_h + 3)
        canvas.create_rectangle(
            12, y, 12 + swatch_w, y + swatch_h,
            fill=col, outline="#666666"
        )
        canvas.create_text(
            44, y + swatch_h / 2,
            anchor="w",
            text=lbl,
            font=("TkDefaultFont", 8),
            fill=TEXT_COLOR
        )

    # Occupied swatch on the right
    canvas.create_rectangle(
        160, y_start, 160 + swatch_w, y_start + swatch_h,
        fill=OCCUPIED_COLOR, outline="#666666"
    )
    canvas.create_text(
        192, y_start + swatch_h / 2,
        anchor="w",
        text="Building",
        font=("TkDefaultFont", 8),
        fill=TEXT_COLOR
    )

    # Discretization error note
    canvas.create_text(
        10, height - 18,
        anchor="w",
        text="Step error bound: ±Δt/2 per transition",
        font=("TkDefaultFont", 7, "italic"),
        fill="#555555"
    )

    if is_stale:
        canvas.create_text(
            width - 12, 14,
            anchor="e",
            text="STALE: re-run",
            font=("TkDefaultFont", 8, "bold"),
            fill="#D9381E"
        )


class SceneRenderer:
    """Manages layered axonometric rendering on a tkinter Canvas."""
    def __init__(self, canvas):
        self.canvas = canvas
        self.heat_cell_items: dict[tuple[int, int], int] = {}
        self.cached_sun: SunState | None = None

    def draw_static(
        self,
        scenario: Scenario,
        view_params: ViewParams,
        selected_id: int | None = None
    ) -> None:
        """Redraws static background layers: ground, gridlines, buildings."""
        self.canvas.delete("ground")
        self.canvas.delete("gridlines")
        self.canvas.delete("building")

        nx, ny = scenario.ground_size
        cs = scenario.cell_size_m
        gw = nx * cs
        gd = ny * cs

        # 1. Ground polygon
        ground_corners = [(0.0, 0.0, 0.0), (gw, 0.0, 0.0), (gw, gd, 0.0), (0.0, gd, 0.0)]
        ground_proj = [project(pt, view_params) for pt in ground_corners]
        poly_coords = [coord for pt in ground_proj for coord in pt]
        self.canvas.create_polygon(
            poly_coords,
            fill=GROUND_COLOR,
            outline=GRIDLINE_COLOR,
            width=2,
            tags=("ground",)
        )

        # 2. Grid lines
        for i in range(1, nx):
            p1 = project((i * cs, 0.0, 0.0), view_params)
            p2 = project((i * cs, gd, 0.0), view_params)
            self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill=GRIDLINE_COLOR, width=1, tags=("gridlines",))

        for j in range(1, ny):
            p1 = project((0.0, j * cs, 0.0), view_params)
            p2 = project((gw, j * cs, 0.0), view_params)
            self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill=GRIDLINE_COLOR, width=1, tags=("gridlines",))

        # 3. Buildings (sorted back-to-front via painter's algorithm depth key)
        sorted_buildings = sorted(
            scenario.buildings,
            key=lambda b: depth_key(
                Vec3(b.position.x + b.size.x * 0.5, b.position.y + b.size.y * 0.5, b.size.z * 0.5),
                view_params
            ),
            reverse=True
        )

        for b in sorted_buildings:
            self._draw_building(b, view_params, scenario, selected=(b.id == selected_id))

        self.canvas.tag_lower("ground")
        self.canvas.tag_lower("heat", "gridlines")
        self.canvas.tag_lower("gridlines", "shadow")
        self.canvas.tag_lower("shadow", "building")
        self.canvas.tag_raise("overlay")

    def _draw_building(
        self,
        b: Building,
        view_params: ViewParams,
        scenario: Scenario,
        selected: bool = False
    ) -> None:
        """Draws top and visible vertical faces of a box building with Lambertian shading."""
        bx, by = b.position.x, b.position.y
        dx, dy, dz = b.size.x, b.size.y, b.size.z

        c_yaw = view_params.cos_yaw
        s_yaw = view_params.sin_yaw
        cam_dir_x = -s_yaw
        cam_dir_y = -c_yaw

        s_vec = None
        shadows_active = False
        if self.cached_sun is not None:
            shadows_active = self.cached_sun.shadows_active
            s_vec = sun_vector(self.cached_sun.azimuth_deg, self.cached_sun.elevation_deg)

        faces = []

        # Top face (z = dz, normal = (0, 0, 1))
        top_pts = [(bx, by, dz), (bx + dx, by, dz), (bx + dx, by + dy, dz), (bx, by + dy, dz)]
        top_normal = Vec3(0.0, 0.0, 1.0)
        faces.append((top_pts, top_normal, 0))

        # South face (y = by, normal = (0, -1, 0))
        if (-1.0 * cam_dir_y) > 0.0:
            south_pts = [(bx, by, 0.0), (bx + dx, by, 0.0), (bx + dx, by, dz), (bx, by, dz)]
            faces.append((south_pts, Vec3(0.0, -1.0, 0.0), 1))

        # West face (x = bx, normal = (-1, 0, 0))
        if (-1.0 * cam_dir_x) > 0.0:
            west_pts = [(bx, by, 0.0), (bx, by + dy, 0.0), (bx, by + dy, dz), (bx, by, dz)]
            faces.append((west_pts, Vec3(-1.0, 0.0, 0.0), 2))

        # North face (y = by + dy, normal = (0, 1, 0))
        if (1.0 * cam_dir_y) > 0.0:
            north_pts = [(bx + dx, by + dy, 0.0), (bx, by + dy, 0.0), (bx, by + dy, dz), (bx + dx, by + dy, dz)]
            faces.append((north_pts, Vec3(0.0, 1.0, 0.0), 3))

        # East face (x = bx + dx, normal = (1, 0, 0))
        if (1.0 * cam_dir_x) > 0.0:
            east_pts = [(bx + dx, by, 0.0), (bx + dx, by + dy, 0.0), (bx + dx, by + dy, dz), (bx + dx, by, dz)]
            faces.append((east_pts, Vec3(1.0, 0.0, 0.0), 4))

        outline_color = "#D9381E" if selected else "#2B2D42"
        outline_w = 3 if selected else 1

        for pts, normal, _ in faces:
            proj_pts = [project(p, view_params) for p in pts]
            coords = [c for p in proj_pts for c in p]

            if shadows_active and s_vec is not None:
                n_dot_s = max(0.0, normal.x * s_vec.x + normal.y * s_vec.y + normal.z * s_vec.z)
                bright = 0.35 + 0.65 * n_dot_s
            else:
                bright = 0.35

            fill_col = apply_brightness(b.color, bright)
            self.canvas.create_polygon(
                coords,
                fill=fill_col,
                outline=outline_color,
                width=outline_w,
                tags=("building", f"b_{b.id}")
            )

        # Label text above top face
        top_center = (bx + dx * 0.5, by + dy * 0.5, dz)
        tc_scr = project(top_center, view_params)
        self.canvas.create_text(
            tc_scr[0], tc_scr[1] - 8,
            text=b.label,
            font=("TkDefaultFont", 8, "bold"),
            fill=TEXT_COLOR,
            tags=("building", f"b_{b.id}")
        )

    def draw_dynamic(
        self,
        scenario: Scenario,
        sun: SunState,
        view_params: ViewParams,
        heat_visible: bool = False,
        selected_id: int | None = None
    ) -> None:
        """Redraws dynamic layers: shadows, compass, night banner."""
        self.cached_sun = sun
        self.canvas.delete("shadow")
        self.canvas.delete("overlay")

        gw = scenario.ground_size[0] * scenario.cell_size_m
        gd = scenario.ground_size[1] * scenario.cell_size_m

        if sun.is_daytime:
            self.canvas.configure(bg=DAY_BG)
        else:
            self.canvas.configure(bg=NIGHT_BG)

        # Render shadows if sun is above cut-off
        if sun.shadows_active:
            s_vec = sun_vector(sun.azimuth_deg, sun.elevation_deg)
            for b in scenario.buildings:
                poly = shadow_polygon(b, s_vec, gw, gd)
                if poly and len(poly) >= 3:
                    proj = [project((p[0], p[1], 0.0), view_params) for p in poly]
                    coords = [c for p in proj for c in p]
                    if heat_visible:
                        self.canvas.create_polygon(
                            coords,
                            fill="",
                            outline=SHADOW_COLOR,
                            width=2,
                            dash=(4, 4),
                            tags=("shadow",)
                        )
                    else:
                        self.canvas.create_polygon(
                            coords,
                            fill=SHADOW_COLOR,
                            outline="#5A6578",
                            width=1,
                            tags=("shadow",)
                        )

        # Redraw buildings to refresh flat Lambertian face shading
        self.draw_static(scenario, view_params, selected_id)

        # Night or low elevation banner
        if not sun.is_daytime:
            self.canvas.create_rectangle(
                10, 10, 220, 36,
                fill="#2A2D34", outline="#4A4E5A",
                tags=("overlay",)
            )
            self.canvas.create_text(
                115, 23,
                text="Night: Sun below horizon",
                fill="#FFFFFF",
                font=("TkDefaultFont", 9, "bold"),
                tags=("overlay",)
            )
        elif not sun.shadows_active:
            self.canvas.create_rectangle(
                10, 10, 240, 36,
                fill="#FFF3CD", outline="#FFEEBA",
                tags=("overlay",)
            )
            self.canvas.create_text(
                125, 23,
                text="Elevation < 2° (Cut-off: no shadows)",
                fill="#856404",
                font=("TkDefaultFont", 8, "bold"),
                tags=("overlay",)
            )

        self.draw_compass(scenario, sun, view_params)

        self.canvas.tag_lower("ground")
        self.canvas.tag_lower("heat", "gridlines")
        self.canvas.tag_lower("gridlines", "shadow")
        self.canvas.tag_lower("shadow", "building")
        self.canvas.tag_raise("overlay")

    def draw_heat(
        self,
        heatmap_grid: HeatmapGrid | None,
        diff_grid: list[list[float]] | None = None,
        diff_mode: bool = False,
        is_stale: bool = False,
        view_params: ViewParams | None = None,
        scenario: Scenario | None = None
    ) -> None:
        """Draws or recolours heatmap cell tiles on the canvas."""
        self.canvas.delete("heat")
        self.heat_cell_items.clear()

        if heatmap_grid is None or view_params is None or scenario is None:
            return

        nx, ny = heatmap_grid.resolution
        cs = scenario.cell_size_m

        for j in range(ny):
            for i in range(nx):
                p0 = project((i * cs, j * cs, 0.0), view_params)
                p1 = project(((i + 1) * cs, j * cs, 0.0), view_params)
                p2 = project(((i + 1) * cs, (j + 1) * cs, 0.0), view_params)
                p3 = project((i * cs, (j + 1) * cs, 0.0), view_params)
                coords = [p0[0], p0[1], p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]]

                if diff_mode and diff_grid is not None:
                    col = diff_to_color(diff_grid[j][i])
                else:
                    h = heatmap_grid.hours_array[j][i]
                    col = hours_to_color(h)

                if is_stale and col != OCCUPIED_COLOR:
                    col = apply_brightness(col, 0.7)

                item = self.canvas.create_polygon(
                    coords,
                    fill=col,
                    outline="",
                    tags=("heat",)
                )
                self.heat_cell_items[(i, j)] = item

        self.canvas.tag_lower("ground")
        self.canvas.tag_lower("heat", "gridlines")
        self.canvas.tag_lower("gridlines", "shadow")

    def draw_compass(
        self,
        scenario: Scenario,
        sun: SunState,
        view_params: ViewParams
    ) -> None:
        """Draws a 90 px compass rose with true north arrow and sun azimuth indicator."""
        w = self.canvas.winfo_width()
        if w < 100:
            w = 600
        cx = w - 55
        cy = 55
        radius = 36

        # Dial ring
        self.canvas.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            fill="#FFFFFF", outline="#A0AAB2", width=2,
            tags=("overlay",)
        )

        # North direction vector on screen
        y_rad = math.radians(view_params.yaw_deg)
        p_rad = math.radians(view_params.pitch_deg)
        nx_scr = -math.sin(y_rad)
        ny_scr = -math.cos(y_rad) * math.sin(p_rad)
        mag_n = math.sqrt(nx_scr * nx_scr + ny_scr * ny_scr)
        if mag_n > 1e-9:
            nx_scr /= mag_n
            ny_scr /= mag_n

        # East vector (90 deg clockwise from North)
        ex_scr = math.cos(y_rad)
        ey_scr = -math.sin(y_rad) * math.sin(p_rad)
        mag_e = math.sqrt(ex_scr * ex_scr + ey_scr * ey_scr)
        if mag_e > 1e-9:
            ex_scr /= mag_e
            ey_scr /= mag_e

        # North pointer arrow
        arrow_len = radius - 7
        ax = cx + nx_scr * arrow_len
        ay = cy + ny_scr * arrow_len
        self.canvas.create_line(
            cx, cy, ax, ay,
            arrow="last", fill="#D9381E", width=2,
            tags=("overlay",)
        )

        # Cardinal letters N, S, E, W
        lbl_r = radius - 10
        self.canvas.create_text(
            cx + nx_scr * lbl_r, cy + ny_scr * lbl_r,
            text="N", fill="#D9381E", font=("TkDefaultFont", 8, "bold"),
            tags=("overlay",)
        )
        self.canvas.create_text(
            cx - nx_scr * lbl_r, cy - ny_scr * lbl_r,
            text="S", fill="#495057", font=("TkDefaultFont", 7),
            tags=("overlay",)
        )
        self.canvas.create_text(
            cx + ex_scr * lbl_r, cy + ey_scr * lbl_r,
            text="E", fill="#495057", font=("TkDefaultFont", 7),
            tags=("overlay",)
        )
        self.canvas.create_text(
            cx - ex_scr * lbl_r, cy - ey_scr * lbl_r,
            text="W", fill="#495057", font=("TkDefaultFont", 7),
            tags=("overlay",)
        )

        # Sun azimuth marker on ring
        # Azimuth is clockwise from North
        az_rad = math.radians(sun.azimuth_deg)
        sun_dir_x = math.sin(az_rad) * ex_scr + math.cos(az_rad) * nx_scr
        sun_dir_y = math.sin(az_rad) * ey_scr + math.cos(az_rad) * ny_scr
        smag = math.sqrt(sun_dir_x * sun_dir_x + sun_dir_y * sun_dir_y)
        if smag > 1e-9:
            sun_dir_x /= smag
            sun_dir_y /= smag

        sx = cx + sun_dir_x * radius
        sy = cy + sun_dir_y * radius
        dot_r = 5
        if sun.is_daytime:
            self.canvas.create_oval(
                sx - dot_r, sy - dot_r, sx + dot_r, sy + dot_r,
                fill="#FDB813", outline="#B38600", width=1.5,
                tags=("overlay",)
            )
        else:
            self.canvas.create_oval(
                sx - dot_r, sy - dot_r, sx + dot_r, sy + dot_r,
                fill="", outline="#888888", width=1.5,
                tags=("overlay",)
            )

    def hit_test_building(
        self,
        screen_x: float,
        screen_y: float,
        scenario: Scenario,
        view_params: ViewParams
    ) -> int | None:
        """Tests if screen cursor hits any building (tested front-to-back)."""
        sorted_buildings = sorted(
            scenario.buildings,
            key=lambda b: depth_key(
                Vec3(b.position.x + b.size.x * 0.5, b.position.y + b.size.y * 0.5, b.size.z * 0.5),
                view_params
            ),
            reverse=False
        )

        for b in sorted_buildings:
            bx, by = b.position.x, b.position.y
            dx, dy, dz = b.size.x, b.size.y, b.size.z
            corners = [
                (bx, by, 0.0), (bx + dx, by, 0.0), (bx + dx, by + dy, 0.0), (bx, by + dy, 0.0),
                (bx, by, dz), (bx + dx, by, dz), (bx + dx, by + dy, dz), (bx, by + dy, dz)
            ]
            scr_corners = [project(c, view_params) for c in corners]
            hull = convex_hull_2d(scr_corners)
            if point_in_convex_polygon((screen_x, screen_y), hull):
                return b.id
        return None

    def cell_at(
        self,
        screen_x: float,
        screen_y: float,
        scenario: Scenario,
        view_params: ViewParams
    ) -> tuple[int, int] | None:
        """Returns the grid cell indices (i, j) under cursor."""
        gx, gy = unproject_ground((screen_x, screen_y), view_params)
        cs = scenario.cell_size_m
        nx, ny = scenario.ground_size
        if 0.0 <= gx < nx * cs and 0.0 <= gy < ny * cs:
            return (int(gx // cs), int(gy // cs))
        return None


def run_checks() -> list[tuple[str, bool, str]]:
    """Self-test verification for renderer math, color mapping, and accessibility."""
    results = []

    # 1. hours_to_color boundary tests
    c0 = hours_to_color(1.999)
    c1 = hours_to_color(2.0)
    c6 = hours_to_color(12.0)
    c_occ = hours_to_color(-1.0)
    ok_bins = (
        c0 == HEAT_COLORS[0]
        and c1 == HEAT_COLORS[1]
        and c6 == HEAT_COLORS[6]
        and c_occ == OCCUPIED_COLOR
    )
    results.append(("Renderer: hours_to_color bin boundaries", ok_bins, f"1.999->{c0}, 2.0->{c1}, 12.0->{c6}"))

    # 2. WCAG contrast ratios >= 4.5:1
    cr_day = contrast_ratio(TEXT_COLOR, DAY_BG)
    cr_night = contrast_ratio(TEXT_COLOR, NIGHT_BG)
    cr_ground = contrast_ratio(TEXT_COLOR, GROUND_COLOR)
    ok_contrast = (cr_day >= 4.5) and (cr_night >= 4.5) and (cr_ground >= 4.5)
    results.append((
        "Renderer: WCAG 2.2 contrast ratio >= 4.5:1",
        ok_contrast,
        f"Day={cr_day:.2f}:1, Night={cr_night:.2f}:1, Ground={cr_ground:.2f}:1"
    ))

    return results
