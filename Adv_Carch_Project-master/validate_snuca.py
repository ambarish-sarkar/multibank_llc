#!/usr/bin/env python3
import importlib
import math
import os
import sys

from common import (
    BYTES_PER_WORD,
    get_bank_id,
    get_block_number,
    get_local_set,
    get_snuca_geometry,
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


def clear_design_modules():
    for name in ("reference", "bin_addr", "word_addr", "present", "cache"):
        sys.modules.pop(name, None)


def import_design_module(design_dir, module_name):
    clear_design_modules()
    design_path = os.path.join(BASE_DIR, design_dir)
    sys.path.insert(0, design_path)
    try:
        return importlib.import_module(module_name)
    finally:
        sys.path.pop(0)


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


def main():
    print_geometry()
    check_normal_mapping()
    check_randomized_design("Ceaser_cache_occupancy", "CEASER", 1)
    check_randomized_design("Ceaser-s_cache_occupancy", "CEASER-S", 2)
    check_randomized_design("ScatterCache_cache_occupancy", "ScatterCache", 1)
    print("\nS-NUCA validation passed")


if __name__ == "__main__":
    main()
