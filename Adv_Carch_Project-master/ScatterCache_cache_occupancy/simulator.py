#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulator for occupancy-based covert channel with S-NUCA ScatterCache."""

import math
import os
import sys
from collections import OrderedDict

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from common import get_bank_id, get_snuca_geometry
from hybrid_wrapper_cache import HybridWrapperCache
from reference import Reference


class Simulator(object):

    def get_bank_id(self, address, num_banks, num_words_per_block):
        return get_bank_id(address, num_banks, num_words_per_block)

    def filter_addresses_by_banks(self, addresses, target_banks, num_banks, num_words_per_block):
        """Filter addresses to only those that map to target banks."""
        if target_banks is None or num_banks == 1:
            return addresses
        return [addr for addr in addresses if self.get_bank_id(addr, num_banks, num_words_per_block) in target_banks]

    def get_addr_refs(self, word_addrs, num_addr_bits, num_offset_bits, num_index_bits,
                      num_tag_bits, num_partitions, ways_per_partition, *,
                      target_region=0, num_banks=1, sets_per_bank=None):
        return [
            Reference(
                word_addr,
                num_addr_bits,
                num_offset_bits,
                num_index_bits,
                num_tag_bits,
                num_partitions,
                ways_per_partition,
                target_region=target_region,
            )
            for word_addr in word_addrs
        ]

    def emulate_timing(self, refs):
        t = OrderedDict()
        for ref in refs:
            t[str(ref.word_addr)] = 200 if (ref.cache_status.name == 'hit') else 600
        return t

    def run_simulation(self,
                       num_blocks_per_set,
                       num_words_per_block,
                       cache_size,
                       num_partitions,
                       replacement_policy,
                       num_addr_bits,
                       receiver_addresses,
                       sender_addresses,
                       region_split_ratio=0.3,
                       attack_mode='region0',
                       num_banks=1,
                       banks_to_attack=1):

        # -------- S-NUCA geometry -----------
        geom = get_snuca_geometry(
            cache_size, num_words_per_block, num_blocks_per_set, num_banks
        )
        global_index_bits = geom["global_index_bits"]
        num_index_bits = geom["local_index_bits"]
        num_sets = geom["sets_per_bank"]

        # address fields
        all_addrs = receiver_addresses + sender_addresses
        num_addr_bits = max(num_addr_bits, int(math.log2(max(all_addrs))) + 1)
        num_offset_bits = int(math.log2(num_words_per_block))
        # Preserve current single-bank ScatterCache tag semantics; only the
        # randomized set index becomes bank-local.
        num_tag_bits = num_addr_bits - global_index_bits - num_offset_bits
        ways_per_partition = max(1, num_blocks_per_set // num_partitions)

        num_regions = num_banks
        if attack_mode == 'region1' and num_banks > 1:
            target_regions = [1]
        elif attack_mode in ('region0', 'region1'):
            target_regions = [0]
        else:
            target_regions = list(range(banks_to_attack))

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
            region_split_ratio=region_split_ratio,
            num_sets=num_sets,
            num_index_bits=num_index_bits,
            num_partitions=num_partitions,
            num_blocks_per_set=num_blocks_per_set
        )
        
        # Build refs grouped by region
        recv_refs_by_region = [[] for _ in range(len(target_regions))]
        send_refs_by_region = [[] for _ in range(len(target_regions))]
        
        for i, region_id in enumerate(target_regions):
            addrs = region_addrs[region_id]
            
            if addrs['recv']:
                refs = self.get_addr_refs(
                    addrs['recv'], num_addr_bits, num_offset_bits,
                    num_index_bits, num_tag_bits, num_partitions, ways_per_partition,
                    target_region=region_id
                )
                recv_refs_by_region[i] = refs
            
            if addrs['send']:
                refs = self.get_addr_refs(
                    addrs['send'], num_addr_bits, num_offset_bits,
                    num_index_bits, num_tag_bits, num_partitions, ways_per_partition,
                    target_region=region_id
                )
                send_refs_by_region[i] = refs
        
        # Run simulation: receiver -> sender -> receiver
        for i in range(len(target_regions)):
            if recv_refs_by_region[i]:
                cache.read_refs_explicit(num_words_per_block, replacement_policy, 
                                       recv_refs_by_region[i], strict_region=True)
        
        for i in range(len(target_regions)):
            if send_refs_by_region[i]:
                cache.read_refs_explicit(num_words_per_block, replacement_policy,
                                       send_refs_by_region[i], strict_region=True)
        
        # Re-access receiver and collect timings
        recv_re_by_region = []
        for i in range(len(target_regions)):
            if recv_refs_by_region[i]:
                addrs = [ref.word_addr for ref in recv_refs_by_region[i]]
                refs = self.get_addr_refs(
                    addrs, num_addr_bits, num_offset_bits,
                    num_index_bits, num_tag_bits, num_partitions, ways_per_partition,
                    target_region=target_regions[i]
                )
                cache.read_refs_explicit(num_words_per_block, replacement_policy, refs, strict_region=True)
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
