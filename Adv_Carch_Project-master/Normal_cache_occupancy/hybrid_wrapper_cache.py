#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S-NUCA bank wrapper for Normal cache.

Each bank is an independent cache with bank-local sets and the original
ways/set. region_split_ratio is accepted for old callers but ignored here.
"""

from reference import ReferenceCacheStatus
from cache import Cache


class HybridWrapperCache:
    def __init__(self,
                 cache_class=Cache,
                 num_regions=2,
                 region_split_ratio=0.3,
                 *,
                 num_sets=None,
                 num_index_bits=None,
                 num_partitions=None,
                 num_blocks_per_set=None):
        self.num_regions = int(num_regions)
        self.region_split_ratio = float(region_split_ratio)
        
        if any(v is None for v in (num_sets, num_index_bits, num_partitions, num_blocks_per_set)):
            raise ValueError("All geometry params must be provided.")

        self._num_sets = int(num_sets)
        self._num_index_bits = int(num_index_bits)
        self._num_partitions = int(num_partitions)
        self._ways_total = int(num_blocks_per_set)
        self._ways_per_bank = [self._ways_total] * self.num_regions

        # Determine if single region mode (only one active region)
        active_regions = [i for i, w in enumerate(self._ways_per_bank) if w > 0]
        self.single_region_mode = len(active_regions) == 1
        self.active_region = active_regions[0] if self.single_region_mode else None

        print(f"S-NUCA cache configuration:")
        print(f"  banks={self.num_regions}, sets/bank={self._num_sets}, index_bits={self._num_index_bits}")
        print(f"  partitions={self._num_partitions}, total_ways={self._ways_total}")
        print(f"  ways_per_bank={self._ways_per_bank}")
        if self.single_region_mode:
            print(f"  One-bank mode: bank {self.active_region}")

        self.region_caches = [self._create_region_cache(cache_class, ways) 
                              for ways in self._ways_per_bank]

        # Stats: track per-region
        self.region_accesses = [0] * self.num_regions
        self.region_hits = [0] * self.num_regions

    def _create_region_cache(self, cache_class, ways):
        """Create a bank-local cache with original associativity."""
        if ways <= 0:
            return None
        
        return cache_class(
            cache=None,
            num_sets=self._num_sets,
            num_index_bits=self._num_index_bits,
            num_partitions=self._num_partitions,
            ways_per_partition=ways // self._num_partitions
        )

    def smaller_region_id(self):
        """Return ID of smallest region (all S-NUCA banks are equal)."""
        min_ways = min(w for w in self._ways_per_bank if w > 0)
        return next(i for i, w in enumerate(self._ways_per_bank) if w == min_ways)

    # ---- probes ----
    def _is_hit_in_region(self, region_id, ref):
        if region_id >= self.num_regions or self.region_caches[region_id] is None:
            return False
        cache = self.region_caches[region_id]
        return cache.is_hit(ref.partition, ref.index, ref.tag, self._num_partitions)

    def is_hit(self, ref, target_region=None):
        """Return (bool, region_id or None)."""
        if target_region is not None:
            hit = self._is_hit_in_region(target_region, ref)
            return (hit, target_region) if hit else (False, None)
        
        for rid in range(self.num_regions):
            if self._is_hit_in_region(rid, ref):
                return True, rid
        return False, None

    # ---- allocate within a region ----
    def _allocate_in_region(self, region_id, replacement_policy, ref, num_words_per_block):
        if region_id >= self.num_regions or self.region_caches[region_id] is None:
            raise ValueError(f"Region {region_id} is not available")
        
        cache = self.region_caches[region_id]
        bank_ways = self._ways_per_bank[region_id]
        
        cache.set_block(
            replacement_policy=replacement_policy,
            num_blocks_per_set=bank_ways,
            addr_partition=ref.partition,
            num_partition=self._num_partitions,
            addr_index=ref.index,
            new_entry=ref.get_cache_entry(num_words_per_block)
        )

    # ---- main read ----
    def read_refs_explicit(self, num_words_per_block, replacement_policy, refs, strict_region=True):
        """
        Each ref may carry ref.target_region in [0..N-1].
        If strict_region=True, probe/allocate only in target region.
        If False, probe target first, then other regions before allocating.
        """
        for ref in refs:
            # Determine target region
            target_region = getattr(ref, 'target_region', None)
            if target_region is None or target_region >= self.num_regions or self.region_caches[target_region] is None:
                # Default to first active region
                target_region = next((i for i in range(self.num_regions) if self.region_caches[i] is not None), 0)

            # Probe
            hit_region = None
            if self._is_hit_in_region(target_region, ref):
                hit_region = target_region
            elif not strict_region:
                # Try other regions
                for rid in range(self.num_regions):
                    if rid != target_region and self._is_hit_in_region(rid, ref):
                        hit_region = rid
                        break

            if hit_region is not None:
                ref.cache_status = ReferenceCacheStatus.hit
                ref.region = hit_region
                self.region_hits[hit_region] += 1
                self.region_accesses[hit_region] += 1
                self.region_caches[hit_region].mark_ref_as_last_seen(ref)
                continue

            # Miss -> allocate in target region
            ref.cache_status = ReferenceCacheStatus.miss
            ref.region = target_region
            self.region_accesses[target_region] += 1
            self.region_caches[target_region].mark_ref_as_last_seen(ref)
            self._allocate_in_region(target_region, replacement_policy, ref, num_words_per_block)

    # ---- stats ----
    @staticmethod
    def _count_blocks(cache_instance):
        if cache_instance is None:
            return 0
        total = 0
        for _, blocks in cache_instance.items():
            total += len(blocks)
        return total

    def get_occupancy_stats(self):
        """Return per-region stats"""
        stats = {}
        for i in range(self.num_regions):
            occ = self._count_blocks(self.region_caches[i])
            cap = self._num_sets * self._ways_total
            hit_rate = (self.region_hits[i] / self.region_accesses[i]) if self.region_accesses[i] else 0.0
            stats[f'region{i}'] = {
                'occupied': occ,
                'cap': cap,
                'accesses': self.region_accesses[i],
                'hits': self.region_hits[i],
                'hit_rate': hit_rate
            }
        return stats

    def print_occupancy_stats(self):
        stats = self.get_occupancy_stats()
        print(f"\n=== Multi-region Cache Stats ({self.num_regions} regions) ===")
        for i in range(self.num_regions):
            s = stats[f'region{i}']
            print(f"Region {i}: {s['occupied']}/{s['cap']} used, "
                  f"hits {s['hits']}/{s['accesses']} ({s['hit_rate']*100:.1f}%)")
        
        total_accesses = sum(self.region_accesses)
        total_hits = sum(self.region_hits)
        overall = (total_hits / total_accesses) if total_accesses else 0.0
        print(f"Overall: {total_hits}/{total_accesses} ({overall*100:.1f}% hit rate)")

    def reset_stats(self):
        self.region_accesses = [0] * self.num_regions
        self.region_hits = [0] * self.num_regions
