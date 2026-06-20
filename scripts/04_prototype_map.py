r"""
04_prototype_map.py
===================

PHASE 5 (prototype) of the Memphis Pedestrian Safety project.

What this script does, in plain English:
  Draws ONE high-resolution picture (a PNG) so we can eyeball that the crash
  data lands sensibly on a real map of Memphis. It is a sanity-check prototype,
  NOT the final deliverable.

  The map shows:
    - A light OpenStreetMap street background (so the dots sit on a recognizable
      Memphis street grid).
    - The City of Memphis boundary as a thin outline.
    - The TDOT state-route segments as colored lines under the points.
    - Every IN-MEMPHIS crash as a dot, colored by who owns the road:
      teal = City of Memphis, red = TDOT.
    - Fatal crashes drawn bigger with a dark outline so they stand out.
    - A title, legend, scale bar, north arrow, and a text box of headline
      stats computed live from the data.

  If the background map tiles can't be downloaded (e.g. no internet), it falls
  back to a plain white background and prints a note.

It does NOT change any data files - it only reads them and writes a picture.

Run it with:
    .\.venv\Scripts\python.exe scripts\04_prototype_map.py
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import math
from pathlib import Path

import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # draw to a file, no interactive window needed
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrow
from matplotlib.offsetbox import AnchoredText
import contextily as cx


# ---------------------------------------------------------------------------
# SETTINGS - the knobs you might want to change live here at the top.
# ---------------------------------------------------------------------------

# Provisional prototype colors (easy to change later).
COLOR_CITY = "#1b9e9e"   # teal  -> City of Memphis crashes
COLOR_TDOT = "#d62728"   # red   -> TDOT (state route) crashes
COLOR_ROADS = "#7030a0"  # purple -> state-route lines
COLOR_BOUNDARY = "#222222"

# Marker sizes (points^2 for matplotlib scatter).
SIZE_NONFATAL = 16
SIZE_FATAL = 70

# Which jurisdictions count as "in Memphis" and get plotted.
IN_MEMPHIS_JURISDICTIONS = ["TDOT", "City of Memphis"]

# The exact InjuryClass value that means a death.
FATAL_VALUE = "Fatal"

# Coordinate systems.
GEOGRAPHIC_CRS = "EPSG:4326"   # the lat/long the files are stored in
DISPLAY_CRS = "EPSG:3857"      # Web Mercator, to match the basemap tiles

# How much breathing room to leave around the city boundary (fraction of width).
EXTENT_MARGIN = 0.03

# Output settings.
OUTPUT_DPI = 300


# ---------------------------------------------------------------------------
# FILE PATHS
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"

CRASH_CSV_PATH = PROCESSED_DIR / "shelby_crashes_classified.csv"
ROADS_GEOJSON_PATH = RAW_DIR / "state_routes.geojson"
BOUNDARY_GEOJSON_PATH = RAW_DIR / "memphis_boundary.geojson"
OUTPUT_PNG_PATH = OUTPUTS_DIR / "prototype_crash_map.png"


# ---------------------------------------------------------------------------
# Decide whether a single lat/long pair is usable for plotting.
# ---------------------------------------------------------------------------
def is_good_location(lat, lon):
    if pd.isna(lat) or pd.isna(lon):
        return False
    if lat == 0 and lon == 0:
        return False
    # Plausible range for the Memphis / Shelby County area.
    if not (34.9 <= lat <= 35.5):
        return False
    if not (-90.4 <= lon <= -89.5):
        return False
    return True


# ---------------------------------------------------------------------------
# Draw a north arrow in the top-left of the map.
# ---------------------------------------------------------------------------
def add_north_arrow(ax):
    # Place it using axis-fraction coordinates so it sits in a fixed spot.
    x, y = 0.07, 0.93
    ax.annotate(
        "N",
        xy=(x, y), xytext=(x, y - 0.06),
        xycoords="axes fraction",
        ha="center", va="center",
        fontsize=14, fontweight="bold",
        arrowprops=dict(facecolor="black", edgecolor="black", width=4, headwidth=12),
    )


# ---------------------------------------------------------------------------
# Draw a latitude-corrected scale bar in the lower-left of the map.
#
# Web Mercator (EPSG:3857) stretches distances by ~1/cos(latitude). At Memphis
# (~35 deg N) that's about 1.22x. So we shrink the on-screen bar by cos(lat) so
# the labeled distance is approximately TRUE ground distance.
# ---------------------------------------------------------------------------
def add_scale_bar(ax, center_lat_deg, bar_ground_meters=2000):
    correction = math.cos(math.radians(center_lat_deg))
    # Length to draw in Web Mercator meters so that it represents
    # `bar_ground_meters` on the actual ground.
    bar_display_meters = bar_ground_meters / correction

    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    width = xmax - xmin

    # Anchor the bar a little in from the bottom-left corner.
    x0 = xmin + 0.06 * width
    y0 = ymin + 0.07 * (ymax - ymin)
    x1 = x0 + bar_display_meters

    ax.plot([x0, x1], [y0, y0], color="black", linewidth=3, solid_capstyle="butt", zorder=6)
    # Small end ticks.
    tick = 0.012 * (ymax - ymin)
    ax.plot([x0, x0], [y0 - tick, y0 + tick], color="black", linewidth=3, zorder=6)
    ax.plot([x1, x1], [y0 - tick, y0 + tick], color="black", linewidth=3, zorder=6)

    label_km = bar_ground_meters / 1000.0
    label = f"{label_km:g} km"
    ax.text((x0 + x1) / 2, y0 + 0.02 * (ymax - ymin), label,
            ha="center", va="bottom", fontsize=9, fontweight="bold", zorder=6)


def main():
    OUTPUTS_DIR.mkdir(exist_ok=True)

    # -----------------------------------------------------------------------
    # 1. Load the crash data and keep only plottable, in-Memphis rows.
    # -----------------------------------------------------------------------
    df = pd.read_csv(CRASH_CSV_PATH)
    total_rows = len(df)

    good_mask = [is_good_location(lat, lon)
                 for lat, lon in zip(df["Latitude"], df["Longitude"])]
    df_good = df[good_mask].copy()
    dropped_bad_coords = total_rows - len(df_good)

    # Only crashes inside Memphis (TDOT or City of Memphis) get plotted.
    plot_df = df_good[df_good["Jurisdiction"].isin(IN_MEMPHIS_JURISDICTIONS)].copy()

    # -----------------------------------------------------------------------
    # 2. Compute the headline stats LIVE (over the in-Memphis plotted set).
    # -----------------------------------------------------------------------
    n_total = len(plot_df)
    n_city = int((plot_df["Jurisdiction"] == "City of Memphis").sum())
    n_tdot = int((plot_df["Jurisdiction"] == "TDOT").sum())
    pct_city = 100.0 * n_city / n_total if n_total else 0.0
    pct_tdot = 100.0 * n_tdot / n_total if n_total else 0.0

    fatal_df = plot_df[plot_df["InjuryClass"] == FATAL_VALUE]
    n_fatal = len(fatal_df)
    n_fatal_city = int((fatal_df["Jurisdiction"] == "City of Memphis").sum())
    n_fatal_tdot = int((fatal_df["Jurisdiction"] == "TDOT").sum())

    date_min = plot_df["CollisionDate"].min()
    date_max = plot_df["CollisionDate"].max()

    # -----------------------------------------------------------------------
    # 3. Build geometry (lat/long) then reproject everything to Web Mercator
    #    so it lines up with the OpenStreetMap basemap tiles.
    # -----------------------------------------------------------------------
    crashes = gpd.GeoDataFrame(
        plot_df,
        geometry=gpd.points_from_xy(plot_df["Longitude"], plot_df["Latitude"]),
        crs=GEOGRAPHIC_CRS,
    ).to_crs(DISPLAY_CRS)

    roads = gpd.read_file(ROADS_GEOJSON_PATH).to_crs(DISPLAY_CRS)
    boundary = gpd.read_file(BOUNDARY_GEOJSON_PATH)
    # Use the boundary's center latitude (in lat/long) for the scale-bar fix.
    center_lat = float(boundary.geometry.iloc[0].centroid.y)
    boundary = boundary.to_crs(DISPLAY_CRS)

    # -----------------------------------------------------------------------
    # 4. Set up the figure and the map extent (framed on the city boundary).
    # -----------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(12, 13))

    bxmin, bymin, bxmax, bymax = boundary.total_bounds
    mx = (bxmax - bxmin) * EXTENT_MARGIN
    my = (bymax - bymin) * EXTENT_MARGIN
    ax.set_xlim(bxmin - mx, bxmax + mx)
    ax.set_ylim(bymin - my, bymax + my)

    # -----------------------------------------------------------------------
    # 5. Draw layers from bottom to top.
    # -----------------------------------------------------------------------
    # Boundary outline (thin).
    boundary.boundary.plot(ax=ax, color=COLOR_BOUNDARY, linewidth=1.2, zorder=2)

    # State-route lines (under the points, slightly thicker, distinct color).
    roads.plot(ax=ax, color=COLOR_ROADS, linewidth=1.1, alpha=0.8, zorder=3)

    # Crash points. Split into 4 groups: {city, tdot} x {non-fatal, fatal}.
    is_fatal = crashes["InjuryClass"] == FATAL_VALUE
    is_city = crashes["Jurisdiction"] == "City of Memphis"
    is_tdot = crashes["Jurisdiction"] == "TDOT"

    # Non-fatal first (small, no outline), then fatal on top (large, dark edge).
    city_nf = crashes[is_city & ~is_fatal]
    tdot_nf = crashes[is_tdot & ~is_fatal]
    city_f = crashes[is_city & is_fatal]
    tdot_f = crashes[is_tdot & is_fatal]

    ax.scatter(city_nf.geometry.x, city_nf.geometry.y, s=SIZE_NONFATAL,
               c=COLOR_CITY, alpha=0.75, linewidths=0, zorder=4)
    ax.scatter(tdot_nf.geometry.x, tdot_nf.geometry.y, s=SIZE_NONFATAL,
               c=COLOR_TDOT, alpha=0.75, linewidths=0, zorder=4)
    ax.scatter(city_f.geometry.x, city_f.geometry.y, s=SIZE_FATAL,
               c=COLOR_CITY, edgecolors="black", linewidths=1.2, zorder=5)
    ax.scatter(tdot_f.geometry.x, tdot_f.geometry.y, s=SIZE_FATAL,
               c=COLOR_TDOT, edgecolors="black", linewidths=1.2, zorder=5)

    # -----------------------------------------------------------------------
    # 6. Basemap (with graceful fallback to white if tiles fail).
    # -----------------------------------------------------------------------
    basemap_ok = True
    try:
        cx.add_basemap(ax, source=cx.providers.OpenStreetMap.Mapnik,
                       crs=DISPLAY_CRS, attribution_size=6)
    except Exception as problem:
        basemap_ok = False
        ax.set_facecolor("white")
        print(f"NOTE: basemap tiles could not be downloaded ({problem}).")
        print("      Falling back to a plain white background.")

    # -----------------------------------------------------------------------
    # 7. Map furniture: title, legend, scale bar, north arrow, stats box.
    # -----------------------------------------------------------------------
    ax.set_title(
        "Memphis Pedestrian & Non-Motorist Crashes by Road Ownership\n"
        "Prototype sanity map - in-Memphis crashes, City vs. TDOT state routes",
        fontsize=15, fontweight="bold", pad=14,
    )
    ax.set_xticks([])
    ax.set_yticks([])

    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLOR_CITY,
               markersize=9, label="City of Memphis crash"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLOR_TDOT,
               markersize=9, label="TDOT (state route) crash"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#999999",
               markeredgecolor="black", markeredgewidth=1.2, markersize=13,
               label="Fatal crash (larger, outlined)"),
        Line2D([0], [0], color=COLOR_ROADS, linewidth=2.2, label="TDOT state route"),
        Line2D([0], [0], color=COLOR_BOUNDARY, linewidth=1.2, label="Memphis boundary"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", frameon=True,
              framealpha=0.92, fontsize=9, title="Legend", title_fontsize=10)

    add_north_arrow(ax)
    add_scale_bar(ax, center_lat_deg=center_lat, bar_ground_meters=2000)

    # Stats text box (computed above), pinned to the lower-right.
    stats_text = (
        "In-Memphis crashes (2023-01-01 to {dmax})\n"
        "Total plotted: {tot:,}\n"
        "  City of Memphis: {nc:,}  ({pc:.1f}%)\n"
        "  TDOT state route: {nt:,}  ({pt:.1f}%)\n"
        "Fatal crashes: {nf:,}\n"
        "  City: {nfc:,}    TDOT: {nft:,}\n"
        "Date range: {dmin} to {dmax}"
    ).format(
        tot=n_total, nc=n_city, pc=pct_city, nt=n_tdot, pt=pct_tdot,
        nf=n_fatal, nfc=n_fatal_city, nft=n_fatal_tdot,
        dmin=date_min, dmax=date_max,
    )
    stats_box = AnchoredText(
        stats_text, loc="lower right", frameon=True, prop=dict(size=9),
        pad=0.5, borderpad=0.6,
    )
    stats_box.patch.set_facecolor("white")
    stats_box.patch.set_alpha(0.9)
    stats_box.patch.set_edgecolor("#444444")
    ax.add_artist(stats_box)

    # -----------------------------------------------------------------------
    # 8. Save the picture.
    # -----------------------------------------------------------------------
    fig.savefig(OUTPUT_PNG_PATH, dpi=OUTPUT_DPI, bbox_inches="tight")
    plt.close(fig)

    # -----------------------------------------------------------------------
    # 9. Print the stats to the terminal so they can be checked vs. the map.
    # -----------------------------------------------------------------------
    print("=" * 64)
    print("PROTOTYPE MAP - headline stats (computed from the data)")
    print("=" * 64)
    print(f"Rows in source file:                 {total_rows:,}")
    print(f"Rows dropped for bad coordinates:    {dropped_bad_coords:,}")
    print(f"In-Memphis crashes plotted:          {n_total:,}")
    print(f"  City of Memphis: {n_city:,} ({pct_city:.1f}%)")
    print(f"  TDOT state route: {n_tdot:,} ({pct_tdot:.1f}%)")
    print(f"Fatal crashes plotted:               {n_fatal:,}")
    print(f"  City: {n_fatal_city:,}    TDOT: {n_fatal_tdot:,}")
    print(f"Date range (plotted):                {date_min} to {date_max}")
    print(f"Basemap downloaded:                  {basemap_ok}")
    print(f"Saved map -> {OUTPUT_PNG_PATH}")
    print("=" * 64)


if __name__ == "__main__":
    main()
