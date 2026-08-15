#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-NUCA bank wrapper for Mirage Cache.

Each bank is an independent MIRAGE cache with bank-local data blocks and
bank-local tag sets. Tag ways and skew count are preserved; region_split_ratio
is accepted for old callers but ignored in S-NUCA mode.
"""

from reference import ReferenceCacheStatus
from cache import Cache


class HybridWrapperCache:
    def __init__(self,
                 cache_class=Cache,
                 num_regions=2,
                 region_split_ratio=0.3,
                 # geometry derived by Simulator:
                 num_data_blocks=None,
                 num_sets_per_skew=None,
                 num_index_bits=None,
                 num_partitions=None,
                 num_tag_blocks_per_skew=None,
                 num_addr_bits=None,
                 num_offset_bits=None,
                 num_total_ways=None):
        
        self.num_regions = int(num_regions)
        self.region_split_ratio = float(region_split_ratio)
        if any(v is None for v in (
            num_data_blocks,
            num_sets_per_skew,
            num_index_bits,
            num_partitions,
            num_tag_blocks_per_skew,
            num_addr_bits,
            num_offset_bits,
            num_total_ways,
        )):
            raise ValueError("All MIRAGE bank geometry params must be provided.")

        self._num_data_blocks = int(num_data_blocks)
        self._num_sets_per_skew = int(num_sets_per_skew)
        self._num_index_bits = int(num_index_bits)
        self._num_partitions = int(num_partitions)
        self._num_tag_blocks_per_skew = int(num_tag_blocks_per_skew)
        self._num_total_ways = int(num_total_ways)

        if self._num_data_blocks <= 0 or self._num_sets_per_skew <= 0:
            raise ValueError("MIRAGE bank-local geometry must be non-zero")
        if self._num_tag_blocks_per_skew != self._num_sets_per_skew * self._num_total_ways:
            raise ValueError("MIRAGE tag blocks/skew must equal sets/skew * tag ways")

        self._data_blocks_per_bank = [self._num_data_blocks] * self.num_regions
        self.single_region_mode = self.num_regions == 1
        self.active_region = 0 if self.single_region_mode else None

        print(f"S-NUCA Mirage Cache Configuration:")
        print(f"  banks={self.num_regions}, data_blocks/bank={self._num_data_blocks}")
        print(f"  sets/skew/bank={self._num_sets_per_skew}, index_bits={self._num_index_bits}")
        print(f"  skews={self._num_partitions}, tag_ways={self._num_total_ways}")
        if self.single_region_mode:
            print(f"  One-bank mode: bank {self.active_region}")

        # Create N region caches
        self.region_caches = {}
        for region_id in range(self.num_regions):
            self.region_caches[region_id] = cache_class(
                tag_store=None,
                num_data_blocks=self._num_data_blocks,
                num_sets_per_skew=self._num_sets_per_skew,
                num_index_bits=self._num_index_bits,
                num_partitions=self._num_partitions,
                num_tag_blocks_per_skew=self._num_tag_blocks_per_skew,
                num_addr_bits=num_addr_bits,
                num_offset_bits=num_offset_bits,
                num_total_ways=self._num_total_ways
            )

        # Stats: track per-region
        self.region_accesses = [0] * self.num_regions
        self.region_hits = [0] * self.num_regions

    # ----- helpers -----
    def smaller_region_id(self):
        """ID of the smallest region (all S-NUCA banks are equal)."""
        return 0

    def _is_hit_in_region(self, region_id, addr_index, addr_tag):
        if region_id is None or region_id < 0 or region_id >= self.num_regions:
            raise ValueError(f"Invalid S-NUCA bank: {region_id}")
        cache_instance = self.region_caches.get(region_id)
        if cache_instance is None:
            raise ValueError(f"S-NUCA bank {region_id} is not available")
        return cache_instance.is_hit(addr_index, addr_tag, self._num_partitions)

    def is_hit(self, addr_index, addr_tag, target_region=None):
        """Probe only the bank selected by S-NUCA address decomposition."""
        if target_region is None:
            raise ValueError("S-NUCA lookup requires an explicit target bank")
        if self._is_hit_in_region(target_region, addr_index, addr_tag):
            return True, target_region
        return False, None

    def _allocate_in_region(self, region_id, replacement_policy, addr_index, new_entry):
        if region_id is None or region_id < 0 or region_id >= self.num_regions:
            raise ValueError(f"Invalid S-NUCA bank: {region_id}")
        cache_instance = self.region_caches.get(region_id)
        if cache_instance is None:
            raise ValueError(f"S-NUCA bank {region_id} is not available")

        # Mirage Cache.set_block signature:
        # set_block(replacement_policy, num_tags_per_set, num_partition, addr_index, new_entry, count_ref_index, num_index_bits)
        cache_instance.set_block(
            replacement_policy=replacement_policy,
            num_tags_per_set=self._num_total_ways,
            num_partition=self._num_partitions,
            addr_index=addr_index,
            new_entry=new_entry,
            count_ref_index=0,
            num_index_bits=self._num_index_bits
        )

    def read_refs_explicit(self, num_words_per_block, replacement_policy, refs, strict_region=True):
        """Probe and allocate only in the address-selected S-NUCA bank."""
        if not strict_region:
            raise ValueError("S-NUCA mode forbids cross-bank probing")

        for ref in refs:
            # Choose region (must be present)
            target_region = getattr(ref, 'target_region', None)
            if target_region is None or target_region < 0 or target_region >= self.num_regions:
                raise ValueError(f"Invalid S-NUCA bank: {target_region}")
            if target_region not in self.region_caches:
                raise ValueError(f"S-NUCA bank {target_region} is not available")

            hit = self._is_hit_in_region(target_region, ref.index, ref.tag)
            hit_region = target_region if hit else None

            if hit:
                ref.cache_status = ReferenceCacheStatus.hit
                ref.region = hit_region
                self.region_hits[hit_region] += 1
                self.region_accesses[hit_region] += 1
                self.region_caches[hit_region].mark_ref_as_last_seen(ref)
            else:
                ref.cache_status = ReferenceCacheStatus.miss
                ref.region = target_region
                self.region_accesses[target_region] += 1
                self.region_caches[target_region].mark_ref_as_last_seen(ref)
                self._allocate_in_region(
                    target_region,
                    replacement_policy,
                    ref.index,
                    ref.get_cache_entry(num_words_per_block)
                )

    # ----- stats -----
    def get_occupancy_stats(self):
        def count_region(cache_dict):
            total = 0
            valid = 0
            for _, blocks in cache_dict.items():
                total += len(blocks)  # capacity in that set
                for b in blocks:
                    if b.get('valid', 0) == 1:
                        valid += 1
            return valid, total

        stats = {}
        for region_id in range(self.num_regions):
            if region_id in self.region_caches:
                valid, total = count_region(self.region_caches[region_id])
                hit_rate = (self.region_hits[region_id] / self.region_accesses[region_id]) if self.region_accesses[region_id] else 0.0
                stats[f'region{region_id}'] = {
                    'occupied': valid,
                    'total': total,
                    'occupancy_rate': (valid / total) if total else 0.0,
                    'accesses': self.region_accesses[region_id],
                    'hits': self.region_hits[region_id],
                    'hit_rate': hit_rate
                }
            else:
                stats[f'region{region_id}'] = {
                    'occupied': 0,
                    'total': 0,
                    'occupancy_rate': 0.0,
                    'accesses': 0,
                    'hits': 0,
                    'hit_rate': 0.0
                }
        return stats

    def print_occupancy_stats(self):
        stats = self.get_occupancy_stats()
        print(f"\n=== Multi-region Mirage Cache Stats ({self.num_regions} regions) ===")
        for i in range(self.num_regions):
            s = stats[f'region{i}']
            print(f"Region {i}: {s['occupied']}/{s['total']} "
                  f"({s['occupancy_rate']*100:.1f}%), "
                  f"hits {s['hits']}/{s['accesses']} ({s['hit_rate']*100:.1f}%)")
        
        total_acc = sum(self.region_accesses)
        total_hits = sum(self.region_hits)
        overall = (total_hits / total_acc) if total_acc else 0.0
        print(f"Overall: {total_hits}/{total_acc} ({overall*100:.1f}% hit rate)")

    def reset_stats(self):
        self.region_accesses = [0] * self.num_regions
        self.region_hits = [0] * self.num_regions
