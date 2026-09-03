#!/usr/bin/env python3
"""
plot_bit_divergence.py

Creates bit-0 vs bit-1 receiver-miss divergence plots for every cache design,
scenario, and individual physical bank.

Expected repository layout:
    results/
      normal/
      ceaser/
      ceaser_s/
      scatter/
      mirage/

Output per design:
    results/<design>/plots_bit_divergence/
      1_bank/
      2_banks/
      4_banks/
      ... discovered automatically
      <design>_bit_divergence_summary.png
      <design>_bit_divergence_summary.csv

The x-axis is cache occupancy (%), not absolute receiver accesses.
Each individual plot shows mean receiver misses for bit 0 and bit 1 with
95% confidence intervals over the trials.
"""

import argparse
import ast
import csv
import glob
import math
import os
import re
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Safe for SSH/headless servers
import matplotlib.pyplot as plt


DEFAULT_CACHES = ("normal", "ceaser", "ceaser_s", "mirage", "scatter")


def parse_meta(path):
    """
    Returns a scenario dictionary.

    Supported filenames:
      outfile_v1_bit_0_multibank_banks1_banks_0_regions_0.txt
      outfile_v1_bit_0_hybrid2_banks2_banks_0-1_regions_1.txt
      outfile_v1_bit_0_region4_banks4_banks_0-1-2-3_regions_0-1-2-3.txt
      outfile_v1_bit_0_0.5_simultaneous.txt
      outfile_v1_bit_0_0.5_simultaneous_banks2_banks_0.txt
      outfile_v1_bit_0_0.5_simultaneous_banks2_banks_0-1.txt
      outfile_v1_bit_0_0.5_simultaneous_banks4_banks_0-1-2-3.txt

    Legacy banksN_attackM names are also accepted.
    """
    base = os.path.basename(path)
    current = re.match(
        r"outfile_v1_bit_(0|1)_(multibank|hybrid2|region4)_"
        r"banks(\d+)_banks_([0-9]+(?:-[0-9]+)*)_regions_([0-9]+(?:-[0-9]+)*)\.txt$",
        base,
    )
    if current:
        return {
            "bit": int(current.group(1)),
            "ratio": current.group(2),
            "attack": current.group(2),
            "num_banks": int(current.group(3)),
            "target_banks": tuple(int(x) for x in current.group(4).split("-")),
            "target_regions": tuple(int(x) for x in current.group(5).split("-")),
            "legacy_attack_count": None,
        }

    m = re.match(r"outfile_v1_bit_(0|1)_([^_]+)_(.+)\.txt$", base)
    if not m:
        return None

    bit = int(m.group(1))
    ratio = m.group(2)
    attack_part = m.group(3)

    new_m = re.search(r"_banks(\d+)_banks_([0-9]+(?:-[0-9]+)*)$", attack_part)
    if new_m:
        num_banks = int(new_m.group(1))
        target_banks = tuple(int(x) for x in new_m.group(2).split("-"))
        attack = attack_part[:new_m.start()]
        return {
            "bit": bit,
            "ratio": ratio,
            "attack": attack,
            "num_banks": num_banks,
            "target_banks": target_banks,
            "legacy_attack_count": None,
        }

    old_m = re.search(r"_banks(\d+)_attack(\d+)$", attack_part)
    if old_m:
        num_banks = int(old_m.group(1))
        attack_count = int(old_m.group(2))
        attack = attack_part[:old_m.start()]
        # Legacy behavior attacked the first N banks.
        target_banks = tuple(range(attack_count))
        return {
            "bit": bit,
            "ratio": ratio,
            "attack": attack,
            "num_banks": num_banks,
            "target_banks": target_banks,
            "legacy_attack_count": attack_count,
        }

    # No bank suffix = the original one-bank experiment.
    return {
        "bit": bit,
        "ratio": ratio,
        "attack": attack_part,
        "num_banks": 1,
        "target_banks": (0,),
        "legacy_attack_count": None,
    }


def scenario_key(meta):
    return (
        meta["ratio"],
        meta["attack"],
        meta["num_banks"],
        meta["target_banks"],
        meta["legacy_attack_count"],
    )


def scenario_tag(meta):
    targets = "-".join(str(x) for x in meta["target_banks"])
    return f"banks{meta['num_banks']}_targets_{targets}"


def bank_folder_name(num_banks):
    return f"{num_banks}_bank" if num_banks == 1 else f"{num_banks}_banks"


def parse_raw_file(path):
    """
    Returns raw trial rows:
      occupancy: (N,)
      accesses:  (N,)
      misses:    (N, K)

    K is the number of attacked-bank miss columns.
    """
    occ = []
    accesses = []
    misses = []
    expected_cols = None

    with open(path, "r") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                row = ast.literal_eval(line)
            except Exception as exc:
                raise ValueError(f"{path}:{line_no}: cannot parse row: {exc}") from exc

            if not isinstance(row, (list, tuple)) or len(row) < 3:
                raise ValueError(f"{path}:{line_no}: expected [occupancy, accesses, misses...]")

            row_misses = row[2:]
            if expected_cols is None:
                expected_cols = len(row_misses)
            elif len(row_misses) != expected_cols:
                raise ValueError(
                    f"{path}:{line_no}: inconsistent miss-column count "
                    f"{len(row_misses)} != {expected_cols}"
                )

            occ.append(int(row[0]))
            accesses.append(int(row[1]))
            misses.append([float(x) for x in row_misses])

    if not occ:
        raise ValueError(f"No valid rows in {path}")

    return {
        "occupancy": np.asarray(occ, dtype=int),
        "accesses": np.asarray(accesses, dtype=float),
        "misses": np.asarray(misses, dtype=float),
    }


def ci95(values):
    values = np.asarray(values, dtype=float)
    if values.size <= 1:
        return 0.0
    return 1.96 * values.std(ddof=1) / math.sqrt(values.size)


def grouped_stats(data, col):
    result = {}
    for occ in sorted(np.unique(data["occupancy"])):
        mask = data["occupancy"] == occ
        vals = data["misses"][mask, col]
        result[int(occ)] = {
            "mean": float(vals.mean()),
            "ci95": float(ci95(vals)),
            "n": int(vals.size),
        }
    return result


def align_pair(d0, d1):
    if d0["misses"].shape[1] != d1["misses"].shape[1]:
        raise ValueError("bit-0 / bit-1 miss-column count differs")

    occ0 = set(int(x) for x in np.unique(d0["occupancy"]))
    occ1 = set(int(x) for x in np.unique(d1["occupancy"]))
    common = sorted(occ0 & occ1)
    if not common:
        raise ValueError("no common occupancy values")

    for occ in common:
        n0 = int(np.sum(d0["occupancy"] == occ))
        n1 = int(np.sum(d1["occupancy"] == occ))
        if n0 != n1:
            print(
                f"[WARN] occupancy {occ}% has {n0} bit-0 rows and {n1} bit-1 rows; "
                "means/CI are still valid, but pairing is not exact."
            )
    return common


def bank_labels(meta, num_cols):
    targets = meta["target_banks"]
    regions = meta.get("target_regions", (0,))
    pairs = [(bank, region) for bank in targets for region in regions]
    if len(pairs) == num_cols:
        return [f"Bank {b} Region {r}" for b, r in pairs], pairs
    if len(targets) == num_cols:
        return [f"Bank {b}" for b in targets], list(targets)
    return [f"Bank {i}" for i in range(num_cols)], list(range(num_cols))


def draw_divergence(ax, occupancy, mean0, ci0, mean1, ci1, title):
    occupancy = np.asarray(occupancy, dtype=float)
    mean0 = np.asarray(mean0, dtype=float)
    mean1 = np.asarray(mean1, dtype=float)
    ci0 = np.asarray(ci0, dtype=float)
    ci1 = np.asarray(ci1, dtype=float)

    ax.plot(occupancy, mean0, marker="o", label="Bit 0")
    ax.fill_between(occupancy, mean0 - ci0, mean0 + ci0, alpha=0.18)

    ax.plot(occupancy, mean1, marker="o", label="Bit 1")
    ax.fill_between(occupancy, mean1 - ci1, mean1 + ci1, alpha=0.18)

    ax.set_xlabel("Cache occupancy (%)")
    ax.set_ylabel("Receiver cache misses")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)
    ax.legend()


def collect_pairs(folder):
    idx0 = {}
    idx1 = {}

    for path in glob.glob(os.path.join(folder, "outfile_v1_bit_0_*.txt")):
        meta = parse_meta(path)
        if meta:
            idx0[scenario_key(meta)] = (path, meta)

    for path in glob.glob(os.path.join(folder, "outfile_v1_bit_1_*.txt")):
        meta = parse_meta(path)
        if meta:
            idx1[scenario_key(meta)] = (path, meta)

    keys = sorted(
        set(idx0) & set(idx1),
        key=lambda k: (k[2], len(k[3]), k[3], k[0], k[1]),
    )

    return [(idx0[k][0], idx1[k][0], idx0[k][1]) for k in keys]


def plot_cache(cache, base_dir):
    folder = os.path.join(base_dir, cache)
    if not os.path.isdir(folder):
        print(f"[WARN] missing cache folder: {folder}")
        return

    pairs = collect_pairs(folder)
    if not pairs:
        print(f"[WARN] no bit-0/bit-1 pairs for {cache}")
        return

    out_root = os.path.join(folder, "plots_bit_divergence")
    os.makedirs(out_root, exist_ok=True)

    summary_panels = []
    csv_rows = []

    for p0, p1, meta in pairs:
        d0 = parse_raw_file(p0)
        d1 = parse_raw_file(p1)
        common_occ = align_pair(d0, d1)

        num_cols = d0["misses"].shape[1]
        labels, bank_ids = bank_labels(meta, num_cols)

        bank_dir = os.path.join(out_root, bank_folder_name(meta["num_banks"]))
        os.makedirs(bank_dir, exist_ok=True)

        for col in range(num_cols):
            s0 = grouped_stats(d0, col)
            s1 = grouped_stats(d1, col)

            occupancy = [o for o in common_occ if o in s0 and o in s1]
            mean0 = [s0[o]["mean"] for o in occupancy]
            ci0 = [s0[o]["ci95"] for o in occupancy]
            mean1 = [s1[o]["mean"] for o in occupancy]
            ci1 = [s1[o]["ci95"] for o in occupancy]

            bank_id = bank_ids[col]
            targets_text = ",".join(str(x) for x in meta["target_banks"])
            title = (
                f"{cache} | {meta['num_banks']}-bank setup | "
                f"targets [{targets_text}] | Bank {bank_id}"
            )

            fig, ax = plt.subplots(figsize=(9, 5.5))
            draw_divergence(ax, occupancy, mean0, ci0, mean1, ci1, title)
            fig.tight_layout()

            fname = (
                f"{cache}_{scenario_tag(meta)}_bank{bank_id}_bit_divergence.png"
            )
            path = os.path.join(bank_dir, fname)
            fig.savefig(path, dpi=180)
            plt.close(fig)

            summary_panels.append(
                {
                    "meta": meta,
                    "bank_id": bank_id,
                    "occupancy": occupancy,
                    "mean0": mean0,
                    "ci0": ci0,
                    "mean1": mean1,
                    "ci1": ci1,
                    "title": (
                        f"{meta['num_banks']} bank(s), targets [{targets_text}], "
                        f"Bank {bank_id}"
                    ),
                }
            )

            for i, occ in enumerate(occupancy):
                csv_rows.append(
                    {
                        "cache": cache,
                        "num_banks": meta["num_banks"],
                        "target_banks": targets_text,
                        "bank": bank_id,
                        "occupancy_pct": occ,
                        "bit0_mean_misses": mean0[i],
                        "bit0_ci95": ci0[i],
                        "bit1_mean_misses": mean1[i],
                        "bit1_ci95": ci1[i],
                        "raw_delta_of_means": mean1[i] - mean0[i],
                    }
                )

            print(f"[SAVED] {path}")

    # One dashboard-style summary image per design.
    if summary_panels:
        n = len(summary_panels)
        ncols = min(3, n)
        nrows = math.ceil(n / ncols)

        fig, axes = plt.subplots(
            nrows,
            ncols,
            figsize=(6.5 * ncols, 4.6 * nrows),
            squeeze=False,
        )

        for ax, panel in zip(axes.flat, summary_panels):
            draw_divergence(
                ax,
                panel["occupancy"],
                panel["mean0"],
                panel["ci0"],
                panel["mean1"],
                panel["ci1"],
                panel["title"],
            )

        for ax in axes.flat[len(summary_panels):]:
            ax.axis("off")

        fig.suptitle(f"{cache}: bit divergence by physical bank", fontsize=16)
        fig.tight_layout(rect=(0, 0, 1, 0.97))

        summary_png = os.path.join(
            out_root, f"{cache}_bit_divergence_summary.png"
        )
        fig.savefig(summary_png, dpi=180)
        plt.close(fig)
        print(f"[SAVED] {summary_png}")

    summary_csv = os.path.join(
        out_root, f"{cache}_bit_divergence_summary.csv"
    )
    with open(summary_csv, "w", newline="") as f:
        fieldnames = [
            "cache",
            "num_banks",
            "target_banks",
            "bank",
            "occupancy_pct",
            "bit0_mean_misses",
            "bit0_ci95",
            "bit1_mean_misses",
            "bit1_ci95",
            "raw_delta_of_means",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"[SAVED] {summary_csv}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-dir",
        default="results",
        help="Results directory (default: results)",
    )
    parser.add_argument(
        "--caches",
        nargs="*",
        default=list(DEFAULT_CACHES),
        help="Cache folders to process",
    )
    parser.add_argument(
        "--all-cases",
        action="store_true",
        help="Process all 16-way case directories under results/",
    )
    args = parser.parse_args()

    base_dirs = [args.base_dir]
    if args.all_cases:
        base_dirs = [
            os.path.join(args.base_dir, "multibank"),
            os.path.join(args.base_dir, "hybrid_2region_75_25"),
            os.path.join(args.base_dir, "hybrid_4region"),
        ]

    for base_dir in base_dirs:
        if not os.path.isdir(base_dir):
            continue
        for cache in args.caches:
            print(f"\n=== {base_dir}/{cache}: bit divergence ===")
            plot_cache(cache, base_dir)


if __name__ == "__main__":
    main()
