#!/usr/bin/env bash
# run_experiment_once.sh — Trigger one experiment cycle with Telegram notification.
# Called daily by launchd. Can also be run manually.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/experiment_${TIMESTAMP}.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "Starting experiment cycle (notify=true)..."
log "Project: $PROJECT_DIR"

RESPONSE="$(curl -sf -X POST "http://127.0.0.1:8000/jobs/run-once-notify" \
    -H "Content-Type: application/json" \
    --connect-timeout 10 \
    --max-time 600 \
    2>>"$LOG_FILE")" || {
    log "ERROR: curl failed (is the backend running?)"
    exit 1
}

echo "$RESPONSE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
log "Done. Log: $LOG_FILE"
