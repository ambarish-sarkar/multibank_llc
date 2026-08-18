import random
import configparser
import math
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

def parse_config():
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
    c.region_split_ratio = float(cfg.get('region-split-ratio', 0.3))
    c.attack_mode = cfg.get('attack-mode', 'region0').lower()  # region0|region1|simultaneous
    c.num_banks = int(cfg.get('num-banks', 1))
    c.banks_to_attack = int(cfg.get('banks-to-attack', 1))
    if c.attack_mode not in ('region0', 'region1', 'simultaneous'):
        raise ValueError("attack-mode must be 'region0', 'region1', or 'simultaneous'")
    explicit_target_banks = 'target-banks' in cfg
    if not explicit_target_banks and (c.banks_to_attack < 1 or c.banks_to_attack > c.num_banks):
        raise ValueError(
            f"banks-to-attack ({c.banks_to_attack}) must be between 1 and num-banks ({c.num_banks})"
        )
    c.target_banks = resolve_target_banks(
        c.attack_mode,
        c.num_banks,
        c.banks_to_attack,
        cfg.get('target-banks') if explicit_target_banks else None,
    )
    c.target_banks_source = 'target-banks' if explicit_target_banks else 'legacy banks-to-attack/attack-mode'
    if explicit_target_banks and 'banks-to-attack' in cfg and c.banks_to_attack != len(c.target_banks):
        print(
            "target-banks is set; overriding legacy banks-to-attack "
            f"count {c.banks_to_attack} with {len(c.target_banks)} selected banks"
        )
    c.banks_to_attack = len(c.target_banks)
    return c


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
    print("  region_split_ratio is legacy/unused for equal-capacity S-NUCA banks")

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

def get_trial_addresses(sender_accesses_for_0, sender_accesses_for_1, max_receiver_accesses, target_banks, num_banks, num_words_per_block):
    trial_addresses = {}
    for trial in range(100):
        unique_sender_addr = set()
        if target_banks is None:
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
