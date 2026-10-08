#!/usr/bin/env python3
"""
plot_thermo.py — Read stage_*.txt logs and produce thermo_summary.png

Usage:
    python plot_thermo.py [job_dir]
    # Default: current directory

Reads:
    stage_opt1.txt, stage_opt2.txt, stage_eq_md.txt, stage_prod_md.txt

Output:
    thermo_summary.png (6-panel plot)
"""
from __future__ import annotations
import sys
import os
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read_stage(path: str) -> dict[str, list] | None:
    """Read a stage_*.txt file. Returns dict of column lists, or None if missing/empty."""
    if not os.path.isfile(path):
        return None
    cols: dict[str, list] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not cols:
                # header line (skip leading comment-stripped header)
                # detect if first token is numeric
                try:
                    float(parts[0])
                except ValueError:
                    # this is the header row
                    for p in parts:
                        cols[p] = []
                    continue
            # data line
            if not cols:
                # no header found, use generic names
                ncols = len(parts)
                cols = {f"col{i}": [] for i in range(ncols)}
            keys = list(cols.keys())
            for i, p in enumerate(parts):
                if i < len(keys):
                    try:
                        cols[keys[i]].append(float(p))
                    except ValueError:
                        cols[keys[i]].append(p)
    if not cols:
        return None
    return {k: np.array(v) for k, v in cols.items()}


def find_col(data: dict, *candidates: str):
    """Find first matching column name from candidates."""
    for c in candidates:
        if c in data:
            return data[c]
    return None


def main():
    job_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    # Read all stages
    stages = {
        "OPT-1":  read_stage(os.path.join(job_dir, "stage_opt1.txt")),
        "OPT-2":  read_stage(os.path.join(job_dir, "stage_opt2.txt")),
        "Eq MD":  read_stage(os.path.join(job_dir, "stage_eq_md.txt")),
        "Prod MD": read_stage(os.path.join(job_dir, "stage_prod_md.txt")),
    }

    # Filter out None stages
    active = {name: data for name, data in stages.items() if data is not None}
    if not active:
        print("No stage_*.txt files found. Nothing to plot.")
        sys.exit(1)

    print(f"Found stages: {list(active.keys())}")

    # Build x-axis: cumulative step index per stage
    x_ranges = {}
    offset = 0
    boundaries = [0]
    for name, data in active.items():
        n = len(next(iter(data.values())))
        x = np.arange(offset, offset + n)
        x_ranges[name] = x
        offset += n
        boundaries.append(offset)
    total = offset

    # Detect which columns exist across all stages
    has_energy = any(find_col(d, "energy_eV") is not None for d in active.values())
    has_lattice = any(find_col(d, "a_A") is not None for d in active.values())
    has_vol = any(find_col(d, "vol_A3") is not None for d in active.values())
    has_press = any(find_col(d, "P_GPa") is not None for d in active.values())
    has_temp = any(find_col(d, "T_K") is not None for d in active.values())
    has_dens = any(find_col(d, "density_g_cm3") is not None for d in active.values())

    # Figure: 3 rows x 2 cols
    fig, axes = plt.subplots(3, 2, figsize=(14, 10))
    fig.suptitle("UMA Thermo Summary", fontsize=14, fontweight="bold")

    # Stage colors
    stage_colors = {"OPT-1": "#2196F3", "OPT-2": "#4CAF50", "Eq MD": "#FF9800", "Prod MD": "#E91E63"}

    def plot_stage(ax, name, data, col_candidates, ylabel, color, **kwargs):
        y = find_col(data, *col_candidates)
        if y is None:
            return
        x = x_ranges[name]
        # Normalize x to step-within-stage
        x_local = np.arange(len(y))
        ax.plot(x_local, y, "-", color=color, linewidth=0.8, label=name, **kwargs)

    # --- Panel 1: Energy ---
    ax = axes[0, 0]
    for name, data in active.items():
        plot_stage(ax, name, data, ("energy_eV",), "Energy (eV)", stage_colors[name])
    ax.set_ylabel("Energy (eV)")
    ax.set_title("Potential Energy")
    ax.legend(fontsize=8)

    # --- Panel 2: Lattice ---
    ax = axes[0, 1]
    for name, data in active.items():
        for elem, ls in [("a_A", "-"), ("b_A", "--"), ("c_A", ":")]:
            y = find_col(data, elem)
            if y is not None:
                x_local = np.arange(len(y))
                label = f"{name} {elem[0]}"
                ax.plot(x_local, y, ls, color=stage_colors[name], linewidth=0.8, label=label)
    ax.set_ylabel("Lattice (A)")
    ax.set_title("Lattice Constants a, b, c")
    ax.legend(fontsize=7, ncol=2)

    # --- Panel 3: Volume ---
    ax = axes[1, 0]
    for name, data in active.items():
        plot_stage(ax, name, data, ("vol_A3",), "Volume (A3)", stage_colors[name])
    ax.set_ylabel("Volume (A$^3$)")
    ax.set_title("Cell Volume")
    ax.legend(fontsize=8)

    # --- Panel 4: Pressure ---
    ax = axes[1, 1]
    for name, data in active.items():
        plot_stage(ax, name, data, ("P_GPa",), "Pressure (GPa)", stage_colors[name])
    ax.set_ylabel("Pressure (GPa)")
    ax.set_title("Hydrostatic Pressure")
    ax.axhline(0, color="gray", linewidth=0.5, linestyle="-")
    ax.legend(fontsize=8)

    # --- Panel 5: Temperature ---
    ax = axes[2, 0]
    for name, data in active.items():
        plot_stage(ax, name, data, ("T_K",), "Temperature (K)", stage_colors[name])
    ax.set_ylabel("Temperature (K)")
    ax.set_xlabel("Step (cumulative)")
    ax.set_title("Temperature")
    ax.legend(fontsize=8)

    # --- Panel 6: Density ---
    ax = axes[2, 1]
    for name, data in active.items():
        plot_stage(ax, name, data, ("density_g_cm3",), "Density (g/cm3)", stage_colors[name])
    ax.set_ylabel("Density (g/cm$^3$)")
    ax.set_xlabel("Step (cumulative)")
    ax.set_title("Density")
    ax.legend(fontsize=8)

    # Draw vertical stage boundaries on all panels
    for ax_row in axes:
        for ax in ax_row:
            for b in boundaries[1:-1]:
                ax.axvline(b, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)
            ax.tick_params(labelsize=8)

    # Add stage labels at bottom
    stage_names = list(active.keys())
    for i, name in enumerate(stage_names):
        mid = (boundaries[i] + boundaries[i + 1]) / 2
        axes[2, 0].text(mid, axes[2, 0].get_ylim()[0], name,
                        ha="center", va="top", fontsize=9, fontweight="bold",
                        color=stage_colors[name],
                        transform=axes[2, 0].get_xaxis_transform())

    fig.tight_layout(rect=[0, 0.02, 1, 0.96])

    out_path = os.path.join(job_dir, "thermo_summary.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
