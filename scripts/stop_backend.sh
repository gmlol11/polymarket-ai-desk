#!/usr/bin/env bash
# stop_backend.sh — Stop whatever process is serving the backend on port 8000.
#
# Use this to free the port before handing the backend over to launchd, or to
# kill a stale manual uvicorn that is still running old code.

set -euo pipefail

PORT="${BACKEND_PORT:-8000}"

PIDS="$(lsof -ti ":$PORT" 2>/dev/null || true)"

if [[ -z "$PIDS" ]]; then
    echo "Nothing listening on port $PORT."
    exit 0
fi

echo "Stopping process(es) on port $PORT: $PIDS"
# shellcheck disable=SC2086
kill $PIDS 2>/dev/null || true
sleep 1

# Force-kill any survivors
PIDS="$(lsof -ti ":$PORT" 2>/dev/null || true)"
if [[ -n "$PIDS" ]]; then
    echo "Force-killing: $PIDS"
    # shellcheck disable=SC2086
    kill -9 $PIDS 2>/dev/null || true
fi

echo "Port $PORT is free."
