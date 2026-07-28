"""Old vs New comparison for the Mirage cache occupancy covert channel.

Old = ~/IITH/Thesis/randomized_caches/llc_simulator/Mirage_cache_occupancy
      (the original, single-bank simulator; 100 trials per receiver-access
      level; outfile_v100_for_{0,1}.txt, format [receiver_accesses, misses]).

New = this repo's multi-bank simulator, num_banks=2, region0 attack @ 100/0
      split (ratio=1.0) -- the closest match to Old's "attack the whole
      cache, no held-out region" scenario. 100 trials per occupancy level;
      results/mirage/outfile_v1_bit_{0,1}_1.0_region0_banks2_attack2.txt,
      format [occupancy_pct, receiver_accesses, misses].

Both configs resolve to the SAME total cache capacity (131072 data blocks --
Old: (8388608//32)//2, New: 8388608//(8*8) -- coincidentally identical block
size of 64 bytes), so occupancy percentage is a valid, directly comparable
x-axis across the two, even though Old only records raw receiver-access
counts rather than a percentage.
"""
import ast
import os

import matplotlib.pyplot as plt
import numpy as np

OLD_DIR = "/home/ambarish-sarkar/IITH/Thesis/randomized_caches/llc_simulator/Mirage_cache_occupancy"
NEW_DIR = "results/mirage"
OUT_DIR = os.path.join(NEW_DIR, "plots_old_vs_new")

OLD_TOTAL_CACHE_LINES = (8388608 // 32) // 2   # old simulator.py: run_simulation()
NEW_TOTAL_CACHE_LINES = 131072                  # printed by current main.py at runtime
assert OLD_TOTAL_CACHE_LINES == NEW_TOTAL_CACHE_LINES == 131072

COLOR_OLD = "#eb6834"   # validated categorical slot 2, orange
COLOR_NEW = "#2a78d6"   # validated categorical slot 1, blue
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"


def parse_old(path):
    """[receiver_accesses, misses] x 1100 rows -> (occ_pct[11], mean[11], std[11])."""
    by_count = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count, misses = ast.literal_eval(line)
            by_count.setdefault(count, []).append(misses)
    counts = sorted(by_count)
    occ_pct = np.array([c / OLD_TOTAL_CACHE_LINES * 100 for c in counts])
    mean = np.array([np.mean(by_count[c]) for c in counts])
    std = np.array([np.std(by_count[c]) for c in counts])
    return occ_pct, mean, std


def parse_new(path):
    """[occ_pct, receiver_accesses, misses] x 1000 rows -> (occ_pct[10], mean[10], std[10])."""
    by_occ = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            occ, _acc, misses = ast.literal_eval(line)
            by_occ.setdefault(occ, []).append(misses)
    occs = sorted(by_occ)
    occ_pct = np.array([float(o) for o in occs])
    mean = np.array([np.mean(by_occ[o]) for o in occs])
    std = np.array([np.std(by_occ[o]) for o in occs])
    return occ_pct, mean, std


def style_axis(ax):
    ax.set_facecolor(SURFACE)
    ax.set_xlabel("Cache occupancy (%)", color=INK_SECONDARY, fontsize=10)
    ax.set_ylabel("Misses observed", color=INK_SECONDARY, fontsize=10)
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8, linestyle="--", zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED)


def plot_panel(ax, old_x, old_mean, old_std, new_x, new_mean, new_std, subtitle):
    style_axis(ax)
    ax.errorbar(old_x, old_mean, yerr=old_std, color=COLOR_OLD, linestyle="--",
                marker="s", markersize=6, linewidth=1.8, capsize=3,
                label="Old (llc_simulator, single-bank, 100-trial mean ± σ)", zorder=3)
    ax.plot(new_x, new_mean, color=COLOR_NEW, linestyle="-", marker="o",
             markersize=6, linewidth=2.0,
             label="New (multi-bank, region0 @ 100/0 split, 100-trial mean)", zorder=3)
    ax.fill_between(new_x, new_mean - new_std, new_mean + new_std,
                     color=COLOR_NEW, alpha=0.18, linewidth=0, zorder=2,
                     label="New: ±1σ across trials")
    ax.set_title(subtitle, color=INK_PRIMARY, fontsize=11)

    ax.relim()
    ax.autoscale_view()
    _, x1 = ax.get_xlim()
    _, y1 = ax.get_ylim()
    ax.set_xlim(0, x1)
    ax.set_ylim(0, y1)


def make_figure():
    old_x0, old_mean0, old_std0 = parse_old(os.path.join(OLD_DIR, "outfile_v100_for_0.txt"))
    old_x1, old_mean1, old_std1 = parse_old(os.path.join(OLD_DIR, "outfile_v100_for_1.txt"))
    new_x0, new_mean0, new_std0 = parse_new(
        os.path.join(NEW_DIR, "outfile_v1_bit_0_1.0_region0_banks2_attack2.txt"))
    new_x1, new_mean1, new_std1 = parse_new(
        os.path.join(NEW_DIR, "outfile_v1_bit_1_1.0_region0_banks2_attack2.txt"))

    plot_height = 4.4
    header_in = 1.15
    fig_height = plot_height + header_in
    fig, axes = plt.subplots(1, 2, figsize=(12, fig_height), facecolor=SURFACE)

    plot_panel(axes[0], old_x0, old_mean0, old_std0, new_x0, new_mean0, new_std0, "bit '0'")
    plot_panel(axes[1], old_x1, old_mean1, old_std1, new_x1, new_mean1, new_std1, "bit '1'")

    title_y = 1.0 - (0.38 / fig_height)
    subtitle_y = 1.0 - (0.68 / fig_height)
    legend_y = 1.0 - (1.05 / fig_height)
    top_rect = plot_height / fig_height

    handles, labels = axes[0].get_legend_handles_labels()
    legend = fig.legend(handles, labels, loc="upper center", ncol=1, frameon=False,
                         labelcolor=INK_SECONDARY, fontsize=9.5,
                         bbox_to_anchor=(0.5, legend_y))

    suptitle = fig.suptitle("Mirage cache — Old (llc_simulator) vs New (multi-bank simulator)",
                             color=INK_PRIMARY, fontsize=13, fontweight="bold", y=title_y)
    subtitle_txt = fig.text(0.5, subtitle_y,
                             "Same 131,072-line cache capacity in both — occupancy % is directly comparable",
                             ha="center", color=INK_SECONDARY, fontsize=9.5)
    fig.tight_layout(rect=(0, 0.0, 1, top_rect))

    base = "mirage_oldvsnew_llc_simulator_vs_multibank"
    pdf_path = os.path.join(OUT_DIR, base + ".pdf")
    png_path = os.path.join(OUT_DIR, base + ".png")
    extra_artists = (legend, suptitle, subtitle_txt)
    fig.savefig(pdf_path, dpi=1200, format="pdf", facecolor=SURFACE,
                bbox_extra_artists=extra_artists, bbox_inches="tight")
    fig.savefig(png_path, dpi=200, format="png", facecolor=SURFACE,
                bbox_extra_artists=extra_artists, bbox_inches="tight")
    plt.close(fig)
    print(f"[OK] {pdf_path}")
    return png_path


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    make_figure()
