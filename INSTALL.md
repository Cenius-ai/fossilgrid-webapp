# Installing and running FossilGrid

FossilGrid is a plain-Python command line tool. There is no server, no database and no service to
start: installing it means putting one file where you want it and running it with `python3`.

## Prerequisites (installed by you, never by the installer)

| Requirement | Version | Why |
| --- | --- | --- |
| Python | **3.9 or newer** (tested on 3.11) | the tool is standard library only |

Nothing else: no compilers, no system libraries, no `sqlite3-dev`, no `pip` packages, no network
access at any point.

## The one package manager

The only dependency manifest in this project is `requirements.txt`, so **pip** is the package
manager to use:

```sh
python3 -m pip install -r requirements.txt
```

That file is deliberately a complete no-op (documentation only) because FossilGrid has **zero**
third-party dependencies — do not reach for poetry, pipenv, conda or pyenv.

This is a single root project: there is no `backend/` + `client/` split, so there is exactly one
place to install from, the repository root.

## Setup, step by step (all unprivileged, no sudo anywhere)

### 1. Install the project (dependencies → console script → self-check), then it exits

```sh
bash install.sh
```

`install.sh` does four things and then **stops**:

1. prints the interpreter version;
2. refreshes `pip`/`setuptools`/`wheel` if it can (offline machines keep what they have);
3. installs the project dependencies with `pip install -r requirements.txt` and installs the
   project itself in editable mode, which puts the `fossilgrid` console script on `PATH`
   (retrying with `--user` if site-packages is not writable);
4. runs a cheap self-check (`import fossilgrid`, `--version`) so a broken install fails here rather
   than at first use.

It never calls `sudo`, `apt-get`, `apk`, `yum`, `brew` or `systemctl`, never installs or starts a
system service, and never leaves a background process behind. It exits `0` on success and non-zero
on failure.

### 2. There is no migrate step and no seed step

FossilGrid keeps **no datastore**: it reads the CSV or JSON file you name on the command line and
writes text to stdout. There is therefore nothing to migrate and nothing to seed. The demo data is
the shipped, committed `examples/` directory:

```
examples/layers.csv     examples/layers.json     measured section (top to bottom)
examples/taxa.csv       examples/taxa.json       taxon × trait matrix
examples/finds.csv      examples/finds.json      site finds, plus origin/grid metadata
```

If you would rather not run the installer at all, skip to step 3 — the tool has no install
requirement.

### 3. Run it

```sh
python3 fossilgrid.py --help
python3 fossilgrid.py strata plot examples/layers.csv --width 40
python3 fossilgrid.py key generate examples/taxa.csv --title "Ordovician brachiopods"
python3 fossilgrid.py grid plot examples/finds.csv
python3 fossilgrid.py grid convert --file examples/finds.json --to-latlon 3 4
```

Or use the console script installed in step 1:

```sh
fossilgrid grid plot examples/finds.csv
```

### 4. See the whole tool work (optional)

```sh
bash demo.sh        # every command against the shipped example data, non-interactive
```

### 5. Run the test suite (optional, development only)

```sh
python3 -m unittest test_fossilgrid       # standard library runner, no dependencies
python3 -m pytest -q test_fossilgrid.py   # same suite through pytest, if you have it
```

`test_fossilgrid.py` is development-only: delete it and every command still works.

## Installed layout

```
fossilgrid.py            the entire shipped tool (standard library only)
pyproject.toml           packaging metadata for the optional console script
requirements.txt         documents that there are no dependencies
install.sh               deps + console script + self-check, then exits
demo.sh                  end-to-end non-interactive demonstration
examples/                the committed demo datasets
test_fossilgrid.py       development tests (unittest)
README.md USAGE.md INSTALL.md
```

## Configuration

There are no config files, no environment variables to set and no secrets. The only environment
variable FossilGrid reads at all is the conventional `COLUMNS`, which many terminals export, to
decide how wide the stratigraphic column may be; when it is absent the real terminal size is used
and 80 columns is the fallback. Nothing about the tool requires any of them.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `python3: command not found` | install Python 3.9+; on some systems the binary is `python3.11` — run `PYTHON=python3.11 bash install.sh` and use that name for the tool too |
| `unsupported input format '.txt'` | only `.csv` and `.json` inputs are accepted; rename the file or convert it |
| `error: ... invalid choice: 'plot'` | `plot` is a subcommand: `fossilgrid strata plot FILE`, not `fossilgrid plot` |
| Labels look truncated | the label column is 24 characters by default; pass `--width 40` (or wider) |
| The column is narrower than 12 characters | the terminal (or `COLUMNS`) is narrow; one line on stderr names the width used — widen the terminal or set `COLUMNS` |
| A data error names a row and field, exit code `1` | read the message: it is `<file>:<row>: <field>: <problem>`; stdout is untouched so scripts fail cleanly |
| `pip install -e .` fails while offline | the tool needs no install; keep using `python3 fossilgrid.py` directly |

## Uninstalling

FossilGrid has no service, no datastore and no state:

```sh
python3 -m pip uninstall fossilgrid     # only if you ran install.sh
rm -rf /path/to/fossilgrid
```
