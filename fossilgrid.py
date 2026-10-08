#!/usr/bin/env python3
"""FossilGrid -- field-notebook plotting for stratigraphy, taxonomy and site grids.

Four commands, all plain text, standard library only:

    fossilgrid strata plot FILE      ASCII stratigraphic column with depths
    fossilgrid key generate FILE     binary dichotomous identification key
    fossilgrid grid plot FILE        ASCII site grid map of fossil finds
    fossilgrid grid convert ...      grid square <-> lat/long, and distances

Design source of truth (calm-precise / terminal dark / mono):
  surface      terminal dark, no chrome, monospace, compact density
  accent       #b4603c  (oklch(0.58 0.12 43)) -- reserved for primary status lines
  structure    aligned columns and box-drawing separators (--style unicode)
  rule         never signal with colour alone: every state is also spelled out in words
  type ramp    one column grid (labels, plot, depths), one spacing scale
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

PROG = "fossilgrid"
VERSION = "0.1.0"

EXIT_OK = 0
EXIT_DATA = 1
EXIT_USAGE = 2

DEFAULT_TERMINAL_WIDTH = 80
PLOT_COLUMN_WIDTH = 12
DEPTH_COLUMN_WIDTH = 9
MIN_PLOT_WIDTH = 4
MIN_LABEL_WIDTH = 8
DEFAULT_LABEL_WIDTH = 24
DEFAULT_SCALE = 1.0
MIN_SCALE = 0.1

DEFAULT_GRID_WIDTH = 10
DEFAULT_GRID_HEIGHT = 10
DEFAULT_CELL_SIZE_M = 1.0
DEFAULT_CELL_WIDTH = 1
CROWDED_CELL = 10
M_PER_DEGREE_LAT = 111320.0

UNITS = ("m", "km", "ft")
METERS_PER_UNIT = {"m": 1.0, "km": 1000.0, "ft": 0.3048}

# Lithology keyword -> (ASCII code, Unicode glyph). Unknown lithologies fall back
# to the ASCII '?' / Unicode '·' pair so the column never renders an empty cell.
LITHOLOGY_GLYPHS: Dict[str, Tuple[str, str]] = {
    "sandstone": ("s", "\u2592"),
    "shale": ("h", "\u2261"),
    "limestone": ("l", "\u25ac"),
    "mudstone": ("m", "\u2591"),
    "siltstone": ("t", "\u25aa"),
    "conglomerate": ("c", "\u25cb"),
    "breccia": ("b", "\u25cc"),
    "coal": ("k", "\u2593"),
    "marl": ("r", "\u00b7"),
    "chalk": ("C", "\u25ab"),
    "dolomite": ("d", "\u25c6"),
    "ironstone": ("i", "\u25a3"),
    "tuff": ("u", "\u25b2"),
}
UNKNOWN_GLYPH = ("?", "\u00b7")

ROOT_EPILOG = """\
commands:
  strata plot FILE      render an ASCII stratigraphic column from a layer table
  key generate FILE     build a binary dichotomous key from a taxon x trait matrix
  grid plot FILE        map fossil finds onto a site grid
  grid convert ...      convert grid squares to lat/long and measure distances

exit codes:
  0  success, including empty input and unresolved-taxon warnings
  1  data error: unreadable or malformed file, missing column, non-numeric or
     non-positive thickness_m, duplicate taxon name, marker outside the effective
     grid, unusable or missing origin in a file
  2  usage error: unknown command or flag, missing argument, more than one
     conversion target, unsupported file extension

examples:
  fossilgrid strata plot examples/layers.csv --scale 2
  fossilgrid key generate examples/taxa.csv --title "Ordovician fauna"
  fossilgrid grid plot examples/finds.csv --grid 10x10 --cell-size 1
  fossilgrid grid convert --origin-lat 52.0 --origin-lon 4.0 --to-latlon 0 0
"""

STRATA_EPILOG = """\
usage:
  fossilgrid strata plot FILE [--scale S] [--width W] [--style STYLE] [--out FILE]

plot flags and defaults:
  --scale S     vertical rows per metre (float, default 1.0, minimum 0.1)
  --width W     label column width in characters (int, default 24, minimum 8)
  --style STYLE ascii or unicode box drawing (default ascii)
  --out FILE    write the rendered column to FILE instead of stdout
  --json        write the column as a single JSON object on stdout
"""

KEY_EPILOG = """\
usage:
  fossilgrid key generate FILE [--title TEXT] [--format FORMAT] [--out FILE]

generate flags and defaults:
  --title TEXT     first line of the key (no default)
  --format FORMAT  text or markdown (default text)
  --out FILE       write the key to FILE instead of stdout
  --json           write the key as a single JSON object on stdout
"""

GRID_EPILOG = """\
usage:
  fossilgrid grid plot FILE [--grid WxH] [--cell-size S] [--units U] [--cell-width N] [--out FILE]
  fossilgrid grid convert (--origin-lat LAT --origin-lon LON | --file FILE) \\
      (--to-latlon X Y | --to-grid LAT LON | --distance X1 Y1 X2 Y2) [--units U]

plot flags and defaults:
  --grid WxH        grid width x height in cells (default 10x10)
  --cell-size S     cell size in metres (float, default 1)
  --units U         m, km or ft (default m)
  --cell-width N    characters per cell, 1 or more (int, default 1)
  --out FILE        write the map to FILE instead of stdout
  --json            write the map as a single JSON object on stdout

convert flags and defaults:
  --origin-lat LAT  origin latitude in decimal degrees (required with --origin-lon)
  --origin-lon LON  origin longitude in decimal degrees
  --file FILE       .json finds file whose "origin" block supplies lat/lon
  --to-latlon X Y   grid square X Y -> lat/long
  --to-grid LAT LON lat/long -> containing grid square
  --distance X1 Y1 X2 Y2   planar distance between two grid squares
  --grid WxH        effective grid used for bounds notes (default 10x10)
  --cell-size S     cell size in metres (float, default 1)
  --units U         unit for printed distances (default m)
  --json            write the conversion as a single JSON object on stdout
"""


class DataError(Exception):
    """A problem with the user's data. Rendered as '<file>:<row>: <field>: <problem>'."""

    def __init__(self, path: str, record: Any, field_name: str, problem: str) -> None:
        super().__init__(f"{path}:{record}: {field_name}: {problem}")
        self.path = path
        self.record = record
        self.field_name = field_name
        self.problem = problem


class UsageError(Exception):
    """A problem with the command line. The caller prints it and exits 2."""


# ---------------------------------------------------------------- formatting

def format_measure(value: float) -> str:
    """Two decimals, the unit used for thicknesses and depths."""
    return f"{value:.2f}"


def format_number(value: float) -> str:
    """Compact number: 1.0 -> '1', 0.005 -> '0.005', 30841.5 -> '30841.5'."""
    text = f"{value:.6g}"
    if text in ("-0", "-0.0"):
        return "0"
    return text


def format_latlon(value: float) -> str:
    return f"{value:.6f}"


def clip_to_width(text: str, width: int, ellipsis: str) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(ellipsis):
        return text[:width]
    return text[: width - len(ellipsis)] + ellipsis


# ---------------------------------------------------------------- table input

@dataclass
class Table:
    """One normalized row table: CSV and JSON both arrive here."""

    path: str
    header: List[str]
    rows: List[Dict[str, Any]]
    meta: Dict[str, Any]


def file_extension(path: str) -> str:
    """Lower-case extension of the last path segment, '.csv' style, or ''."""
    name = os.path.basename(path)
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def detect_format(path: str) -> str:
    extension = file_extension(path)
    if extension == ".csv":
        return "csv"
    if extension == ".json":
        return "json"
    shown = extension if extension else "(no extension)"
    raise UsageError(
        f"{path}: unsupported input format '{shown}': only .csv and .json inputs are accepted"
    )


def _json_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, list):
        return [_json_cell(item) for item in value]
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def read_table(path: str, collection: str) -> Table:
    """Read a CSV or JSON file into one row model.

    JSON is accepted as an array of row objects, or as an object holding the
    named collection ('layers', 'taxa', 'finds') plus optional metadata keys.
    """
    if detect_format(path) == "csv":
        return _read_csv(path)
    return _read_json(path, collection)


def _read_csv(path: str) -> Table:
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = [cell.strip() for cell in next(reader, [])]
            rows: List[Dict[str, Any]] = []
            for line_number, raw in enumerate(reader, start=2):
                if not raw or all(cell.strip() == "" for cell in raw):
                    continue
                row: Dict[str, Any] = {"__record__": line_number}
                for index, name in enumerate(header):
                    row[name] = raw[index].strip() if index < len(raw) else ""
                rows.append(row)
    except FileNotFoundError:
        raise DataError(path, "-", "file", "cannot be read: no such file")
    except IsADirectoryError:
        raise DataError(path, "-", "file", "cannot be read: that path is a directory")
    except PermissionError:
        raise DataError(path, "-", "file", "cannot be read: permission denied")
    except UnicodeDecodeError:
        raise DataError(path, "-", "content", "is not valid UTF-8 text")
    except OSError as error:
        raise DataError(path, "-", "file", f"cannot be read: {error.strerror or error}")
    return Table(path, header, rows, {})


def _read_json(path: str, collection: str) -> Table:
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise DataError(path, "-", "file", "cannot be read: no such file")
    except IsADirectoryError:
        raise DataError(path, "-", "file", "cannot be read: that path is a directory")
    except PermissionError:
        raise DataError(path, "-", "file", "cannot be read: permission denied")
    except UnicodeDecodeError:
        raise DataError(path, "-", "content", "is not valid UTF-8 text")
    except OSError as error:
        raise DataError(path, "-", "file", f"cannot be read: {error.strerror or error}")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise DataError(
            path,
            "-",
            "content",
            f"is not valid JSON (line {error.lineno}, column {error.colno}: {error.msg})",
        )

    meta: Dict[str, Any] = {}
    if isinstance(payload, list):
        raw_rows: Sequence[Any] = payload
    elif isinstance(payload, dict):
        if collection not in payload:
            raise DataError(
                path,
                "-",
                collection,
                "file has no '{}' collection (expected a JSON array or an object with a "
                "'{}' key)".format(collection, collection),
            )
        raw_rows = payload[collection]
        meta = {key: value for key, value in payload.items() if key != collection}
        if not isinstance(raw_rows, list):
            raise DataError(path, "-", collection, "'{}' must be a JSON array".format(collection))
    else:
        raise DataError(
            path, "-", "content", "must be a JSON array of rows or an object with a "
            "'{}' collection".format(collection)
        )

    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_rows, start=1):
        if not isinstance(item, dict):
            raise DataError(path, index, "record", "must be a JSON object with named fields")
        row: Dict[str, Any] = {"__record__": index}
        for key, value in item.items():
            row[key] = _json_cell(value)
        rows.append(row)
    header = [key for key in rows[0] if key != "__record__"] if rows else []
    return Table(path, header, rows, meta)


# ------------------------------------------------------------ field validators

def require_columns(table: Table, names: Sequence[str]) -> None:
    for name in names:
        if name not in table.header:
            raise DataError(table.path, 1, name, "required column is missing from the header")


def require_word(row: Dict[str, Any], name: str, table: Table) -> str:
    text = str(row.get(name, "")).strip()
    if not text:
        raise DataError(table.path, row.get("__record__", "?"), name, "must not be empty")
    return text


def require_number(row: Dict[str, Any], name: str, table: Table) -> float:
    text = str(row.get(name, "")).strip()
    record = row.get("__record__", "?")
    if text == "":
        raise DataError(table.path, record, name, "is required but missing")
    try:
        return float(text)
    except ValueError:
        raise DataError(
            table.path, record, name, f"expected a number greater than 0, got '{text}'"
        )


def require_positive_number(row: Dict[str, Any], name: str, table: Table) -> float:
    text = str(row.get(name, "")).strip()
    value = require_number(row, name, table)
    if not math.isfinite(value) or value <= 0:
        raise DataError(
            table.path,
            row.get("__record__", "?"),
            name,
            f"expected a number greater than 0, got '{text}'",
        )
    return value


def require_index(row: Dict[str, Any], name: str, table: Table) -> int:
    text = str(row.get(name, "")).strip()
    record = row.get("__record__", "?")
    if text == "":
        raise DataError(table.path, record, name, "is required but missing")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        value = float(text)
    except ValueError:
        raise DataError(table.path, record, name, f"expected a whole number, got '{text}'")
    if not math.isfinite(value) or not value.is_integer():
        raise DataError(table.path, record, name, f"expected a whole number, got '{text}'")
    return int(value)


# --------------------------------------------------------- stratigraphic column

@dataclass(frozen=True)
class Stratum:
    order_index: int
    name: str
    thickness_m: float
    lithology: str
    notes: str
    depth_from_top_m: float
    depth_from_base_m: float


@dataclass
class Column:
    source_path: str
    layers: List[Stratum]
    total_thickness_m: float


def parse_column(table: Table) -> Column:
    if not table.rows:
        return Column(table.path, [], 0.0)
    require_columns(table, ("name", "thickness_m"))
    raw: List[Tuple[str, float, str, str]] = []
    total = 0.0
    for row in table.rows:
        name = require_word(row, "name", table)
        thickness = require_positive_number(row, "thickness_m", table)
        lithology = str(row.get("lithology", "")).strip()
        notes = str(row.get("notes", "")).strip()
        raw.append((name, thickness, lithology, notes))
        total += thickness
    layers: List[Stratum] = []
    running = 0.0
    for index, (name, thickness, lithology, notes) in enumerate(raw, start=1):
        running += thickness
        layers.append(
            Stratum(
                order_index=index,
                name=name,
                thickness_m=thickness,
                lithology=lithology,
                notes=notes,
                depth_from_top_m=round(running, 6),
                depth_from_base_m=round(total - running, 6),
            )
        )
    return Column(table.path, layers, round(total, 6))


def layer_top_from_base(layer: Stratum) -> float:
    """Height above the base of the section for the layer's top boundary."""
    return layer.depth_from_base_m + layer.thickness_m


def lithology_glyphs(lithology: str, style: str) -> Tuple[str, str]:
    key = lithology.strip().lower()
    pair = LITHOLOGY_GLYPHS.get(key)
    if pair is None:
        pair = LITHOLOGY_GLYPHS.get(key.split()[0]) if key else None
    if pair is None:
        pair = UNKNOWN_GLYPH
    return pair if style == "ascii" else (pair[1], pair[0])


def lithology_code(lithology: str) -> str:
    return lithology_glyphs(lithology, "ascii")[0]


def terminal_width() -> int:
    """$COLUMNS when set (pipe/recorder friendly), else the real terminal size."""
    override = os.environ.get("COLUMNS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    try:
        return shutil.get_terminal_size(fallback=(DEFAULT_TERMINAL_WIDTH, 24)).columns
    except OSError:
        return DEFAULT_TERMINAL_WIDTH


def column_geometry(label_width: int, width: int) -> Tuple[int, int, int]:
    """Return (plot_width, effective_label_width, usable_width) for one terminal."""
    usable = max(width, MIN_LABEL_WIDTH + MIN_PLOT_WIDTH + DEPTH_COLUMN_WIDTH + 2)
    budget = usable - DEPTH_COLUMN_WIDTH - 2
    plot_width = min(PLOT_COLUMN_WIDTH, max(MIN_PLOT_WIDTH, budget - label_width))
    effective_label = min(label_width, max(MIN_LABEL_WIDTH, budget - plot_width))
    effective_label = max(1, min(effective_label, budget - plot_width))
    return plot_width, effective_label, usable


def fit_lines(lines: Sequence[str], width: int) -> Tuple[List[str], bool]:
    """Guarantee every rendered line fits the terminal width."""
    if width <= 0:
        return list(lines), False
    fitted: List[str] = []
    wrapped = False
    for line in lines:
        if len(line) <= width:
            fitted.append(line)
            continue
        wrapped = True
        pieces = textwrap.wrap(
            line,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        fitted.extend(pieces if pieces else [line])
    return fitted, wrapped


def compression_note(
    width: int, plot_width: int, requested_label: int, effective_label: int, wrapped: bool
) -> Optional[str]:
    reasons: List[str] = []
    if plot_width < PLOT_COLUMN_WIDTH:
        reasons.append(
            f"the plot column was compressed from {PLOT_COLUMN_WIDTH} to {plot_width} characters"
        )
    if effective_label < requested_label:
        reasons.append(
            f"labels were clipped from {requested_label} to {effective_label} characters"
        )
    if wrapped:
        reasons.append("over-long text lines were wrapped")
    if not reasons:
        return None
    return f"{PROG}: note: terminal width {width} -- " + " and ".join(reasons)


def _top_rule(plot_width: int, style: str, bottom: bool = False) -> str:
    inner = "-" * max(plot_width - 2, 0)
    if style == "ascii":
        return ("+" + inner + "+") if not bottom else ("+" + inner + "+")
    return ("\u2514" + "\u2500" * max(plot_width - 2, 0) + "\u2518") if bottom else (
        "\u250c" + "\u2500" * max(plot_width - 2, 0) + "\u2510"
    )


def _side_rule(plot_width: int, style: str, glyph: str) -> str:
    edge = "|" if style == "ascii" else "\u2502"
    return edge + glyph * max(plot_width - 2, 0) + edge


def _layer_labels(layer: Stratum, width: int, ellipsis: str) -> List[str]:
    labels = [clip_to_width(f"{layer.name} ({format_measure(layer.thickness_m)} m)", width, ellipsis)]
    if layer.lithology:
        labels.append(
            clip_to_width(
                f"lithology: {layer.lithology} [{lithology_code(layer.lithology)}]", width, ellipsis
            )
        )
    labels.append(
        clip_to_width(
            "depth from base: {} - {} m".format(
                format_measure(layer_top_from_base(layer)),
                format_measure(layer.depth_from_base_m),
            ),
            width,
            ellipsis,
        )
    )
    if layer.notes:
        labels.append(clip_to_width(f"notes: {layer.notes}", width, ellipsis))
    return labels


def _layer_block(
    layer: Stratum, plot_width: int, label_width: int, scale: float, style: str, ellipsis: str
) -> List[str]:
    rows = max(1, int(math.floor(layer.thickness_m * scale + 0.5)))
    glyph = lithology_glyphs(layer.lithology, style)[0]
    labels = _layer_labels(layer, label_width, ellipsis)
    height = max(rows, len(labels))
    block: List[str] = []
    for row in range(height):
        if row == 0:
            depth = f"{format_measure(layer_top_from_base(layer))} m".rjust(DEPTH_COLUMN_WIDTH)
            cell = _top_rule(plot_width, style)
        else:
            depth = " " * DEPTH_COLUMN_WIDTH
            cell = _side_rule(plot_width, style, glyph)
        label = labels[row] if row < len(labels) else ""
        block.append(f"{depth} {cell} {label}".rstrip())
    return block


def _legend_lines(column: Column, style: str, ellipsis: str, width: int) -> List[str]:
    seen: List[str] = []
    for layer in column.layers:
        if layer.lithology and layer.lithology not in seen:
            seen.append(layer.lithology)
    lines = []
    for lithology in seen:
        glyph = lithology_glyphs(lithology, style)[0]
        lines.append(clip_to_width(f"  {glyph}  {lithology}", width, ellipsis))
    return lines


def render_column(
    column: Column, label_width: int, scale: float, width: int, style: str
) -> Tuple[str, Optional[str]]:
    """Render the ASCII/Unicode column. Returns (text, stderr note or None)."""
    plot_width, effective_label, usable = column_geometry(label_width, width)
    ellipsis = "..." if style == "ascii" else "\u2026"
    layer_word = "layer" if len(column.layers) == 1 else "layers"

    if not column.layers:
        lines = [f"no layers to plot -- add name,thickness_m rows to {column.source_path}"]
        fitted, wrapped = fit_lines(lines, usable)
        return "\n".join(fitted) + "\n", compression_note(
            width, plot_width, label_width, effective_label, wrapped
        )

    lines = [
        f"Stratigraphic column -- {column.source_path}",
        "",
        f"Total thickness: {format_measure(column.total_thickness_m)} m across "
        f"{len(column.layers)} {layer_word}",
        f"Top boundary depth from base: {format_measure(column.total_thickness_m)} m",
        "Base boundary depth from base: 0.00 m",
        f"Scale: {format_number(scale)} rows per metre   Label width: {effective_label} chars"
        f"   Plot width: {plot_width} chars",
        "",
    ]
    for layer in column.layers:
        lines.extend(
            _layer_block(layer, plot_width, effective_label, scale, style, ellipsis)
        )
    base_depth = f"{format_measure(0.0)} m".rjust(DEPTH_COLUMN_WIDTH)
    base_label = clip_to_width("base of section", effective_label, ellipsis)
    lines.append(f"{base_depth} {_top_rule(plot_width, style, bottom=True)} {base_label}".rstrip())

    legend = _legend_lines(column, style, ellipsis, usable)
    if legend:
        lines.extend(["", "Lithology legend:"] + legend)

    fitted, wrapped = fit_lines(lines, usable)
    note = compression_note(width, plot_width, label_width, effective_label, wrapped)
    return "\n".join(fitted) + "\n", note


def column_payload(
    column: Column, label_width: int, scale: float, width: int, text: str
) -> Dict[str, Any]:
    plot_width, effective_label, _ = column_geometry(label_width, width)
    return {
        "command": "strata plot",
        "source": column.source_path,
        "total_thickness_m": column.total_thickness_m,
        "scale": scale,
        "label_width": effective_label,
        "plot_width": plot_width,
        "layers": [
            {
                "order_index": layer.order_index,
                "name": layer.name,
                "thickness_m": layer.thickness_m,
                "lithology": layer.lithology,
                "notes": layer.notes,
                "depth_from_top_m": layer.depth_from_top_m,
                "depth_from_base_m": layer.depth_from_base_m,
            }
            for layer in column.layers
        ],
        "text": text,
    }


# ------------------------------------------------------------ dichotomy matrix

@dataclass(frozen=True)
class Taxon:
    name: str
    values: Dict[str, Tuple[str, ...]]


@dataclass
class Matrix:
    source_path: str
    traits: List[str]
    taxa: List[Taxon]


def split_cell_values(cell: Any) -> Tuple[str, ...]:
    if isinstance(cell, list):
        raw = [str(item) for item in cell]
    else:
        raw = str(cell).split("|")
    values = [part.strip() for part in raw if part.strip()]
    return tuple(dict.fromkeys(values))


def parse_matrix(table: Table) -> Matrix:
    if not table.rows:
        return Matrix(table.path, [], [])
    taxon_column = None
    for name in table.header:
        if name.strip().lower() == "taxon":
            taxon_column = name
            break
    if taxon_column is None:
        raise DataError(table.path, 1, "taxon", "required column is missing from the header")
    traits = [name for name in table.header if name != taxon_column and name.strip()]

    seen: Dict[str, Any] = {}
    taxa: List[Taxon] = []
    for row in table.rows:
        name = require_word(row, taxon_column, table)
        record = row.get("__record__", "?")
        if name in seen:
            raise DataError(
                table.path,
                record,
                "taxon",
                f"duplicate taxon name '{name}' (first seen in record {seen[name]})",
            )
        seen[name] = record
        values = {trait: split_cell_values(row.get(trait, "")) for trait in traits}
        taxa.append(Taxon(name, values))
    return Matrix(table.path, traits, taxa)


@dataclass
class Leaf:
    names: List[str]
    unresolved: bool


@dataclass
class Couplet:
    number: str
    depth: int
    trait: str
    balance: int
    branch_a_text: str
    branch_b_text: str
    branch_a: Any
    branch_b: Any


def value_order(subset: Sequence[Taxon], trait: str) -> List[str]:
    counts: Dict[str, int] = {}
    for taxon in subset:
        for value in taxon.values.get(trait, ()):
            counts[value] = counts.get(value, 0) + 1
    return sorted(counts, key=lambda value: (-counts[value], value))


def trait_split(subset: Sequence[Taxon], trait: str) -> Optional[Tuple[int, str, List[Taxon], List[Taxon]]]:
    best: Optional[Tuple[int, str, List[Taxon], List[Taxon]]] = None
    for value in value_order(subset, trait):
        positive = [taxon for taxon in subset if value in taxon.values.get(trait, ())]
        negative = [taxon for taxon in subset if value not in taxon.values.get(trait, ())]
        if not positive or not negative:
            continue
        balance = min(len(positive), len(negative))
        if best is None or balance > best[0]:
            best = (balance, value, positive, negative)
    return best


def best_split(subset: Sequence[Taxon], traits: Sequence[str]) -> Optional[Tuple[str, str, List[Taxon], List[Taxon]]]:
    """Most balanced one-vs-rest split; ties go to the earlier header column, then value order."""
    best: Optional[Tuple[str, str, List[Taxon], List[Taxon]]] = None
    best_balance = -1
    for trait in traits:
        candidate = trait_split(subset, trait)
        if candidate is None:
            continue
        balance, value, positive, negative = candidate
        if balance > best_balance:
            best_balance = balance
            best = (trait, value, positive, negative)
    return best


class KeyBuilder:
    """Deterministic binary key: header-order tie-breaks, one-vs-rest binarization."""

    def __init__(self, matrix: Matrix) -> None:
        self.matrix = matrix
        self.counter = 0
        self.unresolved: List[List[str]] = []
        self.couplet_count = 0

    def build(self) -> Any:
        return self._solve(list(self.matrix.taxa), None, None, 0)

    def _assign_number(self, parent_number: Optional[str], parent_trait: Optional[str], trait: str) -> str:
        if parent_number is not None and parent_trait == trait:
            base = parent_number.rstrip("abcdefghijklmnopqrstuvwxyz")
            letters = parent_number[len(base):]
            return base + chr(ord("a") + len(letters))
        self.counter += 1
        return str(self.counter)

    def _solve(
        self, subset: List[Taxon], parent_number: Optional[str], parent_trait: Optional[str], depth: int
    ) -> Any:
        if len(subset) == 1:
            return Leaf([subset[0].name], False)
        choice = best_split(subset, self.matrix.traits)
        if choice is None:
            names = sorted(taxon.name for taxon in subset)
            self.unresolved.append(names)
            return Leaf(names, True)

        trait, value, positive, negative = choice
        number = self._assign_number(parent_number, parent_trait, trait)
        node = Couplet(
            number=number,
            depth=depth,
            trait=trait,
            balance=min(len(positive), len(negative)),
            branch_a_text=f"{trait} = {value}",
            branch_b_text="{} in {{{}}}".format(trait, ", ".join(value_order(negative, trait))),
            branch_a=None,
            branch_b=None,
        )
        node.branch_a = self._solve(positive, number, trait, depth + 1)
        node.branch_b = self._solve(negative, number, trait, depth + 1)
        self.couplet_count += 1
        return node


def target_of(branch: Any) -> str:
    if isinstance(branch, Couplet):
        return f"go to {branch.number}"
    if branch.unresolved:
        return " / ".join(branch.names) + " (unresolved)"
    return branch.names[0]


def render_key_plain(root: Any, title: Optional[str], matrix: Matrix, couplets: int) -> str:
    lines: List[str] = []
    if title:
        lines.extend([title, "=" * len(title), ""])
    noun = "taxon" if len(matrix.taxa) == 1 else "taxa"
    lines.append(
        f"Key for {len(matrix.taxa)} {noun} from {matrix.source_path} "
        f"({len(matrix.traits)} traits, {couplets} couplets)"
    )
    lines.append("")
    _emit_couplets(root, lines, 0)
    return "\n".join(lines).rstrip() + "\n"


def _emit_couplets(node: Any, lines: List[str], depth: int) -> None:
    if not isinstance(node, Couplet):
        return
    indent = "  " * depth
    for branch_text, branch in ((node.branch_a_text, node.branch_a), (node.branch_b_text, node.branch_b)):
        lines.append(f"{indent}{node.number}. {branch_text}  ->  {target_of(branch)}")
    for branch in (node.branch_a, node.branch_b):
        _emit_couplets(branch, lines, depth + 1)


def render_key_markdown(root: Any, title: Optional[str], matrix: Matrix, couplets: int) -> str:
    lines: List[str] = []
    if title:
        lines.extend([f"# {title}", ""])
    noun = "taxon" if len(matrix.taxa) == 1 else "taxa"
    lines.append(
        f"Binary key for {len(matrix.taxa)} {noun} from {matrix.source_path} "
        f"({len(matrix.traits)} traits, {couplets} couplets)."
    )
    lines.append("")
    _emit_markdown(root, lines, 0)
    return "\n".join(lines).rstrip() + "\n"


def _emit_markdown(node: Any, lines: List[str], depth: int) -> None:
    if not isinstance(node, Couplet):
        return
    indent = "  " * depth
    for branch_text, branch in ((node.branch_a_text, node.branch_a), (node.branch_b_text, node.branch_b)):
        lines.append(f"{indent}- **{node.number}.** {branch_text} -> {target_of(branch)}")
        _emit_markdown(branch, lines, depth + 1)


def flatten_couplets(node: Any, out: List[Dict[str, Any]]) -> None:
    if not isinstance(node, Couplet):
        return
    out.append(
        {
            "number": node.number,
            "depth": node.depth,
            "trait": node.trait,
            "balance": node.balance,
            "branch_a": {
                "text": node.branch_a_text,
                "target": target_of(node.branch_a),
                "target_type": "couplet" if isinstance(node.branch_a, Couplet) else "taxon",
            },
            "branch_b": {
                "text": node.branch_b_text,
                "target": target_of(node.branch_b),
                "target_type": "couplet" if isinstance(node.branch_b, Couplet) else "taxon",
            },
        }
    )
    flatten_couplets(node.branch_a, out)
    flatten_couplets(node.branch_b, out)


def key_payload(
    matrix: Matrix, root: Any, title: Optional[str], couplets: int, unresolved: List[List[str]], text: str
) -> Dict[str, Any]:
    flattened: List[Dict[str, Any]] = []
    flatten_couplets(root, flattened)
    return {
        "command": "key generate",
        "source": matrix.source_path,
        "title": title,
        "traits": list(matrix.traits),
        "taxon_count": len(matrix.taxa),
        "couplet_count": couplets,
        "couplets": flattened,
        "unresolved": unresolved,
        "text": text,
    }


# ------------------------------------------------------------------ site grid

@dataclass(frozen=True)
class GridDefinition:
    width: int
    height: int
    cell_size_m: float
    units: str
    origin_lat: Optional[float] = None
    origin_lon: Optional[float] = None


@dataclass(frozen=True)
class Find:
    find_id: str
    taxon: str
    x: int
    y: int
    notes: str
    record: Any


@dataclass
class SiteMap:
    source_path: str
    grid: GridDefinition
    finds: List[Find]


def parse_grid_size(text: str) -> Tuple[int, int]:
    cleaned = text.strip().lower().replace(" ", "")
    parts = cleaned.split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected WxH such as 10x10, got '{text}'")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WxH such as 10x10, got '{text}'")
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError(f"grid cells must be one or more, got '{text}'")
    return width, height


def _meta_positive_float(meta: Dict[str, Any], key: str) -> Optional[float]:
    value = meta.get(key)
    if value is None:
        return None
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _meta_grid(meta: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    block = meta.get("grid")
    if not isinstance(block, dict):
        return None
    try:
        width = int(block["width"])
        height = int(block["height"])
    except (KeyError, TypeError, ValueError):
        return None
    return (width, height) if width >= 1 and height >= 1 else None


def resolve_grid(table: Table, grid_flag: Optional[Tuple[int, int]], cell_size: Optional[float], units: Optional[str]) -> GridDefinition:
    width, height = grid_flag or _meta_grid(table.meta) or (DEFAULT_GRID_WIDTH, DEFAULT_GRID_HEIGHT)
    size = cell_size or _meta_positive_float(table.meta, "cell_size_m") or DEFAULT_CELL_SIZE_M
    unit = units or str(table.meta.get("units") or "").strip().lower() or "m"
    if unit not in UNITS:
        unit = "m"
    origin = table.meta.get("origin") if isinstance(table.meta.get("origin"), dict) else {}
    lat = origin.get("lat") if isinstance(origin, dict) else None
    lon = origin.get("lon") if isinstance(origin, dict) else None
    try:
        origin_lat = float(lat) if lat is not None else None
        origin_lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        origin_lat, origin_lon = None, None
    return GridDefinition(width, height, size, unit, origin_lat, origin_lon)


def parse_finds(table: Table, grid: GridDefinition) -> List[Find]:
    if not table.rows:
        return []
    require_columns(table, ("find_id", "taxon", "x", "y"))
    finds: List[Find] = []
    for row in table.rows:
        find_id = require_word(row, "find_id", table)
        taxon = require_word(row, "taxon", table)
        x = require_index(row, "x", table)
        y = require_index(row, "y", table)
        record = row.get("__record__", "?")
        if not 0 <= x < grid.width:
            raise DataError(
                table.path,
                record,
                "x",
                "marker '{}' at x={}, y={} is outside the effective grid bounds 0..{} x 0..{}".format(
                    find_id, x, y, grid.width - 1, grid.height - 1
                ),
            )
        if not 0 <= y < grid.height:
            raise DataError(
                table.path,
                record,
                "y",
                "marker '{}' at x={}, y={} is outside the effective grid bounds 0..{} x 0..{}".format(
                    find_id, x, y, grid.width - 1, grid.height - 1
                ),
            )
        finds.append(Find(find_id, taxon, x, y, str(row.get("notes", "")).strip(), record))
    return finds


def cell_glyph(count: int) -> str:
    if count <= 0:
        return "."
    if count >= CROWDED_CELL:
        return "+"
    return str(count)


def _ruler_step(cell_width: int, width: int) -> int:
    if cell_width == 1:
        return 1 if width <= 10 else 5
    return 5


def _ruler_line(grid: GridDefinition, label_width: int, cell_width: int, stride: int) -> str:
    total = max(grid.width * stride - (1 if cell_width == 1 else 0), 1)
    slots = [" "] * total
    for x in range(0, grid.width, _ruler_step(cell_width, grid.width)):
        text = str(x)
        offset = x * stride + max(0, (cell_width - len(text)) // 2)
        if offset + len(text) > total:
            continue
        if any(slots[offset + index] != " " for index in range(len(text))):
            continue
        for index, char in enumerate(text):
            slots[offset + index] = char
    return (" " * (label_width + 1) + "".join(slots)).rstrip()


def _grid_body(
    grid: GridDefinition, occupied: Dict[Tuple[int, int], List[Find]], label_width: int, cell_width: int
) -> List[str]:
    stride = cell_width + (1 if cell_width == 1 else 0)
    separator = " " if cell_width == 1 else ""
    lines = [_ruler_line(grid, label_width, cell_width, stride)]
    for y in range(grid.height - 1, -1, -1):
        cells = [cell_glyph(len(occupied.get((x, y), ()))).center(cell_width) for x in range(grid.width)]
        lines.append(f"{y:>{label_width}} {separator.join(cells)}".rstrip())
    return lines


def render_grid(site: SiteMap, cell_width: int) -> str:
    grid = site.grid
    occupied: Dict[Tuple[int, int], List[Find]] = {}
    legend: Dict[str, int] = {}
    for find in site.finds:
        occupied.setdefault((find.x, find.y), []).append(find)
        legend[find.taxon] = legend.get(find.taxon, 0) + 1
    label_width = max(1, len(str(grid.height - 1)))

    lines = [
        "Site grid: {} x {} cells, cell size {} m (distance units: {}), "
        "origin SW cell (0,0), x east, y north".format(
            grid.width,
            grid.height,
            format_number(grid.cell_size_m),
            grid.units,
        ),
        "",
    ]
    lines.extend(_grid_body(grid, occupied, label_width, cell_width))
    lines.extend(
        [
            "",
            "Origin: the south-west cell is (0,0); x increases east, y increases north.",
            "Cells: '.' = no finds, 1-9 = find count, '+' = 10 or more",
        ]
    )

    if not site.finds:
        lines.append(
            f"no finds recorded -- add find_id,taxon,x,y rows to {site.source_path}"
        )
        return "\n".join(lines) + "\n"

    lines.extend(["", "Legend (taxa):"])
    name_width = max(len(taxon) for taxon in legend) + 2
    for taxon, count in sorted(legend.items(), key=lambda item: (-item[1], item[0])):
        lines.append("  " + f"{taxon:<{name_width}}" + str(count))
    crowded = sorted(
        ((key, len(value)) for key, value in occupied.items() if len(value) >= CROWDED_CELL),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )
    if crowded:
        lines.append("Squares with 10 or more finds:")
        for (x, y), count in crowded:
            lines.append(f"  square {x},{y}  {count} finds (drawn as '+')")
    lines.append(
        "Total: {} finds in {} occupied square(s).".format(len(site.finds), len(occupied))
    )
    return "\n".join(lines) + "\n"


def grid_payload(site: SiteMap, text: str) -> Dict[str, Any]:
    grid = site.grid
    occupied: Dict[Tuple[int, int], List[Find]] = {}
    legend: Dict[str, int] = {}
    for find in site.finds:
        occupied.setdefault((find.x, find.y), []).append(find)
        legend[find.taxon] = legend.get(find.taxon, 0) + 1
    return {
        "command": "grid plot",
        "source": site.source_path,
        "grid": {
            "width": grid.width,
            "height": grid.height,
            "cell_size_m": grid.cell_size_m,
            "units": grid.units,
            "origin_corner": "SW",
            "x_axis": "east",
            "y_axis": "north",
        },
        "cells": [
            {
                "x": x,
                "y": y,
                "count": len(value),
                "taxa": sorted({find.taxon for find in value}),
                "find_ids": [find.find_id for find in value],
            }
            for (x, y), value in sorted(occupied.items())
        ],
        "legend": [
            {"taxon": taxon, "count": count}
            for taxon, count in sorted(legend.items(), key=lambda item: (-item[1], item[0]))
        ],
        "total_finds": len(site.finds),
        "text": text,
    }


# --------------------------------------------------------------- projection

@dataclass(frozen=True)
class Projection:
    origin_lat: float
    origin_lon: float
    cell_size_m: float

    def meters_per_degree_lon(self) -> float:
        return M_PER_DEGREE_LAT * math.cos(math.radians(self.origin_lat))

    def to_latlon(self, x: float, y: float) -> Tuple[float, float]:
        east = x * self.cell_size_m
        north = y * self.cell_size_m
        lat = self.origin_lat + north / M_PER_DEGREE_LAT
        lon = self.origin_lon + east / self.meters_per_degree_lon()
        return lat, lon

    def cell_index(self, offset_m: float) -> int:
        """Floor to a cell index, tolerant of projection round-off at a boundary."""
        return int(math.floor(round(offset_m / self.cell_size_m, 9)))

    def to_grid(self, lat: float, lon: float) -> Tuple[int, int]:
        east = (lon - self.origin_lon) * self.meters_per_degree_lon()
        north = (lat - self.origin_lat) * M_PER_DEGREE_LAT
        return (self.cell_index(east), self.cell_index(north))


def planar_distance_m(cell_size_m: float, x1: float, y1: float, x2: float, y2: float) -> float:
    return math.hypot((x2 - x1) * cell_size_m, (y2 - y1) * cell_size_m)


def convert_units(meters: float, units: str) -> float:
    return meters / METERS_PER_UNIT[units]


def _compass(value: float, positive: str, negative: str) -> str:
    return f"{format_latlon(abs(value))} {positive if value >= 0 else negative}"


def _origin_line(projection: Projection, units: str) -> str:
    return (
        f"origin {format_latlon(projection.origin_lat)}, {format_latlon(projection.origin_lon)} "
        f"(local equirectangular, cell size {format_number(projection.cell_size_m)} m, units {units})"
    )


def render_conversion(
    mode: str, projection: Projection, values: Sequence[float], grid: GridDefinition, units: str
) -> Tuple[str, Dict[str, Any]]:
    """Render one conversion result. Returns (text, json fields)."""
    if mode == "to-latlon":
        x, y = values[0], values[1]
        lat, lon = projection.to_latlon(x, y)
        text = "grid {},{} -> {}, {}".format(
            format_number(x), format_number(y), _compass(lat, "N", "S"), _compass(lon, "E", "W")
        )
        fields = {"mode": mode, "grid": {"x": x, "y": y}, "result": {"lat": lat, "lon": lon}}
    elif mode == "to-grid":
        lat, lon = values[0], values[1]
        x, y = projection.to_grid(lat, lon)
        note = "rounded to the containing cell"
        if not (0 <= x < grid.width and 0 <= y < grid.height):
            note += f"; outside the effective grid 0..{grid.width - 1} x 0..{grid.height - 1}"
        text = "lat/long {}, {} -> grid {},{} ({})".format(
            format_latlon(lat), format_latlon(lon), x, y, note
        )
        fields = {"mode": mode, "latlon": {"lat": lat, "lon": lon}, "result": {"x": x, "y": y}}
    else:
        meters = planar_distance_m(projection.cell_size_m, *values)
        shown = convert_units(meters, units)
        text = "distance {},{} -> {},{} = {} {} (cell size {} m)".format(
            format_number(values[0]),
            format_number(values[1]),
            format_number(values[2]),
            format_number(values[3]),
            format_number(shown),
            units,
            format_number(projection.cell_size_m),
        )
        fields = {"mode": mode, "result": {"distance": shown, "units": units}}
    lines = [text, _origin_line(projection, units)]
    return "\n".join(lines) + "\n", {
        "command": "grid convert",
        "origin": {"lat": projection.origin_lat, "lon": projection.origin_lon},
        "cell_size_m": projection.cell_size_m,
        "units": units,
        "text": "\n".join(lines) + "\n",
        **fields,
    }


def resolve_origin(args: argparse.Namespace) -> Tuple[float, float]:
    """Origin from --origin-lat/--origin-lon, else from the origin block of --file."""
    lat_given = args.origin_lat is not None
    lon_given = args.origin_lon is not None
    if lat_given or lon_given:
        if not (lat_given and lon_given):
            raise UsageError("--origin-lat and --origin-lon must be given together")
        return float(args.origin_lat), float(args.origin_lon)

    if not args.file:
        raise UsageError(
            "no origin: pass --origin-lat LAT --origin-lon LON, or --file with a JSON "
            "'origin' block"
        )
    if detect_format(args.file) != "json":
        raise UsageError(
            f"{args.file}: a CSV input carries no origin block; grid convert needs "
            "--origin-lat/--origin-lon or a .json file with an 'origin' block"
        )
    table = read_table(args.file, "finds")
    origin = table.meta.get("origin")
    if not isinstance(origin, dict) or origin.get("lat") is None or origin.get("lon") is None:
        raise UsageError(
            f"{args.file}: no usable origin block; expected "
            '{"origin": {"lat": ..., "lon": ...}} or --origin-lat/--origin-lon'
        )
    try:
        return float(str(origin["lat"])), float(str(origin["lon"]))
    except (TypeError, ValueError):
        raise UsageError(
            f"{args.file}: origin.lat and origin.lon must be numbers, got "
            f"{origin.get('lat')!r} and {origin.get('lon')!r}"
        )


# ------------------------------------------------------------------ commands

def write_output(text: str, destination: Optional[str]) -> None:
    if destination:
        directory = os.path.dirname(os.path.abspath(destination))
        if directory and not os.path.isdir(directory):
            raise UsageError(f"{destination}: output directory does not exist")
        try:
            with open(destination, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as error:
            raise UsageError(f"{destination}: cannot be written ({error.strerror or error})")
        return
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "unknown"
        raise UsageError(
            f"stdout is {encoding} and cannot print these characters; use --style ascii "
            "(the default) or set PYTHONIOENCODING=utf-8"
        )


def emit_json(payload: Dict[str, Any], destination: Optional[str]) -> None:
    write_output(json.dumps(payload, indent=2) + "\n", destination)


def cmd_strata_plot(args: argparse.Namespace) -> int:
    table = read_table(args.file, "layers")
    column = parse_column(table)
    width = terminal_width()
    text, note = render_column(column, args.width, args.scale, width, args.style)
    if note:
        print(note, file=sys.stderr)
    if args.json:
        emit_json(column_payload(column, args.width, args.scale, width, text), args.out)
    else:
        write_output(text, args.out)
    return EXIT_OK


def cmd_key_generate(args: argparse.Namespace) -> int:
    table = read_table(args.file, "taxa")
    matrix = parse_matrix(table)
    if not matrix.taxa:
        text = f"no taxa to key -- add taxon rows to {matrix.source_path}\n"
        if args.json:
            emit_json(
                key_payload(matrix, None, args.title, 0, [], text),
                args.out,
            )
        else:
            write_output(text, args.out)
        return EXIT_OK

    builder = KeyBuilder(matrix)
    root = builder.build()
    for group in builder.unresolved:
        print(
            "{}: warning: {}: {} share identical trait vectors and cannot be separated".format(
                PROG, matrix.source_path, ", ".join(repr(name) for name in group)
            ),
            file=sys.stderr,
        )
    if args.format == "markdown":
        text = render_key_markdown(root, args.title, matrix, builder.couplet_count)
    else:
        text = render_key_plain(root, args.title, matrix, builder.couplet_count)
    if args.json:
        emit_json(
            key_payload(matrix, root, args.title, builder.couplet_count, builder.unresolved, text),
            args.out,
        )
    else:
        write_output(text, args.out)
    return EXIT_OK


def cmd_grid_plot(args: argparse.Namespace) -> int:
    table = read_table(args.file, "finds")
    grid = resolve_grid(table, args.grid, args.cell_size, args.units)
    finds = parse_finds(table, grid)
    site = SiteMap(table.path, grid, finds)
    text = render_grid(site, args.cell_width)
    if args.json:
        emit_json(grid_payload(site, text), args.out)
    else:
        write_output(text, args.out)
    return EXIT_OK


def cmd_grid_convert(args: argparse.Namespace) -> int:
    origin_lat, origin_lon = resolve_origin(args)
    if abs(math.cos(math.radians(origin_lat))) < 1e-9:
        raise DataError(
            f"{args.file}" if args.file else "--origin-lat",
            "-",
            "origin_lat",
            "a latitude of ±90 makes the local equirectangular projection degenerate",
        )
    width, height = args.grid or (DEFAULT_GRID_WIDTH, DEFAULT_GRID_HEIGHT)
    cell_size = args.cell_size or DEFAULT_CELL_SIZE_M
    grid = GridDefinition(width, height, cell_size, args.units, origin_lat, origin_lon)
    projection = Projection(origin_lat, origin_lon, cell_size)

    if args.to_latlon is not None:
        mode, values = "to-latlon", args.to_latlon
    elif args.to_grid is not None:
        mode, values = "to-grid", args.to_grid
    else:
        mode, values = "distance", args.distance

    text, payload = render_conversion(mode, projection, values, grid, args.units)
    if args.json:
        emit_json(payload, args.out)
    else:
        write_output(text, args.out)
    return EXIT_OK


# -------------------------------------------------------------------- parser

def positive_scale(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number")
    if not math.isfinite(value) or value < MIN_SCALE:
        raise argparse.ArgumentTypeError(f"scale must be a number >= {MIN_SCALE}, got '{text}'")
    return value


def label_width(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not an integer")
    if value < MIN_LABEL_WIDTH:
        raise argparse.ArgumentTypeError(
            f"label width must be an integer >= {MIN_LABEL_WIDTH}, got '{text}'"
        )
    return value


def positive_cell_size(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number")
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"cell size must be a number > 0, got '{text}'")
    return value


def cell_width_value(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not an integer")
    if value < 1:
        raise argparse.ArgumentTypeError(f"cell width must be an integer >= 1, got '{text}'")
    return value


def add_common_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--out", metavar="FILE", default=None, help="write to FILE instead of stdout")
    parser.add_argument(
        "--json", action="store_true", help="write a single JSON object instead of plain text"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="FossilGrid -- stratigraphic columns, dichotomous keys and site grid maps.",
        epilog=ROOT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"FossilGrid {VERSION}")
    groups = parser.add_subparsers(dest="group", metavar="{strata,key,grid}")

    strata = groups.add_parser(
        "strata",
        help="render a stratigraphic column",
        description="Plot a measured section as an ASCII stratigraphic column.",
        epilog=STRATA_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    strata_commands = strata.add_subparsers(dest="command", metavar="{plot}")
    plot = strata_commands.add_parser(
        "plot",
        help="render the column for a layers file",
        description="Render a top-to-bottom layer table as a stratigraphic column.",
        epilog=STRATA_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    plot.add_argument("file", metavar="FILE", help="layers table: .csv or .json")
    plot.add_argument(
        "--scale",
        type=positive_scale,
        default=DEFAULT_SCALE,
        metavar="S",
        help=f"vertical rows per metre (float, default {DEFAULT_SCALE}, min {MIN_SCALE})",
    )
    plot.add_argument(
        "--width",
        type=label_width,
        default=DEFAULT_LABEL_WIDTH,
        metavar="W",
        help=f"label column width in characters (int, default {DEFAULT_LABEL_WIDTH}, min {MIN_LABEL_WIDTH})",
    )
    plot.add_argument(
        "--style",
        choices=("ascii", "unicode"),
        default="ascii",
        help="column drawing style (default ascii)",
    )
    add_common_output(plot)
    plot.set_defaults(func=cmd_strata_plot)

    key = groups.add_parser(
        "key",
        help="build a dichotomous identification key",
        description="Generate a binary dichotomous key from a taxon x trait matrix.",
        epilog=KEY_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    key_commands = key.add_subparsers(dest="command", metavar="{generate}")
    generate = key_commands.add_parser(
        "generate",
        help="generate the key for a taxa file",
        description="Generate a deterministic binary key from a taxon x trait matrix.",
        epilog=KEY_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    generate.add_argument("file", metavar="FILE", help="taxon x trait matrix: .csv or .json")
    generate.add_argument("--title", metavar="TEXT", default=None, help="first line of the key")
    generate.add_argument(
        "--format",
        choices=("text", "markdown"),
        default="text",
        help="output format (default text)",
    )
    add_common_output(generate)
    generate.set_defaults(func=cmd_key_generate)

    grid = groups.add_parser(
        "grid",
        help="map finds on a site grid and convert coordinates",
        description="Map fossil finds onto a site grid and convert grid squares.",
        epilog=GRID_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grid_commands = grid.add_subparsers(dest="command", metavar="{plot,convert}")

    grid_plot = grid_commands.add_parser(
        "plot",
        help="draw the ASCII site map",
        description="Draw an ASCII map of fossil finds on a site grid.",
        epilog=GRID_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grid_plot.add_argument("file", metavar="FILE", help="finds table: .csv or .json")
    grid_plot.add_argument(
        "--grid",
        type=parse_grid_size,
        default=None,
        metavar="WxH",
        help=f"grid width x height in cells (default {DEFAULT_GRID_WIDTH}x{DEFAULT_GRID_HEIGHT})",
    )
    grid_plot.add_argument(
        "--cell-size",
        type=positive_cell_size,
        default=None,
        metavar="S",
        help=f"cell size in metres (float, default {format_number(DEFAULT_CELL_SIZE_M)})",
    )
    grid_plot.add_argument(
        "--units",
        choices=UNITS,
        default=None,
        help="distance unit for the header (default m)",
    )
    grid_plot.add_argument(
        "--cell-width",
        type=cell_width_value,
        default=DEFAULT_CELL_WIDTH,
        metavar="N",
        help=f"characters per cell (int, default {DEFAULT_CELL_WIDTH}, min 1)",
    )
    add_common_output(grid_plot)
    grid_plot.set_defaults(func=cmd_grid_plot)

    convert = grid_commands.add_parser(
        "convert",
        help="convert grid squares to lat/long and back",
        description="Convert between grid squares and lat/long with a local equirectangular "
        "projection about an origin.",
        epilog=GRID_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    origin = convert.add_argument_group("origin (one of the two forms is required)")
    origin.add_argument("--origin-lat", type=float, default=None, metavar="LAT", help="origin latitude in decimal degrees")
    origin.add_argument("--origin-lon", type=float, default=None, metavar="LON", help="origin longitude in decimal degrees")
    origin.add_argument("--file", metavar="FILE", default=None, help=".json finds file whose 'origin' block supplies lat/lon")
    targets = convert.add_mutually_exclusive_group(required=True)
    targets.add_argument(
        "--to-latlon",
        nargs=2,
        type=float,
        metavar="X Y",
        default=None,
        help="grid square X Y -> lat/long",
    )
    targets.add_argument(
        "--to-grid",
        nargs=2,
        type=float,
        metavar="LAT LON",
        default=None,
        help="lat/long -> containing grid square",
    )
    targets.add_argument(
        "--distance",
        nargs=4,
        type=float,
        metavar="X1 Y1 X2 Y2",
        default=None,
        help="planar distance between two grid squares",
    )
    convert.add_argument(
        "--units", choices=UNITS, default="m", help="unit for printed distances (default m)"
    )
    convert.add_argument(
        "--grid",
        type=parse_grid_size,
        default=None,
        metavar="WxH",
        help=f"effective grid for bounds notes (default {DEFAULT_GRID_WIDTH}x{DEFAULT_GRID_HEIGHT})",
    )
    convert.add_argument(
        "--cell-size",
        type=positive_cell_size,
        default=None,
        metavar="S",
        help=f"cell size in metres (float, default {format_number(DEFAULT_CELL_SIZE_M)})",
    )
    add_common_output(convert)
    convert.set_defaults(func=cmd_grid_convert)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help()
        return EXIT_OK
    try:
        return handler(args)
    except DataError as error:
        print(str(error), file=sys.stderr)
        return EXIT_DATA
    except UsageError as error:
        print(f"{PROG}: error: {error}", file=sys.stderr)
        return EXIT_USAGE


def cli() -> None:
    try:
        sys.exit(main())
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        sys.exit(EXIT_OK)
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    cli()
