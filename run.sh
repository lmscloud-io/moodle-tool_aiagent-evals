#!/usr/bin/env bash
# Local entry point, e.g.: ./run.sh run --tier compat --moodle 502 --cells 'openai-*' --tasks plain-reply
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/aiagent-evals ]; then
    # uv when available; python3.11's own venv needs the python3.11-venv package on Debian and Ubuntu.
    if command -v uv > /dev/null 2>&1; then
        uv venv .venv --python python3.11
        uv pip install --python .venv/bin/python -e '.[dev]'
    else
        python3.11 -m venv .venv
        .venv/bin/pip install -e '.[dev]'
    fi
fi
exec .venv/bin/aiagent-evals "$@"
