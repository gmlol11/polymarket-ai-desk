#!/usr/bin/env bash
# install_launchd.sh — Install and load both launchd agents.
#
# What it does:
#   1. Copies plist templates from launchd/ to ~/Library/LaunchAgents/
#   2. Replaces __PROJECT_PATH__ placeholder with the actual project path
#   3. Loads both agents (backend keep-alive + daily 10:00 experiment)
#
# Run only once. To update: uninstall_launchd.sh + install_launchd.sh.
# Neither script modifies .env or touches API keys.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCHD_AGENTS="$HOME/Library/LaunchAgents"
TEMPLATE_DIR="$PROJECT_DIR/launchd"
LOG_DIR="$PROJECT_DIR/logs"

echo "Project directory: $PROJECT_DIR"
echo "LaunchAgents dir : $LAUNCHD_AGENTS"
echo ""

mkdir -p "$LAUNCHD_AGENTS" "$LOG_DIR"
chmod +x "$PROJECT_DIR/scripts/start_backend.sh"
chmod +x "$PROJECT_DIR/scripts/run_experiment_once.sh"

install_plist() {
    local TEMPLATE="$1"
    local NAME
    NAME="$(basename "$TEMPLATE")"
    local TARGET="$LAUNCHD_AGENTS/$NAME"

    sed "s|__PROJECT_PATH__|$PROJECT_DIR|g" "$TEMPLATE" > "$TARGET"
    echo "  Installed: $TARGET"

    launchctl load "$TARGET" 2>&1 && echo "  Loaded:    $NAME" || \
        echo "  WARN: launchctl load failed for $NAME (already loaded?)"
}

echo "Installing plist files..."
for TEMPLATE in "$TEMPLATE_DIR"/*.plist; do
    install_plist "$TEMPLATE"
done

echo ""
echo "Done."
echo ""
echo "Backend will start automatically on login (KeepAlive=true)."
echo "Experiment will run daily at 10:00 local time."
echo ""
echo "Check status:"
echo "  launchctl list | grep polymarket"
echo ""
echo "Check logs:"
echo "  tail -f $LOG_DIR/backend_stderr.log"
echo "  tail -f $LOG_DIR/daily_stdout.log"
