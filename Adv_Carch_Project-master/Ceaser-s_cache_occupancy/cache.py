#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May 18 17:53:27 2021

@author: anirban
"""
from bin_addr import BinaryAddress
from word_addr import WordAddress
from reference import ReferenceCacheStatus
import random

class Cache(dict):
    partition = None
    cal_index = None
    def __init__(self, cache=None, num_sets=None, num_index_bits=None, num_partitions = None, ways_per_partition = None):
       
        self.recently_used_addrs = []
        if cache is not None:
            self.update(cache)
        else:
            for j in range(num_partitions):
                for i in range(num_sets):                
                    index = BinaryAddress(word_addr = WordAddress(i), num_addr_bits = num_index_bits)
                    self[str(j)+str(index)] = []            
            
    def mark_ref_as_last_seen(self, ref):
        addr_id = (ref.index, ref.tag)
        if addr_id in self.recently_used_addrs:
            self.recently_used_addrs.remove(addr_id)
        self.recently_used_addrs.append(addr_id)
        
        
    def is_hit(self, addr_partition, addr_index, addr_tag, num_partitions):
        global partition
        global cal_index
        num_index_bits = int(len(addr_index[0]))
        blocks = []
        if addr_index[0] is None:
            blocks = self[str(0).zfill(num_index_bits)]
        else:
            for i in range(num_partitions):
                actual_index = str(i)+str(addr_index[i])
                empty_set = True 
                if (actual_index) in self:
                    blocks = self[actual_index]
                    for block in blocks:    # enumerate through all the ways to find if any tag is present
                        if 'tag' in block.keys():
                            empty_set = False
                            break
                    if empty_set == True:
                        continue
                    else:
                        for block in blocks:
                            if ('tag' in block.keys() and block['tag'] == addr_tag):    # if the tag matches, then return true; else false in all cases
                                partition = i
                                cal_index = addr_index[i]
                                return True
                else:
                    return False  
        return False            
                
    def replace_block(self, blocks, replacement_policy, num_blocks_per_set, addr_partition, num_partition, addr_index, new_entry):
        if (replacement_policy == 'rand'):
            repl_block_index = random.randint(0, (num_blocks_per_set // num_partition) - 1)
            for (i, block) in enumerate(blocks):
                if (i == repl_block_index):
                    blocks[i] = new_entry
                    return
        if (replacement_policy == 'lru'):
            recently_used_addrs = self.recently_used_addrs
            for recent_index, recent_tag in recently_used_addrs:
                for i, block in enumerate(blocks):
                    if (recent_index == addr_index and block['tag'] == recent_tag):
                        blocks[i] = new_entry
                        return
                
    def set_block(self, replacement_policy, num_blocks_per_set, addr_partition, num_partition, addr_index, new_entry):
        # CEASER-S: addr_partition = (0, 1), addr_index = (index1, index2)
        # On miss, randomly pick one half to install the line
        
        if addr_index is None or addr_index[0] is None:
            # Handle null case - use partition 0
            chosen_partition = 0
            chosen_index = "0"
            num_index_bits = 1
        else:
            # Randomly choose between the two partitions (Left=0, Right=1)
            chosen_partition_idx = random.randint(0, len(addr_partition) - 1)
            chosen_partition = addr_partition[chosen_partition_idx]
            chosen_index = addr_index[chosen_partition_idx]
            num_index_bits = len(chosen_index)
        
        # Create cache key for the chosen partition
        cache_key = str(chosen_partition) + str(chosen_index).zfill(num_index_bits)
        
        # Get or create the blocks list for this cache location
        if cache_key not in self:
            self[cache_key] = []
        blocks = self[cache_key]
        
        # Check if we need replacement or can just append
        ways_per_partition = num_blocks_per_set // len(addr_partition)
        if (len(blocks) == ways_per_partition):
            self.replace_block(blocks, replacement_policy, num_blocks_per_set, chosen_partition, num_partition, chosen_index, new_entry)
        else:
            blocks.append(new_entry)
            
            
    def read_refs(self, num_blocks_per_set, num_words_per_block, num_partitions, replacement_policy, refs):
        for ref in refs:
            self.mark_ref_as_last_seen(ref)
            if self.is_hit(ref.partition, ref.index, ref.tag, num_partitions):
                ref.cache_status = ReferenceCacheStatus.hit
                ref.partition = partition
                ref.index = cal_index
                    
            else:
                ref.cache_status = ReferenceCacheStatus.miss
                self.set_block(
                        replacement_policy = replacement_policy,
                        num_blocks_per_set = num_blocks_per_set,
                        addr_partition = ref.partition,
                        num_partition = num_partitions,
                        addr_index = ref.index,
                        new_entry = ref.get_cache_entry(num_words_per_block)
                        )
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        