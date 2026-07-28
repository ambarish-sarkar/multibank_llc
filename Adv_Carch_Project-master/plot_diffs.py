import os
import re
import ast
import glob
from typing import Dict, Tuple, Optional
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

def _parse_file(path: str):
    """Parse outfile into dict:
       single -> {'format':'single','occupancy','accesses','misses'}
       dual   -> {'format':'dual','occupancy','accesses','misses_r0','misses_r1'}
       multi  -> {'format':'multi','occupancy','accesses','misses':[array per bank], 'num_banks':N}"""
    occ, acc, misses_cols, fmt = [], [], [], None
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = ast.literal_eval(line)
            except Exception:
                continue
            if not isinstance(row, (list, tuple)):
                continue
            if len(row) == 3:
                o,a,m = row
                occ.append(int(o)); acc.append(int(a))
                if fmt is None:
                    misses_cols = [[]]
                    fmt = 'single'
                misses_cols[0].append(int(m))
            elif len(row) == 4:
                o,a,r0,r1 = row
                occ.append(int(o)); acc.append(int(a))
                if fmt is None:
                    misses_cols = [[], []]
                    fmt = 'dual'
                misses_cols[0].append(int(r0))
                misses_cols[1].append(int(r1))
            elif len(row) > 4:
                # Multi-bank format: [occupancy, accesses, miss1, miss2, ..., missN]
                o, a = row[0], row[1]
                misses = row[2:]
                occ.append(int(o)); acc.append(int(a))
                if fmt is None:
                    misses_cols = [[] for _ in misses]
                    fmt = 'multi'
                for i, m in enumerate(misses):
                    misses_cols[i].append(int(m))
            else:
                continue
    if not occ:
        raise ValueError(f"No valid rows parsed from {path}")

    # Multiple trials write one row per (occupancy, trial), so the same
    # occupancy value can repeat several times. Average all rows sharing an
    # occupancy value instead of letting later trials silently overwrite
    # earlier ones downstream.
    occ_raw = np.array(occ, int)
    acc_raw = np.array(acc, int)
    unique_occ = np.unique(occ_raw)
    avg_acc = np.array([acc_raw[occ_raw == o].mean() for o in unique_occ])
    avg_misses_cols = [
        np.array([np.array(col, float)[occ_raw == o].mean() for o in unique_occ])
        for col in misses_cols
    ]

    out = {"occupancy": unique_occ, "accesses": avg_acc, "format": fmt}
    if fmt == 'single':
        out["misses"] = avg_misses_cols[0]
    elif fmt == 'dual':
        out["misses_r0"] = avg_misses_cols[0]
        out["misses_r1"] = avg_misses_cols[1]
    else:  # multi
        out["misses"] = avg_misses_cols
        out["num_banks"] = len(avg_misses_cols)
    return out

def _extract_meta(filename: str) -> Optional[Tuple[str, str, str, Optional[int], Optional[int]]]:
    """Return (bit, ratio, attack, num_banks, num_attacks) from filename.
       Examples:
         outfile_v1_bit_0_0.5_simultaneous.txt -> ('0', '0.5', 'simultaneous', None, None)
         outfile_v1_bit_0_0.5_simultaneous_banks4_attack2.txt -> ('0', '0.5', 'simultaneous', 4, 2)
    """
    base = os.path.basename(filename)
    m = re.match(r"outfile_v1_bit_(0|1)_([^_]+)_(.+)\.txt$", base)
    if not m:
        return None
    bit, ratio, attack_part = m.group(1), m.group(2), m.group(3)
    
    # Check if attack_part contains banks/attack info
    banks_match = re.search(r"banks(\d+)_attack(\d+)", attack_part)
    if banks_match:
        num_banks = int(banks_match.group(1))
        num_attacks = int(banks_match.group(2))
        # Extract the base attack name (everything before _banks)
        attack = attack_part.split('_banks')[0]
        return (bit, ratio, attack, num_banks, num_attacks)
    else:
        return (bit, ratio, attack_part, None, None)

def plot_bit_diff_misses(cache: str, base_dir: str = "results"):
    """For each (ratio, attack), bar-plot Δmisses = bit1 - bit0.
       - single format: one bar per occupancy.
       - dual format: grouped bars (region0, region1) per occupancy.
       - multi format: grouped bars for each bank per occupancy.
       Outputs to results/<cache>/plots_bit_diff_misses/ and writes a CSV summary."""
    folder = os.path.join(base_dir, cache)
    if not os.path.isdir(folder):
        print(f"[WARN] Folder not found: {folder}")
        return

    files0 = glob.glob(os.path.join(folder, "outfile_v1_bit_0_*_*.txt"))
    files1 = glob.glob(os.path.join(folder, "outfile_v1_bit_1_*_*.txt"))

    idx0: Dict[Tuple, str] = {}
    idx1: Dict[Tuple, str] = {}
    for p in files0:
        m = _extract_meta(p)
        if m: 
            _, r, a, nb, na = m
            key = (r, a, nb, na)
            idx0[key] = p
    for p in files1:
        m = _extract_meta(p)
        if m: 
            _, r, a, nb, na = m
            key = (r, a, nb, na)
            idx1[key] = p

    common = sorted(set(idx0) & set(idx1), key=lambda x: (x[0], x[1], x[2] or 0, x[3] or 0))
    if not common:
        print(f"[INFO] No matching bit-0/bit-1 pairs in {folder}.")
        return

    out_dir = os.path.join(folder, "plots_bit_diff_misses")
    os.makedirs(out_dir, exist_ok=True)

    summary = []

    for key in common:
        ratio, attack, num_banks, num_attacks = key
        p0, p1 = idx0[key], idx1[key]
        try:
            d0 = _parse_file(p0)
            d1 = _parse_file(p1)
        except Exception as e:
            print(f"[SKIP] {key} parse error: {e}")
            continue

        # Align by occupancy only
        occ_common = np.intersect1d(d0["occupancy"], d1["occupancy"])
        if occ_common.size == 0:
            print(f"[SKIP] No overlapping occupancy for {key}")
            continue
        map0 = {int(o): i for i, o in enumerate(d0["occupancy"])}
        map1 = {int(o): i for i, o in enumerate(d1["occupancy"])}
        i0 = np.array([map0[int(o)] for o in occ_common], int)
        i1 = np.array([map1[int(o)] for o in occ_common], int)

        if d0["format"] != d1["format"]:
            print(f"[WARN] Format mismatch for {key}. Skipping.")
            continue

        # Build filename suffix
        if num_banks is not None and num_attacks is not None:
            suffix = f"banks{num_banks}_attack{num_attacks}"
        else:
            suffix = ""

        if d0["format"] == "single":
            # Δmisses (bit1 - bit0)
            delta = d1["misses"][i1] - d0["misses"][i0]
            x = np.arange(len(occ_common))
            plt.figure()
            plt.bar(x, delta)
            plt.xticks(x, [str(o) for o in occ_common], rotation=0)
            plt.xlabel("Cache occupancy (%)")
            plt.ylabel("Δmisses (bit1 - bit0)")
            title_extra = f" | {suffix}" if suffix else ""
            plt.title(f"{cache} | ratio={ratio} | attack={attack}{title_extra} | Δmisses (single)")
            fname = f"{cache}_ratio-{ratio}_attack-{attack}"
            if suffix:
                fname += f"_{suffix}"
            fname += "_delta_misses_single.png"
            f_single = os.path.join(out_dir, fname)
            plt.tight_layout()
            plt.savefig(f_single, dpi=160)
            plt.close()

            summary.append({
                "cache": cache, "ratio": ratio, "attack": attack,
                "num_banks": num_banks, "num_attacks": num_attacks,
                "format": "single", "plot": f_single
            })

        elif d0["format"] == "dual":
            # dual format -> grouped bars per occupancy for region0 and region1
            d_r0 = d1["misses_r0"][i1] - d0["misses_r0"][i0]
            d_r1 = d1["misses_r1"][i1] - d0["misses_r1"][i0]

            x = np.arange(len(occ_common))
            bw = 0.4
            plt.figure()
            plt.bar(x - bw/2, d_r0, width=bw, label="Δmisses region0")
            plt.bar(x + bw/2, d_r1, width=bw, label="Δmisses region1")
            plt.xticks(x, [str(o) for o in occ_common], rotation=0)
            plt.xlabel("Cache occupancy (%)")
            plt.ylabel("Δmisses (bit1 - bit0)")
            title_extra = f" | {suffix}" if suffix else ""
            plt.title(f"{cache} | ratio={ratio} | attack={attack}{title_extra} | Δmisses by region")
            plt.legend()
            fname = f"{cache}_ratio-{ratio}_attack-{attack}"
            if suffix:
                fname += f"_{suffix}"
            fname += "_delta_misses_dual.png"
            f_dual = os.path.join(out_dir, fname)
            plt.tight_layout()
            plt.savefig(f_dual, dpi=160)
            plt.close()

            summary.append({
                "cache": cache, "ratio": ratio, "attack": attack,
                "num_banks": num_banks, "num_attacks": num_attacks,
                "format": "dual", "plot": f_dual
            })

        else:  # multi format
            # Multiple banks: create grouped bar chart
            num_b = d0["num_banks"]
            deltas = []
            for b in range(num_b):
                delta = d1["misses"][b][i1] - d0["misses"][b][i0]
                deltas.append(delta)
            
            x = np.arange(len(occ_common))
            bw = 0.8 / num_b  # divide the total width among banks
            
            plt.figure(figsize=(12, 6))
            for b in range(num_b):
                offset = (b - num_b/2 + 0.5) * bw
                plt.bar(x + offset, deltas[b], width=bw, label=f"Δmisses bank{b}")
            
            plt.xticks(x, [str(o) for o in occ_common], rotation=0)
            plt.xlabel("Cache occupancy (%)")
            plt.ylabel("Δmisses (bit1 - bit0)")
            title_extra = f" | {suffix}" if suffix else ""
            plt.title(f"{cache} | ratio={ratio} | attack={attack}{title_extra} | Δmisses by bank")
            plt.legend()
            fname = f"{cache}_ratio-{ratio}_attack-{attack}"
            if suffix:
                fname += f"_{suffix}"
            fname += "_delta_misses_multi.png"
            f_multi = os.path.join(out_dir, fname)
            plt.tight_layout()
            plt.savefig(f_multi, dpi=160)
            plt.close()

            summary.append({
                "cache": cache, "ratio": ratio, "attack": attack,
                "num_banks": num_banks, "num_attacks": num_attacks,
                "format": "multi", "plot": f_multi
            })

    if summary:
        df = pd.DataFrame(summary)
        csv_path = os.path.join(out_dir, f"{cache}_bit_diff_misses_summary.csv")
        df.to_csv(csv_path, index=False)
        print(f"Saved summary: {csv_path}")
    else:
        print("No plots generated.")

# Usage:
if __name__ == "__main__":
    for cache in ("normal", "ceaser", "ceaser_s", "mirage", "scatter"):
        plot_bit_diff_misses(cache, base_dir="results")
