#!/usr/bin/env python3
import copy
import os
import sys

from arch_model import BankedArchitectureCache
from common import (
    BYTES_PER_WORD,
    Configs,
    configure_architecture,
    get_bank_id,
    get_new_random_addresses_for_targets,
    get_region_id,
    get_snuca_geometry,
    validate_architecture_config,
)


DESIGNS = ["normal", "ceaser", "ceaser_s", "scatter", "mirage"]
MODES = ["multibank", "hybrid2", "region4"]


def cfg_for(design, mode, banks=1, ratio=0.75, targets=None, regions=None):
    c = Configs()
    c.cache_size = 8388608
    c.num_words_per_block = 8
    c.num_addr_bits = 64
    c.replacement_policy = "rand"
    c.num_banks = banks
    c.target_banks = targets or [0]
    c.banks_to_attack = len(c.target_banks)
    c.architecture_mode = mode
    c.region_split_ratio = ratio
    c.strict_region = True
    c.strict_integer_split = True
    c.workload_mode = "default"
    c.trials = 1
    if design == "mirage":
        c.num_blocks_per_set = 8
        c.num_additional_tags = 6
        c.num_partitions = 2
    elif design == "ceaser_s":
        c.num_blocks_per_set = 16
        c.num_partitions = 2
    elif design == "scatter":
        c.num_blocks_per_set = 16
        c.num_partitions = 16
    else:
        c.num_blocks_per_set = 16
        c.num_partitions = 1
    if mode == "hybrid2":
        c.num_regions = 2
        c.attack_regions = regions or [1]
    elif mode == "region4":
        c.num_regions = 4
        c.attack_regions = regions or [0, 1, 2, 3]
    else:
        c.num_regions = 1
        c.attack_regions = [0]
    configure_architecture(c)
    validate_architecture_config(c, design)
    return c


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def check_global_geometry():
    print("GLOBAL")
    assert_eq(8 * BYTES_PER_WORD, 64, "block size")
    assert_eq(8388608 // 64, 131072, "total data lines")
    for banks, sets in ((1, 8192), (2, 4096), (4, 2048)):
        geom = get_snuca_geometry(8388608, 8, 16, banks)
        assert_eq(geom["sets_per_bank"], sets, f"{banks} bank sets/bank")
        assert_eq(geom["aggregate_lines"], 131072, f"{banks} bank aggregate")
        print(f"  {banks} bank: sets/bank={sets}, ways=16, aggregate=131072")


def check_capacities():
    print("CAPACITY")
    for design in DESIGNS:
        for mode in MODES:
            for banks in (1, 2, 4):
                c = cfg_for(design, mode, banks, targets=list(range(banks)) if banks > 1 else [0])
                cache = BankedArchitectureCache(design, c)
                capacities = cache.capacities()
                per_bank_total = [sum(regions.values()) for regions in capacities.values()]
                assert_eq(sum(per_bank_total), 131072, f"{design} {mode} banks={banks} aggregate data")
                assert all(total == 131072 // banks for total in per_bank_total)
                if design != "mirage":
                    if mode == "multibank":
                        if design in ("normal", "ceaser"):
                            assert_eq(c.region_way_groups, [[16]], f"{design} baseline ways")
                        elif design == "ceaser_s":
                            assert_eq(c.region_way_groups, [[8, 8]], "ceaser_s baseline")
                        elif design == "scatter":
                            assert_eq([len(x) for x in c.region_skews], [16], "scatter baseline")
                    elif mode == "hybrid2":
                        if design in ("normal", "ceaser"):
                            assert_eq(c.region_way_groups, [[12], [4]], f"{design} hybrid2 ways")
                        elif design == "ceaser_s":
                            assert_eq(c.region_way_groups, [[6, 6], [2, 2]], "ceaser_s hybrid2")
                        elif design == "scatter":
                            assert_eq([len(x) for x in c.region_skews], [12, 4], "scatter hybrid2 skews")
                    else:
                        if design in ("normal", "ceaser"):
                            assert_eq(c.region_way_groups, [[4], [4], [4], [4]], f"{design} region4")
                        elif design == "ceaser_s":
                            assert_eq(c.region_way_groups, [[2, 2], [2, 2], [2, 2], [2, 2]], "ceaser_s region4")
                        elif design == "scatter":
                            assert_eq(c.region_skews, [list(range(0, 4)), list(range(4, 8)), list(range(8, 12)), list(range(12, 16))], "scatter region4")
                else:
                    for bank_regions in cache.bank_region.values():
                        data = [r.data_entries for r in bank_regions.values()]
                        tag_sets = [r.tag_sets_per_skew for r in bank_regions.values()]
                        assert all(r.tag_skews == 2 and r.tag_ways == 14 for r in bank_regions.values())
                        if mode == "hybrid2":
                            assert_eq(data, [98304 // banks, 32768 // banks], f"mirage hybrid data banks={banks}")
                        if mode == "region4":
                            assert_eq(data, [32768 // banks] * 4, f"mirage region4 data banks={banks}")
                        assert_eq(sum(tag_sets), (131072 // banks) // 16, f"mirage tag-set aggregate banks={banks}")
    print("  enforced capacities OK")


def check_invalid_ratio():
    print("RATIO")
    cfg_for("normal", "hybrid2", 1, ratio=0.75)
    failed = False
    try:
        cfg_for("normal", "hybrid2", 1, ratio=0.80)
    except ValueError as exc:
        failed = "Invalid hybrid region ratio" in str(exc)
    assert failed, "0.80 ratio must fail for 16-way way split"
    print("  0.75 passes; 0.80 fails")


def check_address_targeting():
    print("ADDRESS TARGETING")
    scenarios = [
        cfg_for("normal", "hybrid2", 4, targets=[0, 2], regions=[1]),
        cfg_for("scatter", "region4", 4, targets=[1, 3], regions=[0, 1, 2, 3]),
    ]
    for c in scenarios:
        addrs = get_new_random_addresses_for_targets(set(), 256, c)
        target_pairs = {(b, r) for b in c.target_banks for r in c.attack_regions}
        seen = set()
        for addr in addrs:
            pair = (get_bank_id(addr, c.num_banks, c.num_words_per_block), get_region_id(addr, c))
            if pair not in target_pairs:
                raise AssertionError(f"address {addr} mapped to non-target {pair}")
            seen.add(pair)
        assert seen <= target_pairs
        assert seen, "no target pairs generated"
    print("  bank+region constrained generation OK")


def check_replacement_isolation():
    print("REPLACEMENT ISOLATION")
    c = cfg_for("normal", "region4", 1, regions=[0])
    cache = BankedArchitectureCache("normal", c)
    for i in range(128):
        addr = (i * c.num_regions + 0) * c.num_words_per_block
        cache.access(addr, 0, 0)
    occupied = cache.occupied()[0]
    assert occupied[0] > 0
    assert_eq(occupied[1], 0, "region1 untouched")
    assert_eq(occupied[2], 0, "region2 untouched")
    assert_eq(occupied[3], 0, "region3 untouched")

    c = cfg_for("normal", "multibank", 4, targets=[0])
    cache = BankedArchitectureCache("normal", c)
    for i in range(128):
        addr = (i * 4 + 0) * c.num_words_per_block
        cache.access(addr, 0, 0)
    occupied = cache.occupied()
    assert occupied[0][0] > 0
    assert_eq(occupied[1][0], 0, "bank1 untouched")
    assert_eq(occupied[2][0], 0, "bank2 untouched")
    assert_eq(occupied[3][0], 0, "bank3 untouched")
    print("  no cross-region or cross-bank allocation")


def main():
    check_global_geometry()
    check_capacities()
    check_invalid_ratio()
    check_address_targeting()
    check_replacement_isolation()
    print("VALIDATION PASSED")


if __name__ == "__main__":
    main()
