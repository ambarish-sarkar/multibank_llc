#!/bin/bash
set -e

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

declare -A DIRS=(
  [ceaser_s]="Ceaser-s_cache_occupancy"
  [scatter]="ScatterCache_cache_occupancy"
)

run_cache_bank_sweep() {
  local cache="$1"
  local banks="$2"
  local dir="${DIRS[$cache]}"

  echo "=== $cache: ${banks}-bank sweep ==="
  cd "$BASE/$dir"

  sed -i 's/region-split-ratio=.*/region-split-ratio=0.5/g' config.ini
  sed -i 's/attack-mode=.*/attack-mode=simultaneous/g' config.ini
  sed -i "s/num-banks=.*/num-banks=${banks}/g" config.ini

  echo "  banks-to-attack=1 (single bank out of ${banks}, others idle)"
  sed -i 's/banks-to-attack=.*/banks-to-attack=1/g' config.ini
  python3 main.py

  echo "  banks-to-attack=${banks} (all ${banks} banks simultaneously)"
  sed -i "s/banks-to-attack=.*/banks-to-attack=${banks}/g" config.ini
  python3 main.py

  echo "  $cache ${banks}-bank runs complete."

  sed -i 's/num-banks=.*/num-banks=2/g' config.ini
  sed -i 's/banks-to-attack=.*/banks-to-attack=2/g' config.ini

  cd "$BASE"
}

for cache in ceaser_s scatter; do
  for banks in 8 16; do
    run_cache_bank_sweep "$cache" "$banks"
  done
done

echo "=== Generating plots for ceaser_s and scatter ==="
python3 -c "
from plot_diffs import plot_bit_diff_misses
from plot_bank_bit_misses import plot_bank_bit_misses
for cache in ('ceaser_s', 'scatter'):
    plot_bit_diff_misses(cache, base_dir='results')
    plot_bank_bit_misses(cache, base_dir='results')
"

echo "Ceaser-s and ScatterCache 8/16-bank runs and plots complete."
