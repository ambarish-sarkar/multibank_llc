#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main driver for covert-channel occupancy simulation (Ceaser_s Hybrid)
"""

from simulator import Simulator
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from common import *

def run_experiment(receiver_addrs, sender_addrs, cli_args):
    sim = Simulator()
    timing_by_region = sim.run_simulation(
        num_blocks_per_set=cli_args.num_blocks_per_set,
        num_words_per_block=cli_args.num_words_per_block,
        cache_size=cli_args.cache_size,
        num_partitions=cli_args.num_partitions,
        replacement_policy=cli_args.replacement_policy,
        num_addr_bits=cli_args.num_addr_bits,
        receiver_addresses=receiver_addrs,
        sender_addresses=sender_addrs,
        region_split_ratio=cli_args.region_split_ratio,
        attack_mode=cli_args.attack_mode,
        num_banks=cli_args.num_banks,
        banks_to_attack=cli_args.banks_to_attack,
        target_banks=cli_args.target_banks
    )

    # Count receiver misses (timing == 600)
    def count_misses(tdict):
        return sum(1 for _, t in tdict.items() if t == 600)

    # For simultaneous mode: return list of misses for each region
    if cli_args.attack_mode == 'simultaneous':
        return [count_misses(timing_by_region.get(f'region{i}', {})) for i in cli_args.target_banks]
    
    # Single-region modes: return single value
    return sum(count_misses(timing_by_region.get(f'region{i}', {})) for i in cli_args.target_banks)

if __name__ == '__main__':
    cli_args = parse_config()

    # Cache geometry printout
    bytes_per_line = cli_args.num_words_per_block * BYTES_PER_WORD
    total_cache_lines = cli_args.cache_size // bytes_per_line

    print(f"Cache configuration (Ceaser_s):")
    print(f"  Total cache lines (theoretical): {total_cache_lines}")
    print(f"  Cache size: {cli_args.cache_size} bytes")
    print(f"  Words per block: {cli_args.num_words_per_block}")
    print(f"  Blocks per set: {cli_args.num_blocks_per_set}")
    print(f"  Partitions: {cli_args.num_partitions}")
    print(f"  Region split ratio: {cli_args.region_split_ratio}")
    print(f"  Attack mode: {cli_args.attack_mode}")
    capacity_per_bank, selected_bank_capacity = get_selected_bank_capacity(
        total_cache_lines, cli_args.num_banks, cli_args.target_banks
    )
    print_experiment_bank_config(cli_args, total_cache_lines, capacity_per_bank, selected_bank_capacity)

    sender_accesses_for_0 = int(total_cache_lines * sender_percent_for_0 / 100)
    sender_accesses_for_1 = int(total_cache_lines * sender_percent_for_1 / 100)

    print(f"Sender accesses: {sender_accesses_for_0} ({sender_percent_for_0}%) for bit '0', "
          f"{sender_accesses_for_1} ({sender_percent_for_1}%) for bit '1'")

    # Receiver access counts to target occupancy (approx)
    receiver_access_counts = get_receiver_access_counts(selected_bank_capacity)
    target_banks_label = get_target_banks_label(cli_args.target_banks)

    if cli_args.num_banks > 1:
        file_0 = f"../results/ceaser_s/outfile_v1_bit_0_{cli_args.region_split_ratio}_{cli_args.attack_mode}_banks{cli_args.num_banks}_{target_banks_label}.txt"
        file_1 = f"../results/ceaser_s/outfile_v1_bit_1_{cli_args.region_split_ratio}_{cli_args.attack_mode}_banks{cli_args.num_banks}_{target_banks_label}.txt"
    else:
        file_0 = f"../results/ceaser_s/outfile_v1_bit_0_{cli_args.region_split_ratio}_{cli_args.attack_mode}.txt"
        file_1 = f"../results/ceaser_s/outfile_v1_bit_1_{cli_args.region_split_ratio}_{cli_args.attack_mode}.txt"

    print("Starting Ceaser_s covert channel experiment ...")
    print(f"Sender accesses: {sender_accesses_for_0} for bit '0', {sender_accesses_for_1} for bit '1'")

    # Store addresses for each trial to reuse in bit '1' experiment
    trial_addresses = get_trial_addresses(sender_accesses_for_0, sender_accesses_for_1, receiver_access_counts[-1], cli_args.target_banks, cli_args.num_banks, cli_args.num_words_per_block)

    # Experiment for bit '0'
    with open(file_0, "w") as f:
        print("\nSender transmitting bit '0'\n")
        for target_percent, num_receiver_addrs in zip(target_occupancy_percentages, receiver_access_counts):
            print(f"Target occupancy: {target_percent}% of selected-bank capacity (using {num_receiver_addrs} receiver addresses)")
            
            for trial in range(100):
                addrs = trial_addresses[trial]
                sender_addrs_for_0 = addrs["sender_0"]
                receiver_addrs = addrs["all_receiver"][:num_receiver_addrs]
                
                res = run_experiment(receiver_addrs, sender_addrs_for_0, cli_args)
                if cli_args.attack_mode == 'simultaneous':
                    # res is a list of misses per region
                    f.write(str([target_percent, num_receiver_addrs] + res) + "\n")
                else:
                    f.write(str([target_percent, num_receiver_addrs, res]) + "\n")
                f.flush()

    # Experiment for bit '1'
    with open(file_1, "w") as f:
        print("\nSender transmitting bit '1'\n")
        for target_percent, num_receiver_addrs in zip(target_occupancy_percentages, receiver_access_counts):
            print(f"Target occupancy: {target_percent}% of selected-bank capacity (using {num_receiver_addrs} receiver addresses)")
            
            for trial in range(100):
                # Retrieve THE SAME addresses used in bit '0' for this trial
                addrs = trial_addresses[trial]
                sender_addrs_for_1 = addrs['sender_1']
                all_receiver_addrs = addrs['all_receiver'][:num_receiver_addrs]
                
                # Use the SAME cumulative receiver addresses as bit '0'
                receiver_addrs = all_receiver_addrs[:num_receiver_addrs]
                
                res = run_experiment(receiver_addrs, sender_addrs_for_1, cli_args)
                if cli_args.attack_mode == 'simultaneous':
                    # res is a list of misses per region
                    f.write(str([target_percent, num_receiver_addrs] + res) + "\n")
                else:
                    f.write(str([target_percent, num_receiver_addrs, res]) + "\n")
                f.flush()

    print("\nCeaser_s cache covert channel simulation completed!")
