#!/usr/bin/env bash
# uninstall_launchd.sh — Boot out and remove launchd agents (modern macOS).
#
# Uses `launchctl bootout` (the counterpart to bootstrap). Does NOT delete
# logs, DB data, or project files.

set -euo pipefail

LAUNCHD_AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

LABELS=(
    "com.polymarket-ai.backend"
    "com.polymarket-ai.daily-experiment"
)

echo "Uninstalling Polymarket AI Desk launchd agents (domain $DOMAIN)..."
echo ""

for LABEL in "${LABELS[@]}"; do
    PLIST="$LAUNCHD_AGENTS/$LABEL.plist"

    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null \
        && echo "  Booted out: $LABEL" \
        || echo "  (not loaded: $LABEL)"

    if [[ -f "$PLIST" ]]; then
        rm -f "$PLIST"
        echo "  Removed:    $PLIST"
    fi
done

echo ""
echo "Done. Both agents are removed. Logs preserved in logs/."
