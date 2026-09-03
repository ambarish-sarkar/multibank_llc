#!/usr/bin/env python3
import os
import tempfile

from arch_model import run_architecture_simulation
from common import (
    get_bank_id,
    get_new_random_addresses_for_targets,
    get_region_id,
    get_target_pairs,
)
from validate_snuca import DESIGNS, MODES, cfg_for


BANK_TARGETS = {
    1: [[0]],
    2: [[0], [0, 1]],
    4: [[0], [0, 1, 2, 3]],
}


def misses(tdict):
    return sum(1 for _, timing in tdict.items() if timing == 600)


def main():
    tmp = tempfile.mkdtemp(prefix="snuca_smoke_")
    print(f"Smoke output directory: {tmp}")
    runs = 0
    for design in DESIGNS:
        for mode in MODES:
            for banks, target_lists in BANK_TARGETS.items():
                for targets in target_lists:
                    regions = [1] if mode == "hybrid2" else ([0, 1, 2, 3] if mode == "region4" else [0])
                    c = cfg_for(design, mode, banks, targets=targets, regions=regions)
                    unique = set()
                    recv = get_new_random_addresses_for_targets(unique, 8, c)
                    send0 = get_new_random_addresses_for_targets(unique, 6, c)
                    send1 = send0 + get_new_random_addresses_for_targets(unique, 6, c)
                    assert len(send1) > len(send0)
                    target_pairs = set(get_target_pairs(c))
                    for addr in recv + send0 + send1:
                        pair = (get_bank_id(addr, c.num_banks, c.num_words_per_block), get_region_id(addr, c))
                        assert pair in target_pairs, (design, mode, banks, targets, pair)

                    out0 = run_architecture_simulation(design, c, recv, send0)
                    out1 = run_architecture_simulation(design, c, recv, send1)
                    row0 = [1, len(recv)] + [misses(out0[k]) for k in out0]
                    row1 = [1, len(recv)] + [misses(out1[k]) for k in out1]
                    if len(row0) != 2 + len(target_pairs):
                        raise AssertionError(f"bad result column count for {design} {mode}")

                    outdir = os.path.join(tmp, mode, design)
                    os.makedirs(outdir, exist_ok=True)
                    slug = "-".join(str(t) for t in targets)
                    with open(os.path.join(outdir, f"banks{banks}_targets_{slug}.txt"), "w") as f:
                        f.write(str(row0) + "\n")
                        f.write(str(row1) + "\n")
                    runs += 1
    print(f"SMOKE PASSED: {runs} tiny jobs completed")


if __name__ == "__main__":
    main()
