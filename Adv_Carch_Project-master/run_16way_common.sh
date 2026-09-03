#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: run_16way_common.sh --mode multibank|hybrid2|region4 --design normal|ceaser|ceaser_s|scatter|mirage [options]

Options:
  --banks N             Physical banks: 1, 2, or 4
  --target-banks LIST   Comma-separated target banks, e.g. 0 or 0,1,2,3
  --trials N            Trial count, default 100
  --seed N              Deterministic base seed, default 20260904
  --output-dir DIR      Job-specific result directory
  --skip-existing       Skip when both bit output files already exist
EOF
}

MODE=""
DESIGN=""
BANKS="1"
TARGET_BANKS="0"
TRIALS="100"
SEED="20260904"
OUTPUT_DIR=""
SKIP_EXISTING=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --design) DESIGN="$2"; shift 2 ;;
    --banks) BANKS="$2"; shift 2 ;;
    --target-banks) TARGET_BANKS="$2"; shift 2 ;;
    --trials) TRIALS="$2"; shift 2 ;;
    --seed) SEED="$2"; shift 2 ;;
    --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    --skip-existing) SKIP_EXISTING="--skip-existing"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 2 ;;
  esac
done

[[ -n "$MODE" && -n "$DESIGN" ]] || { usage; exit 2; }

case "$DESIGN" in
  normal) DIR="Normal_cache_occupancy"; PARTITIONS=1; WAYS=16; EXTRA_ARGS=() ;;
  ceaser) DIR="Ceaser_cache_occupancy"; PARTITIONS=1; WAYS=16; EXTRA_ARGS=() ;;
  ceaser_s) DIR="Ceaser-s_cache_occupancy"; PARTITIONS=2; WAYS=16; EXTRA_ARGS=() ;;
  scatter) DIR="ScatterCache_cache_occupancy"; PARTITIONS=16; WAYS=16; EXTRA_ARGS=() ;;
  mirage) DIR="Mirage_cache_occupancy"; PARTITIONS=2; WAYS=8; EXTRA_ARGS=(--num-additional-tags 6) ;;
  *) echo "Unknown design: $DESIGN"; exit 2 ;;
esac

case "$MODE" in
  multibank) REGIONS=1; ATTACK_REGIONS="0"; CASE_DIR="multibank" ;;
  hybrid2) REGIONS=2; ATTACK_REGIONS="1"; CASE_DIR="hybrid_2region_75_25" ;;
  region4) REGIONS=4; ATTACK_REGIONS="0,1,2,3"; CASE_DIR="hybrid_4region" ;;
  *) echo "Unknown mode: $MODE"; exit 2 ;;
esac

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$ROOT/results/$CASE_DIR/$DESIGN"
fi
mkdir -p "$OUTPUT_DIR" "$ROOT/results/run_logs"

target_slug="${TARGET_BANKS//,/-}"
region_slug="${ATTACK_REGIONS//,/-}"
log="$ROOT/results/run_logs/${DESIGN}_${MODE}_${BANKS}banks_targets_${target_slug}_regions_${region_slug}_trials${TRIALS}_seed${SEED}.log"

(
  cd "$ROOT/$DIR"
  python3 main.py \
    --architecture-mode "$MODE" \
    --num-regions "$REGIONS" \
    --attack-regions "$ATTACK_REGIONS" \
    --region-split-ratio 0.75 \
    --num-banks "$BANKS" \
    --target-banks "$TARGET_BANKS" \
    --banks-to-attack "$(awk -F, '{print NF}' <<< "$TARGET_BANKS")" \
    --trials "$TRIALS" \
    --seed "$SEED" \
    --output-dir "$OUTPUT_DIR" \
    --num-blocks-per-set "$WAYS" \
    --num-partitions "$PARTITIONS" \
    "${EXTRA_ARGS[@]}" \
    $SKIP_EXISTING
) 2>&1 | tee "$log"
