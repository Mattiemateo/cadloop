"""Render the provisional 65-degree study as PNG/SVG using the flight model.

Run in the restricted test Docker image, which already supplies matplotlib.
Each Cd scenario receives its own center-aimed launch speed. No measured drag,
traction efficiency, scoring probability, or basket-interior clearance is implied.
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Circle

from trajectory import (COS_TILT, MOUTH_HEIGHT_M, SIN_TILT, Shooter,
                        aimed_speed, aperture_clearance, flight, mouth_coordinates)


def plot(output_dir):
    shooter = Shooter(deck_m=0.180, efficiency=1)
    angle = 65
    ranges, cds = (1.5, 2.0, 2.5), (0, 0.5, 1.0)
    colors = ("#246D9B", "#C96B2B", "#75609B")
    styles = ("-", (0, (5, 3)), (0, (1, 2)))
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.labelcolor": "#273544", "text.color": "#273544",
                         "svg.fonttype": "none", "savefig.facecolor": "white"})
    fig, (ax, panel) = plt.subplots(1, 2, figsize=(13.5, 8),
                                   gridspec_kw={"width_ratios": (1.6, 1)})
    fig.subplots_adjust(left=0.065, right=0.965, top=0.85, bottom=0.18, wspace=0.16)
    fig.suptitle("BIOBUZZ · 65° hood trajectory study", y=0.965, fontsize=21, fontweight="bold")
    fig.text(0.5, 0.913, "180 mm deck  ·  73.66 mm ball  ·  100 mm tire  ·  assumed ball mass 25 g",
             ha="center", fontsize=11, color="#526170")
    results = []
    for distance, color in zip(ranges, colors):
        for cd, style in zip(cds, styles):
            speed = aimed_speed(shooter, angle, distance, cd)
            rows = flight(shooter, angle, speed, distance + 0.55, cd)
            check = aperture_clearance(rows, distance, shooter.lip_height_m,
                                       shooter.ball_diameter_m / 2)
            visible = []
            for row in rows:
                visible.append(row)
                if mouth_coordinates(row, distance, shooter.lip_height_m)[0] < -shooter.ball_diameter_m / 2:
                    break
            ax.plot([row[0] for row in visible], [row[1] for row in visible],
                    color=color, linestyle=style, linewidth=1.7)
            results.append({"range_m": distance, "cd": cd, "speed_m_s": speed,
                            "wheel_rpm_k1": shooter.rpm(speed), **check})
        x1 = distance + MOUTH_HEIGHT_M * SIN_TILT
        z1 = shooter.lip_height_m + MOUTH_HEIGHT_M * COS_TILT
        ax.plot((distance, x1), (shooter.lip_height_m, z1), color=color, linewidth=5, alpha=0.32)
        ax.add_patch(Circle(((distance + x1) / 2, (shooter.lip_height_m + z1) / 2),
                            shooter.ball_diameter_m / 2, fill=False, edgecolor=color, linewidth=1.2))

    x0, z0, _, _ = shooter.release(angle)
    ax.scatter([x0], [z0], s=30, color="#273544", zorder=5)
    ax.annotate(f"Release: {z0:.3f} m", (x0, z0), (0.23, 0.13), fontsize=9,
                arrowprops={"arrowstyle": "-", "color": "#687887"})
    ax.text(2.66, 1.13, "Tilted opening\nplanes only", ha="right", fontsize=9, color="#526170")
    ax.set(xlabel="Forward distance from wheel shaft (m)", ylabel="Ball-center height above tiles (m)",
           xlim=(-0.04, 2.83), ylim=(0, 2.58))
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color="#DDE3E9", linewidth=0.65)
    ax.spines[["top", "right"]].set_visible(False)
    distance_legend = ax.legend([Line2D([], [], color=color, lw=2) for color in colors],
                                [f"{distance:.1f} m" for distance in ranges],
                                title="Lower-lip range from wheel shaft", loc="upper left",
                                ncol=3, frameon=False, fontsize=9, title_fontsize=9)
    ax.add_artist(distance_legend)
    ax.legend([Line2D([], [], color="#526170", linestyle=style, lw=1.7) for style in styles],
              [f"Cd={cd:g}" for cd in cds], title="Drag assumptions; speed adjusted for each",
              loc="lower right", ncol=3, frameon=False, fontsize=9, title_fontsize=9)

    def table(data, columns, bounds):
        item = panel.table(cellText=data, colLabels=columns, cellLoc="center", bbox=bounds)
        item.auto_set_font_size(False)
        item.set_fontsize(10)
        for (row, column), cell in item.get_celld().items():
            cell.set_edgecolor("#CFD8E0")
            cell.set_linewidth(0.65)
            if row == 0:
                cell.set_facecolor("#EAF0F4")
                cell.set_text_props(weight="bold")
            elif column == 0:
                cell.set_text_props(color=colors[row - 1], weight="bold")
        return item

    panel.axis("off")
    panel.text(0, 0.98, "Required wheel speed", fontsize=15, weight="bold")
    panel.text(0, 0.92, "RPM at ideal transfer efficiency k = 1", fontsize=10)
    rpm_rows = []
    aperture_rows = []
    for distance in ranges:
        group = [item for item in results if item["range_m"] == distance]
        rpm_rows.append([f"{distance:.1f} m"] + [f"{item['wheel_rpm_k1']:,.0f}" for item in group])
        entry = [item["entry_angle_deg"] for item in group]
        aperture_rows.append([f"{distance:.1f} m",
                              f"{min(item['swept_sphere_clearance_lower_bound_mm'] for item in group):.1f} mm",
                              f"{min(entry):.0f} to {max(entry):.0f}°"])
    table(rpm_rows, ["Range", "Cd = 0", "Cd = 0.5", "Cd = 1"], (0, 0.61, 1, 0.25))
    panel.text(0, 0.535, "Actual RPM = table ÷ measured k", fontsize=11, weight="bold")
    panel.text(0, 0.472,
               f"Example: k = 0.8, 2.5 m, Cd = 1 → {results[-1]['wheel_rpm_k1'] / 0.8:,.0f} RPM",
               fontsize=9.5)
    panel.text(0, 0.36, "Whole-ball aperture check", fontsize=12, weight="bold")
    table(aperture_rows, ["Range", "Min. clearance", "Entry angle"], (0, 0.115, 1, 0.21))
    panel.text(0, 0.045, "Minimum over the three separately tuned drag scenarios.\n"
               "Clearance checks the swept sphere against the gable plane.", fontsize=9, color="#526170")
    fig.text(0.5, 0.086, "SIMULATION — NOT SHOT VALIDATION", ha="center", fontsize=11, weight="bold")
    fig.text(0.5, 0.043,
             "Cd is unmeasured; ±5% launch-speed variation can hit the rim. "
             "The model excludes rim thickness, basket interior, wind and Magnus lift.",
             ha="center", fontsize=9.5, color="#526170")
    output_dir.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        fig.savefig(output_dir / f"trajectory.{extension}", dpi=200)
    plt.close(fig)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("work/biobuzz"))
    args = parser.parse_args()
    results = plot(args.output_dir)
    print(json.dumps({"outputs": [str(args.output_dir / f"trajectory.{ext}") for ext in ("png", "svg")],
                      "case_count": len(results),
                      "minimum_aperture_clearance_mm": min(item["swept_sphere_clearance_lower_bound_mm"] for item in results),
                      "nominal_cases_clear_and_descending": all(item["aperture_plane_clear"] and item["descending_entry"] for item in results)}, indent=2))
