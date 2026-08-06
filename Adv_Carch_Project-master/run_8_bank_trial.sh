#!/bin/bash
set -e

BASE="/home/mtp2/Thesis_Ambarish/multibank_llc/Adv_Carch_Project-master"

declare -A DIRS=(
  [mirage]="Mirage_cache_occupancy"
  [ceaser]="Ceaser_cache_occupancy"
  [ceaser_s]="Ceaser-s_cache_occupancy"
  [scatter]="ScatterCache_cache_occupancy"
  [normal]="Normal_cache_occupancy"
)

run_cache_trial() {
  local cache="$1"
  local dir="${DIRS[$cache]}"

  (
    echo "=== $cache: 8-bank sweep ==="
    cd "$BASE/$dir"

    # ratio is a don't-care once num-banks>2 (equal split across regions), fixed at 0.5 for a consistent label
    sed -i 's/region-split-ratio=.*/region-split-ratio=0.5/g' config.ini
    sed -i 's/attack-mode=.*/attack-mode=simultaneous/g' config.ini
    sed -i 's/num-banks=.*/num-banks=8/g' config.ini

    echo "  banks-to-attack=1 (single bank out of 8, others idle)"
    sed -i 's/banks-to-attack=.*/banks-to-attack=1/g' config.ini
    python3 main.py &
    sleep 1

    echo "  banks-to-attack=8 (all 8 banks simultaneously)"
    sed -i 's/banks-to-attack=.*/banks-to-attack=8/g' config.ini
    python3 main.py &
    sleep 1

    wait
    echo "  $cache 8-bank runs complete."

    # restore the 2-bank baseline so the single-design scripts keep working afterward
    sed -i 's/num-banks=.*/num-banks=2/g' config.ini
    sed -i 's/banks-to-attack=.*/banks-to-attack=2/g' config.ini
  ) &
}

for cache in mirage ceaser ceaser_s scatter normal; do
  run_cache_trial "$cache"
done

wait

echo "=== Generating plots for all 5 designs ==="
python3 -c "
from plot_diffs import plot_bit_diff_misses
for cache in ('mirage', 'ceaser', 'ceaser_s', 'scatter', 'normal'):
    plot_bit_diff_misses(cache, base_dir='results')
"

echo "All 8-bank runs and plots complete."
