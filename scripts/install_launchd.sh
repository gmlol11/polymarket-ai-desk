#!/usr/bin/env bash
# install_launchd.sh — Install and load both launchd agents (modern macOS).
#
# Uses `launchctl bootstrap` (Ventura/Sonoma/Sequoia) instead of the legacy
# `launchctl load`, which fails with "Input/output error" on recent macOS.
#
# What it does:
#   1. Copies plist templates to ~/Library/LaunchAgents/ with __PROJECT_PATH__
#      replaced by the real project path
#   2. Boots out any previous instance, then bootstraps + enables each agent
#
# IMPORTANT: the backend agent binds port 8000. Stop any manually-started
# uvicorn first (see scripts/stop_backend.sh) or bootstrap will crash-loop.
#
# Neither this script nor uninstall touches .env or API keys.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHD_AGENTS="$HOME/Library/LaunchAgents"
TEMPLATE_DIR="$PROJECT_DIR/launchd"
LOG_DIR="$PROJECT_DIR/logs"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

echo "Project directory: $PROJECT_DIR"
echo "LaunchAgents dir : $LAUNCHD_AGENTS"
echo "launchd domain   : $DOMAIN"
echo ""

mkdir -p "$LAUNCHD_AGENTS" "$LOG_DIR"
chmod +x "$PROJECT_DIR/scripts/start_backend.sh"
chmod +x "$PROJECT_DIR/scripts/run_experiment_once.sh"

# Warn if port 8000 is already taken (a manual uvicorn would block the agent).
if lsof -ti :8000 >/dev/null 2>&1; then
    echo "WARNING: port 8000 is already in use."
    echo "         Stop the existing backend first:  bash scripts/stop_backend.sh"
    echo ""
fi

install_plist() {
    local TEMPLATE="$1"
    local NAME LABEL TARGET
    NAME="$(basename "$TEMPLATE")"
    LABEL="${NAME%.plist}"
    TARGET="$LAUNCHD_AGENTS/$NAME"

    sed "s|__PROJECT_PATH__|$PROJECT_DIR|g" "$TEMPLATE" > "$TARGET"
    echo "  Installed: $TARGET"

    # Remove any prior instance (ignore errors if not loaded).
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

    if launchctl bootstrap "$DOMAIN" "$TARGET" 2>/tmp/launchd_err.$$; then
        launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
        echo "  Bootstrapped + enabled: $LABEL"
    else
        echo "  ERROR: bootstrap failed for $LABEL:"
        sed 's/^/    /' "/tmp/launchd_err.$$"
    fi
    rm -f "/tmp/launchd_err.$$"
}

echo "Installing plist files..."
for TEMPLATE in "$TEMPLATE_DIR"/*.plist; do
    install_plist "$TEMPLATE"
done

echo ""
echo "Done."
echo ""
echo "Verify:"
echo "  launchctl list | grep polymarket"
echo "  curl -s http://127.0.0.1:8000/jobs/status | python3 -m json.tool"
echo ""
echo "Manually fire the daily job once (without waiting for 10:00):"
echo "  launchctl kickstart -k $DOMAIN/com.polymarket-ai.daily-experiment"
echo ""
echo "Logs:"
echo "  tail -f $LOG_DIR/backend_stderr.log"
echo "  tail -f $LOG_DIR/daily_stdout.log"
