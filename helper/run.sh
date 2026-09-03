#!/usr/bin/env bash
# Start the helper. Creates the venv on first run, repairs it when the system
# Python moved (a Homebrew upgrade breaks venv symlinks), and reinstalls deps
# when requirements.txt changed since the last install.
#
#   ./run.sh               start the helper in the foreground
#   ./run.sh --setup-only  prepare the venv and exit (used by install.sh)
set -e
cd "$(dirname "$0")"

PY=./.venv/bin/python
STAMP=.venv/.requirements.sha256

req_hash() {
  python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' requirements.txt
}

if [ -d .venv ] && ! "$PY" -c 'import sys' >/dev/null 2>&1; then
  echo "helper/.venv no longer runs (system Python changed). Recreating it." >&2
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
  "$PY" -m pip install --disable-pip-version-check -q --upgrade pip
fi

if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$(req_hash)" ]; then
  echo "Installing Python dependencies..." >&2
  "$PY" -m pip install --disable-pip-version-check -q -r requirements.txt
  req_hash > "$STAMP"
fi

if [ "${1:-}" = "--setup-only" ]; then
  exit 0
fi

exec "$PY" main.py
