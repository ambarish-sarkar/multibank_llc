#!/usr/bin/env python3
import importlib
import math
import os
import random
import sys

from common import (
    BYTES_PER_WORD,
    get_bank_id,
    get_block_number,
    get_local_set,
    get_snuca_geometry,
    require_power_of_two,
)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_SIZE = 8388608
NUM_WORDS_PER_BLOCK = 8
NUM_BLOCKS_PER_SET = 8
NUM_ADDR_BITS = 64
NUM_PARTITIONS = {
    "Normal_cache_occupancy": 1,
    "Ceaser_cache_occupancy": 1,
    "Ceaser-s_cache_occupancy": 2,
    "ScatterCache_cache_occupancy": 2,
}
MIRAGE_DESIGN = "Mirage_cache_occupancy"
MIRAGE_PARTITIONS = 2
MIRAGE_ADDITIONAL_TAGS = 6
MIRAGE_TAG_WAYS = NUM_BLOCKS_PER_SET + MIRAGE_ADDITIONAL_TAGS
MIRAGE_GLOBAL_DATA_BLOCKS = 131072
MIRAGE_GLOBAL_SETS_PER_SKEW = 8192
MIRAGE_GLOBAL_TAG_ENTRIES = 229376


def clear_design_modules():
    for name in ("reference", "bin_addr", "word_addr", "present", "cache", "hybrid_wrapper_cache"):
        sys.modules.pop(name, None)


def import_design_module(design_dir, module_name):
    clear_design_modules()
    design_path = os.path.join(BASE_DIR, design_dir)
    sys.path.insert(0, design_path)
    try:
        return importlib.import_module(module_name)
    finally:
        sys.path.pop(0)


def import_design_modules(design_dir):
    clear_design_modules()
    design_path = os.path.join(BASE_DIR, design_dir)
    sys.path.insert(0, design_path)
    try:
        return (
            importlib.import_module("reference"),
            importlib.import_module("cache"),
            importlib.import_module("hybrid_wrapper_cache"),
        )
    finally:
        sys.path.pop(0)


def make_reference(ref_mod, design_dir, word_address, banks, target_bank):
    partitions = NUM_PARTITIONS[design_dir]
    geom = get_snuca_geometry(CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks)
    offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
    tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits
    ways_per_partition = NUM_BLOCKS_PER_SET // partitions
    kwargs = {"target_region": target_bank}
    if design_dir == "Normal_cache_occupancy":
        kwargs.update(
            {
                "num_banks": banks,
                "sets_per_bank": geom["sets_per_bank"],
                "snuca_indexing": True,
            }
        )
    return ref_mod.Reference(
        word_address,
        NUM_ADDR_BITS,
        offset_bits,
        geom["local_index_bits"],
        tag_bits,
        partitions,
        ways_per_partition,
        **kwargs,
    )


def make_wrapper(wrapper_mod, design_dir, banks):
    geom = get_snuca_geometry(CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks)
    return wrapper_mod.HybridWrapperCache(
        num_regions=banks,
        region_split_ratio=0.5,
        num_sets=geom["sets_per_bank"],
        num_index_bits=geom["local_index_bits"],
        num_partitions=NUM_PARTITIONS[design_dir],
        num_blocks_per_set=NUM_BLOCKS_PER_SET,
    )


def allocated_lines(cache_obj, partitions):
    total = 0
    for blocks in cache_obj.values():
        if blocks and isinstance(blocks[0], dict) and "valid" in blocks[0]:
            total += sum(1 for block in blocks if block.get("valid") == 1)
        else:
            total += len(blocks)
    return total


def physical_capacity(wrapper, partitions):
    per_bank = []
    ways_per_partition = wrapper._ways_total // partitions
    for bank_cache in wrapper.region_caches:
        per_bank.append(len(bank_cache) * ways_per_partition)
    return per_bank


def print_geometry():
    print("Banks | Sets/bank | Ways | Aggregate lines")
    for banks in (1, 2, 4, 8, 16):
        geom = get_snuca_geometry(
            CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks
        )
        print(
            f"{banks} | {geom['sets_per_bank']} | "
            f"{NUM_BLOCKS_PER_SET} | {geom['aggregate_lines']}"
        )
        assert geom["aggregate_lines"] == 131072
        assert NUM_BLOCKS_PER_SET == 8


def check_actual_wrapper_capacity():
    for design_dir in NUM_PARTITIONS:
        _, _, wrapper_mod = import_design_modules(design_dir)
        partitions = NUM_PARTITIONS[design_dir]
        for banks in (1, 2, 4, 8, 16):
            wrapper = make_wrapper(wrapper_mod, design_dir, banks)
            capacities = physical_capacity(wrapper, partitions)
            geom = get_snuca_geometry(
                CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks
            )
            assert all(cap == geom["sets_per_bank"] * NUM_BLOCKS_PER_SET for cap in capacities)
            assert sum(capacities) == 131072
            assert wrapper._ways_total == 8
    print("Actual wrapper capacity OK")


def check_normal_mapping():
    print("\nNormal 2-bank mapping:")
    normal_ref = import_design_module("Normal_cache_occupancy", "reference")
    geom = get_snuca_geometry(CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, 2)
    offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
    tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits

    expected = []
    for block in range(6):
        word_address = block * NUM_WORDS_PER_BLOCK
        bank_id = get_bank_id(word_address, 2, NUM_WORDS_PER_BLOCK)
        local_set = get_local_set(
            word_address, NUM_WORDS_PER_BLOCK, 2, geom["sets_per_bank"]
        )
        ref = normal_ref.Reference(
            word_address,
            NUM_ADDR_BITS,
            offset_bits,
            geom["local_index_bits"],
            tag_bits,
            1,
            NUM_BLOCKS_PER_SET,
            target_region=bank_id,
            num_banks=2,
            sets_per_bank=geom["sets_per_bank"],
            snuca_indexing=True,
        )
        actual_set = int(ref.index, 2)
        expected.append((block, bank_id, local_set))
        print(
            f"block {block} -> word {word_address}, "
            f"bank {bank_id}, local set {actual_set}"
        )
        assert actual_set == local_set

    assert expected == [
        (0, 0, 0),
        (1, 1, 0),
        (2, 0, 1),
        (3, 1, 1),
        (4, 0, 2),
        (5, 1, 2),
    ]

    for banks in (1, 2, 4, 8, 16):
        geom = get_snuca_geometry(
            CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks
        )
        seen = {bank: set() for bank in range(banks)}
        for bank in range(banks):
            for local_set in range(geom["sets_per_bank"]):
                block = local_set * banks + bank
                word_address = block * NUM_WORDS_PER_BLOCK
                seen[bank].add(
                    get_local_set(
                        word_address,
                        NUM_WORDS_PER_BLOCK,
                        banks,
                        geom["sets_per_bank"],
                    )
                )
        for bank, local_sets in seen.items():
            assert len(local_sets) == geom["sets_per_bank"], (banks, bank)


def check_randomized_design(design_dir, display_name, expected_encrypts_per_ref):
    ref_mod = import_design_module(design_dir, "reference")
    bin_mod = sys.modules["bin_addr"]
    original_present = bin_mod.Present
    calls = {"count": 0}

    class CountingPresent:
        def __init__(self, key):
            self.impl = original_present(key)

        def encrypt(self, plaintext):
            calls["count"] += 1
            return self.impl.encrypt(plaintext)

    bin_mod.Present = CountingPresent
    try:
        partitions = NUM_PARTITIONS[design_dir]
        for banks in (1, 2, 4, 8, 16):
            geom = get_snuca_geometry(
                CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, banks
            )
            offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
            tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits
            ways_per_partition = NUM_BLOCKS_PER_SET // partitions
            before = calls["count"]
            refs = []
            for block in range(8):
                word_address = block * NUM_WORDS_PER_BLOCK
                refs.append(
                    ref_mod.Reference(
                        word_address,
                        NUM_ADDR_BITS,
                        offset_bits,
                        geom["local_index_bits"],
                        tag_bits,
                        partitions,
                        ways_per_partition,
                        target_region=get_bank_id(
                            word_address, banks, NUM_WORDS_PER_BLOCK
                        ),
                    )
                )

            for ref in refs:
                if isinstance(ref.index, tuple):
                    assert len(ref.index) == partitions
                    for index in ref.index:
                        assert 0 <= int(index, 2) < geom["sets_per_bank"]
                else:
                    if partitions > 1:
                        assert len(ref.index) == partitions * geom["local_index_bits"]
                        for part in range(partitions):
                            start = len(ref.index) - ((part + 1) * geom["local_index_bits"])
                            end = len(ref.index) - (part * geom["local_index_bits"])
                            assert 0 <= int(ref.index[start:end], 2) < geom["sets_per_bank"]
                    else:
                        assert 0 <= int(ref.index, 2) < geom["sets_per_bank"]

                expected_tag = ref.bin_addr.get_tag(tag_bits)
                assert ref.tag == expected_tag

            encrypts = calls["count"] - before
            assert encrypts == expected_encrypts_per_ref * len(refs), (
                display_name,
                banks,
                encrypts,
            )
        print(f"{display_name}: randomized bank-local indexing OK")
    finally:
        bin_mod.Present = original_present


def check_bank_isolation_for_design(design_dir, display_name):
    ref_mod, _, wrapper_mod = import_design_modules(design_dir)
    banks = 2
    for target_bank in (0, 1):
        random.seed(100 + target_bank)
        wrapper = make_wrapper(wrapper_mod, design_dir, banks)
        word_address = target_bank * NUM_WORDS_PER_BLOCK

        ref = make_reference(ref_mod, design_dir, word_address, banks, target_bank)
        wrapper.read_refs_explicit(NUM_WORDS_PER_BLOCK, "rand", [ref], strict_region=True)
        assert ref.cache_status.name == "miss", (display_name, target_bank)
        assert ref.region == target_bank

        ref_again = make_reference(ref_mod, design_dir, word_address, banks, target_bank)
        wrapper.read_refs_explicit(
            NUM_WORDS_PER_BLOCK, "rand", [ref_again], strict_region=True
        )
        assert ref_again.cache_status.name == "hit", (display_name, target_bank)
        assert ref_again.region == target_bank

        other_bank = 1 - target_bank
        assert allocated_lines(wrapper.region_caches[target_bank], NUM_PARTITIONS[design_dir]) == 1
        assert allocated_lines(wrapper.region_caches[other_bank], NUM_PARTITIONS[design_dir]) == 0

        invalid_ref = make_reference(ref_mod, design_dir, word_address, banks, target_bank)
        invalid_ref.target_region = banks
        try:
            wrapper.read_refs_explicit(
                NUM_WORDS_PER_BLOCK, "rand", [invalid_ref], strict_region=True
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"{display_name}: invalid bank did not raise")

        try:
            wrapper.read_refs_explicit(
                NUM_WORDS_PER_BLOCK, "rand", [ref_again], strict_region=False
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"{display_name}: cross-bank probing did not raise")

    print(f"{display_name}: bank isolation and allocation behavior OK")


def check_one_bank_equivalence():
    for design_dir in NUM_PARTITIONS:
        ref_mod, cache_mod, wrapper_mod = import_design_modules(design_dir)
        partitions = NUM_PARTITIONS[design_dir]
        geom = get_snuca_geometry(CACHE_SIZE, NUM_WORDS_PER_BLOCK, NUM_BLOCKS_PER_SET, 1)
        offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
        tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits
        ways_per_partition = NUM_BLOCKS_PER_SET // partitions
        word_addresses = [0, 8, 16, 24, 8192 * 8, 8193 * 8, 20000 * 8, 30000 * 8]

        def refs(seed):
            random.seed(seed)
            out = []
            for word_address in word_addresses:
                kwargs = {"target_region": 0}
                if design_dir == "Normal_cache_occupancy":
                    kwargs.update(
                        {
                            "num_banks": 1,
                            "sets_per_bank": geom["sets_per_bank"],
                            "snuca_indexing": True,
                        }
                    )
                out.append(
                    ref_mod.Reference(
                        word_address,
                        NUM_ADDR_BITS,
                        offset_bits,
                        geom["local_index_bits"],
                        tag_bits,
                        partitions,
                        ways_per_partition,
                        **kwargs,
                    )
                )
            return out

        direct_refs = refs(55)
        wrapper_refs = refs(55)
        random.seed(77)
        direct_cache = cache_mod.Cache(
            num_sets=geom["sets_per_bank"],
            num_index_bits=geom["local_index_bits"],
            num_partitions=partitions,
            ways_per_partition=ways_per_partition,
        )
        direct_cache.read_refs(
            NUM_BLOCKS_PER_SET, NUM_WORDS_PER_BLOCK, partitions, "rand", direct_refs
        )

        random.seed(77)
        wrapper = make_wrapper(wrapper_mod, design_dir, 1)
        wrapper.read_refs_explicit(
            NUM_WORDS_PER_BLOCK, "rand", wrapper_refs, strict_region=True
        )

        assert physical_capacity(wrapper, partitions) == [131072]
        assert [r.cache_status.name for r in direct_refs] == [
            r.cache_status.name for r in wrapper_refs
        ]
        assert [r.index for r in direct_refs] == [r.index for r in wrapper_refs]
        assert [r.tag for r in direct_refs] == [r.tag for r in wrapper_refs]
    print("One-bank wrapper equivalence OK")


def get_mirage_geometry(banks):
    require_power_of_two(banks, "num_banks")
    global_data_blocks = (CACHE_SIZE // BYTES_PER_WORD) // NUM_WORDS_PER_BLOCK
    if global_data_blocks != MIRAGE_GLOBAL_DATA_BLOCKS:
        raise AssertionError(global_data_blocks)
    if global_data_blocks % banks != 0:
        raise ValueError("MIRAGE data blocks must be divisible by banks")

    global_sets_per_skew_num = global_data_blocks // MIRAGE_PARTITIONS
    if global_sets_per_skew_num % NUM_BLOCKS_PER_SET != 0:
        raise ValueError("MIRAGE data blocks/skew must divide by data ways")
    global_sets_per_skew = global_sets_per_skew_num // NUM_BLOCKS_PER_SET
    if global_sets_per_skew != MIRAGE_GLOBAL_SETS_PER_SKEW:
        raise AssertionError(global_sets_per_skew)
    if global_sets_per_skew % banks != 0:
        raise ValueError("MIRAGE sets/skew must be divisible by banks")

    sets_per_skew_per_bank = global_sets_per_skew // banks
    require_power_of_two(sets_per_skew_per_bank, "sets_per_skew_per_bank")
    data_blocks_per_bank = global_data_blocks // banks
    tag_blocks_per_skew_per_bank = sets_per_skew_per_bank * MIRAGE_TAG_WAYS
    total_tag_entries = (
        banks * MIRAGE_PARTITIONS * tag_blocks_per_skew_per_bank
    )
    total_data_blocks = banks * data_blocks_per_bank
    return {
        "global_data_blocks": global_data_blocks,
        "data_blocks_per_bank": data_blocks_per_bank,
        "global_sets_per_skew": global_sets_per_skew,
        "sets_per_skew_per_bank": sets_per_skew_per_bank,
        "global_index_bits": int(math.log2(global_sets_per_skew)),
        "local_index_bits": int(math.log2(sets_per_skew_per_bank)),
        "tag_blocks_per_skew_per_bank": tag_blocks_per_skew_per_bank,
        "total_tag_entries": total_tag_entries,
        "total_data_blocks": total_data_blocks,
        "tag_data_ratio": total_tag_entries / total_data_blocks,
    }


def make_mirage_reference(ref_mod, word_address, banks, target_bank):
    geom = get_mirage_geometry(banks)
    offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
    tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits
    return ref_mod.Reference(
        word_address,
        NUM_ADDR_BITS,
        offset_bits,
        geom["local_index_bits"],
        tag_bits,
        MIRAGE_PARTITIONS,
        geom["tag_blocks_per_skew_per_bank"],
        target_region=target_bank,
    )


def make_mirage_wrapper(wrapper_mod, banks):
    geom = get_mirage_geometry(banks)
    return wrapper_mod.HybridWrapperCache(
        num_regions=banks,
        region_split_ratio=0.5,
        num_data_blocks=geom["data_blocks_per_bank"],
        num_sets_per_skew=geom["sets_per_skew_per_bank"],
        num_index_bits=geom["local_index_bits"],
        num_partitions=MIRAGE_PARTITIONS,
        num_tag_blocks_per_skew=geom["tag_blocks_per_skew_per_bank"],
        num_addr_bits=NUM_ADDR_BITS,
        num_offset_bits=int(math.log2(NUM_WORDS_PER_BLOCK)),
        num_total_ways=MIRAGE_TAG_WAYS,
    )


def mirage_valid_tags(cache_obj):
    return sum(
        1
        for blocks in cache_obj.values()
        for block in blocks
        if block.get("valid") == 1
    )


def mirage_valid_data(cache_obj):
    return sum(
        1
        for entry in cache_obj.data_store
        if entry != -1 and entry[1] == "valid"
    )


def mirage_tag_entries(cache_obj):
    return sum(len(blocks) for blocks in cache_obj.values())


def check_mirage_actual_geometry():
    _, _, wrapper_mod = import_design_modules(MIRAGE_DESIGN)
    print("\nMIRAGE geometry:")
    print("Banks | Data blocks/bank | Sets/skew/bank | Tag ways | Skews | Total tags")
    for banks in (1, 2, 4, 8, 16):
        geom = get_mirage_geometry(banks)
        wrapper = make_mirage_wrapper(wrapper_mod, banks)
        aggregate_data = 0
        aggregate_tags = 0
        for bank_id, bank_cache in wrapper.region_caches.items():
            assert len(bank_cache.data_store) == geom["data_blocks_per_bank"]
            assert len(bank_cache) == geom["sets_per_skew_per_bank"] * MIRAGE_PARTITIONS
            assert mirage_tag_entries(bank_cache) == (
                geom["tag_blocks_per_skew_per_bank"] * MIRAGE_PARTITIONS
            )
            for blocks in bank_cache.values():
                assert len(blocks) == MIRAGE_TAG_WAYS, (banks, bank_id)
            aggregate_data += len(bank_cache.data_store)
            aggregate_tags += mirage_tag_entries(bank_cache)

        assert aggregate_data == MIRAGE_GLOBAL_DATA_BLOCKS
        assert aggregate_tags == MIRAGE_GLOBAL_TAG_ENTRIES
        assert aggregate_tags / aggregate_data == 1.75
        print(
            f"{banks} | {geom['data_blocks_per_bank']} | "
            f"{geom['sets_per_skew_per_bank']} | {MIRAGE_TAG_WAYS} | "
            f"{MIRAGE_PARTITIONS} | {aggregate_tags}"
        )
    print("MIRAGE actual geometry OK")


def check_mirage_index_range_and_encryption():
    ref_mod = import_design_module(MIRAGE_DESIGN, "reference")
    bin_mod = sys.modules["bin_addr"]
    original_present = bin_mod.Present
    calls = {"count": 0}

    class CountingPresent:
        def __init__(self, key):
            self.impl = original_present(key)

        def encrypt(self, plaintext):
            calls["count"] += 1
            return self.impl.encrypt(plaintext)

    bin_mod.Present = CountingPresent
    try:
        for banks in (1, 2, 4, 8, 16):
            geom = get_mirage_geometry(banks)
            before = calls["count"]
            refs = []
            for block in range(16):
                word_address = block * NUM_WORDS_PER_BLOCK
                refs.append(
                    make_mirage_reference(
                        ref_mod,
                        word_address,
                        banks,
                        get_bank_id(word_address, banks, NUM_WORDS_PER_BLOCK),
                    )
                )
            for ref in refs:
                assert isinstance(ref.index, tuple)
                assert len(ref.index) == MIRAGE_PARTITIONS
                for index in ref.index:
                    assert 0 <= int(index, 2) < geom["sets_per_skew_per_bank"]

                tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - int(
                    math.log2(NUM_WORDS_PER_BLOCK)
                )
                assert ref.tag == ref.bin_addr.get_tag(tag_bits)

            encrypts = calls["count"] - before
            assert encrypts == 2 * len(refs), (banks, encrypts)
    finally:
        bin_mod.Present = original_present
    print("MIRAGE encrypted bank-local indexes OK")


def check_mirage_pointer_locality(bank_cache, selected_bank, num_index_bits):
    valid_entries = []
    for blocks in bank_cache.values():
        for block in blocks:
            if block.get("valid") == 1:
                valid_entries.append(block)
    assert len(valid_entries) == 1, (selected_bank, len(valid_entries))
    block = valid_entries[0]
    fptr = block["fptr"]
    assert isinstance(fptr, int), (selected_bank, fptr)
    assert 0 <= fptr < len(bank_cache.data_store), (selected_bank, fptr)
    data_entry = bank_cache.data_store[fptr]
    assert data_entry != -1
    assert data_entry[1] == "valid"

    rptr_entry = data_entry[0][0:(num_index_bits + 1)]
    rptr_way = int(data_entry[0][(num_index_bits + 1):])
    assert rptr_entry in bank_cache, (selected_bank, rptr_entry)
    assert 0 <= rptr_way < MIRAGE_TAG_WAYS, (selected_bank, rptr_way)
    assert bank_cache[rptr_entry][rptr_way]["fptr"] == fptr


def check_mirage_bank_isolation_and_pointers():
    ref_mod, _, wrapper_mod = import_design_modules(MIRAGE_DESIGN)
    banks = 2
    for target_bank in (0, 1):
        geom = get_mirage_geometry(banks)
        random.seed(500 + target_bank)
        wrapper = make_mirage_wrapper(wrapper_mod, banks)
        word_address = target_bank * NUM_WORDS_PER_BLOCK
        ref = make_mirage_reference(ref_mod, word_address, banks, target_bank)
        wrapper.read_refs_explicit(NUM_WORDS_PER_BLOCK, "rand", [ref], strict_region=True)
        assert ref.cache_status.name == "miss"
        assert ref.region == target_bank

        ref_again = make_mirage_reference(ref_mod, word_address, banks, target_bank)
        wrapper.read_refs_explicit(
            NUM_WORDS_PER_BLOCK, "rand", [ref_again], strict_region=True
        )
        assert ref_again.cache_status.name == "hit"
        assert ref_again.region == target_bank

        other_bank = 1 - target_bank
        assert mirage_valid_tags(wrapper.region_caches[target_bank]) == 1
        assert mirage_valid_data(wrapper.region_caches[target_bank]) == 1
        assert mirage_valid_tags(wrapper.region_caches[other_bank]) == 0
        assert mirage_valid_data(wrapper.region_caches[other_bank]) == 0
        check_mirage_pointer_locality(
            wrapper.region_caches[target_bank], target_bank, geom["local_index_bits"]
        )

        invalid_ref = make_mirage_reference(ref_mod, word_address, banks, target_bank)
        invalid_ref.target_region = banks
        try:
            wrapper.read_refs_explicit(
                NUM_WORDS_PER_BLOCK, "rand", [invalid_ref], strict_region=True
            )
        except ValueError:
            pass
        else:
            raise AssertionError("MIRAGE invalid bank did not raise")

        try:
            wrapper.read_refs_explicit(
                NUM_WORDS_PER_BLOCK, "rand", [ref_again], strict_region=False
            )
        except ValueError:
            pass
        else:
            raise AssertionError("MIRAGE cross-bank probing did not raise")
    print("MIRAGE bank isolation and pointer locality OK")


def check_mirage_one_bank_equivalence():
    ref_mod, cache_mod, wrapper_mod = import_design_modules(MIRAGE_DESIGN)
    geom = get_mirage_geometry(1)
    offset_bits = int(math.log2(NUM_WORDS_PER_BLOCK))
    tag_bits = NUM_ADDR_BITS - geom["global_index_bits"] - offset_bits
    word_addresses = [0, 8, 16, 24, 8192 * 8, 8193 * 8, 20000 * 8, 30000 * 8]

    def refs():
        return [
            ref_mod.Reference(
                word_address,
                NUM_ADDR_BITS,
                offset_bits,
                geom["local_index_bits"],
                tag_bits,
                MIRAGE_PARTITIONS,
                geom["tag_blocks_per_skew_per_bank"],
                target_region=0,
            )
            for word_address in word_addresses
        ]

    direct_refs = refs()
    wrapper_refs = refs()
    assert [r.index for r in direct_refs] == [r.index for r in wrapper_refs]
    assert [r.tag for r in direct_refs] == [r.tag for r in wrapper_refs]

    random.seed(777)
    direct_cache = cache_mod.Cache(
        num_data_blocks=geom["data_blocks_per_bank"],
        num_sets_per_skew=geom["sets_per_skew_per_bank"],
        num_index_bits=geom["local_index_bits"],
        num_partitions=MIRAGE_PARTITIONS,
        num_tag_blocks_per_skew=geom["tag_blocks_per_skew_per_bank"],
        num_addr_bits=NUM_ADDR_BITS,
        num_offset_bits=offset_bits,
        num_total_ways=MIRAGE_TAG_WAYS,
    )
    direct_cache.read_refs(
        MIRAGE_TAG_WAYS,
        MIRAGE_PARTITIONS,
        "rand",
        NUM_WORDS_PER_BLOCK,
        geom["local_index_bits"],
        direct_refs,
    )

    random.seed(777)
    wrapper = make_mirage_wrapper(wrapper_mod, 1)
    wrapper.read_refs_explicit(
        NUM_WORDS_PER_BLOCK, "rand", wrapper_refs, strict_region=True
    )

    assert len(wrapper.region_caches) == 1
    assert len(wrapper.region_caches[0].data_store) == geom["data_blocks_per_bank"]
    assert mirage_tag_entries(wrapper.region_caches[0]) == MIRAGE_GLOBAL_TAG_ENTRIES
    assert [r.cache_status.name for r in direct_refs] == [
        r.cache_status.name for r in wrapper_refs
    ]

    direct_again = refs()
    wrapper_again = refs()
    random.seed(778)
    direct_cache.read_refs(
        MIRAGE_TAG_WAYS,
        MIRAGE_PARTITIONS,
        "rand",
        NUM_WORDS_PER_BLOCK,
        geom["local_index_bits"],
        direct_again,
    )
    random.seed(778)
    wrapper.read_refs_explicit(
        NUM_WORDS_PER_BLOCK, "rand", wrapper_again, strict_region=True
    )
    assert [r.cache_status.name for r in direct_again] == [
        r.cache_status.name for r in wrapper_again
    ]
    assert all(r.cache_status.name == "hit" for r in wrapper_again)
    print("MIRAGE one-bank wrapper equivalence OK")


def check_mirage_error_handling():
    try:
        get_mirage_geometry(3)
    except ValueError:
        pass
    else:
        raise AssertionError("MIRAGE non-power-of-two bank count did not raise")
    print("MIRAGE error handling OK")


def main():
    print_geometry()
    check_actual_wrapper_capacity()
    check_normal_mapping()
    check_randomized_design("Ceaser_cache_occupancy", "CEASER", 1)
    check_randomized_design("Ceaser-s_cache_occupancy", "CEASER-S", 2)
    check_randomized_design("ScatterCache_cache_occupancy", "ScatterCache", 1)
    check_bank_isolation_for_design("Normal_cache_occupancy", "Normal")
    check_bank_isolation_for_design("Ceaser_cache_occupancy", "CEASER")
    check_bank_isolation_for_design("Ceaser-s_cache_occupancy", "CEASER-S")
    check_bank_isolation_for_design("ScatterCache_cache_occupancy", "ScatterCache")
    check_one_bank_equivalence()
    check_mirage_actual_geometry()
    check_mirage_index_range_and_encryption()
    check_mirage_bank_isolation_and_pointers()
    check_mirage_one_bank_equivalence()
    check_mirage_error_handling()
    print("\nS-NUCA validation passed")


if __name__ == "__main__":
    main()
