import random
import configparser
import math
import argparse
MIN_ADDRESS = 0
MAX_ADDRESS = 10000000000
BYTES_PER_WORD = 8

# Percentages (relative to cache lines)
target_occupancy_percentages = [1, 2, 5, 10, 15, 20, 25, 30, 35, 40]
sender_percent_for_0 = 1  # % of lines for bit '0'
sender_percent_for_1 = 2  # % of lines for bit '1'

class Configs:
    def __init__(self):
        self.cache_size = 0
        self.num_blocks_per_set = 0
        self.num_additional_tags = 0 # only used by mirage
        self.num_partitions = 0
        self.num_words_per_block = 0
        self.num_addr_bits = 0
        self.replacement_policy = ""
        self.region_split_ratio = 0.0
        self.attack_mode = ""
        self.num_banks = 0
        self.banks_to_attack = 0
        self.target_banks = []
        self.target_banks_source = ""
        self.architecture_mode = "multibank"
        self.num_regions = 1
        self.region_split_ratio = 0.75
        self.region_split_policy = ""
        self.strict_region = True
        self.strict_integer_split = True
        self.attack_regions = [0]
        self.attack_regions_source = ""
        self.workload_mode = "default"
        self.trials = 100
        self.output_dir = None
        self.skip_existing = False
        self.region_fractions = [1.0]
        self.region_way_groups = [[16]]
        self.region_skews = [[0]]

def parse_config(argv=None):
    parser = configparser.ConfigParser()
    parser.read('config.ini')
    cfg = parser[parser.sections()[0]]

    c = Configs()
    c.cache_size = int(cfg['cache-size'])                      # bytes
    c.num_blocks_per_set = int(cfg['num-blocks-per-set'])
    if 'num-additional-tags' in cfg:
        c.num_additional_tags = int(cfg['num-additional-tags'])
    c.num_partitions = int(cfg['num-partitions'])
    c.num_words_per_block = int(cfg['num-words-per-block'])
    c.num_addr_bits = int(cfg['num-addr-bits'])
    c.replacement_policy = cfg.get('replacement-policy', 'rand')
    c.region_split_ratio = float(cfg.get('region-split-ratio', 0.75))
    c.attack_mode = cfg.get('attack-mode', 'region0').lower()  # region0|region1|simultaneous
    c.num_banks = int(cfg.get('num-banks', 1))
    c.banks_to_attack = int(cfg.get('banks-to-attack', 1))
    c.architecture_mode = cfg.get('architecture-mode', 'multibank').lower()
    c.num_regions = int(cfg.get('num-regions', 1))
    c.region_split_policy = cfg.get('region-split-policy', '').lower()
    c.strict_region = cfg.get('strict-region', 'true').lower() == 'true'
    c.strict_integer_split = cfg.get('strict-integer-split', 'true').lower() == 'true'
    c.workload_mode = cfg.get('workload-mode', 'default').lower()
    c.trials = int(cfg.get('trials', 100))
    c.output_dir = cfg.get('output-dir', None)
    c.skip_existing = cfg.get('skip-existing', 'false').lower() == 'true'

    overrides = _parse_cli_overrides(argv)
    for key, value in vars(overrides).items():
        if value is not None:
            setattr(c, key.replace('-', '_'), value)
    if c.attack_mode not in ('region0', 'region1', 'simultaneous'):
        raise ValueError("attack-mode must be 'region0', 'region1', or 'simultaneous'")
    target_banks_text = overrides.target_banks if overrides.target_banks is not None else cfg.get('target-banks')
    explicit_target_banks = target_banks_text is not None
    if not explicit_target_banks and (c.banks_to_attack < 1 or c.banks_to_attack > c.num_banks):
        raise ValueError(
            f"banks-to-attack ({c.banks_to_attack}) must be between 1 and num-banks ({c.num_banks})"
        )
    c.target_banks = resolve_target_banks(
        c.attack_mode,
        c.num_banks,
        c.banks_to_attack,
        target_banks_text if explicit_target_banks else None,
    )
    c.target_banks_source = 'target-banks' if explicit_target_banks else 'legacy banks-to-attack/attack-mode'
    if explicit_target_banks and 'banks-to-attack' in cfg and c.banks_to_attack != len(c.target_banks):
        print(
            "target-banks is set; overriding legacy banks-to-attack "
            f"count {c.banks_to_attack} with {len(c.target_banks)} selected banks"
        )
    c.banks_to_attack = len(c.target_banks)
    attack_regions_text = overrides.attack_regions if overrides.attack_regions is not None else cfg.get('attack-regions')
    c.attack_regions = resolve_attack_regions(c.architecture_mode, c.num_regions, attack_regions_text)
    c.attack_regions_source = 'attack-regions' if attack_regions_text is not None else 'architecture-mode default'
    configure_architecture(c)
    return c


def _parse_cli_overrides(argv=None):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument('--cache-size', type=int)
    p.add_argument('--num-blocks-per-set', type=int)
    p.add_argument('--num-partitions', type=int)
    p.add_argument('--num-additional-tags', type=int)
    p.add_argument('--num-words-per-block', type=int)
    p.add_argument('--num-addr-bits', type=int)
    p.add_argument('--replacement-policy')
    p.add_argument('--region-split-ratio', type=float)
    p.add_argument('--attack-mode')
    p.add_argument('--num-banks', type=int)
    p.add_argument('--banks-to-attack', type=int)
    p.add_argument('--target-banks')
    p.add_argument('--architecture-mode')
    p.add_argument('--num-regions', type=int)
    p.add_argument('--region-split-policy')
    p.add_argument('--strict-region', type=lambda s: s.lower() == 'true')
    p.add_argument('--strict-integer-split', type=lambda s: s.lower() == 'true')
    p.add_argument('--attack-regions')
    p.add_argument('--workload-mode')
    p.add_argument('--trials', type=int)
    p.add_argument('--output-dir')
    p.add_argument('--skip-existing', action='store_true')
    args, _ = p.parse_known_args(argv)
    return args


def parse_target_banks(target_banks_text):
    if target_banks_text is None:
        return None
    text = str(target_banks_text).strip()
    if not text:
        raise ValueError("target-banks must specify at least one bank")
    banks = []
    for token in text.split(','):
        token = token.strip()
        if not token:
            raise ValueError(f"Invalid empty bank in target-banks={target_banks_text!r}")
        try:
            bank = int(token)
        except ValueError as exc:
            raise ValueError(f"Invalid bank ID {token!r} in target-banks") from exc
        banks.append(bank)
    return banks


def parse_int_list(text, name):
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        raise ValueError(f"{name} must specify at least one value")
    values = []
    for token in raw.split(','):
        token = token.strip()
        if not token:
            raise ValueError(f"Invalid empty value in {name}={text!r}")
        try:
            values.append(int(token))
        except ValueError as exc:
            raise ValueError(f"Invalid integer {token!r} in {name}") from exc
    return values


def validate_regions(regions, num_regions):
    if not regions:
        raise ValueError("At least one target region must be specified")
    seen = set()
    for region in regions:
        if region in seen:
            raise ValueError(f"Duplicate target region ID: {region}")
        seen.add(region)
        if region < 0 or region >= num_regions:
            raise ValueError(f"Target region {region} is outside valid range 0..{num_regions - 1}")
    return list(regions)


def resolve_attack_regions(architecture_mode, num_regions, attack_regions_text=None):
    explicit = parse_int_list(attack_regions_text, "attack-regions")
    if explicit is not None:
        return validate_regions(explicit, num_regions)
    if architecture_mode == "hybrid2":
        return [1]
    if architecture_mode == "region4":
        return [0, 1, 2, 3]
    return [0]


def require_integer_split(total, ratio, label):
    exact = total * ratio
    rounded = int(round(exact))
    if abs(exact - rounded) > 1e-9:
        raise ValueError(
            "Invalid hybrid region ratio:\n"
            f"{total} ways * {ratio:.2f} = {exact:g} ways.\n"
            "Region allocations must contain whole ways."
        )
    return rounded


def configure_architecture(c):
    if c.architecture_mode not in ("multibank", "hybrid2", "region4"):
        raise ValueError("architecture-mode must be multibank, hybrid2, or region4")
    if c.workload_mode != "default":
        raise ValueError("Only workload-mode=default is implemented in this campaign")
    if c.architecture_mode == "multibank":
        c.num_regions = 1
        c.attack_regions = [0]
        c.region_fractions = [1.0]
    elif c.architecture_mode == "hybrid2":
        c.num_regions = 2
        c.region_fractions = [c.region_split_ratio, 1.0 - c.region_split_ratio]
        c.attack_regions = validate_regions(c.attack_regions, c.num_regions)
    else:
        c.num_regions = 4
        c.region_fractions = [0.25, 0.25, 0.25, 0.25]
        c.attack_regions = validate_regions(c.attack_regions, c.num_regions)


def validate_architecture_config(c, design):
    bytes_per_line = c.num_words_per_block * BYTES_PER_WORD
    if bytes_per_line != 64:
        raise ValueError(f"block size must be 64 B, got {bytes_per_line}")
    if c.cache_size // bytes_per_line != 131072:
        raise ValueError("total data lines must be 131072")
    if c.num_banks not in (1, 2, 4):
        raise ValueError("num-banks must be 1, 2, or 4 for the 16-way campaign")
    if design == "mirage":
        if c.num_blocks_per_set != 8 or c.num_partitions != 2 or c.num_additional_tags != 6:
            raise ValueError("MIRAGE must use 8 base ways, 6 additional tags, and 2 native tag skews")
    else:
        if c.num_blocks_per_set != 16:
            raise ValueError("Conventional designs must use num-blocks-per-set=16")
    if design in ("normal", "ceaser"):
        if c.architecture_mode == "multibank":
            c.region_way_groups = [[16]]
        elif c.architecture_mode == "hybrid2":
            large = require_integer_split(16, c.region_split_ratio, "hybrid2")
            c.region_way_groups = [[large], [16 - large]]
        else:
            c.region_way_groups = [[4], [4], [4], [4]]
    elif design == "ceaser_s":
        if c.num_partitions != 2:
            raise ValueError("CEASER-S must retain 2 native encrypted skews")
        if c.architecture_mode == "multibank":
            c.region_way_groups = [[8, 8]]
        elif c.architecture_mode == "hybrid2":
            large = require_integer_split(16, c.region_split_ratio, "hybrid2")
            small = 16 - large
            if large % 2 or small % 2:
                raise ValueError("CEASER-S hybrid ways must divide cleanly across 2 skews")
            c.region_way_groups = [[large // 2, large // 2], [small // 2, small // 2]]
        else:
            c.region_way_groups = [[2, 2], [2, 2], [2, 2], [2, 2]]
    elif design == "scatter":
        if c.architecture_mode == "multibank":
            c.region_skews = [list(range(16))]
        elif c.architecture_mode == "hybrid2":
            large = require_integer_split(16, c.region_split_ratio, "hybrid2")
            c.region_skews = [list(range(large)), list(range(large, 16))]
        else:
            c.region_skews = [list(range(0, 4)), list(range(4, 8)), list(range(8, 12)), list(range(12, 16))]
        c.region_way_groups = [[1 for _ in skews] for skews in c.region_skews]
    elif design == "mirage":
        pass
    else:
        raise ValueError(f"Unknown design {design}")


def validate_target_banks(target_banks, num_banks):
    if target_banks is None or len(target_banks) == 0:
        raise ValueError("At least one target bank must be specified")
    seen = set()
    for bank in target_banks:
        if bank in seen:
            raise ValueError(f"Duplicate target bank ID: {bank}")
        seen.add(bank)
        if bank < 0 or bank >= num_banks:
            raise ValueError(f"Target bank {bank} is outside valid range 0..{num_banks - 1}")
    return list(target_banks)


def resolve_target_banks(attack_mode, num_banks, banks_to_attack=1, target_banks_text=None):
    explicit = parse_target_banks(target_banks_text)
    if explicit is not None:
        return validate_target_banks(explicit, num_banks)
    if attack_mode == 'region1' and num_banks > 1:
        legacy = [1]
    elif attack_mode in ('region0', 'region1'):
        legacy = [0]
    else:
        if banks_to_attack <= 0:
            raise ValueError("banks-to-attack must be at least 1")
        if banks_to_attack > num_banks:
            raise ValueError(f"banks-to-attack ({banks_to_attack}) cannot exceed num-banks ({num_banks})")
        legacy = list(range(banks_to_attack))
    return validate_target_banks(legacy, num_banks)


def get_total_cache_lines(cache_size, num_words_per_block):
    bytes_per_line = num_words_per_block * BYTES_PER_WORD
    return cache_size // bytes_per_line


def get_selected_bank_capacity(total_cache_lines, num_banks, target_banks):
    validate_target_banks(target_banks, num_banks)
    if total_cache_lines % num_banks != 0:
        raise ValueError("total cache lines must be divisible by num_banks")
    capacity_per_bank = total_cache_lines // num_banks
    selected_capacity = capacity_per_bank * len(target_banks)
    return capacity_per_bank, selected_capacity


def get_target_region_capacity(capacity_per_bank, cfg):
    return int(capacity_per_bank * sum(cfg.region_fractions[r] for r in cfg.attack_regions))


def get_target_pairs(cfg):
    return [(bank, region) for bank in cfg.target_banks for region in cfg.attack_regions]


def get_receiver_access_counts(selected_bank_capacity):
    return [
        int(selected_bank_capacity * pct / 100)
        for pct in target_occupancy_percentages
    ]


def get_target_banks_label(target_banks):
    return "banks_" + "-".join(str(bank) for bank in target_banks)


def print_experiment_bank_config(cli_args, total_cache_lines, capacity_per_bank, selected_bank_capacity):
    print(f"  Number of banks: {cli_args.num_banks}")
    print(f"  Target banks: {cli_args.target_banks}")
    print(f"  Target bank source: {cli_args.target_banks_source}")
    print(f"  Number of target banks: {len(cli_args.target_banks)}")
    print(f"  Total cache lines: {total_cache_lines}")
    print(f"  Capacity per bank: {capacity_per_bank}")
    print(f"  Selected bank capacity: {selected_bank_capacity}")
    print(f"  Architecture mode: {cli_args.architecture_mode}")
    print(f"  Internal regions per bank: {cli_args.num_regions}")
    print(f"  Attack regions: {cli_args.attack_regions}")
    print(f"  Region fractions: {cli_args.region_fractions}")

def get_new_random_addresses(unique_sender_addr, num_addresses):
    new_addresses = []
    while(num_addresses > 0):
        new_address = random.randint(MIN_ADDRESS, MAX_ADDRESS)
        if new_address not in unique_sender_addr:
            new_addresses.append(new_address)
            unique_sender_addr.add(new_address)
            num_addresses -= 1
    return new_addresses

def require_power_of_two(value, name):
    if value <= 0 or (value & (value - 1)) != 0:
        raise ValueError(f"{name} must be a positive power of two")


def get_block_number(word_address, num_words_per_block):
    """Addresses in this simulator are word addresses, not byte addresses."""
    return int(word_address) // int(num_words_per_block)


def get_bank_id(word_address, num_banks, num_words_per_block):
    """Determine the S-NUCA bank from a word-address block number."""
    block_number = get_block_number(word_address, num_words_per_block)
    return block_number % num_banks


def get_region_id_from_block(block_number, num_banks, sets_per_bank, num_regions):
    """Select an internal way-partition region independently of bank-local set.

    S-NUCA bank selection uses the low ``log2(num_banks)`` block bits and the
    bank-local set uses the next ``log2(sets_per_bank)`` bits.  Region selection
    uses the remaining stream above those fields:

        block = ((region_stream * sets_per_bank) + local_set) * num_banks + bank

    Varying ``region_stream`` changes the region without changing the physical
    bank or bank-local set, so strict regions partition ways/capacity, not sets.
    """
    if num_regions <= 1:
        return 0
    region_stream = int(block_number) // (int(num_banks) * int(sets_per_bank))
    return region_stream % int(num_regions)


def get_region_id(word_address, cfg):
    geom = get_snuca_geometry(cfg.cache_size, cfg.num_words_per_block, 16, cfg.num_banks)
    block_number = get_block_number(word_address, cfg.num_words_per_block)
    return get_region_id_from_block(
        block_number,
        cfg.num_banks,
        geom["sets_per_bank"],
        cfg.num_regions,
    )


def get_snuca_geometry(cache_size, num_words_per_block, num_blocks_per_set, num_banks):
    require_power_of_two(num_words_per_block, "num_words_per_block")
    require_power_of_two(num_blocks_per_set, "num_blocks_per_set")
    require_power_of_two(num_banks, "num_banks")

    total_blocks = (cache_size // BYTES_PER_WORD) // num_words_per_block
    if total_blocks % num_blocks_per_set != 0:
        raise ValueError("total cache blocks must be divisible by ways/set")

    global_num_sets = total_blocks // num_blocks_per_set
    require_power_of_two(global_num_sets, "global_num_sets")
    if global_num_sets % num_banks != 0:
        raise ValueError("global_num_sets must be divisible by num_banks")

    sets_per_bank = global_num_sets // num_banks
    require_power_of_two(sets_per_bank, "sets_per_bank")

    global_index_bits = int(math.log2(global_num_sets))
    bank_bits = int(math.log2(num_banks))
    local_index_bits = int(math.log2(sets_per_bank))
    if global_index_bits != bank_bits + local_index_bits:
        raise ValueError("S-NUCA bit decomposition is inconsistent")

    aggregate_lines = num_banks * sets_per_bank * num_blocks_per_set
    if aggregate_lines != total_blocks:
        raise ValueError("S-NUCA geometry does not preserve aggregate capacity")

    return {
        "total_blocks": total_blocks,
        "global_num_sets": global_num_sets,
        "sets_per_bank": sets_per_bank,
        "global_index_bits": global_index_bits,
        "bank_bits": bank_bits,
        "local_index_bits": local_index_bits,
        "aggregate_lines": aggregate_lines,
    }


def get_local_set(word_address, num_words_per_block, num_banks, sets_per_bank):
    block_number = get_block_number(word_address, num_words_per_block)
    return (block_number // num_banks) % sets_per_bank


def get_new_random_addresses_for_banks(unique_sender_addr, num_addresses, target_banks, num_banks, num_words_per_block):
    """Generate random addresses that map to specific target banks."""
    new_addresses = []
    max_attempts = num_addresses * 1000  # Prevent infinite loop
    attempts = 0
    
    while num_addresses > 0 and attempts < max_attempts:
        new_address = random.randint(MIN_ADDRESS, MAX_ADDRESS)
        attempts += 1
        
        # Check if address is unique and maps to one of the target banks
        if new_address not in unique_sender_addr:
            bank_id = get_bank_id(new_address, num_banks, num_words_per_block)
            if bank_id in target_banks:
                new_addresses.append(new_address)
                unique_sender_addr.add(new_address)
                num_addresses -= 1
    
    if num_addresses > 0:
        print(f"Warning: Could only generate {len(new_addresses)} addresses for target banks after {max_attempts} attempts")
    
    return new_addresses


def get_new_random_addresses_for_targets(unique_sender_addr, num_addresses, cfg):
    """Generate unique addresses matching selected physical banks and internal regions."""
    target_pairs = set(get_target_pairs(cfg))
    if num_addresses <= 0:
        return []
    new_addresses = []
    max_attempts = max(10000, num_addresses * 5000)
    attempts = 0
    while num_addresses > 0 and attempts < max_attempts:
        new_address = random.randint(MIN_ADDRESS, MAX_ADDRESS)
        attempts += 1
        if new_address in unique_sender_addr:
            continue
        bank_id = get_bank_id(new_address, cfg.num_banks, cfg.num_words_per_block)
        region_id = get_region_id(new_address, cfg)
        if (bank_id, region_id) in target_pairs:
            new_addresses.append(new_address)
            unique_sender_addr.add(new_address)
            num_addresses -= 1
    if num_addresses > 0:
        raise RuntimeError(
            f"Could not generate enough addresses for banks={cfg.target_banks} "
            f"regions={cfg.attack_regions}; missing {num_addresses}"
        )
    return new_addresses

def get_trial_addresses(sender_accesses_for_0, sender_accesses_for_1, max_receiver_accesses, target_banks=None, num_banks=1, num_words_per_block=8, cfg=None, trials=100):
    trial_addresses = {}
    for trial in range(trials):
        unique_sender_addr = set()
        if cfg is not None:
            sender_addrs_for_0 = get_new_random_addresses_for_targets(unique_sender_addr, sender_accesses_for_0, cfg)
            sender_addrs_for_1 = sender_addrs_for_0 + get_new_random_addresses_for_targets(unique_sender_addr, sender_accesses_for_1 - sender_accesses_for_0, cfg)
            all_receiver_addrs = get_new_random_addresses_for_targets(unique_sender_addr, max_receiver_accesses, cfg)
        elif target_banks is None:
            # Single bank mode
            sender_addrs_for_0 = get_new_random_addresses(unique_sender_addr, sender_accesses_for_0)
            sender_addrs_for_1 = sender_addrs_for_0 + get_new_random_addresses(unique_sender_addr, sender_accesses_for_1 - sender_accesses_for_0)
            # Generate all receiver addresses (maximum needed = 40%)
            all_receiver_addrs = get_new_random_addresses(unique_sender_addr, max_receiver_accesses)
        else:
            sender_addrs_for_0 = get_new_random_addresses_for_banks(unique_sender_addr, sender_accesses_for_0, target_banks, num_banks, num_words_per_block)
            sender_addrs_for_1 = sender_addrs_for_0 + get_new_random_addresses_for_banks(unique_sender_addr, sender_accesses_for_1 - sender_accesses_for_0, target_banks, num_banks, num_words_per_block)
            # Generate all receiver addresses (maximum needed = 40%)
            all_receiver_addrs = get_new_random_addresses_for_banks(unique_sender_addr, max_receiver_accesses, target_banks, num_banks, num_words_per_block)
        # Store addresses for this trial
        trial_addresses[trial] = {
                'sender_0': sender_addrs_for_0,
                'sender_1': sender_addrs_for_1,
                'all_receiver': all_receiver_addrs
        }
    return trial_addresses
