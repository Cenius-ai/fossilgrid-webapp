"""Development tests for FossilGrid.

Run from the repository root:  python3 -m unittest test_fossilgrid
This module is dev-only: the tool works without it.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fossilgrid as fg  # noqa: E402  (path fix above must run first)

LAYERS_CSV = (
    "name,thickness_m,lithology,notes\n"
    "Top sand,1.0,sandstone,\n"
    "Middle shale,2.0,shale,ammonites\n"
    "Base limestone,3.0,limestone,\n"
)

SCALE_CSV = "name,thickness_m,lithology\nSingle bed,3.0,sandstone\n"

TAXA_CSV = (
    "taxon,lithology,ribbing\n"
    "Alpha,shale,coarse\n"
    "Beta,shale,coarse\n"
    "Gamma,limestone,coarse\n"
    "Delta,limestone,fine\n"
)


def run_cli(*args, env=None, stdin_text=None):
    """Run the shipped CLI in a subprocess and capture both streams."""
    environment = dict(os.environ)
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "fossilgrid.py")] + list(args),
        cwd=ROOT,
        env=environment,
        input=stdin_text,
        capture_output=True,
        text=True,
    )


class TempFilesMixin:
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="fossilgrid-test-")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for name in os.listdir(self._dir):
            os.remove(os.path.join(self._dir, name))
        os.rmdir(self._dir)

    def write(self, name, content):
        path = os.path.join(self._dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path


# ------------------------------------------------------------------- surface

class TestCliSurface(unittest.TestCase):
    def test_version_on_stdout_exit_zero(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "FossilGrid 0.1.0")

    def test_root_help_lists_groups_and_exit_codes(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for word in ("strata", "key", "grid", "exit codes", "0  success", "2  usage error"):
            self.assertIn(word, result.stdout)

    def test_group_help_lists_plot_flags_with_defaults(self):
        result = run_cli("strata", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("plot", result.stdout)
        for flag in ("--scale", "--width", "--out"):
            self.assertIn(flag, result.stdout)
        self.assertIn("default 1.0", result.stdout)
        self.assertIn("default 24", result.stdout)

    def test_command_help_lists_convert_flags(self):
        result = run_cli("grid", "convert", "--help")
        self.assertEqual(result.returncode, 0)
        for flag in (
            "--origin-lat",
            "--origin-lon",
            "--to-latlon",
            "--to-grid",
            "--distance",
            "--units",
            "--grid",
            "--cell-size",
            "--file",
        ):
            self.assertIn(flag, result.stdout)

    def test_bare_invocation_prints_help_and_exits_zero(self):
        result = run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("strata plot", result.stdout)

    def test_unknown_command_is_usage_error(self):
        result = run_cli("bogus")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("strata", result.stderr)

    def test_unknown_flag_is_usage_error(self):
        result = run_cli("strata", "plot", "--nope", "x.csv")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_bad_scale_value_is_usage_error(self):
        result = run_cli("strata", "plot", "examples/layers.csv", "--scale", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("scale", result.stderr)


# -------------------------------------------------------------------- loader

class TestLoader(TempFilesMixin, unittest.TestCase):
    def test_csv_and_json_produce_identical_column_body(self):
        csv_path = self.write("layers.csv", LAYERS_CSV)
        json_path = self.write(
            "layers.json",
            json.dumps(
                [
                    {"name": "Top sand", "thickness_m": 1.0, "lithology": "sandstone", "notes": ""},
                    {"name": "Middle shale", "thickness_m": 2.0, "lithology": "shale", "notes": "ammonites"},
                    {"name": "Base limestone", "thickness_m": 3.0, "lithology": "limestone", "notes": ""},
                ]
            ),
        )
        from_csv = run_cli("strata", "plot", csv_path)
        from_json = run_cli("strata", "plot", json_path)
        self.assertEqual(from_csv.returncode, 0)
        self.assertEqual(from_json.returncode, 0)
        # only the echoed source path may differ
        self.assertEqual(from_csv.stdout.splitlines()[1:], from_json.stdout.splitlines()[1:])

    def test_named_collection_object_is_accepted(self):
        path = self.write("layers.json", json.dumps({"layers": [{"name": "Bed", "thickness_m": 2}]}))
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Bed", result.stdout)

    def test_json_object_without_collection_is_data_error(self):
        path = self.write("layers.json", json.dumps({"nope": []}))
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("layers", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unsupported_extension_is_usage_error(self):
        path = self.write("layers.txt", LAYERS_CSV)
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("only .csv and .json", result.stderr)

    def test_missing_file_is_data_error(self):
        result = run_cli("strata", "plot", os.path.join(self._dir, "absent.csv"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot be read", result.stderr)


# ------------------------------------------------------------------- columns

class TestStrataColumn(TempFilesMixin, unittest.TestCase):
    def test_depths_run_top_to_bottom(self):
        path = self.write("layers.csv", LAYERS_CSV)
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Top boundary depth from base: 6.00 m", result.stdout)
        self.assertIn("Base boundary depth from base: 0.00 m", result.stdout)
        self.assertIn("Total thickness: 6.00 m across 3 layers", result.stdout)

    def test_layer_label_block_carries_depth_lithology_and_notes(self):
        path = self.write("layers.csv", LAYERS_CSV)
        text = run_cli("strata", "plot", path, "--width", "40").stdout
        self.assertIn("Middle shale (2.00 m)", text)
        self.assertIn("lithology: shale [h]", text)
        self.assertIn("depth from base: 5.00 - 3.00 m", text)
        self.assertIn("notes: ammonites", text)

    def test_legend_and_base_line(self):
        path = self.write("layers.csv", LAYERS_CSV)
        text = run_cli("strata", "plot", path).stdout
        self.assertIn("Lithology legend:", text)
        self.assertIn("s  sandstone", text)
        self.assertIn("base of section", text)

    def test_non_numeric_thickness_names_file_row_and_field(self):
        path = self.write("layers.csv", "name,thickness_m\nBed,thick\n")
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertRegex(result.stderr.strip(), r"^" + re.escape(path) + r":2: thickness_m: .+")

    def test_missing_name_is_reported_at_its_row(self):
        path = self.write("layers.csv", "name,thickness_m\n,2.0\n")
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stderr.strip(), r":2: name: ")

    def test_missing_required_column_is_reported(self):
        path = self.write("layers.csv", "name,lithology\nBed,sandstone\n")
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("thickness_m", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_header_only_file_is_a_friendly_empty_state(self):
        path = self.write("layers.csv", "name,thickness_m,lithology,notes\n")
        result = run_cli("strata", "plot", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("no layers to plot -- add name,thickness_m rows to", result.stdout)


class TestColumnRenderer(TempFilesMixin, unittest.TestCase):
    def test_scale_multiplies_rows_but_labels_once(self):
        path = self.write("layers.csv", SCALE_CSV)
        text = run_cli("strata", "plot", path, "--scale", "2").stdout
        lines = [line for line in text.splitlines() if line.strip()]
        sides = [line for line in lines if "ssss" in line]
        tops = [line for line in lines if "+--" in line and "base of section" not in line]
        self.assertEqual(len(sides) + len(tops), 6)
        self.assertEqual(sum(1 for line in lines if "(3.00 m)" in line), 1)

    def test_tiny_scale_still_draws_at_least_one_row(self):
        path = self.write("layers.csv", SCALE_CSV)
        text = run_cli("strata", "plot", path, "--scale", "0.5").stdout
        self.assertIn("(3.00 m)", text)
        self.assertTrue(any("+--" in line for line in text.splitlines()))

    def test_width_truncates_with_ellipsis_and_keeps_edges_aligned(self):
        path = self.write("layers.csv", "name,thickness_m,lithology\nCross-bedded fluvial sandstone,1.0,sandstone\n")
        text = run_cli("strata", "plot", path, "--width", "8").stdout
        self.assertIn("Cross...", text)
        widths = {len(line.rstrip()) for line in text.splitlines() if "+--" in line or "ssss" in line}
        self.assertEqual(len(widths), 1)

    def test_narrow_terminal_compresses_column_and_notes_on_stderr(self):
        result = run_cli("strata", "plot", "examples/layers.csv", env={"COLUMNS": "40"})
        self.assertEqual(result.returncode, 0)
        for line in result.stdout.splitlines():
            self.assertLessEqual(len(line), 40, msg="line too wide: %r" % line)
        self.assertIn("was compressed", result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)

    def test_wide_terminal_is_not_compressed(self):
        result = run_cli("strata", "plot", "examples/layers.csv", env={"COLUMNS": "120"})
        self.assertEqual(result.stderr, "")
        self.assertIn("Plot width: 12 chars", result.stdout)

    def test_out_writes_exactly_the_stdout_text(self):
        path = self.write("layers.csv", LAYERS_CSV)
        destination = os.path.join(self._dir, "column.txt")
        piped = run_cli("strata", "plot", path)
        written = run_cli("strata", "plot", path, "--out", destination)
        self.assertEqual(written.stdout, "")
        with open(destination, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), piped.stdout)

    def test_unicode_style_uses_box_drawing_and_keeps_ascii_default(self):
        path = self.write("layers.csv", LAYERS_CSV)
        ascii_text = run_cli("strata", "plot", path).stdout
        unicode_text = run_cli("strata", "plot", path, "--style", "unicode").stdout
        self.assertIn("+-", ascii_text)
        self.assertIn("\u250c", unicode_text)
        self.assertIn("\u2592", unicode_text)
        for line in unicode_text.splitlines():
            if "\u2502" in line:
                self.assertIn("\u2502", line)

    def test_renderer_is_deterministic(self):
        first = run_cli("strata", "plot", "examples/layers.csv").stdout
        second = run_cli("strata", "plot", "examples/layers.csv").stdout
        self.assertEqual(first, second)


# ---------------------------------------------------------------------- keys

class TestKeyMatrix(TempFilesMixin, unittest.TestCase):
    def test_multi_value_cells_become_value_lists(self):
        path = self.write("taxa.csv", "taxon,lithology\nAlpha,shale|limestone\nBeta,sandstone\n")
        matrix = fg.parse_matrix(fg.read_table(path, "taxa"))
        self.assertEqual(matrix.taxa[0].values["lithology"], ("shale", "limestone"))

    def test_json_taxa_object_matches_csv_key(self):
        csv_path = self.write("taxa.csv", TAXA_CSV)
        json_path = self.write(
            "taxa.json",
            json.dumps(
                {
                    "taxa": [
                        {"taxon": "Alpha", "lithology": "shale", "ribbing": "coarse"},
                        {"taxon": "Beta", "lithology": "shale", "ribbing": "coarse"},
                        {"taxon": "Gamma", "lithology": "limestone", "ribbing": "coarse"},
                        {"taxon": "Delta", "lithology": "limestone", "ribbing": "fine"},
                    ]
                }
            ),
        )
        from_csv = run_cli("key", "generate", csv_path)
        from_json = run_cli("key", "generate", json_path)
        self.assertEqual(from_csv.returncode, 0)
        self.assertEqual(from_csv.stdout.splitlines()[1:], from_json.stdout.splitlines()[1:])

    def test_duplicate_taxon_name_is_data_error(self):
        path = self.write("taxa.csv", "taxon,lithology\nAlpha,shale\nAlpha,limestone\n")
        result = run_cli("key", "generate", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate taxon name 'Alpha'", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_empty_matrix_is_a_friendly_empty_state(self):
        path = self.write("taxa.csv", "taxon,lithology\n")
        result = run_cli("key", "generate", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("no taxa to key -- add taxon rows to", result.stdout)

    def test_missing_taxon_column_is_data_error(self):
        path = self.write("taxa.csv", "name,lithology\nAlpha,shale\n")
        result = run_cli("key", "generate", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("taxon", result.stderr)


class TestKeySplitting(unittest.TestCase):
    def test_one_vs_rest_uses_frequency_order(self):
        matrix = fg.parse_matrix(
            fg.Table(
                "t.csv",
                ["taxon", "lithology"],
                [
                    {"__record__": 2, "taxon": "A", "lithology": "sandstone"},
                    {"__record__": 3, "taxon": "B", "lithology": "sandstone"},
                    {"__record__": 4, "taxon": "C", "lithology": "sandstone"},
                    {"__record__": 5, "taxon": "D", "lithology": "shale"},
                    {"__record__": 6, "taxon": "E", "lithology": "shale"},
                    {"__record__": 7, "taxon": "F", "lithology": "limestone"},
                ],
                {},
            )
        )
        builder = fg.KeyBuilder(matrix)
        root = builder.build()
        self.assertEqual(root.branch_a_text, "lithology = sandstone")
        self.assertEqual(root.branch_b_text, "lithology in {shale, limestone}")
        self.assertEqual(root.number, "1")

    def test_continuing_the_same_trait_is_lettered(self):
        matrix = fg.parse_matrix(
            fg.Table(
                "t.csv",
                ["taxon", "lithology"],
                [
                    {"__record__": 2, "taxon": "A", "lithology": "sandstone"},
                    {"__record__": 3, "taxon": "B", "lithology": "sandstone"},
                    {"__record__": 4, "taxon": "C", "lithology": "shale"},
                    {"__record__": 5, "taxon": "D", "lithology": "limestone"},
                ],
                {},
            )
        )
        builder = fg.KeyBuilder(matrix)
        root = builder.build()
        self.assertEqual(root.number, "1")
        self.assertEqual(root.branch_b.number, "1a")
        self.assertEqual(root.branch_b.branch_a_text, "lithology = limestone")

    def test_header_order_breaks_balance_ties(self):
        traits = ["second_trait", "first_trait"]
        subset = [
            fg.Taxon("A", {"second_trait": ("x",), "first_trait": ("p",)}),
            fg.Taxon("B", {"second_trait": ("x",), "first_trait": ("q",)}),
            fg.Taxon("C", {"second_trait": ("y",), "first_trait": ("p",)}),
            fg.Taxon("D", {"second_trait": ("y",), "first_trait": ("q",)}),
        ]
        choice = fg.best_split(subset, traits)
        self.assertEqual(choice[0], "second_trait")

    def test_value_order_is_frequency_then_alphabetical(self):
        subset = [
            fg.Taxon("A", {"t": ("beta", "alpha")}),
            fg.Taxon("B", {"t": ("beta",)}),
        ]
        self.assertEqual(fg.value_order(subset, "t"), ["beta", "alpha"])

    def test_identical_vectors_are_unresolved(self):
        path = os.path.join(ROOT, "examples", "taxa.csv")
        matrix = fg.parse_matrix(fg.read_table(path, "taxa"))
        twins = fg.Matrix(
            "twins.csv",
            matrix.traits,
            matrix.taxa[:1] + [fg.Taxon(matrix.taxa[0].name + " II", matrix.taxa[0].values)],
        )
        builder = fg.KeyBuilder(twins)
        builder.build()
        self.assertEqual(len(builder.unresolved), 1)
        self.assertEqual(len(builder.unresolved[0]), 2)


class TestKeyRendering(TempFilesMixin, unittest.TestCase):
    def test_numbered_couplets_lead_to_every_taxon(self):
        path = self.write("taxa.csv", TAXA_CSV)
        result = run_cli("key", "generate", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("1. ", result.stdout)
        for taxon in ("Alpha", "Beta", "Gamma", "Delta"):
            self.assertIn(taxon, result.stdout)

    def test_title_is_the_first_line(self):
        path = self.write("taxa.csv", TAXA_CSV)
        result = run_cli("key", "generate", path, "--title", "Ordovician fauna")
        self.assertEqual(result.stdout.splitlines()[0], "Ordovician fauna")

    def test_unresolved_taxa_warn_but_still_render(self):
        path = self.write(
            "taxa.csv",
            "taxon,lithology,ribbing\nAlpha,shale,coarse\nBeta,shale,coarse\nGamma,limestone,fine\n",
        )
        result = run_cli("key", "generate", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("warning", result.stderr)
        self.assertIn("Alpha", result.stderr)
        self.assertIn("Beta", result.stderr)
        self.assertIn("(unresolved)", result.stdout)

    def test_out_writes_exactly_the_stdout_text(self):
        path = self.write("taxa.csv", TAXA_CSV)
        destination = os.path.join(self._dir, "key.txt")
        piped = run_cli("key", "generate", path)
        written = run_cli("key", "generate", path, "--out", destination)
        self.assertEqual(written.stdout, "")
        with open(destination, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), piped.stdout)

    def test_markdown_matches_plain_key_order_and_leaves(self):
        path = self.write("taxa.csv", TAXA_CSV)
        plain = run_cli("key", "generate", path).stdout
        markdown = run_cli("key", "generate", path, "--format", "markdown").stdout
        plain_order = [line.split(".", 1)[0] for line in plain.splitlines() if re.match(r"^\s*\S+\. ", line)]
        markdown_numbers = re.findall(r"\*\*([0-9a-z]+)\.\*\*", markdown)
        self.assertTrue(markdown.startswith("Binary key"))
        self.assertEqual(len(markdown_numbers), len(plain_order))
        for taxon in ("Alpha", "Beta", "Gamma", "Delta"):
            self.assertIn(taxon, markdown)

    def test_default_format_is_plain_text(self):
        path = self.write("taxa.csv", TAXA_CSV)
        result = run_cli("key", "generate", path)
        self.assertNotIn("**", result.stdout)
        self.assertIn("->", result.stdout)


# ---------------------------------------------------------------------- grid

class TestGridParsing(TempFilesMixin, unittest.TestCase):
    def test_defaults_are_ten_by_ten(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,3,4\n")
        result = run_cli("grid", "plot", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Site grid: 10 x 10 cells", result.stdout)
        bodies = [line for line in result.stdout.splitlines() if line[:2].strip().isdigit()]
        self.assertEqual(len(bodies), 10)

    def test_marker_lands_three_across_four_up(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,3,4\n")
        result = run_cli("grid", "plot", path)
        rows = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^(\d+) (.*)$", line)
            if match:
                rows[int(match.group(1))] = match.group(2).split()
        self.assertEqual(rows[4][3], "1")
        self.assertEqual(rows[0][3], ".")

    def test_out_of_bounds_marker_names_find_and_bounds(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nFG-014,Ammonite,5,4\n")
        result = run_cli("grid", "plot", path, "--grid", "5x5")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FG-014", result.stderr)
        self.assertIn("0..4 x 0..4", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_bounds_follow_the_effective_grid(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,10,7\n")
        result = run_cli("grid", "plot", path, "--grid", "12x8")
        self.assertEqual(result.returncode, 0)
        rows = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^(\d+) (.*)$", line)
            if match:
                rows[int(match.group(1))] = match.group(2).split()
        self.assertEqual(rows[7][10], "1")
        ruler = next(line for line in result.stdout.splitlines() if re.match(r"^\s*0\s+5", line))
        self.assertIn("10", ruler)

    def test_two_finds_in_one_square_show_two_and_both_taxa(self):
        path = self.write(
            "finds.csv", "find_id,taxon,x,y\nF1,Ammonite,7,3\nF2,Belemnite,7,3\n"
        )
        result = run_cli("grid", "plot", path)
        self.assertIn("2", result.stdout)
        self.assertIn("Ammonite", result.stdout)
        self.assertIn("Belemnite", result.stdout)

    def test_cell_size_flag_changes_only_the_header(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,3,4\n")
        default = run_cli("grid", "plot", path).stdout
        bigger = run_cli("grid", "plot", path, "--cell-size", "5").stdout
        self.assertIn("cell size 5 m", bigger.splitlines()[0])
        self.assertEqual(default.splitlines()[2:], bigger.splitlines()[2:])


class TestGridRendering(TempFilesMixin, unittest.TestCase):
    def test_empty_file_draws_dots_and_explains_what_to_add(self):
        path = self.write("finds.csv", "find_id,taxon,x,y,notes\n")
        result = run_cli("grid", "plot", path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("no finds recorded -- add find_id,taxon,x,y rows", result.stdout)
        body = [line for line in result.stdout.splitlines() if line[:2].strip().isdigit()]
        self.assertEqual(len(body), 10)
        self.assertIn(". . . . . . . . . .", body[0])

    def test_ten_or_more_finds_show_a_plus_and_a_legend_note(self):
        rows = "".join("F{},Ammonite,4,4\n".format(index) for index in range(12))
        path = self.write("finds.csv", "find_id,taxon,x,y\n" + rows)
        result = run_cli("grid", "plot", path)
        self.assertIn("+", result.stdout)
        self.assertIn("Squares with 10 or more finds:", result.stdout)
        self.assertIn("square 4,4  12 finds", result.stdout)
        self.assertIn("Ammonite  12", result.stdout)

    def test_legend_lists_each_taxon_once_with_its_count(self):
        path = self.write(
            "finds.csv",
            "find_id,taxon,x,y\n"
            "F1,A very long taxon name indeed,1,1\n"
            "F2,A very long taxon name indeed,2,2\n"
            "F3,Short,3,3\n",
        )
        result = run_cli("grid", "plot", path)
        legend = [line for line in result.stdout.splitlines() if "A very long" in line]
        self.assertEqual(len(legend), 1)
        self.assertIn("2", legend[0])
        self.assertEqual(len([line for line in result.stdout.splitlines() if line.strip().startswith("Short")]), 1)

    def test_out_writes_exactly_the_stdout_text(self):
        destination = os.path.join(self._dir, "map.txt")
        piped = run_cli("grid", "plot", "examples/finds.csv")
        written = run_cli("grid", "plot", "examples/finds.csv", "--out", destination)
        self.assertEqual(written.stdout, "")
        with open(destination, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), piped.stdout)

    def test_cell_width_three_centres_glyphs_and_labels_every_fifth_column(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,3,4\n")
        result = run_cli("grid", "plot", path, "--cell-width", "3")
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        ruler = next(line for line in lines if re.match(r"^\s*0\s+5", line))
        self.assertNotIn("1", ruler.replace("10", ""))
        body = [line for line in lines if re.match(r"^\d\s", line)]
        self.assertEqual(len(body), 10)
        self.assertIn(" 1 ", body[-5])
        self.assertIn(" . ", body[-1])

    def test_default_cell_width_is_one_character(self):
        path = self.write("finds.csv", "find_id,taxon,x,y\nF1,Ammonite,3,4\n")
        text = run_cli("grid", "plot", path).stdout
        body = [line for line in text.splitlines() if re.match(r"^\d ", line)]
        self.assertIn(". . . 1 . . . . . .", body[-5])


# ------------------------------------------------------------------ convert

class TestGridConvert(unittest.TestCase):
    def test_grid_to_latlon_uses_the_origin(self):
        result = run_cli(
            "grid", "convert", "--origin-lat", "52.0", "--origin-lon", "4.0", "--to-latlon", "0", "0"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("52.000000 N, 4.000000 E", result.stdout)
        self.assertIn("origin 52.000000, 4.000000", result.stdout)

    def test_latlon_to_containing_grid_square(self):
        result = run_cli(
            "grid",
            "convert",
            "--origin-lat",
            "52.0",
            "--origin-lon",
            "4.0",
            "--cell-size",
            "100",
            "--to-grid",
            "52.0",
            "4.45",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("grid 308,0", result.stdout)
        self.assertIn("rounded to the containing cell", result.stdout)

    def test_distance_in_metres_and_kilometres(self):
        meters = run_cli(
            "grid", "convert", "--origin-lat", "52.0", "--origin-lon", "4.0", "--distance", "0", "0", "3", "4"
        )
        self.assertEqual(meters.returncode, 0)
        self.assertIn("= 5 m", meters.stdout)
        kilometres = run_cli(
            "grid",
            "convert",
            "--origin-lat",
            "52.0",
            "--origin-lon",
            "4.0",
            "--distance",
            "0",
            "0",
            "3",
            "4",
            "--units",
            "km",
        )
        self.assertIn("= 0.005 km", kilometres.stdout)

    def test_origin_can_come_from_the_file_origin_block(self):
        result = run_cli("grid", "convert", "--file", "examples/finds.json", "--to-latlon", "0", "0")
        self.assertEqual(result.returncode, 0)
        self.assertIn("52.000000 N, 4.000000 E", result.stdout)

    def test_missing_origin_is_a_usage_error(self):
        result = run_cli("grid", "convert", "--to-grid", "52.0", "4.0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("origin", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_two_conversion_targets_are_a_usage_error(self):
        result = run_cli(
            "grid",
            "convert",
            "--origin-lat",
            "52.0",
            "--origin-lon",
            "4.0",
            "--to-grid",
            "52.0",
            "4.0",
            "--distance",
            "0",
            "0",
            "1",
            "1",
        )
        self.assertEqual(result.returncode, 2)

    def test_no_conversion_target_is_a_usage_error(self):
        result = run_cli("grid", "convert", "--origin-lat", "52.0", "--origin-lon", "4.0")
        self.assertEqual(result.returncode, 2)

    def test_origin_lat_without_lon_is_a_usage_error(self):
        result = run_cli("grid", "convert", "--origin-lat", "52.0", "--to-latlon", "0", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("together", result.stderr)

    def test_projection_round_trip(self):
        projection = fg.Projection(52.0, 4.0, 1.0)
        for x, y in ((0, 0), (3, 4), (9, 9)):
            lat, lon = projection.to_latlon(x, y)
            self.assertEqual(projection.to_grid(lat, lon), (x, y))

    def test_distance_helper(self):
        self.assertAlmostEqual(fg.planar_distance_m(1.0, 0.0, 0.0, 3.0, 4.0), 5.0)
        self.assertAlmostEqual(fg.convert_units(5000.0, "km"), 5.0)
        self.assertAlmostEqual(fg.convert_units(1.0, "ft"), 1.0 / 0.3048)


# --------------------------------------------------------------- json output

class TestJsonOutput(TempFilesMixin, unittest.TestCase):
    def test_strata_json_document(self):
        result = run_cli("strata", "plot", "examples/layers.csv", "--json")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "strata plot")
        self.assertEqual(len(payload["layers"]), 6)
        self.assertAlmostEqual(payload["total_thickness_m"], 10.1)
        self.assertIn("depth_from_base_m", payload["layers"][0])

    def test_key_json_document(self):
        result = run_cli("key", "generate", "examples/taxa.csv", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "key generate")
        self.assertTrue(payload["couplets"])
        self.assertEqual(payload["unresolved"], [])
        self.assertEqual(payload["couplets"][0]["number"], "1")

    def test_grid_json_document(self):
        result = run_cli("grid", "plot", "examples/finds.csv", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "grid plot")
        self.assertEqual(payload["grid"]["width"], 10)
        self.assertTrue(payload["cells"])
        self.assertTrue(payload["legend"])

    def test_convert_json_document(self):
        result = run_cli(
            "grid", "convert", "--origin-lat", "52.0", "--origin-lon", "4.0", "--distance", "0", "0", "3", "4", "--json"
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "grid convert")
        self.assertEqual(payload["result"]["units"], "m")
        self.assertAlmostEqual(payload["result"]["distance"], 5.0)

    def test_json_mode_keeps_data_errors_on_stderr(self):
        path = self.write("layers.csv", "name,thickness_m\nBed,thick\n")
        result = run_cli("strata", "plot", path, "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("thickness_m", result.stderr)


# ------------------------------------------------------------------- example

class TestShippedExamples(unittest.TestCase):
    def test_every_documented_example_command_succeeds(self):
        commands = (
            ("strata", "plot", "examples/layers.csv", "--scale", "2"),
            ("strata", "plot", "examples/layers.json"),
            ("key", "generate", "examples/taxa.csv", "--title", "Ordovician fauna"),
            ("grid", "plot", "examples/finds.csv"),
            ("grid", "plot", "examples/finds.json"),
            ("grid", "convert", "--file", "examples/finds.json", "--to-latlon", "3", "4"),
        )
        for command in commands:
            result = run_cli(*command)
            self.assertEqual(result.returncode, 0, msg="%r failed: %s" % (command, result.stderr))
            self.assertTrue(result.stdout.strip())

    def test_examples_are_generous_enough_for_a_useful_first_paint(self):
        layers = run_cli("strata", "plot", "examples/layers.csv", "--width", "40").stdout
        self.assertGreaterEqual(len(layers.splitlines()), 30)
        key = run_cli("key", "generate", "examples/taxa.csv").stdout
        self.assertGreaterEqual(len(key.splitlines()), 6)
        grid = run_cli("grid", "plot", "examples/finds.csv").stdout
        self.assertIn("12 finds in 9 occupied square(s)", grid)


if __name__ == "__main__":
    unittest.main()
