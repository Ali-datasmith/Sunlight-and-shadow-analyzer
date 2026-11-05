# Sunlight & Shadow Analyzer (SSA)

The Sunlight & Shadow Analyzer is an intuitive, interactive desktop planning application designed for urban planners, municipal reviewers, and architecture students. It allows non-technical stakeholders to quickly explore how proposed buildings cast shadows and alter sunlight accessibility across urban plots, private courtyards, neighboring gardens, and rooftops over any day of the year. Operating completely offline without expensive licenses or complex CAD software, the tool delivers immediate visual feedback through responsive solar scrubbing, clear-sky sunlight accumulation heatmaps, and side-by-side scenario comparisons.

## Problem Statement

Junior urban planners and architecture students working on tight urban plots in dense cities frequently struggle to assess how new developments alter sunlight access for neighboring properties throughout an entire day. Commercial simulation packages are heavily licensed, difficult to learn, or online-only, while traditional hand-drawn solar diagrams capture only one or two arbitrary moments, making worst-case shadow impacts easy to miss. The Sunlight & Shadow Analyzer addresses this gap with an offline, interactive tool that simulates continuous daily shadow transitions, computes direct sunlight-hour heatmaps, and quantifies before-and-after differences with transparent scientific assumptions.

## Screenshots

Screenshot: A clean split-pane window featuring an axonometric (isometric) 3D view of an urban courtyard site in Lahore. Colorful rectangular buildings cast dark, crisp shadows across a light-green 60 m × 60 m ground grid under a morning sun at azimuth 129° and elevation 46°. In the top-right corner of each viewport, a circular compass rose indicates orientation with a red true-north arrow and a yellow sun marker. A horizontal time slider scrubs smoothly across the 24-hour day beneath a yellow daylight span indicator showing sunrise and sunset times. The left panel houses intuitive location presets, building addition controls, and a vibrant Viridis sunlight-hour heatmap overlay with a dedicated comparative metrics summary.

## Installation

Ensure Python 3.10 or higher is installed. On Linux systems, install the Tkinter package from your operating system package manager if not already available:

```bash
# On Debian/Ubuntu Linux:
sudo apt-get update && sudo apt-get install -y python3-tk

# Optional: install numpy to accelerate ray-casting operations
pip install -r requirements.txt
```

## How to Run

Launch the application directly from the project root directory:

```bash
python main.py
```

## How to Use

1. **Explore the Site & Shadows:** Scrub the horizontal **Time Slider** at the bottom to watch the sun move across the sky and observe real-time shadow elongation and direction changes from dawn to dusk.
2. **Add a Building:** In the left sidebar under **Add Building**, enter a label (e.g., "Tower"), specify the footprint width, depth, and height, select a color, and click **Add Building**. If the chosen coordinates overlap an existing structure, the system will automatically snap the building to the nearest free grid cell.
3. **Move & Adjust Buildings:** Click on any building in the viewport to select it. Drag it with the mouse across the 2 m grid, or nudge it with the keyboard arrow keys. Adjust its height in the **Selected Building** frame or press **Delete** to remove it.
4. **Run Sunlight Heatmap:** Select a time step (5, 10, 15, or 30 minutes) and click **Run Heatmap**. A non-blocking progress bar will track calculation progress. Once complete, check **Show Heatmap** to display the direct sunlight-hours color map across all ground and rooftop cells.
5. **Compare Scenarios (A/B):** Check **Compare Scenarios (A/B)** to open a side-by-side viewport. Click **Copy A → B**, modify buildings in Scenario B (e.g., reduce height or shift footprint), run the heatmap on both, and toggle **Diff (B − A)** to inspect gained (blue) and lost (orange) sunlight hours alongside quantitative impact metrics.

## Controls Reference

| Control | Location | Description |
|---|---|---|
| **Time Slider** | Center bottom | Scrubs local time from 00:00 to 23:59 with a 50 ms debounce for fluid shadow updates. |
| **Daylight Strip** | Above time slider | Visual bar highlighting the daylight window between local sunrise and sunset with a red cursor. |
| **City Preset** | Left panel (Location) | Quick-select dropdown for preconfigured cities (Lahore, Karachi, Islamabad, London, New York, Sydney). |
| **Lat / Lon / UTC Offset** | Left panel (Location) | Manual numerical entry fields for site coordinates and standard timezone offset. |
| **Month / Day / Year** | Left panel (Location) | Date controls to calculate solar declination and seasonal sun paths. |
| **Add Building Form** | Left panel | Input fields for label, X/Y coordinates, width, depth, height, and color selection. |
| **Selected Height Spinbox** | Left panel | Adjusts the height of the currently active building in real time. |
| **Delete Building Button** | Left panel | Deletes the currently selected building (also bound to the `<Delete>` key). |
| **Time Step Combobox** | Left panel (Heatmap) | Selects the numerical integration step (5, 10, 15, or 30 minutes). |
| **Run Heatmap Button** | Left panel (Heatmap) | Launches non-blocking sunlight accumulation; toggles to "Cancel" during execution. |
| **Show Heatmap Checkbox** | Left panel (Heatmap) | Toggles the visibility of the color-coded sunlight-hours overlay on ground and roofs. |
| **Target Hours Spinbox** | Left panel (Heatmap) | Threshold in hours (default 2.0 h) for amenity space compliance analysis (BRE BR 209). |
| **Compare Checkbox** | Left panel (Scenarios) | Toggles dual-viewport side-by-side comparison mode between Scenario A and Scenario B. |
| **Absolute / Diff Radios** | Left panel (Scenarios) | Switches Scenario B heatmap between absolute hours and difference map (B − A). |
| **Copy A → B Button** | Left panel (Scenarios) | Clones Scenario A layout into Scenario B for rapid iterative testing. |
| **Assumptions & Limits** | Left panel / Help menu | Opens the scientific disclosures dialog detailing all physical and mathematical assumptions. |
| **Run Self-Tests** | Help menu | Runs comprehensive unit and integration verification against benchmark solar cases. |
| **Benchmark** | Help menu | Executes a 100-frame rendering benchmark measuring mean/p95 frame times and FPS. |

## Known Limitations

1. **Axis-Aligned Box Geometry Only:** All buildings are modeled as axis-aligned cuboids; rotations around the vertical axis, curved surfaces, pitched roofs, and arbitrary CAD shapes are not supported.
2. **Clear-Sky Direct Sunlight Model:** The tool calculates direct beam sunlight only; cloud attenuation, diffuse sky illumination, ambient reflections, and atmospheric turbidity are omitted.
3. **Hard-Edged Point Sun:** The sun is treated as an idealized point source; shadows have sharp geometric edges without penumbral soft blur.
4. **2.0° Horizon Cut-off:** Sunlight accumulation and shadow casting are intentionally deactivated when apparent solar elevation is below 2.0° to prevent unbounded shadow lengths.
5. **Fixed Grid Resolution:** The simulation grid is fixed at 30 × 30 cells (2.0 m cell size, 60 m × 60 m site area), which balances real-time performance with spatial detail.
6. **No Automatic Daylight Saving Time:** Timezone offsets are entered manually by the user in standard hours east of UTC without automatic seasonal DST shifts.
7. **Orientation-Only Facade Shading:** Building vertical walls display Lambertian orientation shading for 3D depth, but facade-on-facade shadow occlusion is not computed in the heatmap.

## Project Structure

```
├── geometry.py        # 3D vector math, isometric projection, ray-AABB, and polygon clipping.
├── solar.py           # NOAA solar position calculations, refraction, and sunrise/sunset scanning.
├── scenario.py        # Building and Scenario data models, collision/overlap logic, and serialization.
├── heatmap.py         # Incremental sunlight-hours accumulator and A/B scenario comparison metrics.
├── renderer.py        # Layered Tkinter canvas rendering, face shading, color palettes, and legend.
├── ui.py              # Tkinter UI assembly, event handlers, time debouncing, and modal dialogs.
├── main.py            # Clean application entry point initializing Tk and launching mainloop.
├── requirements.txt   # Optional dependencies (numpy for accelerated ray testing).
└── README.md          # Comprehensive user guide, mathematical specifications, and documentation.
```

## Credits

- **NOAA Global Monitoring Laboratory:** "General Solar Position Calculations" spreadsheet algorithm, derived from Jean Meeus, *Astronomical Algorithms*, 2nd ed., Willmann-Bell, 1998.
- **Ray-AABB Intersection:** Kay, T. L., & Kajiya, J. T. (1986). "Ray tracing complex scenes", *ACM SIGGRAPH Computer Graphics*, 20(4); and Williams et al. (2005), "An efficient and robust ray-box intersection algorithm", *Journal of Graphics Tools*, 10(1).
- **Convex Hull & Clipping:** Andrew's monotone chain 2D convex hull algorithm; Sutherland, I. E., & Hodgman, G. W. (1974), "Reentrant polygon clipping", *Communications of the ACM*, 17(1).
- **Color Scales & Usability:** Viridis colormap by Nathaniel Smith & Stéfan van der Walt; WCAG 2.2 contrast compliance standards by W3C; Littlefair, P. (2011), *Site layout planning for daylight and sunlight: a guide to good practice* (BRE BR 209).
