#!/bin/sh
set -e

# .venv lives in a named volume, so it starts empty regardless of what the
# image built at /app/.venv - re-sync on every start (uv cache makes this fast).
uv sync
exec uv run "$@"
