import os
import sys

from arch_model import run_architecture_simulation
from common import (
    BYTES_PER_WORD,
    get_receiver_access_counts,
    get_selected_bank_capacity,
    get_target_banks_label,
    print_experiment_bank_config,
    sender_percent_for_0,
    sender_percent_for_1,
    target_occupancy_percentages,
    get_trial_addresses,
)


CASE_DIR = {
    "multibank": "multibank",
    "hybrid2": "hybrid_2region_75_25",
    "region4": "hybrid_4region",
}


def count_misses(tdict):
    return sum(1 for _, timing in tdict.items() if timing == 600)


def output_path(cfg, design_key, bit):
    base = cfg.output_dir
    if base is None:
        base = os.path.join("..", "results", CASE_DIR[cfg.architecture_mode], design_key)
    os.makedirs(base, exist_ok=True)
    target_banks_label = get_target_banks_label(cfg.target_banks)
    region_label = "regions_" + "-".join(str(r) for r in cfg.attack_regions)
    name = (
        f"outfile_v1_bit_{bit}_{cfg.architecture_mode}_banks{cfg.num_banks}_"
        f"{target_banks_label}_{region_label}.txt"
    )
    return os.path.join(base, name)


def run_design_experiment(design_key, cfg):
    bytes_per_line = cfg.num_words_per_block * BYTES_PER_WORD
    total_cache_lines = cfg.cache_size // bytes_per_line
    capacity_per_bank, selected_bank_capacity = get_selected_bank_capacity(
        total_cache_lines, cfg.num_banks, cfg.target_banks
    )
    sender_accesses_for_0 = int(total_cache_lines * sender_percent_for_0 / 100)
    sender_accesses_for_1 = int(total_cache_lines * sender_percent_for_1 / 100)
    receiver_access_counts = get_receiver_access_counts(selected_bank_capacity)

    print(f"Cache configuration ({design_key}):")
    print(f"  Cache size: {cfg.cache_size} bytes")
    print(f"  Block size: {bytes_per_line} bytes")
    print(f"  Blocks per set/base ways: {cfg.num_blocks_per_set}")
    print(f"  Native partitions/skews: {cfg.num_partitions}")
    print(f"  Trials: {cfg.trials}")
    print_experiment_bank_config(cfg, total_cache_lines, capacity_per_bank, selected_bank_capacity)
    print(f"Sender accesses: {sender_accesses_for_0} for bit '0', {sender_accesses_for_1} for bit '1'")

    file_0 = output_path(cfg, design_key, 0)
    file_1 = output_path(cfg, design_key, 1)
    if cfg.skip_existing and os.path.exists(file_0) and os.path.exists(file_1):
        print(f"Skipping existing outputs: {file_0}, {file_1}")
        return

    trial_addresses = get_trial_addresses(
        sender_accesses_for_0,
        sender_accesses_for_1,
        receiver_access_counts[-1],
        cfg=cfg,
        trials=cfg.trials,
    )

    def run_one(bit, path):
        with open(path, "w") as f:
            sender_key = "sender_0" if bit == 0 else "sender_1"
            for target_percent, num_receiver_addrs in zip(target_occupancy_percentages, receiver_access_counts):
                print(f"Target occupancy: {target_percent}% using {num_receiver_addrs} receiver addresses")
                for trial in range(cfg.trials):
                    addrs = trial_addresses[trial]
                    receiver_addrs = addrs["all_receiver"][:num_receiver_addrs]
                    timing_by_target = run_architecture_simulation(
                        design_key,
                        cfg,
                        receiver_addrs,
                        addrs[sender_key],
                    )
                    misses = [count_misses(timing_by_target[key]) for key in timing_by_target]
                    f.write(str([target_percent, num_receiver_addrs] + misses) + "\n")
                    f.flush()

    print(f"Writing bit 0 results: {file_0}")
    run_one(0, file_0)
    print(f"Writing bit 1 results: {file_1}")
    run_one(1, file_1)
    print(f"{design_key} simulation completed")
