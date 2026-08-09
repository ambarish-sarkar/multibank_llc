#!/usr/bin/env python3
"""Generate bank-wise bit miss plots without touching plot_diffs.py.

For each cache design and each available bank count, this script writes one
PNG/PDF for the single-bank attack and one PNG/PDF for the simultaneous
attack. Bit 0 and bit 1 misses are drawn together in each plot, using color to
identify the bank and line style to identify the bit.
"""

from __future__ import annotations

import glob
import os
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np

from plot_diffs import _extract_meta, _parse_file


INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"

CACHE_ORDER = ("normal", "ceaser", "ceaser_s", "mirage", "scatter")
BANK_COUNTS = (2, 4, 8, 16)
RATIO = "0.5"
REGION0_RATIOS = ("0.3", "0.5", "1.0")
ATTACK_MODE = "simultaneous"


def _build_index(folder: str) -> Dict[Tuple[str, str, str, Optional[int], Optional[int]], str]:
    idx: Dict[Tuple[str, str, str, Optional[int], Optional[int]], str] = {}
    for path in glob.glob(os.path.join(folder, "outfile_v1_bit_*.txt")):
        meta = _extract_meta(path)
        if meta is None:
            continue
        bit, ratio, attack, num_banks, banks_to_attack = meta
        idx[(bit, ratio, attack, num_banks, banks_to_attack)] = path
    return idx


def _bank_labels(fmt: str, bank_count: int) -> List[str]:
    if fmt == "dual" and bank_count == 2:
        return ["region0", "region1"]
    return [f"bank{i}" for i in range(bank_count)]


def _bank_series(parsed: dict) -> List[np.ndarray]:
    if parsed["format"] == "dual":
        return [parsed["misses_r0"], parsed["misses_r1"]]
    if parsed["format"] == "multi":
        return parsed["misses"]
    if parsed["format"] == "single":
        return [parsed["misses"]]
    raise ValueError(f"Unsupported file format: {parsed['format']}")


def _panel_style(ax, ylabel: Optional[str] = None, xlabel: Optional[str] = None):
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8, linestyle="--", zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("bottom", "left"):
        ax.spines[spine].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK_SECONDARY, fontsize=10)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK_SECONDARY, fontsize=10)


def _plot_panel(ax, occ: np.ndarray, series0: List[np.ndarray], series1: List[np.ndarray],
                bank_labels: List[str], title: str, colors):
    for bank_idx, label in enumerate(bank_labels):
        color = colors[bank_idx % len(colors)]
        ax.plot(
            occ,
            series0[bank_idx],
            color=color,
            linestyle="-",
            marker="o",
            markersize=3.5,
            linewidth=1.8,
            label=label,
            zorder=3,
        )
        ax.plot(
            occ,
            series1[bank_idx],
            color=color,
            linestyle="--",
            marker="s",
            markersize=3.5,
            linewidth=1.8,
            label="_nolegend_",
            zorder=3,
        )

    ax.set_title(title, color=INK_PRIMARY, fontsize=11)
    y_max = max(
        max(float(np.max(series)) for series in series0),
        max(float(np.max(series)) for series in series1),
    )
    ax.set_ylim(bottom=0, top=y_max * 1.08 if y_max > 0 else 1)


def _save_attack_figure(cache: str, bank_count: int, attack_slug: str, attack_title: str,
                        occ: np.ndarray, series0: List[np.ndarray], series1: List[np.ndarray],
                        bank_labels: List[str], colors, out_dir: str):
    fig, ax = plt.subplots(1, 1, figsize=(8.0, 12.0), facecolor=SURFACE)
    _panel_style(ax, ylabel="Misses observed", xlabel="Cache occupancy (%)")
    _plot_panel(ax, occ, series0, series1, bank_labels, attack_title, colors)

    handles, labels = ax.get_legend_handles_labels()
    legend = fig.legend(
        handles,
        labels,
        loc="upper center",
        ncol=min(8, len(labels)),
        frameon=False,
        labelcolor=INK_SECONDARY,
        fontsize=9.0,
        bbox_to_anchor=(0.5, 0.955),
    )

    title = fig.suptitle(
        f"{cache} cache - {bank_count}-bank {attack_slug.replace('_', ' ')} (solid=bit0, dashed=bit1)",
        color=INK_PRIMARY,
        fontsize=13,
        fontweight="bold",
        y=0.988,
    )
    fig.tight_layout(rect=(0, 0.0, 1, 0.88))

    base = f"{cache}_{bank_count}bank_{attack_slug}_bit_misses_by_occupancy"
    png_path = os.path.join(out_dir, base + ".png")
    pdf_path = os.path.join(out_dir, base + ".pdf")
    fig.savefig(
        png_path,
        dpi=200,
        format="png",
        facecolor=SURFACE,
        bbox_inches="tight",
        bbox_extra_artists=(legend, title),
    )
    fig.savefig(
        pdf_path,
        dpi=1200,
        format="pdf",
        facecolor=SURFACE,
        bbox_inches="tight",
        bbox_extra_artists=(legend, title),
    )
    plt.close(fig)
    print(f"Saved occupancy figure: {png_path}")


def plot_bank_bit_misses(cache: str, base_dir: str = "results") -> None:
    folder = os.path.join(base_dir, cache)
    if not os.path.isdir(folder):
        print(f"[WARN] Folder not found: {folder}")
        return

    idx = _build_index(folder)
    out_dir = os.path.join(folder, "plots_bank_bit_misses")
    os.makedirs(out_dir, exist_ok=True)

    palette = plt.get_cmap("tab20")
    colors = [palette(i) for i in range(20)]

    for bank_count in BANK_COUNTS:
        key_multi_0 = ("0", RATIO, ATTACK_MODE, bank_count, bank_count)
        key_multi_1 = ("1", RATIO, ATTACK_MODE, bank_count, bank_count)
        if key_multi_0 in idx and key_multi_1 in idx:
            d_multi_0 = _parse_file(idx[key_multi_0])
            d_multi_1 = _parse_file(idx[key_multi_1])
            if d_multi_0["format"] == d_multi_1["format"]:
                occ_common = np.intersect1d(d_multi_0["occupancy"], d_multi_1["occupancy"])
                map_multi_0 = {int(o): i for i, o in enumerate(d_multi_0["occupancy"])}
                map_multi_1 = {int(o): i for i, o in enumerate(d_multi_1["occupancy"])}
                i_multi_0 = np.array([map_multi_0[int(o)] for o in occ_common], dtype=int)
                i_multi_1 = np.array([map_multi_1[int(o)] for o in occ_common], dtype=int)
                series_multi_0 = _bank_series(d_multi_0)
                series_multi_1 = _bank_series(d_multi_1)
                bank_labels_multi = _bank_labels(d_multi_0["format"], len(series_multi_0))

                _save_attack_figure(
                    cache,
                    bank_count,
                    "simultaneous_attack",
                    f"simultaneous attack on {bank_count} banks, ratio={RATIO}",
                    occ_common,
                    [s[i_multi_0] for s in series_multi_0],
                    [s[i_multi_1] for s in series_multi_1],
                    bank_labels_multi,
                    colors,
                    out_dir,
                )

        if bank_count == 2:
            single_specs = [
                (ratio, "region0", 2, f"region0_ratio_{ratio.replace('.', 'p')}", f"region0 attack on 2 banks, ratio={ratio}")
                for ratio in REGION0_RATIOS
            ]
        else:
            single_specs = [
                (RATIO, ATTACK_MODE, 1, "single_bank_attack", f"single-bank attack (1 of {bank_count} banks), ratio={RATIO}")
            ]

        for ratio, attack, banks_to_attack, slug, title in single_specs:
            key_single_0 = ("0", ratio, attack, bank_count, banks_to_attack)
            key_single_1 = ("1", ratio, attack, bank_count, banks_to_attack)
            if key_single_0 not in idx or key_single_1 not in idx:
                continue

            d_single_0 = _parse_file(idx[key_single_0])
            d_single_1 = _parse_file(idx[key_single_1])
            if d_single_0["format"] != d_single_1["format"]:
                print(f"[WARN] Format mismatch for {cache} bank_count={bank_count} ratio={ratio}; skipping.")
                continue

            occ_common = np.intersect1d(d_single_0["occupancy"], d_single_1["occupancy"])
            if occ_common.size == 0:
                print(f"[WARN] No overlapping occupancy for {cache} bank_count={bank_count} ratio={ratio}; skipping.")
                continue

            map_single_0 = {int(o): i for i, o in enumerate(d_single_0["occupancy"])}
            map_single_1 = {int(o): i for i, o in enumerate(d_single_1["occupancy"])}
            i_single_0 = np.array([map_single_0[int(o)] for o in occ_common], dtype=int)
            i_single_1 = np.array([map_single_1[int(o)] for o in occ_common], dtype=int)
            series_single_0 = _bank_series(d_single_0)
            series_single_1 = _bank_series(d_single_1)
            bank_labels_single = _bank_labels(d_single_0["format"], len(series_single_0))

            _save_attack_figure(
                cache,
                bank_count,
                slug,
                title,
                occ_common,
                [s[i_single_0] for s in series_single_0],
                [s[i_single_1] for s in series_single_1],
                bank_labels_single,
                colors,
                out_dir,
            )


if __name__ == "__main__":
    for cache in CACHE_ORDER:
        plot_bank_bit_misses(cache, base_dir="results")
