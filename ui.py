import math
import datetime
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from geometry import Vec3, ViewParams, fit_view
import geometry
from solar import solar_position, sunrise_sunset, SunState
import solar
from scenario import (
    Building,
    Scenario,
    create_demo_scenario,
    CITY_PRESETS,
    MAX_BUILDINGS,
    CELL_SIZE_M,
    GROUND_CELLS,
)
import scenario as scenario_mod
from heatmap import HeatmapGrid, HeatmapJob, compare
import heatmap as heatmap_mod
from renderer import (
    SceneRenderer,
    draw_legend,
    BUILDING_COLORS,
    DAY_BG,
    TEXT_COLOR,
)
import renderer as renderer_mod


class AppState:
    """Central mutable application state."""
    def __init__(self):
        self.date: tuple[int, int, int] = (2024, 3, 21)
        self.minutes: int = 600  # 10:00 AM
        self.scenarios: dict[str, Scenario | None] = {
            "A": create_demo_scenario(),
            "B": None,
        }
        self.active: str = "A"
        self.compare_on: bool = False
        self.views: dict[str, ViewParams] = {
            "A": ViewParams(yaw_deg=45.0, pitch_deg=35.264),
            "B": ViewParams(yaw_deg=45.0, pitch_deg=35.264),
        }
        self.selected_id: int | None = None
        self.heat: dict[str, HeatmapGrid | None] = {"A": None, "B": None}
        self.show_heat: bool = False
        self.diff_mode: bool = False
        self.step_min: int = 15
        self.target_hours: float = 2.0
        self.sun: SunState = solar_position(31.5204, 74.3587, (2024, 3, 21), 600.0, 5.0)
        self.sunrise_min: int | None = None
        self.sunset_min: int | None = None
        self.drag: dict | None = None


class AssumptionsDialog(tk.Toplevel):
    """Modal dialog disclosing all modeling assumptions, limits, and uncertainties."""
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Assumptions & Limitations")
        self.geometry("640x520")
        self.minsize(500, 400)
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=14, pady=14)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text="Scientific Assumptions & Engineering Disclosures",
            font=("TkDefaultFont", 11, "bold")
        )
        lbl.pack(anchor="w", pady=(0, 8))

        text_box = tk.Text(frame, wrap=tk.WORD, font=("TkDefaultFont", 9), padx=8, pady=8)
        scroll = ttk.Scrollbar(frame, command=text_box.yview)
        text_box.configure(yscrollcommand=scroll.set)

        assumptions_content = (
            "1. CLEAR-SKY DIRECT SUNLIGHT MODEL\n"
            "   Only direct extraterrestrial solar beam radiation is simulated. Cloud cover, "
            "haze, atmospheric attenuation, diffuse sky irradiance, and ground albedo "
            "are not included. Accumulated hours represent a theoretical upper bound.\n\n"
            "2. POINT-SOURCE ASTRONOMICAL SUN\n"
            "   The sun is treated as an infinitesimal point source. Shadows are cast with "
            "ideal geometric hard edges. The 0.53° angular solar disc diameter is not modeled, "
            "so no penumbra / soft shadow transitions are rendered.\n\n"
            "3. AXIS-ALIGNED RECTANGULAR BOX GEOMETRY\n"
            "   All buildings are strictly axis-aligned rectangular boxes (X=East, Y=North, Z=Up). "
            "Rotated structures, sloped roofs, pitched overhangs, courtyards cut into boxes, "
            "and non-box CAD models are out of scope.\n\n"
            "4. FLAT GROUND PLANE & ZERO TOPOGRAPHY\n"
            "   Ground is assumed to be an ideal planar surface at z = 0 m. Terrain slopes, "
            "hills, vegetation, trees, and subterranean levels are excluded.\n\n"
            "5. SOLAR POSITION & ATMOSPHERIC REFRACTION\n"
            "   Solar azimuth and apparent elevation are derived from NOAA General Solar "
            "Position Calculations (Meeus 1998 algorithm). Refraction follows standard "
            "atmospheric conditions without dynamic local barometric pressure or temperature tuning.\n\n"
            "6. 2.0° ELEVATION CUT-OFF THRESHOLD\n"
            "   To prevent unbounded shadow lengths and singularity near the horizon, "
            "shadow projection and sunlight accumulation are strictly active only when "
            "apparent solar elevation >= 2.0°.\n\n"
            "7. USER-PROVIDED STANDARD TIMEZONE\n"
            "   Timezone offset is specified directly as hours east of UTC without automatic "
            "Daylight Saving Time (DST) rules or online geocoding lookups.\n\n"
            "8. MIDPOINT NUMERICAL INTEGRATION ERROR\n"
            "   Heatmap accumulation uses midpoint-rule time discretization. The maximum "
            "theoretical time-step error is bounded by ±Δt/2 per shadow boundary transition "
            "(e.g. ±7.5 minutes at a 15-minute time step).\n\n"
            "9. VISUAL FACE SHADING LIMITATION\n"
            "   Building vertical faces use Lambertian cosine flat shading for 3D orientation cues. "
            "Facade-on-facade shadow occlusion is not computed; only horizontal ground and "
            "rooftop sunlight hours are integrated in the heatmap."
        )

        text_box.insert(tk.END, assumptions_content)
        text_box.configure(state=tk.DISABLED)

        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn = ttk.Button(self, text="Close", command=self.destroy)
        btn.pack(pady=10)


class App:
    """Main application controller and graphical interface."""
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Sunlight & Shadow Analyzer")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 680)

        self.state = AppState()
        self.renderers: dict[str, SceneRenderer] = {}
        self.active_heatmap_job: HeatmapJob | None = None
        self._slider_after_id: str | None = None
        self._status_after_id: str | None = None

        self._build_menu()
        self._build_layout()
        self._recompute_sun_and_strip()
        self._full_redraw()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New (Demo)", command=self.on_new)
        file_menu.add_command(label="Open...", command=self.on_open)
        file_menu.add_command(label="Save...", command=self.on_save)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Assumptions & Limits", command=self.on_show_assumptions)
        help_menu.add_command(label="Run Self-Tests", command=self.on_run_selftest)
        help_menu.add_command(label="Benchmark", command=self.on_run_benchmark)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.on_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=0, minsize=310)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=0)

        # Left panel (scrollable container)
        left_container = tk.Frame(self.root, width=310, bg="#F0F2F5", padx=6, pady=6)
        left_container.grid(row=0, column=0, sticky="nsew")
        left_container.grid_propagate(False)

        left_canvas = tk.Canvas(left_container, bg="#F0F2F5", highlightthickness=0)
        left_scroll = ttk.Scrollbar(left_container, orient="vertical", command=left_canvas.yview)
        self.left_panel = tk.Frame(left_canvas, bg="#F0F2F5")
        self.left_panel.bind(
            "<Configure>",
            lambda e: left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        )
        left_canvas.create_window((0, 0), window=self.left_panel, anchor="nw")
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_scroll.pack(side="right", fill="y")

        # Center frame
        center_frame = tk.Frame(self.root, bg="#FFFFFF")
        center_frame.grid(row=0, column=1, sticky="nsew")
        center_frame.rowconfigure(0, weight=1)
        center_frame.rowconfigure(1, weight=0)
        center_frame.columnconfigure(0, weight=1)

        # Canvas frame
        self.canvas_frame = tk.Frame(center_frame, bg="#FFFFFF")
        self.canvas_frame.grid(row=0, column=0, sticky="nsew")
        self.canvas_frame.rowconfigure(1, weight=1)
        self.canvas_frame.columnconfigure(0, weight=1)
        self.canvas_frame.columnconfigure(1, weight=1)

        # Pane titles (U3)
        self.title_A = tk.Label(
            self.canvas_frame,
            text="Scenario A (Before)",
            font=("TkDefaultFont", 10, "bold"),
            bg="#FFFFFF",
            fg=TEXT_COLOR
        )
        self.title_A.grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))

        self.title_B = tk.Label(
            self.canvas_frame,
            text="Scenario B (After)",
            font=("TkDefaultFont", 10, "normal"),
            bg="#FFFFFF",
            fg=TEXT_COLOR
        )
        self.title_B.grid(row=0, column=1, sticky="w", padx=10, pady=(6, 2))
        self.title_B.grid_remove()

        # Canvas A (U1)
        self.canvas_A = tk.Canvas(
            self.canvas_frame,
            bg=DAY_BG,
            highlightthickness=2,
            highlightbackground="#0066CC"
        )
        self.canvas_A.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.renderers["A"] = SceneRenderer(self.canvas_A)

        # Canvas B (U2)
        self.canvas_B = tk.Canvas(
            self.canvas_frame,
            bg=DAY_BG,
            highlightthickness=2,
            highlightbackground="#CCCCCC"
        )
        self.canvas_B.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        self.canvas_B.grid_remove()
        self.renderers["B"] = SceneRenderer(self.canvas_B)

        self._bind_canvas_events(self.canvas_A, "A")
        self._bind_canvas_events(self.canvas_B, "B")

        # Time panel (U5 - U8)
        time_panel = tk.Frame(center_frame, bg="#FFFFFF", padx=12, pady=6)
        time_panel.grid(row=1, column=0, sticky="ew")
        time_panel.columnconfigure(1, weight=1)

        self.time_label = tk.Label(
            time_panel,
            text="10:00 (UTC+5.0)",
            font=("TkDefaultFont", 13, "bold"),
            bg="#FFFFFF",
            fg=TEXT_COLOR,
            width=16,
            anchor="w"
        )
        self.time_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        # Daylight summary text
        self.daylight_info_label = tk.Label(
            time_panel,
            text="Sunrise --:-- / Sunset --:--",
            font=("TkDefaultFont", 9),
            bg="#FFFFFF",
            fg="#555555"
        )
        self.daylight_info_label.grid(row=0, column=1, sticky="e")

        # U6 Scale
        self.time_scale = tk.Scale(
            time_panel,
            from_=0,
            to=1439,
            orient=tk.HORIZONTAL,
            showvalue=0,
            command=self.on_time_change,
            bg="#E9ECEF",
            troughcolor="#CED4DA",
            highlightthickness=0
        )
        self.time_scale.set(self.state.minutes)
        self.time_scale.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 2))
        self.time_scale.bind("<ButtonRelease-1>", lambda e: self._on_slider_release())

        # U7 Daylight bar
        self.daylight_strip = tk.Canvas(time_panel, height=10, bg="#D5D9E3", highlightthickness=0)
        self.daylight_strip.grid(row=2, column=0, columnspan=2, sticky="ew")

        # U8 Hour tick labels
        tick_frame = tk.Frame(time_panel, bg="#FFFFFF")
        tick_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        for i, tick_str in enumerate(["00:00", "06:00", "12:00", "18:00", "24:00"]):
            lbl = tk.Label(tick_frame, text=tick_str, font=("TkDefaultFont", 7), bg="#FFFFFF", fg="#6C757D")
            if i == 0:
                lbl.pack(side="left")
            elif i == 4:
                lbl.pack(side="right")
            else:
                lbl.pack(side="left", expand=True)

        # Left panel sections
        self._build_location_section()
        self._build_add_building_section()
        self._build_selected_building_section()
        self._build_heatmap_section()
        self._build_scenario_section()

        # U17 Assumptions button
        btn_assump = ttk.Button(
            self.left_panel,
            text="Assumptions & Limits",
            command=self.on_show_assumptions
        )
        btn_assump.pack(fill="x", padx=4, pady=(8, 12))

        # Status bar (U19)
        self.status_frame = tk.Frame(self.root, bg="#E9ECEF", padx=8, pady=3)
        self.status_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_frame.columnconfigure(0, weight=1)

        self.status_msg = tk.Label(
            self.status_frame,
            text="Ready. Drag buildings or scrub time slider.",
            font=("TkDefaultFont", 8),
            bg="#E9ECEF",
            fg=TEXT_COLOR,
            anchor="w"
        )
        self.status_msg.grid(row=0, column=0, sticky="w")

        self.sun_readout = tk.Label(
            self.status_frame,
            text="Az 0.0° | El 0.0°",
            font=("TkDefaultFont", 8, "bold"),
            bg="#E9ECEF",
            fg=TEXT_COLOR
        )
        self.sun_readout.grid(row=0, column=1, sticky="e", padx=10)

        self.hover_readout = tk.Label(
            self.status_frame,
            text="x=0.0m y=0.0m",
            font=("TkDefaultFont", 8),
            bg="#E9ECEF",
            fg="#495057",
            width=28,
            anchor="e"
        )
        self.hover_readout.grid(row=0, column=2, sticky="e")

    def _bind_canvas_events(self, canvas: tk.Canvas, pane_id: str) -> None:
        canvas.bind("<Configure>", lambda e, p=pane_id: self.on_canvas_resize(p, e))
        canvas.bind("<ButtonPress-1>", lambda e, p=pane_id: self.on_canvas_press(p, e))
        canvas.bind("<B1-Motion>", lambda e, p=pane_id: self.on_canvas_drag(p, e))
        canvas.bind("<ButtonRelease-1>", lambda e, p=pane_id: self.on_canvas_release(p, e))
        canvas.bind("<Motion>", lambda e, p=pane_id: self.on_canvas_hover(p, e))
        canvas.bind("<Key-Left>", lambda e: self.on_canvas_key(-1, 0))
        canvas.bind("<Key-Right>", lambda e: self.on_canvas_key(1, 0))
        canvas.bind("<Key-Up>", lambda e: self.on_canvas_key(0, 1))
        canvas.bind("<Key-Down>", lambda e: self.on_canvas_key(0, -1))
        canvas.bind("<Delete>", lambda e: self.on_delete_selected())

    # --- Left Panel Widgets ---

    def _build_location_section(self) -> None:
        lf = ttk.LabelFrame(self.left_panel, text="Location & Date", padding=6)
        lf.pack(fill="x", padx=4, pady=4)

        # Preset combobox (U9)
        r0 = tk.Frame(lf)
        r0.pack(fill="x", pady=2)
        tk.Label(r0, text="Preset:", font=("TkDefaultFont", 8)).pack(side="left")
        self.preset_combo = ttk.Combobox(
            r0,
            values=list(CITY_PRESETS.keys()),
            state="readonly",
            width=14
        )
        self.preset_combo.set("Lahore")
        self.preset_combo.pack(side="right")
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)

        # Lat / Lon / Tz entries (U10)
        r1 = tk.Frame(lf)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="Lat (°N):", font=("TkDefaultFont", 8)).pack(side="left")
        self.lat_entry = ttk.Entry(r1, width=10)
        self.lat_entry.insert(0, "31.5204")
        self.lat_entry.pack(side="right")
        self.lat_entry.bind("<Return>", lambda e: self.on_location_commit())
        self.lat_entry.bind("<FocusOut>", lambda e: self.on_location_commit())

        r2 = tk.Frame(lf)
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="Lon (°E):", font=("TkDefaultFont", 8)).pack(side="left")
        self.lon_entry = ttk.Entry(r2, width=10)
        self.lon_entry.insert(0, "74.3587")
        self.lon_entry.pack(side="right")
        self.lon_entry.bind("<Return>", lambda e: self.on_location_commit())
        self.lon_entry.bind("<FocusOut>", lambda e: self.on_location_commit())

        r3 = tk.Frame(lf)
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="UTC Offset (h):", font=("TkDefaultFont", 8)).pack(side="left")
        self.tz_entry = ttk.Entry(r3, width=10)
        self.tz_entry.insert(0, "5.0")
        self.tz_entry.pack(side="right")
        self.tz_entry.bind("<Return>", lambda e: self.on_location_commit())
        self.tz_entry.bind("<FocusOut>", lambda e: self.on_location_commit())

        # Date picker (U11)
        r4 = tk.Frame(lf)
        r4.pack(fill="x", pady=2)
        tk.Label(r4, text="Date:", font=("TkDefaultFont", 8)).pack(side="left")

        months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ]
        self.month_combo = ttk.Combobox(r4, values=months, state="readonly", width=5)
        self.month_combo.set("Mar")
        self.month_combo.pack(side="left", padx=2)
        self.month_combo.bind("<<ComboboxSelected>>", lambda e: self.on_date_change())

        self.day_spin = ttk.Spinbox(
            r4, from_=1, to=31, width=3,
            command=self.on_date_change
        )
        self.day_spin.set(21)
        self.day_spin.pack(side="left", padx=2)
        self.day_spin.bind("<Return>", lambda e: self.on_date_change())

        self.year_spin = ttk.Spinbox(
            r4, from_=1900, to=2100, width=5,
            command=self.on_date_change
        )
        self.year_spin.set(2024)
        self.year_spin.pack(side="left", padx=2)
        self.year_spin.bind("<Return>", lambda e: self.on_date_change())

    def _build_add_building_section(self) -> None:
        lf = ttk.LabelFrame(self.left_panel, text="Add Building (Max 15)", padding=6)
        lf.pack(fill="x", padx=4, pady=4)

        # Label entry
        r0 = tk.Frame(lf)
        r0.pack(fill="x", pady=2)
        tk.Label(r0, text="Label:", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_label_entry = ttk.Entry(r0, width=12)
        self.b_label_entry.insert(0, "Block")
        self.b_label_entry.pack(side="right")

        # X, Y coords
        r1 = tk.Frame(lf)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="X (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_x_spin = ttk.Spinbox(r1, from_=0, to=58, increment=2, width=5)
        self.b_x_spin.set(20)
        self.b_x_spin.pack(side="left", padx=(2, 6))

        tk.Label(r1, text="Y (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_y_spin = ttk.Spinbox(r1, from_=0, to=58, increment=2, width=5)
        self.b_y_spin.set(20)
        self.b_y_spin.pack(side="right")

        # Width (dx), Depth (dy)
        r2 = tk.Frame(lf)
        r2.pack(fill="x", pady=2)
        tk.Label(r2, text="W (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_w_spin = ttk.Spinbox(r2, from_=2, to=20, increment=2, width=5)
        self.b_w_spin.set(8)
        self.b_w_spin.pack(side="left", padx=(2, 6))

        tk.Label(r2, text="D (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_d_spin = ttk.Spinbox(r2, from_=2, to=20, increment=2, width=5)
        self.b_d_spin.set(8)
        self.b_d_spin.pack(side="right")

        # Height (dz), Color
        r3 = tk.Frame(lf)
        r3.pack(fill="x", pady=2)
        tk.Label(r3, text="H (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_h_spin = ttk.Spinbox(r3, from_=3, to=45, increment=1, width=5)
        self.b_h_spin.set(12)
        self.b_h_spin.pack(side="left", padx=(2, 6))

        tk.Label(r3, text="Color:", font=("TkDefaultFont", 8)).pack(side="left")
        self.b_color_combo = ttk.Combobox(
            r3,
            values=BUILDING_COLORS,
            state="readonly",
            width=7
        )
        self.b_color_combo.set(BUILDING_COLORS[0])
        self.b_color_combo.pack(side="right")

        btn_add = ttk.Button(lf, text="Add Building", command=self.on_add_building)
        btn_add.pack(fill="x", pady=(4, 2))

    def _build_selected_building_section(self) -> None:
        self.sel_lf = ttk.LabelFrame(self.left_panel, text="Selected Building", padding=6)
        self.sel_lf.pack(fill="x", padx=4, pady=4)

        self.sel_name_label = tk.Label(
            self.sel_lf,
            text="No building selected",
            font=("TkDefaultFont", 8, "italic"),
            fg="#6C757D"
        )
        self.sel_name_label.pack(anchor="w", pady=2)

        r1 = tk.Frame(self.sel_lf)
        r1.pack(fill="x", pady=2)
        tk.Label(r1, text="Height (m):", font=("TkDefaultFont", 8)).pack(side="left")
        self.sel_height_spin = ttk.Spinbox(
            r1, from_=3, to=45, increment=1, width=6,
            command=self.on_height_commit
        )
        self.sel_height_spin.set(12)
        self.sel_height_spin.pack(side="right")
        self.sel_height_spin.bind("<Return>", lambda e: self.on_height_commit())

        self.btn_delete = ttk.Button(
            self.sel_lf,
            text="Delete Building",
            command=self.on_delete_selected
        )
        self.btn_delete.pack(fill="x", pady=(4, 2))
        self._update_selected_ui()

    def _build_heatmap_section(self) -> None:
        lf = ttk.LabelFrame(self.left_panel, text="Heatmap Analysis", padding=6)
        lf.pack(fill="x", padx=4, pady=4)

        r0 = tk.Frame(lf)
        r0.pack(fill="x", pady=2)
        tk.Label(r0, text="Time Step:", font=("TkDefaultFont", 8)).pack(side="left")
        self.step_combo = ttk.Combobox(
            r0, values=["5", "10", "15", "30"], state="readonly", width=5
        )
        self.step_combo.set("15")
        self.step_combo.pack(side="right")

        self.btn_run_heatmap = ttk.Button(
            lf, text="Run Heatmap", command=self.on_run_heatmap
        )
        self.btn_run_heatmap.pack(fill="x", pady=3)

        self.heatmap_progress = ttk.Progressbar(lf, orient="horizontal", mode="determinate")
        self.heatmap_progress.pack(fill="x", pady=2)

        r1 = tk.Frame(lf)
        r1.pack(fill="x", pady=2)
        self.heat_var = tk.BooleanVar(value=False)
        self.chk_heat = ttk.Checkbutton(
            r1,
            text="Show Heatmap",
            variable=self.heat_var,
            command=self.on_toggle_heat
        )
        self.chk_heat.pack(side="left")

        tk.Label(r1, text="Target (h):", font=("TkDefaultFont", 8)).pack(side="left", padx=(6, 2))
        self.target_spin = ttk.Spinbox(
            r1, from_=0.5, to=12.0, increment=0.5, width=4,
            command=self.on_target_change
        )
        self.target_spin.set(2.0)
        self.target_spin.pack(side="right")
        self.target_spin.bind("<Return>", lambda e: self.on_target_change())

        # Legend canvas (U15)
        self.legend_canvas = tk.Canvas(
            lf, width=280, height=190, bg=DAY_BG, highlightthickness=1, highlightbackground="#D0D7DE"
        )
        self.legend_canvas.pack(fill="x", pady=(4, 2))
        self._update_legend()

    def _build_scenario_section(self) -> None:
        lf = ttk.LabelFrame(self.left_panel, text="A/B Scenario Comparison", padding=6)
        lf.pack(fill="x", padx=4, pady=4)

        self.compare_var = tk.BooleanVar(value=False)
        self.chk_compare = ttk.Checkbutton(
            lf,
            text="Compare Scenarios (A/B)",
            variable=self.compare_var,
            command=self.on_toggle_compare
        )
        self.chk_compare.pack(anchor="w", pady=2)

        r_mode = tk.Frame(lf)
        r_mode.pack(fill="x", pady=2)
        self.view_mode_var = tk.StringVar(value="abs")
        self.rad_abs = ttk.Radiobutton(
            r_mode, text="Absolute", value="abs",
            variable=self.view_mode_var,
            command=self.on_view_mode_change
        )
        self.rad_abs.pack(side="left", padx=2)
        self.rad_diff = ttk.Radiobutton(
            r_mode, text="Diff (B − A)", value="diff",
            variable=self.view_mode_var,
            command=self.on_view_mode_change
        )
        self.rad_diff.pack(side="left", padx=2)

        self.btn_copy_a_to_b = ttk.Button(
            lf, text="Copy A → B", command=self.on_copy_a_to_b, state=tk.DISABLED
        )
        self.btn_copy_a_to_b.pack(fill="x", pady=3)

        self.summary_label = tk.Label(
            lf,
            text="Comparison inactive.",
            font=("TkDefaultFont", 8),
            justify="left",
            anchor="w",
            bg="#FFFFFF",
            relief="sunken",
            padx=4,
            pady=4
        )
        self.summary_label.pack(fill="x", pady=2)

    # --- Core State & Throttled Rendering ---

    def _mark_stale(self) -> None:
        """Flags cached heatmaps as stale after edits."""
        self._update_legend()
        self._update_compare_summary()

    def _schedule_time_redraw(self, delay_ms: int = 50) -> None:
        """Debounces slider redraws by at least 50 ms."""
        if self._slider_after_id is not None:
            self.root.after_cancel(self._slider_after_id)
        self._slider_after_id = self.root.after(delay_ms, self._redraw_dynamic)

    def _on_slider_release(self) -> None:
        """Ensures immediate precise redraw upon slider release."""
        if self._slider_after_id is not None:
            self.root.after_cancel(self._slider_after_id)
            self._slider_after_id = None
        self._redraw_dynamic()

    def on_time_change(self, value) -> None:
        self.state.minutes = int(float(value))
        self._schedule_time_redraw(50)

    def _recompute_sun_and_strip(self) -> None:
        scen = self.state.scenarios[self.state.active] or self.state.scenarios["A"]
        sr, ss = sunrise_sunset(scen.lat, scen.lon, self.state.date, scen.tz_offset)
        self.state.sunrise_min = sr
        self.state.sunset_min = ss

        if sr is None:
            self.daylight_info_label.config(text="Polar Night: Sun below horizon all day")
        elif sr == 0 and ss == 1439:
            self.daylight_info_label.config(text="Midnight Sun: 24h Daylight")
        else:
            sr_h, sr_m = divmod(sr, 60)
            ss_h, ss_m = divmod(ss, 60)
            self.daylight_info_label.config(
                text=f"Sunrise {sr_h:02d}:{sr_m:02d} / Sunset {ss_h:02d}:{ss_m:02d}"
            )

        self._draw_daylight_strip()

    def _draw_daylight_strip(self) -> None:
        self.daylight_strip.delete("all")
        w = self.daylight_strip.winfo_width()
        if w < 10:
            w = 500
        h = 10

        sr = self.state.sunrise_min
        ss = self.state.sunset_min

        # Background night color
        self.daylight_strip.create_rectangle(0, 0, w, h, fill="#A4B0BE", outline="")

        if sr is not None and ss is not None and ss > sr:
            x0 = (sr / 1440.0) * w
            x1 = (ss / 1440.0) * w
            self.daylight_strip.create_rectangle(x0, 0, x1, h, fill="#FFDD59", outline="")

        # Tick at current time
        cur_x = (self.state.minutes / 1440.0) * w
        self.daylight_strip.create_line(cur_x, 0, cur_x, h, fill="#D9381E", width=2)

    def _redraw_dynamic(self) -> None:
        """Updates shadows, compass rose, time labels, and status bar."""
        self._slider_after_id = None
        scen_a = self.state.scenarios["A"]
        tz = scen_a.tz_offset if scen_a else 5.0
        lat = scen_a.lat if scen_a else 31.5204
        lon = scen_a.lon if scen_a else 74.3587

        self.state.sun = solar_position(lat, lon, self.state.date, float(self.state.minutes), tz)

        hh, mm = divmod(self.state.minutes, 60)
        sign = "+" if tz >= 0 else "-"
        self.time_label.config(text=f"{hh:02d}:{mm:02d} (UTC{sign}{abs(tz):.1f})")

        self._draw_daylight_strip()

        # Canvas A
        if self.state.scenarios["A"] is not None:
            sel_a = self.state.selected_id if self.state.active == "A" else None
            self.renderers["A"].draw_dynamic(
                self.state.scenarios["A"],
                self.state.sun,
                self.state.views["A"],
                heat_visible=self.state.show_heat,
                selected_id=sel_a
            )

        # Canvas B
        if self.state.compare_on and self.state.scenarios["B"] is not None:
            sel_b = self.state.selected_id if self.state.active == "B" else None
            self.renderers["B"].draw_dynamic(
                self.state.scenarios["B"],
                self.state.sun,
                self.state.views["B"],
                heat_visible=self.state.show_heat,
                selected_id=sel_b
            )

        self._update_status()

    def _full_redraw(self) -> None:
        """Full redraw: views fitting, static layers, heatmap layer, dynamic layers."""
        self._recompute_sun_and_strip()

        # Fit views
        w_a = max(200, self.canvas_A.winfo_width())
        h_a = max(200, self.canvas_A.winfo_height())
        scen_a = self.state.scenarios["A"]
        if scen_a:
            max_h_a = max([b.size.z for b in scen_a.buildings] or [20.0])
            fit_view(scen_a.ground_size, scen_a.cell_size_m, max_h_a, w_a, h_a, self.state.views["A"])
            self.renderers["A"].draw_static(scen_a, self.state.views["A"], self.state.selected_id if self.state.active == "A" else None)
            if self.state.show_heat:
                is_stale_a = (self.state.heat["A"] is None or self.state.heat["A"].scenario_revision != scen_a.revision)
                self.renderers["A"].draw_heat(self.state.heat["A"], is_stale=is_stale_a, view_params=self.state.views["A"], scenario=scen_a)

        if self.state.compare_on and self.state.scenarios["B"]:
            w_b = max(200, self.canvas_B.winfo_width())
            h_b = max(200, self.canvas_B.winfo_height())
            scen_b = self.state.scenarios["B"]
            max_h_b = max([b.size.z for b in scen_b.buildings] or [20.0])
            fit_view(scen_b.ground_size, scen_b.cell_size_m, max_h_b, w_b, h_b, self.state.views["B"])
            self.renderers["B"].draw_static(scen_b, self.state.views["B"], self.state.selected_id if self.state.active == "B" else None)

            if self.state.show_heat:
                is_stale_b = (self.state.heat["B"] is None or self.state.heat["B"].scenario_revision != scen_b.revision)
                diff_grid = None
                if self.state.diff_mode and self.state.heat["A"] and self.state.heat["B"]:
                    _, diff_grid = compare(self.state.heat["A"], self.state.heat["B"], scen_a, scen_b, self.state.target_hours)
                self.renderers["B"].draw_heat(
                    self.state.heat["B"],
                    diff_grid=diff_grid,
                    diff_mode=self.state.diff_mode,
                    is_stale=is_stale_b,
                    view_params=self.state.views["B"],
                    scenario=scen_b
                )

        self._redraw_dynamic()
        self._update_legend()
        self._update_compare_summary()

    def _update_status(self, msg: str | None = None) -> None:
        if msg:
            self.status_msg.config(text=msg)
            if self._status_after_id:
                self.root.after_cancel(self._status_after_id)
            self._status_after_id = self.root.after(
                6000,
                lambda: self.status_msg.config(text="Ready. Drag buildings or scrub time slider.")
            )

        sun = self.state.sun
        state_str = "Day" if sun.is_daytime else "Night"
        self.sun_readout.config(text=f"Az {sun.azimuth_deg:.1f}° | El {sun.elevation_deg:.1f}° | {state_str}")

    def _update_selected_ui(self) -> None:
        scen = self.state.scenarios[self.state.active]
        if scen is None or self.state.selected_id is None:
            self.sel_name_label.config(text="No building selected", fg="#6C757D")
            self.sel_height_spin.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)
            return

        target = next((b for b in scen.buildings if b.id == self.state.selected_id), None)
        if target is None:
            self.state.selected_id = None
            self.sel_name_label.config(text="No building selected", fg="#6C757D")
            self.sel_height_spin.config(state=tk.DISABLED)
            self.btn_delete.config(state=tk.DISABLED)
            return

        self.sel_name_label.config(
            text=f"Selected: {target.label} (ID {target.id})",
            fg=TEXT_COLOR
        )
        self.sel_height_spin.config(state=tk.NORMAL)
        self.sel_height_spin.set(int(target.size.z))
        self.btn_delete.config(state=tk.NORMAL)

    def _update_legend(self) -> None:
        mode = "diff" if (self.state.compare_on and self.state.diff_mode) else "abs"
        scen = self.state.scenarios[self.state.active]
        heat = self.state.heat[self.state.active]
        is_stale = (heat is None) or (scen is not None and heat.scenario_revision != scen.revision)
        draw_legend(self.legend_canvas, mode=mode, is_stale=is_stale)

    def _update_compare_summary(self) -> None:
        if not self.state.compare_on:
            self.summary_label.config(text="Comparison inactive.")
            return

        heat_a = self.state.heat["A"]
        heat_b = self.state.heat["B"]
        scen_a = self.state.scenarios["A"]
        scen_b = self.state.scenarios["B"]

        if heat_a is None or heat_b is None:
            self.summary_label.config(text="Run heatmap to compare A and B.")
            return

        is_stale = (heat_a.scenario_revision != scen_a.revision) or (heat_b.scenario_revision != scen_b.revision)
        metrics, _ = compare(heat_a, heat_b, scen_a, scen_b, self.state.target_hours)

        stale_prefix = "[STALE: Re-run] " if is_stale else ""
        text = (
            f"{stale_prefix}Common Cells: {metrics['common_count']}\n"
            f"Δ Sunlight: {metrics['delta']:+.2f} cell·h ({metrics['pct']:+.1f}%)\n"
            f"Area Impact: {metrics['area_hours']:+.1f} m²·h\n"
            f"Gained: {metrics['gained']} | Lost: {metrics['lost']} | Same: {metrics['unchanged']}\n"
            f"Frac >= {self.state.target_hours:.1f}h: A={metrics['frac_a']*100:.1f}%, B={metrics['frac_b']*100:.1f}%"
        )
        self.summary_label.config(text=text)

    # --- Canvas Event Handlers ---

    def on_canvas_resize(self, pane_id: str, event) -> None:
        self._full_redraw()

    def on_canvas_press(self, pane_id: str, event) -> None:
        self.state.active = pane_id
        if pane_id == "A":
            self.canvas_A.config(highlightbackground="#0066CC")
            self.canvas_B.config(highlightbackground="#CCCCCC")
            self.title_A.config(font=("TkDefaultFont", 10, "bold"))
            self.title_B.config(font=("TkDefaultFont", 10, "normal"))
            self.canvas_A.focus_set()
        else:
            self.canvas_B.config(highlightbackground="#0066CC")
            self.canvas_A.config(highlightbackground="#CCCCCC")
            self.title_B.config(font=("TkDefaultFont", 10, "bold"))
            self.title_A.config(font=("TkDefaultFont", 10, "normal"))
            self.canvas_B.focus_set()

        scen = self.state.scenarios[pane_id]
        if scen is None:
            return

        view = self.state.views[pane_id]
        hit_id = self.renderers[pane_id].hit_test_building(event.x, event.y, scen, view)
        self.state.selected_id = hit_id
        self._update_selected_ui()

        if hit_id is not None:
            b = next(b for b in scen.buildings if b.id == hit_id)
            gx, gy = geometry.unproject_ground((event.x, event.y), view)
            self.state.drag = {
                "b_id": hit_id,
                "start_g": (gx, gy),
                "orig_pos": (b.position.x, b.position.y),
            }

        self.renderers[pane_id].draw_static(scen, view, self.state.selected_id)
        self._redraw_dynamic()

    def on_canvas_drag(self, pane_id: str, event) -> None:
        if self.state.drag is None or self.state.drag.get("b_id") != self.state.selected_id:
            return

        scen = self.state.scenarios[pane_id]
        view = self.state.views[pane_id]
        if scen is None:
            return

        gx, gy = geometry.unproject_ground((event.x, event.y), view)
        dx = gx - self.state.drag["start_g"][0]
        dy = gy - self.state.drag["start_g"][1]

        ox, oy = self.state.drag["orig_pos"]
        cs = scen.cell_size_m
        new_x = round((ox + dx) / cs) * cs
        new_y = round((oy + dy) / cs) * cs

        moved = scen.move_building(self.state.drag["b_id"], Vec3(new_x, new_y, 0.0))
        if moved:
            self._mark_stale()
            self.renderers[pane_id].draw_static(scen, view, self.state.selected_id)
            self._redraw_dynamic()

    def on_canvas_release(self, pane_id: str, event) -> None:
        self.state.drag = None

    def on_canvas_hover(self, pane_id: str, event) -> None:
        scen = self.state.scenarios[pane_id]
        if scen is None:
            return
        view = self.state.views[pane_id]
        gx, gy = geometry.unproject_ground((event.x, event.y), view)

        cell = self.renderers[pane_id].cell_at(event.x, event.y, scen, view)
        b_id = self.renderers[pane_id].hit_test_building(event.x, event.y, scen, view)

        txt = f"x={gx:.1f}m y={gy:.1f}m"
        if b_id is not None:
            b = next(b for b in scen.buildings if b.id == b_id)
            txt += f" | {b.label} (H={b.size.z:.0f}m)"
        elif cell is not None and self.state.heat[pane_id] is not None:
            ci, cj = cell
            h = self.state.heat[pane_id].hours_array[cj][ci]
            if h >= 0:
                txt += f" | Cell: {h:.2f} h"

        self.hover_readout.config(text=txt)

    def on_canvas_key(self, step_x: int, step_y: int) -> None:
        if self.state.selected_id is None:
            return
        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return
        target = next((b for b in scen.buildings if b.id == self.state.selected_id), None)
        if target is None:
            return

        cs = scen.cell_size_m
        new_pos = Vec3(target.position.x + step_x * cs, target.position.y + step_y * cs, 0.0)
        if scen.move_building(target.id, new_pos):
            self._mark_stale()
            self.renderers[self.state.active].draw_static(
                scen, self.state.views[self.state.active], self.state.selected_id
            )
            self._redraw_dynamic()

    def on_delete_selected(self) -> None:
        if self.state.selected_id is None:
            return
        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return
        scen.remove_building(self.state.selected_id)
        self.state.selected_id = None
        self._update_selected_ui()
        self._mark_stale()
        self.renderers[self.state.active].draw_static(scen, self.state.views[self.state.active], None)
        self._redraw_dynamic()
        self._update_status("Deleted building.")

    # --- Location & Date Handlers ---

    def on_preset_selected(self, event=None) -> None:
        city = self.preset_combo.get()
        if city in CITY_PRESETS:
            p = CITY_PRESETS[city]
            self.lat_entry.delete(0, tk.END)
            self.lat_entry.insert(0, str(p["lat"]))
            self.lon_entry.delete(0, tk.END)
            self.lon_entry.insert(0, str(p["lon"]))
            self.tz_entry.delete(0, tk.END)
            self.tz_entry.insert(0, str(p["tz"]))
            self.on_location_commit()

    def on_location_commit(self) -> None:
        try:
            lat = float(self.lat_entry.get())
            lon = float(self.lon_entry.get())
            tz = float(self.tz_entry.get())

            if not (-90.0 <= lat <= 90.0):
                raise ValueError("Latitude must be between -90 and 90.")
            if not (-180.0 <= lon <= 180.0):
                raise ValueError("Longitude must be between -180 and 180.")
            if not (-12.0 <= tz <= 14.0):
                raise ValueError("Timezone offset must be between -12 and 14.")

            for k in ["A", "B"]:
                scen = self.state.scenarios[k]
                if scen:
                    scen.lat = lat
                    scen.lon = lon
                    scen.tz_offset = tz
                    scen.touch()

            self._mark_stale()
            self._full_redraw()
            self._update_status(f"Updated location: {lat:.2f}°N, {lon:.2f}°E, UTC{tz:+.1f}")
        except ValueError as err:
            self._update_status(f"Error: {err}")

    def on_date_change(self) -> None:
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        m_idx = months.index(self.month_combo.get()) + 1
        y = int(self.year_spin.get())
        d = int(self.day_spin.get())

        # Clamp day to month length
        if m_idx in (4, 6, 9, 11):
            max_d = 30
        elif m_idx == 2:
            is_leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
            max_d = 29 if is_leap else 28
        else:
            max_d = 31

        d = min(d, max_d)
        self.day_spin.set(d)
        self.state.date = (y, m_idx, d)

        for k in ["A", "B"]:
            scen = self.state.scenarios[k]
            if scen:
                scen.touch()

        self._mark_stale()
        self._full_redraw()
        self._update_status(f"Updated date: {y}-{m_idx:02d}-{d:02d}")

    # --- Building Form Handlers ---

    def on_add_building(self) -> None:
        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return

        if len(scen.buildings) >= MAX_BUILDINGS:
            self._update_status("Maximum 15 buildings reached.")
            return

        lbl = self.b_label_entry.get().strip() or "Block"
        if len(lbl) > 12:
            self._update_status("Label too long (max 12 characters).")
            return

        try:
            x = float(self.b_x_spin.get())
            y = float(self.b_y_spin.get())
            w = float(self.b_w_spin.get())
            d = float(self.b_d_spin.get())
            h = float(self.b_h_spin.get())
        except ValueError:
            self._update_status("Invalid numbers in building form.")
            return

        cs = scen.cell_size_m
        x = round(x / cs) * cs
        y = round(y / cs) * cs
        w = max(2.0, round(w / cs) * cs)
        d = max(2.0, round(d / cs) * cs)
        h = max(3.0, min(45.0, round(h)))
        color = self.b_color_combo.get()

        candidate = Building(scen.next_id, lbl, Vec3(x, y, 0.0), Vec3(w, d, h), color)
        if not scen.can_place(candidate):
            free_spot = scen.find_free_spot(candidate.size)
            if free_spot is None:
                self._update_status("No space available on site for this footprint.")
                return
            candidate.position = free_spot
            self.b_x_spin.set(int(free_spot.x))
            self.b_y_spin.set(int(free_spot.y))

        scen.add_building(candidate)
        self.state.selected_id = candidate.id
        self._update_selected_ui()
        self._mark_stale()
        self.renderers[self.state.active].draw_static(
            scen, self.state.views[self.state.active], self.state.selected_id
        )
        self._redraw_dynamic()
        self._update_status(f"Added {lbl} at ({candidate.position.x:.0f}, {candidate.position.y:.0f}).")

    def on_height_commit(self) -> None:
        if self.state.selected_id is None:
            return
        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return
        target = next((b for b in scen.buildings if b.id == self.state.selected_id), None)
        if target is None:
            return

        try:
            h = float(self.sel_height_spin.get())
            h = max(3.0, min(45.0, round(h)))
            target.size.z = h
            scen.touch()
            self._mark_stale()
            self.renderers[self.state.active].draw_static(
                scen, self.state.views[self.state.active], self.state.selected_id
            )
            self._redraw_dynamic()
        except ValueError:
            pass

    # --- Heatmap Execution Handlers ---

    def on_run_heatmap(self) -> None:
        if self.active_heatmap_job is not None:
            self.active_heatmap_job.cancel()
            self.active_heatmap_job = None
            self.btn_run_heatmap.config(text="Run Heatmap")
            self._update_status("Heatmap run cancelled.")
            return

        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return

        sr, ss = sunrise_sunset(scen.lat, scen.lon, self.state.date, scen.tz_offset)
        if sr is None or ss is None:
            self._update_status("No direct daylight on selected date.")
            return

        step_min = int(self.step_combo.get())
        self.state.step_min = step_min

        self.active_heatmap_job = HeatmapJob(scen, self.state.date, sr, ss, step_min)
        self.btn_run_heatmap.config(text="Cancel")
        self.heatmap_progress["value"] = 0
        self.root.after(1, self._heat_tick)

    def _heat_tick(self) -> None:
        if self.active_heatmap_job is None:
            return

        has_more = self.active_heatmap_job.step()
        prog = self.active_heatmap_job.progress()
        self.heatmap_progress["value"] = prog * 100.0

        if has_more and not self.active_heatmap_job.cancelled:
            self.root.after(1, self._heat_tick)
        else:
            if not self.active_heatmap_job.cancelled:
                grid = self.active_heatmap_job.result()
                self.state.heat[self.state.active] = grid
                self.state.show_heat = True
                self.heat_var.set(True)
                self._update_status("Heatmap analysis complete.")

            self.btn_run_heatmap.config(text="Run Heatmap")
            self.active_heatmap_job = None
            self._full_redraw()

    def on_toggle_heat(self) -> None:
        self.state.show_heat = self.heat_var.get()
        self._full_redraw()

    def on_target_change(self) -> None:
        try:
            self.state.target_hours = float(self.target_spin.get())
            self._update_compare_summary()
        except ValueError:
            pass

    # --- Scenario Comparison Handlers ---

    def on_toggle_compare(self) -> None:
        self.state.compare_on = self.compare_var.get()
        if self.state.compare_on:
            if self.state.scenarios["B"] is None:
                self.state.scenarios["B"] = self.state.scenarios["A"].clone()
                self.state.scenarios["B"].name = "Scenario B"

            self.canvas_B.grid()
            self.title_B.grid()
            self.btn_copy_a_to_b.config(state=tk.NORMAL)
            self._update_status("Scenario comparison enabled.")
        else:
            self.canvas_B.grid_remove()
            self.title_B.grid_remove()
            self.btn_copy_a_to_b.config(state=tk.DISABLED)
            self.state.active = "A"
            self.canvas_A.config(highlightbackground="#0066CC")
            self._update_status("Scenario comparison disabled.")

        self._full_redraw()

    def on_view_mode_change(self) -> None:
        self.state.diff_mode = (self.view_mode_var.get() == "diff")
        self._full_redraw()

    def on_copy_a_to_b(self) -> None:
        if self.state.scenarios["A"] is not None:
            self.state.scenarios["B"] = self.state.scenarios["A"].clone()
            self.state.scenarios["B"].name = "Scenario B"
            self.state.heat["B"] = None
            self._mark_stale()
            self._full_redraw()
            self._update_status("Copied Scenario A to Scenario B.")

    # --- Menu Actions ---

    def on_new(self) -> None:
        self.state.scenarios["A"] = create_demo_scenario()
        self.state.scenarios["B"] = None
        self.state.heat["A"] = None
        self.state.heat["B"] = None
        self.state.selected_id = None
        self.state.compare_on = False
        self.compare_var.set(False)
        self.canvas_B.grid_remove()
        self.title_B.grid_remove()
        self._update_selected_ui()
        self._full_redraw()
        self._update_status("Loaded default Courtyard demo scenario.")

    def on_open(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_scen = Scenario.from_dict(data)
            self.state.scenarios[self.state.active] = loaded_scen
            self.state.heat[self.state.active] = None
            self.state.selected_id = None
            self._update_selected_ui()
            self._full_redraw()
            self._update_status(f"Opened scenario from {path}")
        except Exception as err:
            messagebox.showerror("Error", f"Could not load scenario: {err}")

    def on_save(self) -> None:
        scen = self.state.scenarios[self.state.active]
        if scen is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(scen.to_dict(), f, indent=2)
            self._update_status(f"Saved scenario to {path}")
        except Exception as err:
            messagebox.showerror("Error", f"Could not save scenario: {err}")

    def on_show_assumptions(self) -> None:
        AssumptionsDialog(self.root)

    def on_run_selftest(self) -> None:
        all_checks = []
        all_checks.extend(solar.run_checks())
        all_checks.extend(geometry.run_checks())
        all_checks.extend(scenario_mod.run_checks())
        all_checks.extend(heatmap_mod.run_checks())
        all_checks.extend(renderer_mod.run_checks())

        win = tk.Toplevel(self.root)
        win.title("Self-Test Results")
        win.geometry("620x460")
        win.minsize(500, 350)
        win.transient(self.root)

        txt = tk.Text(win, wrap=tk.WORD, padx=10, pady=10)
        scroll = ttk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)

        passed_count = sum(1 for c in all_checks if c[1])
        total_count = len(all_checks)

        header = f"=== SELF-TEST REPORT: {passed_count}/{total_count} PASSED ===\n\n"
        txt.insert(tk.END, header)

        for name, ok, detail in all_checks:
            tag = "PASS" if ok else "FAIL"
            txt.insert(tk.END, f"[{tag}] {name}\n      {detail}\n\n")

        txt.configure(state=tk.DISABLED)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def on_run_benchmark(self) -> None:
        # Create a benchmark scenario with 15 buildings
        bench_scen = self.state.scenarios["A"].clone()
        while len(bench_scen.buildings) < MAX_BUILDINGS:
            idx = len(bench_scen.buildings)
            spot = bench_scen.find_free_spot(Vec3(4.0, 4.0, 10.0))
            if spot:
                bench_scen.add_building(
                    Building(idx + 10, f"B{idx}", spot, Vec3(4.0, 4.0, 10.0), BUILDING_COLORS[idx % len(BUILDING_COLORS)])
                )
            else:
                break

        times_ms = []
        # Run 100 redraws sweeping across the day
        for m in range(360, 1080, 7):
            t0 = datetime.datetime.now()
            sun = solar_position(bench_scen.lat, bench_scen.lon, (2024, 3, 21), float(m), bench_scen.tz_offset)
            self.renderers["A"].draw_dynamic(bench_scen, sun, self.state.views["A"], heat_visible=False)
            self.root.update_idletasks()
            dt = (datetime.datetime.now() - t0).total_seconds() * 1000.0
            times_ms.append(dt)

        times_ms.sort()
        mean_ms = sum(times_ms) / len(times_ms) if times_ms else 0.0
        p95_ms = times_ms[int(0.95 * len(times_ms))] if times_ms else 0.0
        fps = 1000.0 / mean_ms if mean_ms > 0 else 0.0

        messagebox.showinfo(
            "Benchmark Results",
            f"100 Frame Benchmark (15 Buildings):\n\n"
            f"Mean frame time: {mean_ms:.2f} ms ({fps:.1f} FPS)\n"
            f"p95 frame time: {p95_ms:.2f} ms\n\n"
            f"Success Criterion SC3 (p95 <= 66 ms): {'PASS' if p95_ms <= 66.0 else 'FAIL'}"
        )

    def on_about(self) -> None:
        messagebox.showinfo(
            "About",
            "Sunlight & Shadow Analyzer (SSA)\n"
            "Version 1.0\n\n"
            "An interactive sun-path, shadow, and sunlight-hours tool "
            "for small-site urban planning and architectural design."
        )
