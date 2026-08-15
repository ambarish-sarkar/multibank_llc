#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulator for occupancy-based covert channel with Multi-BANK/REGION Mirage cache
"""

import math
import os
import sys
from collections import OrderedDict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from common import get_bank_id as get_snuca_bank_id
from common import require_power_of_two

from hybrid_wrapper_cache import HybridWrapperCache
from bin_addr import BinaryAddress
from reference import Reference
from table import Table


REF_COL_NAMES = ('WordAddr', 'BinAddr', 'Tag', 'Partition', 'Index', 'Offset', 'Hit/Miss', 'SAE/GL')
MIN_BITS_PER_GROUP = 4
DEFAULT_TABLE_WIDTH = 180


class Simulator(object):

    def get_bank_id(self, address, num_banks, num_words_per_block):
        return get_snuca_bank_id(address, num_banks, num_words_per_block)

    def get_mirage_snuca_geometry(
        self,
        cache_size,
        num_words_per_block,
        num_blocks_per_set,
        num_additional_tags,
        num_partitions,
        num_banks,
    ):
        require_power_of_two(num_words_per_block, "num_words_per_block")
        require_power_of_two(num_blocks_per_set, "num_blocks_per_set")
        require_power_of_two(num_banks, "num_banks")

        global_data_blocks = (cache_size // 8) // num_words_per_block
        if global_data_blocks <= 0:
            raise ValueError("MIRAGE global data blocks must be non-zero")
        if global_data_blocks % num_banks != 0:
            raise ValueError("MIRAGE data blocks must be divisible by num_banks")
        if global_data_blocks % num_partitions != 0:
            raise ValueError("MIRAGE data blocks must be divisible by skews")

        data_blocks_per_bank = global_data_blocks // num_banks
        tag_ways = num_blocks_per_set + num_additional_tags
        global_sets_per_skew_num = global_data_blocks // num_partitions
        if global_sets_per_skew_num % num_blocks_per_set != 0:
            raise ValueError("MIRAGE data blocks/skew must be divisible by data ways")
        global_sets_per_skew = global_sets_per_skew_num // num_blocks_per_set
        require_power_of_two(global_sets_per_skew, "global_sets_per_skew")
        if global_sets_per_skew % num_banks != 0:
            raise ValueError("MIRAGE sets/skew must be divisible by num_banks")

        sets_per_skew_per_bank = global_sets_per_skew // num_banks
        require_power_of_two(sets_per_skew_per_bank, "sets_per_skew_per_bank")
        if sets_per_skew_per_bank <= 0:
            raise ValueError("MIRAGE bank-local sets/skew must be non-zero")

        global_index_bits = int(math.log2(global_sets_per_skew))
        local_index_bits = int(math.log2(sets_per_skew_per_bank))
        tag_blocks_per_skew_per_bank = sets_per_skew_per_bank * tag_ways
        total_data_blocks = data_blocks_per_bank * num_banks
        total_tag_entries = (
            num_banks * num_partitions * tag_blocks_per_skew_per_bank
        )

        return {
            "global_data_blocks": global_data_blocks,
            "data_blocks_per_bank": data_blocks_per_bank,
            "global_sets_per_skew": global_sets_per_skew,
            "sets_per_skew_per_bank": sets_per_skew_per_bank,
            "global_index_bits": global_index_bits,
            "local_index_bits": local_index_bits,
            "tag_ways": tag_ways,
            "tag_blocks_per_skew_per_bank": tag_blocks_per_skew_per_bank,
            "total_data_blocks": total_data_blocks,
            "total_tag_entries": total_tag_entries,
            "tag_data_ratio": total_tag_entries / total_data_blocks,
        }

    def filter_addresses_by_banks(self, addresses, target_banks, num_banks, num_words_per_block):
        """Filter addresses to only those that map to target banks."""
        if target_banks is None or num_banks == 1:
            return addresses
        return [addr for addr in addresses if self.get_bank_id(addr, num_banks, num_words_per_block) in target_banks]

    def get_addr_refs(self, word_addrs, num_addr_bits, num_offset_bits, num_index_bits, num_tag_bits, num_partitions, ways_per_partition):
        return [Reference(word_addr, num_addr_bits, num_offset_bits, num_index_bits, num_tag_bits, num_partitions, ways_per_partition) for word_addr in word_addrs]

    def emulate_timing(self, refs):
        timing_vals = OrderedDict()
        for ref in refs:
            if (ref.cache_status.name == 'hit'):
                timing_vals[str(ref.word_addr)] = 200
            else:
                timing_vals[str(ref.word_addr)] = 600
        return timing_vals

    @staticmethod
    def _split_alternate(seq):
        """Split a sequence into two by alternating elements (even->A, odd->B)."""
        a, b = [], []
        for i, v in enumerate(seq):
            (a if (i % 2 == 0) else b).append(v)
        return a, b

    def run_simulation(self,
                       num_blocks_per_set,
                       num_words_per_block,
                       cache_size,
                       num_partitions,
                       replacement_policy,
                       num_addr_bits,
                       num_additional_tags,
                       receiver_addresses,
                       sender_addresses,
                       region_split_ratio=0.3,
                       attack_mode='region0',
                       num_banks=1,
                       banks_to_attack=1):
        """
        attack_mode: 'region0' | 'region1' | 'simultaneous'
        num_banks: number of banks (regions) in multi-bank mode
        banks_to_attack: how many banks to attack simultaneously
        """

        # -------- geometry/derived -----------
        geom = self.get_mirage_snuca_geometry(
            cache_size,
            num_words_per_block,
            num_blocks_per_set,
            num_additional_tags,
            num_partitions,
            num_banks,
        )
        num_data_blocks = geom["data_blocks_per_bank"]
        num_sets_per_skew = geom["sets_per_skew_per_bank"]
        num_tag_blocks_per_skew = geom["tag_blocks_per_skew_per_bank"]
        num_total_ways = geom["tag_ways"]

        all_addrs = receiver_addresses + sender_addresses
        num_addr_bits = max(num_addr_bits, int(math.log2(max(all_addrs))) + 1)

        num_offset_bits = int(math.log2(num_words_per_block))
        num_index_bits = geom["local_index_bits"]
        # Keep MIRAGE tag identity tied to the original single-bank index field.
        num_tag_bits = num_addr_bits - geom["global_index_bits"] - num_offset_bits

        # -------- Generic N-region simulation -----------
        # Determine number of regions and how to distribute addresses
        num_regions = num_banks
        if attack_mode == 'region1' and num_banks > 1:
            target_regions = [1]
            print(f"S-NUCA Mirage: single-bank attack on bank 1")
        elif attack_mode in ('region0', 'region1'):
            target_regions = [0]
            print(f"S-NUCA Mirage: single-bank attack on bank 0")
        else:
            if banks_to_attack > num_banks:
                raise ValueError("banks_to_attack cannot exceed num_banks")
            target_regions = list(range(banks_to_attack))
            print(f"S-NUCA Mirage: simultaneous attack on {banks_to_attack} banks")

        region_addrs = {r: {'recv': [], 'send': []} for r in target_regions}
        for addr in receiver_addresses:
            bid = self.get_bank_id(addr, num_banks, num_words_per_block)
            if bid in region_addrs:
                region_addrs[bid]['recv'].append(addr)
        for addr in sender_addresses:
            bid = self.get_bank_id(addr, num_banks, num_words_per_block)
            if bid in region_addrs:
                region_addrs[bid]['send'].append(addr)
        
        # Create N-region cache
        cache = HybridWrapperCache(
            num_regions=num_regions,
            region_split_ratio=region_split_ratio,  # Used only when num_regions=2
            num_data_blocks=num_data_blocks,
            num_sets_per_skew=num_sets_per_skew,
            num_index_bits=num_index_bits,
            num_partitions=num_partitions,
            num_tag_blocks_per_skew=num_tag_blocks_per_skew,
            num_addr_bits=num_addr_bits,
            num_offset_bits=num_offset_bits,
            num_total_ways=num_total_ways
        )

        # Build refs grouped by region
        recv_refs_by_region = [[] for _ in range(len(target_regions))]
        send_refs_by_region = [[] for _ in range(len(target_regions))]
        
        for i, region_id in enumerate(target_regions):
            addrs = region_addrs[region_id]
            
            if addrs['recv']:
                refs = self.get_addr_refs(addrs['recv'], num_addr_bits, num_offset_bits, 
                                         num_index_bits, num_tag_bits, num_partitions, num_tag_blocks_per_skew)
                for ref in refs:
                    ref.target_region = region_id
                recv_refs_by_region[i] = refs
            
            if addrs['send']:
                refs = self.get_addr_refs(addrs['send'], num_addr_bits, num_offset_bits,
                                         num_index_bits, num_tag_bits, num_partitions, num_tag_blocks_per_skew)
                for ref in refs:
                    ref.target_region = region_id
                send_refs_by_region[i] = refs
        
        # Run simulation: receiver -> sender -> receiver
        strict = True  # do not cross regions when probing
        
        for i in range(len(target_regions)):
            if recv_refs_by_region[i]:
                cache.read_refs_explicit(num_words_per_block, replacement_policy, 
                                       recv_refs_by_region[i], strict_region=strict)
        
        for i in range(len(target_regions)):
            if send_refs_by_region[i]:
                cache.read_refs_explicit(num_words_per_block, replacement_policy,
                                       send_refs_by_region[i], strict_region=strict)
        
        # Re-access receiver and collect timings
        recv_re_by_region = []
        for i in range(len(target_regions)):
            if recv_refs_by_region[i]:
                addrs = [ref.word_addr for ref in recv_refs_by_region[i]]
                refs = self.get_addr_refs(addrs, num_addr_bits, num_offset_bits,
                                         num_index_bits, num_tag_bits, num_partitions, num_tag_blocks_per_skew)
                for ref in refs:
                    ref.target_region = target_regions[i]
                cache.read_refs_explicit(num_words_per_block, replacement_policy, refs, strict_region=strict)
                recv_re_by_region.append(refs)
            else:
                recv_re_by_region.append([])
        
        # cache.print_occupancy_stats()
        
        # Build result dict: region0, region1, region2, ...
        result = {}
        for i, region_id in enumerate(target_regions):
            if recv_re_by_region[i]:
                timings = self.emulate_timing(recv_re_by_region[i])
                result[f'region{region_id}'] = timings
        
        return result
