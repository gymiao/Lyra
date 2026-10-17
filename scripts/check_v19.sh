#!/usr/bin/env bash
# Local CI entrypoint: independent environment and isolated artifacts, no broker.
set -eu
cd "$(dirname "$0")/.."
LYRAX_PYTHON="${LYRAX_PYTHON:-python}"
exec "$LYRAX_PYTHON" scripts/check_v19.py "$@"
