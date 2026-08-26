#!/usr/bin/env bash
set -euo pipefail

DEST="$(pwd)/results"
BASE="$HOME/snuca_parallel"

SCENARIOS=(
    "2bank_single"
    "2bank_all"
    "4bank_single"
    "4bank_all"
)

DESIGNS=(
    "normal"
    "ceaser"
    "ceaser_s"
    "scatter"
    "mirage"
)

EXPECTED=1000

echo "Central results: $DEST"
echo

for scenario in "${SCENARIOS[@]}"; do

    SRC="$BASE/$scenario/Adv_Carch_Project-master/results"

    echo "===================================="
    echo "Merging $scenario"
    echo "===================================="

    for design in "${DESIGNS[@]}"; do

        mkdir -p "$DEST/$design"

        if [[ ! -d "$SRC/$design" ]]; then
            echo "ERROR: Missing directory:"
            echo "$SRC/$design"
            exit 1
        fi

        found=0

        for file in "$SRC/$design"/*.txt; do

            [[ -e "$file" ]] || continue
            found=1

            lines=$(wc -l < "$file")
            name=$(basename "$file")

            if [[ "$lines" -ne "$EXPECTED" ]]; then
                echo "ERROR: Partial file:"
                echo "$file"
                echo "$lines / $EXPECTED lines"
                exit 1
            fi

            cp -f "$file" "$DEST/$design/$name"

            echo "[COPIED] $design/$name"
        done

        if [[ "$found" -eq 0 ]]; then
            echo "ERROR: No txt files in:"
            echo "$SRC/$design"
            exit 1
        fi

    done
done

echo
echo "===================================="
echo "MERGE COMPLETE"
echo "===================================="

echo
echo "Checking every result file..."

BAD=0

while IFS= read -r -d '' file; do

    lines=$(wc -l < "$file")

    if [[ "$lines" -ne "$EXPECTED" ]]; then
        echo "[BAD] $lines lines : $file"
        BAD=$((BAD + 1))
    fi

done < <(find "$DEST" -type f -name "outfile*.txt" -print0)

TOTAL=$(find "$DEST" -type f -name "outfile*.txt" | wc -l)

echo
echo "Total result files : $TOTAL"
echo "Bad/partial files  : $BAD"

if [[ "$BAD" -ne 0 ]]; then
    echo "ERROR: Some files are incomplete."
    exit 1
fi

echo
echo "Files per design:"

for design in "${DESIGNS[@]}"; do
    count=$(find "$DEST/$design" -maxdepth 1 -type f -name "outfile*.txt" | wc -l)
    echo "$design : $count"
done

if [[ "$TOTAL" -ne 50 ]]; then
    echo
    echo "WARNING: Expected 50 result files, found $TOTAL."
    echo "Check filenames before plotting."
    exit 1
fi

echo
echo "All 50 expected result files are present and complete."
echo
echo "Running plot_diffs.py..."

python3 plot_diffs.py

echo
echo "DONE."
