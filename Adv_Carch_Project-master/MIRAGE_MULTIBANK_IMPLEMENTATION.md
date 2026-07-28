# Mirage Multi-Bank Implementation

## Overview
This document describes the implementation of multi-bank support for the Mirage cache simulator, mirroring the architecture used in the Ceaser cache simulator.

## Key Changes

### 1. simulator.py Updates

Added multi-bank support with the following features:

#### New Methods
- `get_bank_id(address, num_banks, num_words_per_block)`: Determines which bank an address maps to based on block offset
- `filter_addresses_by_banks(addresses, target_banks, num_banks, num_words_per_block)`: Filters addresses to only those mapping to target banks

#### Enhanced run_simulation() Method
New parameters:
- `num_banks` (default=1): Number of banks/regions in multi-bank mode
- `banks_to_attack` (default=1): How many banks to attack simultaneously

Key logic:
- **Multi-bank mode** (`num_banks > 1`): Each bank is a separate region
  - Addresses are distributed to banks based on `get_bank_id()` function
  - Single-region attack targets bank/region 0
  - Simultaneous attack targets first N banks (specified by `banks_to_attack`)

- **Hybrid mode** (`num_banks = 1`): Traditional 2-region split
  - Uses `region_split_ratio` to allocate data blocks
  - Addresses interleaved for simultaneous attacks
  - Backward compatible with existing behavior

### 2. hybrid_wrapper_cache.py Updates

Transformed from 2-region to N-region architecture:

#### Constructor Changes
- New parameter: `num_regions` (default=2)
- Supports arbitrary number of regions (2, 4, 8, etc.)
- Creates N independent Mirage cache instances

#### Data Block Allocation
- **For num_regions=2**: Uses `region_split_ratio` (backward compatible)
- **For num_regions>2**: Equal split with remainder distribution

#### Key Features
- Each region has independent:
  - Data store with allocated capacity
  - Tag store (shared geometry: sets/ways/partitions)
  - Access/hit statistics
  
- **Skew handling**: All regions share the same skew configuration
  - `num_partitions`: Number of skewed hash functions
  - `num_tag_blocks_per_skew`: Tag storage per skew per region
  - Each region's cache handles skew logic independently

- **Additional tag handling**: Mirage's extra tags are preserved
  - `num_total_ways = num_blocks_per_set + num_additional_tags`
  - Tag blocks allocated per skew: `num_sets_per_skew * num_total_ways`
  - All regions use same tag geometry

#### Updated Methods
- `_compute_data_block_allocation()`: Computes per-region data block counts
- `read_refs_explicit()`: Enhanced to work with N regions
- `get_occupancy_stats()`: Returns stats for all N regions
- `print_occupancy_stats()`: Displays stats for all regions

## Important Mirage-Specific Considerations

### Skewed Caching
Mirage uses multiple skewed hash functions (partitions/skews) to distribute data:
- Each partition has its own hash function
- Within each partition, sets are organized with multiple ways
- Load balancing chooses less-occupied skew for new allocations

The multi-region wrapper preserves this by:
- Passing same `num_partitions` to all region caches
- Letting each region's cache instance handle skew logic
- Each region independently maintains skewed sets

### Additional Tags (Tag-Data Decoupling)
Mirage decouples tags from data:
- More tag entries than data entries possible
- `num_additional_tags`: Extra tags beyond data ways
- Enables higher tag capacity for better hit rates

The multi-region wrapper handles this by:
- Computing `num_tag_blocks_per_skew` per region
- Each region allocates own tag storage
- Data block constraints are per-region, not global

### Tag Store Structure
For each region:
```
num_sets_per_skew = (num_data_blocks / num_partitions) / num_blocks_per_set
num_tag_blocks_per_skew = num_sets_per_skew * (num_blocks_per_set + num_additional_tags)
num_total_ways = num_blocks_per_set + num_additional_tags
```

## Usage Example

### Multi-Bank Configuration (4 banks)
```python
sim = Simulator()
results = sim.run_simulation(
    num_blocks_per_set=16,
    num_words_per_block=8,
    cache_size=16*1024*1024,  # 16MB
    num_partitions=2,          # 2 skews
    replacement_policy='rand',
    num_addr_bits=40,
    num_additional_tags=4,     # Mirage-specific
    receiver_addresses=recv_addrs,
    sender_addresses=send_addrs,
    region_split_ratio=0.3,    # Ignored for num_banks>1
    attack_mode='simultaneous',
    num_banks=4,               # 4-bank mode
    banks_to_attack=2          # Attack first 2 banks
)
```

### Hybrid Configuration (2 regions, traditional)
```python
results = sim.run_simulation(
    # ... other params ...
    region_split_ratio=0.3,    # 30% region0, 70% region1
    attack_mode='region0',     # Single region attack
    num_banks=1                # Hybrid mode
)
```

## Testing Recommendations

1. **Verify bank distribution**: Check addresses map to correct banks
2. **Test region isolation**: Ensure strict_region=True prevents cross-region hits
3. **Validate skew balancing**: Confirm load balancing works per region
4. **Check tag storage**: Verify additional tags don't cause issues
5. **Compare with Ceaser**: Results should be architecturally consistent

## Backward Compatibility

- Default `num_banks=1` preserves original hybrid (2-region) behavior
- `region_split_ratio` still controls allocation in 2-region mode
- All existing code continues to work without changes
