#!/usr/bin/env python3
"""
plot_normalized_delta.py

Creates cross-bank-count comparable delta plots.

Two related metrics are produced:

1) Individual-bank capacity-normalized delta:
       100 * (misses_bit1 - misses_bit0) / capacity_of_one_bank

   This directly addresses the fact that 10 extra misses in one bank of a
   4-bank cache are not equivalent to 10 extra misses in a one-bank cache.
   The same raw delta is 4x larger after normalization when the bank is 4x
   smaller.

2) Aggregate excess receiver miss rate across all attacked banks:
       100 * sum_i(misses_bit1_i - misses_bit0_i) / receiver_accesses

   This is an exact aggregate metric using the receiver-access count already
   stored in each result row. It answers whether the overall channel effect is
   weakened or merely distributed across multiple banks.

Expected output per design:
    results/<design>/plots_normalized_delta/
      1_bank/
      2_banks/
      4_banks/
      ... discovered automatically
      <design>_aggregate_excess_miss_rate_summary.png
      <design>_normalized_delta_summary.csv

By default the total LLC has 131072 cache lines (8 MiB / 64 B).
Override with --total-cache-lines if needed.
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
DEFAULT_TOTAL_CACHE_LINES = 131072


def parse_meta(path):
    base = os.path.basename(path)
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
        return {
            "bit": bit,
            "ratio": ratio,
            "attack": attack,
            "num_banks": num_banks,
            "target_banks": tuple(range(attack_count)),
            "legacy_attack_count": attack_count,
        }

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


def scenario_label(meta):
    targets = ",".join(str(x) for x in meta["target_banks"])
    if meta["num_banks"] == 1:
        return "1 bank"
    return f"{meta['num_banks']} banks, targets [{targets}]"


def bank_folder_name(num_banks):
    return f"{num_banks}_bank" if num_banks == 1 else f"{num_banks}_banks"


def parse_raw_file(path):
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
            accesses.append(float(row[1]))
            misses.append([float(x) for x in row_misses])

    if not occ:
        raise ValueError(f"No valid rows in {path}")

    return {
        "occupancy": np.asarray(occ, dtype=int),
        "accesses": np.asarray(accesses, dtype=float),
        "misses": np.asarray(misses, dtype=float),
    }


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


def ci95(values):
    values = np.asarray(values, dtype=float)
    if values.size <= 1:
        return 0.0
    return 1.96 * values.std(ddof=1) / math.sqrt(values.size)


def paired_rows_for_occupancy(d0, d1, occupancy):
    """
    Pair bit-0 and bit-1 rows by their order within an occupancy bucket.

    The experiment generates corresponding trials in the same order. If counts
    differ, use the common prefix and warn.
    """
    idx0 = np.flatnonzero(d0["occupancy"] == occupancy)
    idx1 = np.flatnonzero(d1["occupancy"] == occupancy)
    n = min(len(idx0), len(idx1))

    if n == 0:
        return None

    if len(idx0) != len(idx1):
        print(
            f"[WARN] occupancy {occupancy}% row mismatch: "
            f"bit0={len(idx0)}, bit1={len(idx1)}; using first {n} paired rows"
        )

    return idx0[:n], idx1[:n]


def bank_ids(meta, num_cols):
    targets = meta["target_banks"]
    if len(targets) == num_cols:
        return list(targets)
    return list(range(num_cols))


def plot_cache(cache, base_dir, total_cache_lines):
    folder = os.path.join(base_dir, cache)
    if not os.path.isdir(folder):
        print(f"[WARN] missing cache folder: {folder}")
        return

    pairs = collect_pairs(folder)
    if not pairs:
        print(f"[WARN] no bit-0/bit-1 pairs for {cache}")
        return

    out_root = os.path.join(folder, "plots_normalized_delta")
    os.makedirs(out_root, exist_ok=True)

    summary_curves = []
    csv_rows = []

    for p0, p1, meta in pairs:
        d0 = parse_raw_file(p0)
        d1 = parse_raw_file(p1)

        if d0["misses"].shape[1] != d1["misses"].shape[1]:
            print(f"[SKIP] miss-column mismatch: {p0} vs {p1}")
            continue

        num_banks = meta["num_banks"]
        if total_cache_lines % num_banks != 0:
            raise ValueError(
                f"total cache lines ({total_cache_lines}) not divisible by "
                f"num_banks ({num_banks})"
            )

        capacity_per_bank = total_cache_lines / num_banks
        num_cols = d0["misses"].shape[1]
        ids = bank_ids(meta, num_cols)
        targets_text = ",".join(str(x) for x in meta["target_banks"])

        common_occ = sorted(
            set(int(x) for x in np.unique(d0["occupancy"]))
            & set(int(x) for x in np.unique(d1["occupancy"]))
        )

        bank_dir = os.path.join(out_root, bank_folder_name(num_banks))
        os.makedirs(bank_dir, exist_ok=True)

        per_bank_series = {col: {"occ": [], "mean": [], "ci": []} for col in range(num_cols)}
        aggregate_series = {"occ": [], "mean": [], "ci": []}
        raw_aggregate_series = {"occ": [], "mean": [], "ci": []}

        for occ in common_occ:
            paired = paired_rows_for_occupancy(d0, d1, occ)
            if paired is None:
                continue

            i0, i1 = paired
            delta = d1["misses"][i1, :] - d0["misses"][i0, :]

            # Individual-bank normalization by that bank's physical capacity.
            for col in range(num_cols):
                normalized = 100.0 * delta[:, col] / capacity_per_bank
                per_bank_series[col]["occ"].append(occ)
                per_bank_series[col]["mean"].append(float(normalized.mean()))
                per_bank_series[col]["ci"].append(float(ci95(normalized)))

            # Aggregate raw delta across attacked-bank columns.
            aggregate_delta = delta.sum(axis=1)

            # Receiver accesses are the same experiment quantity for bit0/bit1.
            # Use the paired bit-0 row's stored total receiver accesses.
            receiver_accesses = d0["accesses"][i0]
            valid = receiver_accesses > 0
            if not np.all(valid):
                aggregate_rate = np.zeros_like(aggregate_delta, dtype=float)
                aggregate_rate[valid] = (
                    100.0 * aggregate_delta[valid] / receiver_accesses[valid]
                )
                aggregate_rate = aggregate_rate[valid]
            else:
                aggregate_rate = 100.0 * aggregate_delta / receiver_accesses

            aggregate_series["occ"].append(occ)
            aggregate_series["mean"].append(float(aggregate_rate.mean()))
            aggregate_series["ci"].append(float(ci95(aggregate_rate)))

            raw_aggregate_series["occ"].append(occ)
            raw_aggregate_series["mean"].append(float(aggregate_delta.mean()))
            raw_aggregate_series["ci"].append(float(ci95(aggregate_delta)))

            for col in range(num_cols):
                csv_rows.append(
                    {
                        "cache": cache,
                        "num_banks": num_banks,
                        "target_banks": targets_text,
                        "bank": ids[col],
                        "occupancy_pct": occ,
                        "capacity_per_bank_lines": int(capacity_per_bank),
                        "mean_capacity_normalized_delta_pct": per_bank_series[col]["mean"][-1],
                        "ci95_capacity_normalized_delta_pct": per_bank_series[col]["ci"][-1],
                        "mean_aggregate_raw_delta_misses": raw_aggregate_series["mean"][-1],
                        "ci95_aggregate_raw_delta_misses": raw_aggregate_series["ci"][-1],
                        "mean_aggregate_excess_miss_rate_pct": aggregate_series["mean"][-1],
                        "ci95_aggregate_excess_miss_rate_pct": aggregate_series["ci"][-1],
                    }
                )

        # Individual physical-bank plots.
        for col in range(num_cols):
            series = per_bank_series[col]
            bank_id = ids[col]

            fig, ax = plt.subplots(figsize=(9, 5.5))
            x = np.asarray(series["occ"], dtype=float)
            y = np.asarray(series["mean"], dtype=float)
            ci = np.asarray(series["ci"], dtype=float)

            ax.plot(x, y, marker="o")
            ax.fill_between(x, y - ci, y + ci, alpha=0.18)
            ax.axhline(0, linewidth=1)
            ax.set_xlabel("Cache occupancy (%)")
            ax.set_ylabel("Capacity-normalized Δ misses (% of physical bank capacity)")
            ax.set_title(
                f"{cache} | {num_banks}-bank setup | "
                f"targets [{targets_text}] | Bank {bank_id}"
            )
            ax.grid(True, alpha=0.25)

            fig.tight_layout()
            fname = (
                f"{cache}_{scenario_tag(meta)}_bank{bank_id}"
                "_capacity_normalized_delta.png"
            )
            path = os.path.join(bank_dir, fname)
            fig.savefig(path, dpi=180)
            plt.close(fig)
            print(f"[SAVED] {path}")

        # Exact aggregate plot for this scenario.
        fig, ax = plt.subplots(figsize=(9, 5.5))
        x = np.asarray(aggregate_series["occ"], dtype=float)
        y = np.asarray(aggregate_series["mean"], dtype=float)
        ci = np.asarray(aggregate_series["ci"], dtype=float)

        ax.plot(x, y, marker="o")
        ax.fill_between(x, y - ci, y + ci, alpha=0.18)
        ax.axhline(0, linewidth=1)
        ax.set_xlabel("Cache occupancy (%)")
        ax.set_ylabel("Aggregate excess receiver miss rate (%)")
        ax.set_title(
            f"{cache} | {scenario_label(meta)} | aggregate attacked-bank effect"
        )
        ax.grid(True, alpha=0.25)

        fig.tight_layout()
        aggregate_path = os.path.join(
            bank_dir,
            f"{cache}_{scenario_tag(meta)}_aggregate_excess_miss_rate.png",
        )
        fig.savefig(aggregate_path, dpi=180)
        plt.close(fig)
        print(f"[SAVED] {aggregate_path}")

        summary_curves.append(
            {
                "label": scenario_label(meta),
                "occ": list(aggregate_series["occ"]),
                "mean": list(aggregate_series["mean"]),
                "ci": list(aggregate_series["ci"]),
            }
        )

    # Main summary: one comparable aggregate curve per scenario.
    if summary_curves:
        fig, ax = plt.subplots(figsize=(11, 6.5))

        for curve in summary_curves:
            x = np.asarray(curve["occ"], dtype=float)
            y = np.asarray(curve["mean"], dtype=float)
            ci = np.asarray(curve["ci"], dtype=float)
            ax.plot(x, y, marker="o", label=curve["label"])
            ax.fill_between(x, y - ci, y + ci, alpha=0.10)

        ax.axhline(0, linewidth=1)
        ax.set_xlabel("Cache occupancy (%)")
        ax.set_ylabel("Aggregate excess receiver miss rate (%)")
        ax.set_title(
            f"{cache}: normalized aggregate bit-induced miss effect"
        )
        ax.grid(True, alpha=0.25)
        ax.legend()

        fig.tight_layout()
        summary_png = os.path.join(
            out_root, f"{cache}_aggregate_excess_miss_rate_summary.png"
        )
        fig.savefig(summary_png, dpi=180)
        plt.close(fig)
        print(f"[SAVED] {summary_png}")

    summary_csv = os.path.join(
        out_root, f"{cache}_normalized_delta_summary.csv"
    )
    with open(summary_csv, "w", newline="") as f:
        fieldnames = [
            "cache",
            "num_banks",
            "target_banks",
            "bank",
            "occupancy_pct",
            "capacity_per_bank_lines",
            "mean_capacity_normalized_delta_pct",
            "ci95_capacity_normalized_delta_pct",
            "mean_aggregate_raw_delta_misses",
            "ci95_aggregate_raw_delta_misses",
            "mean_aggregate_excess_miss_rate_pct",
            "ci95_aggregate_excess_miss_rate_pct",
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
        "--total-cache-lines",
        type=int,
        default=DEFAULT_TOTAL_CACHE_LINES,
        help="Total LLC cache lines (default: 131072)",
    )
    parser.add_argument(
        "--caches",
        nargs="*",
        default=list(DEFAULT_CACHES),
        help="Cache folders to process",
    )
    args = parser.parse_args()

    for cache in args.caches:
        print(f"\n=== {cache}: normalized delta ===")
        plot_cache(cache, args.base_dir, args.total_cache_lines)


if __name__ == "__main__":
    main()
