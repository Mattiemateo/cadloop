"""Plot the finished shooter's actual Y=0 BREP section and an illustrative ball path.

Run inside the CADLoop Docker image; this script only reads an exported scene.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

from cadloop.views import section_lines
from cadloop.worker import load_geometry


STYLE = {
    "hood": ("#1565c0", "Hood, printed"),
    "feed_chute": ("#26a69a", "Feed chute, printed"),
    "flywheel_core": ("#6a1b9a", "Flywheel core, printed"),
    "silicone_tire": ("#e65100", "25A silicone tire"),
    "base_plywood": ("#8d6e63", "3 mm plywood base"),
    "turret_adapter": ("#455a64", "Turret adapter, printed"),
    "camera_mount": ("#7986cb", "Limelight mount, printed"),
    "motor_mount": ("#7cb342", "Motor mount, printed"),
    "chain_guard": ("#9e9d24", "Chain guard, printed"),
    "motor_reference": ("#c62828", "Motor envelope, reference"),
    "limelight_reference": ("#d17f00", "Limelight envelope, reference"),
    "main_shaft_reference": ("#616161", "Shaft, reference"),
    "driver_shaft_reference": ("#616161", "Shaft, reference"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hood-angle", type=float, default=65.0)
    args = parser.parse_args()
    if not 0 < args.hood_angle < 90:
        parser.error("hood angle must be between 0 and 90 degrees")

    parts = load_geometry(args.geometry)
    fig, ax = plt.subplots(figsize=(12.8, 8.0), dpi=180)
    fig.subplots_adjust(left=0.09, right=0.69, bottom=0.12, top=0.84)
    legend = {}
    count = 0
    for name, shape in parts.items():
        lines = section_lines(shape)
        if not lines:
            continue
        color, label = STYLE.get(name, ("#b0bec5", "Other sectioned parts"))
        reference = name.endswith("_reference")
        for line in lines:
            ax.plot(line[:, 0], line[:, 1], color=color,
                    lw=1.15 if reference else 1.55,
                    ls="--" if reference else "-", zorder=3 if reference else 2)
        legend[label] = Line2D([0], [0], color=color,
                               lw=1.6, ls="--" if reference else "-")
        count += len(lines)
    if not count:
        raise RuntimeError("The exported BREP solids did not intersect the Y=0 plane")

    # Nominal centerline construction for maximum specified POLLEN diameter.
    # This overlay is not a measured BREP edge or a ballistic scoring prediction.
    ball_d = 73.66
    ball_r = ball_d / 2
    hood_r = 118.12
    center_r = hood_r - ball_r
    shaft_z = 140.0
    outlet_theta = math.radians(args.hood_angle - 90.0)
    theta = np.linspace(-math.pi, outlet_theta, 181)
    x = center_r * np.cos(theta)
    z = shaft_z + center_r * np.sin(theta)
    ax.plot(x, z, color="#ff7043", lw=2.4, ls=(0, (5, 3)), zorder=5)
    ax.add_patch(Circle((x[-1], z[-1]), ball_r, fill=False,
                        ec="#ff7043", lw=1.35, alpha=0.76, zorder=4))
    dx = 74 * math.cos(math.radians(args.hood_angle))
    dz = 74 * math.sin(math.radians(args.hood_angle))
    ax.annotate("", xy=(x[-1] + dx, z[-1] + dz), xytext=(x[-1], z[-1]),
                arrowprops={"arrowstyle": "-|>", "lw": 2.4, "color": "#d84315",
                            "mutation_scale": 17}, zorder=6)
    ax.annotate(f"{args.hood_angle:g}° upward release tangent",
                xy=(x[-1] + dx, z[-1] + dz), xytext=(104, 235),
                color="#a93313", fontsize=10.5, fontweight="bold",
                arrowprops={"arrowstyle": "-", "color": "#a93313", "lw": 0.8})
    legend["Ø73.66 mm POLLEN center path (illustrative)"] = Line2D(
        [0], [0], color="#ff7043", lw=2.4, ls=(0, (5, 3)))

    ax.axhline(0, color="#757575", lw=0.7, ls=":", zorder=1)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-155, 195)
    ax.set_ylim(-12, 283)
    ax.grid(color="#eceff1", lw=0.7, zorder=0)
    ax.set_xlabel("X relative to flywheel shaft (mm)")
    ax.set_ylabel("Z above turret deck (mm)")
    fig.text(0.09, 0.965, "BIOBUZZ shooter | actual Y = 0 mm BREP section",
             fontsize=15, fontweight="bold")
    fig.text(0.09, 0.922,
             "65° hood shown; dashed ball path is a geometric overlay, not a dynamic firing test",
             fontsize=9.5, color="#455a64")
    fig.legend(list(legend.values()), list(legend), loc="upper left",
               bbox_to_anchor=(0.72, 0.83), frameon=False, fontsize=9.5,
               title="Section key (Y = 0 mm)", title_fontsize=10.5)
    fig.text(0.72, 0.18,
             "The section is extracted from exported solids.\n"
             "Reference envelopes are dashed. Side plates\n"
             "outside Y = 0 mm are absent in this slice.\n"
             "Deck Z = 0 mm; field height needs +deck height.",
             fontsize=9.2, color="#546e7a", va="top")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=180, facecolor="white")
    plt.close(fig)
    print(f"Saved {args.output}; {count} BREP section curves from {len(parts)} parts")


if __name__ == "__main__":
    main()
