#!/usr/bin/env bash
# FossilGrid end-to-end demo: runs every command against the shipped example data.
# Non-interactive, no network, exits non-zero if any step fails.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
FG=("$PYTHON" fossilgrid.py)
STEP=0

banner() {
  STEP=$((STEP + 1))
  printf '\n================================================================\n'
  printf '%s. %s\n' "$STEP" "$1"
  printf '================================================================\n'
}

banner "version and command map"
"${FG[@]}" --version
"${FG[@]}" --help | sed -n '1,20p'

banner "stratigraphic column from examples/layers.csv (top to bottom)"
"${FG[@]}" strata plot examples/layers.csv --width 40

banner "the same section as JSON -- byte-identical output"
"${FG[@]}" strata plot examples/layers.json --width 40 | tail -n +2 > /tmp/fossilgrid-json.txt
"${FG[@]}" strata plot examples/layers.csv --width 40 | tail -n +2 > /tmp/fossilgrid-csv.txt
if diff -q /tmp/fossilgrid-json.txt /tmp/fossilgrid-csv.txt > /dev/null; then
  echo "identical: layers.json and layers.csv render the same column"
else
  echo "MISMATCH between layers.json and layers.csv" >&2
  exit 1
fi

banner "wider scale, wider labels, and --out"
"${FG[@]}" strata plot examples/layers.csv --scale 2 --width 40 --out /tmp/fossilgrid-column.txt
echo "wrote $(wc -l < /tmp/fossilgrid-column.txt) lines to /tmp/fossilgrid-column.txt (stdout stayed empty)"
sed -n '7,13p' /tmp/fossilgrid-column.txt

banner "narrow terminal: the plot column compresses and says so on stderr"
COLUMNS=40 "${FG[@]}" strata plot examples/layers.csv | head -12

banner "dichotomous key from examples/taxa.csv"
"${FG[@]}" key generate examples/taxa.csv --title "Ordovician brachiopods"

banner "the same key as a nested markdown list"
"${FG[@]}" key generate examples/taxa.csv --format markdown | head -8

banner "site grid map from examples/finds.csv"
"${FG[@]}" grid plot examples/finds.csv

banner "wider cells with a ruler label every fifth column"
"${FG[@]}" grid plot examples/finds.csv --cell-width 3 | head -8

banner "coordinate work: grid to lat/long, lat/long to grid, and distance"
"${FG[@]}" grid convert --file examples/finds.json --to-latlon 3 4
"${FG[@]}" grid convert --origin-lat 52.0 --origin-lon 4.0 --cell-size 100 --to-grid 52.0 4.45
"${FG[@]}" grid convert --origin-lat 52.0 --origin-lon 4.0 --distance 0 0 3 4
"${FG[@]}" grid convert --origin-lat 52.0 --origin-lon 4.0 --distance 0 0 3 4 --units km

banner "machine-readable output (one JSON object per command)"
"${FG[@]}" strata plot examples/layers.csv --json | sed -n '1,12p'
"${FG[@]}" grid plot examples/finds.csv --json | sed -n '1,14p'

printf '\n================================================================\n'
printf 'demo complete: %s steps, every command exited 0\n' "$STEP"
printf 'exit codes: 0 success, 1 data error, 2 usage error\n'
printf '================================================================\n'
