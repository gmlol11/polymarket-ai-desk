#!/usr/bin/env bash
# run_experiment_once.sh — Trigger one experiment cycle with Telegram notification.
# Called daily by launchd. Can also be run manually.
#
# Self-healing: if the backend doesn't answer /health (e.g. the long-lived
# process got throttled after system sleep), it is kickstarted via launchd and
# the check is retried. If the cycle still fails, a short alert is sent to
# Telegram directly via the Bot API so that silence always means "machine off",
# never "silent failure". Secrets are read from .env, never printed.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/experiment_${TIMESTAMP}.log"
BACKEND_URL="http://127.0.0.1:8000"
BACKEND_LABEL="com.polymarket-ai.backend"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

# Read Telegram credentials from .env without printing them.
TG_TOKEN="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$PROJECT_DIR/.env" 2>/dev/null | tail -1)"
TG_CHAT="$(sed -n 's/^TELEGRAM_CHAT_ID=//p' "$PROJECT_DIR/.env" 2>/dev/null | tail -1)"

send_alert() {
    # Best-effort failure alert; never breaks the script itself.
    if [[ -z "$TG_TOKEN" || -z "$TG_CHAT" ]]; then
        return 0
    fi
    curl -s --max-time 10 -X POST \
        "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TG_CHAT}" \
        --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

backend_healthy() {
    curl -sf --max-time 5 "$BACKEND_URL/health" >/dev/null 2>&1
}

log "Starting experiment cycle (notify=true)..."
log "Project: $PROJECT_DIR"

# Pre-flight: make sure the backend actually answers before the long request.
if ! backend_healthy; then
    log "Backend not responding — kickstarting $BACKEND_LABEL..."
    launchctl kickstart -k "gui/$(id -u)/$BACKEND_LABEL" >>"$LOG_FILE" 2>&1 || true
    sleep 15
    if ! backend_healthy; then
        log "ERROR: backend still not responding after kickstart"
        send_alert "⚠️ Polymarket AI Desk: daily cycle SKIPPED — backend not responding even after restart ($(date '+%Y-%m-%d %H:%M'))."
        exit 1
    fi
    log "Backend recovered after kickstart."
fi

set +e
RESPONSE="$(curl -sf -X POST "$BACKEND_URL/jobs/run-once-notify" \
    -H "Content-Type: application/json" \
    --connect-timeout 10 \
    --max-time 900 \
    2>>"$LOG_FILE")"
CURL_EXIT=$?
set -e

if [[ $CURL_EXIT -ne 0 ]]; then
    log "ERROR: cycle request failed (curl exit $CURL_EXIT)"
    send_alert "⚠️ Polymarket AI Desk: daily cycle FAILED (curl exit $CURL_EXIT) at $(date '+%Y-%m-%d %H:%M'). See logs/experiment_${TIMESTAMP}.log"
    exit 1
fi

echo "$RESPONSE" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
log "Done. Log: $LOG_FILE"
