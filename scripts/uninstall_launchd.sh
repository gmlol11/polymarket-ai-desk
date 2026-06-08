#!/usr/bin/env bash
# uninstall_launchd.sh — Unload and remove launchd agents.
#
# Stops both services and removes their plist files from ~/Library/LaunchAgents/.
# Does NOT delete logs, DB data, or project files.

set -euo pipefail

LAUNCHD_AGENTS="$HOME/Library/LaunchAgents"

LABELS=(
    "com.polymarket-ai.backend"
    "com.polymarket-ai.daily-experiment"
)

echo "Uninstalling Polymarket AI Desk launchd agents..."
echo ""

for LABEL in "${LABELS[@]}"; do
    PLIST="$LAUNCHD_AGENTS/$LABEL.plist"
    if [[ -f "$PLIST" ]]; then
        launchctl unload "$PLIST" 2>&1 && echo "  Unloaded: $LABEL" || \
            echo "  WARN: unload failed for $LABEL (was it loaded?)"
        rm -f "$PLIST"
        echo "  Removed:  $PLIST"
    else
        echo "  Skipped:  $PLIST (not found)"
    fi
done

echo ""
echo "Done. Both agents are removed."
echo "Logs remain in the project's logs/ directory."
