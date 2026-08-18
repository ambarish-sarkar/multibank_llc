#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CACHE_DIRS=(
  "Normal_cache_occupancy"
  "Ceaser_cache_occupancy"
  "Ceaser-s_cache_occupancy"
  "ScatterCache_cache_occupancy"
  "Mirage_cache_occupancy"
)

CACHE_KEYS=(
  "normal"
  "ceaser"
  "ceaser_s"
  "scatter"
  "mirage"
)

RATIO="0.5"
LOG_DIR="$ROOT/results/run_logs"
mkdir -p "$LOG_DIR"
for key in "${CACHE_KEYS[@]}"; do
  mkdir -p "$ROOT/results/$key"
done

if [[ ! -f "$ROOT/validate_snuca.py" ]]; then
  echo "ERROR: Put this script inside Adv_Carch_Project-master/."
  exit 1
fi

if [[ ! -f "$ROOT/plot_snuca_experiments.py" ]]; then
  echo "ERROR: plot_snuca_experiments.py is missing from $ROOT"
  exit 1
fi

CONFIG_BACKUP="$(mktemp -d)"
restore_configs() {
  for i in "${!CACHE_DIRS[@]}"; do
    dir="${CACHE_DIRS[$i]}"
    if [[ -f "$CONFIG_BACKUP/${dir}.ini" ]]; then
      cp "$CONFIG_BACKUP/${dir}.ini" "$ROOT/$dir/config.ini"
    fi
  done
  rm -rf "$CONFIG_BACKUP"
}
trap restore_configs EXIT

for dir in "${CACHE_DIRS[@]}"; do
  cp "$ROOT/$dir/config.ini" "$CONFIG_BACKUP/${dir}.ini"
done

set_config() {
  local config_path="$1"
  local num_banks="$2"
  local target_banks="$3"

  python3 - "$config_path" "$num_banks" "$target_banks" "$RATIO" <<'PY'
import configparser
import sys

path, num_banks, target_banks, ratio = sys.argv[1:]
banks = [x.strip() for x in target_banks.split(",") if x.strip()]

cfg = configparser.ConfigParser()
if not cfg.read(path) or not cfg.sections():
    raise SystemExit(f"Could not read config: {path}")

section = cfg[cfg.sections()[0]]
section["attack-mode"] = "simultaneous"
section["num-banks"] = str(num_banks)
section["target-banks"] = ",".join(banks)
section["banks-to-attack"] = str(len(banks))
section["region-split-ratio"] = ratio

with open(path, "w") as f:
    cfg.write(f, space_around_delimiters=False)
PY
}

run_cache() {
  local dir="$1"
  local key="$2"
  local num_banks="$3"
  local target_banks="$4"
  local case_label="$5"

  echo
  echo "============================================================"
  echo "Design         : $key"
  echo "Physical banks : $num_banks"
  echo "Target banks   : $target_banks"
  echo "Case           : $case_label"
  echo "============================================================"

  set_config "$ROOT/$dir/config.ini" "$num_banks" "$target_banks"

  local target_slug="${target_banks//,/-}"
  local log_file="$LOG_DIR/${key}_${num_banks}bank_${case_label}_targets_${target_slug}.log"

  (
    cd "$ROOT/$dir"
    python3 main.py
  ) 2>&1 | tee "$log_file"
}

run_scenario() {
  local num_banks="$1"
  local target_banks="$2"
  local case_label="$3"

  for i in "${!CACHE_DIRS[@]}"; do
    run_cache \
      "${CACHE_DIRS[$i]}" \
      "${CACHE_KEYS[$i]}" \
      "$num_banks" \
      "$target_banks" \
      "$case_label"
  done
}

echo "=== Running S-NUCA validation first ==="
python3 "$ROOT/validate_snuca.py"

# 1 physical bank: single-bank attack and all-bank attack are identical.
run_scenario 1 "0" "single_and_all"

# 2 physical banks.
run_scenario 2 "0"   "single_bank"
run_scenario 2 "0,1" "all_banks"

# 4 physical banks.
run_scenario 4 "0"       "single_bank"
run_scenario 4 "0,1,2,3" "all_banks"

echo
echo "=== Simulations complete. Generating plots ==="
python3 "$ROOT/plot_snuca_experiments.py" --base-dir "$ROOT/results" --ratio "$RATIO"

echo
echo "============================================================"
echo "All requested experiments are complete."
echo "Results : $ROOT/results/<design>/"
echo "Plots   : $ROOT/results/plots_snuca/"
echo "Logs    : $LOG_DIR"
echo "Original config.ini files have been restored."
echo "============================================================"
