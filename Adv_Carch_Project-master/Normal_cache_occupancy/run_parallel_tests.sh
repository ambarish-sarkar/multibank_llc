#!/bin/bash

# Parallel Cache Configuration Testing Script
# This script runs the randomized cache occupancy attack with different cache configurations in parallel

echo "Starting Parallel Cache Configuration Tests"
echo "==========================================="

# Cache sizes in MB (4MB to 16MB in powers of 2)
cache_sizes=(4 8 16)

# Associativities to test
associativities=(1 2 4 8 16)

# Function to run a single configuration
run_config() {
    local cache_size_mb=$1
    local associativity=$2
    local cache_size_words=$((cache_size_mb * 1024 * 1024))  # Convert MB to words
    
    echo "Starting test for ${cache_size_mb}MB ${associativity}-way cache..."
    
    # Create a temporary config file for this configuration
    local config_file="config_${cache_size_mb}MB_${associativity}way.ini"
    
    # Copy the original config and modify it
    cp config.ini "$config_file"
    
    # Update the configuration using sed
    sed -i.bak "s/^cache-size=.*/cache-size=${cache_size_words}/" "$config_file"
    sed -i.bak "s/^num-blocks-per-set=.*/num-blocks-per-set=${associativity}/" "$config_file"
    
    # Remove backup file
    rm "${config_file}.bak" 2>/dev/null || true
    
    # Create a temporary copy of the main script that uses this config file
    local script_name="main_${cache_size_mb}MB_${associativity}way.py"
    cp main_randomized.py "$script_name"
    
    # Replace config.ini with our temporary config file in the script
    sed -i.bak "s/config\.ini/${config_file}/g" "$script_name"
    
    # Remove backup file
    rm "${script_name}.bak" 2>/dev/null || true
    
    # Run the experiment
    python3 "$script_name" > "log_${cache_size_mb}MB_${associativity}way.txt" 2>&1
    
    # Clean up temporary files
    rm "$config_file" "$script_name"
    
    echo "Completed test for ${cache_size_mb}MB ${associativity}-way cache!"
}

# Export the function so it can be used by parallel processes
export -f run_config

# Calculate total number of configurations
total_configs=$((${#cache_sizes[@]} * ${#associativities[@]}))
echo "Total configurations to test: $total_configs"
echo "Cache sizes: ${cache_sizes[*]} MB"
echo "Associativities: ${associativities[*]}-way"
echo ""

# Create array of all configuration combinations
configs=()
for cache_size in "${cache_sizes[@]}"; do
    for assoc in "${associativities[@]}"; do
        configs+=("$cache_size $assoc")
    done
done

# Check if GNU parallel is available
if command -v parallel &> /dev/null; then
    echo "Using GNU parallel for maximum efficiency..."
    # Use GNU parallel to run configurations in parallel
    printf '%s\n' "${configs[@]}" | parallel --colsep ' ' run_config {1} {2}
else
    echo "GNU parallel not found. Running with limited parallelism using background processes..."
    
    # Maximum number of parallel processes (adjust based on your system)
    max_parallel=4
    current_jobs=0
    
    # Run configurations with limited parallelism
    for config in "${configs[@]}"; do
        read -r cache_size assoc <<< "$config"
        
        # Wait if we've reached the maximum number of parallel jobs
        while [ $current_jobs -ge $max_parallel ]; do
            wait -n  # Wait for any background job to complete
            current_jobs=$((current_jobs - 1))
        done
        
        # Start the configuration test in background
        run_config "$cache_size" "$assoc" &
        current_jobs=$((current_jobs + 1))
        
        echo "Started background job for ${cache_size}MB ${assoc}-way (${current_jobs}/${max_parallel} active)"
    done
    
    # Wait for all remaining background jobs to complete
    echo "Waiting for all remaining jobs to complete..."
    wait
fi

echo ""
echo "All parallel cache configuration tests completed!"
echo "================================================"

# List all generated output files
echo "Generated output files:"
ls -la outfile_randomized_bit_*_*MB_*way.txt 2>/dev/null || echo "No output files found"

echo ""
echo "Generated log files:"
ls -la log_*MB_*way.txt 2>/dev/null || echo "No log files found"

echo ""
echo "Summary:"
echo "- Total configurations tested: $total_configs"
echo "- Each configuration generates 2 output files (bit_0 and bit_1)"
echo "- Each configuration generates 1 log file"
echo "- Expected total files: $((total_configs * 3))"

# Count actual files generated
output_files=$(ls outfile_randomized_bit_*_*MB_*way.txt 2>/dev/null | wc -l)
log_files=$(ls log_*MB_*way.txt 2>/dev/null | wc -l)
total_files=$((output_files + log_files))

echo "- Actual files generated: $total_files"

if [ $total_files -eq $((total_configs * 3)) ]; then
    echo "All tests completed successfully!"
else
    echo "Some tests may have failed. Check log files for errors."
fi