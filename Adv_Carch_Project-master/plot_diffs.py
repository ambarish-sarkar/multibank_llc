import os
import re
import ast
import glob
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def _parse_file(path: str):
    """Parse outfile into averaged occupancy/miss arrays."""
    occ, acc, misses_cols, fmt = [], [], [], None

    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = ast.literal_eval(line)
            except Exception:
                continue
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue

            o, a = row[0], row[1]
            misses = row[2:]

            occ.append(int(o))
            acc.append(int(a))

            if fmt is None:
                if len(misses) == 1:
                    fmt = "single"
                elif len(misses) == 2:
                    fmt = "dual"
                else:
                    fmt = "multi"
                misses_cols = [[] for _ in misses]

            if len(misses) != len(misses_cols):
                raise ValueError(
                    f"Inconsistent number of miss columns in {path}: "
                    f"expected {len(misses_cols)}, got {len(misses)}"
                )

            for i, m in enumerate(misses):
                misses_cols[i].append(int(m))

    if not occ:
        raise ValueError(f"No valid rows parsed from {path}")

    occ_raw = np.array(occ, int)
    acc_raw = np.array(acc, int)
    unique_occ = np.unique(occ_raw)

    avg_acc = np.array(
        [acc_raw[occ_raw == o].mean() for o in unique_occ]
    )
    avg_misses_cols = [
        np.array(
            [np.array(col, float)[occ_raw == o].mean() for o in unique_occ]
        )
        for col in misses_cols
    ]

    out = {
        "occupancy": unique_occ,
        "accesses": avg_acc,
        "format": fmt,
        "misses": avg_misses_cols,
        "num_miss_columns": len(avg_misses_cols),
    }
    return out


def _extract_meta(filename: str):
    """
    Return:
      (bit, ratio, attack, num_banks, target_banks, legacy_attack_count)

    Supported new filenames:
      outfile_v1_bit_0_0.5_simultaneous_banks4_banks_0.txt
      outfile_v1_bit_0_0.5_simultaneous_banks4_banks_0-2.txt
      outfile_v1_bit_0_0.5_simultaneous_banks8_banks_1-4-6.txt

    Supported legacy filename:
      outfile_v1_bit_0_0.5_simultaneous_banks4_attack2.txt

    Single-bank filename:
      outfile_v1_bit_0_0.5_simultaneous.txt
    """
    base = os.path.basename(filename)
    m = re.match(r"outfile_v1_bit_(0|1)_([^_]+)_(.+)\.txt$", base)
    if not m:
        return None

    bit, ratio, attack_part = m.group(1), m.group(2), m.group(3)

    # New S-NUCA naming:
    # simultaneous_banks4_banks_0-2
    new_m = re.search(r"_banks(\d+)_banks_([0-9]+(?:-[0-9]+)*)$", attack_part)
    if new_m:
        num_banks = int(new_m.group(1))
        target_banks = tuple(int(x) for x in new_m.group(2).split("-"))
        attack = attack_part[:new_m.start()]
        return bit, ratio, attack, num_banks, target_banks, None

    # Legacy naming:
    # simultaneous_banks4_attack2
    old_m = re.search(r"_banks(\d+)_attack(\d+)$", attack_part)
    if old_m:
        num_banks = int(old_m.group(1))
        attack_count = int(old_m.group(2))
        attack = attack_part[:old_m.start()]
        return bit, ratio, attack, num_banks, None, attack_count

    # Single-bank / old no-bank-suffix result.
    return bit, ratio, attack_part, None, None, None


def _suffix(num_banks, target_banks, legacy_attack_count):
    if num_banks is None:
        return ""
    if target_banks is not None:
        return f"banks{num_banks}_banks_" + "-".join(str(x) for x in target_banks)
    if legacy_attack_count is not None:
        return f"banks{num_banks}_attack{legacy_attack_count}"
    return f"banks{num_banks}"


def _bank_labels(data, target_banks):
    """
    Label miss columns using exact physical bank IDs when new filenames provide
    target-banks. Otherwise preserve old region/bank numbering behavior.
    """
    n = data["num_miss_columns"]

    if target_banks is not None and len(target_banks) == n:
        return [f"bank{b}" for b in target_banks]

    if n == 1:
        return ["selected bank"]
    if n == 2:
        return ["region0", "region1"]
    return [f"bank{i}" for i in range(n)]


def plot_bit_diff_misses(cache: str, base_dir: str = "results"):
    """
    For each matching bit-0/bit-1 result pair, plot:
        Δmisses = bit1 - bit0

    The x-axis occupancy is now explicitly the percentage of the combined
    selected/attacked-bank capacity.
    """
    folder = os.path.join(base_dir, cache)
    if not os.path.isdir(folder):
        print(f"[WARN] Folder not found: {folder}")
        return

    files0 = glob.glob(os.path.join(folder, "outfile_v1_bit_0_*_*.txt"))
    files1 = glob.glob(os.path.join(folder, "outfile_v1_bit_1_*_*.txt"))

    idx0: Dict[Tuple, str] = {}
    idx1: Dict[Tuple, str] = {}

    for p in files0:
        meta = _extract_meta(p)
        if meta:
            _, ratio, attack, nb, targets, legacy_count = meta
            key = (ratio, attack, nb, targets, legacy_count)
            idx0[key] = p

    for p in files1:
        meta = _extract_meta(p)
        if meta:
            _, ratio, attack, nb, targets, legacy_count = meta
            key = (ratio, attack, nb, targets, legacy_count)
            idx1[key] = p

    common = sorted(
        set(idx0) & set(idx1),
        key=lambda x: (
            x[0],
            x[1],
            x[2] or 0,
            x[3] or tuple(),
            x[4] or 0,
        ),
    )

    if not common:
        print(f"[INFO] No matching bit-0/bit-1 pairs in {folder}.")
        return

    out_dir = os.path.join(folder, "plots_bit_diff_misses")
    os.makedirs(out_dir, exist_ok=True)

    summary = []

    for key in common:
        ratio, attack, num_banks, target_banks, legacy_attack_count = key
        p0, p1 = idx0[key], idx1[key]

        try:
            d0 = _parse_file(p0)
            d1 = _parse_file(p1)
        except Exception as e:
            print(f"[SKIP] {key} parse error: {e}")
            continue

        if d0["num_miss_columns"] != d1["num_miss_columns"]:
            print(f"[WARN] Miss-column mismatch for {key}. Skipping.")
            continue

        occ_common = np.intersect1d(d0["occupancy"], d1["occupancy"])
        if occ_common.size == 0:
            print(f"[SKIP] No overlapping occupancy for {key}")
            continue

        map0 = {int(o): i for i, o in enumerate(d0["occupancy"])}
        map1 = {int(o): i for i, o in enumerate(d1["occupancy"])}
        i0 = np.array([map0[int(o)] for o in occ_common], int)
        i1 = np.array([map1[int(o)] for o in occ_common], int)

        suffix = _suffix(num_banks, target_banks, legacy_attack_count)
        labels = _bank_labels(d0, target_banks)

        # Δmisses for each selected-bank result column.
        deltas = [
            d1["misses"][col][i1] - d0["misses"][col][i0]
            for col in range(d0["num_miss_columns"])
        ]

        x = np.arange(len(occ_common))

        if len(deltas) == 1:
            plt.figure(figsize=(8, 5))
            plt.bar(x, deltas[0])
            plt.xticks(x, [str(o) for o in occ_common])
            plt.xlabel("Occupancy of selected bank(s) capacity (%)")
            plt.ylabel("Δmisses (bit1 - bit0)")
            title_extra = f" | {suffix}" if suffix else ""
            plt.title(
                f"{cache} | ratio={ratio} | attack={attack}"
                f"{title_extra} | Δmisses"
            )

            fname = f"{cache}_ratio-{ratio}_attack-{attack}"
            if suffix:
                fname += f"_{suffix}"
            fname += "_delta_misses.png"

        else:
            bw = 0.8 / len(deltas)
            plt.figure(figsize=(12, 6))

            for col, delta in enumerate(deltas):
                offset = (col - len(deltas) / 2 + 0.5) * bw
                plt.bar(
                    x + offset,
                    delta,
                    width=bw,
                    label=f"Δmisses {labels[col]}",
                )

            plt.xticks(x, [str(o) for o in occ_common])
            plt.xlabel("Occupancy of selected bank(s) capacity (%)")
            plt.ylabel("Δmisses (bit1 - bit0)")
            title_extra = f" | {suffix}" if suffix else ""
            plt.title(
                f"{cache} | ratio={ratio} | attack={attack}"
                f"{title_extra} | Δmisses by selected bank"
            )
            plt.legend()

            fname = f"{cache}_ratio-{ratio}_attack-{attack}"
            if suffix:
                fname += f"_{suffix}"
            fname += "_delta_misses_multi.png"

        f_plot = os.path.join(out_dir, fname)
        plt.tight_layout()
        plt.savefig(f_plot, dpi=160)
        plt.close()

        summary.append(
            {
                "cache": cache,
                "ratio": ratio,
                "attack": attack,
                "num_banks": num_banks,
                "target_banks": (
                    "-".join(str(x) for x in target_banks)
                    if target_banks is not None
                    else ""
                ),
                "legacy_attack_count": legacy_attack_count,
                "num_result_columns": d0["num_miss_columns"],
                "plot": f_plot,
            }
        )

    if summary:
        df = pd.DataFrame(summary)
        csv_path = os.path.join(
            out_dir, f"{cache}_bit_diff_misses_summary.csv"
        )
        df.to_csv(csv_path, index=False)
        print(f"Saved summary: {csv_path}")
    else:
        print(f"[INFO] No plots generated for {cache}.")


if __name__ == "__main__":
    for cache in ("normal", "ceaser", "ceaser_s", "mirage", "scatter"):
        plot_bit_diff_misses(cache, base_dir="results")
