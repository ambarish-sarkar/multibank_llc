#!/usr/bin/env python3
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from arch_model import run_architecture_simulation
from common import Configs, configure_architecture, validate_target_banks


class Simulator(object):
    DESIGN = "normal"

    def run_simulation(self, num_blocks_per_set, num_words_per_block, cache_size,
                       num_partitions, replacement_policy, num_addr_bits,
                       receiver_addresses, sender_addresses, region_split_ratio=0.75,
                       attack_mode="simultaneous", num_banks=1, banks_to_attack=1,
                       target_banks=None, architecture_mode="multibank",
                       num_regions=1, attack_regions=None, num_additional_tags=6):
        cfg = Configs()
        cfg.cache_size = cache_size
        cfg.num_blocks_per_set = num_blocks_per_set
        cfg.num_words_per_block = num_words_per_block
        cfg.num_partitions = num_partitions
        cfg.num_additional_tags = num_additional_tags
        cfg.replacement_policy = replacement_policy
        cfg.num_addr_bits = num_addr_bits
        cfg.region_split_ratio = region_split_ratio
        cfg.attack_mode = attack_mode
        cfg.num_banks = num_banks
        cfg.target_banks = validate_target_banks(target_banks or list(range(banks_to_attack)), num_banks)
        cfg.banks_to_attack = len(cfg.target_banks)
        cfg.architecture_mode = architecture_mode
        cfg.num_regions = num_regions
        cfg.attack_regions = attack_regions or ([1] if architecture_mode == "hybrid2" else ([0, 1, 2, 3] if architecture_mode == "region4" else [0]))
        cfg.strict_region = True
        cfg.strict_integer_split = True
        cfg.workload_mode = "default"
        configure_architecture(cfg)
        return run_architecture_simulation(self.DESIGN, cfg, receiver_addresses, sender_addresses)
