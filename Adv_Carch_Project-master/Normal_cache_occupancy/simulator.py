#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulator for occupancy-based covert channel with Multi-CACHE WAY-SPLIT Normal
"""

import math
from collections import OrderedDict

from hybrid_wrapper_cache import HybridWrapperCache
from reference import Reference


class Simulator(object):

    def get_bank_id(self, address, num_banks, num_words_per_block):
        """Determine which bank an address maps to based on block offset."""
        BYTES_PER_WORD = 8
        bytes_per_block = num_words_per_block * BYTES_PER_WORD
        block_number = address // bytes_per_block
        return block_number % num_banks

    def filter_addresses_by_banks(self, addresses, target_banks, num_banks, num_words_per_block):
        """Filter addresses to only those that map to target banks."""
        if target_banks is None or num_banks == 1:
            return addresses
        return [addr for addr in addresses if self.get_bank_id(addr, num_banks, num_words_per_block) in target_banks]

    def get_addr_refs(self, word_addrs, num_addr_bits, num_offset_bits, num_index_bits, num_tag_bits, num_partitions, ways_per_partition):
        return [Reference(word_addr, num_addr_bits, num_offset_bits, num_index_bits, num_tag_bits, num_partitions, ways_per_partition) for word_addr in word_addrs]

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

        # -------- geometry -----------
        num_data_blocks = (cache_size // 8) // num_words_per_block
        raw_num_sets = max(1, num_data_blocks // num_blocks_per_set)
        num_index_bits = max(1, int(math.log2(raw_num_sets)))
        num_sets = 1 << num_index_bits

        # address fields
        all_addrs = receiver_addresses + sender_addresses
        num_addr_bits = max(num_addr_bits, int(math.log2(max(all_addrs))) + 1)
        num_offset_bits = int(math.log2(num_words_per_block))
        num_tag_bits = num_addr_bits - num_index_bits - num_offset_bits
        ways_per_partition = max(1, num_blocks_per_set // num_partitions)

        # -------- Generic N-region simulation -----------
        # Determine number of regions and how to distribute addresses
        if num_banks > 1:
            # Multi-bank mode: each bank is a region
            num_regions = num_banks
            
            # Determine which banks (regions) to attack
            if attack_mode in ('region0', 'region1'):
                target_regions = [0]  # Single region attack
                print(f"Multi-bank: Single-region attack on bank/region 0")
            else:  # simultaneous
                target_regions = list(range(banks_to_attack))
                print(f"Multi-bank: Simultaneous attack on {banks_to_attack} banks/regions")
            
            # Group addresses by bank (which maps to region)
            region_addrs = {r: {'recv': [], 'send': []} for r in target_regions}
            for addr in receiver_addresses:
                bid = self.get_bank_id(addr, num_banks, num_words_per_block)
                if bid in region_addrs:
                    region_addrs[bid]['recv'].append(addr)
            for addr in sender_addresses:
                bid = self.get_bank_id(addr, num_banks, num_words_per_block)
                if bid in region_addrs:
                    region_addrs[bid]['send'].append(addr)
        else:
            # Hybrid mode: 2 regions with address interleaving
            num_regions = 2
            
            if attack_mode == 'region0':
                target_regions = [0]
            elif attack_mode == 'region1':
                target_regions = [1]
            else:  # simultaneous
                target_regions = [0, 1]
            
            # Distribute addresses across regions (interleave for simultaneous)
            region_addrs = {r: {'recv': [], 'send': []} for r in target_regions}
            if len(target_regions) == 1:
                # Single region: all addresses go there
                r = target_regions[0]
                region_addrs[r]['recv'] = receiver_addresses
                region_addrs[r]['send'] = sender_addresses
            else:
                # Simultaneous: alternate addresses between regions
                for i, addr in enumerate(receiver_addresses):
                    region_addrs[i % 2]['recv'].append(addr)
                for i, addr in enumerate(sender_addresses):
                    region_addrs[i % 2]['send'].append(addr)
        
        # Create N-region cache
        cache = HybridWrapperCache(
            num_regions=num_regions,
            region_split_ratio=region_split_ratio,  # Used only when num_regions=2
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
                refs = self.get_addr_refs(addrs['recv'], num_addr_bits, num_offset_bits, 
                                         num_index_bits, num_tag_bits, num_partitions, ways_per_partition)
                for ref in refs:
                    ref.target_region = i  # Use index in target_regions
                recv_refs_by_region[i] = refs
            
            if addrs['send']:
                refs = self.get_addr_refs(addrs['send'], num_addr_bits, num_offset_bits,
                                         num_index_bits, num_tag_bits, num_partitions, ways_per_partition)
                for ref in refs:
                    ref.target_region = i
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
                refs = self.get_addr_refs(addrs, num_addr_bits, num_offset_bits,
                                         num_index_bits, num_tag_bits, num_partitions, ways_per_partition)
                for ref in refs:
                    ref.target_region = i
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
