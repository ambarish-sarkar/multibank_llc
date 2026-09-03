#!/usr/bin/env python3
import argparse
import os
import sys

from result_utils import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_MALFORMED,
    classify_result_file,
    parse_occupancies,
)


def iter_result_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith("plots_") and d != "run_logs"]
        for name in sorted(filenames):
            if not name.endswith(".txt"):
                continue
            if ".tmp." in name or name.endswith(".incomplete"):
                continue
            yield os.path.join(dirpath, name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="results", help="Result tree to inspect")
    parser.add_argument("--trials", type=int, default=100, help="Expected trials per occupancy")
    parser.add_argument(
        "--occupancies",
        default="1,2,5,10,15,20,25,30,35,40",
        help="Comma-separated expected occupancy points",
    )
    args = parser.parse_args()

    occupancies = parse_occupancies(args.occupancies)
    totals = {STATUS_COMPLETE: 0, STATUS_INCOMPLETE: 0, STATUS_MALFORMED: 0}
    files = list(iter_result_files(args.root))

    for path in files:
        status, detail = classify_result_file(path, args.trials, occupancies)
        totals[status] += 1
        print(f"{status}\t{path}\t{detail}")

    print("")
    print(f"total complete files: {totals[STATUS_COMPLETE]}")
    print(f"total incomplete files: {totals[STATUS_INCOMPLETE]}")
    print(f"total malformed files: {totals[STATUS_MALFORMED]}")

    if totals[STATUS_INCOMPLETE] or totals[STATUS_MALFORMED]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
