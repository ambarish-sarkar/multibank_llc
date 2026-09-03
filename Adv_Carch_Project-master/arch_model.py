import math
import os
import random
import sys
from collections import OrderedDict
from functools import lru_cache

from common import (
    BYTES_PER_WORD,
    get_bank_id,
    get_region_id,
    get_snuca_geometry,
    get_target_pairs,
    require_integer_split,
    validate_architecture_config,
)


DESIGN_NORMAL = "normal"
DESIGN_CEASER = "ceaser"
DESIGN_CEASER_S = "ceaser_s"
DESIGN_SCATTER = "scatter"
DESIGN_MIRAGE = "mirage"

CEASER_KEY = "00000000000000000011"
CEASER_S_KEYS = ("00000000000000002222", "00000000000000001111")
MIRAGE_KEYS = ("00000000000000000000", "ffffffffffffffffffff")


@lru_cache(maxsize=None)
def _present_cipher(key_hex):
    try:
        from present import Present
    except ModuleNotFoundError:
        present_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Ceaser_cache_occupancy")
        sys.path.insert(0, present_dir)
        try:
            from present import Present
        finally:
            sys.path.pop(0)
    key = bin(int(key_hex, 16))[2:].zfill(80)
    return Present(key)


def _present_ciphertext(word_addr, num_words_per_block, key_hex):
    block_number = int(word_addr) // int(num_words_per_block)
    plaintext = bin(block_number)[2:].zfill(64)
    cipher = _present_cipher(key_hex)
    ciphertext = str(bin(int(cipher.encrypt(plaintext), 16))[2:].zfill(64))
    return ciphertext


def _present_index(word_addr, num_words_per_block, num_index_bits, key_hex):
    """Restore the original offset-aware CEASER index-field extraction.

    The plaintext is the word address with offset bits removed.  The encrypted
    index comes from the ciphertext field immediately above the original offset
    bit positions, matching the pre-centralized BinaryAddress.get_index logic.
    """
    if num_index_bits <= 0:
        return 0
    offset_bits = int(math.log2(num_words_per_block))
    ciphertext = _present_ciphertext(word_addr, num_words_per_block, key_hex)
    end = len(ciphertext) - offset_bits
    start = end - int(num_index_bits)
    return int(ciphertext[start:end], 2)


def _present_index_mod(word_addr, num_words_per_block, num_sets, key_hex):
    """Map an encrypted index field onto any tag-set count."""
    num_sets = int(num_sets)
    if num_sets <= 1:
        return 0
    if num_sets & (num_sets - 1) == 0:
        return _present_index(word_addr, num_words_per_block, int(math.log2(num_sets)), key_hex)

    offset_bits = int(math.log2(num_words_per_block))
    ciphertext = _present_ciphertext(word_addr, num_words_per_block, key_hex)
    end = len(ciphertext) - offset_bits
    raw = int(ciphertext[:end], 2)
    return raw % num_sets


def _plain_local_set(word_addr, num_words_per_block, num_banks, sets_per_bank):
    block_number = int(word_addr) // int(num_words_per_block)
    return (block_number // int(num_banks)) % int(sets_per_bank)


def _tag(word_addr, num_words_per_block, global_index_bits):
    block_number = int(word_addr) // int(num_words_per_block)
    return block_number >> int(global_index_bits)


class SetAssociativeRegion:
    def __init__(self, num_sets, way_groups):
        self.num_sets = int(num_sets)
        self.way_groups = [int(w) for w in way_groups]
        self.sets = [
            [[None for _ in range(ways)] for ways in self.way_groups]
            for _ in range(self.num_sets)
        ]

    @property
    def capacity(self):
        return self.num_sets * sum(self.way_groups)

    def access(self, candidates, tag):
        for group_idx, set_idx in candidates:
            ways = self.sets[set_idx][group_idx]
            for entry in ways:
                if entry == tag:
                    return True
        group_idx, set_idx = random.choice(candidates)
        ways = self.sets[set_idx][group_idx]
        for i, entry in enumerate(ways):
            if entry is None:
                ways[i] = tag
                return False
        ways[random.randrange(len(ways))] = tag
        return False

    def valid_lines(self):
        total = 0
        for set_groups in self.sets:
            for ways in set_groups:
                total += sum(1 for entry in ways if entry is not None)
        return total


class MirageRegion:
    def __init__(self, data_entries, tag_sets_per_skew, tag_skews=2, tag_ways=14, rng=None):
        self.data_entries = int(data_entries)
        self.tag_sets_per_skew = int(tag_sets_per_skew)
        self.tag_skews = int(tag_skews)
        self.tag_ways = int(tag_ways)
        self.rng = rng if rng is not None else random
        self.tags = [
            [[None for _ in range(self.tag_ways)] for _ in range(self.tag_sets_per_skew)]
            for _ in range(self.tag_skews)
        ]
        self.data_store = [None for _ in range(self.data_entries)]

    @property
    def tag_entries(self):
        return self.tag_skews * self.tag_sets_per_skew * self.tag_ways

    def access(self, indexes, tag):
        for skew, set_idx in enumerate(indexes):
            for entry in self.tags[skew][set_idx]:
                if entry is not None and entry[0] == tag:
                    return True

        counts = [
            sum(1 for entry in self.tags[skew][indexes[skew]] if entry is not None)
            for skew in range(self.tag_skews)
        ]
        min_count = min(counts)
        candidate_skews = [skew for skew, count in enumerate(counts) if count == min_count]
        skew = self.rng.choice(candidate_skews)
        set_idx = indexes[skew]
        ways = self.tags[skew][set_idx]

        for way, entry in enumerate(ways):
            if entry is None:
                data_idx = self._allocate_data((skew, set_idx, way))
                ways[way] = (tag, data_idx)
                return False

        way = self.rng.randrange(self.tag_ways)
        old = ways[way]
        data_idx = old[1] if old is not None else self._allocate_data((skew, set_idx, way))
        self.data_store[data_idx] = (skew, set_idx, way)
        ways[way] = (tag, data_idx)
        return False

    def _allocate_data(self, pointer):
        # MIRAGE GLE always samples the region-local data store, even when empty slots remain.
        victim = self.rng.randrange(self.data_entries)
        old_pointer = self.data_store[victim]
        if old_pointer is not None:
            old_skew, old_set, old_way = old_pointer
            self.tags[old_skew][old_set][old_way] = None
        self.data_store[victim] = pointer
        return victim

    def valid_lines(self):
        return sum(1 for entry in self.data_store if entry is not None)

    def check_pointer_invariants(self):
        live_data = {}
        live_tags = {}

        for data_idx, pointer in enumerate(self.data_store):
            if pointer is None:
                continue
            skew, set_idx, way = pointer
            if not (0 <= skew < self.tag_skews):
                raise AssertionError(f"data[{data_idx}] points to invalid skew {skew}")
            if not (0 <= set_idx < self.tag_sets_per_skew):
                raise AssertionError(f"data[{data_idx}] points to invalid set {set_idx}")
            if not (0 <= way < self.tag_ways):
                raise AssertionError(f"data[{data_idx}] points to invalid way {way}")
            tag_entry = self.tags[skew][set_idx][way]
            if tag_entry is None:
                raise AssertionError(f"data[{data_idx}] points to an invalid tag")
            if tag_entry[1] != data_idx:
                raise AssertionError(
                    f"data[{data_idx}] reverse pointer disagrees with tag forward pointer {tag_entry[1]}"
                )
            live_data[pointer] = data_idx

        for skew in range(self.tag_skews):
            for set_idx in range(self.tag_sets_per_skew):
                for way, entry in enumerate(self.tags[skew][set_idx]):
                    if entry is None:
                        continue
                    pointer = (skew, set_idx, way)
                    data_idx = entry[1]
                    if pointer not in live_data:
                        raise AssertionError(f"tag {pointer} points to unoccupied data[{data_idx}]")
                    if self.data_store[data_idx] != pointer:
                        raise AssertionError(f"tag {pointer} forward pointer disagrees with data reverse pointer")
                    if data_idx in live_tags:
                        raise AssertionError(f"duplicate live forward pointer to data[{data_idx}]")
                    live_tags[data_idx] = pointer

        if len(live_data) != len(live_tags):
            raise AssertionError("live tag/data pointer cardinality mismatch")
        return True


class BankedArchitectureCache:
    def __init__(self, design, cfg):
        validate_architecture_config(cfg, design)
        self.design = design
        self.cfg = cfg
        self.geom = get_snuca_geometry(
            cfg.cache_size,
            cfg.num_words_per_block,
            16 if design != DESIGN_MIRAGE else 8,
            cfg.num_banks,
        )
        if design == DESIGN_MIRAGE:
            self.geom = self._mirage_geometry()
        self.num_regions = cfg.num_regions
        self.bank_region = {}
        if design == DESIGN_MIRAGE:
            self._init_mirage()
        else:
            self._init_conventional()
        self.hits = {}
        self.accesses = {}

    def _init_conventional(self):
        sets_per_bank = self.geom["sets_per_bank"]
        for bank in range(self.cfg.num_banks):
            self.bank_region[bank] = {}
            for region, groups in enumerate(self.cfg.region_way_groups):
                self.bank_region[bank][region] = SetAssociativeRegion(sets_per_bank, groups)

    def _init_mirage(self):
        total_data = self.geom["total_blocks"]
        data_per_bank = self.geom["data_per_bank"]
        self.mirage_data_per_bank = data_per_bank
        self.mirage_tag_sets_per_bank = self.geom["sets_per_bank"]
        for bank in range(self.cfg.num_banks):
            self.bank_region[bank] = {}
            for region, fraction in enumerate(self.cfg.region_fractions):
                data_entries = int(data_per_bank * fraction)
                if data_entries <= 0 or data_entries % 16 != 0:
                    raise ValueError("MIRAGE region data entries must be positive and divisible by 16")
                tag_sets = data_entries // (2 * 8)
                self.bank_region[bank][region] = MirageRegion(data_entries, tag_sets, 2, 14)

    def _mirage_geometry(self):
        total_data = self.cfg.cache_size // (self.cfg.num_words_per_block * BYTES_PER_WORD)
        data_per_bank = total_data // self.cfg.num_banks
        global_tag_sets_per_skew = total_data // (2 * 8)
        if global_tag_sets_per_skew % self.cfg.num_banks != 0:
            raise ValueError("MIRAGE global tag sets must divide cleanly across banks")
        sets_per_bank = global_tag_sets_per_skew // self.cfg.num_banks
        return {
            "total_blocks": total_data,
            "global_num_sets": global_tag_sets_per_skew,
            "sets_per_bank": sets_per_bank,
            "global_index_bits": int(math.log2(global_tag_sets_per_skew)),
            "bank_bits": int(math.log2(self.cfg.num_banks)),
            "local_index_bits": int(math.log2(sets_per_bank)),
            "aggregate_lines": total_data,
            "data_per_bank": data_per_bank,
        }

    def _candidate_locations(self, word_addr, bank, region):
        local_bits = self.geom["local_index_bits"]
        sets_per_bank = self.geom["sets_per_bank"]
        if self.design == DESIGN_NORMAL:
            return [(0, _plain_local_set(word_addr, self.cfg.num_words_per_block, self.cfg.num_banks, sets_per_bank))]
        if self.design == DESIGN_CEASER:
            return [(0, _present_index(word_addr, self.cfg.num_words_per_block, local_bits, CEASER_KEY) % sets_per_bank)]
        if self.design == DESIGN_CEASER_S:
            return [
                (0, _present_index(word_addr, self.cfg.num_words_per_block, local_bits, CEASER_S_KEYS[0]) % sets_per_bank),
                (1, _present_index(word_addr, self.cfg.num_words_per_block, local_bits, CEASER_S_KEYS[1]) % sets_per_bank),
            ]
        if self.design == DESIGN_SCATTER:
            candidates = []
            for group_idx, local_skew in enumerate(self.cfg.region_skews[region]):
                key = f"{local_skew + 1:020x}"
                candidates.append((group_idx, _present_index(word_addr, self.cfg.num_words_per_block, local_bits, key) % sets_per_bank))
            return candidates
        raise ValueError(f"Unsupported conventional design: {self.design}")

    def _mirage_indexes(self, word_addr, region):
        tag_sets = self.bank_region[0][region].tag_sets_per_skew
        return [
            _present_index_mod(word_addr, self.cfg.num_words_per_block, tag_sets, MIRAGE_KEYS[0]),
            _present_index_mod(word_addr, self.cfg.num_words_per_block, tag_sets, MIRAGE_KEYS[1]),
        ]

    def access(self, word_addr, bank, region):
        key = (bank, region)
        self.accesses[key] = self.accesses.get(key, 0) + 1
        tag = _tag(word_addr, self.cfg.num_words_per_block, self.geom["global_index_bits"])
        if self.design == DESIGN_MIRAGE:
            hit = self.bank_region[bank][region].access(self._mirage_indexes(word_addr, region), tag)
        else:
            hit = self.bank_region[bank][region].access(self._candidate_locations(word_addr, bank, region), tag)
        if hit:
            self.hits[key] = self.hits.get(key, 0) + 1
        return hit

    def capacities(self):
        out = {}
        for bank, regions in self.bank_region.items():
            out[bank] = {region: cache.capacity if hasattr(cache, "capacity") else cache.data_entries for region, cache in regions.items()}
        return out

    def occupied(self):
        out = {}
        for bank, regions in self.bank_region.items():
            out[bank] = {region: cache.valid_lines() for region, cache in regions.items()}
        return out


def run_architecture_simulation(design, cfg, receiver_addresses, sender_addresses):
    cache = BankedArchitectureCache(design, cfg)
    target_pairs = get_target_pairs(cfg)

    def split_by_target(addresses):
        buckets = {pair: [] for pair in target_pairs}
        for addr in addresses:
            bank = get_bank_id(addr, cfg.num_banks, cfg.num_words_per_block)
            region = get_region_id(addr, cfg)
            pair = (bank, region)
            if pair in buckets:
                buckets[pair].append(addr)
        return buckets

    recv_by_target = split_by_target(receiver_addresses)
    send_by_target = split_by_target(sender_addresses)

    for pair in target_pairs:
        for addr in recv_by_target[pair]:
            cache.access(addr, pair[0], pair[1])
    for pair in target_pairs:
        for addr in send_by_target[pair]:
            cache.access(addr, pair[0], pair[1])

    result = OrderedDict()
    for pair in target_pairs:
        misses = OrderedDict()
        for addr in recv_by_target[pair]:
            hit = cache.access(addr, pair[0], pair[1])
            misses[str(addr)] = 200 if hit else 600
        result[f"bank{pair[0]}_region{pair[1]}"] = misses
    return result
