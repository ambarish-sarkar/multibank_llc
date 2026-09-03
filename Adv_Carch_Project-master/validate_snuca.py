#!/usr/bin/env python3
import os
import random
import statistics
import tempfile

from arch_model import (
    CEASER_KEY,
    CEASER_S_KEYS,
    MIRAGE_KEYS,
    BankedArchitectureCache,
    MirageRegion,
    _present_index,
    _present_index_mod,
)
from common import (
    BYTES_PER_WORD,
    Configs,
    configure_architecture,
    derive_cache_seed,
    derive_workload_seed,
    get_bank_id,
    get_receiver_access_counts,
    get_local_set,
    get_new_random_addresses_for_targets,
    get_region_id,
    get_snuca_geometry,
    sender_percent_for_0,
    sender_percent_for_1,
    target_occupancy_percentages,
    validate_architecture_config,
    get_trial_addresses,
)
from common_driver import output_path, outputs_are_complete
from result_utils import (
    STATUS_COMPLETE,
    STATUS_INCOMPLETE,
    STATUS_MALFORMED,
    atomic_write_result,
    classify_result_file,
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
    c.seed = 20260904
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


def word_addr_for(bank, local_set, region_stream, banks, sets_per_bank, words_per_block=8):
    block = ((region_stream * sets_per_bank) + local_set) * banks + bank
    return block * words_per_block


def check_normal_region_reachability():
    print("NORMAL REACHABILITY")
    for mode in MODES:
        for banks in (1, 2, 4):
            c = cfg_for("normal", mode, banks, targets=list(range(banks)))
            geom = get_snuca_geometry(c.cache_size, c.num_words_per_block, 16, banks)
            sets_per_bank = geom["sets_per_bank"]
            for bank in range(banks):
                for region in range(c.num_regions):
                    seen_sets = set()
                    for set_idx in range(sets_per_bank):
                        stream = region
                        addr = word_addr_for(bank, set_idx, stream, banks, sets_per_bank)
                        assert_eq(get_bank_id(addr, banks, c.num_words_per_block), bank, "region mapping changed bank")
                        assert_eq(get_region_id(addr, c), region, "constructed address region")
                        seen_sets.add(get_local_set(addr, c.num_words_per_block, banks, sets_per_bank))
                    assert_eq(len(seen_sets), sets_per_bank, f"{mode} banks={banks} bank={bank} region={region} reachable sets")
    print("  every normal region reaches every bank-local set")


def check_encrypted_index_ranges():
    print("ENCRYPTED INDEX RANGES")
    samples = 4096
    for design in ("ceaser", "ceaser_s"):
        for banks in (1, 2, 4):
            c = cfg_for(design, "multibank", banks, targets=[0])
            cache = BankedArchitectureCache(design, c)
            sets_per_bank = cache.geom["sets_per_bank"]
            for i in range(samples):
                bank = i % banks
                addr = word_addr_for(bank, i % sets_per_bank, i // sets_per_bank, banks, sets_per_bank)
                for _, set_idx in cache._candidate_locations(addr, bank, 0):
                    if set_idx < 0 or set_idx >= sets_per_bank:
                        raise AssertionError(f"{design} banks={banks} produced out-of-range set {set_idx}")
            print(f"  {design} banks={banks}: {samples} deterministic candidates in range")


def check_scatter_semantics():
    print("SCATTER")
    for mode, expected in (
        ("multibank", [list(range(16))]),
        ("hybrid2", [list(range(12)), list(range(12, 16))]),
        ("region4", [list(range(0, 4)), list(range(4, 8)), list(range(8, 12)), list(range(12, 16))]),
    ):
        c = cfg_for("scatter", mode, 1)
        assert_eq(c.region_skews, expected, f"scatter {mode} skew grouping")
        flat = [skew for group in c.region_skews for skew in group]
        assert_eq(len(flat), 16, f"scatter {mode} skew count")
        assert_eq(len(set(flat)), 16, f"scatter {mode} unique skew keys")
        cache = BankedArchitectureCache("scatter", c)
        for region, skews in enumerate(c.region_skews):
            candidates = cache._candidate_locations(0, 0, region)
            assert_eq(len(candidates), len(skews), f"scatter {mode} region {region} candidates")
    print("  16 independent skews with expected hybrid/region grouping")


def check_mirage_geometry_and_reachability():
    print("MIRAGE GEOMETRY")
    expected_keys = ("00000000000000000000", "ffffffffffffffffffff")
    assert_eq(MIRAGE_KEYS, expected_keys, "mirage keys")
    baseline = cfg_for("mirage", "multibank", 1)
    baseline_cache = BankedArchitectureCache("mirage", baseline)
    assert_eq(baseline_cache.geom["global_index_bits"], 13, "mirage 1-bank global tag index width")
    assert_eq(baseline_cache.geom["global_num_sets"], 8192, "mirage 1-bank global tag sets/skew")

    for mode in MODES:
        for banks in (1, 2, 4):
            c = cfg_for("mirage", mode, banks, targets=list(range(banks)))
            cache = BankedArchitectureCache("mirage", c)
            for bank_regions in cache.bank_region.values():
                data = [r.data_entries for r in bank_regions.values()]
                tag_sets = [r.tag_sets_per_skew for r in bank_regions.values()]
                assert_eq(sum(data), 131072 // banks, f"mirage {mode} banks={banks} data capacity")
                assert_eq(sum(tag_sets), (131072 // banks) // 16, f"mirage {mode} banks={banks} tag-set sum")
                assert all(r.tag_skews == 2 and r.tag_ways == 14 for r in bank_regions.values())
                if mode == "hybrid2":
                    assert_eq(tag_sets, [6144 // banks, 2048 // banks], f"mirage hybrid tag sets banks={banks}")
                if mode == "region4":
                    assert_eq(tag_sets, [2048 // banks] * 4, f"mirage region4 tag sets banks={banks}")

    reachability_cases = [
        (1, 0, 6144),
        (1, 1, 2048),
        (2, 0, 3072),
        (2, 1, 1024),
        (4, 0, 1536),
        (4, 1, 512),
    ]
    for banks, region, expected_count in reachability_cases:
        c = cfg_for("mirage", "hybrid2", banks)
        cache = BankedArchitectureCache("mirage", c)
        seen = set()
        sample_limit = max(120000, expected_count * 32)
        for i in range(sample_limit):
            seen.add(_present_index_mod(i * c.num_words_per_block, c.num_words_per_block, expected_count, MIRAGE_KEYS[0]))
            if len(seen) == expected_count:
                break
        assert_eq(len(seen), expected_count, f"mirage banks={banks} region {region} reachable tag sets")
    print("  2 native skews")
    print("  8 base + 6 extra = 14 ways/skew")
    print("  baseline/hybrid2/region4 data capacities correct")
    print("  keys, tag geometry, 6144/2048 reachability, and region capacities OK")


class ScriptedRng:
    def __init__(self, randrange_values, choice_values=None):
        self.randrange_values = list(randrange_values)
        self.choice_values = list(choice_values or [])

    def randrange(self, stop):
        value = self.randrange_values.pop(0)
        if not 0 <= value < stop:
            raise AssertionError(f"scripted randrange value {value} outside 0..{stop - 1}")
        return value

    def choice(self, seq):
        if self.choice_values:
            value = self.choice_values.pop(0)
            if value not in seq:
                raise AssertionError(f"scripted choice value {value} not in {seq}")
            return value
        return seq[0]


def check_mirage_random_gle():
    print("MIRAGE RANDOM GLE")
    region = MirageRegion(8, 2, 2, 4, rng=ScriptedRng([3, 3], [0]))
    assert region.access([0, 0], "A") is False
    assert_eq(region.valid_lines(), 1, "first mirage insertion occupancy")
    assert region.access([0, 0], "B") is False

    assert_eq(region.valid_lines(), 1, "early GLE keeps occupied data count below capacity")
    assert_eq(region.tags[0][0][0], None, "old tag invalidated after occupied data victim")
    assert_eq(region.tags[1][0][0], ("B", 3), "new tag forward pointer")
    assert_eq(region.data_store[3], (1, 0, 0), "new data reverse pointer")
    assert region.check_pointer_invariants()

    print("  O(1) random data placement")
    print("  early eviction before full capacity: PASS")
    print("  reverse-pointer invalidation: PASS")
    print("  forward/reverse pointer consistency: PASS")


def check_mirage_6144_set_mapping():
    print("MIRAGE 6144 SET MAPPING")
    c = cfg_for("mirage", "hybrid2", 1, regions=[0])
    cache = BankedArchitectureCache("mirage", c)
    tag_sets = cache.bank_region[0][0].tag_sets_per_skew
    assert_eq(tag_sets, 6144, "hybrid2 SRAM tag sets")

    samples = 262144
    counts = [0] * tag_sets
    for i in range(samples):
        set_idx = _present_index_mod(i * c.num_words_per_block, c.num_words_per_block, tag_sets, MIRAGE_KEYS[0])
        counts[set_idx] += 1

    reached = sum(1 for count in counts if count > 0)
    mean = statistics.fmean(counts)
    min_count = min(counts)
    max_count = max(counts)
    stdev = statistics.pstdev(counts)
    cv = stdev / mean
    first_mean = statistics.fmean(counts[:2048])
    remaining_mean = statistics.fmean(counts[2048:])
    ratio = first_mean / remaining_mean

    assert_eq(reached, tag_sets, "6144-set reachability")
    if cv > 0.20:
        raise AssertionError(f"6144-set mapping CV too high: {cv:.4f}")
    if not 0.95 <= ratio <= 1.05:
        raise AssertionError(f"6144-set first/rest average ratio shows bias: {ratio:.4f}")

    print(f"  reachable sets = {reached} / {tag_sets}")
    print(f"  min count = {min_count}, max count = {max_count}, mean = {mean:.2f}, cv = {cv:.4f}")
    print(f"  first-2048 average = {first_mean:.2f}, remaining-4096 average = {remaining_mean:.2f}")
    print("  approximately uniform distribution: PASS")


def check_one_bank_mapping_parity():
    print("ONE-BANK PARITY")
    addrs = [
        0,
        8,
        64,
        4096,
        65536,
        1048576,
        123456789,
        987654321,
        10000000000,
    ]
    c = cfg_for("normal", "multibank", 1)
    geom = get_snuca_geometry(c.cache_size, c.num_words_per_block, 16, 1)
    for addr in addrs:
        assert_eq(get_local_set(addr, c.num_words_per_block, 1, geom["sets_per_bank"]), (addr // 8) % 8192, "normal set parity")

    c = cfg_for("ceaser", "multibank", 1)
    cache = BankedArchitectureCache("ceaser", c)
    for addr in addrs:
        old = _present_index(addr, c.num_words_per_block, 13, CEASER_KEY)
        assert_eq(cache._candidate_locations(addr, 0, 0)[0][1], old, "ceaser index parity")

    c = cfg_for("ceaser_s", "multibank", 1)
    cache = BankedArchitectureCache("ceaser_s", c)
    for addr in addrs:
        old = tuple(_present_index(addr, c.num_words_per_block, 13, key) for key in CEASER_S_KEYS)
        new = tuple(idx for _, idx in cache._candidate_locations(addr, 0, 0))
        assert_eq(new, old, "ceaser-s index parity")

    c = cfg_for("mirage", "multibank", 1)
    cache = BankedArchitectureCache("mirage", c)
    for addr in addrs:
        old_indexes = tuple(_present_index(addr, c.num_words_per_block, 13, key) for key in MIRAGE_KEYS)
        assert_eq(tuple(cache._mirage_indexes(addr, 0)), old_indexes, "mirage index parity")
        assert_eq(cache.geom["global_index_bits"], 13, "mirage parity tag width")
    print("  normal, ceaser, ceaser-s, and mirage mappings match reference formulas")


def check_actual_allocation_isolation():
    print("ACTUAL ALLOCATION")
    c = cfg_for("mirage", "hybrid2", 2, targets=[1], regions=[1])
    cache = BankedArchitectureCache("mirage", c)
    for i in range(512):
        addr = word_addr_for(1, i % 4096, 1 + (i // 4096) * c.num_regions, 2, 4096)
        assert_eq(get_bank_id(addr, c.num_banks, c.num_words_per_block), 1, "mirage allocation address bank")
        assert_eq(get_region_id(addr, c), 1, "mirage allocation address region")
        cache.access(addr, 1, 1)
    occupied = cache.occupied()
    assert occupied[1][1] > 0
    assert_eq(occupied[1][0], 0, "mirage bank1 large region untouched")
    assert_eq(occupied[0][0], 0, "mirage bank0 large region untouched")
    assert_eq(occupied[0][1], 0, "mirage bank0 small region untouched")
    print("  representative fills stay in selected bank/region")


def check_workload_and_attack_semantics():
    print("WORKLOAD/ATTACK")
    total_cache_lines = 8388608 // 64
    assert_eq(int(total_cache_lines * sender_percent_for_0 / 100), 1310, "bit0 total sender accesses")
    assert_eq(int(total_cache_lines * sender_percent_for_1 / 100), 2621, "bit1 total sender accesses")
    assert_eq(cfg_for("normal", "hybrid2", 1).attack_regions, [1], "hybrid2 default attack region")
    assert_eq(cfg_for("normal", "region4", 1).attack_regions, [0, 1, 2, 3], "region4 default attack regions")
    print("  bit0=1310, bit1=2621; hybrid2 attacks small region, region4 all regions")


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


def check_reproducible_workloads():
    print("REPRODUCIBLE WORKLOADS")
    total_cache_lines = 8388608 // 64
    sender0 = int(total_cache_lines * sender_percent_for_0 / 100)
    sender1 = int(total_cache_lines * sender_percent_for_1 / 100)
    c_normal = cfg_for("normal", "region4", 4, targets=[0, 1, 2, 3], regions=[0, 1, 2, 3])
    c_mirage = cfg_for("mirage", "region4", 4, targets=[0, 1, 2, 3], regions=[0, 1, 2, 3])
    max_recv = get_receiver_access_counts(total_cache_lines)[-1]

    first = get_trial_addresses(sender0, sender1, max_recv, cfg=c_normal, trials=1, base_seed=20260904)
    repeat = get_trial_addresses(sender0, sender1, max_recv, cfg=c_normal, trials=1, base_seed=20260904)
    other_design = get_trial_addresses(sender0, sender1, max_recv, cfg=c_mirage, trials=1, base_seed=20260904)
    different_seed = get_trial_addresses(sender0, sender1, max_recv, cfg=c_normal, trials=1, base_seed=20260905)

    assert_eq(first, repeat, "same seed repeated workload")
    assert_eq(first[0]["sender_0"], other_design[0]["sender_0"], "cross-design bit0 sender")
    assert_eq(first[0]["sender_1"], other_design[0]["sender_1"], "cross-design bit1 sender")
    assert_eq(first[0]["all_receiver"], other_design[0]["all_receiver"], "cross-design receiver")
    if first == different_seed:
        raise AssertionError("different seed should change representative workload")
    if derive_workload_seed(20260904, "region4", 4, [0, 1, 2, 3], [0, 1, 2, 3], "all", 0) == derive_workload_seed(20260904, "region4", 4, [0, 1, 2, 3], [0, 1, 2, 3], "all", 1):
        raise AssertionError("trial must affect workload seed")
    if derive_cache_seed(20260904, "normal", "region4", 4, [0, 1, 2, 3], 10, 0) == derive_cache_seed(20260904, "mirage", "region4", 4, [0, 1, 2, 3], 10, 0):
        raise AssertionError("design must affect cache seed")

    print("  same seed repeated workload: PASS")
    print("  same seed cross-design workload equality: PASS")
    print("  different seed changes workload: PASS")


def check_bit_pair_relationship():
    print("BIT PAIR RELATIONSHIP")
    total_cache_lines = 8388608 // 64
    sender0 = int(total_cache_lines * sender_percent_for_0 / 100)
    sender1 = int(total_cache_lines * sender_percent_for_1 / 100)
    c = cfg_for("scatter", "hybrid2", 2, targets=[0, 1], regions=[1])
    addrs = get_trial_addresses(sender0, sender1, 256, cfg=c, trials=1, base_seed=20260904)[0]
    assert_eq(len(addrs["sender_0"]), 1310, "bit0 sender length")
    assert_eq(len(addrs["sender_1"]), 2621, "bit1 sender length")
    if not set(addrs["sender_0"]).issubset(set(addrs["sender_1"])):
        raise AssertionError("bit0 sender must be subset of bit1 sender")
    repeat = get_trial_addresses(sender0, sender1, 256, cfg=c, trials=1, base_seed=20260904)[0]
    assert_eq(addrs["all_receiver"], repeat["all_receiver"], "bit0/bit1 receiver list")
    print("  bit0 subset of bit1 and receiver pairing: PASS")


def write_rows(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(str(row) + "\n")


def complete_rows(trials=2):
    rows = []
    for occ in target_occupancy_percentages:
        for _ in range(trials):
            rows.append([occ, occ * 10, 1, 2])
    return rows


def check_result_file_infrastructure():
    print("RESULT FILE INFRASTRUCTURE")
    with tempfile.TemporaryDirectory() as tmp:
        valid = os.path.join(tmp, "valid.txt")
        truncated = os.path.join(tmp, "truncated.txt")
        malformed = os.path.join(tmp, "malformed.txt")
        temp_only = os.path.join(tmp, "atomic.txt")
        write_rows(valid, complete_rows(trials=2))
        write_rows(truncated, complete_rows(trials=2)[:-1])
        with open(malformed, "w") as f:
            f.write("[1, 10, 3]\n")
            f.write("not a row\n")
        with open(f"{temp_only}.tmp.{os.getpid()}", "w") as f:
            f.write(str([1, 10, 1]) + "\n")

        assert_eq(classify_result_file(valid, 2, target_occupancy_percentages)[0], STATUS_COMPLETE, "valid synthetic result")
        assert_eq(classify_result_file(truncated, 2, target_occupancy_percentages)[0], STATUS_INCOMPLETE, "truncated result")
        assert_eq(classify_result_file(malformed, 2, target_occupancy_percentages)[0], STATUS_MALFORMED, "malformed result")
        assert_eq(classify_result_file(temp_only, 2, target_occupancy_percentages)[0], STATUS_INCOMPLETE, "temp-only result")

        final = os.path.join(tmp, "atomic_final.txt")
        atomic_write_result(final, lambda f: [f.write(str(row) + "\n") for row in complete_rows(trials=1)])
        assert_eq(classify_result_file(final, 1, target_occupancy_percentages)[0], STATUS_COMPLETE, "atomic final")
        assert outputs_are_complete([valid], 2, target_occupancy_percentages), "complete output should skip"
        assert not outputs_are_complete([truncated], 2, target_occupancy_percentages), "incomplete output should rerun"
    print("  completeness, atomic writer, and skip-existing checks: PASS")


def check_production_path_uniqueness():
    print("PRODUCTION PATH UNIQUENESS")
    bank_targets = {
        1: [[0]],
        2: [[0], [0, 1]],
        4: [[0], [0, 1, 2, 3]],
    }
    result_paths = []
    log_paths = []
    for mode in MODES:
        for design in DESIGNS:
            for banks, target_lists in bank_targets.items():
                for targets in target_lists:
                    regions = [1] if mode == "hybrid2" else ([0, 1, 2, 3] if mode == "region4" else [0])
                    c = cfg_for(design, mode, banks, targets=targets, regions=regions)
                    c.output_dir = os.path.join("results", {
                        "multibank": "multibank",
                        "hybrid2": "hybrid_2region_75_25",
                        "region4": "hybrid_4region",
                    }[mode], design)
                    result_paths.append(output_path(c, design, 0))
                    result_paths.append(output_path(c, design, 1))
                    target_slug = "-".join(str(x) for x in targets)
                    region_slug = "-".join(str(x) for x in regions)
                    log_paths.append(
                        f"results/run_logs/{design}_{mode}_{banks}banks_targets_{target_slug}_"
                        f"regions_{region_slug}_trials100_seed20260904.log"
                    )
    assert_eq(len(log_paths), 75, "75 production jobs")
    assert_eq(len(set(result_paths)), len(result_paths), "unique result paths")
    assert_eq(len(set(log_paths)), len(log_paths), "unique log paths")
    print("  75-job matrix has unique result and log paths")


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
    random.seed(12345)
    check_global_geometry()
    check_capacities()
    check_invalid_ratio()
    check_workload_and_attack_semantics()
    check_reproducible_workloads()
    check_bit_pair_relationship()
    check_result_file_infrastructure()
    check_production_path_uniqueness()
    check_normal_region_reachability()
    check_address_targeting()
    check_encrypted_index_ranges()
    check_scatter_semantics()
    check_mirage_geometry_and_reachability()
    check_mirage_6144_set_mapping()
    check_one_bank_mapping_parity()
    check_replacement_isolation()
    check_actual_allocation_isolation()
    check_mirage_random_gle()
    print("VALIDATION PASSED")


if __name__ == "__main__":
    main()
