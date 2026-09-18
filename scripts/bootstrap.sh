#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
    if [ ! -d .venv ]; then uv venv --python 3.13 .venv; fi
    uv pip install --python .venv/bin/python -e '.[cadquery,dev]'
else
    PYTHON=${PYTHON:-python3}
    "$PYTHON" -c 'import sys; assert (3,12) <= sys.version_info[:2] < (3,14), "Use Python 3.12 or 3.13"'
    if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
    .venv/bin/python -m pip install -e '.[cadquery,dev]'
fi
.venv/bin/cadloop doctor
printf '\nRun: .venv/bin/cadloop demo --directory ./work/plate-stack --trusted-native\n'
