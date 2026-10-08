#!/usr/bin/env bash
# FossilGrid installer: project-level dependencies, the console script, and a self-check.
# Runs unprivileged, installs no system packages, never starts a server, and exits.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" > /dev/null 2>&1; then
  echo "error: '$PYTHON' was not found on PATH; install Python 3.9+ first (see INSTALL.md)" >&2
  exit 1
fi

echo "1/4  python: $("$PYTHON" --version 2>&1)"

# Refresh the packaging tooling so editable installs work on older pip versions.
# Offline machines keep their existing tooling; that is not a failure.
if ! "$PYTHON" -m pip install --upgrade pip setuptools wheel > /dev/null 2>&1; then
  echo "note: could not refresh pip/setuptools/wheel (offline?); continuing with the installed versions" >&2
fi

echo "2/4  project dependencies (FossilGrid is standard library only)"
"$PYTHON" -m pip install -r requirements.txt

echo "3/4  console script 'fossilgrid'"
if ! "$PYTHON" -m pip install --no-build-isolation -e . > /dev/null; then
  echo "note: retrying the editable install for the current user" >&2
  "$PYTHON" -m pip install --no-build-isolation --user -e .
fi

echo "4/4  self-check"
"$PYTHON" -c "import fossilgrid; print('fossilgrid', fossilgrid.VERSION, 'imports cleanly')"
"$PYTHON" fossilgrid.py --version

cat <<'EOF'

Setup complete. Nothing was started -- FossilGrid is a command line tool.
Run it:
  python3 fossilgrid.py strata plot examples/layers.csv
  python3 fossilgrid.py --help
Or, with the console script on PATH:
  fossilgrid grid plot examples/finds.csv
Full demo:
  bash demo.sh
Tests:
  python3 -m unittest test_fossilgrid
EOF
