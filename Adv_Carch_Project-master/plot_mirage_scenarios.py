"""Compare the 4 New (multi-bank) Mirage attack scenarios against each other:
  - region0 @ 100/0, 50/50, 30/70 split (single-region attack, held-out ratio varies)
  - simultaneous @ 50/50 split (both banks attacked at once)

All four share the same occupancy grid (target_occupancy_percentages, 10
levels) and 100 trials/level, so they're directly comparable -- no Old data
involved here.

Two figures:
  1. mirage_scenarios_misses_vs_occupancy  -- raw misses per bit, 2 panels
  2. mirage_scenarios_delta_signal         -- Delta-misses (bit1-bit0), the
     covert-channel signal strength, paired per-trial (same trial index used
     for bit0 and bit1, since common.py's get_trial_addresses reuses the same
     receiver addresses across both bits within a trial).
"""
import ast
import os
from collections import OrderedDict

import matplotlib.pyplot as plt
import numpy as np

NEW_DIR = "results/mirage"
OUT_DIR = os.path.join(NEW_DIR, "plots_scenario_comparison")

INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"

# Ordinal blue ramp (references/palette.md) for region0 split ratio, light->dark
# as more of the cache is dedicated to region0; simultaneous gets its own hue
# (categorical slot 2, orange) since it isn't a point on that ordinal axis.
SCENARIOS = [
    dict(ratio="0.3", attack="region0", label="region0 (30/70 split)",
         color="#86b6ef", marker="o", linestyle="-"),
    dict(ratio="0.5", attack="region0", label="region0 (50/50 split)",
         color="#5598e7", marker="o", linestyle="-"),
    dict(ratio="1.0", attack="region0", label="region0 (100/0 split)",
         color="#2a78d6", marker="o", linestyle="-"),
    dict(ratio="0.5", attack="simultaneous", label="simultaneous (50/50 split, avg. both banks)",
         color="#eb6834", marker="s", linestyle="--"),
]

OCCUPANCIES = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40]


def load_raw(path):
    """occ -> list of per-trial tuples (misses columns), in trial order."""
    raw = OrderedDict()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = ast.literal_eval(line)
            occ = row[0]
            misses = tuple(row[2:])
            raw.setdefault(occ, []).append(misses)
    return raw


def representative_series(raw):
    """mean/std per occupancy of the representative signal (single col as-is,
    dual col averaged per trial across the two banks)."""
    means, stds = [], []
    for occ in OCCUPANCIES:
        trials = raw[occ]
        vals = [sum(t) / len(t) for t in trials]  # avg over columns per trial
        means.append(np.mean(vals))
        stds.append(np.std(vals))
    return np.array(means), np.array(stds)


def paired_delta_series(raw0, raw1):
    """mean/std per occupancy of the paired per-trial delta (bit1 - bit0),
    averaged over columns (banks) per trial first."""
    means, stds = [], []
    for occ in OCCUPANCIES:
        t0 = raw0[occ]
        t1 = raw1[occ]
        deltas = [
            (sum(b) / len(b)) - (sum(a) / len(a))
            for a, b in zip(t0, t1)
        ]
        means.append(np.mean(deltas))
        stds.append(np.std(deltas))
    return np.array(means), np.array(stds)


def style_axis(ax, ylabel):
    ax.set_facecolor(SURFACE)
    x = np.arange(len(OCCUPANCIES))
    ax.set_xticks(x)
    ax.set_xticklabels([str(o) for o in OCCUPANCIES], color=INK_SECONDARY, fontsize=9)
    ax.set_xlabel("Target cache occupancy (%)", color=INK_SECONDARY, fontsize=10)
    ax.set_ylabel(ylabel, color=INK_SECONDARY, fontsize=10)
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8, linestyle="--", zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED)
    return x


def add_header(fig, plot_height, title, subtitle, n_series):
    legend_rows = (n_series + 1) // 2
    header_in = 0.55 + 0.30 + 0.30 * legend_rows + 0.15  # title + subtitle + legend rows + pad
    fig_height = plot_height + header_in
    title_y = 1.0 - (0.10 / fig_height)
    subtitle_y = 1.0 - (0.45 / fig_height)
    legend_y = 1.0 - (0.75 / fig_height)
    top_rect = plot_height / fig_height
    suptitle = fig.suptitle(title, color=INK_PRIMARY, fontsize=13,
                             fontweight="bold", y=title_y, va="top")
    subtitle_txt = fig.text(0.5, subtitle_y, subtitle, ha="center", va="top",
                             color=INK_SECONDARY, fontsize=9.5)
    return fig_height, title_y, subtitle_y, legend_y, top_rect, suptitle, subtitle_txt


def figure_misses():
    data0 = {}
    data1 = {}
    for s in SCENARIOS:
        base = f"outfile_v1_bit_{{}}_{s['ratio']}_{s['attack']}_banks2_attack2.txt"
        raw0 = load_raw(os.path.join(NEW_DIR, base.format(0)))
        raw1 = load_raw(os.path.join(NEW_DIR, base.format(1)))
        data0[s["label"]] = representative_series(raw0)
        data1[s["label"]] = representative_series(raw1)

    plot_height = 4.4
    fig, axes = plt.subplots(1, 2, figsize=(12.5, plot_height), facecolor=SURFACE)

    for ax, data, bit in ((axes[0], data0, "0"), (axes[1], data1, "1")):
        x = style_axis(ax, "Misses observed")
        for s in SCENARIOS:
            mean, std = data[s["label"]]
            ax.plot(x, mean, color=s["color"], linestyle=s["linestyle"],
                     marker=s["marker"], markersize=6, linewidth=2.0,
                     label=s["label"], zorder=3)
            ax.fill_between(x, mean - std, mean + std, color=s["color"],
                             alpha=0.15, linewidth=0, zorder=2)
        ax.set_title(f"bit '{bit}'", color=INK_PRIMARY, fontsize=11)
        ax.relim(); ax.autoscale_view()
        _, y1 = ax.get_ylim()
        ax.set_ylim(0, y1)

    fig_height, *_ , top_rect, suptitle, subtitle_txt = add_header(
        fig, plot_height,
        "Mirage cache — New simulator: attack scenario comparison",
        "Misses vs. target occupancy — 100-trial mean, shaded band = ±1σ",
        len(SCENARIOS))
    handles, labels = axes[0].get_legend_handles_labels()
    legend_y = 1.0 - (0.75 / fig_height)
    legend = fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False,
                         labelcolor=INK_SECONDARY, fontsize=9.5,
                         bbox_to_anchor=(0.5, legend_y))
    fig.tight_layout(rect=(0, 0.0, 1, top_rect))

    base = "mirage_scenarios_misses_vs_occupancy"
    _save(fig, base, (legend, suptitle, subtitle_txt))


def figure_delta():
    deltas = {}
    for s in SCENARIOS:
        base = f"outfile_v1_bit_{{}}_{s['ratio']}_{s['attack']}_banks2_attack2.txt"
        raw0 = load_raw(os.path.join(NEW_DIR, base.format(0)))
        raw1 = load_raw(os.path.join(NEW_DIR, base.format(1)))
        deltas[s["label"]] = paired_delta_series(raw0, raw1)

    plot_height = 4.6
    fig, ax = plt.subplots(1, 1, figsize=(8, plot_height), facecolor=SURFACE)
    x = style_axis(ax, "Δ misses (bit '1' − bit '0')")
    for s in SCENARIOS:
        mean, std = deltas[s["label"]]
        ax.plot(x, mean, color=s["color"], linestyle=s["linestyle"],
                 marker=s["marker"], markersize=6, linewidth=2.0,
                 label=s["label"], zorder=3)
        ax.fill_between(x, mean - std, mean + std, color=s["color"],
                         alpha=0.15, linewidth=0, zorder=2)
    ax.axhline(0, color=INK_MUTED, linewidth=1.0, zorder=1)
    ax.relim(); ax.autoscale_view()
    y0, y1 = ax.get_ylim()
    pad = 0.05 * (y1 - y0)
    ax.set_ylim(y0 - pad, y1 + pad)

    fig_height, *_ , top_rect, suptitle, subtitle_txt = add_header(
        fig, plot_height,
        "Mirage cache — covert-channel signal strength by scenario",
        "Paired per-trial Δmisses (bit1 − bit0) — larger |Δ| = more distinguishable bits",
        len(SCENARIOS))
    legend_y = 1.0 - (0.75 / fig_height)
    legend = fig.legend(*ax.get_legend_handles_labels(), loc="upper center", ncol=2,
                         frameon=False, labelcolor=INK_SECONDARY, fontsize=9.5,
                         bbox_to_anchor=(0.5, legend_y))
    fig.tight_layout(rect=(0, 0.0, 1, top_rect))

    base = "mirage_scenarios_delta_signal"
    _save(fig, base, (legend, suptitle, subtitle_txt))


def _save(fig, base, extra_artists):
    pdf_path = os.path.join(OUT_DIR, base + ".pdf")
    png_path = os.path.join(OUT_DIR, base + ".png")
    fig.savefig(pdf_path, dpi=1200, format="pdf", facecolor=SURFACE,
                bbox_extra_artists=extra_artists, bbox_inches="tight")
    fig.savefig(png_path, dpi=200, format="png", facecolor=SURFACE,
                bbox_extra_artists=extra_artists, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {pdf_path}")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    figure_misses()
    figure_delta()
