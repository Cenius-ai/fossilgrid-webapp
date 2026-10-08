# Using FossilGrid

Four walkthroughs, one per command, with the real output of the shipped example data. Every example
runs offline; nothing here needs an install.

Contents:

1. [Plot a measured section](#1-plot-a-measured-section)
2. [Build a dichotomous key](#2-build-a-dichotomous-key)
3. [Map a site grid](#3-map-a-site-grid)
4. [Convert coordinates and measure distances](#4-convert-coordinates-and-measure-distances)
5. [Scripting recipes](#5-scripting-recipes)

---

## 1. Plot a measured section

A measured section is a list of beds written down from the top of the outcrop to the base. The first
data row is the **topmost** layer; the last row is the base of the section. Write it as CSV
(`name,thickness_m,lithology,notes` — the last two columns are optional):

```csv
name,thickness_m,lithology,notes
Cross-bedded fluvial sandstone,1.5,sandstone,Sharp erosive base; mudstone clasts along the scour
Dark grey fissile shale,2.2,shale,Ammonites concentrated in the upper 40 cm
Nodular bioclastic limestone,0.8,limestone,Crinoid ossicles; bored hardground at the top
```

then

```sh
python3 fossilgrid.py strata plot examples/layers.csv --width 40
```

```
Stratigraphic column -- examples/layers.csv

Total thickness: 10.10 m across 6 layers
Top boundary depth from base: 10.10 m
Base boundary depth from base: 0.00 m
Scale: 1 rows per metre   Label width: 40 chars   Plot width: 12 chars

  10.10 m +----------+ Cross-bedded fluvial sandstone (1.50 m)
          |ssssssssss| lithology: sandstone [s]
          |ssssssssss| depth from base: 10.10 - 8.60 m
          |ssssssssss| notes: Sharp erosive base; mudstone c...
   8.60 m +----------+ Dark grey fissile shale (2.20 m)
          |hhhhhhhhhh| lithology: shale [h]
          |hhhhhhhhhh| depth from base: 8.60 - 6.40 m
   ...
   0.00 m +----------+ base of section

Lithology legend:
  s  sandstone
  h  shale
  l  limestone
  m  mudstone
  t  siltstone
```

What to read from it:

* The left number on each `+--+` line is the **depth from the base of the section** of that boundary.
  The axis runs from `Total thickness` at the top down to `0.00 m` at the base, and each layer's
  label repeats its own range (`10.10 - 8.60 m`).
* Depths are computed from the row order — never typed in — so a section with a corrected thickness
  re-plots consistently.
* The plot column is filled with the lithology character for that bed (`s`, `h`, `l`, …), and the
  legend below lists every lithology used.

Useful variations:

```sh
# twice as tall, to see thin beds
python3 fossilgrid.py strata plot examples/layers.csv --scale 2 --width 40

# narrow terminal: the plot column compresses and explains itself on stderr
COLUMNS=40 python3 fossilgrid.py strata plot examples/layers.csv

# box drawing and lithology glyphs instead of ASCII
python3 fossilgrid.py strata plot examples/layers.csv --style unicode

# write the column to a file (stdout stays empty, so pipes stay clean)
python3 fossilgrid.py strata plot examples/layers.csv --out column.txt
```

An equivalent JSON file is accepted in two shapes and produces the same column:

```json
[ { "name": "Dark grey fissile shale", "thickness_m": 2.2, "lithology": "shale" } ]
```
```json
{ "layers": [ { "name": "Dark grey fissile shale", "thickness_m": 2.2, "lithology": "shale" } ] }
```

Empty input is not an error: a header-only file prints
`no layers to plot -- add name,thickness_m rows to <file>` and exits `0`. A bad thickness stops the
run and prints, for example:

```
layers.csv:3: thickness_m: expected a number greater than 0, got 'thick'
```

with nothing on stdout and exit code `1`.

---

## 2. Build a dichotomous key

A matrix has one row per taxon and one column per trait. A cell may hold several values separated
by `|`, which is how you record a specimen that could be scored either way:

```csv
taxon,lithology,valve_concavity,ribbing,hinge_line
Strophomena filosa,shale,concavoconvex,parvicostellate,straight
Sowerbyella sericea,shale,concavoconvex,simple,fine
```

```sh
python3 fossilgrid.py key generate examples/taxa.csv --title "Ordovician brachiopods"
```

```
Ordovician brachiopods
======================

Key for 6 taxa from examples/taxa.csv (4 traits, 5 couplets)

1. lithology = shale  ->  go to 2
1. lithology in {limestone, sandstone}  ->  go to 1a
  2. valve_concavity = concavoconvex  ->  go to 3
  2. valve_concavity in {planoconvex}  ->  Platystrophia biforata
    3. ribbing = parvicostellate  ->  Strophomena filosa
    3. ribbing in {simple}  ->  Sowerbyella sericea
  1a. lithology = limestone  ->  go to 4
  1a. lithology in {sandstone}  ->  Rafinesquina alternata
    4. valve_concavity = biconvex  ->  Hebertella occidentalis
    4. valve_concavity in {planoconvex}  ->  Dalmanella testudinaria
```

How the couplets are chosen (deterministically — the same matrix always gives the same key):

* multi-value traits are binarized **one-vs-rest**: values are ordered by descending frequency, ties
  alphabetically, so the first couplet on a trait is `trait = v1` against `trait in {v2, …, vn}` and
  the remainder is split again by the same rule;
* the splitting trait is the one with the best balance `min(countA, countB)` across the current
  taxa; equal balances go to the trait that appears earlier in the header, then to the earlier value
  in binarization order;
* every branch reaches either a taxon name or another couplet, so keying is a single tree walk;
* couplets are numbered in order; a couplet that continues the same trait is lettered (`1` → `1a`).

A markdown version keeps the same order and the same leaves:

```sh
python3 fossilgrid.py key generate examples/taxa.csv --format markdown
```

```
Binary key for 6 taxa from examples/taxa.csv (4 traits, 5 couplets).

- **1.** lithology = shale → go to 2
  - **2.** valve_concavity = concavoconvex → go to 3
    - **3.** ribbing = parvicostellate → Strophomena filosa
```

Two taxa scored identically cannot be separated by any trait. FossilGrid says so on stderr, still
prints both as an unresolved leaf and exits `0`, because the rest of the key is still usable:

```
fossilgrid: warning: twins.csv: 'Alpha', 'Beta' share identical trait vectors and cannot be separated
```

Duplicate taxon names, by contrast, are a data error (exit `1`):

```
taxa.csv:4: taxon: duplicate taxon name 'Alpha' (first seen in record 2)
```

---

## 3. Map a site grid

Finds are recorded as cell indices: `find_id,taxon,x,y,notes`. The south-west cell is `(0,0)`, `x`
increases **east** and `y` increases **north**, and the digits are cell indices rather than metres —
so `--cell-size` changes the physical size of the site, not the position of a find.

```sh
python3 fossilgrid.py grid plot examples/finds.csv
```

```
Site grid: 10 x 10 cells, cell size 1 m (distance units: m), origin SW cell (0,0), x east, y north

  0 1 2 3 4 5 6 7 8 9
9 . . . . . . . . . 1
8 . 1 . . . . . . . .
7 . . . . . . . . 1 .
6 . . . . . 1 . . . .
5 . . . . . . . . . .
4 . . . 2 1 . . . . .
3 . . . . . . . . . .
2 . . 2 . . . . 2 . .
1 . . . . . . 1 . . .
0 . . . . . . . . . .

Origin: the south-west cell is (0,0); x increases east, y increases north.
Cells: '.' = no finds, 1-9 = find count, '+' = 10 or more

Legend (taxa):
  Calymene blumenbachii    2
  Hebertella occidentalis  2
  Strophomena filosa       2
  Dalmanella testudinaria  1
  ...
Total: 12 finds in 9 occupied square(s).
```

* `.` is an empty square, `1`–`9` is the number of finds in it, `+` means ten or more — and any
  crowded square is listed by coordinate under `Squares with 10 or more finds`.
* The legend lists each taxon once with its total count.
* The ruler above the map is the `x` index; the numbers down the left edge are `y`.

Useful variations:

```sh
# a wider grid with larger cells: --cell-size changes the site, not the find positions
python3 fossilgrid.py grid plot examples/finds.csv --grid 12x12 --cell-size 2.5

# three characters per cell; the ruler labels every fifth column
python3 fossilgrid.py grid plot examples/finds.csv --cell-width 3
```

Marker bounds are checked against the **effective** grid, after `--grid` and any metadata in the
JSON file, and a bad marker names the find, the coordinate and the bounds:

```
finds.csv:4: x: marker 'FG-014' at x=11, y=4 is outside the effective grid bounds 0..9 x 0..9
```

A file with no finds is not an error: the full grid of dots is printed with
`no finds recorded -- add find_id,taxon,x,y rows to <file>` and exit code `0`.

---

## 4. Convert coordinates and measure distances

Conversions use a local equirectangular projection about an origin: `111320 m` per degree of
latitude, and `111320 · cos(origin_lat)` per degree of longitude. That is accurate to a few metres
across a site-sized area, which is the point — this is not a geodesy package.

The origin comes from `--origin-lat`/`--origin-lon` (give both), or from the `"origin"` block of the
JSON file you pass to `--file`:

```json
{ "origin": { "lat": 52.0, "lon": 4.0 }, "finds": [ ... ] }
```

**Grid square → lat/long**

```sh
python3 fossilgrid.py grid convert --file examples/finds.json --to-latlon 3 4
```
```
grid 3,4 -> 52.000036 N, 4.000044 E
origin 52.000000, 4.000000 (local equirectangular, cell size 1 m, units m)
```

**Lat/long → the square that contains it**

```sh
python3 fossilgrid.py grid convert --origin-lat 52.0 --origin-lon 4.0 --cell-size 100 --to-grid 52.0 4.45
```
```
lat/long 52.000000, 4.450000 -> grid 308,0 (rounded to the containing cell; outside the effective grid 0..9 x 0..9)
origin 52.000000, 4.000000 (local equirectangular, cell size 100 m, units m)
```

The second line always echoes the origin actually used, so any conversion can be reproduced later.

**Distance between two squares**

```sh
python3 fossilgrid.py grid convert --origin-lat 52.0 --origin-lon 4.0 --distance 0 0 3 4
python3 fossilgrid.py grid convert --origin-lat 52.0 --origin-lon 4.0 --distance 0 0 3 4 --units km
```
```
distance 0,0 -> 3,4 = 5 m (cell size 1 m)
distance 0,0 -> 3,4 = 0.005 km (cell size 1 m)
```

`--units m|km|ft` changes only how the distance is printed. Exactly one of `--to-latlon`,
`--to-grid` or `--distance` must be supplied; giving two, giving none, or supplying an origin
latitude without a longitude is a usage error (`2`):

```
fossilgrid: error: no origin: pass --origin-lat LAT --origin-lon LON, or --file with a JSON 'origin' block
```

---

## 5. Scripting recipes

FossilGrid keeps stdout for the artifact and stderr for everything else, which makes it safe in
pipelines.

```sh
# keep the map, keep the complaint, decide on the exit code
python3 fossilgrid.py grid plot examples/finds.csv > /tmp/map.txt 2> /tmp/problems.txt \
  || echo "data error, see /tmp/problems.txt"

# write a report straight to a file (stdout stays empty)
python3 fossilgrid.py key generate examples/taxa.csv --out /tmp/key.txt

# machine-readable output for another tool (one JSON object per command)
python3 fossilgrid.py strata plot examples/layers.csv --json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['total_thickness_m'], 'm in', len(d['layers']), 'layers')"

# the same for the site map: cells and their counts
python3 fossilgrid.py grid plot examples/finds.csv --json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(c['count'] for c in d['cells']), 'finds')"

# check before plotting: does my grid actually contain every find?
python3 fossilgrid.py grid plot examples/finds.csv --grid 8x8 > /dev/null \
  || echo "some marker falls outside 8x8"

# a quick check in a shell script, with the warnings counted
if python3 fossilgrid.py key generate examples/taxa.csv --out /tmp/key.txt 2> /tmp/key.err; then
  echo "key written; $(grep -c warning /tmp/key.err) unresolved-taxon warning(s)"
else
  cat /tmp/key.err >&2
fi
```

Exit codes, once more: `0` success (including empty input and unresolved-taxon warnings), `1` data
error, `2` usage error — see the tables in [README.md](README.md#exit-codes).
